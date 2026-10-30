from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from pcbprep.inspection_model import load_archive
from pcbprep.main_window import PcbPrepWindow


class Phase2GInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_valentine_uses_disclosed_phase2e_recovery_records(self):
        archive = ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip"
        document = load_archive(archive)
        try:
            self.assertEqual(len(document.hits), 230)
            self.assertEqual(len(document.slots), 0)
            self.assertEqual(len(document.regions), 2)
            self.assertTrue(all(r.recovery_status == "RECOVERABLE" for r in document.regions))
            self.assertTrue(all(r.candidate_polygon is not None for r in document.regions))
            self.assertTrue(all(r.source_conforms_202605 is False for r in document.regions))
            self.assertIn("WARNING", document.source_compliance)
            self.assertIn("BLOCKED", document.machining_eligibility)
            window = PcbPrepWindow()
            window._install_document(document)
            self.assertIn("119 redundant draws; safely handled", window.inspect_summary.text())
            handled_row = next(window.issues_list.item(i) for i in range(window.issues_list.count())
                               if "contain redundant commands" in window.issues_list.item(i).text())
            handled_issue = handled_row.data(Qt.ItemDataRole.UserRole)
            self.assertEqual(handled_issue["severity"].split(" · ")[0], "HANDLED")
            self.assertIn("No action is needed", handled_issue["summary"])
            legacy_rows = [window.issues_list.item(i).data(Qt.ItemDataRole.UserRole)
                           for i in range(window.issues_list.count())
                           if "Legacy polygon-ring warning resolved" in window.issues_list.item(i).text()]
            comparison_rows = [window.issues_list.item(i).data(Qt.ItemDataRole.UserRole)
                               for i in range(window.issues_list.count())
                               if "Saved copper comparison needs review" in window.issues_list.item(i).text()]
            self.assertEqual(len(legacy_rows), 2)
            self.assertTrue(all(x["category"] == "HANDLED" for x in legacy_rows))
            self.assertTrue(all("isolation block remains" in x["summary"] for x in legacy_rows))
            self.assertEqual(len(comparison_rows), 2)
            self.assertTrue(all(x["category"] == "NEEDS VERIFICATION" and
                                "could affect isolation milling" in x["summary"] for x in comparison_rows))
            window.issues_list.setCurrentItem(handled_row)
            self.app.processEvents()
            self.assertFalse(any(isinstance(item.data(0), dict) and
                                "region outline" in item.data(0).get("label", "").lower()
                                for item in window.scene.items()))
            self.assertFalse(any(isinstance(item.data(0), dict) and item.data(0).get("diagnosticMarker")
                                 for item in window.scene.items()))
            window.close()
        finally:
            if document.temp_directory is not None:
                document.close()

    def test_laser_candidate_evidence_and_region79_blocking(self):
        archive = ROOT / "phase2f/fixtures/laser-v2.0-export.zip"
        document = load_archive(archive)
        try:
            self.assertEqual(len(document.hits), 183)
            self.assertEqual(len(document.slots), 8)
            self.assertEqual(len(document.regions), 182)
            proposals = [r for r in document.regions if r.native_polygon is not None and r.index != 79]
            self.assertEqual(len(proposals), 181)
            outlier = document.regions[79]
            self.assertEqual(outlier.native_path_index, 3)
            self.assertAlmostEqual(outlier.boundary_hausdorff_mm, 0.2841233245858055, places=10)
            self.assertAlmostEqual(outlier.symmetric_difference_mm2, 3.5401711304220287, places=9)
            self.assertEqual(outlier.recovery_status, "BLOCKED")
            self.assertIn("NONCONFORMING", document.source_compliance)
            self.assertIn("BLOCKED", document.machining_eligibility)
        finally:
            document.close()

    def test_window_smoke_selection_layer_toggle_and_render(self):
        window = PcbPrepWindow()
        window.resize(1500, 900)
        window.show()
        started = __import__("time").monotonic()
        window.request_load_archive(ROOT / "phase2f/fixtures/laser-v2.0-export.zip")
        self.assertLess(__import__("time").monotonic() - started, .5)
        loop = QEventLoop()
        window._load_thread.finished.connect(loop.quit)
        QTimer.singleShot(90000, loop.quit)
        loop.exec()
        self.assertIsNotNone(window.document)
        self.app.processEvents()
        self.assertEqual(window.selected_region.index, 79)
        self.assertIn("BLOCKED", window.eligibility.text())
        self.assertIn("0.284 mm", window.inspect_summary.text())
        self.assertGreater(len(window.scene.items()), 0)

        # The selected region 79 overlay has both the localized difference and
        # screen-sized warning markers; disabling diagnostics removes both.
        metadata = [item.data(0) for item in window.scene.items()]
        self.assertTrue(any(isinstance(m, dict) and m.get("label", "").startswith("Gerber/native symmetric") for m in metadata))
        self.assertGreaterEqual(sum(isinstance(m, dict) and m.get("diagnosticMarker", False) for m in metadata), 2)
        window.layer_checks["diagnostics"].setChecked(False)
        self.app.processEvents()
        self.assertFalse(any(isinstance(item.data(0), dict) and item.data(0).get("diagnosticMarker") for item in window.scene.items()))
        window.layer_checks["diagnostics"].setChecked(True)
        warning_marker = next(item for item in window.scene.items()
                              if isinstance(item.data(0), dict) and item.data(0).get("diagnosticMarker"))
        marker_pos = window.view.mapFromScene(warning_marker.pos())
        QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, marker_pos)
        self.app.processEvents()
        self.assertIn(warning_marker, window.scene.selectedItems())
        self.assertFalse(window.view._panning)

        # Cursor-anchored wheel zoom leaves the same world coordinate under the pointer.
        window.fit_board(); self.app.processEvents()
        view = window.view
        cursor = QPoint(view.viewport().width() // 3, view.viewport().height() // 3)
        before = view.mapToScene(cursor)
        class WheelEvent:
            def position(self): return QPointF(cursor)
            def angleDelta(self): return QPoint(0, 120)
            def accept(self): self.accepted = True
        wheel = WheelEvent()
        view.wheelEvent(wheel)
        after = view.mapToScene(cursor)
        self.assertLess((after - before).manhattanLength(), .05)
        click_pos = QPointF(700, 500)
        view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, click_pos, click_pos, click_pos,
                                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier))
        self.assertFalse(view._panning)
        view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, click_pos, click_pos, click_pos,
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier))

        # Middle drag and Space+left drag pan; ordinary left click remains available to select.
        def drag(button, buttons, start, end):
            press_pos = QPointF(start)
            press = QMouseEvent(QEvent.Type.MouseButtonPress, press_pos, press_pos, press_pos,
                                button, buttons, Qt.KeyboardModifier.NoModifier)
            view.mousePressEvent(press)
            move_pos = QPointF(end)
            move = QMouseEvent(QEvent.Type.MouseMove, move_pos, move_pos, move_pos,
                               Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
            view.mouseMoveEvent(move)
            release = QMouseEvent(QEvent.Type.MouseButtonRelease, move_pos, move_pos, move_pos,
                                  button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            view.mouseReleaseEvent(release)
        center0 = view.mapToScene(view.viewport().rect().center())
        drag(Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton, QPoint(300, 300), QPoint(350, 335))
        center1 = view.mapToScene(view.viewport().rect().center())
        self.assertGreater((center1-center0).manhattanLength(), .5)
        with patch("pcbprep.view.QCursor.pos", return_value=view.viewport().mapToGlobal(QPoint(500, 420))):
            self.app.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                                  Qt.KeyboardModifier.NoModifier))
            self.assertTrue(view._space_down)
        view.reset_to_board(); self.app.processEvents()
        center2 = view.mapToScene(view.viewport().rect().center())
        drag(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, QPoint(500, 420), QPoint(545, 455))
        center3 = view.mapToScene(view.viewport().rect().center())
        self.assertGreater((center3-center2).manhattanLength(), .5)
        self.app.sendEvent(window, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space,
                                              Qt.KeyboardModifier.NoModifier))
        self.assertFalse(view._space_down)

        # Layer toggles preserve center and scale; selecting the mismatch zooms to its maximum pair.
        before_center = view.mapToScene(view.viewport().rect().center())
        before_scale = view.transform().m11()
        window.layer_checks["native"].setChecked(True)
        self.app.processEvents()
        after_center = view.mapToScene(view.viewport().rect().center())
        self.assertAlmostEqual(view.transform().m11(), before_scale, places=8)
        self.assertLess((after_center-before_center).manhattanLength(), .5)  # scrollbar quantization, under a few screen pixels
        self.assertGreater(len(window.scene.items()), 0)
        self.assertTrue(window.grab().isNull() is False)
        issue_item = next(window.issues_list.item(i) for i in range(window.issues_list.count())
                          if "boundary differs" in window.issues_list.item(i).text().lower())
        window._issue_double_clicked(issue_item)
        focused = view.mapToScene(view.viewport().rect().center())
        point = window.selected_region.discrepancy_point_mm
        self.assertLess(abs(focused.x()-point[0]) + abs(-focused.y()-point[1]), .15)
        self.assertGreater(view.transform().m11(), before_scale)

        # F and Home both return to the complete board view.
        view.keyPressEvent(type("Key", (), {"key": lambda self: Qt.Key.Key_F, "accept": lambda self: None})())
        fit_scale = view.transform().m11()
        view.wheelEvent(type("Wheel", (), {"position": lambda self: QPointF(cursor),
                                           "angleDelta": lambda self: QPoint(0, 120),
                                           "accept": lambda self: None})())
        view.keyPressEvent(type("Key", (), {"key": lambda self: Qt.Key.Key_Home, "accept": lambda self: None})())
        self.assertAlmostEqual(view.transform().m11(), fit_scale, delta=.01)
        window.close()
        self.app.processEvents()

    def test_loading_animation_stage_and_error_lifecycle(self):
        window = PcbPrepWindow()
        window.show()
        window.request_load_archive(ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip")
        self.assertTrue(window._loading_timer.isActive())
        self.assertFalse(window.open_action.isEnabled())
        self.assertTrue(QApplication.overrideCursor() is not None)
        window._loading_stage("Parsing manufacturing file 1 of 13: Gerber_TopLayer.GTL")
        self.assertIn("Parsing manufacturing file", window.overlay_stage.text())
        first_spinner = window.overlay_spinner.text()
        tick = QEventLoop()
        QTimer.singleShot(350, tick.quit)
        tick.exec()
        self.assertNotEqual(first_spinner, window.overlay_spinner.text())
        loop = QEventLoop()
        window._load_thread.finished.connect(loop.quit)
        QTimer.singleShot(90000, loop.quit)
        loop.exec()
        self.assertIsNotNone(window.document)
        self.assertFalse(window._loading_timer.isActive())
        self.assertTrue(window.open_action.isEnabled())
        self.assertIn("Ready", window.loading_label.text())
        self.assertIsNone(QApplication.overrideCursor())
        window.close()

        failed = PcbPrepWindow()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Ok):
            failed.request_load_archive(ROOT / "phase2g/missing-input.zip")
            loop = QEventLoop()
            failed._load_thread.finished.connect(loop.quit)
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
        self.assertIsNone(failed.document)
        self.assertIn("failed", failed.loading_label.text().lower())
        self.assertTrue(failed.open_action.isEnabled())
        failed.close()

    def test_zip_traversal_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            malicious = folder / "unsafe.zip"
            with zipfile.ZipFile(malicious, "w") as archive:
                archive.writestr("../escape.gbr", "%FSLAX45Y45*%\n%MOMM*%\n")
            with self.assertRaises(ValueError):
                load_archive(malicious)
            self.assertFalse((folder.parent / "escape.gbr").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
