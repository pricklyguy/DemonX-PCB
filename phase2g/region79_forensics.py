"""Read-only Phase 2G region 79 discrepancy measurements and annotated plot."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely import hausdorff_distance
from shapely.ops import nearest_points

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / x) for x in ("phase2f", "phase2d")]
import compare_revision as phase2f
import forensics

OUT = ROOT / "phase2g/results"
GBL = ROOT / "phase2f/fixtures/extracted/laser-v2.0/Gerber_BottomLayer.GBL"
NATIVE_FILE = ROOT / "phase2f/fixtures/laser-v2.0-pcb.json"
REVISION_JSON = ROOT / "phase2f/results/revision-comparison.json"
PHASE2D_JSON = ROOT / "phase2d/results/region-evidence.json"


def _point_segment_distance(point, line: LineString):
    return point.distance(line)


def measure():
    source_bytes = GBL.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_text = source_bytes.decode("ascii")
    region = forensics.scan(source_text)[79]
    comparison = json.loads(REVISION_JSON.read_text(encoding="utf-8"))
    native = json.loads(NATIVE_FILE.read_text(encoding="utf-8"))
    registration = comparison["coordinateTransformNativeToGerber"]
    paths = phase2f.native_fill_paths(native)
    path_id = 3
    source_ticks = region["contours"][0]["points"]
    source_mm = [(int(x)*1e-5, int(y)*1e-5) for x, y in source_ticks]
    candidate = Polygon(source_mm)
    native_mm = [tuple(map(float, phase2f.map_point(p, registration))) for p in paths[path_id]]
    cached_fill = Polygon(native_mm)
    diff = candidate.symmetric_difference(cached_fill)
    boundaries = [candidate.boundary, cached_fill.boundary]
    source_lines = region["contours"][0]["segmentLines"]

    # Identify contiguous Gerber command spans whose source contour is more than
    # 5 micrometres from the mapped cached-fill boundary. Sample at <= 0.005 mm.
    segment_rows = []
    for i, (a, b) in enumerate(zip(candidate.exterior.coords, candidate.exterior.coords[1:])):
        line = LineString([a, b])
        sample_count = max(1, math.ceil(line.length / 0.005))
        sample_distances = []
        sample_points = []
        for k in range(sample_count + 1):
            point = line.interpolate(k / sample_count, normalized=True)
            sample_distances.append(point.distance(cached_fill.boundary))
            sample_points.append(point)
        at = int(np.argmax(sample_distances))
        segment_rows.append({"segmentIndex": i, "sourceLine": source_lines[i] if i < len(source_lines) else None,
                             "edgeType": "Gerber source segment" if i < len(source_lines) else "hypothetical closing edge",
                             "startMm": list(a), "endMm": list(b),
                             "sampleSpacingMmMax": line.length/sample_count,
                             "sampledMaxBoundaryDistanceMm": sample_distances[at],
                             "sampledMaxPointMm": [sample_points[at].x, sample_points[at].y]})
    mismatching = [r for r in segment_rows if r["sampledMaxBoundaryDistanceMm"] > 0.005]
    spans = []
    for item in mismatching:
        if not spans or item["segmentIndex"] > spans[-1]["lastSegmentIndex"] + 1:
            spans.append({"firstSegmentIndex": item["segmentIndex"], "lastSegmentIndex": item["segmentIndex"],
                          "rows": [item]})
        else:
            spans[-1]["lastSegmentIndex"] = item["segmentIndex"]
            spans[-1]["rows"].append(item)
    mismatch_spans = []
    for span in spans:
        rows = span.pop("rows")
        first, last = rows[0], rows[-1]
        worst = max(rows, key=lambda x: x["sampledMaxBoundaryDistanceMm"])
        span.update({"firstGerberLine": first["sourceLine"], "lastGerberLine": last["sourceLine"],
                     "startMm": first["startMm"], "endMm": last["endMm"],
                     "maximumSampledBoundaryDistanceMm": worst["sampledMaxBoundaryDistanceMm"],
                     "maximumPointMm": worst["sampledMaxPointMm"],
                     "samplingSpacingMaxMm": max(x["sampleSpacingMmMax"] for x in rows)})
        mismatch_spans.append(span)

    # GEOS densified Hausdorff result and corresponding nearest boundary points.
    hd = float(hausdorff_distance(candidate.boundary, cached_fill.boundary, densify=0.25))
    nearest_pair = None
    for direction_name, source_geom, other_geom, coords in (
        ("Gerber-to-native", candidate.boundary, cached_fill.boundary, list(candidate.exterior.coords)),
        ("native-to-Gerber", cached_fill.boundary, candidate.boundary, list(cached_fill.exterior.coords)),
    ):
        for segment_index, (a, b) in enumerate(zip(coords, coords[1:])):
            line = LineString([a, b])
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                point = line.interpolate(fraction, normalized=True)
                other_point = nearest_points(point, other_geom)[1]
                distance = point.distance(other_point)
                if nearest_pair is None or distance > nearest_pair["distanceMm"]:
                    nearest_pair = {"direction": direction_name, "distanceMm": distance,
                                    "segmentIndex": segment_index,
                                    "pointMm": [point.x, point.y],
                                    "nearestPointMm": [other_point.x, other_point.y]}
    # Identify exact source command segment nearest to the Hausdorff extremum.
    closest_source_segment = min(
        ((LineString([a,b]).distance(Point(nearest_pair["nearestPointMm"])), i, a, b)
         for i, (a,b) in enumerate(zip(candidate.exterior.coords, candidate.exterior.coords[1:]))),
        key=lambda row: row[0])
    nearest_pair["nearestGerberSegmentIndex"] = closest_source_segment[1]
    nearest_pair["nearestGerberLine"] = (source_lines[closest_source_segment[1]]
                                          if closest_source_segment[1] < len(source_lines) else None)
    nearest_pair["nearestGerberSegmentMm"] = [list(closest_source_segment[2]), list(closest_source_segment[3])]
    nearest_native_segment = min(
        ((LineString([a,b]).distance(Point(nearest_pair["pointMm"])), i, a, b)
         for i, (a,b) in enumerate(zip(cached_fill.exterior.coords, cached_fill.exterior.coords[1:]))),
        key=lambda row: row[0])
    nearest_pair["nearestNativeSegmentIndex"] = nearest_native_segment[1]
    nearest_pair["nearestNativeSegmentMm"] = [list(nearest_native_segment[2]), list(nearest_native_segment[3])]

    diff_parts = [diff] if diff.geom_type == "Polygon" else list(diff.geoms)
    largest = max((p for p in diff_parts if p.geom_type == "Polygon"), key=lambda p: p.area)
    xmin, ymin, xmax, ymax = largest.bounds
    phase2d = json.loads(PHASE2D_JSON.read_text(encoding="utf-8"))
    laser = next(b for b in phase2d if b["boardId"] == "gerber-prickly-laser-module-2-5")
    parser_region = laser["regions"][79]
    all_comparisons = comparison["candidateRingVsNativeCachedFillComparison"]["regions"]
    other = [x for x in all_comparisons if x["regionIndex"] != 79]
    report = {
        "recordVersion": "0.1",
        "source": {"archiveV20Sha256": "d17abf51ea793d7151f7cb452db5bc97a0a1a2d1f1859414c1b37a13c884e1c8",
                   "bottomGerberSha256": source_hash, "file": "Gerber_BottomLayer.GBL",
                   "regionIndex": 79, "g36Line": region["g36Line"], "g37Line": region["g37Line"],
                   "sourceCoordinateUnit": "mm", "sourceTickMm": "0.00001",
                   "pointCount": len(source_mm), "drawSegmentCount": len(source_lines),
                   "allRegionCommandsLinear": parser_region["interpolationModes"] == ["G01"],
                   "gerbonaraSegmentCount": parser_region["gerbonara"]["segmentCount"],
                   "pygerberSegmentCount": parser_region["pygerber"]["segmentCount"],
                   "gerbonaraMaxCoordinateDeltaMm": parser_region["gerbonara"]["maxCoordinateDeltaMm"],
                   "pygerberMaxCoordinateDeltaMm": parser_region["pygerber"]["maxCoordinateDeltaMm"]},
        "candidateClosure": {"fromEndMm": list(source_mm[-1]), "toStartMm": list(source_mm[0]),
                             "lengthMm": LineString([source_mm[-1], source_mm[0]]).length,
                             "cachedFillPathIndex": path_id,
                             "cachedFillBoundaryDistanceUpperBoundMm":
                                 comparison["nativeCachedCopperFillComparison"]["maximumConservativeDeviationUpperBoundMm"],
                             "candidatePolygonValid": candidate.is_valid},
        "cachedFillPath": {"nativeShapeKind": "COPPERAREA", "layer": "bottom copper", "net": "GND",
                           "pathIndex": path_id, "vertexCount": len(native_mm),
                           "polygonValid": cached_fill.is_valid,
                           "nativeToGerberTransform": registration},
        "candidateRingComparison": {"candidateAreaMm2": candidate.area, "cachedFillAreaMm2": cached_fill.area,
                                     "symmetricDifferenceAreaMm2": diff.area,
                                     "boundaryHausdorffMm": hd,
                                     "candidateBoundsMm": list(candidate.bounds),
                                     "cachedFillBoundsMm": list(cached_fill.bounds),
                                     "differenceComponentCount": len(diff_parts),
                                     "largestDifferenceComponentAreaMm2": largest.area,
                                     "largestDifferenceComponentBoundsMm": [xmin,ymin,xmax,ymax],
                                     "largestDifferenceWidthMm": xmax-xmin,
                                     "largestDifferenceHeightMm": ymax-ymin,
                                     "largestDifferenceCentroidMm": [largest.centroid.x, largest.centroid.y]},
        "maximumBoundaryDisplacement": nearest_pair,
        "sourceLineSpansBeyond0_005mmBoundaryDistance": mismatch_spans,
        "other181RingCheck": {"numberOfOtherRegions": len(other),
                               "countOver0_005mmBoundaryHausdorff": sum(x["boundaryHausdorffMm"] > .005 for x in other),
                               "maximumBoundaryHausdorffMm": max(x["boundaryHausdorffMm"] for x in other),
                               "maximumRegionIndex": max(other, key=lambda x:x["boundaryHausdorffMm"])["regionIndex"],
                               "comparisonBasis": "Phase 2F candidate polygon vs its one-to-one matched cached path; no repair"},
        "causeAssessment": {
            "globalCoordinateTransformError": "Not supported by evidence: four-corner outline fit residual 0.0000011 mm; other 181 rings compare within 0.001489 mm.",
            "GerberParserCommandLoss": "Not indicated: source scanner, Gerbonara and PyGerber segment counts and coordinates agree for region 79.",
            "GerberArcPolygonization": "Not indicated as the direct cause in this region: source boundary commands are all linear G01 and source ticks are preserved.",
            "NativeCacheStalenessOrDesignIntent": "Unresolved: native fill is a saved COPPERAREA cache without an authenticated repour/export revision record, and the v2.5 native PCB is unavailable.",
            "SourceExportIncompleteOrChanged": "Unresolved: the v2.0 and v2.5 Gerber exports match each other; no v2.5 native design state is available to distinguish exporter omission from genuine saved-design differences.",
            "manufacturingEligibility": "BLOCKED; no automatic closure approval or machining operation is enabled."},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "region79-analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    render(candidate, cached_fill, diff, largest, report, OUT / "region79-discrepancy-annotated.png")
    return report


def render(candidate, cached, diff, largest, report, output: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 8), dpi=220, gridspec_kw={"width_ratios": [1, 1.25]})
    ax = axes[0]
    for geom, color, label in ((candidate, "#57a6ff", "Gerber region + hypothetical straight closure"),
                               (cached, "#ffc857", "EasyEDA v2.0 saved cached fill path 3")):
        x, y = geom.exterior.xy
        ax.plot(x, y, color=color, lw=.8, alpha=.9, label=label)
    end, start = report["candidateClosure"]["fromEndMm"], report["candidateClosure"]["toStartMm"]
    ax.annotate("", xy=start, xytext=end, arrowprops={"arrowstyle":"<->", "color":"#38d6c3", "lw":1.4})
    ax.text((start[0]+end[0])/2, (start[1]+end[1])/2+0.8,
            f"candidate closing edge {report['candidateClosure']['lengthMm']:.6f} mm", color="#38d6c3", fontsize=8, ha="center")
    bx0, by0, bx1, by1 = report["candidateRingComparison"]["largestDifferenceComponentBoundsMm"]
    ax.add_patch(Rectangle((bx0,by0), bx1-bx0, by1-by0, fill=False, edgecolor="#ff5d67", linestyle="--", lw=1.0))
    ax.set_title("Region 79 · complete ring", color="white")
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)"); ax.axis("equal"); ax.grid(alpha=.25, lw=.3)
    ax.legend(fontsize=7, loc="lower left")

    ax = axes[1]
    x, y = candidate.exterior.xy; ax.plot(x, y, color="#57a6ff", lw=1.0, label="Gerber candidate boundary")
    x, y = cached.exterior.xy; ax.plot(x, y, color="#ffc857", lw=1.0, label="Native cached-fill boundary")
    polygons = [diff] if diff.geom_type == "Polygon" else list(diff.geoms)
    for i, polygon in enumerate(p for p in polygons if p.geom_type == "Polygon"):
        x, y = polygon.exterior.xy
        ax.fill(x, y, color="#ff4e5a", alpha=.62 if polygon is largest else .42,
                linewidth=0, label="Symmetric-difference area" if i == 0 else None)
    maxpair = report["maximumBoundaryDisplacement"]
    p1, p2 = maxpair["pointMm"], maxpair["nearestPointMm"]
    ax.scatter([p1[0],p2[0]],[p1[1],p2[1]],s=18,c=["#ffc857","#57a6ff"],zorder=8)
    ax.annotate(f"max boundary displacement\n{maxpair['distanceMm']:.6f} mm",
                xy=p1, xytext=p2, color="white", fontsize=8,
                arrowprops={"arrowstyle":"<->", "color":"#ffffff", "lw":1.2},
                bbox={"boxstyle":"round,pad=.3", "fc":"#202a34", "ec":"#94a6b5", "alpha":.9})
    ax.set_xlim(bx0-.45, bx1+.45); ax.set_ylim(by0-.4, by1+.4)
    ax.set_title(f"Localized mismatch · {bx1-bx0:.3f} × {by1-by0:.3f} mm extent\n"
                 f"Largest component {largest.area:.6f} mm² · total symmetric difference {diff.area:.6f} mm²", color="white")
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)"); ax.axis("equal"); ax.grid(alpha=.25, lw=.3)
    ax.legend(fontsize=7, loc="lower left")
    fig.suptitle("DemonX PCB Prep · Region 79 forensic comparison\nCandidate closure is diagnostic only — native fill state/revision unresolved",
                 color="white", fontsize=13)
    fig.patch.set_facecolor("#0b1118")
    for a in axes:
        a.set_facecolor("#111a23"); a.tick_params(colors="#dbe4ea")
        a.xaxis.label.set_color("#dbe4ea"); a.yaxis.label.set_color("#dbe4ea")
        for spine in a.spines.values(): spine.set_color("#41515e")
        a.title.set_color("#ffffff")
    fig.tight_layout(rect=(0,0,1,.92))
    fig.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    result = measure()
    print(json.dumps({k: result[k] for k in ("candidateRingComparison", "maximumBoundaryDisplacement", "other181RingCheck")}, indent=2))
