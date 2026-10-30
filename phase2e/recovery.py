"""Controlled, disclosed recovery for the observed linear Gerber region subset.

Original bytes never change. Exact zero-length G01 region segments can be omitted
in a separately recorded derived model; uncertain closing edges remain candidates.
"""
from __future__ import annotations
import hashlib,json,math,sys,platform,zipfile
from collections import Counter,defaultdict
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from importlib.metadata import version

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'phase2b/.venv/Lib/site-packages'))
sys.path.insert(0,str(ROOT/'phase2d'))
sys.path.insert(0,str(ROOT/'phase2c'))
import forensics as d
import verify_phase2c as c
from shapely import union_all
from shapely.geometry import Polygon,LineString,mapping
from shapely.affinity import scale
from gerbonara import GerberFile
from pygerber.gerberx3.api.v2 import GerberFile as PG

OUT=ROOT/'phase2e/results'
FIX=ROOT/'phase2a/fixtures/extracted'
BOARDS=('gerber-pcb-valentine-feb-new','gerber-prickly-laser-module-2-5')
SCALE=d.SCALE
POLICY='pcbprep.exact-zero-length-region-draw.v1'
SPEC='https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf'
LEGACY_SPEC='https://www.ucamco.com/files/downloads/file_en/416/the-gerber-layer-format-specification-revision-2021-02_en.pdf'

def sha(data):return hashlib.sha256(data).hexdigest()
def decimal_mm(ticks):return str(Decimal(ticks)/SCALE)
def mm(g):return scale(g,xfact=1/SCALE,yfact=1/SCALE,origin=(0,0))
def metrics(g):
    ps=[g] if g.geom_type=='Polygon' and not g.is_empty else list(g.geoms) if g.geom_type=='MultiPolygon' else []
    return {'areaMm2':g.area,'components':len(ps),'interiorVoids':sum(len(p.interiors) for p in ps),'valid':bool(g.is_valid),'boundsMm':list(g.bounds) if not g.is_empty else None}

def candidate_digest(validation,candidate):
    return sha(json.dumps({'sourceSha256':validation['sourceSha256'],'sourceCommandRange':validation['sourceCommandRange'],
        'edgeTicks':candidate['edgeTicks'],'geometry':candidate.get('geometry'),'exactCandidateAreaMm2':candidate.get('exactCandidateAreaMm2')},sort_keys=True).encode())

def normalize_exact_noops(record,*,enabled):
    """Only G01/D01 zero-length segments in regions; never change other commands."""
    if not enabled: return record,[]
    changes=[];contours=[]
    for contour in record['contours']:
        pts=contour['points'];keep=[pts[0]];lines=[]
        for index,(a,b,line) in enumerate(zip(pts,pts[1:],contour['segmentLines'])):
            command=next(x for x in record['commands'] if x['line']==line)
            if a==b and command['operation']=='D01' and command['mode']=='G01':
                changes.append({'action':'OMIT_EXACT_ZERO_LENGTH_REGION_SEGMENT_FROM_DERIVED_MODEL',
                    'sourceLine':line,'segmentIndex':index,'originalCommand':command['raw'],'pointTicks':a,
                    'proof':'Start equals end in original integer source coordinates; no contour edge or enclosed area is changed.'})
            else:keep.append(b);lines.append(line)
        contours.append({'points':keep,'segmentLines':lines})
    return {**record,'contours':contours},changes

