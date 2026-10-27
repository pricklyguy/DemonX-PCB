"""Exact command evidence scanner for the observed absolute, linear X4.5 mm subset.

Not an independent reference parser: source evidence is compared to two library parsers.
No implicit closing edges or geometry repair is allowed in accepted geometry.
"""
import json, re, sys, hashlib
from collections import Counter, defaultdict
from fractions import Fraction as F
from decimal import Decimal
from pathlib import Path
from shapely import STRtree, union_all, make_valid
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize
from shapely.affinity import scale
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'phase2b/.venv/Lib/site-packages'))
from gerbonara import GerberFile
from pygerber.gerberx3.api.v2 import GerberFile as PG
sys.path.insert(0,str(ROOT/'phase2a'))
from verify_fixtures import primitive_to_geometry
OUT=ROOT/'phase2d/results'
SCALE=100000

def scan(text):
    if '%FSLAX45Y45*%' not in text or '%MOMM*%' not in text:
        raise ValueError('Scanner supports only declared absolute X4.5 mm')
    x=y=0; mode='G01'; active=None; results=[]; modal=None; polarity='dark'
    for m in re.finditer(r'[^*]+\*',text):
        raw=m.group().strip(' \r\n%'); c=raw.rstrip('*').strip('%\r\n ')
        line=text.count('\n',0,m.start()+len(m.group())-len(m.group().lstrip('\r\n% ')))+1
        if c.startswith('G04'): continue
        if c in ('LPD','LPC'):
            polarity='dark' if c=='LPD' else 'clear'
        if c=='G36':
            if active is not None: raise ValueError('nested region')
            active={'g36Line':line,'polarity':polarity,'commands':[],'contours':[]};modal=None;continue
        if c=='G37':
            if active is None: raise ValueError('G37 without G36')
            active['g37Line']=line;results.append(active);active=None;continue
        for g in re.findall(r'G0?[123](?!\d)',c): mode='G'+g[1:].zfill(2)
        ds=re.findall(r'D0?([123])(?!\d)',c)
        coords=re.findall(r'([XY])([+-]?\d+)',c)
        if ds: modal=int(ds[-1])
        if not coords and not ds:
            if active is not None and c not in ('G01','G02','G03'): raise ValueError('unhandled region command '+c)
            continue
        nx,ny=x,y
        for axis,value in coords:
            if axis=='X': nx=int(value)
            else: ny=int(value)
        if active is not None:
            if modal not in (1,2): raise ValueError('non D01/D02 region operation')
            rec={'line':line,'raw':raw,'operation':'D0'+str(modal),'mode':mode,'startTicks':[x,y],'endTicks':[nx,ny]}
            active['commands'].append(rec)
            if modal==2: active['contours'].append({'points':[[nx,ny]],'segmentLines':[]})
            else:
                if not active['contours']: active['contours'].append({'points':[[x,y]],'segmentLines':[]})
                active['contours'][-1]['points'].append([nx,ny]);active['contours'][-1]['segmentLines'].append(line)
                if mode!='G01': raise ValueError('curved region unsupported by forensic scanner')
        x,y=nx,ny
    if active is not None: raise ValueError('unterminated region')
    return results

def cross(a,b): return a[0]*b[1]-a[1]*b[0]
def sub(a,b): return (a[0]-b[0],a[1]-b[1])
def exact_intersection(a,b,c,d):
    r,s=sub(b,a),sub(d,c); den=cross(r,s); ca=sub(c,a)
    if den:
        t,u=F(cross(ca,s),den),F(cross(ca,r),den)
        if 0<=t<=1 and 0<=u<=1:
            p=(F(a[0])+t*r[0],F(a[1])+t*r[1])
            return ('endpoint' if t in (0,1) and u in (0,1) else 'cross_or_vertex_on_edge', [p])
        return None
    if cross(ca,r): return None
    common=sorted(set(p for p in (a,b,c,d) if min(a[0],b[0])<=p[0]<=max(a[0],b[0]) and min(a[1],b[1])<=p[1]<=max(a[1],b[1]) and min(c[0],d[0])<=p[0]<=max(c[0],d[0]) and min(c[1],d[1])<=p[1]<=max(c[1],d[1])))
    if not common:return None
    return ('overlap' if len(common)>1 else 'endpoint',common)

