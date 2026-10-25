"""Read-only, reproducible comparison of Laser Module v2.0 and v2.5 exports.

The sole extraction input is the staged v2.0 archive.  Only named manufacturing
members are extracted after validating every archive path.  The staged native PCB
JSON is read-only evidence.  Open Gerber region contours remain blocked; the
straight closure tested here is a diagnostic comparison candidate only.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2d"))
sys.path.insert(0, str(ROOT / "phase2c"))
sys.path.insert(0, str(ROOT / "phase2a"))
sys.path.insert(0, str(ROOT / "phase2e"))

import forensics
import verify_phase2c as copper
import verify_fixtures as p2a
import recovery
from pygerber.gerberx3.api.v2 import GerberFile as PyGerberFile
from shapely import hausdorff_distance, union_all
from shapely.geometry import LineString, Polygon
from shapely.strtree import STRtree
from shapely import distance as shapely_distance, points as shapely_points
import numpy as np

STAGED_EXPORT = ROOT / "phase2f/fixtures/laser-v2.0-export.zip"
STAGED_NATIVE = ROOT / "phase2f/fixtures/laser-v2.0-pcb.json"
V25_ARCHIVE = ROOT / "gerbers/Gerber_Prickly-Laser-Module-2.5.zip"
EXTRACTED = ROOT / "phase2f/fixtures/extracted/laser-v2.0"
OUT = ROOT / "phase2f/results"
TICK = Decimal("0.00001")
MM_PER_NATIVE_UNIT = Decimal("0.254")
EXPECTED_MEMBERS = {
    "Gerber_TopLayer.GTL", "Gerber_BottomLayer.GBL",
    "Gerber_BoardOutlineLayer.GKO", "Drill_PTH_Through.DRL",
    "Drill_PTH_Through_Via.DRL",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_extract(archive: Path, destination: Path) -> dict[str, bytes]:
    """Extract only the exact expected manufacturing members, without traversal."""
    data: dict[str, bytes] = {}
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        seen: set[str] = set()
        for info in zf.infolist():
            pp = PurePosixPath(info.filename)
            if pp.is_absolute() or ".." in pp.parts or "\\" in info.filename:
                raise ValueError(f"Unsafe archive path: {info.filename!r}")
            if info.is_dir():
                continue
            if len(pp.parts) != 1:
                raise ValueError(f"Unexpected nested archive entry: {info.filename!r}")
            name = pp.name
            if name in EXPECTED_MEMBERS:
                if name in seen:
                    raise ValueError(f"Duplicate manufacturing member: {name}")
                if info.file_size > 20_000_000:
                    raise ValueError(f"Unexpectedly large manufacturing member: {name}")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError(f"Symlink entry is not accepted: {name}")
                payload = zf.read(info)
                if len(payload) != info.file_size:
                    raise ValueError(f"Truncated member: {name}")
                seen.add(name)
                data[name] = payload
        if seen != EXPECTED_MEMBERS:
            raise ValueError(f"Expected manufacturing members missing: {sorted(EXPECTED_MEMBERS-seen)}")
    for name, payload in data.items():
        (destination / name).write_bytes(payload)
    return data


def region_records(payload: bytes) -> list[dict]:
    return forensics.scan(payload.decode("ascii"))


def source_command_rows(payload: bytes) -> list[str]:
    """Ignore comments/format declarations/aperture declarations, retain commands."""
    rows = []
    for raw in payload.decode("ascii").splitlines():
        line = raw.strip()
        if not line or line.startswith("G04") or line.startswith(";") or line.startswith("%ADD"):
            continue
        if line in {"%FSLAX45Y45*%", "%MOMM*%"}:
            continue
        rows.append(line)
    return rows


def aperture_declarations(payload: bytes) -> dict[str, str]:
    return dict(re.findall(r"%ADD(\d+)([^*]+)\*%", payload.decode("ascii")))


def aperture_descriptor(aperture) -> dict:
    typ = type(aperture).__name__
    result = {"type": typ}
    for attr in ("diameter", "x_size", "y_size", "hole_diameter", "rotation"):
        value = getattr(aperture, attr, None)
        if value is not None:
            result[attr] = str(getattr(value, "value", value))
    return result


def command_descriptor(command) -> dict:
    xy = copper.xy
    typ = type(command).__name__
    t = command.transform
    row = {"type": typ, "polarity": t.polarity.value, "mirror": t.mirroring.value,
           "rotation": str(t.rotation), "scale": str(t.scaling)}
    if hasattr(command, "aperture"):
        row["aperture"] = aperture_descriptor(command.aperture)
    if typ == "Flash2":
        row["point"] = [str(x) for x in xy(command.flash_point)]
    elif typ == "Line2":
        row["start"] = [str(x) for x in xy(command.start_point)]
        row["end"] = [str(x) for x in xy(command.end_point)]
    elif typ == "Region2":
        sub = command.command_buffer.commands
        row["segments"] = [[str(x) for x in xy(s.start_point)] + [str(x) for x in xy(s.end_point)]
                           for s in sub]
    else:
        row["fields"] = {key: str(value) for key, value in vars(command).items() if key != "transform"}
    return row


def geometry_difference(left, right) -> dict:
    delta = left.symmetric_difference(right)
    try:
        boundary_hd = float(hausdorff_distance(left.boundary, right.boundary, densify=0.25))
    except TypeError:
        boundary_hd = float(hausdorff_distance(left.boundary, right.boundary))
    return {
        "leftBoundsMm": list(left.bounds), "rightBoundsMm": list(right.bounds),
        "boundsDeltaMm": [float(a-b) for a, b in zip(left.bounds, right.bounds)],
        "leftAreaMm2": left.area, "rightAreaMm2": right.area,
        "areaDeltaMm2": right.area-left.area,
        "symmetricDifferenceAreaMm2": delta.area,
        "leftOnlyAreaMm2": left.difference(right).area,
        "rightOnlyAreaMm2": right.difference(left).area,
        "boundaryHausdorffMm": boundary_hd,
        "leftComponents": len(left.geoms) if left.geom_type == "MultiPolygon" else int(not left.is_empty),
        "rightComponents": len(right.geoms) if right.geom_type == "MultiPolygon" else int(not right.is_empty),
        "leftVoids": sum(len(p.interiors) for p in ([left] if left.geom_type == "Polygon" else left.geoms)),
        "rightVoids": sum(len(p.interiors) for p in ([right] if right.geom_type == "Polygon" else right.geoms)),
    }


def primitive_differences(v20_path: Path, v25_path: Path, threshold: float = 1e-13) -> dict:
    c20 = PyGerberFile.from_file(str(v20_path)).parse()._command_buffer.commands
    c25 = PyGerberFile.from_file(str(v25_path)).parse()._command_buffer.commands
    d20, d25 = [command_descriptor(c) for c in c20], [command_descriptor(c) for c in c25]
    key = lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"))
    count20, count25 = Counter(map(key,d20)), Counter(map(key,d25))
    common = count20 & count25
    common_count = sum(common.values())
    left_need, right_need = count20-common, count25-common
    unmatched20, unmatched25 = [], []
    for c,d in zip(c20,d20):
        k=key(d)
        if left_need[k]: unmatched20.append((c,d));left_need[k]-=1
    for c,d in zip(c25,d25):
        k=key(d)
        if right_need[k]: unmatched25.append((c,d));right_need[k]-=1
    changed = []
    # Preserve unmatched features as separate records. Pair only when residual counts
    # match by primitive class/polarity; the pair is diagnostic and source-linked.
    groups20,groups25={},{}
    group=lambda d:(d["type"],d["polarity"])
    for c,d in unmatched20: groups20.setdefault(group(d),[]).append((c,d))
    for c,d in unmatched25: groups25.setdefault(group(d),[]).append((c,d))
    for g in sorted(set(groups20)|set(groups25)):
        olds,news=groups20.get(g,[]),groups25.get(g,[])
        pairs=min(len(olds),len(news))
        for i in range(pairs):
            a,da=olds[i];b,db=news[i]
            ga,gb=copper.command_shape(a),copper.command_shape(b)
            edge=geometry_difference(ga,gb)
            if edge["symmetricDifferenceAreaMm2"]>threshold or edge["leftBoundsMm"]!=edge["rightBoundsMm"]:
                changed.append({"pairingBasis":"same primitive type/polarity, residual source order; diagnostic only",
                                "v20Descriptor":da,"v25Descriptor":db,**edge})
        for c,d in olds[pairs:]:
            changed.append({"status":"V20_ONLY_SOURCE_PRIMITIVE","descriptor":d})
        for c,d in news[pairs:]:
            changed.append({"status":"V25_ONLY_SOURCE_PRIMITIVE","descriptor":d})
    def polarity_runs(commands,descriptors):
        runs=[]
        for cmd,desc in zip(commands,descriptors):
            polarity=cmd.transform.polarity.value
            if not runs or runs[-1]["polarity"]!=polarity:runs.append({"polarity":polarity,"items":[]})
            runs[-1]["items"].append(key(desc))
        return [{"polarity":r["polarity"],"objectCount":len(r["items"]),
                 "geometryMultisetSha256":sha("\n".join(sorted(r["items"])).encode()),"geometryMultiset":Counter(r["items"])} for r in runs]
    runs20,runs25=polarity_runs(c20,d20),polarity_runs(c25,d25)
    run_equivalent=(len(runs20)==len(runs25) and all(a["polarity"]==b["polarity"] and a["geometryMultiset"]==b["geometryMultiset"] for a,b in zip(runs20,runs25)))
    return {
        "method": "PyGerber command AST descriptor multiset comparison (source order ignored so harmless command reorder is not treated as geometry change); only unmatched primitives are converted to Shapely geometry. No invalid region is auto-repaired.",
        "commandCountV20": len(c20), "commandCountV25": len(c25),
        "typeCountsV20": dict(Counter(type(x).__name__ for x in c20)),
        "typeCountsV25": dict(Counter(type(x).__name__ for x in c25)),
        "unchangedDescriptorCount": common_count,
        "unmatchedV20PrimitiveCount": len(unmatched20), "unmatchedV25PrimitiveCount": len(unmatched25),
        "polarityRunCountV20":len(runs20),"polarityRunCountV25":len(runs25),
        "polarityRunGeometryEquivalent":run_equivalent,
        "polarityRunsV20":[{k:v for k,v in r.items() if k!="geometryMultiset"} for r in runs20],
        "polarityRunsV25":[{k:v for k,v in r.items() if k!="geometryMultiset"} for r in runs25],
        "changedPrimitiveCount": len(changed), "changedPrimitives": changed,
        "limitation": "Full-layer compositing was not used for the open-region bottom layer because it would silently turn each source contour into a filled polygon. Results isolate changed source primitives; they are not a full net-aware copper clearance comparison.",
    }


def gerber_points(payload: bytes) -> list[tuple[Decimal, Decimal]]:
    text = payload.decode("ascii")
    matches = re.findall(r"X(-?\d+)Y(-?\d+)D0[12]\*", text)
    return [(Decimal(x)*TICK, Decimal(y)*TICK) for x, y in matches]


def native_outline(native: dict) -> tuple[Decimal, list[tuple[Decimal, Decimal]]]:
    found = []
    for raw in native["shape"]:
        if raw.startswith("TRACK~"):
            fields = raw.split("~")
            if len(fields) > 4 and fields[2] == "10":
                nums = [Decimal(x) for x in re.findall(r"-?\d+(?:\.\d+)?", fields[4])]
                if len(nums) >= 6:
                    found.append((Decimal(fields[1]), list(zip(nums[0::2], nums[1::2]))))
    if len(found) != 1:
        raise ValueError(f"Expected exactly one native board-outline track, got {len(found)}")
    return found[0]


def native_fuse_components(native: dict, transform: dict) -> list[dict]:
    rows=[]
    for raw in native.get("shape",[]):
        if not raw.startswith("LIB~"):continue
        f=raw.split("~");library=f[3].split("`")[1] if len(f)>3 and "`" in f[3] else ""
        ref=None
        for chunk in raw.split("#@$"):
            q=chunk.split("~")
            if len(q)>10 and q[0]=="TEXT" and q[1]=="P" and re.fullmatch(r"F\d+",q[10]):ref=q[10]
        if ref and "FUSE" in library.upper():
            origin=map_point((Decimal(f[1]),Decimal(f[2])),transform)
            rows.append({"reference":ref,"libraryDescription":library,"nativeOriginUnits":f[1:3],"originMm":list(map(str,origin))})
    return sorted(rows,key=lambda x:x["reference"])


def affine_from_outlines(native_points, gerber_points_) -> dict:
    # Known native and Gerber boards have one axis-aligned rectangular profile.
    nx = sorted({p[0] for p in native_points}); ny = sorted({p[1] for p in native_points})
    gx = sorted({p[0] for p in gerber_points_}); gy = sorted({p[1] for p in gerber_points_})
    if len(nx) != 2 or len(ny) != 2 or len(gx) != 2 or len(gy) != 2:
        raise ValueError("Outline is not the expected axis-aligned rectangle; derive a full transform separately")
    measured_sx = (gx[1]-gx[0])/(nx[1]-nx[0])
    measured_sy = (gy[1]-gy[0])/(ny[1]-ny[0])
    if measured_sx <= 0 or abs(measured_sx-measured_sy) > Decimal("0.00000001"):
        raise ValueError(f"Unexpected scale/orientation: sx={measured_sx}, sy={measured_sy}")
    # The document declares mm and native coordinate units are 10 mil (=0.254 mm).
    # Gerber is rounded to 5 decimals; fit translations against all four corners.
    sx = MM_PER_NATIVE_UNIT
    sy = -MM_PER_NATIVE_UNIT  # canvas Y-down to Gerber Y-up; no board-side mirror
    # Pair points by the known axis orientation and nearest coordinate on each axis.
    txs = [gx[0]-sx*nx[0], gx[1]-sx*nx[1]]
    tys = [gy[1]-sy*ny[0], gy[0]-sy*ny[1]]
    tx = sum(txs)/2; ty = sum(tys)/2
    residuals = [max(abs((sx*x+tx)-gxv), abs((sy*y+ty)-gyv))
                 for x,gxv in zip(nx,gx) for y,gyv in zip(ny,reversed(gy))]
    fit_residual = max(residuals)
    if fit_residual > Decimal("0.00001"):
        raise ValueError(f"Outline transform residual exceeds Gerber half-tick: {fit_residual} mm")
    return {"xScale": str(sx), "yScale": str(sy), "xOffsetMm": str(tx), "yOffsetMm": str(ty),
            "fitResidualMm": str(fit_residual), "measuredScaleX": str(measured_sx), "measuredScaleYAbs": str(measured_sy),
            "basis": "Four corresponding rectangular outline vertices; 0.254 mm per EasyEDA native 10 mil unit, Gerber quantization residual recorded",
            "sideMirrorApplied": False}


def native_fill_paths(native: dict) -> list[list[tuple[Decimal, Decimal]]]:
    areas = [s for s in native["shape"] if s.startswith("COPPERAREA~")]
    if len(areas) != 1:
        raise ValueError(f"Expected one cached native bottom COPPERAREA, got {len(areas)}")
    field = areas[0].split("~")[10]
    groups = json.loads(field)
    paths = groups[0]
    output = []
    token_re = re.compile(r"([A-Za-z])|(-?\d+(?:\.\d+)?)")
    for path in paths:
        tokens = token_re.findall(path)
        cmds = [command for command,value in tokens if command]
        if any(c not in {"M", "L", "Z"} for c in cmds):
            raise ValueError(f"Native fill contains unsupported path command: {set(cmds)-{'M','L','Z'}}")
        current=[]; values=[]; rings=[]
        for command,value in tokens:
            if command == "M":
                if current:
                    if len(values)%2: raise ValueError("Malformed native path coordinate pair")
                    ring=list(zip(values[0::2],values[1::2]))
                    if len(ring)<3: raise ValueError("Native cached fill ring has fewer than three vertices")
                    rings.append(ring)
                current=["M"];values=[]
            elif command == "L":
                if not current: raise ValueError("Native fill line before move")
                current.append("L")
            elif command == "Z":
                if current:
                    if len(values)%2: raise ValueError("Malformed native path coordinate pair")
                    ring=list(zip(values[0::2],values[1::2]))
                    if len(ring)<3: raise ValueError("Native cached fill ring has fewer than three vertices")
                    rings.append(ring);current=[];values=[]
            elif value:
                values.append(Decimal(value))
        if current:
            if len(values)%2: raise ValueError("Malformed native path coordinate pair")
            ring=list(zip(values[0::2],values[1::2]))
            if len(ring)<3: raise ValueError("Native cached fill ring has fewer than three vertices")
            rings.append(ring)
        output.extend(rings)
    return output


def map_point(p, transform):
    return (Decimal(transform["xScale"])*p[0]+Decimal(transform["xOffsetMm"]),
            Decimal(transform["yScale"])*p[1]+Decimal(transform["yOffsetMm"]))


def cached_fill_correspondence(native: dict, regions: list[dict], transform: dict) -> dict:
    paths = native_fill_paths(native)
    if len(paths) != len(regions):
        return {"pathCount": len(paths), "regionCount": len(regions), "exactPathCorrespondence": 0,
                "pathVertexCounts": [len(x) for x in paths], "status": "COUNT_MISMATCH"}
    native_lines = []
    line_geometries = []
    for path_i, path in enumerate(paths):
        mapped = [map_point(p, transform) for p in path]
        for i in range(len(mapped)):
            a, b = mapped[i], mapped[(i+1) % len(mapped)]
            native_lines.append((path_i, a, b))
            line_geometries.append(LineString([tuple(map(float,a)), tuple(map(float,b))]))
    tree = STRtree(line_geometries)
    result = []
    for i, record in enumerate(regions):
        points = record["contours"][0]["points"]
        start = (Decimal(points[0][0])*TICK, Decimal(points[0][1])*TICK)
        end = (Decimal(points[-1][0])*TICK, Decimal(points[-1][1])*TICK)
        candidate = LineString([tuple(map(float, end)), tuple(map(float, start))])
        nearest = []
        indices = tree.query(candidate, predicate="dwithin", distance=0.005)
        for idx in indices:
            path_i, a, b = native_lines[int(idx)]
            line = line_geometries[int(idx)]
            distance = candidate.hausdorff_distance(line)
            if distance <= 0.0001:
                nearest.append({"nativePathIndex": path_i, "nativeSegment": [list(map(str,a)), list(map(str,b))],
                                "maxEndpointOrBoundaryDistanceMm": distance})
        nearby=union_all([line_geometries[int(idx)] for idx in indices]) if len(indices) else LineString()
        tolerance_buffer=nearby.buffer(0.005,quad_segs=32) if not nearby.is_empty else nearby
        coverage=(candidate.intersection(tolerance_buffer).length/candidate.length) if candidate.length and not nearby.is_empty else 0.0
        path_coverage=[]
        sampled_deviation=None
        for path_i in sorted({native_lines[int(idx)][0] for idx in indices}):
            sub=[line_geometries[int(idx)] for idx in indices if native_lines[int(idx)][0]==path_i]
            merged=union_all(sub);buff=merged.buffer(0.005,quad_segs=32)
            ratio=candidate.intersection(buff).length/candidate.length if candidate.length else 1.0
            if ratio>0.999999:
                path_coverage.append(path_i)
                if len(path_coverage)==1:
                    spacing=0.001
                    count=max(1,math.ceil(candidate.length/spacing))
                    x0,y0=candidate.coords[0];x1,y1=candidate.coords[-1]
                    xs=np.linspace(x0,x1,count+1);ys=np.linspace(y0,y1,count+1)
                    dists=shapely_distance(shapely_points(xs,ys),merged)
                    max_sample=float(np.max(dists))
                    sampled_deviation={"sampleSpacingMmMax":candidate.length/count,
                                       "sampledMaximumDeviationMm":max_sample,
                                       "conservativeMaximumDeviationUpperBoundMm":max_sample+candidate.length/count/2,
                                       "method":"uniform samples along candidate edge to the corresponding native fill linework; distance is 1-Lipschitz, so max plus half sample spacing bounds the unsampled maximum"}
        result.append({"regionIndex": i, "sourceRange": [record["g36Line"], record["g37Line"]],
                       "proposedClosingEdgeMm": [list(map(str,end)), list(map(str,start))],
                       "nativeCachedFillMatchingEdgesWithin0_0001mm": nearest,
                       "nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm":path_coverage,
                       "edgeLengthMm":candidate.length,"fractionWithin0_005mm":coverage,
                       "fullyCoveredWithin0_005mm":coverage>=0.999999,
                       "sampledNativeBoundaryDeviation":sampled_deviation})
    one_to_one = all(len(x["nativeCachedFillMatchingEdgesWithin0_0001mm"]) == 1 for x in result)
    covered_count=sum(x["fullyCoveredWithin0_005mm"] for x in result)
    return {"nativeFillPathCount": len(paths), "regionCount": len(regions),
            "nativeFillVertexCounts": [len(x) for x in paths],
            "regionVertexCounts": [len(r["contours"][0]["points"]) for r in regions],
            "candidateEdgesMatchingOneNativeSegmentWithin0_0001mm": sum(bool(x["nativeCachedFillMatchingEdgesWithin0_0001mm"]) for x in result),
            "candidateEdgesWithUniqueNativeSegmentMatchWithin0_0001mm": sum(len(x["nativeCachedFillMatchingEdgesWithin0_0001mm"]) == 1 for x in result),
            "candidateEdgesFullyWithin0_005mmOfNativeCachedFillLinework":covered_count,
            "allCandidatesWithin0_005mmOfCachedFillLinework":covered_count==len(result),
            "candidateEdgesWithUniqueCachedFillPathWithin0_005mm":sum(len(x["nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm"])==1 for x in result),
            "candidateToCachedFillPathMappingOneToOne":(all(len(x["nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm"])==1 for x in result)
                and len({x["nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm"][0] for x in result if x["nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm"]})==len(result)),
            "maximumSampledBoundaryDeviationMm":max((x["sampledNativeBoundaryDeviation"]["sampledMaximumDeviationMm"] for x in result if x["sampledNativeBoundaryDeviation"]),default=None),
            "maximumConservativeDeviationUpperBoundMm":max((x["sampledNativeBoundaryDeviation"]["conservativeMaximumDeviationUpperBoundMm"] for x in result if x["sampledNativeBoundaryDeviation"]),default=None),
            "allCandidatesMatchUniqueNativeFillEdgeWithin0_0001mm":one_to_one,
            "caveat": "Matches use stored EasyEDA copper fill from v2.0 native JSON. Cached pour geometry is design-intent evidence but is not a re-exported Gerber or CAM validation; matching edges do not approve every contour or clear-area interpretation.",
            "regions": result}


def ring_geometry_comparison(native: dict, regions: list[dict], transform: dict, fill_map: dict) -> dict:
    """Compare each candidate-closed source ring with its mapped native cached-fill ring.

    This is contour-to-contour evidence, not an assertion that either set of rings
    alone represents the full ordered copper image. Invalid geometry is reported,
    never repaired.
    """
    paths=native_fill_paths(native);rows=[]
    for i,record in enumerate(regions):
        mapping_row=fill_map["regions"][i]
        path_ids=mapping_row["nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm"]
        if len(path_ids)!=1:
            rows.append({"regionIndex":i,"sourceRange":[record["g36Line"],record["g37Line"]],"status":"NO_UNIQUE_NATIVE_FILL_PATH"})
            continue
        native_index=path_ids[0]
        ticks=record["contours"][0]["points"]
        proposed=Polygon([(int(x)*float(TICK),int(y)*float(TICK)) for x,y in ticks])
        mapped=[tuple(map(float,map_point(p,transform))) for p in paths[native_index]]
        reference=Polygon(mapped)
        row={"regionIndex":i,"sourceRange":[record["g36Line"],record["g37Line"]],
             "nativeCachedFillPathIndex":native_index,"candidatePolygonValid":bool(proposed.is_valid),
             "nativeCachedFillPolygonValid":bool(reference.is_valid),
             "candidateAreaMm2":proposed.area,"nativeCachedFillAreaMm2":reference.area,
             "candidateBoundsMm":list(proposed.bounds),"nativeCachedFillBoundsMm":list(reference.bounds),
             "candidateInteriorRingCount":len(proposed.interiors),"nativeInteriorRingCount":len(reference.interiors)}
        if proposed.is_valid and reference.is_valid:
            delta=proposed.symmetric_difference(reference)
            row.update(status="COMPARABLE",absoluteAreaDeltaMm2=abs(proposed.area-reference.area),
                signedAreaDeltaMm2=reference.area-proposed.area,symmetricDifferenceAreaMm2=delta.area,
                boundaryHausdorffMm=float(proposed.boundary.hausdorff_distance(reference.boundary)),
                symmetricDifferenceBoundsMm=list(delta.bounds) if not delta.is_empty else None)
        else:
            row.update(status="INVALID_INPUT_GEOMETRY_NO_REPAIR_OR_COMPARISON")
        rows.append(row)
    comparable=[x for x in rows if x["status"]=="COMPARABLE"]
    return {"basis":"Each open Gerber region is closed only as the separately labelled candidate polygon; compared with the uniquely mapped EasyEDA cached-fill path. No repair applied.",
            "comparisonCount":len(comparable),"invalidOrUnmatchedCount":len(rows)-len(comparable),
            "candidateRegionsWithin0_005mmBoundaryHausdorff":sum(x["boundaryHausdorffMm"]<=0.005 for x in comparable),
            "candidateRegionsOver0_005mmBoundaryHausdorff":[x["regionIndex"] for x in comparable if x["boundaryHausdorffMm"]>0.005],
            "maximumBoundaryHausdorffMm":max((x["boundaryHausdorffMm"] for x in comparable),default=None),
            "medianBoundaryHausdorffMm":float(np.median([x["boundaryHausdorffMm"] for x in comparable])) if comparable else None,
            "maximumAbsoluteAreaDeltaMm2":max((x["absoluteAreaDeltaMm2"] for x in comparable),default=None),
            "maximumSymmetricDifferenceAreaMm2":max((x["symmetricDifferenceAreaMm2"] for x in comparable),default=None),
            "medianSymmetricDifferenceAreaMm2":float(np.median([x["symmetricDifferenceAreaMm2"] for x in comparable])) if comparable else None,
            "sumOfPerRingSymmetricDifferenceAreasMm2":sum(x["symmetricDifferenceAreaMm2"] for x in comparable),
            "sumDisclaimer":"Per-ring differences overlap spatially and are not a whole-copper symmetric-difference area.",
            "regions":rows}


def render_region_overlay(native: dict, record: dict, transform: dict, fill_row: dict, target: Path) -> None:
    """Render the material difference for the worst ring-wise comparison only."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    idx=fill_row["nativeCachedFillPathIndex"]
    source=record["contours"][0]["points"]
    candidate=Polygon([(int(x)*float(TICK),int(y)*float(TICK)) for x,y in source])
    paths=native_fill_paths(native)
    reference=Polygon([tuple(map(float,map_point(p,transform))) for p in paths[idx]])
    diff=candidate.symmetric_difference(reference)
    fig,ax=plt.subplots(figsize=(12,9),dpi=220)
    for geom,color,label in ((candidate,"#2f6fb0","Gerber candidate closure"),(reference,"#e5a128","EasyEDA cached fill")):
        geoms=list(geom.geoms) if geom.geom_type=="MultiPolygon" else [geom]
        first=True
        for poly in geoms:
            x,y=poly.exterior.xy;ax.fill(x,y,color=color,alpha=.28,label=label if first else None);first=False
            ax.plot(x,y,color=color,linewidth=.8)
    geoms=list(diff.geoms) if diff.geom_type=="MultiPolygon" else [diff]
    for poly in geoms:
        if poly.geom_type!="Polygon":continue
        x,y=poly.exterior.xy;ax.fill(x,y,color="#c82424",alpha=.75,label="Symmetric difference" if poly is geoms[0] else None)
    ax.set_aspect("equal",adjustable="box");ax.set_xlabel("X (mm)");ax.set_ylabel("Y (mm)")
    ax.set_title(f"Laser v2.0 vs v2.5 candidate ring {fill_row['regionIndex']} — source lines {record['g36Line']}–{record['g37Line']}\n"
                 f"Boundary Hausdorff {fill_row['boundaryHausdorffMm']:.6f} mm; symmetric difference {fill_row['symmetricDifferenceAreaMm2']:.6f} mm²")
    ax.grid(True,linewidth=.25);ax.legend(loc="best");fig.tight_layout();target.parent.mkdir(parents=True,exist_ok=True);fig.savefig(target);plt.close(fig)


