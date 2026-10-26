"""Canonical material envelopes and diagnostic V-bit isolation geometry.

All public dimensions and coordinates use millimetres. GEOS outputs here are
derived geometry; source primitives/provenance remain separately addressable.
Nothing in this module produces manufacturing-ready paths.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from shapely import normalize, to_wkb
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

MAX_PREVIEW_DEPTH_MM = 2.0


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


@dataclass(frozen=True)
class LayerMaterial:
    name: str
    side: str
    polarity: str
    geometry: Any
    provenance: tuple[tuple[str, str], ...]
    role: str = "verified-derived"
    approximation_error_bound_mm: float | None = None


@dataclass(frozen=True)
class CanonicalGeometry:
    units: str
    coordinate_frame: str
    implicit_bottom_mirror: bool
    layers: tuple[LayerMaterial, ...]
    source_conformance: str
    independent_verification: str
    machining_eligibility: str
    curve_approximation: str = "source analytic records retained; material polygons use source parser tessellation metadata"
    source_features: tuple[dict[str, Any], ...] = ()
    drill_features: tuple[dict[str, Any], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "source_features", tuple(_freeze(item) for item in self.source_features))
        object.__setattr__(self, "drill_features", tuple(_freeze(item) for item in self.drill_features))
        if self.units != "mm":
            raise ValueError("CANONICAL_UNITS_MUST_BE_MM")
        if not self.coordinate_frame:
            raise ValueError("COORDINATE_FRAME_REQUIRED")
        if self.implicit_bottom_mirror:
            raise ValueError("IMPLICIT_BOTTOM_MIRROR_FORBIDDEN")
        if self.source_conformance not in {"VALID", "NONCONFORMING", "UNKNOWN"}:
            raise ValueError("INVALID_SOURCE_CONFORMANCE")
        if self.independent_verification not in {"VERIFIED", "PARTIAL", "NOT_VERIFIED"}:
            raise ValueError("INVALID_INDEPENDENT_VERIFICATION")
        if self.machining_eligibility not in {"ELIGIBLE", "CONDITIONAL", "BLOCKED"}:
            raise ValueError("INVALID_MACHINING_ELIGIBILITY")
        if self.machining_eligibility == "ELIGIBLE" and (
                self.source_conformance != "VALID" or self.independent_verification != "VERIFIED"):
            raise ValueError("ELIGIBILITY_REQUIRES_VALIDATED_GEOMETRY")

    def material(self, layer_name: str):
        return next((layer.geometry for layer in self.layers if layer.name == layer_name), None)

    def to_dict(self) -> dict[str, Any]:
        layers = []
        for layer in self.layers:
            geometry = normalize(layer.geometry)
            layers.append({
                "name": layer.name, "side": layer.side, "polarity": layer.polarity,
                "role": layer.role, "provenance": [list(item) for item in layer.provenance],
                "wkbHex": to_wkb(geometry, hex=True, output_dimension=2, byte_order=1),
                "materialGeoJson": mapping(geometry),
                "boundsMm": list(geometry.bounds) if not geometry.is_empty else None,
                "approximationErrorBoundMm": layer.approximation_error_bound_mm,
            })
        return {
            "schemaVersion": "1.1.0", "units": self.units,
            "boardCoordinateFrame": {
                "name": self.coordinate_frame, "units": "mm", "origin": "source-defined",
                "axes": "right-handed XY in source coordinates",
                "sideTransforms": {"top": [[1, 0, 0], [0, 1, 0]],
                                   "bottom": [[1, 0, 0], [0, 1, 0]]},
                "implicitBottomMirror": self.implicit_bottom_mirror},
            "layers": layers,
            "sourceFeatures": _thaw(self.source_features),
            "drillFeatures": _thaw(self.drill_features),
            "validation": {"sourceConformance": self.source_conformance,
                           "independentGeometryVerification": self.independent_verification,
                           "manufacturingEligibility": self.machining_eligibility},
            "curveApproximation": self.curve_approximation,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def content_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class VBit:
    included_angle_deg: float = 30.0
    tip_diameter_mm: float = 0.100
    calibration_scale: float = 1.0

    def __post_init__(self):
        if not math.isfinite(self.included_angle_deg) or not 0 < self.included_angle_deg < 180:
            raise ValueError("INCLUDED_ANGLE_MUST_BE_BETWEEN_0_AND_180_DEGREES")
        if not math.isfinite(self.tip_diameter_mm) or self.tip_diameter_mm < 0:
            raise ValueError("TIP_DIAMETER_MUST_BE_FINITE_AND_NONNEGATIVE_MM")
        if not math.isfinite(self.calibration_scale) or self.calibration_scale <= 0:
            raise ValueError("CALIBRATION_SCALE_MUST_BE_FINITE_AND_POSITIVE")

    def effective_width_mm(self, depth_mm: float) -> float:
        if not math.isfinite(depth_mm) or depth_mm < 0:
            raise ValueError("DEPTH_MUST_BE_FINITE_AND_NONNEGATIVE_MM")
        if depth_mm > MAX_PREVIEW_DEPTH_MM:
            raise ValueError("DEPTH_EXCEEDS_PHASE2L_PREVIEW_LIMIT_2_MM")
        return self.calibration_scale * (self.tip_diameter_mm +
               2.0 * depth_mm * math.tan(math.radians(self.included_angle_deg) / 2.0))

    def centerline_offset_mm(self, depth_mm: float) -> float:
        return self.effective_width_mm(depth_mm) / 2.0


@dataclass(frozen=True)
class IsolationPlan:
    cutter: VBit
    depth_mm: float
    effective_width_mm: float
    centerline_offset_mm: float
    center_paths: Any
    cutting_footprint: Any
    unfit_clearances: Any
    copper_intrusion: Any
    approximation_error_bound_mm: float
    source_role: str = "hypothetical"
    label: str = "Isolation Simulation — Not Approved for Machining"


def _polygons(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in _polygons(child)]
    return []


def quad_segments_for_error(radius_mm: float, error_mm: float) -> int:
    """GEOS segments per quadrant for a circle chord sagitta bound."""
    if not math.isfinite(radius_mm) or radius_mm <= 0:
        raise ValueError("ARC_RADIUS_MUST_BE_POSITIVE_MM")
    if not math.isfinite(error_mm) or error_mm <= 0:
        raise ValueError("APPROXIMATION_ERROR_BOUND_MUST_BE_POSITIVE_MM")
    if error_mm >= radius_mm:
        return 8
    angle = math.acos(max(-1.0, min(1.0, 1 - error_mm / radius_mm)))
    return max(8, min(4096, math.ceil(math.pi / (4 * angle))))


def plan_isolation(material, cutter: VBit, depth_mm: float, *,
                   approximation_error_bound_mm: float = 0.002,
                   machine_epsilon_mm: float = 1e-9) -> IsolationPlan:
    """Build preview-only center contours around synthetic/verified copper.

    Circular-arc tessellation is conservatively selected from a sagitta target.
    GEOS offset topology can still collapse narrow features; those are explicitly
    returned as unfit clearances and must be treated as unsafe diagnostics.
    """
    width = cutter.effective_width_mm(depth_mm)
    if width <= 0:
        raise ValueError("EFFECTIVE_CUT_WIDTH_MUST_BE_POSITIVE_MM")
    radius = width / 2
    if not math.isfinite(approximation_error_bound_mm) or approximation_error_bound_mm <= 0:
        raise ValueError("APPROXIMATION_ERROR_BOUND_MUST_BE_POSITIVE_MM")
    if not math.isfinite(machine_epsilon_mm) or machine_epsilon_mm < 0:
        raise ValueError("MACHINE_EPSILON_MUST_BE_NONNEGATIVE_MM")
    if material is None or material.is_empty or not material.is_valid:
        raise ValueError("ISOLATION_REQUIRES_NONEMPTY_VALID_COPPER_MATERIAL")
    # GEOS uses quad_segs segments per quadrant. Choose enough so circle sagitta
    # is at most the explicit error budget, with a small upper resource guard.
    quad_segs = quad_segments_for_error(radius, approximation_error_bound_mm) if radius else 8
    components = _polygons(material)
    expanded = [component.buffer(radius, quad_segs=quad_segs) for component in components]
    individual_paths = [geometry.boundary for geometry in expanded if not geometry.is_empty]
    paths = unary_union(individual_paths) if individual_paths else GeometryCollection()
    footprint_parts = [path.buffer(radius, quad_segs=quad_segs) for path in individual_paths]
    footprint = unary_union(footprint_parts) if footprint_parts else GeometryCollection()
    unfit_parts = []
    if len(expanded) > 1:
        for i, first in enumerate(expanded):
            for second in expanded[i+1:]:
                overlap = first.intersection(second)
                if not overlap.is_empty and overlap.area > machine_epsilon_mm ** 2:
                    unfit_parts.append(overlap)
    # A vanished void has no offset contour to carry a tool through. Preserve it
    # as an explicit no-fit area rather than silently dropping its center path.
    for original, offset in zip(components, expanded):
        if len(offset.interiors) < len(original.interiors):
            for ring in original.interiors:
                hole = Polygon(ring)
                remaining = hole.buffer(-radius, quad_segs=quad_segs)
                if remaining.is_empty or remaining.area <= machine_epsilon_mm ** 2:
                    unfit_parts.append(hole)
    unfit = unary_union(unfit_parts) if unfit_parts else GeometryCollection()
    intrusion = footprint.intersection(material)
    if intrusion.area <= machine_epsilon_mm ** 2:
        intrusion = GeometryCollection()
    return IsolationPlan(cutter, depth_mm, width, radius, paths, footprint, unfit,
                         intrusion, approximation_error_bound_mm)


def synthetic_demo_material():
    """Hand-defined deterministic demo: pads, tracks, via, island, void, curve-ish arc polygon."""
    from shapely.geometry import Point
    pads = Point(0, 0).buffer(0.85, quad_segs=64).union(
        Point(3.2, 0).buffer(0.85, quad_segs=64))
    rectangular_pad = Polygon([(0, 3), (1.6, 3), (1.6, 4), (0, 4)])
    trace = LineString([(0.85, 0.0), (1.2, 0.0), (2.1, 0.0), (2.35, 0.0)]).buffer(.18, cap_style="flat")
    via = Point(5.2, 1.0).buffer(.62, quad_segs=48).difference(
        Point(5.2, 1.0).buffer(.18, quad_segs=48))
    island = Polygon([(4.0, 3.0), (6.1, 3.0), (6.0, 4.1), (5.25, 3.7), (4.3, 4.4)])
    island = island.difference(Point(4.9, 3.6).buffer(.18, quad_segs=32))
    narrow_trace = LineString([(0, 5.2), (1.0, 5.2), (2.0, 5.2), (3.5, 5.2)]).buffer(.10, cap_style="flat")
    slot_region = Polygon([(7.8, 0), (10.4, 0), (10.4, 2), (7.8, 2)]).difference(
        LineString([(8.3, 1), (9.9, 1)]).buffer(.25, cap_style="flat"))
    close_pads = Point(12, 0).buffer(.6, quad_segs=48).union(
        Point(13.22, 0).buffer(.6, quad_segs=48))
    return unary_union([pads, rectangular_pad, trace, via, island, narrow_trace,
                        slot_region, close_pads])


def synthetic_canonical_geometry() -> CanonicalGeometry:
    from shapely.geometry import Point, box
    material = synthetic_demo_material()
    bottom = box(0, 8, 3, 10).difference(Point(1.5, 9).buffer(.35, quad_segs=40))
    synthetic_hash = hashlib.sha256(b"phase2l-independent-synthetic-geometry-v1").hexdigest()
    sources = tuple({"sourceFile": "synthetic-demo", "sourceSha256": synthetic_hash,
                     "objectIndex": index, "primitiveIndex": 0, "primitiveType": kind,
                     "semantic": semantic, "polarity": "dark", "sourceCoordinatesMm": coordinates,
                     "polygonizationSagittaMm": .001, "lineReference": None}
                    for index, (kind, semantic, coordinates) in enumerate((
                        ("CircularArc", "circular pad", {"cx": 0.0, "cy": 0.0, "radiusMm": .85}),
                        ("LineString", "rectangular pad", {"xMin": 0.0, "yMin": 3.0, "xMax": 1.6, "yMax": 4.0}),
                        ("LineString", "narrow trace", {"startX": 0.0, "startY": 5.2, "endX": 3.5, "endY": 5.2}),
                        ("CircularArc", "via annulus", {"cx": 5.2, "cy": 1.0, "outerRadiusMm": .62, "holeRadiusMm": .18}),
                        ("CircularArc", "copper void", {"cx": 4.9, "cy": 3.6, "radiusMm": .18}),
                        ("RoutedSlot", "slot", {"startX": 8.3, "startY": 1.0, "endX": 9.9, "endY": 1.0, "widthMm": .5}),
                        ("ConcavePolygon", "copper island", {"verticesMm": [[4.0, 3.0], [6.1, 3.0], [6.0, 4.1], [5.25, 3.7], [4.3, 4.4]]}),
                        ("CircularArc", "adjacent pads", {"firstCenterMm": [12.0, 0.0], "secondCenterMm": [13.22, 0.0], "radiusMm": .6}),
                    )))
    drills = (
        {"kind": "circular-hole", "sourceFile": "synthetic-demo", "sourceFeatureIndex": 0,
         "xMm": 5.2, "yMm": 1.0, "diameterMm": .36, "plating": "plated", "role": "original"},
        {"kind": "routed-slot", "sourceFile": "synthetic-demo", "sourceFeatureIndex": 1,
         "centerlineMm": [[8.3, 1.0], [9.9, 1.0]], "diameterMm": .5,
         "plating": "non-plated", "role": "original"},
    )
    return CanonicalGeometry("mm", "synthetic-demo right-handed XY", False,
        (LayerMaterial("top-copper", "top", "composed-dark-clear", material,
                       (("synthetic-demo", "independently-defined-v1"),), "original"),
         LayerMaterial("bottom-copper", "bottom", "composed-dark-clear", bottom,
                       (("synthetic-demo", "independently-defined-v1"),), "original")),
        "VALID", "VERIFIED", "BLOCKED",
        "synthetic circular pads/arcs use 0.001 mm nominal sagitta; analytic source line/arc records retained separately",
        sources, drills)


def eligibility_for_simulation(geometry: CanonicalGeometry) -> tuple[bool, str]:
    if geometry.machining_eligibility != "ELIGIBLE":
        return False, "Simulation refused: source geometry is blocked from machining eligibility."
    if geometry.source_conformance != "VALID" or geometry.independent_verification != "VERIFIED":
        return False, "Simulation refused: geometry is unresolved or independently unverified."
    return True, "Diagnostic simulation only; this result is never machining approval."