def winding(p,pts):
    w=0
    for a,b in zip(pts,pts[1:]):
        z=cross(sub(b,a),sub(p,a))
        if a[1]<=p[1]<b[1] and z>0:w+=1
        elif b[1]<=p[1]<a[1] and z<0:w-=1
    return w

def analyze(pts):
    pts=[tuple(p) for p in pts];segments=list(zip(pts,pts[1:]));n=len(segments)
    delta=sub(pts[-1],pts[0]); closed=delta==(0,0)
    tree=STRtree([LineString([a,b]) for a,b in segments]);issues=[];reverse=[]
    for i,(a,b) in enumerate(segments):
        if a==b: issues.append({'segments':[i],'type':'zero_length','pointsTicks':[a]})
        for jj in tree.query(LineString([a,b])):
            j=int(jj)
            if j<=i:continue
            c,d=segments[j];hit=exact_intersection(a,b,c,d)
            if not hit:continue
            typ,loc=hit
            if typ=='endpoint' and (j==i+1 or (closed and i==0 and j==n-1)):continue
            if a==d and b==c and a!=b:
                typ='full_reverse_horizontal' if a[1]==b[1] else ('full_reverse_vertical' if a[0]==b[0] else 'full_reverse_diagonal')
                reverse.append([i,j])
            issues.append({'segments':[i,j],'type':typ,'pointsTicks':[[str(v) for v in p] for p in loc]})
    return {'closedExactly':closed,'closureDeltaTicks':delta,'closureDeltaMm':[str(F(v,SCALE)) for v in delta],
            'segmentCount':n,'intersectionTypes':dict(Counter(i['type'] for i in issues)),'intersections':issues,'reversePairs':reverse}

def cutin_geometry(pts,analysis):
    """Accept only strictly validated simple linear rings or horizontal/vertical cut-ins."""
    if not analysis['closedExactly']: raise ValueError('OPEN_SOURCE_CONTOUR')
    forbidden={'zero_length','cross_or_vertex_on_edge','overlap','full_reverse_diagonal'}
    if any(k in forbidden for k in analysis['intersectionTypes']):raise ValueError('INVALID_SOURCE_INTERSECTION')
    pairs=analysis['reversePairs']; removed={i for pair in pairs for i in pair}
    axes={('H' if pts[i][1]==pts[i+1][1] else 'V') for i,j in pairs}
    if len(axes)>1:raise ValueError('MIXED_CUTIN_AXES')
    # Every non-adjacent endpoint encounter must belong to a bridge endpoint.
    bridge_ends={tuple(pts[i]) for pair in pairs for i in pair}
    for item in analysis['intersections']:
        if item['type']=='endpoint' and not all(tuple(F(v) for v in p) in bridge_ends for p in item['pointsTicks']):
            raise ValueError('UNSUPPORTED_SELF_TOUCH')
    edges=[LineString([a,b]) for i,(a,b) in enumerate(zip(pts,pts[1:])) if i not in removed]
    degrees=Counter(tuple(p) for i,(a,b) in enumerate(zip(pts,pts[1:])) if i not in removed for p in (a,b))
    if any(n!=2 for n in degrees.values()):raise ValueError('NON_SIMPLE_LOOPS_AFTER_CUTIN_REMOVAL')
    if any(tuple(pts[k]) not in degrees for i,j in pairs for k in (i,i+1)):
        raise ValueError('RETRACED_SPUR_WITHOUT_HOLE_LOOP')
    ends=Counter(tuple(pts[k]) for i,j in pairs for k in (i,i+1))
    if any(n>1 for n in ends.values()):raise ValueError('SHARED_CUTIN_ENDPOINTS')
    faces=list(polygonize(union_all(edges)))
    if not faces:raise ValueError('NO_CLOSED_FACES')
    filled=[]
    signs=set()
    for face in faces:
        p=face.representative_point();w=winding((F(p.x),F(p.y)),pts)
        if abs(w)>1: raise ValueError('INCONSISTENT_WINDING')
        if w:filled.append(face);signs.add(w)
    if len(signs)>1:raise ValueError('INCONSISTENT_INSIDE_SIDE')
    return union_all(filled)

