from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication
from pcbprep.main_window import PcbPrepWindow


def main():
    output = ROOT / "phase2g/results/screenshots"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = PcbPrepWindow()
    window.resize(1700, 1000)
    fixtures = [
        (ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip", "valentine-inspection.png"),
        (ROOT / "phase2f/fixtures/laser-v2.0-export.zip", "laser-module-full-board.png"),
    ]
    for archive, filename in fixtures:
        window.load_archive(archive)
        window.show()
        app.processEvents()
        window.fit_board()
        app.processEvents()
        if not window.grab().save(str(output / filename)):
            raise RuntimeError(f"Failed to save screenshot {filename}")
    window.select_region(79, zoom=True)
    app.processEvents()
    if not window.grab().save(str(output / "laser-region-079-inspection.png")):
        raise RuntimeError("Failed to save region 79 screenshot")
    window.close()
    app.processEvents()
    print(f"Saved UI captures to {output}")


if __name__ == "__main__":
    main()
