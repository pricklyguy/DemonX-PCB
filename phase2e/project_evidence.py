"""Inspect supplied archive provenance and specify later native-project evidence."""
import json,zipfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'phase2e/results'

def run():
    inventory=[]
    for path in sorted((ROOT/'gerbers').glob('*.zip')):
        with zipfile.ZipFile(path) as z:
            members=[];native=[]
            for item in z.infolist():
                if item.is_dir():continue
                data=z.read(item)
                entry={'name':item.filename,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                if Path(item.filename).suffix.lower() in {'.epro','.eprj','.kicad_pcb','.pcbdoc'}:native.append(item.filename)
                if item.filename.lower().endswith('.json'):
                    obj=json.loads(data)
                    entry['jsonTopLevelKeys']=list(obj) if isinstance(obj,dict) else []
                    if isinstance(obj,dict) and 'head' in obj and ('shape' in obj or 'canvas' in obj):native.append(item.filename)
                if Path(item.filename).suffix.upper() in {'.GBL','.GTL','.DRL','.GKO'}:
                    lines=data.decode('ascii',errors='replace').splitlines()
                    entry['headerEvidence']=[x for x in lines[:30] if x.startswith(('G04',';','%FS','%MO','METRIC'))]
                members.append(entry)
            inventory.append({'archive':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'members':members,
                'containsEditableNativePCBProject':bool(native),'nativePCBProjectCandidates':native,'nativeRevisionCorrespondence':'NOT_VERIFIED',
                'ownerStatement':'User confirms original editable EasyEDA projects still exist; none requested or accessed during Phase 2E.'})
    (OUT/'archive-project-provenance.json').write_text(json.dumps(inventory,indent=2)+'\n')
    p2a=json.loads((ROOT/'phase2a/results/parsed_geometry.json').read_text())
    p2c=json.loads((ROOT/'phase2c/results/copper-comparison.json').read_text())
    requirements={'accessRequested':False,'purpose':'Evidence specification for a later authorized EasyEDA project comparison',
        'artifacts':[
            {'board':'Valentine','nativeFiles':['complete EasyEDA Pro project export (.epro/project ZIP) or offline .eprj copy','matching PCB document and cached copper fill/region data','project revision/history identity and export settings'],
             'archiveHeaderTarget':'EasyEDA Pro 2.2.45.4; Gerber Generator 0.3; 2026-02-05; one-click export'},
            {'board':'Laser Module','nativeFiles':['EasyEDA Standard PCB JSON source and complete project backup ZIP','saved copper pour and solid region definitions, cached fill where available','revision/history identity and export settings'],
             'archiveHeaderTarget':'EasyEDA 6.5.51; Gerber Generator 0.2; 2026-06-11; opaque markers 97eb0bbe93fb4be09f112c218f02c656,f2a3d59ec7b1417cbfc1eaa01b809597,10'}],
        'minimumMeasurements':['board outline vertex coordinates and dimensions in mm','raw top/bottom copper bounds, filled area, components and holes before/after a copied-project pour rebuild',
            'drill centers, original diameters, plating and slots as complete feature table','for each of the 182 Laser candidates: native object identity/net/layer, closed vertex boundary or native fill evidence showing intended material on both sides of candidate edge',
            'for Valentine: native 103/14 region-hole topology and all copper islands/clearances','at least three noncollinear pad/drill anchor coordinates with side/origin/rotation/mirror settings'],
        'revisionProtocol':['hash immutable native backup before opening','identify PCB document/revision against archived headers and history; filenames alone insufficient',
            'open a duplicate using original editor edition/version if available; record any migration','capture saved fill first, then separately test repour on another duplicate',
            'export twice from same unchanged snapshot/settings to separate fresh directories; hash all outputs','compare original/re-exported profile, all drill/slot records and all copper topology/boundaries; classify revision drift separately from exporter changes',
            'accept native intent evidence only after matching board identity, revision and geometry; a current export is not automatically authoritative for the archived revision'],
        'fixtureTargets':[{'boardId':b['boardId'],'archiveSha256':b['archiveSha256'],'boardWidthMm':b['boardWidthMm'],'boardHeightMm':b['boardHeightMm'],
            'circularSourceRecords':len(b['drillHits']),'routedSlots':len(b['slots']),'phase2aDerivedTopCopper':b['topCopper'],'phase2aDerivedBottomCopper':b['bottomCopper'],
            'phase2cReferenceMetrics':[{'sourceFile':x['sourceFile'],'metrics':x['referenceMetrics']} for x in p2c['files'] if x['boardId']==b['boardId']]} for b in p2a['boards']]}
    (OUT/'native-project-evidence-requirements.json').write_text(json.dumps(requirements,indent=2)+'\n')

if __name__=='__main__':run()