def parse_native_drill_records(native: dict, transform: dict) -> list[dict]:
    records = []
    for raw in native["shape"]:
        for chunk in raw.split("#@$"):
            if not chunk.startswith("PAD~"):
                continue
            f = chunk.split("~")
            if len(f) < 17:
                continue
            try:
                hole = Decimal(f[9])
                if hole <= 0:
                    continue
                point = map_point((Decimal(f[2]), Decimal(f[3])), transform)
                hole_length = Decimal(f[13]) if len(f)>13 and f[13] else Decimal(0)
                hole_points=[]
                if len(f)>14 and f[14]:
                    nums=[Decimal(x) for x in re.findall(r"-?\d+(?:\.\d+)?",f[14])]
                    if len(nums)>=4:
                        hole_points=[list(map(str,map_point((nums[0],nums[1]),transform))),
                                     list(map(str,map_point((nums[2],nums[3]),transform)))]
                records.append({"nativePadId": f[12], "layer": f[6], "net": f[7], "padNumber": f[8],
                                "centerMm": list(map(str, point)), "holeDiameterMm": str(2*hole*MM_PER_NATIVE_UNIT),
                                "nativeHoleUnits": str(hole),"nativeHoleLengthUnits":str(hole_length),
                                "holeLengthMm":str(hole_length*MM_PER_NATIVE_UNIT),"holePathPointsMm":hole_points})
            except (ValueError, ArithmeticError):
                continue
    return records


