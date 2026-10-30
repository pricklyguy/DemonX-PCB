"""Non-destructive, evidence-labelled open-contour repair proposals."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Sequence

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


DEFAULT_CLOSURE_TOLERANCE_MM = 0.010
NATIVE_COMPARISON_LIMIT_MM = 0.005


def _polygon_metrics(geometry) -> dict[str, Any]:
    polygons = ([geometry] if geometry.geom_type == "Polygon" else
                [g for g in getattr(geometry, "geoms", []) if g.geom_type == "Polygon"])
    return {"areaMm2": geometry.area, "components": len(polygons),
            "interiorVoids": sum(len(poly.interiors) for poly in polygons),
            "valid": bool(geometry.is_valid), "boundsMm": list(geometry.bounds) if not geometry.is_empty else None}


@dataclass(frozen=True)
class RepairProposal:
    status: str
    reason: str
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]
    gap_mm: float
    tolerance_mm: float
    closing_segment: Any
    candidate_material: Any
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    unintended_intersections: tuple[tuple[float, float], ...]
    source_layer: str
    polarity: str
    contour_direction: str
    nearest_geometry_distance_mm: float | None
    source_command_context: tuple[dict[str, Any], ...]
    audit_record: dict[str, Any]


def propose_closure(points: Sequence[tuple[float, float]], *,
                    source_commands: Sequence[dict[str, Any]] = (),
                    source_layer: str = "unknown", polarity: str = "unknown",
                    tolerance_mm: float = DEFAULT_CLOSURE_TOLERANCE_MM,
                    source_role: str = "original", source_material=None,
                    protected_geometry=None, native_boundary_mismatch_mm: float | None = None) -> RepairProposal:
    """Evaluate one straight closure without modifying source or canonical geometry.

    Non-synthetic designs never receive SAFE CANDIDATE from endpoint proximity
    alone. Missing native evidence remains manual review. An authenticated
    excessive mismatch or a geometric contradiction refuses automatic repair.
    """
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError("CLOSURE_TOLERANCE_MUST_BE_POSITIVE_MM")
    if len(points) < 3:
        raise ValueError("OPEN_CONTOUR_REQUIRES_AT_LEAST_THREE_POINTS")
    start, end = tuple(map(float, points[0])), tuple(map(float, points[-1]))
    coords = [tuple(map(float, point)) for point in points]
    if not all(math.isfinite(v) for point in coords for v in point):
        raise ValueError("CONTOUR_COORDINATES_MUST_BE_FINITE_MM")
    gap = math.dist(start, end)
    signed_area = .5 * sum(coords[i][0] * coords[(i + 1) % len(coords)][1] -
                           coords[(i + 1) % len(coords)][0] * coords[i][1]
                           for i in range(len(coords)))
    contour_direction = "counterclockwise" if signed_area > 0 else "clockwise"
    closing = LineString([end, start])
    open_line = LineString(coords)
    candidate = Polygon([*coords, start])
    context = tuple(dict(command) for command in source_commands[:4]) + tuple(
        dict(command) for command in source_commands[-4:] if command not in source_commands[:4])

    reason = ""
    status = "NEEDS MANUAL REVIEW"
    if gap == 0:
        status, reason = "CANNOT AUTOMATICALLY REPAIR", "The contour is already closed; no closure proposal applies."
    elif gap > tolerance_mm:
        status, reason = "CANNOT AUTOMATICALLY REPAIR", "The endpoint gap exceeds the selected review tolerance."
    elif source_commands and any(command.get("mode") != "G01" for command in source_commands):
        status, reason = "CANNOT AUTOMATICALLY REPAIR", "The contour contains unsupported curved or non-linear source commands."
    elif source_commands and any(command.get("operation") != "D01" for command in source_commands):
        status, reason = "NEEDS MANUAL REVIEW", "Source moves include D02 contour transitions or cut-in semantics; a straight close could fill a legitimate void."
    elif not candidate.is_valid or candidate.is_empty or candidate.area == 0:
        status, reason = "CANNOT AUTOMATICALLY REPAIR", "The proposed edge creates an invalid or zero-area contour."
    elif closing.crosses(open_line) or closing.overlaps(open_line):
        status, reason = "CANNOT AUTOMATICALLY REPAIR", "The closing edge crosses or retraces a source segment."
    elif (native_boundary_mismatch_mm is not None and
          native_boundary_mismatch_mm > NATIVE_COMPARISON_LIMIT_MM):
        status, reason = "CANNOT AUTOMATICALLY REPAIR", "Native comparison evidence contradicts this closure candidate."
    elif source_role == "synthetic":
        status, reason = "SAFE CANDIDATE", "Synthetic fixture: supported linear contour, within fixture-backed tolerance, and valid material."
    else:
        reason = ("The line closes a valid contour, but native-design or independent intent evidence is missing. "
                  "Endpoint proximity alone is not approval.")

    intersections = ()
    nearest_geometry_distance = None
    if protected_geometry is not None and not protected_geometry.is_empty:
        conflict = candidate.intersection(protected_geometry)
        nearest_geometry_distance = candidate.distance(protected_geometry)
        if not conflict.is_empty:
            point = conflict.representative_point()
            intersections = ((point.x, point.y),)
            if status == "SAFE CANDIDATE":
                status = "NEEDS MANUAL REVIEW"
                reason = "The closure candidate touches protected copper; inspect whether it would join separate material."

    before = source_material if source_material is not None else Polygon()
    after = unary_union([before, candidate]) if not before.is_empty else candidate
    before_metrics = _polygon_metrics(before)
    after_metrics = _polygon_metrics(after)
    audit = {
        "version": "phase2m-repair-v1", "sourceLayer": source_layer, "polarity": polarity,
        "sourceContourDirection": contour_direction,
        "nearestProtectedGeometryDistanceMm": nearest_geometry_distance,
        "sourceRole": source_role, "originalStartMm": list(start), "originalEndMm": list(end),
        "proposedSegmentMm": [list(end), list(start)], "gapMm": gap,
        "selectedToleranceMm": tolerance_mm, "status": status, "reason": reason,
        "sourceCommandContext": list(context), "before": before_metrics, "after": after_metrics,
        "unintendedIntersectionCoordinatesMm": [list(point) for point in intersections],
        "userApproved": False,
    }
    audit["sha256"] = hashlib.sha256(json.dumps(audit, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return RepairProposal(status, reason, start, end, gap, tolerance_mm, closing, candidate,
                          before_metrics, after_metrics, intersections, source_layer, polarity,
                          contour_direction, nearest_geometry_distance, context, audit)


def approve_proposal(proposal: RepairProposal, *, explicit_approval: bool):
    if not explicit_approval:
        raise ValueError("EXPLICIT_USER_APPROVAL_REQUIRED")
    if proposal.status != "SAFE CANDIDATE":
        raise ValueError("ONLY_SAFE_CANDIDATES_CAN_ENTER_WORKING_GEOMETRY")
    audit = dict(proposal.audit_record)
    audit.pop("sha256", None)
    audit["userApproved"] = True
    audit["approvedRole"] = "verified-derived-working-layer"
    audit["sha256"] = hashlib.sha256(json.dumps(audit, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    working_geometry = proposal.candidate_material
    return working_geometry, audit
