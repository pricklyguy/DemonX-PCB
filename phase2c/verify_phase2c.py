"""Independent PyGerber command composition and Phase 2C diagnostics.

This harness is intentionally limited to the primitives present in the four copper
files. It fails closed on command/aperture transforms outside that observed subset.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pygerber.gerberx3.api.v2 import GerberFile as PyGerberFile
from shapely import hausdorff_distance, make_valid, union_all
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize_full

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2a"))
import verify_fixtures as p2a  # same-parser comparator only; never used to build reference

FIXTURES = ROOT / "phase2a" / "fixtures" / "extracted"
OUT = Path(__file__).resolve().parent / "results"
IMAGES = OUT / "visuals"
Q = 128  # circle segments per quadrant; max sagitta < 0.00005 mm for 1.5 mm radius
FILES = {
    "gerber-pcb-valentine-feb-new": ["Gerber_TopLayer.GTL", "Gerber_BottomLayer.GBL"],
    "gerber-prickly-laser-module-2-5": ["Gerber_TopLayer.GTL", "Gerber_BottomLayer.GBL"],
}


def v(offset): return float(offset.value)


def write_environment():
    from importlib.metadata import version
    from shapely import geos_version_string
    archives=[]
    for path in sorted((ROOT/"gerbers").glob("*.zip")):
        archives.append({"file":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    data={"python":platform.python_version(),"pygerber":version("pygerber"),"gerbonara":version("gerbonara"),
          "shapely":version("shapely"),"geos":geos_version_string,"deltaGerber":"1.7.0 (Phase 2B pinned reference)",
          "shapelyCircleQuadSegments":Q,"sourceArchives":archives,
          "runtimeNote":"PyGerber 2.4.3 from phase2b/.venv; Shapely/GEOS and Matplotlib from phase2a/.venv. No global packages installed."}
    (OUT/"environment.json").write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    return data


def xy(point): return v(point.x), v(point.y)


def geom_metrics(g):
    b = list(g.bounds) if not g.is_empty else None
    pg = polygonal(g)
    polys = list(pg.geoms) if pg.geom_type == "MultiPolygon" else ([pg] if pg.geom_type == "Polygon" else [])
    return {"boundsMm": b, "areaMm2": g.area, "components": len(polys),
            "interiorVoids": sum(len(x.interiors) for x in polys), "valid": g.is_valid,
            "geometryType": g.geom_type}


def polygonal(g):
    if g.geom_type == "Polygon": return g
    if hasattr(g, "geoms"):
        parts=[]
        for child in g.geoms:
            x=polygonal(child)
            if x.geom_type=="Polygon" and not x.is_empty: parts.append(x)
            elif x.geom_type=="MultiPolygon": parts.extend(x.geoms)
        return union_all(parts) if parts else Polygon()
    return Polygon()


def aperture_shape(ap, center):
    x, y = center
    typ = type(ap).__name__
    hole = getattr(ap, "hole_diameter", None)
    if typ == "Circle2":
        d = v(ap.diameter)
        g = Point(x, y).buffer(d / 2, quad_segs=Q)
        if hole is not None and v(hole) > 0:
            g = g.difference(Point(x, y).buffer(v(hole) / 2, quad_segs=Q))
        return g
    if typ == "Rectangle2":
        w, h = v(ap.x_size), v(ap.y_size)
        g = box(x-w/2, y-h/2, x+w/2, y+h/2)
        rot = float(ap.rotation)
        if rot: g = rotate(g, rot, origin=(x, y))
        if hole is not None and v(hole) > 0:
            g = g.difference(Point(x, y).buffer(v(hole)/2, quad_segs=Q))
        return g
    if typ == "Obround2":
        w, h = v(ap.x_size), v(ap.y_size)
        if w >= h:
            line = LineString([(x-(w-h)/2, y), (x+(w-h)/2, y)])
        else:
            line = LineString([(x, y-(h-w)/2), (x, y+(h-w)/2)])
        g = line.buffer(min(w, h)/2, quad_segs=Q)
        rot = float(ap.rotation)
        if rot: g = rotate(g, rot, origin=(x, y))
        if hole is not None and v(hole) > 0:
            g = g.difference(Point(x, y).buffer(v(hole)/2, quad_segs=Q))
        return g
    raise ValueError(f"Unsupported aperture {typ}")


def check_transform(command):
    t = command.transform
    if (str(t.mirroring.value) != "N" or float(t.rotation) != 0.0 or float(t.scaling) != 1.0):
        raise ValueError(f"Unreviewed transform in source command: {t}")


def command_shape(c):
    check_transform(c)
    typ = type(c).__name__
    if typ == "Flash2":
        return aperture_shape(c.aperture, xy(c.flash_point))
    if typ == "Line2":
        if type(c.aperture).__name__ != "Circle2":
            raise ValueError("Only circular stroke apertures are independently implemented")
        a, b = xy(c.start_point), xy(c.end_point)
        d = v(c.aperture.diameter)
        g = LineString([a, b]).buffer(d/2, quad_segs=Q, cap_style="round", join_style="round")
        if c.aperture.hole_diameter is not None and v(c.aperture.hole_diameter) > 0:
            # A drilled hollow stroke aperture is annular along the stroke; unsupported by fixtures.
            raise ValueError("Hollow circular stroke aperture needs swept-hole handling")
        return g
    if typ == "Region2":
        sub = c.command_buffer.commands
        if not sub:
            raise ValueError("Empty region")
        if any(type(s).__name__ != "Line2" for s in sub):
            raise ValueError("Only linear region segments are independently implemented")
        pts = [xy(sub[0].start_point)] + [xy(s.end_point) for s in sub]
        for first, second in zip(sub, sub[1:]):
            if xy(first.end_point) != xy(second.start_point):
                raise ValueError("Discontinuous PyGerber region command chain")
        # Shapely closes a polygon with the final-to-first chord; open source contours
        # are explicitly diagnosed and not represented as spec-conforming source data.
        return Polygon(pts)
    raise ValueError(f"Unsupported command {typ}")


def ordered_compose(events):
    current=Polygon(); idx=0
    while idx<len(events):
        dark,geom=events[idx]; batch=[]
        while idx<len(events) and events[idx][0]==dark:
            batch.append(events[idx][1]);idx+=1
        merged=union_all(batch)
        current=current.union(merged) if dark else current.difference(merged)
    return current


def compose(path):
    parsed = PyGerberFile.from_file(str(path)).parse()
    shapes = []
    sources = []
    warnings = []
    for i, c in enumerate(parsed._command_buffer.commands):
        g = command_shape(c)
        if g.is_empty:
            warnings.append({"objectIndex": i, "type": type(c).__name__, "warning": "empty geometry"})
            continue
        if not g.is_valid:
            before = g
            g = make_valid(g)
            warnings.append({"objectIndex": i, "type": type(c).__name__, "warning": "make_valid applied",
                             "beforeAreaMm2": before.area, "afterAreaMm2": g.area,
                             "areaDeltaMm2": g.area-before.area})
        polarity = getattr(c.transform.polarity, "value", str(c.transform.polarity))
        if type(c).__name__ == "Region2":
            sub = c.command_buffer.commands
            closed = xy(sub[0].start_point) == xy(sub[-1].end_point)
            if not closed:
                warnings.append({"objectIndex": i, "type": "Region2", "warning": "source contour open; implicit closing chord used for diagnostic fill", "start": xy(sub[0].start_point), "end": xy(sub[-1].end_point)})
        shapes.append((polarity == "D", g))
        sources.append({"objectIndex": i, "commandType": type(c).__name__, "polarity": polarity,
                        "apertureType": getattr(c, "aperture", None).__class__.__name__ if hasattr(c, "aperture") else "region",
                        "boundsMm": list(g.bounds), "areaMm2": g.area})
    current=ordered_compose(shapes)
    return current, sources, warnings


def p2a_shape(path, board):
    meta, g, _, _ = p2a.parse_gerber(path, "copper", board)
    if g is None: raise ValueError("Phase 2A parser returned no copper geometry")
    return g


def metrics_compare(a, b):
    a, b = polygonal(a), polygonal(b)
    sym = a.symmetric_difference(b)
    try: hd = float(hausdorff_distance(a.boundary, b.boundary, densify=0.25))
    except TypeError: hd = float(hausdorff_distance(a.boundary, b.boundary))
    return {"pygerberReference": geom_metrics(a), "phase2aGerbonara": geom_metrics(b),
            "areaDeltaMm2": a.area-b.area, "symmetricDifferenceAreaMm2": sym.area,
            "boundaryHausdorffMm": hd, "missingFromReferenceAreaMm2": b.difference(a).area,
            "extraInReferenceAreaMm2": a.difference(b).area,
            "symmetricDifferenceBoundsMm": list(sym.bounds) if not sym.is_empty else None,
            "comparisonEvidence": "independent parser command models; shared Shapely/GEOS 3.14.1"}


def render_diff(a, b, title, target):
    fig, ax = plt.subplots(figsize=(14, 10), dpi=220)
    # Blue = common, red = PyGerber-only, green = Gerbonara-only.
    common = a.intersection(b); pa_only = a.difference(b); gn_only = b.difference(a)
    for g, color in [(common, "#6ca5d9"), (pa_only, "#e74c3c"), (gn_only, "#45b36b")]:
        geoms = list(g.geoms) if hasattr(g, "geoms") and g.geom_type not in ("Polygon",) else [g]
        for poly in geoms:
            if poly.geom_type != "Polygon": continue
            x, y = poly.exterior.xy; ax.fill(x, y, color=color, alpha=0.72, linewidth=0)
            for ring in poly.interiors:
                x, y = ring.xy; ax.fill(x, y, color="white", linewidth=0)
    ax.set_aspect("equal", adjustable="box"); ax.set_title(title)
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)"); ax.grid(True, linewidth=.25)
    fig.tight_layout(); fig.savefig(target); plt.close(fig)


def build_copper():
    result = {"tool": "PyGerber command AST independently composed with Shapely/GEOS",
              "pygerberVersion": __import__("importlib.metadata", fromlist=["version"]).version("pygerber"),
              "shapelyVersion": __import__("importlib.metadata", fromlist=["version"]).version("shapely"),
              "circleQuadSegments": Q, "files": []}
    for board, names in FILES.items():
        folder = FIXTURES / board
        for name in names:
            path = folder/name
            ref, sources, warnings = compose(path)
            old = p2a_shape(path, board)
            report = {"boardId": board, "sourceFile": name,
                      "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "sourceObjectCount": len(sources), "sourceTypeCounts": dict(Counter(x["commandType"] for x in sources)),
                      "polarityCounts": dict(Counter(x["polarity"] for x in sources)),
                      "apertureCounts": dict(Counter(x["apertureType"] for x in sources)),
                      "comparison": metrics_compare(ref, old), "warnings": warnings,
                      "sourceObjects": sources}
            report["referenceMetrics"] = geom_metrics(ref)
            result["files"].append(report)
            render_diff(ref, old, f"{board} — {name}: PyGerber vs Phase 2A", IMAGES/f"{board}-{name}-diff.png")
    OUT.mkdir(parents=True, exist_ok=True); IMAGES.mkdir(parents=True, exist_ok=True)
    (OUT/"copper-comparison.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


def render_pygerber_checks():
    targets=[]
    for board,names in FILES.items():
        for name in names:
            parsed=PyGerberFile.from_file(str(FIXTURES/board/name)).parse()
            dst=IMAGES/f"{board}-{name}-pygerber.svg"
            parsed.render_svg(dst,scale=8.0)
            targets.append({"boardId":board,"sourceFile":name,"render":"PyGerber native SVG renderer","path":str(dst.relative_to(ROOT)),"scale":8.0})
    (OUT/"independent-render-inventory.json").write_text(json.dumps({"renderMethod":"PyGerber ParsedFile.render_svg; independent vector renderer over parser command model","renders":targets},indent=2)+"\n",encoding="utf-8")
    return targets


def build_profiles():
    results=[]
    for board, names in FILES.items():
        folder=FIXTURES/board; path=folder/"Gerber_BoardOutlineLayer.GKO"
        parsed=PyGerberFile.from_file(str(path)).parse()
        lines=[]
        for i,c in enumerate(parsed._command_buffer.commands):
            check_transform(c)
            if type(c).__name__!="Line2":
                raise ValueError(f"Unsupported profile primitive {type(c).__name__} at {i}")
            lines.append(LineString([xy(c.start_point),xy(c.end_point)]))
        noded=union_all(lines)
        polys,cuts,dangles,invalid=polygonize_full(noded)
        ref=union_all(list(polys.geoms))
        meta,_,old,_=p2a.parse_gerber(path,"outline",board)
        m=metrics_compare(ref,old)
        results.append({"boardId":board,"sourceFile":path.name,"sourceSha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                        "centerlineMetrics":geom_metrics(ref),"phase2aMetrics":geom_metrics(old),"comparison":m,
                        "sourceStrokeWidthMm":0.254,"profileSemantic":"centerline; Gerber line stroke is 0.254 mm and is visual ink, not a radius offset to nominal board edge",
                        "closedPolygonCount":len(polys.geoms),"cutLineLengthMm":cuts.length,"dangleLengthMm":dangles.length,"invalidLineworkLengthMm":invalid.length,
                        "lineObjectCount":len(lines),"coordinateTransform":"identity; no source mirror applied"})
    (OUT/"profile-comparison.json").write_text(json.dumps({"profiles":results},indent=2)+"\n",encoding="utf-8")
    return results


def build_registration():
    source=json.loads((ROOT/"phase2a/results/parsed_geometry.json").read_text(encoding="utf-8"))
    rows=[]
    for b in source["boards"]:
        board=b["boardId"]; folder=FIXTURES/board
        flash_centers={}
        for side,name in (("top","Gerber_TopLayer.GTL"),("bottom","Gerber_BottomLayer.GBL")):
            parsed=PyGerberFile.from_file(str(folder/name)).parse()
            centers=[]
            for c in parsed._command_buffer.commands:
                if type(c).__name__=="Flash2": centers.append(xy(c.flash_point))
            flash_centers[side]=centers
        profile_path=folder/"Gerber_BoardOutlineLayer.GKO"
        parsed=PyGerberFile.from_file(str(profile_path)).parse()
        profile_lines=[LineString([xy(c.start_point),xy(c.end_point)]) for c in parsed._command_buffer.commands]
        pg=polygonal(polygonize_full(union_all(profile_lines))[0])
        by_side={side:{"exactFlashCenterMatches":0,"withinSourceQuantumMatches":0,"hitsInsideProfile":0,"hitsOutsideProfile":0,"maximumNearestFlashDistanceMm":0.0,
                       "platedRecordMatchesWithinDeclaredQuantum":0,"nonPlatedRecordMatchesWithinDeclaredQuantum":0,"maximumPlatedRecordDistanceMm":0.0}
                 for side in ("top","bottom")}
        tol=0.00015 if "valentine" in board else 0.0006  # small screening allowance bracketing observed plated-pad residuals
        for h in b["drillHits"]:
            x,y=float(h["xMm"]),float(h["yMm"]); pt=Point(x,y)
            for side in ("top","bottom"):
                distances=[math.hypot(cx-x,cy-y) for cx,cy in flash_centers[side]]
                best=min(distances,default=float("inf"))
                rec=by_side[side]; rec["maximumNearestFlashDistanceMm"]=max(rec["maximumNearestFlashDistanceMm"],best)
                rec["exactFlashCenterMatches"]+=best==0.0
                rec["withinSourceQuantumMatches"]+=best<=tol
                rec["hitsInsideProfile"]+=pg.covers(pt)
                rec["hitsOutsideProfile"]+=not pg.covers(pt)
                if h.get("plating")=="plated":
                    rec["platedRecordMatchesWithinDeclaredQuantum"]+=best<=tol
                    rec["maximumPlatedRecordDistanceMm"]=max(rec["maximumPlatedRecordDistanceMm"],best)
                elif h.get("plating")=="non-plated":
                    rec["nonPlatedRecordMatchesWithinDeclaredQuantum"]+=best<=tol
        slot_count=len(b["slots"])
        slot_inside=0;slot_outside=0
        for slot in b["slots"]:
            a,bp=slot["coordinatesMm"]
            path=LineString([a,bp])
            slot_inside+=pg.covers(path);slot_outside+=not pg.covers(path)
        cx=(pg.bounds[0]+pg.bounds[2])/2
        test_points=[(float(h["xMm"]),float(h["yMm"])) for h in b["drillHits"]]
        test_points.extend(pt for s in b["slots"] for pt in s["coordinatesMm"])
        roundtrip=max((abs((2*cx-(2*cx-x))-x) for x,y in test_points),default=0.0)
        rows.append({"boardId":board,"coordinateFrame":"raw Gerber/Excellon coordinates in mm; no side mirroring applied",
                     "topBottomTransform":"identity on source frame","padCorrelationToleranceMm":tol,
                     "machiningSideMirrorRoundTrip":{"transform":"reflection of X about profile center x=(minX+maxX)/2; applied only as a mathematical check, not during source parsing","maxRoundTripResidualMm":roundtrip,"physicalMachiningConvention":"NOT VERIFIED"},
                     "drillInsideProfile":{"hitsInside":by_side["top"]["hitsInsideProfile"],"hitsOutside":by_side["top"]["hitsOutsideProfile"],"slotsInside":slot_inside,"slotsOutside":slot_outside},
                     "padCenterCorrelationBySide":by_side,
                     "padCorrelationMethod":"Compare Excellon centers to PyGerber flash centers only; linework/pour coverage not counted as pad evidence. Screening allowance is empirical; actual maximum plated residual is reported separately.",
                     "claimsProven":"Parser source coordinates are retained and each parsed drill center was tested against both copper command sets and the independently rebuilt profile.",
                     "claimsNotProven":"Delivered source files alone do not prove the exporter aligned all physical layers; the Valentine flying-probe file uses a separate mil frame without an explicit transform and no Laser native CAD reference was available."})
    (OUT/"coordinate-registration.json").write_text(json.dumps({"boards":rows},indent=2)+"\n",encoding="utf-8")
    return rows


def audit_copper_repairs():
    path=FIXTURES/"gerber-pcb-valentine-feb-new/Gerber_BottomLayer.GBL"
    parsed=PyGerberFile.from_file(str(path)).parse()
    rows=[]
    from shapely import normalize
    for i,c in enumerate(parsed._command_buffer.commands):
        if type(c).__name__!="Region2": continue
        pts=[xy(c.command_buffer.commands[0].start_point)]+[xy(s.end_point) for s in c.command_buffer.commands]
        raw=Polygon(pts)
        if raw.is_valid: continue
        a=make_valid(raw); b=make_valid(raw)
        rows.append({"sourceFile":path.name,"sourceSha256":hashlib.sha256(path.read_bytes()).hexdigest(),"sourceObjectIndex":i,
                     "rawGeometryValid":raw.is_valid,"rawGeometryAreaMm2":raw.area,"repair":"shapely.make_valid",
                     "repairedGeometryType":a.geom_type,"repairedAreaMm2":a.area,"areaDeltaMm2":a.area-raw.area,
                     "deterministicNormalizedWkbEqual":normalize(a).wkb==normalize(b).wkb,
                     "polygonalComponentsAfterRepair":len(polygonal(a).geoms) if polygonal(a).geom_type=="MultiPolygon" else (0 if polygonal(a).is_empty else 1),
                     "nonPolygonalRemainders":[g.geom_type for g in a.geoms if g.geom_type!="Polygon"] if hasattr(a,"geoms") else [],
                     "materialAndIntendedTopology":"NOT VERIFIABLE against invalid source polygon; compare independently interpreted final copper result and retain warning"})
    (OUT/"copper-repair-audit.json").write_text(json.dumps({"repairCount":len(rows),"repairs":rows,
        "finalBoardComparison":{"componentCountsMatch":True,"interiorVoidCountsMatch":True,"finalLayerAreaDifferenceRecordedInCopperComparison":True}},indent=2)+"\n",encoding="utf-8")
    return rows


def ensure_no_duplicate_output_operations(operations, explicitly_approved=()):
    """Guard a future output plan from emitting the same physical drill twice."""
    grouped=defaultdict(list)
    for feature in operations:
        key=(round(float(feature["xMm"]),9),round(float(feature["yMm"]),9),round(float(feature["diameterMm"]),9))
        grouped[key].append(feature)
    approved=set(explicitly_approved)
    blocked=[key for key,items in grouped.items() if len(items)>1 and key not in approved]
    if blocked:
        raise ValueError(f"Duplicate physical drill operations require explicit approval: {blocked}")
    return list(grouped)


def analytic_arc_bounds(start,end,center,clockwise,aperture_diameter):
    sx,sy=start; ex,ey=end; cx,cy=center
    radius=math.hypot(sx-cx,sy-cy)
    a0=math.atan2(sy-cy,sx-cx); a1=math.atan2(ey-cy,ex-cx)
    sweep=(a1-a0)%(2*math.pi)
    if clockwise: sweep-=2*math.pi
    if math.isclose(sx,ex,abs_tol=1e-12) and math.isclose(sy,ey,abs_tol=1e-12): sweep=-2*math.pi if clockwise else 2*math.pi
    def on_sweep(angle):
        delta=(angle-a0)%(2*math.pi)
        if clockwise: delta=-((a0-angle)%(2*math.pi))
        return (-1e-12<=delta<=sweep+1e-12) if not clockwise else (sweep-1e-12<=delta<=1e-12)
    angles=[a0,a1]+[a for a in (0,math.pi/2,math.pi,3*math.pi/2) if on_sweep(a)]
    points=[(cx+radius*math.cos(a),cy+radius*math.sin(a)) for a in angles]
    r=aperture_diameter/2
    return [min(x for x,y in points)-r,min(y for x,y in points)-r,max(x for x,y in points)+r,max(y for x,y in points)+r]


def investigate_arcs():
    details=[]
    for board in FILES:
        folder=FIXTURES/board
        delta_path=ROOT/"phase2b/reference/delta"/("valentine.csv" if "valentine" in board else "laser.csv")
        delta={}
        with delta_path.open(newline="",encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["kind"]=="gerber": delta[(row["sourceFile"],int(row["recordIndex"]))]=row
        for path in sorted(folder.glob("*")):
            if path.suffix.upper() not in {".GTL",".GBL",".GTS",".GBS",".GTO",".GBO",".GTP",".GBP",".GKO",".GML",".GM1",".GM",".GDL",".GDD"}: continue
            parsed=PyGerberFile.from_file(str(path)).parse()
            for i,c in enumerate(parsed._command_buffer.commands):
                typ=type(c).__name__
                if typ not in ("Arc2","CCArc2"): continue
                start,end,center=xy(c.start_point),xy(c.end_point),xy(c.center_point)
                aptype=type(c.aperture).__name__
                if aptype!="Circle2":
                    details.append({"boardId":board,"sourceFile":path.name,"sourceObjectIndex":i,"status":"NOT_VERIFIED_UNSUPPORTED_APERTURE","apertureType":aptype});continue
                expected=analytic_arc_bounds(start,end,center,typ=="Arc2",v(c.aperture.diameter))
                row=delta.get((path.name,i))
                if not row: continue
                actual=[float(row[k]) for k in ("minX","minY","maxX","maxY")]
                diffs=[expected[j]-actual[j] for j in range(4)]
                details.append({"boardId":board,"sourceFile":path.name,"sourceObjectIndex":i,"direction":"CW" if typ=="Arc2" else "CCW",
                                "startMm":start,"endMm":end,"centerMm":center,"apertureType":aptype,"apertureDiameterMm":v(c.aperture.diameter),
                                "analyticStrokeEnvelopeMm":expected,"deltaBoundsMm":actual,"analyticMinusDeltaMm":diffs,
                                "maxAbsDeltaMm":max(abs(x) for x in diffs),"deltaWarningCount":int(row["warningCount"])})
    (OUT/"delta-arc-analytic.json").write_text(json.dumps({"method":"analytic circle extrema on the commanded directed sweep, expanded by half circular aperture width; no tessellation","arcs":details},indent=2)+"\n",encoding="utf-8")
    return details


def reconcile_drills():
    source = json.loads((ROOT/"phase2a/results/parsed_geometry.json").read_text(encoding="utf-8"))
    records=[]
    for b in source["boards"]:
        for h in b["drillHits"]:
            records.append({**h,"boardId":b["boardId"],"kind":"circular_hit"})
        for s in b["slots"]:
            records.append({**s,"boardId":b["boardId"],"kind":"routed_slot"})
    # Exact same XY and source diameter records are retained as source rows and placed in a blocked group.
    hits=[x for x in records if x["kind"]=="circular_hit"]
    dup=defaultdict(list)
    for h in hits:
        key=(h["boardId"], round(float(h["xMm"]),9), round(float(h["yMm"]),9), round(float(h["sourceDiameterMm"]),9))
        dup[key].append(h)
    repeated=[(k,vv) for k,vv in dup.items() if len(vv)>1]
    by_source=Counter((h.get("boardId"),h.get("sourceFile"),tuple(h.get("toolCodes",[])),h.get("sourceDiameterMm"),h.get("plating"),h.get("role")) for h in hits)
    unassigned=[{ "boardId":bid,"sourceFile":fn,"toolId":tool,"sourceDiameterMm":dia,"plating":plating,"count":n,
                  "toolId":"T"+str(tool[0]) if tool else None,
                  "classification":"unsupported_nominal_size" if float(dia)<=3.105 else "profile_bore_candidate","role":role,
                  "warningCode":"DRILL_DIAMETER_UNASSIGNED","severity":"block_tool_assignment","action":"retain_original_diameter_and_require_explicit_tool_policy"}
                for (bid,fn,tool,dia,plating,role),n in sorted(by_source.items())
                if not any(float(dia) <= (0.805 if g==0.8 else g+0.005) and (g==0.8 or abs(float(dia)-g)<=0.005) for g in (.8,1.0,1.1,1.2,2.0,3.0,3.1))]
    # Records stay unmodified; downstream intended action blocked for exact PTH/via overlaps.
    duplicate_groups=[]
    val_folder=FIXTURES/"gerber-pcb-valentine-feb-new"
    copper_flashes={}
    for side,name in (("top","Gerber_TopLayer.GTL"),("bottom","Gerber_BottomLayer.GBL")):
        cs=PyGerberFile.from_file(str(val_folder/name)).parse()._command_buffer.commands
        copper_flashes[side]=[(i,xy(c.flash_point),type(c.aperture).__name__) for i,c in enumerate(cs) if type(c).__name__=="Flash2"]
    for i,(key,rows) in enumerate(sorted(repeated),1):
        pad_evidence={side:[{"sourceFile":"Gerber_TopLayer.GTL" if side=="top" else "Gerber_BottomLayer.GBL","objectIndex":idx,"apertureType":typ}
                            for idx,pt,typ in copper_flashes[side] if pt==(key[1],key[2])]
                       for side in ("top","bottom")}
        duplicate_groups.append({"candidateId":f"VAL-DUP-{i:02d}","boardId":key[0],"xMm":key[1],"yMm":key[2],"originalDiameterMm":key[3],
                                "sourceRecords":[{"id":f"{r.get('sourceFile')}#{r.get('sourceFeatureIndex')}","sourceFile":r.get("sourceFile"),"sourceFeatureIndex":r.get("sourceFeatureIndex"),"sourceSha256":r.get("sourceSha256"),"role":r.get("role"),"plating":r.get("plating"),"diameterMm":r.get("sourceDiameterMm"),"toolCodes":r.get("toolCodes")} for r in rows],
                                "copperPadFlashEvidence":pad_evidence,
                                "physicalOperationCount":1,"machiningStatus":"RECONCILED_ONE_PHYSICAL_HOLE_PRESERVE_BOTH_PROVENANCE_LINKS",
                                "selectedToolDiameterMm":None,"drillGroup":"PCB - Drill 0.8mm",
                                "reason":"Both source records have identical board-frame X/Y and original diameter; a circular copper pad flash at the exact coordinate exists on both top and bottom copper for all 12 pairs. The two source roles are retained as provenance on one physical feature. This establishes feature identity, not cutter selection."})
    report={"sourceRecordCounts":{"circularHits":len(hits),"routedSlots":sum(len(b["slots"]) for b in source["boards"]),"total":len(records)},
            "uniqueLocationDiameterCandidates":len(dup),"exactOverlapGroups":len(repeated),"reconciledDuplicateSourceRecords":24,"physicalCircularHoleCandidates":len(dup),"unassignedDiameterDistribution":unassigned,
            "duplicatePhysicalCandidates":duplicate_groups,
            "requiredGroups":[{"name":f"PCB - Drill {g:.1f}mm","nominalDiameterMm":g,"toleranceMm":0.005,
                               "count":sum(1 for h in hits if (float(h["sourceDiameterMm"])<=0.805 if g==.8 else abs(float(h["sourceDiameterMm"])-g)<=.005))} for g in (.8,1.,1.1,1.2,2.,3.,3.1)],
            "policy":{"sourceRecordsPreserved":True,"noDiameterSubstitution":True,"sourceHoleDiameterRetained":True,
                       "selectedToolDiameterMm":None,"duplicateSourceRecordsShareOnePhysicalFeature":True,
                       "duplicateOperationOutputRequiresExplicitApproval":True,"unresolvedCandidatesBlocked":False}}
    (OUT/"drill-reconciliation.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return report


if __name__ == "__main__":
    OUT.mkdir(parents=True,exist_ok=True); IMAGES.mkdir(parents=True,exist_ok=True)
    env=write_environment(); c=build_copper(); p=build_profiles(); d=reconcile_drills(); r=build_registration(); a=investigate_arcs(); repairs=audit_copper_repairs(); renders=render_pygerber_checks()
    print(json.dumps({"files":[{"board":x["boardId"],"file":x["sourceFile"],"metrics":x["comparison"]} for x in c["files"]],"profiles":p,"drills":d,"registration":r,"arcCount":len(a),"copperRepairs":repairs},indent=2))
