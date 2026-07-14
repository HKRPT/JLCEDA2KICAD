import pytest

from jlceda2kicad.footprint_preview import (
    ArcPrimitive,
    CirclePrimitive,
    FootprintPreviewError,
    LinePrimitive,
    PadPrimitive,
    PolygonPrimitive,
    RectPrimitive,
    parse_footprint,
)

FOOTPRINT = """(footprint "Demo"
  (layer "F.Cu")
  (pad "1" smd roundrect (at 1 2 90) (size 1.5 2.5)
    (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
  (pad "2" thru_hole circle (at -1 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask"))
  (fp_line (start 0 0) (end 3 0) (stroke (width 0.2) (type default)) (layer "F.SilkS"))
  (fp_rect (start -2 -1) (end 2 1) (stroke (width 0.15) (type default)) (fill none) (layer "F.Fab"))
  (fp_circle (center 0 0) (end 1 0) (stroke (width 0.1) (type default))
    (fill none) (layer "F.SilkS"))
  (fp_arc (start 1 0) (mid 0 1) (end -1 0) (stroke (width 0.12) (type default)) (layer "F.SilkS"))
  (fp_poly (pts (xy 0 0) (xy 1 0) (xy 0.5 1)) (stroke (width 0.1) (type default))
    (fill solid) (layer "F.Cu"))
)"""


def test_parse_footprint_supports_required_graphics_and_pad_fields() -> None:
    preview = parse_footprint(FOOTPRINT)

    assert preview.name == "Demo"
    assert [type(item) for item in preview.primitives] == [
        PadPrimitive,
        PadPrimitive,
        LinePrimitive,
        RectPrimitive,
        CirclePrimitive,
        ArcPrimitive,
        PolygonPrimitive,
    ]
    pad = preview.primitives[0]
    assert isinstance(pad, PadPrimitive)
    assert pad.number == "1"
    assert pad.at == (1.0, 2.0)
    assert pad.rotation == 90.0
    assert pad.size == (1.5, 2.5)
    assert pad.layers == ("F.Cu", "F.Paste", "F.Mask")
    assert pad.roundrect_ratio == 0.2
    plated = preview.primitives[1]
    assert isinstance(plated, PadPrimitive) and plated.drill == (1.0, 1.0)


def test_parse_footprint_retains_layers_width_and_polygon_points() -> None:
    preview = parse_footprint(FOOTPRINT)
    line = preview.primitives[2]
    polygon = preview.primitives[-1]

    assert isinstance(line, LinePrimitive)
    assert line.layer == "F.SilkS" and line.width == 0.2
    assert isinstance(polygon, PolygonPrimitive)
    assert polygon.points == ((0.0, 0.0), (1.0, 0.0), (0.5, 1.0))
    assert polygon.filled is True


def test_parse_footprint_warns_and_skips_unknown_graphic() -> None:
    preview = parse_footprint('(footprint "Demo" (fp_curve (pts (xy 0 0)) (layer "F.SilkS")))')

    assert preview.primitives == ()
    assert len(preview.warnings) == 1
    assert "fp_curve" in preview.warnings[0]


def test_parse_footprint_rejects_invalid_and_unbounded_coordinates() -> None:
    with pytest.raises(FootprintPreviewError, match="footprint"):
        parse_footprint('(symbol "wrong")')
    with pytest.raises(FootprintPreviewError, match="范围"):
        parse_footprint('(footprint "huge" (fp_line (start 0 0) (end 10000000 0) (layer "F.Cu")))')
