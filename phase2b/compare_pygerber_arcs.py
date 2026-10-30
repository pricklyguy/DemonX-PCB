"""Cross-check Gerbonara source primitives against PyGerber command records."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from importlib.metadata import version
from gerbonara import GerberFile
from pygerber.gerberx3.api.v2 import GerberFile as PyGerberFile

ROOT=Path(__file__).resolve().parent
FIXTURES=ROOT.parent/'phase2a'/'fixtures'/'extracted'
GEOM={'.GTL','.GBL','.GTS','.GBS','.GTO','.GBO','.GTP','.GBP','.GKO','.GML','.GM1','.GM','.GDL','.GDD'}
MAP={'Flash':'Flash2','Line':'Line2','Region':'Region2'}

def run():
    results=[]
    for path in sorted(FIXTURES.rglob('*')):
        if not path.is_file() or path.suffix.upper() not in GEOM: continue
        g=GerberFile.open(path)
        p=PyGerberFile.from_file(str(path)).parse()
        gc=Counter(type(o).__name__ for o in g.objects)
        rawpc=Counter(type(c).__name__ for c in p._command_buffer.commands)
        pc=Counter()
        for kind,count in rawpc.items(): pc['Arc2' if kind in ('CCArc2','Arc2') else kind]+=count
        normalized={MAP.get(k,'Arc2' if k=='Arc' else k):v for k,v in gc.items()}
        pyarcs=[c for c in p._command_buffer.commands if type(c).__name__ in ('Arc2','CCArc2')]
        garcs=[o for o in g.objects if type(o).__name__=='Arc']
        arc_diffs=[]
        directions=[]
        for go,pa in zip(garcs,pyarcs):
            coords=[float(pa.start_point.x.value),float(pa.start_point.y.value),float(pa.end_point.x.value),float(pa.end_point.y.value),float(pa.center_point.x.value),float(pa.center_point.y.value)]
            source=[go.x1,go.y1,go.x2,go.y2,go.x1+go.cx,go.y1+go.cy]
            arc_diffs.extend(abs(a-b) for a,b in zip(coords,source))
            directions.append(go.clockwise == (type(pa).__name__=='Arc2'))
        results.append({'boardId':path.parent.name,'sourceFile':path.name,'gerbonaraObjectCount':len(g.objects),'pygerberCommandCount':len(p._command_buffer.commands),'typeCountsMatch':normalized==dict(pc),'arcCountGerbonara':len(garcs),'arcCountPyGerber':len(pyarcs),'arcCoordinateMaxDifferenceMm':max(arc_diffs,default=0.0),'arcDirectionMatches':all(directions)})
    out={'pygerberVersion':version('pygerber'),'results':results}
    (ROOT/'reference'/'pygerber-comparison.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__': run()
