from __future__ import annotations

import os
import sys
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2g"))
sys.path.insert(0, str(ROOT / "phase2l"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from pcbprep.main_window import PcbPrepWindow
from pcbprep.inspection_model import load_archive
from jsonschema import Draft202012Validator


class Phase2LPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unresolved_document_simulation_is_refused(self):
        window = PcbPrepWindow()
        window.simulation_action.setChecked(True)
        self.app.processEvents()
        self.assertFalse(window.simulation_action.isChecked())
        self.assertIsNone(window.simulation_plan)
        self.assertIn("refused", window.statusBar().currentMessage().lower())
        window.close()

    def test_inspection_and_simulation_consume_the_same_canonical_material(self):
        window = PcbPrepWindow()
        window.show_synthetic_demo()
        original = window.demo_canonical.material("top-copper")
        self.assertIs(window.demo_geometry, original)
        window.simulation_action.setChecked(True)
        self.app.processEvents()
        self.assertIsNotNone(window.simulation_plan)
        labels = [item.data(0).get("label", "") for item in window.scene.items()
                  if isinstance(item.data(0), dict)]
        self.assertTrue(any("Synthetic original copper" in label for label in labels))
        self.assertTrue(any("Simulated cutting footprint" in label for label in labels))
        self.assertTrue(any("Proposed cutter-center path" in label for label in labels))
        self.assertIn("Not Approved for Machining", window.statusBar().currentMessage())
        old_width = window.simulation_plan.effective_width_mm
        window.depth_input.setValue(.250)
        self.app.processEvents()
        self.assertGreater(window.simulation_plan.effective_width_mm, old_width)
        window.close()

    def test_real_sample_archives_keep_all_phase2k_blocks(self):
        schema = json.loads((ROOT / "phase2l" / "schema" / "canonical-pcb-geometry-1.1.schema.json").read_text(encoding="utf-8"))
        for name, expected_regions in (("Gerber_PCB_Valentine_Feb_New.zip", 2),
                                       ("Gerber_Prickly-Laser-Module-2.5.zip", 182)):
            archive = ROOT / "gerbers" / name
            if not archive.is_file():
                self.skipTest(f"Private sample archive not provisioned: {name}")
            document = load_archive(archive)
            try:
                self.assertEqual(len(document.regions), expected_regions)
                self.assertEqual(document.machining_eligibility.split(" —", 1)[0], "BLOCKED")
                self.assertEqual(document.canonical_geometry.machining_eligibility, "BLOCKED")
                self.assertTrue(document.canonical_geometry.content_hash.startswith("sha256:"))
                self.assertIs(document.canonical_geometry.material("bottom-copper"), document.bottom_geometry)
                payload = document.canonical_geometry.to_dict()
                payload["contentHash"] = document.canonical_geometry.content_hash
                self.assertEqual(list(Draft202012Validator(schema).iter_errors(payload)), [])
                if "Laser" in name:
                    self.assertEqual(sum(region.recovery_status == "PROPOSED_ONLY"
                                         for region in document.regions), 181)
                    self.assertEqual(document.regions[79].recovery_status, "BLOCKED")
                    self.assertAlmostEqual(document.regions[79].boundary_hausdorff_mm,
                                           .284123324586, places=9)
                else:
                    self.assertEqual([region.recovery_status for region in document.regions],
                                     ["RECOVERABLE", "RECOVERABLE"])
            finally:
                document.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
