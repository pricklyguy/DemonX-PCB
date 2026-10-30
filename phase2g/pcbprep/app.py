from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from .main_window import PcbPrepWindow


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    smoke_test_startup = args == ["--smoke-test-startup"]
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DemonX PCB Prep")
    window = PcbPrepWindow()
    window.show()
    if smoke_test_startup:
        app.processEvents()
        if not window.isVisible():
            return 2
        print("PCB_PREP_STARTUP_OK", flush=True)
        QTimer.singleShot(250, app.quit)
        return app.exec()
    if args:
        window.request_load_archive(Path(args[0]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