def classify_region(record,board,source_sha,index):
    normalized,changes=normalize_exact_noops(record,enabled=True)
    identity=f'{board}:Gerber_BottomLayer.GBL:region:{index}'
    base={'recordVersion':'0.1','id':identity,'boardId':board,'sourceFile':'Gerber_BottomLayer.GBL','sourceSha256':source_sha,
        'sourceCommandRange':{'firstLine':record['g36Line'],'lastLine':record['g37Line']},
        'specificationRevision':'2026.05','originalGeometry':{'units':'source_ticks','tickMm':'0.00001','contours':record['contours'],
            'commands':record['commands'],'filledAreaMm2':None},
        'proposedChanges':changes,'recoveryPolicyId':POLICY if changes else None,
        'proposedRecoveryGeometry':None,'sourceToRecoveryAreaDeltaMm2':None,'sourceToRecoveryTopologyDelta':None,
        'acceptance':{'manualAcceptance':None,'independentDesignIntentEvidence':None,'unresolvedRisk':False}}
    try:
        if any(x['operation']=='D01' and x['mode']!='G01' for x in record['commands']):
            raise ValueError('UNSUPPORTED_REGION_INTERPOLATION')
        shape=mm(d.region_geometry_ticks(normalized))
        base.update(status='RECOVERABLE' if changes else 'VALID',severity='warning' if changes else 'info',
            issueClassification='EXACT_ZERO_LENGTH_REGION_DRAW' if changes else 'CONFORMING_LINEAR_REGION',
            sourceConforms202605=not bool(changes),recoveryConfidence='EXACT_NON_MATERIAL' if changes else 'CONFORMING',
            proposedRecoveryGeometry={'format':'GeoJSON','geometry':mapping(shape),'units':'mm','metrics':metrics(shape)},
            derivedNormalizationApplied=bool(changes),manufacturingEligibility={'geometryEligible':True,'readyForMachining':False,
                'basis':'Verified derived geometry with disclosed exact no-op normalization' if changes else 'Validated original geometry'},
            requiredUserAction='Review the disclosed normalization record; no copper-boundary choice is required.' if changes else 'None for source-region validation.',
            supportingEvidence=[{'type':'exact_integer_source_predicate','result':'No moved coordinates, no inserted edge, exact zero-length G01 segments only'},
                {'type':'gerber_region_validation','result':'Normalized contour passes strict simple/cut-in validation'},
                {'type':'versioned_specification','revision':'2021.02','url':LEGACY_SPEC,'result':'Historic reader guidance explicitly allowed removing zero-length contour segments'}])
        if changes:
            base['sourceToRecoveryAreaDeltaMm2']=0
            base['sourceToRecoveryTopologyDelta']={'materialComponents':0,'interiorVoids':0,'basis':'Exact removal of zero-length path edges, not comparison with an undefined invalid polygon fill'}
        return base,shape
    except ValueError as exc:
        base.update(status='BLOCKED',severity='error',issueClassification=str(exc),sourceConforms202605=False,
            recoveryConfidence='INTENT_UNPROVEN',derivedNormalizationApplied=False,
            manufacturingEligibility={'geometryEligible':False,'readyForMachining':False,'basis':'Intended material is not established'},
            supportingEvidence=[{'type':'strict_region_validation','result':str(exc)}],
            requiredUserAction='Obtain matching native EasyEDA revision/fill evidence or explicitly accept the identified candidate and unresolved risk.')
        base['acceptance']['unresolvedRisk']=True
        return base,None

def closure_candidate(record):
    pts=record['contours'][0]['points'];start,end=pts[0],pts[-1]
    delta=[start[i]-end[i] for i in (0,1)]
    hits=[]
    for i,(a,b) in enumerate(zip(pts,pts[1:])):
        hit=d.exact_intersection(tuple(end),tuple(start),tuple(a),tuple(b))
        if hit:
            kind,points=hit
            expected=(i==0 or i==len(pts)-2) and kind=='endpoint'
            hits.append({'sourceSegmentIndex':i,'sourceLine':record['contours'][0]['segmentLines'][i],
                'type':kind,'pointsTicks':[[str(x) for x in p] for p in points],'expectedAdjacentEndpoint':expected})
    candidate={'type':'STRAIGHT_CLOSING_EDGE_DIAGNOSTIC_ONLY','edgeTicks':[end,start],
        'startMm':[decimal_mm(v) for v in start],'endMm':[decimal_mm(v) for v in end],
        'endMinusStartMm':[decimal_mm(end[i]-start[i]) for i in (0,1)],
        'proposedEdgeDisplacementMm':[decimal_mm(v) for v in delta],
        'gapLengthSquaredMm2':str(Fraction(sum(v*v for v in delta),SCALE*SCALE)),
        'gapLengthMm':math.hypot(*delta)/SCALE,'edgeIntersections':hits,
        'unexpectedIntersectionCount':sum(not h['expectedAdjacentEndpoint'] for h in hits),
        'candidatePolygonValid':False,'manufacturingIntentProven':False,'metrics':None}
    closed=pts+[start]
    try:
        g=mm(d.cutin_geometry(closed,d.analyze(closed)))
        candidate.update(candidatePolygonValid=True,geometry={'format':'GeoJSON','units':'mm','geometry':mapping(g)},metrics=metrics(g))
        # Shoelace is exact on original source ticks, after the explicitly proposed edge.
        twice=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(closed,closed[1:]))
        candidate['exactCandidateAreaMm2']=str(Fraction(abs(twice),2*SCALE*SCALE))
        return candidate,g
    except ValueError as exc:
        candidate['candidateValidationFailure']=str(exc)
        return candidate,None