def region_geometry_ticks(record):
    """Strict handoff: independent contours fill separately and union. Never repair."""
    return union_all([cutin_geometry(c['points'],analyze(c['points'])) for c in record['contours']])

def run():
    OUT.mkdir(exist_ok=True,parents=True);output=[]
    for board in ('gerber-pcb-valentine-feb-new','gerber-prickly-laser-module-2-5'):
        path=ROOT/'phase2a/fixtures/extracted'/board/'Gerber_BottomLayer.GBL';text=path.read_text()
        raw=scan(text);gb=[o for o in GerberFile.open(path).objects if type(o).__name__=='Region']
        pg=[c for c in PG.from_file(str(path)).parse()._command_buffer.commands if type(c).__name__=='Region2']
        records=[]
        for i,r in enumerate(raw):
            if len(r['contours'])!=1: raise ValueError('Real-board evidence mapping expects one contour per observed region')
            pts=r['contours'][0]['points'];a=analyze(pts)
            py=pg[i].command_buffer.commands
            pypts=[(str(c.start_point.x.value),str(c.start_point.y.value),str(c.end_point.x.value),str(c.end_point.y.value)) for c in py]
            gbsegments=list(list(gb[i].to_primitives('mm'))[0].segments)
            gbs=[(str(s[0][0]),str(s[0][1]),str(s[1][0]),str(s[1][1])) for s in gbsegments]
            expected=[tuple(str(F(v,SCALE)) for v in (*p,*q)) for p,q in zip(pts,pts[1:])]
            def deltas(parsed):
                return max((abs(float(F(x)-F(y))) for p,q in zip(parsed,expected) for x,y in zip(p,q)),default=0)
            entry={**r,'regionIndex':i,'analysis':a,'gerbonara':{'segmentCount':len(gbs),'maxCoordinateDeltaMm':deltas(gbs),'segmentsMm':gbs},'pygerber':{'segmentCount':len(pypts),'maxCoordinateDeltaMm':deltas(pypts),'segmentsMm':pypts}}
            entry['sourceStartMm']=[str(Decimal(v)/SCALE) for v in pts[0]]
            entry['operationCounts']=dict(Counter(c['operation'] for c in r['commands']))
            entry['interpolationModes']=sorted(set(c['mode'] for c in r['commands'] if c['operation']=='D01'))
            entry['sourceEndMm']=[str(Decimal(v)/SCALE) for v in pts[-1]]
            entry['closureDeltaDecimalMm']=[str(Decimal(v)/SCALE) for v in a['closureDeltaTicks']]
            entry['gerbonara']['rawOutlinePointCount']=len(gb[i].outline)
            entry['gerbonara']['rawOutlineStartMm']=gb[i].outline[0]
            entry['gerbonara']['rawOutlineEndMm']=gb[i].outline[-1]
            entry['gerbonara']['extraPrimitiveSegmentsMm']=gbs[len(expected):]
            if a['intersectionTypes'].get('zero_length'):
                # Explicit forensic experiment only, never accepted as source or used for manufacturing.
                q=[pts[0]]+[b for a,b in zip(pts,pts[1:]) if a!=b]
                qa=analyze(q)
                try:
                    g=cutin_geometry(q,qa)
                    oldraw,_=primitive_to_geometry(list(gb[i].to_primitives('mm'))[0])
                    before=make_valid(oldraw)
                    mm=scale(g,xfact=1/SCALE,yfact=1/SCALE,origin=(0,0))
                    beforepolys=union_all([p for p in before.geoms if p.geom_type=='Polygon'])
                    entry['diagnosticZeroLengthOmission']={'omittedCommandCount':len(pts)-len(q),'notApprovedForManufacturing':True,
                        'analysis':qa,'areaMm2':g.area/SCALE**2,'interiorVoids':len(g.interiors),
                        'symmetricDifferenceVsPhase2AMakeValidMm2':mm.symmetric_difference(beforepolys).area,
                        'hausdorffVsPhase2AMakeValidMm':mm.boundary.hausdorff_distance(beforepolys.boundary)}
                except ValueError as e: entry['diagnosticZeroLengthOmission']={'status':str(e)}
            try:
                g=region_geometry_ticks(r)
                before=Polygon(pts);repaired=make_valid(before)
                entry['acceptedGeometry']={'areaMm2':g.area/SCALE**2,'interiorVoids':sum(len(p.interiors) for p in (list(g.geoms) if hasattr(g,'geoms') else [g])),'symmetricDifferenceVsPreviousMakeValidMm2':g.symmetric_difference(repaired).area/SCALE**2}
                entry['status']='VALID_CUTIN' if a['reversePairs'] else 'VALID_SIMPLE'
            except ValueError as e:entry['status']='BLOCKED_'+str(e)
            records.append(entry)
        output.append({'boardId':board,'sourceSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'coordinateUnit':'mm','decimalPlaces':5,'tickMm':'0.00001','regionCount':len(raw),'gerbonaraRegionCount':len(gb),'pygerberRegionCount':len(pg),'regions':records})
        excerpt=OUT/(board+'-source-regions.txt')
        lines=text.splitlines(keepends=True)
        excerpt.write_text(''.join(f'--- REGION {i} original lines {r["g36Line"]}..{r["g37Line"]} ---\n'+''.join(lines[r['g36Line']-1:r['g37Line']]) for i,r in enumerate(raw)))
    (OUT/'region-evidence.json').write_text(json.dumps(output,indent=2)+'\n')
    import zipfile,math,platform
    from importlib.metadata import version
    archive_names=['Gerber_PCB_Valentine_Feb_New.zip','Gerber_Prickly-Laser-Module-2.5.zip']
    identities=[]
    for board,name in zip(output,archive_names):
        path=ROOT/'gerbers'/name
        with zipfile.ZipFile(path) as z:
            member=next(n for n in z.namelist() if n.endswith('Gerber_BottomLayer.GBL'))
            identical=hashlib.sha256(z.read(member)).hexdigest()==board['sourceSha256']
        identities.append({'archive':name,'archiveSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'extractedBottomMatchesArchivedBytes':identical})
    laser=output[1]['regions'];deltas=[r['analysis']['closureDeltaTicks'] for r in laser]
    summary={'runtime':{'python':platform.python_version(),'gerbonara':version('gerbonara'),'pygerber':version('pygerber'),'shapely':version('shapely')},
        'archives':identities,'blockedRegionCount':sum(len(b['regions']) for b in output),
        'valentineZeroLengthSegments':[105,14],'valentineHorizontalCutinPairs':[103,14],
        'laserGapDirectionCounts':dict(Counter('horizontal' if d[1]==0 else 'vertical' if d[0]==0 else 'diagonal' for d in deltas)),
        'laserMinimumGapLengthMm':min(math.hypot(*d)/SCALE for d in deltas),'laserMaximumGapLengthMm':max(math.hypot(*d)/SCALE for d in deltas),
        'manufacturingDiagnostics':[{'boardId':b['boardId'],'sourceSha256':b['sourceSha256'],'blockedRegionIndices':[r['regionIndex'] for r in b['regions'] if r['status'].startswith('BLOCKED')],
            'scope':'Affected bottom-copper source regions and operations dependent on their material/clearance; no rejection of unrelated top layers or drill inventory',
            'acceptedManufacturingGeometry':None} for b in output]}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print([(b['boardId'],Counter(r['status'] for r in b['regions'])) for b in output])
    print('Valentine intersections',[(r['regionIndex'],r['analysis']['intersectionTypes']) for r in output[0]['regions']])

if __name__=='__main__':run()
