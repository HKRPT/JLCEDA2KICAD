import math

import pytest

from jlceda2kicad.wrl_preview import (
    WrlPreviewError,
    parse_wrl,
    project_vertices,
)

WRL = """#VRML V2.0 utf8
Shape {
  appearance Appearance { material Material { diffuseColor 0.2 0.6 0.8 } }
  geometry IndexedFaceSet {
    coord Coordinate {
      point [
        -1 -1 0, 1 -1 0, 1 1 0, -1 1 0,
        0 0 2
      ]
    }
    coordIndex [ 0, 1, 4, -1, 1, 2, 4, -1, 2, 3, 4, -1, 3, 0, 4, -1 ]
  }
}
"""


def test_parse_wrl_extracts_vertices_faces_and_material_color() -> None:
    mesh = parse_wrl(WRL)

    assert len(mesh.vertices) == 5
    assert mesh.faces[0] == (0, 1, 4)
    assert len(mesh.faces) == 4
    assert mesh.color == (0.2, 0.6, 0.8)


def test_parse_wrl_triangulates_polygon_faces() -> None:
    mesh = parse_wrl(
        """#VRML V2.0 utf8
Shape { geometry IndexedFaceSet {
coord Coordinate { point [0 0 0, 1 0 0, 1 1 0, 0 1 0] }
coordIndex [0, 1, 2, 3, -1]
} }"""
    )

    assert mesh.faces == ((0, 1, 2), (0, 2, 3))


def test_project_vertices_supports_view_rotation_zoom_and_pan() -> None:
    mesh = parse_wrl(WRL)
    projected = project_vertices(
        mesh.vertices,
        yaw_degrees=90,
        pitch_degrees=0,
        scale=10,
        pan=(3, -2),
    )

    assert projected[0][0] == pytest.approx(3.0)
    assert projected[0][1] == pytest.approx(8.0)
    assert math.isfinite(projected[-1][2])


def test_parse_wrl_rejects_missing_or_out_of_range_geometry() -> None:
    with pytest.raises(WrlPreviewError, match="顶点"):
        parse_wrl("#VRML V2.0 utf8 Shape {}")
    with pytest.raises(WrlPreviewError, match="索引"):
        parse_wrl(
            """#VRML V2.0 utf8 Shape { geometry IndexedFaceSet {
coord Coordinate { point [0 0 0, 1 0 0, 0 1 0] }
coordIndex [0, 1, 99, -1]
} }"""
        )
