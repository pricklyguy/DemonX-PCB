"""Inspection-only inference must never become manufacturing authorization."""
import json
import os
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'phase2g'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from shapely.geometry import Polygon, box
from pcbprep.inspection_model import load_archive
from pcbprep.main_window import PcbPrepWindow
from phase2l.geometry import CanonicalGeometry, LayerMaterial, eligibility_for_simulation, plan_isolation
from phase2n.test_audit import HEADER, region


class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_inspection_opt_in_does_not_relax_manufacturing_gate(self):
        geometry = CanonicalGeometry('mm', 'source', False,
            (LayerMaterial('bottom-copper', 'bottom', 'composed', box(0,0,1,1), (), 'hypothetical'),),
            'NONCONFORMING', 'PARTIAL', 'BLOCKED')
        self.assertFalse(eligibility_for_simulation(geometry)[0])
        self.assertTrue(eligibility_for_simulation(geometry, inspection_only=True)[0])
        self.assertEqual(geometry.machining_eligibility, 'BLOCKED')
        empty = replace(geometry, layers=(replace(geometry.layers[0], geometry=Polygon()),))
        self.assertFalse(eligibility_for_simulation(empty, inspection_only=True)[0])
        invalid = replace(geometry, layers=(replace(geometry.layers[0], geometry=Polygon([(0,0),(1,1),(0,1),(1,0)])),))
        self.assertFalse(eligibility_for_simulation(invalid, inspection_only=True)[0])

    def test_surviving_chord_is_clipped_by_later_material_without_snapping(self):
        text = HEADER+region([(0,0),(200000,0),(200000,200000),(0,200000),(0,0)])
        text += region([(50000,50000),(150000,50000),(150000,150000),(50000,150000)], 'C')
        text += region([(0,0),(100000,0),(100000,100000),(0,100000),(0,0)])+'M02*'
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder)/'authored.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('authored.GBL', text)
            document = load_archive(archive)
            try:
                r = document.regions[1]
                self.assertEqual(r.source_points_mm[0], (.5,.5))
                self.assertEqual(r.source_points_mm[-1], (.5,1.5))
                self.assertEqual(r.surviving_closure.length, .5)
                self.assertEqual(r.surviving_closure.bounds, (.5,1,.5,1.5))
            finally:
                document.close()


@unittest.skipUnless(os.environ.get('DEMONX_PHASE2N_ARCHIVE'), 'Private archive path not configured')
class PrivateCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = PcbPrepWindow()
        self.window.load_archive(Path(os.environ['DEMONX_PHASE2N_ARCHIVE']))
        self.report = json.loads((ROOT/'phase2n/results/audit.json').read_text(encoding='utf-8'))
        self.assertEqual(self.window.document.archive_sha256, self.report['archiveSha256'])

    def tearDown(self):
        self.window.close()

    def test_grouped_inspector_keeps_every_source_finding_in_advanced_and_full_archive(self):
        w = self.window
        count = self.report['openContourCount']
        self.assertEqual(w.issues_list.count(), 1)
        group = w.issues_list.item(0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(group['sourceFindingCount'], count)
        self.assertEqual(sum(issue.get('kind') == 'region' for issue, _ in w._all_issue_rows), count)
        for r in w.document.regions:
            self.assertIn(r.source_sha256, group['advanced'])
            self.assertIn(f'Source lines: {r.first_line}–{r.last_line}', group['advanced'])
        w.operation_selector.setCurrentIndex(3)
        self.assertEqual(sum(w.issues_list.item(i).data(Qt.ItemDataRole.UserRole).get('kind') == 'region'
                             for i in range(w.issues_list.count())), count)

    def test_real_preview_uses_canonical_copper_preserves_source_and_blocks_output(self):
        w = self.window
        canonical = w.document.canonical_geometry
        original_hash = canonical.content_hash
        original_points = [list(r.source_points_mm) for r in w.document.regions]
        with patch('pcbprep.main_window.plan_isolation', wraps=plan_isolation) as planner:
            w.simulation_action.setChecked(True)
            self.assertIs(planner.call_args.args[0], canonical.material('bottom-copper'))
        self.assertIsNotNone(w.simulation_plan)
        self.assertGreater(w.simulation_plan.center_paths.length, 0)
        self.assertIn('Inferred/hypothetical', w.statusBar().currentMessage())
        self.assertIn('Not Approved for Machining', w.statusBar().currentMessage())
        self.assertEqual(canonical.content_hash, original_hash)
        self.assertEqual([r.source_points_mm for r in w.document.regions], original_points)
        self.assertEqual(canonical.source_conformance, 'NONCONFORMING')
        self.assertEqual(canonical.machining_eligibility, 'BLOCKED')
        self.assertIn('BLOCKED', w.eligibility.text())
        self.assertFalse(w.approved_repair_layers)
        path_items = [item for item in w.scene.items() if isinstance(item.data(0), dict) and
                      item.data(0).get('label') == 'Proposed cutter-center path · not a toolpath']
        self.assertEqual(len(path_items), 1)
        self.assertIn(path_items[0].pen().style(), (Qt.PenStyle.DashLine, Qt.PenStyle.CustomDashLine))
        w.simulation_action.setChecked(False)
        self.assertIsNone(w.simulation_plan)
        self.assertEqual(w.issues_list.count(), 1)

    def test_actual_case_highlights_omit_covered_edge_and_keep_surviving_portions(self):
        w = self.window
        w.layer_checks["inferred"].setChecked(True)
        cases = self.report['caseIndices']
        for index in cases:
            r = w.document.regions[index]
            expected = self.report['regions'][index]['straightClosureDiagnostic']['closingChordOnFinalBoundaryMm']
            self.assertAlmostEqual(r.surviving_closure.length, expected, places=9)
            labels = [item.data(0).get('label','') for item in w.scene.items() if isinstance(item.data(0), dict)]
            self.assertEqual(any(label.startswith(f'Inferred closing segment {index} ·') for label in labels), expected > 0)
        w.layer_checks["inferred"].setChecked(False)
        labels = [item.data(0).get('label','') for item in w.scene.items() if isinstance(item.data(0), dict)]
        self.assertFalse(any(label.startswith('Inferred closing segment ') or
                             label.startswith('Hypothetical closure ') for label in labels))

    def test_unknown_bottom_conversions_still_refuse_preview(self):
        w = self.window
        bottom = next(layer for layer in w.document.layer_files if layer.kind == 'bottom')
        bottom.metadata['unresolvedCount'] = 1
        w.simulation_action.setChecked(True)
        self.assertFalse(w.simulation_enabled)
        self.assertIsNone(w.simulation_plan)
        self.assertIn('refused', w.statusBar().currentMessage())


if __name__ == '__main__':
    unittest.main(verbosity=2)