def manual_candidate_permission(validation,candidate,acceptance):
    """An explicit exception never converts unproven design intent to VALID."""
    required={'sourceSha256','candidateSha256','reviewer','reason','acceptUnresolvedRisk'}
    ok=(acceptance is not None and required<=set(acceptance) and acceptance['sourceSha256']==validation['sourceSha256']
        and acceptance['candidateSha256']==candidate['candidateSha256']==candidate_digest(validation,candidate) and bool(acceptance['reviewer']) and bool(acceptance['reason'])
        and acceptance['acceptUnresolvedRisk'] is True and candidate['candidatePolygonValid'])
    return {'validationStatus':validation['status'],'candidateUsePermittedByException':bool(ok),
            'intendedGeometryVerified':False,'unresolvedRisk':True,'readyForMachining':False}

def parser_reproduction(path,source):
    out={}
    gb=[o for o in GerberFile.open(path).objects if type(o).__name__=='Region']
    pg=[c for c in PG.from_file(str(path)).parse()._command_buffer.commands if type(c).__name__=='Region2']
    def ticks(x):
        value=Decimal(str(x))*SCALE
        if value!=value.to_integral_value():raise ValueError('Parser coordinate not on original source tick grid')
        return int(value)
    arrays={'sourceScanner':[r['contours'][0]['points'] for r in source],
        'gerbonaraRawOutline':[[[ticks(x),ticks(y)] for x,y in o.outline] for o in gb],
        'pygerberCommands':[[[ticks(r.command_buffer.commands[0].start_point.x.value),ticks(r.command_buffer.commands[0].start_point.y.value)]]+
            [[ticks(c.end_point.x.value),ticks(c.end_point.y.value)] for c in r.command_buffer.commands] for r in pg]}
    for name,contours in arrays.items():
        zero=reverse=open_count=0
        for pts in contours:
            open_count+=pts[0]!=pts[-1]
            edges=Counter((tuple(a),tuple(b)) for a,b in zip(pts,pts[1:]) if a!=b)
            zero+=sum(a==b for a,b in zip(pts,pts[1:]))
            reverse+=sum(min(n,edges.get((b,a),0)) for (a,b),n in edges.items() if a<b)
        out[name]={'regions':len(contours),'openContours':open_count,'zeroLengthDraws':zero,'fullyCoincidentReversePairs':reverse,
            'allCoordinatesExactlyMatchSource':contours==arrays['sourceScanner']}
    return out

def overlay_svg(path,pts,edge):
    # Diagnostic document, not an application UI. Source paths remain blue; proposal is red.
    xs=[p[0]/SCALE for p in pts];ys=[p[1]/SCALE for p in pts];lo,hi=min(xs),max(xs);bot,top=min(ys),max(ys)
    margin=max(0.01,max(hi-lo,top-bot)*0.05);width=hi-lo+margin*2;height=top-bot+margin*2
    points=' '.join(f'{x/SCALE},{-y/SCALE}' for x,y in pts)
    a,b=edge;stroke=max(width,height)/350
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="700" viewBox="{lo-margin} {-top-margin} {width} {height}"><title>Blue original open contour; red proposed edge, unapproved. Coordinates mm; Y displayed upward.</title><rect x="{lo-margin}" y="{-top-margin}" width="{width}" height="{height}" fill="white"/><polyline points="{points}" fill="none" stroke="#1761a5" stroke-width="{stroke}"/><line x1="{a[0]/SCALE}" y1="{-a[1]/SCALE}" x2="{b[0]/SCALE}" y2="{-b[1]/SCALE}" stroke="#d32620" stroke-width="{stroke*1.4}" stroke-dasharray="{stroke*5} {stroke*3}"/></svg>',encoding='utf-8')

