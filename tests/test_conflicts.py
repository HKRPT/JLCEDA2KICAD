from pathlib import Path

import pytest

from jlceda2kicad.conflicts import (
    ComponentConflictError,
    merge_symbol_library,
    resolve_file_conflicts,
)
from jlceda2kicad.models import ConflictPolicy

EXISTING = """(kicad_symbol_lib
  (version 20231120)
  (symbol "OldName" (property "LCSC Part" "C100"))
  (symbol "SameName" (property "LCSC Part" "C200"))
)"""


def _incoming(name: str = "NewName", lcsc_id: str = "C100") -> str:
    return f"""(kicad_symbol_lib
  (version 20231120)
  (generator easyeda2kicad)
  (symbol "{name}" (property "LCSC Part" "{lcsc_id}"))
)"""


def test_symbol_conflict_cancel_reports_lcsc_collision() -> None:
    with pytest.raises(ComponentConflictError, match="C100"):
        merge_symbol_library(EXISTING, _incoming(), "C100", ConflictPolicy.CANCEL)


def test_symbol_conflict_skip_leaves_library_byte_for_byte() -> None:
    result = merge_symbol_library(EXISTING, _incoming(), "C100", ConflictPolicy.SKIP_EXISTING)

    assert result.text == EXISTING
    assert result.skipped is True
    assert result.overwritten_names == ()


def test_symbol_conflict_overwrite_replaces_only_colliding_node() -> None:
    result = merge_symbol_library(EXISTING, _incoming(), "C100", ConflictPolicy.OVERWRITE_COMPONENT)

    assert 'symbol "OldName"' not in result.text
    assert 'symbol "NewName"' in result.text
    assert 'symbol "SameName"' in result.text
    assert result.overwritten_names == ("OldName",)


def test_symbol_name_collision_is_detected_even_with_different_lcsc_id() -> None:
    with pytest.raises(ComponentConflictError, match="SameName"):
        merge_symbol_library(EXISTING, _incoming("SameName", "C300"), "C300", ConflictPolicy.CANCEL)


def test_symbol_merge_creates_a_library_when_none_exists() -> None:
    result = merge_symbol_library(None, _incoming(), "C100", ConflictPolicy.CANCEL)

    assert result.text == _incoming()
    assert result.skipped is False


def test_file_skip_policy_keeps_only_missing_targets(tmp_path: Path) -> None:
    existing = tmp_path / "part.kicad_mod"
    existing.write_text("old", encoding="utf-8")
    missing = tmp_path / "part.step"
    staged_existing = tmp_path / "staged.kicad_mod"
    staged_missing = tmp_path / "staged.step"

    selected, skipped = resolve_file_conflicts(
        {staged_existing: existing, staged_missing: missing},
        ConflictPolicy.SKIP_EXISTING,
    )

    assert selected == {staged_missing: missing}
    assert skipped == (existing,)


def test_file_cancel_policy_refuses_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "part.wrl"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(ComponentConflictError, match=r"part\.wrl"):
        resolve_file_conflicts({tmp_path / "staged.wrl": target}, ConflictPolicy.CANCEL)
