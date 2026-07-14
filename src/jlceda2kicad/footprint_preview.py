"""Pure parser for the KiCad footprint primitives rendered by the Qt preview."""

import math
from dataclasses import dataclass
from typing import TypeAlias

from .sexpr import ListExpr, SExprError, parse_one


class FootprintPreviewError(ValueError):
    """Raised when a footprint cannot be represented safely."""


Point = tuple[float, float]
_MAX_COORDINATE = 100_000.0


@dataclass(frozen=True, slots=True)
class PadPrimitive:
    number: str
    pad_type: str
    shape: str
    at: Point
    size: Point
    rotation: float
    layers: tuple[str, ...]
    drill: Point | None = None
    roundrect_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class LinePrimitive:
    start: Point
    end: Point
    width: float
    layer: str


@dataclass(frozen=True, slots=True)
class RectPrimitive:
    start: Point
    end: Point
    width: float
    layer: str
    filled: bool = False


@dataclass(frozen=True, slots=True)
class CirclePrimitive:
    center: Point
    end: Point
    width: float
    layer: str
    filled: bool = False


@dataclass(frozen=True, slots=True)
class ArcPrimitive:
    start: Point
    mid: Point
    end: Point
    width: float
    layer: str


@dataclass(frozen=True, slots=True)
class PolygonPrimitive:
    points: tuple[Point, ...]
    width: float
    layer: str
    filled: bool = False


Primitive: TypeAlias = (
    PadPrimitive | LinePrimitive | RectPrimitive | CirclePrimitive | ArcPrimitive | PolygonPrimitive
)


@dataclass(frozen=True, slots=True)
class FootprintPreview:
    name: str
    primitives: tuple[Primitive, ...]
    warnings: tuple[str, ...] = ()


def _child(expression: ListExpr, head: str) -> ListExpr | None:
    return next((item for item in expression.children if item.head == head), None)


def _numbers(expression: ListExpr, *, start: int = 1) -> tuple[float, ...]:
    try:
        values = tuple(float(atom.value) for atom in expression.atoms[start:])
    except ValueError as error:
        raise FootprintPreviewError(f"{expression.head} 包含非数字坐标。") from error
    if any(abs(value) > _MAX_COORDINATE for value in values):
        raise FootprintPreviewError(f"{expression.head} 坐标超出安全范围。")
    return values


def _point(expression: ListExpr, head: str) -> Point:
    child = _child(expression, head)
    if child is None:
        raise FootprintPreviewError(f"{expression.head} 缺少 {head}。")
    values = _numbers(child)
    if len(values) < 2:
        raise FootprintPreviewError(f"{head} 缺少二维坐标。")
    return values[0], values[1]


def _layer(expression: ListExpr) -> str:
    child = _child(expression, "layer")
    if child is None or len(child.atoms) < 2:
        return "F.Cu"
    return child.atoms[1].value


def _width(expression: ListExpr) -> float:
    direct = _child(expression, "width")
    if direct is not None:
        values = _numbers(direct)
        return values[0] if values else 0.0
    stroke = _child(expression, "stroke")
    nested = _child(stroke, "width") if stroke is not None else None
    if nested is not None:
        values = _numbers(nested)
        return values[0] if values else 0.0
    return 0.0


def _filled(expression: ListExpr) -> bool:
    fill = _child(expression, "fill")
    return bool(fill and len(fill.atoms) >= 2 and fill.atoms[1].value != "none")


def _parse_pad(expression: ListExpr) -> PadPrimitive:
    atoms = expression.atoms
    if len(atoms) < 4:
        raise FootprintPreviewError("pad 节点字段不完整。")
    at_node = _child(expression, "at")
    size_node = _child(expression, "size")
    if at_node is None or size_node is None:
        raise FootprintPreviewError("pad 缺少 at 或 size。")
    at_values = _numbers(at_node)
    size_values = _numbers(size_node)
    if len(at_values) < 2 or len(size_values) < 2:
        raise FootprintPreviewError("pad 的 at 或 size 字段不完整。")
    layers_node = _child(expression, "layers")
    layers = tuple(atom.value for atom in layers_node.atoms[1:]) if layers_node is not None else ()
    drill_node = _child(expression, "drill")
    drill: Point | None = None
    if drill_node is not None:
        numeric: list[float] = []
        for atom in drill_node.atoms[1:]:
            try:
                numeric.append(float(atom.value))
            except ValueError:
                continue
        if numeric:
            drill = (numeric[0], numeric[1] if len(numeric) > 1 else numeric[0])
    ratio_node = _child(expression, "roundrect_rratio")
    ratio_values = _numbers(ratio_node) if ratio_node is not None else ()
    return PadPrimitive(
        number=atoms[1].value,
        pad_type=atoms[2].value,
        shape=atoms[3].value,
        at=(at_values[0], at_values[1]),
        size=(size_values[0], size_values[1]),
        rotation=at_values[2] if len(at_values) >= 3 else 0.0,
        layers=layers,
        drill=drill,
        roundrect_ratio=ratio_values[0] if ratio_values else 0.0,
    )


