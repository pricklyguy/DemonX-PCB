"""Phase 2O independent geometry assertions and private real-board acceptance."""
from __future__ import annotations

import os
import sys
import unittest
import hashlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2g"))
from phase2l.geometry import VBit, plan_isolation
from phase2o.isolation import (identify_residual_candidates, plan_selective_clearing,
                               plan_two_pass)


CUTTER = VBit(30, .1)
DEPTH = .1
ERROR = .002


class TwoPassGeometryTests(unittest.TestCase):
    def test_single_pass_remains_exact_reference_for_connected_pads_and_trace(self):
        pads = [Point(0, 0).buffer(.6, quad_segs=96), Point(3, 0).buffer(.6, quad_segs=96)]
        trace = box(.4, -.15, 2.6, .15)
        separate = Point(8, 0).buffer(.5, quad_segs=48)
        material = GeometryCollection([*pads, trace, separate])
        baseline = plan_isolation(material, CUTTER, DEPTH)
        multipass = plan_two_pass(material, CUTTER, DEPTH, .2)
        self.assertTrue(multipass.single_pass.center_paths.equals(baseline.center_paths))
        self.assertTrue(multipass.single_pass.cutting_footprint.equals(baseline.cutting_footprint))
        self.assertAlmostEqual(baseline.center_paths.length,
                               multipass.single_pass.center_paths.length, places=12)

    def test_full_swept_tool_footprint_rejects_narrow_pad_trace_junction(self):
        left = box(0, 0, 2, 4)
        nearby_pad = box(2.3, 1, 3.4, 3)
        result = plan_two_pass(unary_union([left, nearby_pad]), CUTTER, DEPTH, .2)
        self.assertGreater(result.rejected_length_mm, 0)
        self.assertTrue(any(item.category.startswith("protected-copper") for item in result.rejections))
        self.assertGreater(sum(item.protected_overlap.area for item in result.rejections), 0)
        # Full swept footprint, including the V-bit radius, is tested on each
        # retained fragment with an extra declared approximation margin.
        protected = unary_union([left, nearby_pad]).buffer(ERROR)
        for path in result.accepted_paths.geoms:
            self.assertTrue(path.buffer(result.single_pass.effective_width_mm / 2).disjoint(protected))

    def test_two_separate_pads_below_added_clearance_are_retained_as_rejections(self):
        first = Point(0, 0).buffer(.6, quad_segs=72)
        second = Point(1.5, 0).buffer(.6, quad_segs=72)
        result = plan_two_pass(unary_union([first, second]), CUTTER, DEPTH, .2)
        self.assertGreater(first.distance(second), result.single_pass.effective_width_mm)
        self.assertTrue(any(r.category.startswith("protected-copper") for r in result.rejections))
        self.assertGreater(result.rejected_length_mm, 0)
        self.assertTrue(any(r.path.disjoint(unary_union([first, second])) and
                            r.swept_footprint.intersects(unary_union([first, second]))
                            for r in result.rejections if "collision" in r.category))

    def test_varying_clearance_keeps_open_safe_fragments_and_reports_rejected_middle(self):
        first = box(0, 0, 2, 4)
        second = box(2.3, 1, 3.1, 3)
        result = plan_two_pass(unary_union([first, second]), CUTTER, DEPTH, .2)
        self.assertGreater(result.accepted_length_mm, 0)
        self.assertGreater(result.rejected_length_mm, 0)
        self.assertTrue(any(not line.is_ring for line in result.accepted_paths.geoms))
        self.assertTrue(any(not line.is_ring for line in result.rejected_paths.geoms))
        self.assertTrue(all(line.coords[0] != line.coords[-1] for line in result.accepted_paths.geoms))

    def test_parallel_trace_gap_collision_is_not_hidden_by_centerline_clearance(self):
        first = box(0, 0, 8, .2)
        second = box(0, .5, 8, .7)
        result = plan_two_pass(unary_union([first, second]), CUTTER, DEPTH, .2)
        collision_rejections = [r for r in result.rejections if "collision" in r.category]
        self.assertTrue(collision_rejections)
        self.assertTrue(all(not r.swept_footprint.is_empty for r in collision_rejections))
        self.assertTrue(any(r.path.disjoint(unary_union([first, second])) and
                            r.swept_footprint.intersects(unary_union([first, second]))
                            for r in collision_rejections))
        self.assertGreater(result.rejected_footprint.area, 0)

    def test_invalid_offset_units_and_depth_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "ADDITIONAL_OFFSET"):
            plan_two_pass(box(0, 0, 1, 1), CUTTER, DEPTH, float("nan"))
        with self.assertRaisesRegex(ValueError, "UNITS_MUST_BE_MM"):
            plan_two_pass(box(0, 0, 1, 1), CUTTER, DEPTH, .1, units="inch")
        with self.assertRaisesRegex(ValueError, "DEPTH_EXCEEDS"):
            plan_two_pass(box(0, 0, 1, 1), CUTTER, 2.1, .1)

    def test_concave_copper_is_composed_and_offset_loops_do_not_bridge_components(self):
        concave = Polygon([(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)])
        other = box(5, 0, 6, 1)
        result = plan_two_pass(GeometryCollection([concave, other]), CUTTER, DEPTH, .1)
        self.assertTrue(result.accepted_paths.is_valid)
        self.assertTrue(result.rejected_paths.is_valid)
        # Components remain individual boundaries; no connector path is added.
        self.assertFalse(any(len(line.coords) == 2 and line.length > 1 for line in result.accepted_paths.geoms))

    def test_void_island_and_multiple_offset_loops_are_preserved(self):
        donut = box(0, 0, 6, 6).difference(box(1, 1, 5, 5))
        island = Point(3, 3).buffer(.5, quad_segs=48)
        material = unary_union([donut, island])
        result = plan_two_pass(material, CUTTER, DEPTH, .12)
        self.assertEqual(len([p for p in result.single_pass.center_paths.geoms]), 3)
        self.assertTrue(result.accepted_paths.is_valid)
        self.assertTrue(result.single_pass.cutting_footprint.intersection(island).area < island.area)

    def test_narrow_neck_and_collapsing_void_are_reported_as_topology_changes(self):
        material = box(0, 0, 5, 5).difference(box(2.4, 2.4, 2.6, 2.6))
        result = plan_two_pass(material, CUTTER, DEPTH, .2)
        self.assertTrue(any(r.category == "collapsed void loop" for r in result.rejections))
        self.assertTrue(any("void" in r.message for r in result.rejections))

    def test_incremental_sweep_and_protected_copper_removal_are_measured_separately(self):
        material = box(0, 0, 2, 2)
        result = plan_two_pass(material, CUTTER, DEPTH, .2)
        self.assertGreater(result.incremental_swept_area_mm2, 0)
        self.assertEqual(result.incremental_copper_removal_mm2, 0)
        self.assertFalse(result.manufacturing_authorized)


