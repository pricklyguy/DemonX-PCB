from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase2g"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from pcbprep.main_window import PcbPrepWindow  # noqa: E402


def main():
    output = ROOT / "phase2i/results/screenshots"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = PcbPrepWindow()
    window.resize(1700, 1000)
    window.show()
    for archive, title, issue_match, filename in (
        (ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip", "Valentine", "contain redundant commands", "valentine-handled.png"),
        (ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip", "Valentine", "Bottom copper geometry repair · object 0", "valentine-geos-repair.png"),
        (ROOT / "gerbers/Gerber_PCB_Valentine_Feb_New.zip", "Valentine", "Bottom copper geometry repair · object 0", "valentine-geos-offset-sensitivity.png"),
        (ROOT / "phase2f/fixtures/laser-v2.0-export.zip", "Laser Module", "182 copper regions have open boundaries", "laser-full-board.png"),
        (ROOT / "phase2f/fixtures/laser-v2.0-export.zip", "Laser Module", "Copper boundary differs from the saved design", "laser-region-79-blocked.png"),
    ):
        window.load_archive(archive)
        window.setWindowTitle(f"DemonX PCB Prep — {title}")
        app.processEvents()
        for index in range(window.issues_list.count()):
            item = window.issues_list.item(index)
            if issue_match.casefold() in item.text().casefold():
                window.issues_list.setCurrentItem(item)
                break
        window.fit_board()
        if filename.startswith("valentine-geos-"):
            window.advanced_button.setChecked(True)
        app.processEvents()
        if filename == "valentine-geos-offset-sensitivity.png":
            cursor = window.advanced_text.document().find("23.174808194")
            if not cursor.isNull():
                window.advanced_text.setTextCursor(cursor)
                window.advanced_text.ensureCursorVisible()
        if "region-79" in filename:
            window.zoom_to_issue()
            window.advanced_button.setChecked(True)
        app.processEvents()
        if not window.grab().save(str(output / filename)):
            raise RuntimeError(f"Screenshot could not be saved: {filename}")
    window.close()
    app.processEvents()
    print(output)


if __name__ == "__main__":
    main()
