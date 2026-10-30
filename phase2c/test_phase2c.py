"""Phase 2C independent-command baselines and safety regression tests."""
import json
import hashlib
import math
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"phase2b"/".venv"/"Lib"/"site-packages"))
sys.path.insert(0,str(ROOT/"phase2c"))
import verify_phase2c as v


class Phase2CRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.copper=json.loads((ROOT/"phase2c/results/copper-comparison.json").read_text(encoding="utf-8"))
        cls.drills=json.loads((ROOT/"phase2c/results/drill-reconciliation.json").read_text(encoding="utf-8"))
        cls.profiles=json.loads((ROOT/"phase2c/results/profile-comparison.json").read_text(encoding="utf-8"))["profiles"]
        cls.registration=json.loads((ROOT/"phase2c/results/coordinate-registration.json").read_text(encoding="utf-8"))["boards"]
        cls.arcs=json.loads((ROOT/"phase2c/results/delta-arc-analytic.json").read_text(encoding="utf-8"))["arcs"]
        cls.repairs=json.loads((ROOT/"phase2c/results/copper-repair-audit.json").read_text(encoding="utf-8"))["repairs"]
        cls.environment=json.loads((ROOT/"phase2c/results/environment.json").read_text(encoding="utf-8"))

    def test_original_archive_hashes_remain_golden(self):
        for item in self.environment["sourceArchives"]:
            path=ROOT/"gerbers"/item["file"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),item["sha256"])

    def test_independent_copper_golden_metrics(self):
        self.assertEqual(len(self.copper["files"]),4)
        for layer in self.copper["files"]:
            c=layer["comparison"]
            self.assertLessEqual(c["boundaryHausdorffMm"],0.01)
            self.assertAlmostEqual(c["pygerberReference"]["areaMm2"],layer["referenceMetrics"]["areaMm2"],places=8)
            self.assertEqual(c["pygerberReference"]["components"],c["phase2aGerbonara"]["components"])
            self.assertEqual(c["pygerberReference"]["interiorVoids"],c["phase2aGerbonara"]["interiorVoids"])
            self.assertTrue(layer["sourceSha256"])

    def test_drill_source_reconciliation_and_duplicate_provenance(self):
        n=self.drills["sourceRecordCounts"]
        self.assertEqual(n,{"circularHits":413,"routedSlots":8,"total":421})
        self.assertEqual(self.drills["exactOverlapGroups"],12)
        self.assertEqual(self.drills["physicalCircularHoleCandidates"],401)
        self.assertEqual(len(self.drills["duplicatePhysicalCandidates"]),12)
        for item in self.drills["duplicatePhysicalCandidates"]:
            self.assertEqual(item["physicalOperationCount"],1)
            self.assertEqual(len(item["sourceRecords"]),2)
            self.assertTrue(all(item["copperPadFlashEvidence"][side] for side in ("top","bottom")))
            self.assertIn("PRESERVE_BOTH_PROVENANCE_LINKS",item["machiningStatus"])

    def test_required_drill_groups_and_unassigned_reconcile(self):
        groups=self.drills["requiredGroups"]
        self.assertEqual([x["count"] for x in groups],[262,58,0,6,0,0,0])
        self.assertEqual(sum(x["count"] for x in groups)+sum(x["count"] for x in self.drills["unassignedDiameterDistribution"]),413)
        self.assertEqual(sum(x["count"] for x in self.drills["unassignedDiameterDistribution"]),87)
        self.assertTrue(all(x["warningCode"]=="DRILL_DIAMETER_UNASSIGNED" for x in self.drills["unassignedDiameterDistribution"]))

    def test_output_planner_rejects_accidental_duplicate_operation(self):
        feature={"xMm":1.0,"yMm":2.0,"diameterMm":0.8}
        with self.assertRaises(ValueError): v.ensure_no_duplicate_output_operations([feature,dict(feature)])
        key=(1.0,2.0,0.8)
        self.assertEqual(v.ensure_no_duplicate_output_operations([feature,dict(feature)],explicitly_approved=[key]),[key])

    def test_profile_and_registration_baselines(self):
        self.assertEqual(len(self.profiles),2)
        for p in self.profiles:
            self.assertAlmostEqual(p["comparison"]["symmetricDifferenceAreaMm2"],0.0,places=10)
            self.assertLess(p["comparison"]["boundaryHausdorffMm"],1e-9)
            self.assertEqual(p["closedPolygonCount"],1)
            self.assertEqual(p["dangleLengthMm"],0.0)
        for b in self.registration:
            self.assertEqual(b["drillInsideProfile"]["hitsOutside"],0)
            self.assertEqual(b["drillInsideProfile"]["slotsOutside"],0)
            self.assertEqual(b["topBottomTransform"],"identity on source frame")
            self.assertLess(b["machiningSideMirrorRoundTrip"]["maxRoundTripResidualMm"],1e-12)
        self.assertEqual(self.registration[0]["padCenterCorrelationBySide"]["top"]["platedRecordMatchesWithinDeclaredQuantum"],226)
        self.assertEqual(self.registration[1]["padCenterCorrelationBySide"]["top"]["platedRecordMatchesWithinDeclaredQuantum"],183)

    def test_analytic_arc_extrema_and_known_delta_mismatch(self):
        # CCW quarter circle from +X to +Y, expanded by a 0.2 mm circular aperture.
        bounds=v.analytic_arc_bounds((1,0),(0,1),(0,0),False,0.2)
        for actual,expected in zip(bounds,(-0.1,-0.1,1.1,1.1)):
            self.assertAlmostEqual(actual,expected,places=12)
        self.assertEqual(len(self.arcs),293)
        mismatches=[x for x in self.arcs if x.get("maxAbsDeltaMm",0)>1e-6]
        self.assertEqual(len(mismatches),279)
        self.assertAlmostEqual(max(x["maxAbsDeltaMm"] for x in mismatches),2.50012,places=5)

    def test_copper_repairs_repeat_and_preserve_measured_material(self):
        self.assertEqual(len(self.repairs),2)
        for r in self.repairs:
            self.assertFalse(r["rawGeometryValid"])
            self.assertTrue(r["deterministicNormalizedWkbEqual"])
            self.assertLess(abs(r["areaDeltaMm2"]),1e-9)
            self.assertTrue(r["nonPolygonalRemainders"])

    def test_ordered_dark_clear_composition_restores_later_dark(self):
        from shapely.geometry import box
        base=box(0,0,3,3);clear=box(1,1,2,2);dark=box(1.4,1.4,1.6,1.6)
        out=v.ordered_compose([(True,base),(False,clear),(True,dark)])
        self.assertAlmostEqual(out.area,8.04,places=12)
        self.assertTrue(out.covers(box(1.4,1.4,1.6,1.6)))
        self.assertFalse(out.covers(box(1.1,1.1,1.2,1.2)))


if __name__=="__main__": unittest.main(verbosity=2)
