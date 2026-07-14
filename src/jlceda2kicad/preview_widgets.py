"""Qt widgets for symbol, footprint, and software-rendered WRL previews."""

import math
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItemGroup,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from .footprint_preview import (
    ArcPrimitive,
    CirclePrimitive,
    FootprintPreview,
    LinePrimitive,
    PadPrimitive,
    PolygonPrimitive,
    RectPrimitive,
    parse_footprint,
)
from .wrl_preview import WrlMesh, parse_wrl, project_vertices


class SymbolPreviewWidget(QGraphicsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.source_path: Path | None = None

    def load_svg(self, path: Path) -> None:
        item = QGraphicsSvgItem(str(path))
        if not item.renderer().isValid():
            raise ValueError(f"无法加载符号 SVG：{path}")
        scene = self.scene()
        scene.clear()
        scene.addItem(item)
        scene.setSceneRect(item.boundingRect())
        self.source_path = path
        self._fit()

    def _fit(self) -> None:
        scene = self.scene()
        if scene.items():
            self.fitInView(scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()


_MM = 20.0
_LAYER_COLORS = {
    "F.Cu": QColor("#c95f5f"),
    "B.Cu": QColor("#4d79cc"),
    "F.SilkS": QColor("#f2f2f2"),
    "B.SilkS": QColor("#b5b5b5"),
    "F.Fab": QColor("#ba87d4"),
    "B.Fab": QColor("#7d5b91"),
    "F.CrtYd": QColor("#d66bc3"),
    "B.CrtYd": QColor("#8f4783"),
}


def _point(point: tuple[float, float]) -> QPointF:
    return QPointF(point[0] * _MM, point[1] * _MM)


def _pen(layer: str, width: float) -> QPen:
    pen = QPen(_LAYER_COLORS.get(layer, QColor("#d5b85a")))
    pen.setWidthF(max(1.0, width * _MM))
    pen.setCosmetic(True)
    return pen


class FootprintPreviewWidget(QGraphicsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.preview: FootprintPreview | None = None
        self.warnings: tuple[str, ...] = ()

    def load_file(self, path: Path) -> None:
        self.load_text(path.read_text(encoding="utf-8"))

    def load_text(self, text: str) -> None:
        self.preview = parse_footprint(text)
        self.warnings = self.preview.warnings
        scene = self.scene()
        scene.clear()
        for primitive in self.preview.primitives:
            self._draw(primitive)
        if scene.items():
            margin = 20.0
            scene.setSceneRect(scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _draw(self, primitive: object) -> None:
        scene = self.scene()
        if isinstance(primitive, PadPrimitive):
            self._draw_pad(primitive)
        elif isinstance(primitive, LinePrimitive):
            scene.addLine(
                primitive.start[0] * _MM,
                primitive.start[1] * _MM,
                primitive.end[0] * _MM,
                primitive.end[1] * _MM,
                _pen(primitive.layer, primitive.width),
            )
        elif isinstance(primitive, RectPrimitive):
            start, end = _point(primitive.start), _point(primitive.end)
            rectangle = QRectF(start, end).normalized()
            brush = QBrush(_LAYER_COLORS.get(primitive.layer)) if primitive.filled else QBrush()
            scene.addRect(rectangle, _pen(primitive.layer, primitive.width), brush)
        elif isinstance(primitive, CirclePrimitive):
            center, end = _point(primitive.center), _point(primitive.end)
            radius = math.hypot(end.x() - center.x(), end.y() - center.y())
            rectangle = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            brush = QBrush(_LAYER_COLORS.get(primitive.layer)) if primitive.filled else QBrush()
            scene.addEllipse(rectangle, _pen(primitive.layer, primitive.width), brush)
        elif isinstance(primitive, ArcPrimitive):
            path = QPainterPath(_point(primitive.start))
            path.quadTo(_point(primitive.mid), _point(primitive.end))
            scene.addPath(path, _pen(primitive.layer, primitive.width))
        elif isinstance(primitive, PolygonPrimitive):
            polygon = QPolygonF([_point(point) for point in primitive.points])
            brush = QBrush(_LAYER_COLORS.get(primitive.layer)) if primitive.filled else QBrush()
            scene.addPolygon(polygon, _pen(primitive.layer, primitive.width), brush)

    def _draw_pad(self, pad: PadPrimitive) -> None:
        group = QGraphicsItemGroup()
        width, height = pad.size[0] * _MM, pad.size[1] * _MM
        rectangle = QRectF(-width / 2, -height / 2, width, height)
        color = QColor("#d9a52a") if pad.number == "1" else QColor("#bd8240")
        outline = QPen(color.lighter(150))
        brush = QBrush(color)
        shape_item: QGraphicsRectItem | QGraphicsEllipseItem | QGraphicsPathItem
        if pad.shape in {"circle", "oval"}:
            shape_item = QGraphicsEllipseItem(rectangle)
            shape_item.setPen(outline)
            shape_item.setBrush(brush)
        elif pad.shape == "roundrect":
            radius = min(width, height) * pad.roundrect_ratio
            path = QPainterPath()
            path.addRoundedRect(rectangle, radius, radius)
            shape_item = QGraphicsPathItem(path)
            shape_item.setPen(outline)
            shape_item.setBrush(brush)
        else:
            shape_item = QGraphicsRectItem(rectangle)
            shape_item.setPen(outline)
            shape_item.setBrush(brush)
        group.addToGroup(shape_item)
        if pad.drill is not None:
            drill_width, drill_height = pad.drill[0] * _MM, pad.drill[1] * _MM
            drill = QGraphicsEllipseItem(
                -drill_width / 2, -drill_height / 2, drill_width, drill_height
            )
            drill.setPen(QPen(Qt.PenStyle.NoPen))
            drill.setBrush(QColor("#20242b"))
            group.addToGroup(drill)
        if pad.number:
            label = QGraphicsSimpleTextItem(pad.number)
            label.setBrush(QColor("#16191f"))
            bounds = label.boundingRect()
            label.setPos(-bounds.width() / 2, -bounds.height() / 2)
            group.addToGroup(label)
        group.setPos(pad.at[0] * _MM, pad.at[1] * _MM)
        group.setRotation(pad.rotation)
        self.scene().addItem(group)


class WrlPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 180)
        self.mesh: WrlMesh | None = None
        self.yaw_degrees = 45.0
        self.pitch_degrees = 35.264
        self.zoom = 1.0
        self.pan = QPointF()
        self._last_mouse: QPoint | None = None
        self._panning = False

    def load_file(self, path: Path) -> None:
        self.load_text(path.read_text(encoding="utf-8", errors="replace"))

    def load_text(self, text: str) -> None:
        self.mesh = parse_wrl(text)
        self.zoom = 1.0
        self.pan = QPointF()
        self.update()

    def set_named_view(self, name: str) -> None:
        views = {
            "top": (0.0, 90.0),
            "front": (0.0, 0.0),
            "isometric": (45.0, 35.264),
        }
        if name not in views:
            raise ValueError(f"未知视图：{name}")
        self.yaw_degrees, self.pitch_degrees = views[name]
        self.update()

    def adjust_zoom(self, angle_delta_y: int) -> None:
        factor = 1.15 if angle_delta_y > 0 else 1 / 1.15
        self.zoom = min(20.0, max(0.05, self.zoom * factor))
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.adjust_zoom(event.angleDelta().y())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse = event.position().toPoint()
        self._panning = event.button() in {
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        }
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        current = event.position().toPoint()
        if self._last_mouse is None:
            self._last_mouse = current
            return
        delta = current - self._last_mouse
        if self._panning:
            self.pan += QPointF(delta)
        else:
            self.yaw_degrees += delta.x() * 0.7
            self.pitch_degrees = min(90.0, max(-90.0, self.pitch_degrees + delta.y() * 0.7))
        self._last_mouse = current
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._last_mouse = None
        self._panning = False
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1f232b"))
        if self.mesh is None:
            painter.setPen(QColor("#aeb5c0"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无 WRL 模型")
            return
        vertices = self.mesh.vertices
        spans = [max(values) - min(values) for values in zip(*vertices, strict=True)]
        extent = max(max(spans), 1e-6)
        scale = min(self.width(), self.height()) * 0.68 / extent * self.zoom
        center = tuple(sum(values) / len(vertices) for values in zip(*vertices, strict=True))
        centered = tuple((x - center[0], y - center[1], z - center[2]) for x, y, z in vertices)
        projected = project_vertices(
            centered,
            yaw_degrees=self.yaw_degrees,
            pitch_degrees=self.pitch_degrees,
            scale=scale,
            pan=(self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y()),
        )
        faces = sorted(
            self.mesh.faces,
            key=lambda face: sum(projected[index][2] for index in face) / 3,
        )
        base = QColor.fromRgbF(*self.mesh.color)
        for order, face in enumerate(faces):
            polygon = QPolygonF(
                [QPointF(projected[index][0], projected[index][1]) for index in face]
            )
            shade = 85 + int(35 * order / max(1, len(faces) - 1))
            painter.setBrush(base.lighter(shade))
            painter.setPen(QPen(base.lighter(145), 0.8))
            painter.drawPolygon(polygon)
