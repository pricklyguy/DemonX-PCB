from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from shapely import hausdorff_distance
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2j"))
sys.path.insert(0, str(ROOT / "phase2d"))
import geometry_contract as contract
import verify_valentine_native as native
import forensics


class Phase2JTests(unittest.TestCase):
    def test_source_archive_hashes_revision_and_manifest(self):
        epro = Path(r"E:\Gerber_Recovery\ProPrj_PCB_Valentine_2026_2026-02-05.epro")
        archive = ROOT / "gerbers" / "Gerber_PCB_Valentine_Feb_New.zip"
        if not epro.is_file() or not archive.is_file():
            self.skipTest("Local immutable native/fixture inputs are not provisioned")
        project = native.read_project(epro)
        self.assertEqual(project["project"]["config"]["editorVersion"], "2.2.45.4")
        self.assertEqual(len(project["documentHeads"]), 2)
        self.assertTrue(any(str(head.get("uuid", "")).startswith(project["pcbId"])
                            for head in project["documentHeads"] if isinstance(head, dict)))
        self.assertTrue(all(len(row["sha256"]) == 64 for row in project["members"]))
        result = native.run(epro, archive, ROOT / "phase2j" / "results")
        self.assertEqual(result["nativeProject"]["archiveSha256"], project["archiveSha256"])
        self.assertEqual(result["independentAnchorRegistration"]["matchedViaAnchors"], 12)
        self.assertEqual(result["independentAnchorRegistration"]["matchedDuplicatePthAnchors"], 12)
        outline = result["outlineBoundsRegistration"]
        self.assertEqual(outline["referenceStatus"], "HASH_MATCHED")
        self.assertLess(max(abs(value) for value in outline["boundsDeltaMm"]), .00001)

    def test_native_arc_decoder_respects_mm_and_bounded_chord_error(self):
        path = native.parse_poured_path([0.0, 0.0, "ARC", 90.0, 1.0, 1.0])
        self.assertEqual(path["segments"][0]["kind"], "arc")
        self.assertTrue(path["polygonizedBoundary"] is None)  # not closed: no implicit snap
        self.assertFalse(path["closedExactly"])
        self.assertAlmostEqual(path["linearizedPoints"][-1][0], 0.254)
        self.assertAlmostEqual(path["linearizedPoints"][-1][1], 0.254)

    def test_strict_cut_in_material_has_valid_hole_topology_without_make_valid(self):
        source = forensics.scan((ROOT / "phase2d" / "fixtures" / "cutin.gbr").read_text())[0]
        geometry = forensics.region_geometry_ticks(source)
        self.assertTrue(geometry.is_valid)
        self.assertEqual(len(geometry.interiors), 1)
        self.assertAlmostEqual(geometry.area, 840_000_000_000)

    def test_diagnostic_offsets_are_repeatable_on_valid_representation(self):
        source = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)], holes=[[(.5, .5), (1.5, .5), (1.5, 1.5), (.5, 1.5)]])
        first = native.diagnostic_offsets(source, source)
        second = native.diagnostic_offsets(source, source)
        self.assertEqual(first, second)
        for row in first:
            self.assertEqual(row["symmetricDifferenceAreaMm2"], 0)
            self.assertEqual(row["referenceComponents"], row["candidateComponents"])
            self.assertEqual(hausdorff_distance(source.boundary, source.boundary), 0)

    def test_contract_hash_is_deterministic_and_statuses_remain_separate(self):
        document = {
            "schemaVersion": "1.0.0", "units": "mm", "sourceFiles": [],
            "boardCoordinateFrame": {"name": "board", "origin": "source-defined",
                "axes": "right-handed XY in source coordinates",
                "sideTransforms": {"top": {"matrix2x3": [[1,0,0],[0,1,0]], "purpose": "none"},
                                   "bottom": {"matrix2x3": [[1,0,0],[0,1,0]], "purpose": "none"}},
                "implicitBottomMirror": False},
            "layers": [], "features": [],
            "recovery": {"status": "disclosed", "policyId": "exact-noop-only", "changes": [], "arbitrarySnapping": False},
            "validation": {"sourceConformance": "NONCONFORMING", "independentGeometryVerification": "PARTIAL",
                           "manufacturingEligibility": "BLOCKED", "verificationEvidence": []},
            "geometryTolerance": {"boundaryDeviationMm": .005, "areaDifferenceMm2": 0,
                                   "method": "bounded source-precision comparison", "approximationBoundMm": 0},
        }
        first = contract.seal(document)
        second = contract.seal(dict(reversed(list(document.items()))))
        self.assertEqual(first["contentHash"], second["contentHash"])
        contract.validate_status_separation(first)
        first["validation"]["manufacturingEligibility"] = "ELIGIBLE"
        with self.assertRaisesRegex(ValueError, "ELIGIBILITY"):
            contract.validate_status_separation(first)

    def test_existing_laser_and_geos_blockers_are_not_cleared(self):
        report = (ROOT / "docs" / "PHASE2I_PRACTICAL_VALIDATION_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("182 open-contour findings", report)
        self.assertIn("Region 79", report)
        self.assertIn("machining **BLOCKED**", report)
        self.assertIn("NEEDS VERIFICATION", report)

    def test_contract_schema_is_valid_json_with_explicit_safety_invariants(self):
        schema = json.loads((ROOT / "phase2j" / "schema" / "canonical-pcb-geometry.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["boardCoordinateFrame"]["$ref"], "#/$defs/frame")
        self.assertEqual(schema["$defs"]["frame"]["properties"]["implicitBottomMirror"], {"const": False})
        self.assertEqual(schema["$defs"]["recovery"]["properties"]["arbitrarySnapping"], {"const": False})

    def test_native_comparison_keeps_measured_disagreements_visible(self):
        result_path = ROOT / "phase2j" / "results" / "verification.json"
        if not result_path.is_file():
            self.skipTest("Private native comparison results not generated")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["sourceRevisionAssessment"], "PARTIAL")
        self.assertEqual(result["manufacturingApproval"], "WITHHELD")
        rows = result["regionComparisons"]
        self.assertEqual([row["gerberNoOpDraws"] for row in rows], [105, 14])
        self.assertEqual([row["metrics"]["referenceInteriorVoids"] for row in rows], [103, 14])
        self.assertGreater(rows[0]["metrics"]["symmetricDifferenceAreaMm2"], 2.2)
        self.assertGreater(rows[0]["metrics"]["boundaryHausdorffMm"], .005)
        self.assertEqual(len(result["diagnosticOverlays"]), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
