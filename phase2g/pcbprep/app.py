from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .main_window import PcbPrepWindow


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DemonX PCB Prep")
    window = PcbPrepWindow()
    window.show()
    if args:
        window.request_load_archive(Path(args[0]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
