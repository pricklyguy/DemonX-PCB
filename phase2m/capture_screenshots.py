"""Capture deterministic synthetic-only Phase 2M UI evidence."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2g"))
sys.path.insert(0, str(ROOT / "phase2l"))
sys.path.insert(0, str(ROOT / "phase2m"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from pcbprep.main_window import PcbPrepWindow


def capture(window: PcbPrepWindow, path: Path):
    window.resize(1720, 1040)
    window.show()
    QApplication.processEvents()
    if window.current_issue is not None:
        window.zoom_to_issue()
        QApplication.processEvents()
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"SCREENSHOT_SAVE_FAILED: {path}")
    window.close()
    QApplication.processEvents()


def main():
    destination = ROOT / "phase2m" / "screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    connected = PcbPrepWindow()
    connected.show_connected_pad_demo()
    connected.set_simulation_enabled(True)
    capture(connected, destination / "connected-pad-isolation.png")

    operations = PcbPrepWindow()
    operations.show_synthetic_demo()
    operations.operation_selector.setCurrentIndex(3)
    QApplication.processEvents()
    capture(operations, destination / "operation-specific-validation.png")

    repair = PcbPrepWindow()
    repair.show_synthetic_repair_example()
    QApplication.processEvents()
    capture(repair, destination / "repair-proposal-manual-review.png")

    print(f"Synthetic-only screenshots saved under {destination}")


if __name__ == "__main__":
    main()
