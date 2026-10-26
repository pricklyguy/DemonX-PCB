"""Read-only Valentine EasyEDA Pro native-fill comparison.

This adapter reads the already supplied EasyEDA .epro container and its native
JSON-lines .epcb document. Gerber commands are interpreted by the existing
Phase 2D exact scanner and strict cut-in converter; this module does not add a
second Gerber parser.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from shapely import hausdorff_distance, union_all
from shapely.affinity import scale as scale_geometry
from shapely.geometry import LineString, Polygon
from shapely.ops import nearest_points

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2d"))
import forensics  # noqa: E402

MIL_TO_MM = 25.4 / 1000.0
POUR_UNIT_TO_MM = 0.254  # PX100 -> mm conversion for the .epcb CANVAS=mm section
SOURCE_TICK_MM = 0.00001
NATIVE_ARC_SAGITTA_MM = 0.00005


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in ("..", "") for part in path.parts)


def read_project(epro_path: Path) -> dict:
    """Read required native records in memory; never extract or modify .epro."""
    raw = epro_path.read_bytes()
    with zipfile.ZipFile(epro_path) as archive:
        infos = archive.infolist()
        if any(not safe_member(item.filename) for item in infos):
            raise ValueError("UNSAFE_EPRO_MEMBER_PATH")
        project_bytes = archive.read("project.json")
        project = json.loads(project_bytes)
        if len(project.get("pcbs", {})) != 1:
            raise ValueError("EXPECTED_ONE_PCB_DOCUMENT")
        pcb_id, pcb_name = next(iter(project["pcbs"].items()))
        pcb_member = f"PCB/{pcb_id}.epcb"
        pcb_bytes = archive.read(pcb_member)

    rows = []
    for line_no, line in enumerate(pcb_bytes.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"INVALID_EPCB_RECORD line={line_no}") from exc
        if not isinstance(record, list) or not record or not isinstance(record[0], str):
            raise ValueError(f"INVALID_EPCB_RECORD_SHAPE line={line_no}")
        rows.append({"line": line_no, "record": record})

    heads = [x["record"][1] for x in rows if x["record"][0] == "HEAD" and len(x["record"]) > 1]
    return {
        "archiveBytes": raw,
        "archiveSha256": sha256(raw),
        "archiveSizeBytes": len(raw),
        "members": [
            {"name": i.filename, "size": i.file_size, "sha256": sha256(archive_read(epro_path, i.filename))}
            for i in infos if not i.is_dir()
        ],
        "projectBytesSha256": sha256(project_bytes),
        "pcbBytesSha256": sha256(pcb_bytes),
        "project": project,
        "pcbId": pcb_id,
        "pcbName": pcb_name,
        "documentHeads": heads,
        "documentRows": rows,
    }


def archive_read(path: Path, member: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(member)


def parse_poured_path(seq: list, unit_to_mm: float = POUR_UNIT_TO_MM) -> dict:
    """Decode .epcb L/ARC endpoint paths using EasyEDA's published-in-binary format logic."""
    if len(seq) < 5 or not isinstance(seq[0], (int, float)) or not isinstance(seq[1], (int, float)):
        raise ValueError("INVALID_POURED_PATH_START")
    points = [(float(seq[0]) * unit_to_mm, float(seq[1]) * unit_to_mm)]
    segments = []
    index = 2
    line_mode = False
    while index < len(seq):
        token = seq[index]
        if token == "L":
            index += 1
            if index + 1 >= len(seq):
                raise ValueError("TRUNCATED_NATIVE_LINE")
            end = (float(seq[index]) * unit_to_mm, float(seq[index + 1]) * unit_to_mm)
            index += 2
            segments.append({"kind": "line", "start": points[-1], "end": end})
            points.append(end)
            line_mode = True
        elif token in ("ARC", "CARC"):
            if index + 3 >= len(seq):
                raise ValueError("TRUNCATED_NATIVE_ARC")
            angle_deg = float(seq[index + 1])
            end = (float(seq[index + 2]) * unit_to_mm, float(seq[index + 3]) * unit_to_mm)
            segments.append({"kind": "arc", "start": points[-1], "end": end, "sweepDeg": angle_deg})
            points.append(end)
            index += 4
            line_mode = False
        elif line_mode and isinstance(token, (int, float)):
            if index + 1 >= len(seq):
                raise ValueError("TRUNCATED_IMPLICIT_NATIVE_LINE")
            end = (float(seq[index]) * unit_to_mm, float(seq[index + 1]) * unit_to_mm)
            segments.append({"kind": "line", "start": points[-1], "end": end})
            points.append(end)
            index += 2
        else:
            raise ValueError(f"UNSUPPORTED_NATIVE_PATH_TOKEN:{token!r}")

    linearized = [points[0]]
    for segment in segments:
        if segment["kind"] == "line":
            linearized.append(segment["end"])
            continue
        start, end = segment["start"], segment["end"]
        sweep = math.radians(segment["sweepDeg"])
        chord_x, chord_y = end[0] - start[0], end[1] - start[1]
        chord = math.hypot(chord_x, chord_y)
        if chord == 0 or sweep == 0 or abs(sweep) >= 2 * math.pi:
            raise ValueError("DEGENERATE_OR_UNSUPPORTED_NATIVE_ARC")
        radius = chord / (2 * math.sin(abs(sweep) / 2))
        left = (-chord_y / chord, chord_x / chord)
        half = abs(sweep) / 2
        rotated_left = (left[0] * math.cos(half) - left[1] * math.sin(half),
                        left[0] * math.sin(half) + left[1] * math.cos(half))
        if sweep > 0:
            center = (end[0] + rotated_left[0] * radius, end[1] + rotated_left[1] * radius)
        else:
            center = (start[0] - rotated_left[0] * radius, start[1] - rotated_left[1] * radius)
        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        max_angle = 2 * math.acos(max(-1.0, min(1.0, 1 - NATIVE_ARC_SAGITTA_MM / radius)))
        steps = max(1, math.ceil(abs(sweep) / max_angle))
        for n in range(1, steps + 1):
            angle = start_angle + sweep * n / steps
            linearized.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)))

    closed = points[0] == points[-1]
    closure_delta = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
    raw_values = [float(seq[0]), float(seq[1]), float(seq[-2]), float(seq[-1])]
    float_roundoff_bound = 2 * max(math.ulp(value) for value in raw_values) * unit_to_mm
    if closed and linearized[-1] != linearized[0]:
        linearized[-1] = linearized[0]
    implicit_fill_closed = closure_delta <= float_roundoff_bound
    polygon = Polygon(linearized) if implicit_fill_closed else None
    return {"sourcePoints": points, "segments": segments, "closedExactly": closed,
            "implicitFillClosedWithinFloatRoundoff": implicit_fill_closed,
            "implicitClosureDeltaMm": closure_delta, "floatRoundoffBoundMm": float_roundoff_bound,
            "polygonizedBoundary": polygon, "linearizedPoints": linearized}


