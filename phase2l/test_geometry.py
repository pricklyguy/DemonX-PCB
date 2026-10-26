from __future__ import annotations

import math
import sys
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2l"))

from geometry import (CanonicalGeometry, LayerMaterial, VBit, eligibility_for_simulation,
                     plan_isolation, quad_segments_for_error, synthetic_canonical_geometry,
                     synthetic_demo_material)
from shapely.geometry import Point, box
from jsonschema import Draft202012Validator


class VBitGeometryTests(unittest.TestCase):
    def test_width_for_multiple_depths_and_angles(self):
        cases = [(30, .1, 0, .1), (30, .1, .2, .1 + .4 * math.tan(math.radians(15))),
                 (60, .2, .5, .2 + 1.0 * math.tan(math.radians(30))),
                 (90, 0, .3, .6)]
        for angle, tip, depth, expected in cases:
            self.assertAlmostEqual(VBit(angle, tip).effective_width_mm(depth), expected, places=12)

    def test_invalid_cutter_angle_tip_depth_and_calibration(self):
        for angle in (0, 180, -1, math.nan, math.inf):
            with self.assertRaises(ValueError): VBit(included_angle_deg=angle)
        for tip in (-.01, math.nan, math.inf):
            with self.assertRaises(ValueError): VBit(tip_diameter_mm=tip)
        for scale in (0, -1, math.nan, math.inf):
            with self.assertRaises(ValueError): VBit(calibration_scale=scale)
        cutter = VBit()
        for depth in (-1, math.nan, math.inf):
            with self.assertRaises(ValueError): cutter.effective_width_mm(depth)
        with self.assertRaisesRegex(ValueError, "DEPTH_EXCEEDS"):
            cutter.effective_width_mm(2.001)
        with self.assertRaisesRegex(ValueError, "EFFECTIVE_CUT_WIDTH"):
            plan_isolation(box(0, 0, 1, 1), VBit(30, 0), 0)

    def test_centerline_offset_is_half_effective_width(self):
        cutter = VBit(30, .1)
        for depth in (0, .05, .2, .8):
            width = cutter.effective_width_mm(depth)
            self.assertAlmostEqual(cutter.centerline_offset_mm(depth), width / 2, places=14)

    def test_calibration_is_explicit_and_non_destructive(self):
        nominal = VBit(30, .1)
        measured = VBit(30, .1, calibration_scale=1.08)
        self.assertAlmostEqual(measured.effective_width_mm(.2), nominal.effective_width_mm(.2) * 1.08)

    def test_clearance_collision_and_copper_intrusion_diagnostics(self):
        too_close = Point(0, 0).buffer(.6, quad_segs=48).union(Point(1.22, 0).buffer(.6, quad_segs=48))
        plan = plan_isolation(too_close, VBit(30, .1), .2)
        self.assertGreater(plan.unfit_clearances.area, 0)
        self.assertAlmostEqual(plan.effective_width_mm, .1 + .4 * math.tan(math.radians(15)))
        self.assertGreater(plan.copper_intrusion.area, 0)
        adequate = box(0, 0, 10, 10)
        clear = plan_isolation(adequate, VBit(), .1)
        self.assertTrue(clear.unfit_clearances.is_empty)
        self.assertLess(clear.copper_intrusion.area, 1e-4)

    def test_polygon_voids_islands_concavity_and_synthetic_geometry_valid(self):
        material = synthetic_demo_material()
        self.assertTrue(material.is_valid)
        self.assertGreater(len(material.geoms), 1)
        plan = plan_isolation(material, VBit(), .1)
        self.assertGreater(len(plan.center_paths.geoms), 1)
        self.assertGreater(plan.effective_width_mm, .1)

    def test_circular_via_hole_and_rectangular_pad_centerline_clearance(self):
        via_annulus = Point(0, 0).buffer(1, quad_segs=96).difference(
            Point(0, 0).buffer(.4, quad_segs=96))
        rect_pad = box(3, 0, 5, 1)
        plan = plan_isolation(via_annulus.union(rect_pad), VBit(30, .1), .05)
        self.assertEqual(len(plan.center_paths.geoms), 3)  # via annulus has inner and outer contour
        outer = via_annulus.exterior.distance(plan.center_paths)
        self.assertAlmostEqual(outer, plan.centerline_offset_mm, delta=.003)
        self.assertLess(plan.copper_intrusion.area, 1e-4)

    def test_void_narrower_than_cutter_is_marked_unfit(self):
        small_void = box(0, 0, 2, 2).difference(Point(1, 1).buffer(.04, quad_segs=48))
        plan = plan_isolation(small_void, VBit(30, .1), .1)
        self.assertGreater(plan.unfit_clearances.area, .004)
        path_count = len(plan.center_paths.geoms) if hasattr(plan.center_paths, "geoms") else 1
        self.assertEqual(path_count, 1)  # collapsed hole path is absent but reported

    def test_approximation_sagitta_budget(self):
        radius, error = .8, .002
        segments = quad_segments_for_error(radius, error)
        actual = radius * (1 - math.cos(math.pi / (4 * segments)))
        self.assertLessEqual(actual, error)
        self.assertGreater(quad_segments_for_error(radius, error / 2), segments)
        self.assertEqual(plan_isolation(box(0, 0, 2, 2), VBit(), .1,
                                        approximation_error_bound_mm=error).approximation_error_bound_mm, error)

    def test_canonical_serialization_and_hash_are_deterministic(self):
        one = synthetic_canonical_geometry()
        two = synthetic_canonical_geometry()
        self.assertEqual(one.canonical_bytes(), two.canonical_bytes())
        self.assertEqual(one.content_hash, two.content_hash)
        self.assertEqual(one.material("bottom-copper").bounds, (0.0, 8.0, 3.0, 10.0))
        self.assertFalse(one.implicit_bottom_mirror)
        with self.assertRaises(TypeError):
            one.source_features[0]["semantic"] = "mutated"
        with self.assertRaises(TypeError):
            one.drill_features[0]["diameterMm"] = 123.0

    def test_canonical_units_provenance_and_status_gates(self):
        geom = box(0, 0, 1, 1)
        with self.assertRaisesRegex(ValueError, "CANONICAL_UNITS"):
            CanonicalGeometry("in", "frame", False, (), "VALID", "VERIFIED", "BLOCKED")
        with self.assertRaisesRegex(ValueError, "ELIGIBILITY_REQUIRES"):
            CanonicalGeometry("mm", "frame", False, (), "UNKNOWN", "PARTIAL", "ELIGIBLE")
        model = CanonicalGeometry("mm", "frame", False,
            (LayerMaterial("top", "top", "dark", geom, (("top.gbr", "abc"),)),),
            "VALID", "VERIFIED", "ELIGIBLE")
        self.assertEqual(model.layers[0].provenance, (("top.gbr", "abc"),))
        self.assertEqual(eligibility_for_simulation(model)[0], True)
        blocked = CanonicalGeometry("mm", "frame", False, (), "NONCONFORMING", "PARTIAL", "BLOCKED")
        self.assertFalse(eligibility_for_simulation(blocked)[0])

    def test_side_orientation_is_explicit_and_never_implicitly_mirrored(self):
        model = synthetic_canonical_geometry()
        top = model.material("top-copper").bounds
        bottom = model.material("bottom-copper").bounds
        self.assertEqual(top[0:2], (-.85, -.85))
        self.assertEqual(bottom, (0.0, 8.0, 3.0, 10.0))
        self.assertFalse(model.implicit_bottom_mirror)

    def test_v11_json_schema_and_millimeter_geojson_material(self):
        schema_path = ROOT / "phase2l" / "schema" / "canonical-pcb-geometry-1.1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        model = synthetic_canonical_geometry()
        payload = model.to_dict(); payload["contentHash"] = model.content_hash
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(payload)), [])
        self.assertEqual(payload["layers"][0]["materialGeoJson"]["type"], "MultiPolygon")
        self.assertIn("implicitBottomMirror", payload["boardCoordinateFrame"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
