from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "phase2g"), str(ROOT / "phase2d")]

from gerbonara import ExcellonFile, GerberFile  # noqa: E402
import forensics  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from pcbprep.inspection_model import load_archive  # noqa: E402
from pcbprep.main_window import PcbPrepWindow  # noqa: E402


class Phase2ICorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ucamco_official_corpus_known_cases_and_parser_limit(self):
        archive = ROOT / "phase2i/fixtures/ucamco-gerber-tests.zip"
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(digest, "7e1e6bacdc24deb92fbf08940d37ccd26cff25fc9e5ca608b919d4d542d2698f")
        valid_counts = {
            "A_drill_file.gbr": 29,
            "Polarities_and_Apertures.gbr": 23,
            "sample_macro.gbr": 53,
            "SMD_prim_20.gbr": 8,
            "SMD_prim_21.gbr": 8,
            "Two_square_boxes.gbr": 8,
        }
        expected_unsupported = {"Block_with_different_orientations.gbr", "Nested_blocks.gbr"}
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.namelist()
            parsed_cases = {}
            for name, expected_objects in valid_counts.items():
                member = next(item for item in members if item.endswith("/" + name))
                with tempfile.TemporaryDirectory() as td:
                    source = Path(td) / name
                    source.write_bytes(bundle.read(member))
                    parsed = GerberFile.open(source)
                    self.assertEqual(len(parsed.objects), expected_objects, name)
                    if name in {"Polarities_and_Apertures.gbr", "Two_square_boxes.gbr"}:
                        parsed_cases[name] = [primitive for obj in parsed.objects for primitive in obj.to_primitives("mm")]
            polarity_types = Counter(type(p).__name__ for p in parsed_cases["Polarities_and_Apertures.gbr"])
            self.assertEqual(polarity_types, Counter({"Line": 7, "Circle": 9, "Rectangle": 5, "Arc": 1, "ArcPoly": 4}))
            square_lines = parsed_cases["Two_square_boxes.gbr"]
            self.assertEqual(len(square_lines), 8)
            self.assertTrue(all(type(p).__name__ == "Line" and abs(p.width - .01) < 1e-12 for p in square_lines))
            # Official reference example contains two 5 mm square paths, offset 1 mm apart.
            starts = [(p.x1, p.y1) for p in square_lines]
            self.assertEqual(Counter(starts), Counter({(0.0, 0.0): 1, (5.0, 0.0): 1, (5.0, 5.0): 1, (0.0, 5.0): 1,
                                                        (6.0, 0.0): 1, (11.0, 0.0): 1, (11.0, 5.0): 1, (6.0, 5.0): 1}))
            for name in expected_unsupported:
                member = next(item for item in members if item.endswith("/" + name))
                with tempfile.TemporaryDirectory() as td:
                    source = Path(td) / name
                    source.write_bytes(bundle.read(member))
                    with self.assertRaises((SyntaxError, ValueError)):
                        GerberFile.open(source)

    def test_authored_region_conformance_fixtures(self):
        fixture_dir = ROOT / "phase2i/fixtures/regions"
        valid = forensics.scan((fixture_dir / "valid_square.gbr").read_text(encoding="ascii"))[0]
        points = valid["contours"][0]["points"]
        analysis = forensics.analyze(points)
        self.assertTrue(analysis["closedExactly"])
        self.assertEqual(analysis["intersectionTypes"], {})
        square = forensics.cutin_geometry(points, analysis)
        self.assertTrue(square.is_valid)
        self.assertAlmostEqual(square.area / (forensics.SCALE ** 2), 0.01)

        open_region = forensics.scan((fixture_dir / "invalid_open.gbr").read_text(encoding="ascii"))[0]
        self.assertFalse(forensics.analyze(open_region["contours"][0]["points"])["closedExactly"])
        crossing = forensics.scan((fixture_dir / "invalid_crossing.gbr").read_text(encoding="ascii"))[0]
        crossing_analysis = forensics.analyze(crossing["contours"][0]["points"])
        self.assertTrue(crossing_analysis["closedExactly"])
        self.assertIn("cross_or_vertex_on_edge", crossing_analysis["intersectionTypes"])
        with self.assertRaises(ValueError):
            forensics.cutin_geometry(crossing["contours"][0]["points"], crossing_analysis)

    def test_kicad_10_generated_gerber_excellon_regression(self):
        folder = ROOT / "phase2i/fixtures/kicad-interf-u"
        expected = {
            "interf_u-top_copper.gtl": ("08d6fb413751a555d4e60ca72cbe61628b4a3eb26ece8db96c430b8c8b39d713", 903, ("Copper", "L1", "Top")),
            "interf_u-bottom_copper.gbl": ("b6004d7bb091a57af4a98f136954bd876b505ef2640ab808b6f53eae0dce21ed", 862, ("Copper", "L2", "Bot")),
            "interf_u-Edge_Cuts.gm1": ("9d18a85d1c0eeade67e561159bdd46a28054b5d28947317a21a78eb0ea0f7476", 9, ("Profile", "NP")),
        }
        for name, (digest, object_count, function) in expected.items():
            path = folder / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            gerber = GerberFile.open(path)
            self.assertEqual(len(gerber.objects), object_count)
            self.assertEqual(gerber.file_attrs[".FileFunction"], function)
            self.assertTrue(gerber.objects)
        drill = ExcellonFile.open(folder / "interf_u.drl")
        self.assertEqual(len(drill.objects), 401)
        self.assertEqual(hashlib.sha256((folder / "interf_u.kicad_pcb").read_bytes()).hexdigest(),
                         "ffc26d2ec84c4a2109b2912e6d1631e23f29e9712fd76db35cc11a634c7ce8c8")
        archive = folder / "kicad-interf-u-export.zip"
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         "b54fce5bb2a98f8845c4f54702c6c5d8b425422aa7430777a3c474b19c32d18e")
        doc = load_archive(archive)
        try:
            self.assertEqual({layer.kind for layer in doc.layer_files}, {"top", "bottom", "profile", "drill"})
            self.assertEqual(len(doc.hits), 401)
            self.assertEqual(len(doc.slots), 0)
            self.assertTrue(any("Region source scan unavailable" in issue for issue in doc.issues))
            self.assertTrue(any("explicit GEOS repair" in issue for issue in doc.issues))
        finally:
            doc.close()

    def test_valentine_handled_formatting_and_separate_bottom_repairs(self):
        doc = load_archive(ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip")
        try:
            window = PcbPrepWindow()
            window._install_document(doc)
            self.assertIn("Nonconforming source", window.compliance.text())
            self.assertIn("safely handled", window.compliance.text())
            issues = [window.issues_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(window.issues_list.count())]
            handled = [x for x in issues if x.get("kind") == "handled"]
            repairs = [x for x in issues if x.get("category") == "NEEDS VERIFICATION" and "Bottom copper geometry repair" in x["title"]]
            self.assertEqual(len(handled), 1)
            self.assertEqual(len(repairs), 2)
            self.assertTrue(all("isolation cut" in x["summary"].lower() for x in repairs))
            repair_row = next(window.issues_list.item(i) for i in range(window.issues_list.count())
                              if "Bottom copper geometry repair · object 0" in window.issues_list.item(i).text())
            window.issues_list.setCurrentItem(repair_row)
            window.advanced_button.setChecked(True)
            self.assertIn("23.174808194", window.advanced_text.toPlainText())
            self.assertIn("not a V-bit/depth toolpath simulation", window.advanced_text.toPlainText())
            self.assertFalse(any(isinstance(item.data(0), dict) and
                                 item.data(0).get("label") == "Shape-preserving no-op region outline"
                                 for item in window.scene.items()))
            self.assertTrue(all(x.get("category") != "BLOCKED" for x in handled))
            self.assertIn("BLOCKED", window.eligibility.text())
            window.close()
        finally:
            doc.close()

    def test_repair_metrics_are_preserved_without_claiming_isolation_verification(self):
        audit = json.loads((ROOT / "phase2c/results/copper-repair-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["repairCount"], 2)
        expected = [-1.000444171950221e-11, 3.410605131648481e-13]
        for row, delta in zip(audit["repairs"], expected, strict=True):
            self.assertFalse(row["rawGeometryValid"])
            self.assertEqual(row["repair"], "shapely.make_valid")
            self.assertAlmostEqual(row["areaDeltaMm2"], delta, delta=1e-22)
            self.assertTrue(row["deterministicNormalizedWkbEqual"])
            self.assertIn("NOT VERIFIABLE", row["materialAndIntendedTopology"])
        self.assertTrue(audit["finalBoardComparison"]["componentCountsMatch"])
        self.assertTrue(audit["finalBoardComparison"]["interiorVoidCountsMatch"])
        self.assertFalse(audit["finalBoardComparison"].get("isolationGeometryVerified", False))
        sensitivity = json.loads((ROOT / "phase2i/results/geos-repair-sensitivity.json").read_text(encoding="utf-8"))
        self.assertEqual(sensitivity["runtime"], {"shapely": "2.2.0", "geos": "3.14.1", "bufferQuadSegments": 16})
        first, second = sensitivity["regions"]
        self.assertEqual(first["boundaryHausdorffMm"], 0.0)
        self.assertAlmostEqual(first["negativeOffsets"][0]["symmetricDifferenceMm2"], 23.174808194064948, places=9)
        self.assertEqual((first["negativeOffsets"][0]["rawComponents"], first["negativeOffsets"][0]["repairedComponents"]), (7, 6))
        self.assertEqual(second["negativeOffsets"][0]["symmetricDifferenceMm2"], 0.0)

    def test_laser_issue_categories_keep_all_regions_blocked_from_machining(self):
        doc = load_archive(ROOT / "phase2f/fixtures/laser-v2.0-export.zip")
        try:
            window = PcbPrepWindow()
            window._install_document(doc)
            rows = [window.issues_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(window.issues_list.count())]
            region_rows = [x for x in rows if x.get("kind") == "region"]
            mismatch = next(x for x in region_rows if x["region"].index == 79)
            proposals = [x for x in region_rows if x["region"].index != 79]
            self.assertEqual(len(region_rows), 182)
            self.assertEqual(mismatch["category"], "BLOCKED")
            self.assertEqual(len(proposals), 181)
            self.assertTrue(all(x["category"] == "NEEDS VERIFICATION" for x in proposals))
            self.assertTrue(all("saved fill closely matches" in x["summary"] for x in proposals))
            self.assertIn("Measured difference", window.evidence_note.text())
            self.assertIn("BLOCKED", window.eligibility.text())
            window.close()
        finally:
            doc.close()

    def test_centered_busy_overlay_lifecycle(self):
        window = PcbPrepWindow()
        window.resize(1400, 850)
        window.show()
        self.app.processEvents()
        window._loading = True
        window._position_loading_overlay()
        window.loading_overlay.show()
        self.app.processEvents()
        viewport = window.view.viewport().rect()
        overlay = window.loading_overlay.geometry()
        self.assertLess(abs((overlay.center() - viewport.center()).x()), 2)
        self.assertLess(abs((overlay.center() - viewport.center()).y()), 2)
        window._loading_stage("Parsing source manufacturing files…")
        self.assertIn("Parsing source", window.overlay_stage.text())
        self.assertTrue(window.overlay_stage.wordWrap())
        window._loading = False
        window.loading_overlay.hide()
        window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
