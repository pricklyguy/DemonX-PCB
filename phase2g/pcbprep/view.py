from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsView,
)


def geometry_path(geometry: Any) -> QPainterPath:
    """Convert an already-derived Shapely geometry to display coordinates (Y up)."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    if geometry is None or geometry.is_empty:
        return path
    typ = geometry.geom_type
    if typ == "Polygon":
        for ring in [geometry.exterior, *geometry.interiors]:
            coords = list(ring.coords)
            if not coords:
                continue
            path.moveTo(QPointF(coords[0][0], -coords[0][1]))
            for x, y in coords[1:]:
                path.lineTo(QPointF(x, -y))
            path.closeSubpath()
    elif typ in {"MultiPolygon", "GeometryCollection"}:
        for child in geometry.geoms:
            path.addPath(geometry_path(child))
    elif typ in {"LineString", "LinearRing"}:
        coords = list(geometry.coords)
        if coords:
            path.moveTo(QPointF(coords[0][0], -coords[0][1]))
            for x, y in coords[1:]:
                path.lineTo(QPointF(x, -y))
    elif typ == "MultiLineString":
        for child in geometry.geoms:
            path.addPath(geometry_path(child))
    elif typ == "Point":
        path.addEllipse(QPointF(geometry.x, -geometry.y), 0.05, 0.05)
    return path


class FeaturePathItem(QGraphicsPathItem):
    def __init__(self, path: QPainterPath, metadata: dict, pen, brush=None):
        super().__init__(path)
        if pen is not None:
            pen.setCosmetic(True)
            self.setPen(pen)
        if brush is not None:
            self.setBrush(brush)
        self.setData(0, metadata)
        self.setToolTip(metadata.get("label", "PCB feature"))
        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(metadata.get("z", 0))


class WarningMarker(QGraphicsEllipseItem):
    """A fixed-pixel warning marker anchored to an exact world coordinate."""
    def __init__(self, x: float, y: float, label: str):
        super().__init__(-7, -7, 14, 14)
        self.setPos(x, -y)
        self.setBrush(QColor("#ff5d67"))
        from PySide6.QtGui import QPen
        pen = QPen(QColor("#fff3f4"), 1.8)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setData(0, {"label": label, "worldXmm": x, "worldYmm": y, "diagnosticMarker": True})
        self.setZValue(1000)


class BoardView(QGraphicsView):
    coordinatesChanged = Signal(float, float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#0b1118"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumSize(360, 300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._space_down = False
        self._panning = False
        self._last_pan_position = QPoint()
        self._board_bounds: tuple[float, float, float, float] | None = None
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched, event):
        # Space is a temporary CAD pan modifier even when the view did not
        # own keyboard focus before the pointer moved over it.
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() == Qt.Key.Key_Space:
            local = self.viewport().mapFromGlobal(QCursor.pos())
            if event.type() == QEvent.Type.KeyRelease:
                self._space_down = False
            elif self.viewport().rect().contains(local):
                self._space_down = True
            return False
        return super().eventFilter(watched, event)

    def set_board_bounds(self, bounds):
        self._board_bounds = bounds

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        cursor = event.position().toPoint()
        before = self.mapToScene(cursor)
        factor = 1.2 ** (delta / 120.0)
        current_scale = self.transform().m11()
        target_scale = max(0.03, min(250.0, current_scale * factor))
        factor = target_scale / current_scale
        self.scale(factor, factor)
        after = self.mapToScene(cursor)
        # Move the view transform by the scene-coordinate delta so the same PCB
        # coordinate remains under the pointer after scale changes.
        shift = after - before
        self.translate(shift.x(), shift.y())
        event.accept()

    def mousePressEvent(self, event):
        pan_gesture = (event.button() == Qt.MouseButton.MiddleButton or
                       (event.button() == Qt.MouseButton.LeftButton and self._space_down))
        if pan_gesture:
            self._panning = True
            self._last_pan_position = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        self.coordinatesChanged.emit(point.x(), -point.y())
        if self._panning:
            current = event.position().toPoint()
            delta = current - self._last_pan_position
            self._last_pan_position = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_down = True
            event.accept()
            return
        if event.key() == Qt.Key.Key_F:
            self.fit_board(self._board_bounds)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Home:
            self.reset_to_board()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_down = False
            event.accept()
            return
        super().keyReleaseEvent(event)

    def fit_board(self, bounds):
        self._board_bounds = bounds
        if not bounds:
            return
        minx, miny, maxx, maxy = bounds
        margin = max(maxx - minx, maxy - miny) * 0.07 or 1.0
        self.fitInView(QRectF(minx - margin, -maxy - margin,
                              maxx - minx + 2 * margin, maxy - miny + 2 * margin),
                       Qt.AspectRatioMode.KeepAspectRatio)

    def reset_to_board(self):
        if self._board_bounds:
            self.resetTransform()
            self.fit_board(self._board_bounds)
            minx, miny, maxx, maxy = self._board_bounds
            self.centerOn((minx + maxx) / 2, -(miny + maxy) / 2)

    def zoom_to_bounds(self, bounds, padding_ratio: float = 0.15, min_extent: float = 0.4):
        if not bounds:
            return
        minx, miny, maxx, maxy = bounds
        width, height = max(maxx - minx, min_extent), max(maxy - miny, min_extent)
        margin = max(width, height) * padding_ratio
        self.fitInView(QRectF(minx - margin, -maxy - margin,
                              width + 2 * margin, height + 2 * margin),
                       Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_to(self, points: list[tuple[float, float]]):
        if not points:
            return
        xs, ys = zip(*points)
        self.zoom_to_bounds((min(xs), min(ys), max(xs), max(ys)))

    def zoom_to_point(self, point: tuple[float, float], radius_mm: float = 1.5):
        x, y = point
        self.zoom_to_bounds((x - radius_mm, y - radius_mm, x + radius_mm, y + radius_mm), 0.10)