def drill_comparison(native: dict, transform: dict, v20dir: Path, v25dir: Path) -> dict:
    result = {"nativeThroughHolePadCount": 0, "exportHitComparison": {}}
    pads = parse_native_drill_records(native, transform)
    result["nativeThroughHolePadCount"] = len(pads)
    hit_features={}
    for label, folder in (("v2.0", v20dir), ("v2.5", v25dir)):
        hits = []; slots = []
        for name in ("Drill_PTH_Through.DRL", "Drill_PTH_Through_Via.DRL"):
            _, holes, file_slots = p2a.parse_excellon(folder/name, "drill", label)
            hits.extend(holes)
            slots.extend(file_slots)
        hit_features[label]=hits
        hit_features[f"{label}-slots"]=[(s["sourceDiameterMm"],s["pathKind"],tuple(tuple(p) for p in s["coordinatesMm"])) for s in slots]
        used = set()
        distances = []; native_diameter_ratios=[]; slot_matches=[]
        unmatched_native = []
        for hit in hits:
            candidates = []
            hx, hy = Decimal(str(hit["xMm"])), Decimal(str(hit["yMm"]))
            hd = Decimal(str(hit["sourceDiameterMm"]))
            for idx, pad in enumerate(pads):
                if Decimal(pad["nativeHoleLengthUnits"])>0:
                    continue
                px, py = map(Decimal, pad["centerMm"])
                pd = Decimal(pad["holeDiameterMm"])
                if max(abs(hx-px),abs(hy-py)) <= Decimal("0.001"):
                    candidates.append((max(abs(hx-px),abs(hy-py)),idx,pd))
            if candidates:
                _,idx,pd=min((x for x in candidates if x[1] not in used),default=min(candidates))
                used.add(idx)
                distances.append({"xMm": float(hx), "yMm": float(hy), "diameterMm": float(hd),
                                  "nativePadId": pads[idx]["nativePadId"], "maxXYResidualMm":float(min(candidates)[0]),
                                  "nativeConvertedHoleDiameterMm":float(pd),
                                  "diameterResidualMm":float(abs(pd-hd)),
                                  "diameterRatioNativeToGerber":float(pd/hd) if hd else None})
                if hd:
                    native_diameter_ratios.append(float(pd/hd))
            else:
                unmatched_native.append({"xMm": hit["xMm"], "yMm": hit["yMm"], "diameterMm": hit["sourceDiameterMm"], "toolCodes": hit["toolCodes"], "source": hit["sourceFile"]})
        matched_native_slot_ids=[]
        for slot in slots:
            ((x1,y1),(x2,y2))=slot["coordinatesMm"]
            midx=(Decimal(str(x1))+Decimal(str(x2)))/2;midy=(Decimal(str(y1))+Decimal(str(y2)))/2
            ranked=[]
            for idx,pad in enumerate(pads):
                if Decimal(pad["nativeHoleLengthUnits"])<=0:continue
                px,py=map(Decimal,pad["centerMm"])
                ranked.append((max(abs(midx-px),abs(midy-py)),idx))
            residual,idx=min(ranked)
            matched_native_slot_ids.append(pads[idx]["nativePadId"])
            native_points=[tuple(map(float,p)) for p in pads[idx]["holePathPointsMm"]]
            export_points=[(float(x1),float(y1)),(float(x2),float(y2))]
            endpoint_residual=min(max(math.dist(export_points[0],native_points[0]),math.dist(export_points[1],native_points[1])),
                                  max(math.dist(export_points[0],native_points[1]),math.dist(export_points[1],native_points[0])))
            slot_matches.append({"sourceDiameterMm":slot["sourceDiameterMm"],"centerMm":[str(midx),str(midy)],
                                 "nearestNativePadId":pads[idx]["nativePadId"],"maxMidpointResidualMm":float(residual),
                                 "within0_001mm":residual<=Decimal("0.001"),
                                 "nativeSlotEndpointResidualMm":endpoint_residual,
                                 "nativeHoleLengthMm":pads[idx]["holeLengthMm"],
                                 "nativeTotalLengthDeltaMm":(float(slot["sourceDiameterMm"])+math.hypot(float(x2)-float(x1),float(y2)-float(y1)))-float(pads[idx]["holeLengthMm"])})
        result["exportHitComparison"][label] = {"hitCount": len(hits), "slotCount": len(slots),
            "slotRecords": slots, "matchedNativePadCount": len(distances),
            "unmatchedExportHitCount": len(unmatched_native), "nativePadsMatched": len(used),
            "unmatchedNativeThroughHolePads": len(pads)-len(used),
            "maxXYResidualMm": max((d["maxXYResidualMm"] for d in distances),default=0),
            "maxHoleDiameterResidualMm":max((d["diameterResidualMm"] for d in distances),default=0),
            "nativeVsGerberHoleDiameterRatioCounts":dict(Counter(str(round(v,6)) for v in native_diameter_ratios)),
            "slotMidpointMatches":sum(x["within0_001mm"] for x in slot_matches),"slotMidpointEvidence":slot_matches,
            "nativeSlotPadsMatchedUniquely":len(set(matched_native_slot_ids))==len(slots),
            "maxNativeSlotEndpointResidualMm":max((x["nativeSlotEndpointResidualMm"] for x in slot_matches),default=0),
            "maxNativeSlotLengthResidualMm":max((abs(x["nativeTotalLengthDeltaMm"]) for x in slot_matches),default=0),
            "unmatchedExamples": unmatched_native[:20],
        }
    # Source sequence comparison is stronger than aggregate count matching.
    result["v2ExportsHitRecordsIdentical"] = (result["exportHitComparison"]["v2.0"]["hitCount"] == result["exportHitComparison"]["v2.5"]["hitCount"]
        and result["exportHitComparison"]["v2.0"]["slotCount"] == result["exportHitComparison"]["v2.5"]["slotCount"]
        and result["exportHitComparison"]["v2.0"]["unmatchedExportHitCount"] == 0
        and result["exportHitComparison"]["v2.5"]["unmatchedExportHitCount"] == 0
        and [(h["xMm"],h["yMm"],h["sourceDiameterMm"],h["toolCodes"]) for h in hit_features["v2.0"]]
            == [(h["xMm"],h["yMm"],h["sourceDiameterMm"],h["toolCodes"]) for h in hit_features["v2.5"]]
        and hit_features["v2.0-slots"]==hit_features["v2.5-slots"])
    return result


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    v20_data = checked_extract(STAGED_EXPORT, EXTRACTED)
    with zipfile.ZipFile(V25_ARCHIVE) as z25:
        v25_data = {name: z25.read(name) for name in EXPECTED_MEMBERS}
    v25_dir = ROOT / "phase2a/fixtures/extracted/gerber-prickly-laser-module-2-5"
    # Archive member bytes must reproduce the source fixture before comparison.
    for name, payload in v25_data.items():
        if (v25_dir/name).read_bytes() != payload:
            raise ValueError(f"v2.5 archive member differs from preserved extracted fixture: {name}")

    native_bytes = STAGED_NATIVE.read_bytes()
    native = json.loads(native_bytes.decode("utf-8"))
    source_manifest = {
        "v20ExportZip": {"pathAsReceived": r"E:\Gerber_Recovery\Gerber_Prickly-Laser-Module-2.0_PCB_Prickly-Laser-Module-2.0_2026-10-25.zip",
                         "sha256": sha(STAGED_EXPORT.read_bytes()), "stagedCopySha256": sha(STAGED_EXPORT.read_bytes()), "bytes": STAGED_EXPORT.stat().st_size},
        "v20NativePcb": {"pathAsReceived": r"E:\Gerber_Recovery\PCB_Prickly Laser Module 2.0.json",
                         "sha256": sha(native_bytes), "stagedCopySha256": sha(native_bytes), "bytes": len(native_bytes),
                         "editorVersion": native.get("head",{}).get("editorVersion")},
        "v25Archive": {"path": "gerbers/Gerber_Prickly-Laser-Module-2.5.zip", "sha256": sha(V25_ARCHIVE.read_bytes()), "bytes": V25_ARCHIVE.stat().st_size},
        "v25BottomCopper": {"sha256": sha(v25_data["Gerber_BottomLayer.GBL"])},
        "v20Members": {k:{"sha256":sha(v),"bytes":len(v)} for k,v in sorted(v20_data.items())},
        "externalOriginalsModified": False,
    }
    (OUT/"source-manifest.json").write_text(json.dumps(source_manifest,indent=2)+"\n",encoding="utf-8")

    print("Parsed preserved archive members and native project", flush=True)
    region_v20 = region_records(v20_data["Gerber_BottomLayer.GBL"])
    region_v25 = region_records(v25_data["Gerber_BottomLayer.GBL"])
    parsed_regions_v20=[x for x in PyGerberFile.from_file(str(EXTRACTED/"Gerber_BottomLayer.GBL")).parse()._command_buffer.commands if type(x).__name__=="Region2"]
    parsed_regions_v25=[x for x in PyGerberFile.from_file(str(v25_dir/"Gerber_BottomLayer.GBL")).parse()._command_buffer.commands if type(x).__name__=="Region2"]
    region_match = []
    for i,(a,b) in enumerate(zip(region_v20,region_v25)):
        region_match.append({"regionIndex":i,"sourceRangeV20":[a["g36Line"],a["g37Line"]],
                             "sourceRangeV25":[b["g36Line"],b["g37Line"]],
                             "commandsIdentical":a["commands"]==b["commands"],
                             "coordinateSequenceIdentical":a["contours"][0]["points"]==b["contours"][0]["points"],
                             "polarityV20":parsed_regions_v20[i].transform.polarity.value,
                             "polarityV25":parsed_regions_v25[i].transform.polarity.value})
    region_summary = {"countV20":len(region_v20),"countV25":len(region_v25),
                      "exactCommandSequenceMatches":sum(r["commandsIdentical"] for r in region_match),
                      "exactCoordinateSequenceMatches":sum(r["coordinateSequenceIdentical"] for r in region_match),
                      "sourceRangesAllSame":all(r["sourceRangeV20"]==r["sourceRangeV25"] for r in region_match),
                      "polarityCountsV20":dict(Counter(x.transform.polarity.value for x in parsed_regions_v20)),
                      "polarityCountsV25":dict(Counter(x.transform.polarity.value for x in parsed_regions_v25)),
                      "closureGapExtremaMm":{
                          "minimum":min(x["proposedRecoveryGeometry"]["gapLengthMm"] for x in recovery.json.loads((ROOT/"phase2e/results/validation-records.json").read_text())["records"] if x["boardId"]=="gerber-prickly-laser-module-2-5"),
                          "maximum":max(x["proposedRecoveryGeometry"]["gapLengthMm"] for x in recovery.json.loads((ROOT/"phase2e/results/validation-records.json").read_text())["records"] if x["boardId"]=="gerber-prickly-laser-module-2-5")},
                      "regionMatches":region_match,
                      "manufacturingApproval":"BLOCKED: exact region repetition establishes exporter reproducibility, not intended fill semantics by itself."}

    files = {}
    for name in sorted(EXPECTED_MEMBERS):
        print(f"Comparing {name}", flush=True)
        a,b=v20_data[name],v25_data[name]
        rows20,rows25=source_command_rows(a),source_command_rows(b)
        entry={"byteIdentical":a==b,"sourceSha256V20":sha(a),"sourceSha256V25":sha(b),
               "commandRowsIdenticalIgnoringCommentsApertureDefinitions":rows20==rows25,
               "commandRowCountV20":len(rows20),"commandRowCountV25":len(rows25),
               "apertureDefinitionsV20":aperture_declarations(a),"apertureDefinitionsV25":aperture_declarations(b)}
        if name in {"Gerber_TopLayer.GTL","Gerber_BottomLayer.GBL"}:
            p20,p25=EXTRACTED/name,v25_dir/name
            entry["effectiveGeometryComparison"]=primitive_differences(p20,p25)
        if name.lower().endswith(".drl"):
            l20,l25=source_command_rows(a),source_command_rows(b)
            entry["geometricBodyIdenticalAfterComments"] = l20==l25
        if name.endswith(".GBL"):
            entry["regionComparison"]=region_summary
        files[name]=entry

    native_width,native_points=native_outline(native)
    outline_name="Gerber_BoardOutlineLayer.GKO"
    gb_points=gerber_points(v20_data[outline_name])
    transform=affine_from_outlines(native_points,gb_points)
    transform["nativeOutlineWidthUnits"]=str(native_width)
    transform["nativeOutlineWidthMm"]=str(native_width*MM_PER_NATIVE_UNIT)
    transform["nativeBoundsUnits"]=[str(min(p[i] for p in native_points)) for i in (0,1)]+[str(max(p[i] for p in native_points)) for i in (0,1)]
    transform["gerberSourceCoordinateBoundsMm"]=[str(min(p[i] for p in gb_points)) for i in (0,1)]+[str(max(p[i] for p in gb_points)) for i in (0,1)]
    transform["scaleMatchesNativeUnitsToMm"]=(Decimal(transform["xScale"])==MM_PER_NATIVE_UNIT and abs(Decimal(transform["yScale"]))==MM_PER_NATIVE_UNIT)
    print("Comparing native cached copper fill", flush=True)
    native_fill=cached_fill_correspondence(native,region_v20,transform)
    native_ring_comparison=ring_geometry_comparison(native,region_v20,transform,native_fill)
    worst_region=max((x for x in native_ring_comparison["regions"] if x["status"]=="COMPARABLE"),
                     key=lambda x:x["boundaryHausdorffMm"])
    render_region_overlay(native,region_v20[worst_region["regionIndex"]],transform,worst_region,OUT/"region-079-native-vs-candidate.png")
    print("Comparing native pads and Excellon", flush=True)
    p2a.OUT = ROOT  # parse_excellon records sourceRelativePath relative to its fixture root
    drills=drill_comparison(native,transform,EXTRACTED,v25_dir)
    result={"reportVersion":"0.1","sourceManifest":"phase2f/results/source-manifest.json",
            "sourceIdentityAssessment":{"exporter":"EasyEDA Standard 6.5.51 / Gerber Generator 0.2",
                "opaqueHeaderIdentifierMatchesV20AndV25":True,
                "interpretation":"The v2.0 re-export and v2.5 archive carry identical two opaque G04 identifiers; they are recorded as matching labels, not interpreted as a documented revision ID. Exact bottom-region commands and a current v2.0 native PCB model independently link the region dataset to the re-exported v2.0 project. Overall v2.5 revision identity is not proven."},
            "coordinateTransformNativeToGerber":transform,
            "sourceRegions":region_summary,
            "nativeCachedCopperFillComparison":native_fill,
            "candidateRingVsNativeCachedFillComparison":native_ring_comparison,
            "worstRingOverlay":"phase2f/results/region-079-native-vs-candidate.png",
            "v20NativeFuseComponents":native_fuse_components(native,transform),
            "drillAndPadComparison":drills,
            "files":files,
            "coordinateOrientation":{"topAndBottomSourceCoordinatesComparedWithoutSideMirror":True,
                "nativeCanvasYToGerberYTransform":transform["yScale"],
                "bottomSideManufacturingMirrorApplied":False},
            "validationBoundary":{"exportBehaviorReproduced":region_summary["countV20"]==182 and region_summary["exactCommandSequenceMatches"]==182,
                "closureRulePromoted":False,"all182RegionsApproved":False,"machiningReady":False,
                "requiredEvidence":"Native fill correspondence plus region-specific electrical/clearance context; exact same exporter output is not a manufacturing correctness oracle."}}
    (OUT/"revision-comparison.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    concise={"regions":{"countV20":region_summary["countV20"],"countV25":region_summary["countV25"],
                         "exactCommands":region_summary["exactCommandSequenceMatches"],"exactCoordinates":region_summary["exactCoordinateSequenceMatches"],
                         "gapExtremaMm":region_summary["closureGapExtremaMm"]},
             "transform":transform,
             "nativeFill":{"nativePaths":native_fill.get("nativeFillPathCount"),
                           "candidatesWithin5um":native_fill.get("candidateEdgesFullyWithin0_005mmOfNativeCachedFillLinework"),
                           "uniqueOneToOnePathMapping":native_fill.get("candidateToCachedFillPathMappingOneToOne"),
                           "maxSampledMm":native_fill.get("maximumSampledBoundaryDeviationMm"),
                           "conservativeBoundMm":native_fill.get("maximumConservativeDeviationUpperBoundMm")},
             "drills":{label:{"circular":data["hitCount"],"slots":data["slotCount"],
                               "maxXYResidualMm":data["maxXYResidualMm"],
                               "maxDiameterResidualMm":data["maxHoleDiameterResidualMm"],
                               "maxSlotEndpointResidualMm":data["maxNativeSlotEndpointResidualMm"],
                               "maxSlotLengthResidualMm":max((abs(x["nativeTotalLengthDeltaMm"]) for x in data["slotMidpointEvidence"]),default=0)}
                       for label,data in drills["exportHitComparison"].items()},
             "copperLayers":{k:{field:v["effectiveGeometryComparison"].get(field) for field in
                         ("commandCountV20","unchangedDescriptorCount","changedPrimitiveCount","polarityRunGeometryEquivalent")}
                         for k,v in files.items() if "effectiveGeometryComparison" in v}}
    print(json.dumps(concise,indent=2))
    return result


if __name__ == "__main__":
    run()
