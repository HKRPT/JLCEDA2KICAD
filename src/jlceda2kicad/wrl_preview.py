"""Small VRML 2.0 mesh reader and orthographic projection helpers."""

import math
import re
from dataclasses import dataclass


class WrlPreviewError(ValueError):
    """Raised when a WRL file has no safely renderable indexed geometry."""


Vertex = tuple[float, float, float]
Face = tuple[int, int, int]
Color = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class WrlMesh:
    vertices: tuple[Vertex, ...]
    faces: tuple[Face, ...]
    color: Color = (0.55, 0.65, 0.75)


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _float_values(text: str) -> tuple[float, ...]:
    return tuple(float(value) for value in re.findall(_NUMBER, text))


def _index_values(text: str) -> tuple[int, ...]:
    return tuple(int(value) for value in re.findall(r"-?\d+", text))


def parse_wrl(text: str) -> WrlMesh:
    points_match = re.search(r"\bpoint\s*\[([^\]]*)\]", text, re.IGNORECASE | re.DOTALL)
    if points_match is None:
        raise WrlPreviewError("WRL 中没有顶点数组。")
    values = _float_values(points_match.group(1))
    if not values or len(values) % 3:
        raise WrlPreviewError("WRL 顶点数组不完整。")
    vertices = tuple(
        (values[index], values[index + 1], values[index + 2]) for index in range(0, len(values), 3)
    )

    indices_match = re.search(r"\bcoordIndex\s*\[([^\]]*)\]", text, re.IGNORECASE | re.DOTALL)
    if indices_match is None:
        raise WrlPreviewError("WRL 中没有面索引。")
    polygons: list[list[int]] = [[]]
    for index in _index_values(indices_match.group(1)):
        if index == -1:
            if polygons[-1]:
                polygons.append([])
            continue
        if index < 0 or index >= len(vertices):
            raise WrlPreviewError(f"WRL 面索引 {index} 超出顶点范围。")
        polygons[-1].append(index)
    polygons = [polygon for polygon in polygons if len(polygon) >= 3]
    if not polygons:
        raise WrlPreviewError("WRL 中没有有效面索引。")
    faces = tuple(
        (polygon[0], polygon[offset], polygon[offset + 1])
        for polygon in polygons
        for offset in range(1, len(polygon) - 1)
    )

    color_match = re.search(
        rf"\bdiffuseColor\s+({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})",
        text,
        re.IGNORECASE,
    )
    color: Color = (0.55, 0.65, 0.75)
    if color_match:
        color = tuple(min(1.0, max(0.0, float(value))) for value in color_match.groups())  # type: ignore[assignment]
    return WrlMesh(vertices, faces, color)


def project_vertices(
    vertices: tuple[Vertex, ...],
    *,
    yaw_degrees: float,
    pitch_degrees: float,
    scale: float,
    pan: tuple[float, float],
) -> tuple[Vertex, ...]:
    yaw = math.radians(yaw_degrees)
    pitch = math.radians(pitch_degrees)
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
    projected: list[Vertex] = []
    for x, y, z in vertices:
        yaw_x = x * cos_yaw + z * sin_yaw
        yaw_z = -x * sin_yaw + z * cos_yaw
        pitch_y = y * cos_pitch - yaw_z * sin_pitch
        depth = y * sin_pitch + yaw_z * cos_pitch
        projected.append((yaw_x * scale + pan[0], -pitch_y * scale + pan[1], depth))
    return tuple(projected)