def _parse_graphic(expression: ListExpr) -> Primitive:
    width = _width(expression)
    layer = _layer(expression)
    if expression.head == "fp_line":
        return LinePrimitive(_point(expression, "start"), _point(expression, "end"), width, layer)
    if expression.head == "fp_rect":
        return RectPrimitive(
            _point(expression, "start"),
            _point(expression, "end"),
            filled=_filled(expression),
            width=width,
            layer=layer,
        )
    if expression.head == "fp_circle":
        return CirclePrimitive(
            _point(expression, "center"),
            _point(expression, "end"),
            filled=_filled(expression),
            width=width,
            layer=layer,
        )
    if expression.head == "fp_arc":
        mid = _child(expression, "mid")
        if mid is None:
            center = _point(expression, "start")
            arc_start = _point(expression, "end")
            angle_node = _child(expression, "angle")
            angle_values = _numbers(angle_node) if angle_node is not None else ()
            if not angle_values:
                raise FootprintPreviewError("旧式 fp_arc 缺少 angle。")

            def rotate(angle_degrees: float) -> Point:
                radians = math.radians(angle_degrees)
                offset_x = arc_start[0] - center[0]
                offset_y = arc_start[1] - center[1]
                return (
                    center[0] + offset_x * math.cos(radians) - offset_y * math.sin(radians),
                    center[1] + offset_x * math.sin(radians) + offset_y * math.cos(radians),
                )

            angle = angle_values[0]
            return ArcPrimitive(
                arc_start,
                rotate(angle / 2.0),
                rotate(angle),
                width=width,
                layer=layer,
            )
        return ArcPrimitive(
            _point(expression, "start"),
            _point_node(mid),
            _point(expression, "end"),
            width=width,
            layer=layer,
        )
    if expression.head == "fp_poly":
        points_node = _child(expression, "pts")
        if points_node is None:
            raise FootprintPreviewError("fp_poly 缺少 pts。")
        points = tuple(_point_node(point) for point in points_node.children if point.head == "xy")
        if len(points) < 3:
            raise FootprintPreviewError("fp_poly 至少需要三个点。")
        return PolygonPrimitive(points, width, layer, filled=_filled(expression))
    raise FootprintPreviewError(f"不支持的图元：{expression.head}")


def _point_node(expression: ListExpr) -> Point:
    values = _numbers(expression)
    if len(values) < 2:
        raise FootprintPreviewError("xy 缺少二维坐标。")
    return values[0], values[1]


def parse_footprint(text: str) -> FootprintPreview:
    try:
        root = parse_one(text)
    except SExprError as error:
        raise FootprintPreviewError(f"封装 S 表达式无效：{error}") from error
    if root.head not in {"footprint", "module"}:
        raise FootprintPreviewError("预览内容不是 footprint。")
    atoms = root.atoms
    name = atoms[1].value if len(atoms) >= 2 else "未命名封装"
    if root.head == "module":
        name = name.rsplit(":", 1)[-1]
    primitives: list[Primitive] = []
    warnings: list[str] = []
    supported = {"fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"}
    for child in root.children:
        if child.head == "pad":
            primitives.append(_parse_pad(child))
        elif child.head in supported:
            primitives.append(_parse_graphic(child))
        elif child.head is not None and child.head.startswith("fp_"):
            warnings.append(f"未知封装图元 {child.head} 已跳过。")
    return FootprintPreview(name, tuple(primitives), tuple(warnings))
