from pathlib import Path

import pytest

from jlceda2kicad.import_validation import (
    ImportValidationError,
    validate_footprint,
    validate_symbol_library,
)


def test_symbol_validation_rejects_unbalanced_library(tmp_path: Path) -> None:
    symbol = tmp_path / "broken.kicad_sym"
    symbol.write_text('(kicad_symbol_lib (symbol "broken")', encoding="utf-8")

    with pytest.raises(ImportValidationError, match="括号"):
        validate_symbol_library(symbol)


def test_footprint_validation_rejects_absolute_or_temporary_model_paths(
    tmp_path: Path,
) -> None:
    footprint = tmp_path / "bad.kicad_mod"
    footprint.write_text(
        '(footprint "bad" (model "C:/Users/demo/AppData/Local/Temp/part.step"))',
        encoding="utf-8",
    )

    with pytest.raises(ImportValidationError, match=r"绝对路径|临时路径"):
        validate_footprint(footprint)


def test_footprint_validation_accepts_project_relative_model_reference(
    tmp_path: Path,
) -> None:
    footprint = tmp_path / "good.kicad_mod"
    footprint.write_text(
        """(footprint "good"
  (pad "1" thru_hole circle (at 0 0) (size 1 1) (drill 0.5) (layers "*.Cu" "*.Mask"))
  (model "${KIPRJMOD}/libs/lcsc_project.3dshapes/good.step"))""",
        encoding="utf-8",
    )

    result = validate_footprint(footprint)

    assert result.model_paths == ("${KIPRJMOD}/libs/lcsc_project.3dshapes/good.step",)


def test_footprint_validation_accepts_easyeda_legacy_module(tmp_path: Path) -> None:
    footprint = tmp_path / "C0805.kicad_mod"
    footprint.write_text(
        """(module easyeda2kicad:C0805 (layer F.Cu)
  (pad 1 smd rect (at 0 0) (size 1 1) (layers F.Cu F.Paste F.Mask))
  (model "${KIPRJMOD}/libs/lcsc_project.3dshapes/C0805.wrl"))""",
        encoding="utf-8",
    )

    result = validate_footprint(footprint)

    assert result.pin_or_pad_numbers == frozenset({"1"})
    assert result.model_paths == ("${KIPRJMOD}/libs/lcsc_project.3dshapes/C0805.wrl",)


def test_pin_pad_number_difference_is_warning_not_failure(tmp_path: Path) -> None:
    symbol = tmp_path / "lib.kicad_sym"
    symbol.write_text(
        """(kicad_symbol_lib
  (version 20231120)
  (symbol "part" (symbol "part_1_1"
    (pin passive line (at 0 0 0) (length 2.54) (name "A") (number "1"))
    (pin passive line (at 0 0 0) (length 2.54) (name "B") (number "2")))))""",
        encoding="utf-8",
    )
    footprint = tmp_path / "part.kicad_mod"
    footprint.write_text(
        '(footprint "part" (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu")))',
        encoding="utf-8",
    )

    symbol_result = validate_symbol_library(symbol)
    footprint_result = validate_footprint(footprint)
    warnings = symbol_result.compare_pad_numbers(footprint_result)

    assert len(warnings) == 1
    assert "2" in warnings[0]


def test_empty_kicad_file_is_rejected(tmp_path: Path) -> None:
    footprint = tmp_path / "empty.kicad_mod"
    footprint.write_bytes(b"")

    with pytest.raises(ImportValidationError, match="空文件"):
        validate_footprint(footprint)