def rings_to_material(rings: list[Polygon]) -> Polygon | object:
    """Classify nested closed rings by containment parity without repairing rings."""
    if any(r.is_empty or not r.is_valid for r in rings):
        raise ValueError("INVALID_NATIVE_RING")
    ordered = sorted(range(len(rings)), key=lambda i: rings[i].area, reverse=True)
    parents: dict[int, int | None] = {}
    for pos, index in enumerate(ordered):
        point = rings[index].representative_point()
        containing = [j for j in ordered[:pos] if rings[j].covers(point)]
        parents[index] = min(containing, key=lambda j: rings[j].area) if containing else None
    depth = {}
    for index in ordered:
        level, p = 0, parents[index]
        while p is not None:
            level += 1
            p = parents[p]
        depth[index] = level
    filled = []
    for index in ordered:
        if depth[index] % 2:
            continue
        holes = [rings[j].exterior for j in ordered if parents[j] == index and depth[j] == depth[index] + 1]
        filled.append(Polygon(rings[index].exterior, holes))
    return union_all(filled)


def extract_poured_material(document_rows: list[dict]) -> list[dict]:
    rows = [x["record"] for x in document_rows if x["record"][0] == "POURED" and len(x["record"]) > 5 and x["record"][4] is True]
    materials = []
    for row in rows:
        paths = [parse_poured_path(path) for path in row[5]]
        if not all(p["implicitFillClosedWithinFloatRoundoff"] and p["polygonizedBoundary"] is not None for p in paths):
            raise ValueError("OPEN_NATIVE_POURED_BOUNDARY_BEYOND_FLOAT_ROUNDOFF")
        material = rings_to_material([p["polygonizedBoundary"] for p in paths])
        materials.append({"pouredId": row[1], "pourId": row[2], "layer": None,
                          "pathCount": len(paths), "arcCount": sum(len([s for s in p["segments"] if s["kind"] == "arc"]) for p in paths),
                          "material": material, "paths": paths})
    return materials


