from pathlib import Path

import pytest

from jlceda2kicad.preview_widgets import (
    FootprintPreviewWidget,
    SymbolPreviewWidget,
    WrlPreviewWidget,
)

pytestmark = pytest.mark.usefixtures("qapp")


def test_symbol_preview_loads_svg_into_graphics_scene(qtbot: object, tmp_path: Path) -> None:
    svg = tmp_path / "symbol.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
        '<rect x="1" y="1" width="98" height="48" fill="none" stroke="black"/>'
        "</svg>",
        encoding="utf-8",
    )
    widget = SymbolPreviewWidget()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    widget.load_svg(svg)

    assert widget.source_path == svg
    assert len(widget.scene().items()) == 1


def test_footprint_preview_draws_primitives_and_exposes_warnings(qtbot: object) -> None:
    widget = FootprintPreviewWidget()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    text = """(footprint "Demo"
      (pad "1" smd rect (at 0 0) (size 1 2) (layers "F.Cu"))
      (fp_line (start -2 0) (end 2 0) (stroke (width 0.2) (type default)) (layer "F.SilkS"))
      (fp_curve (pts (xy 0 0)) (layer "F.SilkS")))"""

    widget.load_text(text)

    assert widget.preview is not None
    assert len(widget.scene().items()) >= 3  # pad shape, pad number, line
    assert "fp_curve" in widget.warnings[0]


def test_wrl_preview_loads_mesh_and_supports_named_views(qtbot: object) -> None:
    widget = WrlPreviewWidget()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.resize(320, 240)
    widget.load_text(
        """#VRML V2.0 utf8
Shape { geometry IndexedFaceSet {
coord Coordinate { point [0 0 0, 1 0 0, 0 1 0] }
coordIndex [0, 1, 2, -1]
} }"""
    )

    widget.set_named_view("top")
    assert widget.mesh is not None
    assert (widget.yaw_degrees, widget.pitch_degrees) == (0.0, 90.0)
    widget.set_named_view("front")
    assert (widget.yaw_degrees, widget.pitch_degrees) == (0.0, 0.0)
    widget.set_named_view("isometric")
    assert (widget.yaw_degrees, widget.pitch_degrees) == (45.0, 35.264)


def test_wrl_preview_wheel_changes_zoom(qtbot: object) -> None:
    widget = WrlPreviewWidget()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    before = widget.zoom
    widget.adjust_zoom(120)

    assert widget.zoom > before
