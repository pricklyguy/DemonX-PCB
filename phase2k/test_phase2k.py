from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2j"))
import geometry_contract as contract  # noqa: E402


SCHEMA_PATH = ROOT / "phase2j" / "schema" / "canonical-pcb-geometry.schema.json"


def sample_document() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "units": "mm",
        "sourceFiles": [{
            "id": "gerber-bottom",
            "name": "bottom.gbr",
            "sha256": "a" * 64,
            "archiveSha256": "b" * 64,
            "format": "Gerber X2",
            "units": "mm",
            "coordinatePrecision": "0.00001 mm",
            "sourceRevision": "fixture",
        }],
        "boardCoordinateFrame": {
            "name": "board",
            "origin": "source-defined",
            "axes": "right-handed XY in source coordinates",
            "sideTransforms": {
                "top": {"matrix2x3": [[1, 0, 0], [0, 1, 0]], "purpose": "none"},
                "bottom": {"matrix2x3": [[1, 0, 0], [0, 1, 0]], "purpose": "none"},
            },
            "implicitBottomMirror": False,
        },
        "layers": [],
        "features": [],
        "recovery": {"status": "none", "policyId": None, "changes": [], "arbitrarySnapping": False},
        "validation": {
            "sourceConformance": "VALID",
            "independentGeometryVerification": "PARTIAL",
            "manufacturingEligibility": "BLOCKED",
            "verificationEvidence": [],
        },
        "geometryTolerance": {
            "boundaryDeviationMm": 0.005,
            "areaDifferenceMm2": 0,
            "method": "source-precision comparison",
            "approximationBoundMm": None,
        },
        "contentHash": "sha256:" + "0" * 64,
    }


class Phase2KTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_passes_draft_2020_12_meta_schema_and_sample(self):
        Draft202012Validator.check_schema(self.schema)
        doc = contract.seal(sample_document())
        errors = list(Draft202012Validator(self.schema).iter_errors(doc))
        self.assertEqual(errors, [])

    def test_serialization_and_content_hash_are_deterministic(self):
        doc = sample_document()
        sealed = contract.seal(doc)
        reordered = contract.seal(dict(reversed(list(doc.items()))))
        self.assertEqual(contract.canonical_bytes(sealed), contract.canonical_bytes(reordered))
        self.assertEqual(sealed["contentHash"], reordered["contentHash"])

    def test_eligibility_guard_keeps_unverified_geometry_blocked(self):
        doc = contract.seal(sample_document())
        contract.validate_status_separation(doc)
        doc["validation"]["manufacturingEligibility"] = "ELIGIBLE"
        with self.assertRaisesRegex(ValueError, "ELIGIBILITY_REQUIRES_VALIDATED_GEOMETRY"):
            contract.validate_status_separation(doc)

    def test_source_identity_requires_hashes_and_names_archive(self):
        doc = sample_document()
        errors = list(Draft202012Validator(self.schema).iter_errors(contract.seal(doc)))
        self.assertEqual(errors, [])
        doc["sourceFiles"][0]["sha256"] = "bad"
        errors = list(Draft202012Validator(self.schema).iter_errors(contract.seal(doc)))
        self.assertTrue(any(list(error.absolute_path) == ["sourceFiles", 0, "sha256"] for error in errors))

    def test_explicit_side_transform_is_applied_without_implicit_mirror(self):
        transform = {"matrix2x3": [[-1, 0, 10], [0, 1, 0]], "purpose": "machining-side"}
        self.assertEqual(contract.apply_explicit_transform((2, 3), transform), (8.0, 3.0))
        identity = {"matrix2x3": [[1, 0, 0], [0, 1, 0]], "purpose": "none"}
        self.assertEqual(contract.apply_explicit_transform((2, 3), identity), (2.0, 3.0))
        with self.assertRaisesRegex(ValueError, "INVALID_EXPLICIT_TRANSFORM"):
            contract.apply_explicit_transform((2, 3), {"purpose": "machining-side"})

    def test_original_archive_hashes_remain_unchanged_when_present(self):
        archive = ROOT / "gerbers" / "Gerber_PCB_Valentine_Feb_New.zip"
        native = Path(r"E:\Gerber_Recovery\ProPrj_PCB_Valentine_2026_2026-02-05.epro")
        if not archive.is_file() or not native.is_file():
            self.skipTest("Private immutable inputs are not provisioned")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         "2e23a8cff4bd48d947f5f7fda371b8669d054c03cc87bb561bc2854d39337796")
        self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(),
                         "43c1992652a107d1e7967ae902a643701695c2132cfbf87ce2b475c7fe7cc440")

    def test_existing_laser_restrictions_remain_documented(self):
        report = (ROOT / "docs" / "PHASE2F_NATIVE_REVISION_COMPARISON_REPORT.md").read_text(encoding="utf-8").lower()
        for text in ("182", "181", "region 79", "blocked"):
            self.assertIn(text, report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