def strict_gerber_region_material(gerber_bytes: bytes) -> list[dict]:
    source = forensics.scan(gerber_bytes.decode("ascii"))
    results = []
    for index, record in enumerate(source):
        points = record["contours"][0]["points"]
        nonzero = [points[0]]
        for a, b in zip(points, points[1:]):
            if a != b:
                nonzero.append(b)
        normalized = {**record, "contours": [{**record["contours"][0], "points": nonzero}]}
        if nonzero[0] != nonzero[-1]:
            raise ValueError("OPEN_GERBER_REGION")
        exact_ticks = forensics.region_geometry_ticks(normalized)
        material = scale_geometry(exact_ticks, xfact=SOURCE_TICK_MM / 1e-5 / forensics.SCALE,
                                  yfact=SOURCE_TICK_MM / 1e-5 / forensics.SCALE, origin=(0, 0))
        results.append({"regionIndex": index, "sourceLines": [record["g36Line"], record["g37Line"]],
                        "noOpDraws": len(points) - len(nonzero), "material": material, "source": record})
    return results


def compare_geometries(reference, candidate) -> dict:
    diff = reference.symmetric_difference(candidate)
    return {
        "referenceBoundsMm": list(reference.bounds),
        "candidateBoundsMm": list(candidate.bounds),
        "boundsDeltaMm": [candidate.bounds[i] - reference.bounds[i] for i in range(4)],
        "referenceAreaMm2": reference.area,
        "candidateAreaMm2": candidate.area,
        "areaDeltaMm2": candidate.area - reference.area,
        "symmetricDifferenceAreaMm2": diff.area,
        "boundaryHausdorffMm": hausdorff_distance(reference.boundary, candidate.boundary),
        "referenceComponents": len(reference.geoms) if hasattr(reference, "geoms") else 1,
        "candidateComponents": len(candidate.geoms) if hasattr(candidate, "geoms") else 1,
        "referenceInteriorVoids": sum(len(p.interiors) for p in (list(reference.geoms) if hasattr(reference, "geoms") else [reference]) if p.geom_type == "Polygon"),
        "candidateInteriorVoids": sum(len(p.interiors) for p in (list(candidate.geoms) if hasattr(candidate, "geoms") else [candidate]) if p.geom_type == "Polygon"),
    }


def boundary_rings(geometry) -> list[LineString]:
    polygons = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    return [ring for polygon in polygons if polygon.geom_type == "Polygon"
            for ring in [LineString(polygon.exterior.coords),
                         *[LineString(interior.coords) for interior in polygon.interiors]]]


def greedy_ring_correspondence(reference, candidate) -> dict:
    left, right = boundary_rings(reference), boundary_rings(candidate)
    if len(left) != len(right):
        return {"referenceRingCount": len(left), "candidateRingCount": len(right),
                "oneToOneRingCount": min(len(left), len(right)), "matches": [],
                "status": "RING_COUNT_MISMATCH"}
    pairs = sorted((left[i].hausdorff_distance(right[j]), i, j)
                   for i in range(len(left)) for j in range(len(right)))
    assigned_left, assigned_right, matches = set(), set(), []
    for distance, i, j in pairs:
        if i in assigned_left or j in assigned_right:
            continue
        assigned_left.add(i); assigned_right.add(j)
        matches.append({"gerberRingIndex": i, "nativeRingIndex": j, "hausdorffMm": distance})
        if len(matches) == len(left):
            break
    matches.sort(key=lambda item: item["hausdorffMm"], reverse=True)
    return {"referenceRingCount": len(left), "candidateRingCount": len(right),
            "oneToOneRingCount": len(matches), "assignment": "greedy minimum Hausdorff pairing; diagnostic only",
            "maximumRingHausdorffMm": matches[0]["hausdorffMm"] if matches else 0.0,
            "top10LargestRingDeltas": matches[:10], "status": "MATCHED" if len(matches) == len(left) else "INCOMPLETE"}