class SelectiveClearingTests(unittest.TestCase):
    def setUp(self):
        self.material = unary_union([box(0, 0, 1, 1), box(3, 0, 3.8, .8), box(5, 0, 5.1, .3)])
        self.candidates = identify_residual_candidates(self.material, min_area_mm2=.01, max_area_mm2=1.0)

    def test_disconnected_zones_remain_unclassified_and_require_explicit_action(self):
        self.assertEqual(len(self.candidates), 3)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_PREVIEW_CLASSIFICATION"):
            plan_selective_clearing(self.material, self.candidates,
                [self.candidates[0].candidate_id], cutter=CUTTER, depth_mm=DEPTH,
                classified_for_preview=[])

    def test_selected_zone_is_preview_cleared_but_unselected_zone_stays_protected(self):
        selected = max(self.candidates, key=lambda candidate: candidate.area_mm2)
        other = next(c for c in self.candidates if c.candidate_id != selected.candidate_id)
        plan = plan_selective_clearing(self.material, self.candidates, [selected.candidate_id],
            cutter=CUTTER, depth_mm=DEPTH, classified_for_preview=[selected.candidate_id])
        self.assertGreater(plan.cleared_area_mm2, 0)
        self.assertGreater(plan.remaining_selected_copper.area, 0)
        self.assertTrue(any(not path.is_ring for path in plan.accepted_paths.geoms),
                        "safe loop connectors should be represented where a full sweep fits")
        self.assertFalse(plan.manufacturing_authorized)
        self.assertTrue(plan.swept_footprint.disjoint(other.geometry.buffer(ERROR)))

    def test_unreachable_pocket_is_visible_and_unselected_material_unchanged(self):
        tiny = box(5, 0, 5.1, .3)
        selected = identify_residual_candidates(tiny, min_area_mm2=.001, max_area_mm2=1.0)
        plan = plan_selective_clearing(tiny, selected, [selected[0].candidate_id], cutter=CUTTER,
            depth_mm=DEPTH, classified_for_preview=[selected[0].candidate_id])
        self.assertEqual(plan.accepted_paths.length, 0)
        self.assertGreater(plan.unreachable_zones.area, 0)
        self.assertEqual(plan.remaining_selected_copper.area, tiny.area)

    def test_every_accepted_clearing_sweep_is_clear_of_all_unselected_copper(self):
        selected = max(self.candidates, key=lambda candidate: candidate.area_mm2)
        plan = plan_selective_clearing(self.material, self.candidates, [selected.candidate_id],
            cutter=CUTTER, depth_mm=DEPTH, classified_for_preview=[selected.candidate_id])
        protected = self.material.difference(selected.geometry).buffer(ERROR)
        self.assertTrue(plan.swept_footprint.disjoint(protected))
        self.assertEqual(len(plan.selected_ids), 1)


class StrategyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_strategies_and_visibility_toggles_remain_diagnostic(self):
        from PySide6.QtCore import Qt
        from phase2g.pcbprep.main_window import PcbPrepWindow
        window = PcbPrepWindow()
        try:
            window.show_connected_pad_demo()
            original = window.demo_canonical.content_hash
            window.simulation_action.setChecked(True)
            baseline_paths = window.simulation_plan.center_paths
            window.strategy_selector.setCurrentIndex(1)
            self.assertIsNotNone(window.multipass_plan)
            self.assertTrue(window.multipass_plan.single_pass.center_paths.equals(baseline_paths))
            self.assertEqual(window.demo_canonical.machining_eligibility, "BLOCKED")
            self.assertFalse(window.layer_checks["inferred"].isChecked())
            self.assertFalse(window.layer_checks["uncertainty"].isChecked())
            window.layer_checks["pass2"].setChecked(False)
            self.assertFalse(any(isinstance(item.data(0), dict) and
                item.data(0).get("label", "").startswith("Pass 2 accepted candidate")
                for item in window.scene.items()))
            window.layer_checks["rejected"].setChecked(False)
            self.assertFalse(any(isinstance(item.data(0), dict) and
                item.data(0).get("label", "").startswith("Isolation cannot fit")
                for item in window.scene.items()))
            window.layer_checks["rejected"].setChecked(True)
            self.assertTrue(any(isinstance(item.data(0), dict) and
                item.data(0).get("label", "").startswith("Isolation cannot fit")
                for item in window.scene.items()))
            window.strategy_selector.setCurrentIndex(2)
            self.assertGreater(window.clear_candidates_list.count(), 0)
            item = window.clear_candidates_list.item(0)
            candidate_id = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked)
            self.app.processEvents()
            self.assertEqual(window.clearing_plan.selected_ids, (candidate_id,))
            self.assertTrue(window.clearing_plan.classified_for_preview_only)
            self.assertFalse(window.clearing_plan.manufacturing_authorized)
            self.assertEqual(window.demo_canonical.content_hash, original)
        finally:
            window.close()


@unittest.skipUnless(os.environ.get("DEMONX_PHASE2N_ARCHIVE"), "Private archive path not configured")
class ValentineHeart2Acceptance(unittest.TestCase):
    def test_real_nextpcb_board_uses_same_single_pass_and_has_collision_checked_pass_two(self):
        sys.path.insert(0, str(ROOT / "phase2g"))
        from pcbprep.inspection_model import load_archive
        archive = Path(os.environ["DEMONX_PHASE2N_ARCHIVE"])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
            "88423ef79cf6baf21fcb1e40ac2a903550fae900cc1ad76a020c06dfedda25d5")
        document = load_archive(archive)
        try:
            bottom = document.canonical_geometry.material("bottom-copper")
            canonical_hash = document.canonical_geometry.content_hash
            result = plan_two_pass(bottom, CUTTER, DEPTH, .2)
            self.assertAlmostEqual(result.single_pass.center_paths.length, 3400.34449836058, places=5)
            self.assertEqual(len(result.single_pass.center_paths.geoms), 225)
            self.assertGreater(result.accepted_length_mm, 0)
            self.assertGreater(result.rejected_length_mm, 0)
            self.assertGreater(len(result.rejections), 0)
            self.assertEqual(result.incremental_copper_removal_mm2, 0)
            self.assertFalse(result.manufacturing_authorized)
            self.assertEqual(document.canonical_geometry.machining_eligibility, "BLOCKED")
            self.assertEqual(document.canonical_geometry.content_hash, canonical_hash)
            verified_overlap = result.accepted_footprint.intersection(bottom.buffer(ERROR))
            self.assertTrue(verified_overlap.is_empty)
        finally:
            document.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
