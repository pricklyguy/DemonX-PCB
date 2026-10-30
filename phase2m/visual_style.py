"""Shared visual rules for diagnostic geometry; safe to reuse across DemonX UIs."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPen
from PySide6.QtCore import Qt


COPPER_BLUE = "#60a5fa"
TOOLPATH_AMBER = "#ffd166"
FOOTPRINT_AMBER = "#ffb74d"
COLLISION_RED = "#ff4b5c"
UNCERTAINTY_VIOLET = "#bc8cff"
SELECTED_TEAL = "#38d6c3"


def proposed_toolpath_pen(*, selected: bool = False) -> QPen:
    pen = QPen(QColor(TOOLPATH_AMBER), 1.0, Qt.PenStyle.CustomDashLine)
    pen.setCosmetic(True)
    pen.setDashPattern([5.0, 3.0])  # cosmetic 1 px pen: stable 5 px dash / 3 px gap
    if selected:
        pen.setColor(QColor("#fff3a6"))
        pen.setWidthF(2.0)
    return pen


def selected_toolpath_halo_pen() -> QPen:
    pen = QPen(QColor(SELECTED_TEAL), 4.0, Qt.PenStyle.SolidLine)
    pen.setCosmetic(True)
    return pen


def repair_proposal_pen(*, selected: bool = False) -> QPen:
    pen = QPen(QColor(UNCERTAINTY_VIOLET if not selected else "#f1c5ff"),
               1.0 if not selected else 2.0, Qt.PenStyle.DashDotLine)
    pen.setCosmetic(True)
    return pen