def diagnostic_offsets(reference, candidate, distances=(0.05, 0.1, 0.2)) -> list[dict]:
    output = []
    for distance in distances:
        ref = reference.buffer(-distance, quad_segs=32)
        cand = candidate.buffer(-distance, quad_segs=32)
        output.append({"distanceMm": distance, "referenceAreaMm2": ref.area, "candidateAreaMm2": cand.area,
                       "symmetricDifferenceAreaMm2": ref.symmetric_difference(cand).area,
                       "referenceComponents": len(ref.geoms) if hasattr(ref, "geoms") else (0 if ref.is_empty else 1),
                       "candidateComponents": len(cand.geoms) if hasattr(cand, "geoms") else (0 if cand.is_empty else 1),
                       "purpose": "diagnostic morphology only; not cutter compensation or toolpath"})
    return output


def boundary_vertices(geometry):
    polygons = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    for polygon in polygons:
        if polygon.geom_type != "Polygon":
            continue
        yield from polygon.exterior.coords
        for ring in polygon.interiors:
            yield from ring.coords


def sampled_boundary_extrema(reference, candidate, limit=20):
    """Report source vertices furthest from the opposite boundary, not a proof of Hausdorff."""
    output = {}
    for label, left, right in (("gerberToNative", reference.boundary, candidate.boundary),
                               ("nativeToGerber", candidate.boundary, reference.boundary)):
        rows = []
        for x, y in boundary_vertices(reference if label == "gerberToNative" else candidate):
            point = __import__("shapely").Point(x, y)
            nearest = nearest_points(point, right)[1]
            rows.append({"pointMm": [x, y], "nearestOppositeBoundaryMm": [nearest.x, nearest.y],
                         "distanceMm": point.distance(nearest)})
        output[label] = sorted(rows, key=lambda row: row["distanceMm"], reverse=True)[:limit]
    return output


