"""Compare Delta Gerber 1.7.0 source records with the Phase 2A Gerbonara inventory."""
from __future__ import annotations

import csv, json, math
from collections import Counter, defaultdict
from pathlib import Path

from gerbonara import ExcellonFile, GerberFile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "phase2a" / "fixtures" / "extracted"
P2A = json.loads((ROOT.parent / "phase2a" / "results" / "parsed_geometry.json").read_text(encoding="utf-8"))

def csv_rows(path):
    with path.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def gerbonara_box(obj):
    b = obj.bounding_box()
    return (b[0][0], b[0][1], b[1][0], b[1][1])

def run():
    result = {"reference": "Delta Gerber 1.7.0", "boards": []}
    for board in P2A["boards"]:
        bid = board["boardId"]
        folder = SOURCE / bid
        delta_path = ROOT / "reference" / "delta" / ("valentine.csv" if "valentine" in bid else "laser.csv")
        ref = defaultdict(list)
        for row in csv_rows(delta_path): ref[(row["kind"], row["sourceFile"])].append(row)
        bres = {"boardId": bid, "gerberComparisons": [], "drillComparisons": [], "countTotals": {}}
        for source in board["sourceFiles"]:
            name = source["sourceFile"]
            if source["sourceKind"] != "gerber": continue
            file = folder / name
            g = GerberFile.open(file)
            rows = ref[("gerber", name)]
            typecounts = Counter(x["recordType"] for x in rows)
            ours = g.objects
            # Gerbonara represents linear draws as Line and circular draws as Arc.
            normalized = Counter({"Draw": sum(v for k,v in Counter(type(o).__name__ for o in ours).items() if k == "Line"),
                                  "Arc": sum(v for k,v in Counter(type(o).__name__ for o in ours).items() if k == "Arc"),
                                  "Flash": sum(v for k,v in Counter(type(o).__name__ for o in ours).items() if k == "Flash"),
                                  "Region": sum(v for k,v in Counter(type(o).__name__ for o in ours).items() if k == "Region")})
            normalized = Counter({k:v for k,v in normalized.items() if v})
            bbox_diffs=[]; object_mismatches=Counter()
            if len(ours)==len(rows):
                for o,r in zip(ours,rows):
                    box=gerbonara_box(o)
                    rb=tuple(float(r[k]) for k in ("minX","minY","maxX","maxY"))
                    dif=max(abs(a-b) for a,b in zip(box,rb))
                    bbox_diffs.append(dif)
                    if dif > 1e-6: object_mismatches[type(o).__name__]+=1
            bres["gerberComparisons"].append({"sourceFile":name,"phase2aCount":len(ours),"deltaCount":len(rows),"typeCountsMatch":dict(normalized)==dict(typecounts),"bboxComparedObjects":min(len(ours),len(rows)),"bboxMismatchToleranceMm":1e-6,"bboxMismatchObjects":sum(object_mismatches.values()),"bboxMismatchByGerbonaraType":dict(object_mismatches),"maxObjectBboxCoordinateDifferenceMm":max(bbox_diffs,default=None),"deltaWarnings":sorted({r["warnings"] for r in rows if r["warnings"]})})
        for d in board["drillFiles"]:
            name=d["sourceFile"]; rows=ref[("drill",name)]
            hits=[r for r in rows if r["recordType"]=="DrillHit"]
            slots=[r for r in rows if r["recordType"]=="DrillSlot"]
            p2hits=d["hits"]; p2slots=d["slots"]
            hd=[]; sd=[]; diam=[]
            hit_index_match=[a["sourceFeatureIndex"]==int(b["recordIndex"]) for a,b in zip(p2hits,hits)]
            for a,b in zip(p2hits,hits):
                hd.extend([abs(a["xMm"]-float(b["x1Mm"])),abs(a["yMm"]-float(b["y1Mm"]))])
                diam.append(abs(a["sourceDiameterMm"]-float(b["diameterMm"])))
            slot_index_match=[a["sourceFeatureIndex"]==int(b["recordIndex"]) for a,b in zip(p2slots,slots)]
            for a,b in zip(p2slots,slots):
                coords=a["coordinatesMm"]
                sd.extend([abs(coords[0][0]-float(b["x1Mm"])),abs(coords[0][1]-float(b["y1Mm"])),abs(coords[1][0]-float(b["x2Mm"])),abs(coords[1][1]-float(b["y2Mm"]))])
                diam.append(abs(a["sourceDiameterMm"]-float(b["diameterMm"])))
            bres["drillComparisons"].append({"sourceFile":name,"phase2aHits":len(p2hits),"deltaHits":len(hits),"phase2aSlots":len(p2slots),"deltaSlots":len(slots),"hitSourceIndicesMatch":all(hit_index_match) and len(hit_index_match)==len(p2hits),"slotSourceIndicesMatch":all(slot_index_match) and len(slot_index_match)==len(p2slots),"hitCoordinateMaxDiffMm":max(hd,default=None),"slotEndpointMaxDiffMm":max(sd,default=None),"diameterMaxDiffMm":max(diam,default=None),"deltaWarnings":sorted({r["warnings"] for r in rows if r["warnings"]})})
        result["boards"].append(bres)
    (ROOT/"reference"/"comparison.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__": run()
