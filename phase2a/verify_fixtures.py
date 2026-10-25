"""Parse supplied board fixtures, measure derived geometry, classify drills, and plot QA views.

This is an audit harness, not production PCB Prep code. It preserves parser provenance,
does not filter small geometry, and reports unresolved parser/kernel cases explicitly.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import re
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle as PlotCircle
from matplotlib.patches import Polygon as PlotPolygon
from matplotlib.collections import PatchCollection
from gerbonara import ExcellonFile, GerberFile
from gerbonara import graphic_primitives as gp
from shapely import hausdorff_distance, is_valid, make_valid, union_all
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize_full

from extract_fixtures import OUT, ROOT, inspect_archive

CHORD_ERROR_MM = 0.001
DRILL_TOLERANCE_MM = 0.005
DRILL_GROUPS = (0.8, 1.0, 1.1, 1.2, 2.0, 3.0, 3.1)
ARCHIVES = (
    ROOT / "gerbers" / "Gerber_PCB_Valentine_Feb_New.zip",
    ROOT / "gerbers" / "Gerber_Prickly-Laser-Module-2.5.zip",
)
REPORT_DIR = Path(__file__).resolve().parent / "results"
VIS_DIR = REPORT_DIR / "visuals"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def quad_segs(radius: float, tolerance: float = CHORD_ERROR_MM) -> int:
    if radius <= 0 or tolerance <= 0:
        return 1
    half_step = math.acos(max(-1.0, min(1.0, 1.0 - tolerance / radius)))
    return max(1, math.ceil((math.pi / 4) / max(half_step, 1e-12)))


def sample_arc(x1: float, y1: float, x2: float, y2: float, cx: float, cy: float, clockwise: bool,
               tolerance: float = CHORD_ERROR_MM) -> tuple[list[tuple[float, float]], float]:
    radius = math.hypot(x1 - cx, y1 - cy)
    a1, a2 = math.atan2(y1 - cy, x1 - cx), math.atan2(y2 - cy, x2 - cx)
    sweep = a2 - a1
    if clockwise:
        if sweep >= 0:
            sweep -= 2 * math.pi
    elif sweep <= 0:
        sweep += 2 * math.pi
    if math.isclose(x1, x2, abs_tol=1e-12) and math.isclose(y1, y2, abs_tol=1e-12):
        sweep = -2 * math.pi if clockwise else 2 * math.pi
    if radius == 0:
        return [(x1, y1), (x2, y2)], 0.0
    step = 2 * math.acos(max(-1.0, min(1.0, 1 - tolerance / radius)))
    count = max(1, math.ceil(abs(sweep) / max(step, 1e-12)))
    actual_sagitta = radius * (1 - math.cos(abs(sweep) / (2 * count)))
    return ([(cx + radius * math.cos(a1 + sweep * i / count),
              cy + radius * math.sin(a1 + sweep * i / count)) for i in range(count + 1)], actual_sagitta)


def primitive_to_geometry(prim, tolerance: float = CHORD_ERROR_MM) -> tuple[object | None, float]:
    """Return a Shapely approximation and the largest analytic circular chord error."""
    if isinstance(prim, gp.Line):
        line = LineString([(prim.x1, prim.y1), (prim.x2, prim.y2)])
        return line.buffer(prim.width / 2, quad_segs=quad_segs(prim.width / 2, tolerance)), 0.0
    if isinstance(prim, gp.Arc):
        pts, sagitta = sample_arc(prim.x1, prim.y1, prim.x2, prim.y2, prim.cx, prim.cy, prim.clockwise, tolerance)
        line = LineString(pts)
        return line.buffer(prim.width / 2, quad_segs=quad_segs(prim.width / 2, tolerance)), sagitta
    if isinstance(prim, gp.Circle):
        q = quad_segs(prim.r, tolerance)
        actual = prim.r * (1 - math.cos(math.pi / (4 * q)))
        return Point(prim.x, prim.y).buffer(prim.r, quad_segs=q), actual
    if isinstance(prim, gp.Rectangle):
        g = box(prim.x - prim.w / 2, prim.y - prim.h / 2, prim.x + prim.w / 2, prim.y + prim.h / 2)
        from shapely import affinity
        if prim.rotation:
            g = affinity.rotate(g, prim.rotation, origin=(prim.x, prim.y), use_radians=True)
        return g, 0.0
    if isinstance(prim, gp.ArcPoly):
        pts: list[tuple[float, float]] = []
        worst = 0.0
        for p1, p2, (clockwise, center) in prim.segments:
            if clockwise is None:
                if not pts:
                    pts.append(tuple(p1))
                pts.append(tuple(p2))
            else:
                segment, sagitta = sample_arc(*p1, *p2, *center, clockwise, tolerance)
                worst = max(worst, sagitta)
                if pts and math.dist(pts[-1], segment[0]) < 1e-10:
                    pts.extend(segment[1:])
                else:
                    pts.extend(segment)
        if len(pts) < 3:
            return None, worst
        if math.dist(pts[0], pts[-1]) > 1e-10:
            pts.append(pts[0])
        return Polygon(pts), worst
    return None, 0.0


def classify_diameter(diameter: float, tolerance: float = DRILL_TOLERANCE_MM) -> str:
    if diameter <= 0:
        return "unassigned"
    for nominal in DRILL_GROUPS:
        if nominal == 0.8:
            if diameter <= 0.8 or abs(diameter - nominal) <= tolerance:
                return "PCB - Drill 0.8mm"
        elif abs(diameter - nominal) <= tolerance:
            return f"PCB - Drill {nominal:.1f}mm"
    if diameter > 3.1 + tolerance:
        return "profile-bore candidate"
    return "unassigned"


def raw_metadata(path: Path) -> dict:
    raw = path.read_text(encoding="ascii", errors="replace")
    fs = re.search(r"%FS([LT])([AI])?X(\d)(\d)Y(\d)(\d)\*%", raw, re.I)
    unit_match = re.search(r"%(MO)(MM|IN)\*%", raw, re.I)
    filefn = re.search(r"%TF\.FileFunction,([^*]+)\*%", raw, re.I)
    filepol = re.search(r"%TF\.FilePolarity,([^*]+)\*%", raw, re.I)
    coord_digits = []
    for match in re.finditer(r"(?i)(?:X|Y)([+-]?\d+(?:\.\d+)?)", raw):
        token = match.group(1)
        if "." in token:
            coord_digits.append(len(token.rsplit(".", 1)[1]))
    return {
        "gerberFormat": ({"zeroSuppression": fs.group(1), "notation": fs.group(2) or "absolute",
                           "xIntegerDigits": int(fs.group(3)), "xDecimalDigits": int(fs.group(4)),
                           "yIntegerDigits": int(fs.group(5)), "yDecimalDigits": int(fs.group(6))} if fs else None),
        "declaredUnit": (unit_match.group(2).lower() if unit_match else None),
        "observedCoordinateDecimalDigits": max(coord_digits, default=None),
        "x2FileFunction": filefn.group(1) if filefn else None,
        "x2FilePolarity": filepol.group(1) if filepol else None,
        "negativeImageMarker": bool(re.search(r"(?i)%IPNEG\*%|%TF\.FilePolarity,Negative\*%", raw)),
    }


def layer_function(name: str, declared: str | None) -> str:
    if declared:
        return declared
    n = name.lower()
    if "toplayer" in n or n.endswith(".gtl"):
        return "Copper,L1,Top (inferred from source name; no X2 FileFunction)"
    if "bottomlayer" in n or n.endswith(".gbl"):
        return "Copper,L2,Bot (inferred from source name; no X2 FileFunction)"
    if "outline" in n or n.endswith((".gko", ".gm1", ".gml")):
        return "Profile (inferred from source name; no X2 FileFunction)"
    if "soldermask" in n or n.endswith((".gts", ".gbs")):
        return "Soldermask (inferred from source name)"
    if "silkscreen" in n or n.endswith((".gto", ".gbo")):
        return "Legend (inferred from source name)"
    if "paste" in n or n.endswith((".gtp", ".gbp")):
        return "Paste (inferred from source name)"
    if "drilldrawing" in n or n.endswith(".gdd"):
        return "Drill drawing (inferred from source name)"
    if "document" in n or n.endswith(".gdl"):
        return "Documentation (inferred from source name)"
    return "Gerber function unknown"


def geometry_metrics(geom) -> dict:
    if geom is None:
        return {"empty": True, "bounds": None, "areaMm2": 0.0, "components": 0, "interiorVoids": 0, "valid": None}
    polygons = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    return {
        "empty": geom.is_empty,
        "bounds": list(geom.bounds) if not geom.is_empty else None,
        "areaMm2": geom.area,
        "components": len(polygons),
        "interiorVoids": sum(len(p.interiors) for p in polygons),
        "valid": bool(is_valid(geom)),
        "validityReason": None if is_valid(geom) else str(make_valid(geom).geom_type),
    }


def parse_gerber(path: Path, kind: str, board_id: str) -> tuple[dict, object | None, object | None, list[dict]]:
    meta = raw_metadata(path)
    caught = []
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        layer = GerberFile.open(path)
    caught.extend({"category": w.category.__name__, "message": str(w.message)} for w in observed)
    object_types = collections.Counter(type(o).__name__ for o in layer.objects)
    primitive_types = collections.Counter()
    provenance = []
    unknown = []
    geometry_repairs = []
    max_sagitta = 0.0
    shapes_by_polarity: list[tuple[bool, object]] = []
    profile_lines = []
    profile_regions = []

    for oi, obj in enumerate(layer.objects):
        try:
            primitives = list(obj.to_primitives("mm"))
        except Exception as exc:
            unknown.append({"objectIndex": oi, "objectType": type(obj).__name__, "error": repr(exc)})
            continue
        for pi, prim in enumerate(primitives):
            ptype = type(prim).__name__
            primitive_types[ptype] += 1
            geom, sagitta = primitive_to_geometry(prim)
            max_sagitta = max(max_sagitta, sagitta)
            prov = {
                "sourceFile": path.name,
                "sourceSha256": file_sha256(path),
                "objectIndex": oi,
                "primitiveIndex": pi,
                "objectType": type(obj).__name__,
                "primitiveType": ptype,
                "polarityDark": bool(getattr(prim, "polarity_dark", True)),
                "attributes": getattr(prim, "attrs", {}) or {},
            }
            provenance.append(prov)
            if geom is None:
                unknown.append({**prov, "error": "primitive type not mapped to verification geometry"})
                continue
            if geom.is_empty:
                unknown.append({**prov, "error": "parser yielded empty primitive geometry"})
                continue
            if not geom.is_valid:
                repaired = make_valid(geom)
                geometry_repairs.append({
                    **prov,
                    "repair": "Shapely/GEOS make_valid on polygonized primitive only",
                    "beforeType": geom.geom_type,
                    "beforeAreaMm2": geom.area,
                    "afterType": repaired.geom_type,
                    "afterAreaMm2": repaired.area,
                    "areaDeltaMm2": repaired.area - geom.area,
                    "symmetricDifferenceAreaMm2": None,
                    "comparisonNote": "GEOS cannot compare symmetric difference against invalid source polygon; source feature remains addressable by file hash/object/primitive index.",
                    "afterComponentCount": len(repaired.geoms) if hasattr(repaired, "geoms") else 1,
                })
                geom = repaired
            if "outline" in path.name.lower() or path.suffix.lower() in {".gko", ".gm1", ".gml"}:
                if isinstance(prim, gp.Line):
                    profile_lines.append(LineString([(prim.x1, prim.y1), (prim.x2, prim.y2)]))
                elif isinstance(prim, gp.Arc):
                    arc_pts, _ = sample_arc(prim.x1, prim.y1, prim.x2, prim.y2, prim.cx, prim.cy, prim.clockwise)
                    profile_lines.append(LineString(arc_pts))
                elif isinstance(prim, gp.ArcPoly):
                    profile_regions.append(geom)
            if bool(getattr(prim, "polarity_dark", True)):
                shapes_by_polarity.append((True, geom))
            else:
                shapes_by_polarity.append((False, geom))

    copper_geom = None
    # Preserve ordered clear/dark composition. Batch adjacent equal-polarity features only.
    current = Polygon()
    index = 0
    while index < len(shapes_by_polarity):
        dark = shapes_by_polarity[index][0]
        batch = []
        while index < len(shapes_by_polarity) and shapes_by_polarity[index][0] == dark:
            batch.append(shapes_by_polarity[index][1])
            index += 1
        combined = union_all(batch)
        current = current.union(combined) if dark else current.difference(combined)
    if meta["negativeImageMarker"]:
        unknown.append({"sourceFile": path.name, "error": "negative file image polarity found; image inversion not independently established"})
    else:
        copper_geom = current

    profile = None
    profile_stats = None
    if profile_lines:
        noded = union_all(profile_lines)
        polygons, cuts, dangles, invalid = polygonize_full(noded)
        profile = polygons
        profile_stats = {
            "closedRegions": len(polygons.geoms),
            "cutLineLengthMm": cuts.length,
            "dangleLengthMm": dangles.length,
            "invalidLineworkLengthMm": invalid.length,
            "ringsFromPolygonize": sum(1 + len(p.interiors) for p in polygons.geoms),
            "interpretation": "Gerber profile centerlines polygonized; board material polarity/cutout semantics not guaranteed by filenames alone",
        }
    elif profile_regions:
        profile = union_all(profile_regions)
        profile_stats = {"closedRegions": len(profile_regions), "interpretation": "Gerber region profile geometry"}

    raw = path.read_text(encoding="ascii", errors="replace")
    metadata = {
        "sourceFile": path.name,
        "sourceRelativePath": path.relative_to(OUT).as_posix(),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
        "sourceKind": kind,
        "detectedLayerFunction": layer_function(path.name, meta["x2FileFunction"]),
        "gerbonaraFileAttributes": getattr(layer, "file_attrs", {}),
        "gerbonaraLayerName": getattr(layer, "layer_name", None),
        "coordinateMetadata": meta,
        "objectCount": len(layer.objects),
        "objectTypes": dict(object_types),
        "primitiveCount": sum(primitive_types.values()),
        "primitiveTypes": dict(primitive_types),
        "maxCircularPolygonizationSagittaMm": max_sagitta,
        "primitiveProvenance": provenance,
        "explicitTopologyRepairs": geometry_repairs,
        "unsupportedOrUnresolved": unknown,
        "parserWarnings": caught,
        "copperOrImageGeometry": geometry_metrics(copper_geom),
        "profileGeometry": geometry_metrics(profile),
        "profileReconstruction": profile_stats,
    }
    if "toplayer" in path.name.lower() or path.suffix.lower() == ".gtl":
        metadata["side"] = "top"
    elif "bottomlayer" in path.name.lower() or path.suffix.lower() == ".gbl":
        metadata["side"] = "bottom"
    return metadata, copper_geom, profile, unknown


def tool_table(raw: str) -> dict[str, float]:
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"(?im)^T(\d+)\s*C([0-9]+(?:\.[0-9]+)?)", raw)}


def drill_role(path: Path, raw: str, parsed_plating: str) -> tuple[str, str, str]:
    upper_name = path.name.upper()
    upper = raw.upper()
    if "NON_PLATED" in upper or "NPTH" in upper_name:
        return "non-plated", "through-hole", "source TYPE/name"
    if "VIA" in upper_name or "THROUGH_VIA" in upper:
        return "plated", "via", "source layer/name"
    if "TYPE=PLATED" in upper or "PTH" in upper_name or parsed_plating == "plated":
        return "plated", "through-hole", "source TYPE/name or parser"
    return "unknown", "unknown", "no explicit source plating role"


def parse_excellon(path: Path, kind: str, board_id: str) -> tuple[dict, list[dict], list[dict]]:
    raw = path.read_text(encoding="ascii", errors="replace")
    table = tool_table(raw)
    plating_hint = "non-plated" if ("TYPE=NON_PLATED" in raw.upper() or "NPTH" in path.name.upper()) else (
        "plated" if ("TYPE=PLATED" in raw.upper() or "PTH" in path.name.upper()) else None)
    caught = []
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        layer = ExcellonFile.open(path, plated=(plating_hint == "plated") if plating_hint else None)
    caught.extend({"category": w.category.__name__, "message": str(w.message)} for w in observed)
    parsed_plating = layer.plating_type
    plating, role, confidence = drill_role(path, raw, parsed_plating)
    raw_format = getattr(layer.import_settings, "number_format", None)
    unit = str(getattr(layer.import_settings, "unit", "unknown"))
    coord_digits = [len(m.group(1)) for m in re.finditer(r"(?i)(?:X|Y)[+-]?\d+\.(\d+)", raw)]

    hits: list[dict] = []
    slots: list[dict] = []
    unknown_objects = []
    for ordinal, obj in enumerate(layer.objects):
        ap = getattr(obj, "aperture", None)
        diameter = getattr(ap, "diameter", None)
        if type(obj).__name__ == "Flash":
            entry = {
                "sourceFile": path.name,
                "sourceSha256": file_sha256(path),
                "sourceFeatureIndex": ordinal,
                "xMm": obj.x,
                "yMm": obj.y,
                "sourceDiameterMm": diameter,
                "toolCodes": [code for code, dia in table.items() if diameter is not None and abs(dia - diameter) <= 1e-9],
                "plating": plating,
                "role": role,
            }
            entry["group"] = classify_diameter(diameter) if diameter is not None else "unassigned"
            hits.append(entry)
        elif type(obj).__name__ in {"Line", "Arc"}:
            coords = []
            attrs = getattr(obj, "__dict__", {})
            if all(k in attrs for k in ("x1", "y1", "x2", "y2")):
                coords = [[attrs["x1"], attrs["y1"]], [attrs["x2"], attrs["y2"]]]
            elif all(k in attrs for k in ("x", "y")):
                coords = [[attrs["x"], attrs["y"]]]
            slots.append({
                "sourceFile": path.name,
                "sourceSha256": file_sha256(path),
                "sourceFeatureIndex": ordinal,
                "sourceDiameterMm": diameter,
                "pathKind": type(obj).__name__,
                "coordinatesMm": coords,
                "plating": plating,
                "role": "routed-slot",
            })
        else:
            unknown_objects.append({"sourceFeatureIndex": ordinal, "objectType": type(obj).__name__, "attributes": getattr(obj, "__dict__", {})})

    counts = collections.Counter(h["group"] for h in hits)
    declared_tool_counts = {}
    # Assign source tool codes by source diameter, retaining colliding codes as an explicit list.
    for code, diameter in table.items():
        declared_tool_counts[code] = {"sourceDiameterMm": diameter, "hits": sum(1 for h in hits if code in h["toolCodes"])}
    classified = sum(v for k, v in counts.items() if k != "unassigned")
    total_assignments = sum(counts.values())
    record = {
        "sourceFile": path.name,
        "sourceRelativePath": path.relative_to(OUT).as_posix(),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
        "sourceKind": kind,
        "fileComments": [line.lstrip("; ") for line in raw.splitlines() if line.lstrip().startswith(";")],
        "units": unit,
        "formatNumberDigits": list(raw_format) if raw_format else None,
        "zeroSuppression": getattr(layer.import_settings, "zeros", None),
        "observedCoordinateDecimalDigits": max(coord_digits, default=None),
        "toolTable": declared_tool_counts,
        "parserToolDiametersMm": sorted(layer.drill_sizes()),
        "parsedObjectCount": len(layer.objects),
        "parsedHitCount": len(hits),
        "parsedSlotCount": len(slots),
        "platingClassification": plating,
        "roleClassification": role,
        "classificationBasis": confidence,
        "parserPlatingState": parsed_plating,
        "unsupportedObjects": unknown_objects,
        "parserWarnings": caught,
        "groupCounts": dict(counts),
        "hitReconciliation": {
            "sourceParsedHits": len(hits),
            "groupedAssigned": classified,
            "unassigned": counts.get("unassigned", 0),
            "profileBoreCandidates": counts.get("profile-bore candidate", 0),
            "classificationTotal": total_assignments,
            "duplicatedAssignments": total_assignments - len(hits),
            "reconciles": total_assignments == len(hits) and len({(h["sourceFile"], h["sourceFeatureIndex"]) for h in hits}) == len(hits),
        },
        "hits": hits,
        "slots": slots,
    }
    return record, hits, slots


def plot_geometry(ax, geom, color: str, alpha: float, label: str | None = None) -> None:
    if geom is None or geom.is_empty:
        return
    polygons = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    patches = [PlotPolygon(list(p.exterior.coords), closed=True) for p in polygons]
    if patches:
        ax.add_collection(PatchCollection(patches, facecolor=color, edgecolor=color, alpha=alpha, linewidth=0.2,
                                          label=label))
        for poly in polygons:
            for ring in poly.interiors:
                ax.plot(*zip(*ring.coords), color="white", linewidth=0.25, alpha=min(1, alpha + 0.2))
    elif isinstance(geom, LineString):
        xs, ys = geom.xy
        ax.plot(xs, ys, color=color, alpha=alpha, label=label)


def make_preview(board_id: str, board_result: dict, layers: dict[str, object], profile_geom) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(18, 7), constrained_layout=True)
    top = layers.get("top")
    bottom = layers.get("bottom")
    hits = board_result["drillHits"]
    palette = {
        "PCB - Drill 0.8mm": "#30c5ff", "PCB - Drill 1.0mm": "#ff8c42", "PCB - Drill 1.1mm": "#8bc34a",
        "PCB - Drill 1.2mm": "#ab78d1", "PCB - Drill 2.0mm": "#f3d34a", "PCB - Drill 3.0mm": "#ee4266",
        "PCB - Drill 3.1mm": "#f17cb0", "unassigned": "#ff00ff", "profile-bore candidate": "#ff0000",
    }
    for ax, copper, title, color in ((axes[0], top, "Top copper", "#c77736"), (axes[1], bottom, "Bottom copper", "#528fca")):
        plot_geometry(ax, profile_geom, "#ec55d6", 0.18, "Board profile")
        plot_geometry(ax, copper, color, 0.85, title)
        ax.set_title(title)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)")
        ax.grid(True, linewidth=0.3, alpha=0.4)
    ax = axes[2]
    plot_geometry(ax, profile_geom, "#ec55d6", 0.16, "Board profile")
    plot_geometry(ax, top, "#d07637", 0.52, "Top")
    plot_geometry(ax, bottom, "#3c88cf", 0.52, "Bottom")
    for group, color in palette.items():
        group_hits = [h for h in hits if h["group"] == group]
        if not group_hits:
            continue
        ax.scatter([h["xMm"] for h in group_hits], [h["yMm"] for h in group_hits], s=9, c=color, label=f"{group} ({len(group_hits)})", zorder=6)
    ax.set_title("Copper overlay + drill groups")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)")
    ax.grid(True, linewidth=0.3, alpha=0.4)
    ax.legend(loc="upper left", fontsize=6, framealpha=0.85)
    if profile_geom is not None and not profile_geom.is_empty:
        minx, miny, maxx, maxy = profile_geom.bounds
        margin = max(maxx - minx, maxy - miny) * 0.04
        for panel in axes:
            panel.set_xlim(minx - margin, maxx + margin)
            panel.set_ylim(miny - margin, maxy + margin)
    fig.suptitle(f"{board_id} — parser-derived geometry; not independently verified", fontsize=13)
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    out = VIS_DIR / f"{board_id}.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    return out


def parse_board(board_manifest: dict) -> dict:
    board_id = board_manifest["boardId"]
    board_dir = OUT / board_id
    source_files = []
    top = bottom = profile = None
    unresolved = []
    drill_records = []
    all_hits = []
    all_slots = []

    for extracted in board_manifest["extractedManufacturingFiles"]:
        path = OUT / extracted["path"]
        if extracted["kind"] == "gerber":
            rec, geom, profile_geom, issues = parse_gerber(path, "gerber", board_id)
            if rec.get("side") == "top":
                top = geom
            elif rec.get("side") == "bottom":
                bottom = geom
            if "profile" in path.name.lower() or "outline" in path.name.lower() or path.suffix.lower() in {".gko", ".gm1", ".gml"}:
                profile = profile_geom if rec["profileGeometry"]["empty"] is False else profile
                rec["profileCenterlineReconstruction"] = rec["profileReconstruction"]
            source_files.append(rec)
            unresolved.extend({"file": path.name, **issue} for issue in issues)
        else:
            rec, hits, slots = parse_excellon(path, "excellon", board_id)
            drill_records.append(rec)
            all_hits.extend(hits)
            all_slots.extend(slots)
            unresolved.extend({"file": path.name, "category": "unsupported_drill_object", **item} for item in rec["unsupportedObjects"])

    drill_counts = collections.Counter(hit["group"] for hit in all_hits)
    source_hits = sum(rec["parsedHitCount"] for rec in drill_records)
    assignment_ids = [(h["sourceFile"], h["sourceFeatureIndex"]) for h in all_hits]
    reconciliation = {
        "allParsedHits": source_hits,
        "grouped": sum(v for k, v in drill_counts.items() if k not in {"unassigned", "profile-bore candidate"}),
        "unassigned": drill_counts.get("unassigned", 0),
        "profileBoreCandidates": drill_counts.get("profile-bore candidate", 0),
        "slotsSeparate": len(all_slots),
        "groupAssignmentCount": sum(drill_counts.values()),
        "uniqueSourceFeatureIds": len(set(assignment_ids)),
        "duplicates": sum(drill_counts.values()) - len(all_hits),
        "reconciles": sum(drill_counts.values()) == source_hits == len(all_hits) and len(set(assignment_ids)) == len(all_hits),
    }

    top_metric, bottom_metric, profile_metric = geometry_metrics(top), geometry_metrics(bottom), geometry_metrics(profile)
    bounds_delta = None
    if top_metric["bounds"] and bottom_metric["bounds"]:
        bounds_delta = [bottom_metric["bounds"][i] - top_metric["bounds"][i] for i in range(4)]
    profile_bounds = profile_metric["bounds"]
    summary = {
        "boardId": board_id,
        "archive": board_manifest["archive"],
        "archiveSha256": board_manifest["archiveSha256"],
        "parser": "Gerbonara 1.6.3",
        "geometryEngine": "Shapely/GEOS 3.14.1; fixed floating coordinates; no precision grid snap",
        "polygonizationToleranceTargetMm": CHORD_ERROR_MM,
        "sourceFiles": source_files,
        "drillFiles": drill_records,
        "topCopper": top_metric,
        "bottomCopper": bottom_metric,
        "boardProfile": profile_metric,
        "boardWidthMm": (profile_bounds[2] - profile_bounds[0]) if profile_bounds else None,
        "boardHeightMm": (profile_bounds[3] - profile_bounds[1]) if profile_bounds else None,
        "topBottomBoundsDifferenceMm": bounds_delta,
        "drillCountsByGroup": dict(drill_counts),
        "drillReconciliation": reconciliation,
        "drillHits": all_hits,
        "slots": all_slots,
        "unresolvedConstructs": unresolved,
        "referenceComparison": {
            "independentReferenceAvailable": False,
            "reason": "No KiCad/GerbView or independent trusted Gerber raster/vector reference was found or run; parser-derived metrics and same-parser visualization are not independent confirmation.",
            "boundingBoxDifferenceMm": None,
            "areaDifferenceMm2": None,
            "boundaryDisplacementMm": None,
            "symmetricDifferenceAreaMm2": None,
            "componentCountDifference": None,
            "interiorVoidCountDifference": None,
        },
        "coordinateRegistration": {
            "sourceCoordinatesPreserved": True,
            "transformApplied": "identity for all source Gerber and Excellon files",
            "transformEvidence": "No per-file offsets or alignment transform applied; compare source extents and drill/copper/profile overlaps in these shared raw coordinates.",
            "topBottomBoundsDifferenceMm": bounds_delta,
            "profileBounds": profile_bounds,
            "measuredBoardBoundsVsCopper": {
                "topCopperWithinProfileBounds": bool(profile_bounds and top_metric["bounds"] and all(profile_bounds[i] - 1e-6 <= top_metric["bounds"][i] <= profile_bounds[i + 2] + 1e-6 for i in (0, 1))),
                "bottomCopperWithinProfileBounds": bool(profile_bounds and bottom_metric["bounds"] and all(profile_bounds[i] - 1e-6 <= bottom_metric["bounds"][i] <= profile_bounds[i + 2] + 1e-6 for i in (0, 1))),
            },
        },
        "previewPath": None,
    }
    preview = make_preview(board_id, summary, {"top": top, "bottom": bottom}, profile)
    summary["previewPath"] = preview.relative_to(Path(__file__).resolve().parent).as_posix()
    return summary


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    manifests = [inspect_archive(p) for p in ARCHIVES]
    inventory_file = Path(__file__).resolve().parent / "fixture_inventory.json"
    inventory_file.write_text(json.dumps({"extractionPolicy": "content-sniffed Gerber/Excellon only; path/size/ratio guarded", "boards": manifests}, indent=2) + "\n", encoding="utf-8")
    boards = [parse_board(board) for board in manifests]
    result = {
        "runContext": {
            "pythonVersion": __import__("sys").version,
            "gerbonaraVersion": __import__("importlib.metadata", fromlist=["version"]).version("gerbonara"),
            "shapelyVersion": __import__("shapely").__version__,
            "geosVersion": __import__("shapely").geos_version_string,
            "sourceDate": "2026-10-24",
            "geometryReferenceStatus": "not independently verified",
        },
        "classificationRule": {
            "toleranceMm": DRILL_TOLERANCE_MM,
            "groups": list(DRILL_GROUPS),
            "rule": "Diameters <=0.800 mm or within 0.005 mm of 0.800 map to 0.8; other nominal groups require absolute difference <=0.005 mm; >3.105 mm are profile-bore candidates; all others are unassigned. Source diameter is retained.",
        },
        "boards": boards,
    }
    dest = REPORT_DIR / "parsed_geometry.json"
    dest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {dest}")
    for board in boards:
        print(board["boardId"], "top", board["topCopper"], "bottom", board["bottomCopper"], "profile", board["boardProfile"],
              "drills", board["drillReconciliation"], "unresolved", len(board["unresolvedConstructs"]), "preview", board["previewPath"])


if __name__ == "__main__":
    main()