def render_overlays(bottom, poured, comparisons, out_dir):
    """High-resolution inspection figures; source/results remain in the ignored results tree."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    output = []
    for row in comparisons:
        index = row["gerberRegion"]
        gerber = bottom[index]["material"]
        native = poured[index]["material"]
        diff = gerber.symmetric_difference(native)
        minx, miny, maxx, maxy = gerber.bounds
        fig, ax = plt.subplots(figsize=(12, 9), dpi=220)
        _draw_geometry(ax, native, "#24b6a5", "Saved EasyEDA copper fill", 0.48)
        _draw_geometry(ax, gerber, "#d88138", "Strict Gerber cut-in reconstruction", 0.42)
        _draw_geometry(ax, diff, "#f044c2", "Symmetric difference", 0.95)
        # Boundary-only strokes keep coincident sections distinguishable from filled material.
        for geom, color, label in ((gerber.boundary, "#ffb15d", "Gerber boundary"),
                                   (native.boundary, "#43e5d3", "Native boundary")):
            lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
            ax.add_collection(LineCollection([list(line.coords) for line in lines], colors=color,
                                             linewidths=0.65, label=label))
        pad = max(maxx - minx, maxy - miny) * 0.045
        ax.set_xlim(minx - pad, maxx + pad); ax.set_ylim(miny - pad, maxy + pad)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("Board X (mm)"); ax.set_ylabel("Board Y (mm)")
        metrics = row["metrics"]
        ax.set_title(f"Valentine bottom region {index}: native saved fill vs Gerber reconstruction\n"
                     f"Δarea {metrics['areaDeltaMm2']:.9f} mm² · symmetric difference "
                     f"{metrics['symmetricDifferenceAreaMm2']:.9f} mm² · boundary Hausdorff "
                     f"{metrics['boundaryHausdorffMm']:.9f} mm")
        ax.grid(True, linewidth=0.35, alpha=0.35); ax.legend(loc="upper right", fontsize=8)
        ax.text(0.01, 0.01, "Diagnostic comparison only — manufacturing remains blocked",
                transform=ax.transAxes, fontsize=8, color="#7e1827",
                bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#7e1827"})
        target = out_dir / f"valentine-bottom-region-{index}-comparison.png"
        fig.savefig(target, bbox_inches="tight"); plt.close(fig)
        output.append(str(target))
        # A dimensioned local crop exposes deviations hidden at the whole-board scale.
        point = max(row["sampledBoundaryExtrema"]["gerberToNative"],
                    key=lambda item: item["distanceMm"])
        x, y = point["pointMm"]
        qx, qy = point["nearestOppositeBoundaryMm"]
        local_pad = 0.12
        fig, ax = plt.subplots(figsize=(9, 7), dpi=240)
        _draw_geometry(ax, diff, "#ed35c4", "Symmetric-difference material", 0.88)
        for geom, color, label in ((gerber.boundary, "#c8792f", "Gerber reconstructed boundary"),
                                   (native.boundary, "#039f91", "Saved native-fill boundary")):
            lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
            ax.add_collection(LineCollection([list(line.coords) for line in lines], colors=color,
                                             linewidths=1.2, label=label))
        ax.plot([x, qx], [y, qy], color="#202020", linewidth=0.8, linestyle="--", label="sampled boundary displacement")
        ax.scatter([x, qx], [y, qy], c=["#d6812b", "#02a899"], s=28, zorder=10)
        ax.annotate(f"Gerber sample ({x:.6f}, {y:.6f})", (x, y), xytext=(8, 9),
                    textcoords="offset points", fontsize=8)
        ax.annotate(f"native nearest ({qx:.6f}, {qy:.6f})\n{point['distanceMm']:.6f} mm sampled distance",
                    (qx, qy), xytext=(8, -27), textcoords="offset points", fontsize=8)
        ax.set_xlim(x-local_pad, x+local_pad); ax.set_ylim(y-local_pad, y+local_pad)
        ax.set_aspect("equal", adjustable="box"); ax.grid(True, linewidth=0.4, alpha=0.5)
        ax.set_xlabel("Board X (mm)"); ax.set_ylabel("Board Y (mm)")
        ax.set_title(f"Valentine bottom region {index}: localized boundary discrepancy\n"
                     "Sampled vertex displacement (not the Hausdorff maximizing point)")
        ax.legend(loc="best", fontsize=8)
        local_target = out_dir / f"valentine-bottom-region-{index}-local-discrepancy.png"
        fig.savefig(local_target, bbox_inches="tight"); plt.close(fig)
        output.append(str(local_target))
    return output


def _draw_geometry(ax, geometry, color, label, alpha):
    polygons = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    for index, polygon in enumerate(polygons):
        if polygon.geom_type != "Polygon":
            continue
        ax.fill(*zip(*polygon.exterior.coords), facecolor=color, alpha=alpha,
                edgecolor="none", label=label if index == 0 else None)
        for hole in polygon.interiors:
            ax.fill(*zip(*hole.coords), facecolor="white", alpha=1, edgecolor="none")


def affine_via_registration(native_vias: list, gerber_drills: list, pth_drills: list) -> dict:
    native_mm = [(float(v[5]) * MIL_TO_MM, float(v[6]) * MIL_TO_MM, float(v[7]) * MIL_TO_MM) for v in native_vias]
    matched = []
    for x, y, diameter in native_mm:
        def nearest(rows):
            return min(rows, key=lambda h: math.hypot(h["xMm"] - x, h["yMm"] - y), default=None)
        via = nearest(gerber_drills)
        pth = nearest(pth_drills)
        via_residual = math.hypot(via["xMm"] - x, via["yMm"] - y) if via else None
        pth_residual = math.hypot(pth["xMm"] - x, pth["yMm"] - y) if pth else None
        matched.append({"nativeMm": [x, y], "nativeDrillDiameterMm": diameter,
                        "viaExportNearestCenterResidualMm": via_residual,
                        "pthExportNearestCenterResidualMm": pth_residual,
                        "viaCenterMatches": via_residual is not None and via_residual <= 1e-9,
                        "pthDuplicateCenterMatches": pth_residual is not None and pth_residual <= 1e-9,
                        "viaExportDiameterDeltaMm": via["sourceDiameterMm"] - diameter if via else None})
    return {"coordinateUnit": "mil", "unitScaleMm": MIL_TO_MM, "rotationDegrees": 0,
            "translationMm": [0, 0], "reflection": False, "nativeViaCount": len(native_vias),
            "matchedViaAnchors": sum(m["viaCenterMatches"] for m in matched),
            "matchedDuplicatePthAnchors": sum(m["pthDuplicateCenterMatches"] for m in matched),
            "anchors": matched}


def native_outline_metrics(outline_records: list, gerber_profile_sha256: str) -> dict:
    """Measure native POLY vertices and link an independent prior PyGerber profile baseline by hash."""
    vertices = []
    for record in outline_records:
        sequence = record[6]
        index = 0
        while index < len(sequence):
            if sequence[index] in ("ARC", "CARC"):
                raise ValueError("NATIVE_OUTLINE_ARC_EXTREMA_NOT_IMPLEMENTED")
            if sequence[index] == "L":
                index += 1
                continue
            if index + 1 >= len(sequence):
                raise ValueError("TRUNCATED_NATIVE_OUTLINE_POINT")
            vertices.append((float(sequence[index]) * MIL_TO_MM,
                             float(sequence[index + 1]) * MIL_TO_MM))
            index += 2
    if not vertices:
        raise ValueError("EMPTY_NATIVE_OUTLINE")
    bounds = [min(p[0] for p in vertices), min(p[1] for p in vertices),
              max(p[0] for p in vertices), max(p[1] for p in vertices)]
    baseline_path = ROOT / "phase2c" / "results" / "profile-comparison.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    profile = next((x for x in baseline.get("profiles", [])
                    if x.get("sourceSha256") == gerber_profile_sha256), None)
    if profile is None:
        return {"nativeBoundsMm": bounds, "nativeVertexCount": len(vertices),
                "independentGerberBoundsMm": None, "boundsDeltaMm": None,
                "referenceStatus": "NOT_LINKED_TO_ARCHIVED_PROFILE_HASH"}
    reference = profile["centerlineMetrics"]["boundsMm"]
    return {"nativeBoundsMm": bounds, "nativeVertexCount": len(vertices),
            "independentGerberBoundsMm": reference,
            "boundsDeltaMm": [bounds[i] - reference[i] for i in range(4)],
            "referenceParser": "PyGerber 2.4.3 Phase 2C profile comparison",
            "referenceSourceSha256": profile["sourceSha256"], "referenceStatus": "HASH_MATCHED"}


def run(epro_path: Path, archive_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    native = read_project(epro_path)
    archive_bytes = archive_path.read_bytes()
    with zipfile.ZipFile(archive_path) as z:
        gerber_members = {name: z.read(name) for name in z.namelist()
                          if name.endswith((".GBL", ".GTL", ".GKO", ".DRL"))}
    bottom = strict_gerber_region_material(gerber_members["Gerber_BottomLayer.GBL"])
    poured = extract_poured_material(native["documentRows"])
    if len(bottom) != len(poured):
        raise ValueError(f"REGION_COUNT_MISMATCH gerber={len(bottom)} native={len(poured)}")
    # Match by area only to propose the correspondence, then verify full boundary metrics.
    remaining = set(range(len(poured)))
    comparisons = []
    for source in bottom:
        native_index = min(remaining, key=lambda j: abs(poured[j]["material"].area - source["material"].area))
        remaining.remove(native_index)
        candidate = poured[native_index]
        comparison = compare_geometries(source["material"], candidate["material"])
        ring_match = greedy_ring_correspondence(source["material"], candidate["material"])
        comparisons.append({"gerberRegion": source["regionIndex"], "gerberSourceLines": source["sourceLines"],
                            "gerberNoOpDraws": source["noOpDraws"], "nativePouredId": candidate["pouredId"],
                            "nativePathCount": candidate["pathCount"], "nativeArcCount": candidate["arcCount"],
                            "metrics": comparison, "boundaryRingCorrespondence": ring_match,
                            "sampledBoundaryExtrema": sampled_boundary_extrema(source["material"], candidate["material"]),
                            "nativePathClosure": [{"pathIndex": i, "closedExactly": path["closedExactly"],
                                "endToStartDeltaMm": path["implicitClosureDeltaMm"],
                                "floatRoundoffBoundMm": path["floatRoundoffBoundMm"],
                                "fillClosureAcceptedByNativeSemantics": path["implicitFillClosedWithinFloatRoundoff"]}
                                for i, path in enumerate(candidate["paths"]) if not path["closedExactly"]]})
    doc_rows = [x["record"] for x in native["documentRows"]]
    vias = [r for r in doc_rows if r[0] == "VIA"]
    gerbonara_parsed = None
    from gerbonara.excellon import ExcellonFile
    pth = gerber_members["Drill_PTH_Through.DRL"]
    via_drill = gerber_members["Drill_PTH_Through_Via.DRL"]
    # Native via anchors compare against the explicitly named native-via drill export.
    temp_pth = out_dir / "_read-only-extracted-pth.drl"
    temp_via = out_dir / "_read-only-extracted-via.drl"
    temp_pth.write_bytes(pth)
    temp_via.write_bytes(via_drill)
    drill_sets = []
    for drill_path in (temp_pth, temp_via):
        drill_objects = []
        excellon = ExcellonFile.open(drill_path)
        for obj in excellon.objects:
            if type(obj).__name__ == "ExcellonTool":
                continue
            if hasattr(obj, "x") and hasattr(obj, "y"):
                drill_objects.append({"xMm": float(obj.x), "yMm": float(obj.y),
                                      "sourceDiameterMm": float(getattr(getattr(obj, "tool", None), "diameter", 0.0))})
        drill_sets.append(drill_objects)
    pth_drill_objects, via_drill_objects = drill_sets
    registration = affine_via_registration(vias, via_drill_objects, pth_drill_objects)
    profile_sha = sha256(gerber_members["Gerber_BoardOutlineLayer.GKO"])
    outline_metrics = native_outline_metrics(
        [r for r in doc_rows if r[0] == "POLY" and len(r) > 6 and r[4] == 11], profile_sha)
    overlay_paths = render_overlays(bottom, poured, comparisons, out_dir)
    result = {
        "reportVersion": "2J-0.1",
        "nativeProject": {"path": str(epro_path), "archiveSha256": native["archiveSha256"],
                          "archiveSizeBytes": native["archiveSizeBytes"], "projectJsonSha256": native["projectBytesSha256"],
                          "pcbMemberSha256": native["pcbBytesSha256"], "pcbId": native["pcbId"], "pcbName": native["pcbName"],
                          "editorVersion": native["project"].get("config", {}).get("editorVersion"),
                          "documentHead": native["documentHeads"], "memberHashes": native["members"]},
        "gerberArchive": {"path": str(archive_path), "archiveSha256": sha256(archive_bytes),
                          "archiveSizeBytes": len(archive_bytes),
                          "sourceHashes": {n: sha256(b) for n, b in gerber_members.items()}},
        "independentAnchorRegistration": registration,
        "outlineBoundsRegistration": outline_metrics,
        "nativeProjectStatistics": {
            "recordTypeCounts": dict(Counter(r[0] for r in doc_rows)),
            "layerRecords": [r for r in doc_rows if r[0] == "LAYER" and r[1] in (1, 2, 11)],
            "outlinePolygons": [r for r in doc_rows if r[0] == "POLY" and len(r) > 4 and r[4] == 11],
            "pourDefinitions": [r for r in doc_rows if r[0] == "POUR"],
            "nativeViaRecords": vias,
            "savedCopperFillCount": len(poured),
            "savedCopperFillPathCounts": [p["pathCount"] for p in poured],
        },
        "regionComparisons": comparisons,
        "diagnosticOverlays": overlay_paths,
        "offsetDiagnostics": [
            {"region": c["gerberRegion"], "offsets": diagnostic_offsets(
                bottom[c["gerberRegion"]]["material"], poured[next(j for j,p in enumerate(poured) if p["pouredId"] == c["nativePouredId"])]["material"])}
            for c in comparisons
        ],
        "sourceRevisionAssessment": "PARTIAL",
        "manufacturingApproval": "WITHHELD",
    }
    (out_dir / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "phase2d")]
    parser = argparse.ArgumentParser()
    parser.add_argument("--epro", type=Path, default=Path(r"E:\Gerber_Recovery\ProPrj_PCB_Valentine_2026_2026-02-05.epro"))
    parser.add_argument("--gerber-zip", type=Path, default=root / "gerbers" / "Gerber_PCB_Valentine_Feb_New.zip")
    parser.add_argument("--out", type=Path, default=root / "phase2j" / "results")
    args = parser.parse_args()
    result = run(args.epro, args.gerber_zip, args.out)
    print(json.dumps({"nativeSha256": result["nativeProject"]["archiveSha256"],
                      "gerberSha256": result["gerberArchive"]["archiveSha256"],
                      "registration": result["independentAnchorRegistration"],
                      "regions": result["regionComparisons"],
                      "offsets": result["offsetDiagnostics"]}, indent=2))
