from __future__ import annotations

import os
import sys
import unittest
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2g"))
sys.path.insert(0, str(ROOT / "phase2l"))
sys.path.insert(0, str(ROOT / "phase2m"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from geometry import (VBit, connected_pad_trace_fixture, plan_isolation,
                      synthetic_demo_material, classify_footprint_overlap,
                      synthetic_connected_canonical_geometry)
from operations import evaluate_operation_status, relevant_to_operation
from repair import (DEFAULT_CLOSURE_TOLERANCE_MM, approve_proposal,
                    propose_closure)
from visual_style import proposed_toolpath_pen, repair_proposal_pen
from pcbprep.main_window import PcbPrepWindow
from shapely.geometry import GeometryCollection, LineString, Point, box
from shapely.ops import unary_union


def d01_commands():
    return [{"line": i + 1, "operation": "D01", "mode": "G01"} for i in range(4)]


class Phase2MWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_primitive_union_removes_connected_pad_trace_seams(self):
        primitives, junctions = connected_pad_trace_fixture()
        plan = plan_isolation(primitives, VBit(30, .1), .1)
        width = VBit(30, .1).effective_width_mm(.1)
        radius = width / 2
        primitive_offsets = [shape.buffer(radius, quad_segs=32) for shape in primitives.geoms]
        precomposition_unfit = unary_union([a.intersection(b)
            for a, b in combinations(primitive_offsets, 2)])
        naive_paths = [shape.boundary for shape in primitive_offsets]
        naive_footprint = unary_union([path.buffer(radius, quad_segs=32) for path in naive_paths])
        source_material = unary_union(list(primitives.geoms))
        precomposition_raw_intrusion = naive_footprint.intersection(source_material).area
        corrected_raw_intrusion = plan.copper_intrusion.area + plan.geometry_uncertainty.area
        # The fixture is the single shared copper material plus the two separate
        # near-touching pads. Only their independent gap may create a collision.
        self.assertEqual(plan.center_paths.geom_type, "GeometryCollection")
        self.assertGreater(len(plan.center_paths.geoms), 0)
        self.assertEqual(len(plan.issues), 3)  # true no-fit, approximation uncertainty, and measured intrusion
        self.assertTrue(any(issue.category == "cutter does not fit" and
                            issue.coordinate_mm[0] > 7.0 for issue in plan.issues))
        self.assertTrue(any(issue.category == "potential copper damage" for issue in plan.issues))
        self.assertGreater(precomposition_unfit.area, plan.unfit_clearances.area)
        self.assertGreater(precomposition_raw_intrusion, corrected_raw_intrusion)
        self.assertAlmostEqual(plan.unfit_clearances.area, .052730711610783784, places=8)
        self.assertAlmostEqual(corrected_raw_intrusion, .10469169551551857, places=8)
        for x, y in junctions:
            point = Point(x, y)
            self.assertGreater(plan.center_paths.distance(point), plan.centerline_offset_mm)
            for issue in plan.issues:
                if issue.category == "potential copper damage":
                    self.assertTrue(issue.geometry.intersection(point.buffer(.01)).is_empty)

    def test_connected_material_has_one_exterior_isolation_contour(self):
        primitives, junctions = connected_pad_trace_fixture()
        # Restrict to the joined three copper primitives; overlapping inputs
        # must be dissolved before computing an exterior boundary.
        joined = GeometryCollection([primitives.geoms[index] for index in range(3)])
        plan = plan_isolation(joined, VBit(30, .1), .1)
        self.assertEqual(len(plan.center_paths.geoms), 1)
        self.assertTrue(plan.center_paths.geoms[0].is_ring)
        self.assertTrue(plan.unfit_clearances.is_empty)
        self.assertFalse(any(issue.category == "cutter does not fit" for issue in plan.issues))
        for x, y in junctions:
            self.assertGreater(plan.center_paths.distance(Point(x, y)), 0)

    def test_clearance_and_damage_shrink_with_depth_and_report_measurements(self):
        fixture = synthetic_demo_material()
        high = plan_isolation(fixture, VBit(30, .1), .1)
        low = plan_isolation(fixture, VBit(30, .1), .05)
        self.assertAlmostEqual(high.effective_width_mm, .15358983848622454, places=12)
        self.assertAlmostEqual(low.effective_width_mm, .1267949192431123, places=12)
        self.assertGreater(high.unfit_clearances.area, low.unfit_clearances.area)
        self.assertGreater(high.copper_intrusion.area, 0.0)
        self.assertGreater(low.copper_intrusion.area, 0.0)
        self.assertGreater(high.copper_intrusion.area + high.geometry_uncertainty.area,
                           low.copper_intrusion.area + low.geometry_uncertainty.area)
        self.assertGreater(high.geometry_uncertainty.area, 0)
        # Preserve exact measurements while separating approximation-band overlap.
        self.assertAlmostEqual(high.unfit_clearances.area, .1929108098626266, places=8)
        self.assertAlmostEqual(low.unfit_clearances.area, .14662011671840913, places=8)

    def test_overlap_classifier_distinguishes_damage_and_approximation_artifact(self):
        material = box(0, 0, 2, 2)
        boundary_noise = box(-.0005, .5, .0005, 1.5)
        actual_intrusion = box(.01, .5, .02, 1.5)
        footprint = boundary_noise.union(actual_intrusion)
        damage, uncertain, issues = classify_footprint_overlap(
            material, footprint, .15, approximation_error_bound_mm=.001)
        self.assertAlmostEqual(uncertain.area, boundary_noise.intersection(material).area)
        self.assertAlmostEqual(damage.area, actual_intrusion.area)
        self.assertEqual({issue.category for issue in issues},
                         {"geometry uncertainty", "potential copper damage"})

    def test_operation_filter_drops_silkscreen_but_keeps_full_archive_findings(self):
        silk = {"layer": "Gerber_TopSilkScreenLayer.GTO", "kind": "parser", "category": "BLOCKED"}
        copper = {"layer": "Gerber_BottomLayer.GBL", "kind": "region", "category": "NEEDS VERIFICATION"}
        drill = {"layer": "PTH drill files", "kind": "drill", "category": "NEEDS VERIFICATION"}
        profile = {"layer": "Gerber_BoardOutlineLayer.GKO", "kind": "profile", "category": "BLOCKED"}
        self.assertFalse(relevant_to_operation(silk, "copper-isolation"))
        self.assertTrue(relevant_to_operation(silk, "full-archive"))
        self.assertTrue(relevant_to_operation(copper, "copper-isolation"))
        self.assertTrue(relevant_to_operation(drill, "drilling"))
        self.assertFalse(relevant_to_operation(drill, "outline-cutting"))
        self.assertTrue(relevant_to_operation(profile, "outline-cutting"))
        state = evaluate_operation_status("copper-isolation", [silk],
            source_conformance="NONCONFORMING", independent_verification="PARTIAL")
        self.assertEqual(state.status, "NOT VERIFIED")
        self.assertEqual(state.source_conformance, "NONCONFORMING")
        verified_unrelated_only = evaluate_operation_status("copper-isolation", [silk],
            source_conformance="VALID", independent_verification="VERIFIED")
        self.assertEqual(verified_unrelated_only.status, "ELIGIBLE FOR FURTHER REVIEW")
        drill_status = evaluate_operation_status("drilling", [drill],
            source_conformance="VALID", independent_verification="VERIFIED")
        outline_status = evaluate_operation_status("outline-cutting", [profile],
            source_conformance="VALID", independent_verification="VERIFIED")
        self.assertEqual(drill_status.status, "BLOCKED")
        self.assertEqual(outline_status.status, "BLOCKED")

    def test_ui_selector_keeps_silk_warning_in_full_archive_only(self):
        window = PcbPrepWindow()
        window._add_issue_row({"title": "silkscreen", "severity": "BLOCKED", "layer": "TopSilkScreen", "category": "BLOCKED"}, "#ff0000")
        window._add_issue_row({"title": "copper", "severity": "NEEDS VERIFICATION", "layer": "Bottom copper", "category": "NEEDS VERIFICATION"}, "#ff0000")
        self.assertEqual(window.issues_list.count(), 1)
        window.operation_selector.setCurrentIndex(3)
        self.app.processEvents()
        self.assertEqual(window.issues_list.count(), 2)
        self.assertIn("FULL ARCHIVE", window.issue_header.text())
        window.close()

    def test_simulation_consumes_connected_canonical_material_and_selects_diagnostic(self):
        window = PcbPrepWindow()
        window.show_connected_pad_demo()
        original = window.demo_canonical.material("top-copper")
        self.assertIs(window.demo_geometry, original)
        window.set_simulation_enabled(True)
        self.app.processEvents()
        self.assertIsNotNone(window.simulation_plan)
        self.assertGreater(len(window.simulation_plan.center_paths.geoms), 0)
        self.assertTrue(any(issue.get("syntheticDiagnostic") for issue, _ in window._all_issue_rows))
        diagnostic_index = next(i for i in range(window.issues_list.count())
            if window.issues_list.item(i).data(Qt.ItemDataRole.UserRole).get("syntheticDiagnostic"))
        window.issues_list.setCurrentRow(diagnostic_index)
        self.app.processEvents()
        self.assertIsNotNone(window.current_issue.get("isolationGeometry"))
        self.assertFalse(window.view_issue_button.isHidden())
        window.close()

    def test_synthetic_repair_preview_shows_gap_and_retains_manual_review(self):
        window = PcbPrepWindow()
        window.show_synthetic_repair_example()
        self.app.processEvents()
        self.assertEqual(window.repair_proposal.status, "NEEDS MANUAL REVIEW")
        self.assertAlmostEqual(window.repair_proposal.gap_mm, .008, places=9)
        self.assertTrue(window.repair_toggle.isChecked())
        self.assertFalse(window.approve_repair_button.isVisible())
        self.assertIn("Endpoint proximity alone", window.inspect_summary.text())
        window.close()

    def test_copper_comparison_selection_draws_display_only_native_overlay(self):
        window = PcbPrepWindow()
        candidate = box(0, 0, 1, 1)
        native = box(.2, 0, 1.2, 1)
        region = SimpleNamespace(index=0, source_points_mm=[(0, 0), (1, 0), (1, 1), (0, 1)],
            recovery_status="PROPOSED_ONLY", native_polygon=native,
            candidate_polygon=candidate, discrepancy_geometry=None,
            discrepancy_point_mm=None, discrepancy_nearest_point_mm=None)
        window.document = SimpleNamespace(regions=[])
        window.current_issue = {"kind": "comparison", "region": region}
        window._add_issue_highlights()
        labels = [item.data(0).get("label") for item in window.scene.items()
                  if isinstance(item.data(0), dict)]
        self.assertIn("Proposed Gerber fill vs cached native fill · diagnostic only", labels)
        self.assertIn("EasyEDA cached native boundary", labels)
        window.document = None
        window.close()

    def test_repair_gap_tolerance_context_and_manual_review_rules(self):
        points = [(0, 0), (1, 0), (1, 1), (0, 1), (0, .01)]
        safe = propose_closure(points, source_commands=d01_commands(), source_layer="synthetic.gbr",
                              polarity="dark", tolerance_mm=DEFAULT_CLOSURE_TOLERANCE_MM,
                              source_role="synthetic")
        self.assertAlmostEqual(safe.gap_mm, .01)
        self.assertEqual(safe.status, "SAFE CANDIDATE")
        self.assertEqual(safe.contour_direction, "counterclockwise")
        self.assertEqual(safe.audit_record["userApproved"], False)
        uncertain = propose_closure(points, source_commands=d01_commands(), source_layer="board.gbr",
                                    polarity="dark", tolerance_mm=.02, source_role="original")
        self.assertEqual(uncertain.status, "NEEDS MANUAL REVIEW")
        self.assertIn("Endpoint proximity alone", uncertain.reason)
        too_long = propose_closure(points, source_commands=d01_commands(), tolerance_mm=.005)
        self.assertEqual(too_long.status, "CANNOT AUTOMATICALLY REPAIR")

    def test_legitimate_cut_in_and_native_mismatch_are_never_safely_closed(self):
        points = [(0, 0), (1, 0), (1, 1), (0, 1), (0, .01)]
        cut_in = propose_closure(points,
            source_commands=d01_commands() + [{"line": 9, "operation": "D02", "mode": "G01"}],
            source_role="synthetic")
        self.assertEqual(cut_in.status, "NEEDS MANUAL REVIEW")
        self.assertIn("D02", cut_in.reason)
        mismatch = propose_closure(points, source_commands=d01_commands(),
            source_role="synthetic", native_boundary_mismatch_mm=.284123)
        self.assertEqual(mismatch.status, "CANNOT AUTOMATICALLY REPAIR")

    def test_repair_detects_even_zero_area_contact_with_protected_copper(self):
        points = [(0, 0), (1, 0), (1, 1), (0, 1), (0, .01)]
        protected = box(-.1, .2, 0, .8)  # candidate only touches the protected edge
        proposal = propose_closure(points, source_commands=d01_commands(), source_role="synthetic",
                                   protected_geometry=protected)
        self.assertEqual(proposal.status, "NEEDS MANUAL REVIEW")
        self.assertEqual(proposal.nearest_geometry_distance_mm, 0.0)
        self.assertTrue(proposal.unintended_intersections)
        self.assertTrue(proposal.audit_record["sourceContourDirection"])

    def test_repair_topology_effect_and_audit_hash_are_deterministic(self):
        points = [(0, 0), (1, 0), (1, 1), (0, 1), (0, .01)]
        first = propose_closure(points, source_commands=d01_commands(), source_role="synthetic")
        second = propose_closure(points, source_commands=d01_commands(), source_role="synthetic")
        self.assertEqual(first.audit_record["sha256"], second.audit_record["sha256"])
        self.assertTrue(first.after_metrics["valid"])
        self.assertEqual(first.after_metrics["components"], 1)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_USER_APPROVAL"):
            approve_proposal(first, explicit_approval=False)
        derived, audit = approve_proposal(first, explicit_approval=True)
        self.assertTrue(derived.is_valid)
        self.assertTrue(audit["userApproved"])
        self.assertEqual(audit["approvedRole"], "verified-derived-working-layer")

    def test_dash_style_is_cosmetic_and_selected_path_is_distinct(self):
        pen = proposed_toolpath_pen()
        selected = proposed_toolpath_pen(selected=True)
        repair = repair_proposal_pen()
        self.assertTrue(pen.isCosmetic())
        self.assertNotEqual(pen.style(), Qt.PenStyle.SolidLine)
        self.assertGreater(selected.widthF(), pen.widthF())
        self.assertTrue(repair.isCosmetic())


if __name__ == "__main__":
    unittest.main(verbosity=2)
