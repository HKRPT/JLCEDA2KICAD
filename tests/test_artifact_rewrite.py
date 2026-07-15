from pathlib import Path

import pytest

from jlceda2kicad.artifact_rewrite import (
    generated_names,
    rewrite_footprint_component,
    rewrite_symbol_component,
    validate_component_name,
)
from jlceda2kicad.models import ArtifactSet
from jlceda2kicad.sexpr import parse_one

SYMBOL = '''(kicad_symbol_lib (version 20231120)
  (symbol "Old"
    (property "Value" "Old")
    (property "Footprint" "easyeda2kicad:Old")
    (property "LCSC Part" "C2040")
    (symbol "Old_1_1" (pin passive line (at 0 0 0) (length 2.54)
      (name "A") (number "1")))))'''


def test_renames_symbol_units_value_and_footprint_association() -> None:
    rewritten = rewrite_symbol_component(SYMBOL, "C2040", "鐢靛 22uF", "Harulib:C0805-Haru")

    parse_one(rewritten)
    assert 'symbol "鐢靛 22uF"' in rewritten
    assert 'symbol "鐢靛 22uF_1_1"' in rewritten
    assert 'property "Value" "鐢靛 22uF"' in rewritten
    assert 'property "Footprint" "Harulib:C0805-Haru"' in rewritten
    assert 'property "LCSC Part" "C2040"' in rewritten


def test_inserts_missing_footprint_as_hidden_kicad_property() -> None:
    text = SYMBOL.replace('    (property "Footprint" "easyeda2kicad:Old")\n', "")

    rewritten = rewrite_symbol_component(text, "C2040", "New", "Harulib:New")

    root = parse_one(rewritten)
    symbol = next(child for child in root.children if child.head == "symbol")
    footprint = next(
        child
        for child in symbol.children
        if child.head == "property" and child.atoms[1].value == "Footprint"
    )
    assert footprint.atoms[2].value == "Harulib:New"
    assert any(child.head == "at" for child in footprint.children)
    effects = next(child for child in footprint.children if child.head == "effects")
    assert any(atom.value == "hide" for atom in effects.atoms)


def test_reads_generated_symbol_and_legacy_footprint_names(tmp_path: Path) -> None:
    symbol = tmp_path / "generated.kicad_sym"
    symbol.write_text(SYMBOL, encoding="utf-8")
    footprint = tmp_path / "generated.kicad_mod"
    footprint.write_text('(module easyeda2kicad:C0805 (layer F.Cu))', encoding="utf-8")
    artifacts = ArtifactSet(
        root=tmp_path,
        symbol_libraries=(symbol,),
        footprints=(footprint,),
    )

    assert generated_names(artifacts, "C2040") == ("Old", "C0805")


@pytest.mark.parametrize("head", ['footprint "Old"', "module easyeda2kicad:Old"])
def test_renames_modern_and_legacy_footprint_with_absolute_model(
    tmp_path: Path, head: str
) -> None:
    text = f'''({head}
      (fp_text value "Old" (at 0 0) (layer "F.Fab"))
      (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
      (model "${{KIPRJMOD}}/libs/lcsc_project.3dshapes/Old.wrl"))'''
    models = tmp_path / "Haru Lib.3dshapes"

    rewritten = rewrite_footprint_component(
        text, "C0805-Haru", model_mode="step", model_dir=models
    )

    root = parse_one(rewritten)
    assert root.head == "footprint"
    assert root.atoms[1].value == "C0805-Haru"
    assert 'fp_text value "C0805-Haru"' in rewritten
    assert (models / "Old.step").as_posix() in rewritten.replace("\\", "/")


@pytest.mark.parametrize("name", ["", "CON", "bad/name", "bad*name", "trailing. "])
def test_rejects_unsafe_component_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_component_name(name, "symbol")