def run():
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'overlays').mkdir(exist_ok=True)
    records=[];reproduction={};copper=[];provenance=[];laser_shapes=[];laser_extra=None
    golden=json.loads((ROOT/'phase2c/results/copper-comparison.json').read_text())
    for board in BOARDS:
        path=FIX/board/'Gerber_BottomLayer.GBL';original=path.read_bytes();text=original.decode();source=d.scan(text)
        reproduction[board]=parser_reproduction(path,source)
        parsed=PG.from_file(str(path)).parse()._command_buffer.commands
        pregions=[x for x in parsed if type(x).__name__=='Region2']
        provenance.append({'boardId':board,'bottomSourceSha256':sha(original),'headerComments':[x for x in text.splitlines()[:10] if x.startswith('G04')],
            'projectRevisionMatch':'NOT_VERIFIED_NATIVE_PROJECT_NOT_STAGED'})
        shapes=[]
        for i,raw in enumerate(source):
            rec,g=classify_region(raw,board,sha(original),i)
            rec['polarity']=pregions[i].transform.polarity.value
            rec['sourceRangeSha256']=sha('\n'.join(text.splitlines()[raw['g36Line']-1:raw['g37Line']]).encode())
            if board==BOARDS[1]:
                candidate,cg=closure_candidate(raw)
                candidate['candidateSha256']=candidate_digest(rec,candidate)
                rec['proposedChanges']=[{'action':'PROPOSE_MISSING_STRAIGHT_EDGE','applied':False,'edgeTicks':candidate['edgeTicks'],'insertionBeforeSourceLine':raw['g37Line']}]
                rec['proposedRecoveryGeometry']=candidate;g=cg;laser_shapes.append(cg)
                overlay=OUT/'overlays'/f'laser-region-{i:03d}.svg';overlay_svg(overlay,raw['contours'][0]['points'],candidate['edgeTicks'])
                rec['overlayPath']=str(overlay.relative_to(ROOT)).replace('\\','/')
                rec['areaTopologyDifferences']={'sourceFilledAreaMm2':None,'sourceToCandidateAreaDeltaMm2':None,
                    'sourceTopology':None,'candidateTopology':candidate['metrics'],
                    'reason':'An unclosed contour has no specified filled interior; a source-to-candidate material delta is undefined, not zero.'}
            else:
                normalized,changes=normalize_exact_noops(raw,enabled=True)
                noop_lines={p['sourceLine'] for p in changes}
                header='%FSLAX45Y45*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\nG01*\n'
                lines=text.splitlines()
                for suffix,omit in [('original',set()),('recovered',noop_lines)]:
                    body='\n'.join(lines[j-1] for j in range(raw['g36Line'],raw['g37Line']+1) if j not in omit)
                    target=ROOT/'phase2e/fixtures'/f'valentine-region-{i}.{suffix}.gbr';target.write_text(header+body+'\nM02*\n')
                rec['sourceSpecificFixtures']=[f'phase2e/fixtures/valentine-region-{i}.{kind}.gbr' for kind in ('original','recovered')]
                rec['supportingEvidence'].append({'type':'source_specific_regression_fixtures','paths':rec['sourceSpecificFixtures']})
            rec['supportingEvidence'].append({'type':'independent_parser_reproduction','path':'phase2e/results/independent-reproduction.json','boardId':board})
            records.append(rec);shapes.append(g)
        # Live remeasurement of four layer compositions. Laser bottom is candidate-only.
        for name in ('Gerber_TopLayer.GTL','Gerber_BottomLayer.GBL'):
            cmds=PG.from_file(str(FIX/board/name)).parse()._command_buffer.commands
            idx=0;events=[];extra=[]
            for command in cmds:
                if type(command).__name__=='Region2':shape=shapes[idx];idx+=1
                else:shape=c.command_shape(command);extra.append(shape)
                if shape is None:raise ValueError('No valid diagnostic candidate; full layer remeasurement unavailable')
                events.append((command.transform.polarity.value=='D',shape))
            composed=c.ordered_compose(events)
            prev=next(x for x in golden['files'] if x['boardId']==board and x['sourceFile']==name)['referenceMetrics']
            current=metrics(composed)
            copper.append({'boardId':board,'sourceFile':name,'mode':'UNAPPROVED_ALL_CLOSURES_CANDIDATE' if board==BOARDS[1] and name.endswith('GBL') else 'VERIFIED_EXACT_NOOP_RECOVERY' if board==BOARDS[0] and name.endswith('GBL') else 'VALID_SOURCE',
                'liveMetrics':current,'phase2cMetrics':prev,'areaDeltaMm2':current['areaMm2']-prev['areaMm2'],
                'componentsDelta':current['components']-prev['components'],'interiorVoidsDelta':current['interiorVoids']-prev['interiorVoids'],
                'maximumBoundsDeltaMm':max(abs(x-y) for x,y in zip(current['boundsMm'],prev['boundsMm']))})
            if board==BOARDS[1] and name.endswith('GBL'):laser_extra=union_all(extra);full=composed
            print('Remeasured',board,name,flush=True)
    # Marginal contribution of each proposed edge/region to the all-candidates layer.
    # Comparison omits one region, not a fabricated interpretation of the open source.
    laser_records=[r for r in records if r['boardId']==BOARDS[1]]
    dark=laser_shapes[0];clears=laser_shapes[1:];clear_union=union_all(clears)
    for i,rec in enumerate(laser_records):
        if i==0:without=laser_extra
        else:
            others=[p for j,p in enumerate(clears,1) if j!=i and p.intersects(laser_shapes[i])]
            patch=laser_shapes[i].intersection(dark).difference(union_all(others)).difference(laser_extra)
            without=full.union(patch)
        before,after=metrics(without),metrics(full)
        rec['areaTopologyDifferences']['marginalAllCandidatesScenario']={
            'basis':'All other 181 closures assumed; compare final layer with this region omitted to final layer with it included. Diagnostic scenario only.',
            'withoutThisCandidate':before,'withThisCandidate':after,
            'copperAreaDeltaMm2':after['areaMm2']-before['areaMm2'],
            'copperSymmetricDifferenceAreaMm2':without.symmetric_difference(full).area,
            'componentDelta':after['components']-before['components'],'interiorVoidDelta':after['interiorVoids']-before['interiorVoids']}
    result={'recordSchemaVersion':'0.1','recoveryPolicy':{'id':POLICY,'enabledForDerivedValidation':True,'originalBytesModified':False,
        'strictSourceConformanceStillReported':True,'autoCloseOpenContours':False,'toleranceMm':0,'makeValidUsed':False},
        'records':records,'counts':dict(Counter(r['status'] for r in records))}
    (OUT/'validation-records.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (OUT/'independent-reproduction.json').write_text(json.dumps(reproduction,indent=2)+'\n')
    (OUT/'copper-remeasurement.json').write_text(json.dumps(copper,indent=2)+'\n')
    (OUT/'export-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    eligibility=[]
    for board in BOARDS:
        selected=[r for r in records if r['boardId']==board]
        blocked=[r['id'] for r in selected if r['status']=='BLOCKED']
        eligibility.append({'boardId':board,'sourceRegionStatus':'BLOCKED' if blocked else 'RECOVERABLE',
            'geometryPreparationEligible':not bool(blocked),'wholeBoardRejectedSolelyForRedundantCommands':False,
            'blockingRegionIds':blocked,'recoverableRegionIds':[r['id'] for r in selected if r['status']=='RECOVERABLE'],
            'unaffectedGeometry':['top copper','board profile','drill and slot source records'],
            'readyForMachining':False,'separateOutstandingRequirements':['actual tool selection and unsupported nominal drill policy','manufacturing setup and physical side convention review']})
    (OUT/'manufacturing-eligibility.json').write_text(json.dumps(eligibility,indent=2)+'\n')
    print('Region statuses',result['counts']);print('Reproduction',reproduction)
    print('Live copper area deltas',[(x['boardId'],x['sourceFile'],x['areaDeltaMm2']) for x in copper])

if __name__=='__main__':run()
