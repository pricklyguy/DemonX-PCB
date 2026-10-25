"""Regression tests for the Laser Module native/export revision comparison."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import compare_revision as compare


class RevisionComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=json.loads((ROOT/"phase2f/results/revision-comparison.json").read_text(encoding="utf-8"))
        cls.manifest=json.loads((ROOT/"phase2f/results/source-manifest.json").read_text(encoding="utf-8"))

    def test_source_hashes_and_staged_copies_are_bound(self):
        import hashlib
        self.assertEqual(hashlib.sha256(compare.STAGED_EXPORT.read_bytes()).hexdigest(),self.manifest["v20ExportZip"]["sha256"])
        self.assertEqual(hashlib.sha256(compare.STAGED_NATIVE.read_bytes()).hexdigest(),self.manifest["v20NativePcb"]["sha256"])
        self.assertEqual(hashlib.sha256(compare.V25_ARCHIVE.read_bytes()).hexdigest(),self.manifest["v25Archive"]["sha256"])
        self.assertFalse(self.manifest["externalOriginalsModified"])

    def test_all_open_region_commands_repeat_exactly(self):
        r=self.result["sourceRegions"]
        self.assertEqual((r["countV20"],r["countV25"]),(182,182))
        self.assertEqual(r["exactCommandSequenceMatches"],182)
        self.assertEqual(r["exactCoordinateSequenceMatches"],182)
        self.assertTrue(r["sourceRangesAllSame"])
        self.assertEqual(r["polarityCountsV20"],{"D":1,"C":181})
        self.assertEqual(r["polarityCountsV25"],{"D":1,"C":181})

    def test_both_copper_layers_have_equal_primitives_and_polarity_runs(self):
        for name,expected in (("Gerber_TopLayer.GTL",191),("Gerber_BottomLayer.GBL",627)):
            layer=self.result["files"][name]["effectiveGeometryComparison"]
            self.assertEqual(layer["commandCountV20"],expected)
            self.assertEqual(layer["commandCountV25"],expected)
            self.assertEqual(layer["unchangedDescriptorCount"],expected)
            self.assertEqual(layer["changedPrimitiveCount"],0)
            self.assertTrue(layer["polarityRunGeometryEquivalent"])

    def test_native_outline_transform_and_dimensions(self):
        t=self.result["coordinateTransformNativeToGerber"]
        self.assertEqual(t["xScale"],"0.254")
        self.assertEqual(t["yScale"],"-0.254")
        self.assertFalse(t["sideMirrorApplied"])
        self.assertLessEqual(float(t["fitResidualMm"]),0.00001)
        bounds=list(map(float,t["gerberSourceCoordinateBoundsMm"]))
        self.assertAlmostEqual(bounds[2]-bounds[0],116.45877,places=5)
        self.assertAlmostEqual(bounds[3]-bounds[1],83.43882,places=5)

    def test_native_cached_fill_maps_every_candidate_but_does_not_approve(self):
        native=self.result["nativeCachedCopperFillComparison"]
        self.assertEqual(native["nativeFillPathCount"],182)
        self.assertEqual(native["candidateEdgesFullyWithin0_005mmOfNativeCachedFillLinework"],182)
        self.assertTrue(native["candidateToCachedFillPathMappingOneToOne"])
        self.assertLessEqual(native["maximumConservativeDeviationUpperBoundMm"],0.005)
        self.assertFalse(self.result["validationBoundary"]["closureRulePromoted"])
        self.assertFalse(self.result["validationBoundary"]["all182RegionsApproved"])
        self.assertFalse(self.result["validationBoundary"]["machiningReady"])
        rings=self.result["candidateRingVsNativeCachedFillComparison"]
        self.assertEqual(rings["comparisonCount"],182)
        self.assertEqual(rings["invalidOrUnmatchedCount"],0)
        self.assertEqual(rings["candidateRegionsWithin0_005mmBoundaryHausdorff"],181)
        self.assertEqual(rings["candidateRegionsOver0_005mmBoundaryHausdorff"],[79])
        self.assertGreater(rings["maximumSymmetricDifferenceAreaMm2"],3.5)
        phase2e=json.loads((ROOT/"phase2e/results/validation-records.json").read_text(encoding="utf-8"))
        blocked=[x for x in phase2e["records"] if x["boardId"]=="gerber-prickly-laser-module-2-5" and x["status"]=="BLOCKED"]
        self.assertEqual(len(blocked),182)

    def test_circular_drills_and_slots_match_native_and_each_other(self):
        drills=self.result["drillAndPadComparison"]
        self.assertTrue(drills["v2ExportsHitRecordsIdentical"])
        self.assertEqual(drills["nativeThroughHolePadCount"],191)
        for label,row in drills["exportHitComparison"].items():
            self.assertEqual((row["hitCount"],row["slotCount"]),(183,8))
            self.assertEqual(row["matchedNativePadCount"],183)
            self.assertEqual(row["unmatchedExportHitCount"],0)
            self.assertEqual(row["slotMidpointMatches"],8)
            self.assertTrue(row["nativeSlotPadsMatchedUniquely"])
            self.assertLess(row["maxXYResidualMm"],0.001)
            self.assertLess(row["maxHoleDiameterResidualMm"],0.002)
            self.assertLess(row["maxNativeSlotEndpointResidualMm"],0.002)
            self.assertLess(row["maxNativeSlotLengthResidualMm"],0.002)

    def test_profile_and_drill_export_bodies_match_v25(self):
        files=self.result["files"]
        self.assertTrue(files["Gerber_BoardOutlineLayer.GKO"]["commandRowsIdenticalIgnoringCommentsApertureDefinitions"])
        for name in ("Drill_PTH_Through.DRL","Drill_PTH_Through_Via.DRL"):
            self.assertTrue(files[name]["geometricBodyIdenticalAfterComments"])

    def test_archives_are_extracted_only_to_expected_paths(self):
        self.assertEqual(set(p.name for p in compare.EXTRACTED.iterdir()),compare.EXPECTED_MEMBERS)
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/"unsafe.zip"
            with zipfile.ZipFile(archive,"w") as zf:
                zf.writestr("../Gerber_BottomLayer.GBL",b"bad")
            with self.assertRaises(ValueError):
                compare.checked_extract(archive,Path(tmp)/"out")

    def test_native_fuse_revision_is_not_misrepresented_as_v25_native(self):
        self.assertEqual([x["reference"] for x in self.result["v20NativeFuseComponents"]],["F2","F3"])
        self.assertIn("Overall v2.5 revision identity is not proven",self.result["sourceIdentityAssessment"]["interpretation"])


if __name__=="__main__":
    unittest.main(verbosity=2)
