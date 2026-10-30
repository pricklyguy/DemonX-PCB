"""Collision-aware multi-pass and explicitly classified copper-clear previews.

This module produces inspectable candidates only. It does not emit machine
paths, authorize machining, modify source material, or approve inferred source
geometry. All coordinates and distances are millimetres.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Iterable

from shapely import normalize, to_wkb
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon
from shapely.ops import nearest_points, unary_union

from phase2l.geometry import IsolationPlan, VBit, _polygons, plan_isolation, quad_segments_for_error


@dataclass(frozen=True)
class PathRejection:
    category: str
    message: str
    path: Any
    swept_footprint: Any
    protected_overlap: Any
    source_component: int | None = None


@dataclass(frozen=True)
class TwoPassPlan:
    single_pass: IsolationPlan
    additional_offset_mm: float
    candidate_paths: Any
    accepted_paths: Any
    rejected_paths: Any
    accepted_footprint: Any
    rejected_footprint: Any
    incremental_swept_area_mm2: float
    incremental_copper_removal_mm2: float
    candidate_length_mm: float
    accepted_length_mm: float
    rejected_length_mm: float
    topology_withheld_length_mm: float
    rejections: tuple[PathRejection, ...]
    geometry_uncertainty: Any
    remaining_copper: Any
    source_role: str = "hypothetical"
    manufacturing_authorized: bool = False


@dataclass(frozen=True)
class ResidualCandidate:
    candidate_id: str
    geometry: Any
    area_mm2: float
    classification_required: str = "Unclassified; explicit owner classification required for preview"


@dataclass(frozen=True)
class ClearingPlan:
    selected_ids: tuple[str, ...]
    candidate_paths: Any
    accepted_paths: Any
    rejected_paths: Any
    swept_footprint: Any
    rejected_footprint: Any
    cleared_area_mm2: float
    remaining_selected_copper: Any
    unreachable_zones: Any
    rejections: tuple[PathRejection, ...]
    classified_for_preview_only: bool
    manufacturing_authorized: bool = False


def _lines(geometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry] if not geometry.is_empty and geometry.length > 0 else []
    if isinstance(geometry, MultiLineString) or hasattr(geometry, "geoms"):
        return [line for child in geometry.geoms for line in _lines(child)]
    return []


def _line_collection(lines: Iterable[Any]):
    parts = [line for geometry in lines for line in _lines(geometry)]
    return GeometryCollection(parts)


def _polygonal_union(material):
    if material is None or material.is_empty:
        raise ValueError("MULTIPASS_REQUIRES_NONEMPTY_COPPER")
    polygons = _polygons(material)
    if not polygons:
        raise ValueError("MULTIPASS_REQUIRES_POLYGONAL_COPPER")
    composed = unary_union(polygons)
    if composed.is_empty or not composed.is_valid:
        raise ValueError("MULTIPASS_REQUIRES_VALID_COMPOSED_COPPER")
    return composed


def _validate_offset(offset: float):
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("ADDITIONAL_OFFSET_MUST_BE_FINITE_NONNEGATIVE_MM")


def plan_two_pass(material, cutter: VBit, depth_mm: float, additional_offset_mm: float, *,
                  approximation_error_bound_mm: float = 0.002,
                  baseline_plan: IsolationPlan | None = None,
                  units: str = "mm") -> TwoPassPlan:
    """Plan a second diagnostic pass and retain all collision/topology rejects.

    Safety test uses the full circular sweep. The exclusion zone is the
    protected material dilated by cutter radius plus two declared curve-error
    bounds (one for footprint polygonization, one conservative overlay margin).
    Candidate centerline portions inside that zone are rejected and retained.
    Accepted fragments receive a second full-sweep intersection check.
    """
    _validate_offset(additional_offset_mm)
    if units != "mm":
        raise ValueError("MULTIPASS_UNITS_MUST_BE_MM")
    if not math.isfinite(approximation_error_bound_mm) or approximation_error_bound_mm <= 0:
        raise ValueError("APPROXIMATION_ERROR_BOUND_MUST_BE_POSITIVE_MM")
    composed = _polygonal_union(material)
    baseline = baseline_plan or plan_isolation(composed, cutter, depth_mm,
        approximation_error_bound_mm=approximation_error_bound_mm)
    radius = baseline.effective_width_mm / 2.0
    qseg = quad_segments_for_error(radius, approximation_error_bound_mm)
    exclusion = composed.buffer(radius + 2 * approximation_error_bound_mm, quad_segs=qseg)

    candidates: list[Any] = []
    topology_rejects: list[PathRejection] = []
    components = _polygons(composed)
    for component_index, component in enumerate(components):
        first = component.buffer(radius, quad_segs=qseg)
        farther = component.buffer(radius + additional_offset_mm, quad_segs=qseg)
        if not first.is_empty and len(_polygons(first)) != len(_polygons(farther)):
            lost = first.boundary
            topology_rejects.append(PathRejection(
                "offset topology change",
                "The added offset changes polygon component topology; affected first-pass boundary is withheld.",
                lost, lost.buffer(radius, quad_segs=qseg), GeometryCollection(), component_index))
            continue
        if not first.is_empty and farther.is_empty:
            lost = first.boundary
            topology_rejects.append(PathRejection(
                "offset topology change", "The added offset eliminates this component's candidate loops.",
                lost, lost.buffer(radius, quad_segs=qseg), GeometryCollection(), component_index))
            continue
        # Positive offsets preserve exterior loops, but can eliminate holes.
        first_polys = _polygons(first)
        # Test each first-pass hole independently, so an unrelated surviving
        # hole cannot mask which specific loop collapses at the next offset.
        for poly in first_polys:
            for ring in poly.interiors:
                hole_after_extra_offset = Polygon(ring).buffer(-additional_offset_mm,
                                                                quad_segs=qseg)
                if hole_after_extra_offset.is_empty:
                    lost = LineString(ring.coords)
                    topology_rejects.append(PathRejection(
                        "collapsed void loop",
                        "The source void's inward clearance loop collapses at this added offset; the missing loop is reported, not dropped.",
                        lost, lost.buffer(radius, quad_segs=qseg), GeometryCollection(), component_index))
        candidates.extend(_lines(farther.boundary))

    candidate_collection = _line_collection(candidates)
    accepted: list[Any] = []
    rejected: list[Any] = [item.path for item in topology_rejects]
    rejected_sweeps: list[Any] = [item.swept_footprint for item in topology_rejects]
    rejections: list[PathRejection] = list(topology_rejects)
    uncertainty_parts: list[Any] = []
    for component_index, candidate in enumerate(candidates):
        # Full-footprint collision dual: dilating protected copper by the tool
        # radius gives the exact center-space forbidden set for a round cutter.
        safe = candidate.difference(exclusion)
        colliding = candidate.intersection(exclusion)
        if not colliding.is_empty:
            sweep = colliding.buffer(radius, quad_segs=qseg)
            actual = sweep.intersection(composed)
            rejections.append(PathRejection(
                "protected-copper collision / required clearance",
                "The complete V-bit sweep would touch protected copper or enter the stated uncertainty margin.",
                colliding, sweep, actual, component_index))
            rejected.append(colliding)
            rejected_sweeps.append(sweep)
            # Keep the proximity area distinct from measured actual overlap.
            uncertainty_parts.append(sweep.intersection(composed.buffer(radius + 2*approximation_error_bound_mm,
                                                                          quad_segs=qseg)))
        for fragment in _lines(safe):
            sweep = fragment.buffer(radius, quad_segs=qseg)
            overlap = sweep.intersection(composed.buffer(approximation_error_bound_mm, quad_segs=qseg))
            if not overlap.is_empty:
                rejections.append(PathRejection(
                    "numerically uncertain sweep",
                    "Full swept-footprint verification was not clear of protected copper plus its approximation margin.",
                    fragment, sweep, overlap, component_index))
                rejected.append(fragment)
                rejected_sweeps.append(sweep)
                uncertainty_parts.append(overlap)
            else:
                accepted.append(fragment)

    accepted_geometry = _line_collection(accepted)
    rejected_geometry = _line_collection(rejected)
    accepted_sweep = unary_union([line.buffer(radius, quad_segs=qseg) for line in accepted]) if accepted else GeometryCollection()
    rejected_sweep = unary_union(rejected_sweeps) if rejected_sweeps else GeometryCollection()
    # Every retained accepted sweep is checked against the composed layer.
    verified_overlap = accepted_sweep.intersection(composed.buffer(approximation_error_bound_mm, quad_segs=qseg))
    if not verified_overlap.is_empty:
        # Fail closed: an implementation/kernel discrepancy rejects all
        # fragments whose sweeps meet the verification overlap.
        failed = [line for line in accepted
                  if not line.buffer(radius, quad_segs=qseg).intersection(
                      composed.buffer(approximation_error_bound_mm, quad_segs=qseg)).is_empty]
        accepted = [line for line in accepted if line not in failed]
        rejected.extend(failed)
        for line in failed:
            sweep = line.buffer(radius, quad_segs=qseg)
            rejected_sweeps.append(sweep)
            rejections.append(PathRejection("post-clip swept-footprint check",
                "A complete-footprint recheck found protected-copper overlap; fragment rejected.",
                line, sweep, sweep.intersection(composed), None))
        accepted_geometry = _line_collection(accepted)
        rejected_geometry = _line_collection(rejected)
        accepted_sweep = unary_union([line.buffer(radius, quad_segs=qseg) for line in accepted]) if accepted else GeometryCollection()
        rejected_sweep = unary_union(rejected_sweeps) if rejected_sweeps else GeometryCollection()
    incremental_sweep = accepted_sweep.difference(baseline.cutting_footprint).area
    incremental_copper = accepted_sweep.difference(baseline.cutting_footprint).intersection(composed).area
    uncertainty = unary_union(uncertainty_parts) if uncertainty_parts else GeometryCollection()
    remaining = composed.difference(baseline.cutting_footprint.union(accepted_sweep))
    return TwoPassPlan(baseline, additional_offset_mm, candidate_collection,
        accepted_geometry, rejected_geometry, accepted_sweep, rejected_sweep,
        incremental_sweep, incremental_copper, candidate_collection.length,
        accepted_geometry.length,
        max(0.0, candidate_collection.length - accepted_geometry.length),
        sum(item.path.length for item in topology_rejects),
        tuple(rejections), uncertainty, remaining)


def identify_residual_candidates(remaining_copper, *, min_area_mm2: float = 0.005,
                                 max_area_mm2: float = 2.0) -> tuple[ResidualCandidate, ...]:
    """List small disconnected remaining copper without judging its purpose."""
    if (not math.isfinite(min_area_mm2) or not math.isfinite(max_area_mm2) or
            min_area_mm2 < 0 or max_area_mm2 <= min_area_mm2):
        raise ValueError("RESIDUAL_AREA_RANGE_MUST_BE_FINITE_AND_ORDERED_MM2")
    candidates = []
    for poly in _polygons(remaining_copper):
        if min_area_mm2 <= poly.area <= max_area_mm2:
            digest = hashlib.sha256(to_wkb(normalize(poly), byte_order=1)).hexdigest()[:12]
            candidates.append(ResidualCandidate(f"residual-{digest}", poly, poly.area))
    return tuple(sorted(candidates, key=lambda item: (item.area_mm2, item.candidate_id)))


def plan_selective_clearing(original_material, candidates: Iterable[ResidualCandidate],
                            selected_ids: Iterable[str], *, cutter: VBit, depth_mm: float,
                            classified_for_preview: Iterable[str],
                            approximation_error_bound_mm: float = 0.002,
                            units: str = "mm") -> ClearingPlan:
    """Make nested-loop clearing candidates only for explicitly classified zones.

    All non-selected original material remains protected. Each retained move is
    checked as a complete V-bit swept footprint; rejected moves and uncut
    material remain in the result. Classification is local to this diagnostic
    call and cannot change canonical geometry or machining status.
    """
    composed = _polygonal_union(original_material)
    if units != "mm":
        raise ValueError("CLEARING_UNITS_MUST_BE_MM")
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected = tuple(dict.fromkeys(selected_ids))
    classified = set(classified_for_preview)
    if not math.isfinite(approximation_error_bound_mm) or approximation_error_bound_mm <= 0:
        raise ValueError("APPROXIMATION_ERROR_BOUND_MUST_BE_POSITIVE_MM")
    if any(candidate_id not in by_id for candidate_id in selected):
        raise ValueError("UNKNOWN_RESIDUAL_CANDIDATE")
    if any(candidate_id not in classified for candidate_id in selected):
        raise ValueError("CLEARING_REQUIRES_EXPLICIT_PREVIEW_CLASSIFICATION")
    width = cutter.effective_width_mm(depth_mm)
    if width <= 0:
        raise ValueError("EFFECTIVE_CUT_WIDTH_MUST_BE_POSITIVE_MM")
    radius = width / 2
    qseg = quad_segments_for_error(radius, approximation_error_bound_mm)
    selected_geometries = [by_id[key].geometry for key in selected]
    selected_union = unary_union(selected_geometries) if selected_geometries else GeometryCollection()
    if not selected_union.is_empty and not selected_union.difference(composed).is_empty:
        raise ValueError("RESIDUAL_CANDIDATE_IS_OUTSIDE_CANONICAL_COPPER")
    protected = composed.difference(selected_union)
    exclusion = protected.buffer(radius + 2 * approximation_error_bound_mm, quad_segs=qseg)
    candidates_paths: list[Any] = []
    accepted: list[Any] = []
    rejected: list[Any] = []
    rejected_sweeps: list[Any] = []
    unreachable: list[Any] = []
    rejections: list[PathRejection] = []
    all_sweeps: list[Any] = []

    for index, zone in enumerate(selected_geometries):
        center_area = zone.buffer(-radius, quad_segs=qseg)
        if center_area.is_empty:
            unreachable.append(zone)
            rejections.append(PathRejection("unreachable clearing zone",
                "The selected copper zone is narrower than the cutter footprint; no centerline fits.",
                GeometryCollection(), GeometryCollection(), zone.intersection(protected), index))
            continue
        loops: list[Any] = []
        current = center_area
        for _ in range(256):
            if current.is_empty:
                break
            loops.extend(_lines(current.boundary))
            next_area = current.buffer(-width, quad_segs=qseg)
            if next_area.is_empty or next_area.area >= current.area:
                break
            current = next_area
        # Where nested loops are adjacent and an entire connector sweep stays
        # inside the selected zone and outside every protected region, add a
        # short checked link. It remains a distinct diagnostic segment; no
        # connector is inferred through a neck or pocket that cannot contain it.
        nested = sorted(loops, key=lambda line: line.length, reverse=True)
        links: list[LineString] = []
        for outer, inner in zip(nested, nested[1:]):
            a, b = nearest_points(outer, inner)
            if a.distance(b) <= approximation_error_bound_mm:
                continue
            link = LineString([a.coords[0], b.coords[0]])
            link_sweep = link.buffer(radius, quad_segs=qseg)
            inside_zone = link_sweep.difference(zone.buffer(approximation_error_bound_mm,
                                                              quad_segs=qseg)).is_empty
            protected_collision = link_sweep.intersection(protected.buffer(
                approximation_error_bound_mm, quad_segs=qseg))
            existing_sweep = unary_union([path.buffer(radius, quad_segs=qseg) for path in loops])
            novel_area = link_sweep.difference(existing_sweep).area
            if inside_zone and protected_collision.is_empty and novel_area > approximation_error_bound_mm**2:
                links.append(link)
            elif not inside_zone or not protected_collision.is_empty:
                rejected.append(link)
                rejected_sweeps.append(link_sweep)
                rejections.append(PathRejection("unsafe clearing connector",
                    "A linked clearing segment is omitted because its complete V-bit sweep leaves the selected zone or enters protected copper.",
                    link, link_sweep, protected_collision, index))
        loops.extend(links)
        zone_paths = _line_collection(loops)
        candidates_paths.extend(loops)
        zone_sweeps = []
        for path in loops:
            safe = path.difference(exclusion)
            forbidden = path.intersection(exclusion)
            if not forbidden.is_empty:
                sweep = forbidden.buffer(radius, quad_segs=qseg)
                rejected.append(forbidden)
                rejected_sweeps.append(sweep)
                rejections.append(PathRejection("clearing path protected-copper collision",
                    "The full clearing sweep enters unselected copper or the approximation margin.",
                    forbidden, sweep, sweep.intersection(protected), index))
            for fragment in _lines(safe):
                sweep = fragment.buffer(radius, quad_segs=qseg)
                overlap = sweep.intersection(protected.buffer(approximation_error_bound_mm,
                                                                 quad_segs=qseg))
                if not overlap.is_empty:
                    rejected.append(fragment)
                    rejected_sweeps.append(sweep)
                    rejections.append(PathRejection("clearing footprint verification",
                        "Full swept-footprint verification was not clear of protected copper.",
                        fragment, sweep, overlap, index))
                else:
                    accepted.append(fragment)
                    zone_sweeps.append(sweep)
        if not zone_sweeps:
            unreachable.append(zone)
        else:
            all_sweeps.append(unary_union(zone_sweeps))

    accepted_paths = _line_collection(accepted)
    rejected_paths = _line_collection(rejected)
    sweep = unary_union(all_sweeps) if all_sweeps else GeometryCollection()
    rejected_sweep = unary_union(rejected_sweeps) if rejected_sweeps else GeometryCollection()
    cleared = selected_union.intersection(sweep)
    remaining = selected_union.difference(sweep)
    # Missing reachable coverage remains visible as uncut copper, not filled in.
    for polygon in _polygons(remaining):
        if polygon.area > approximation_error_bound_mm ** 2:
            unreachable.append(polygon)
    return ClearingPlan(selected, _line_collection(candidates_paths), accepted_paths,
        rejected_paths, sweep, rejected_sweep, cleared.area, remaining,
        unary_union(unreachable) if unreachable else GeometryCollection(),
        tuple(rejections), True)
