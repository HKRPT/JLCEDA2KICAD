from pathlib import Path

import pytest

from jlceda2kicad.library_tables import (
    LibraryTableError,
    build_project_library_table_updates,
    register_project_libraries,
)


def test_register_project_libraries_creates_both_tables(tmp_path: Path) -> None:
    result = register_project_libraries(tmp_path)

    symbol = (tmp_path / "sym-lib-table").read_text(encoding="utf-8")
    footprint = (tmp_path / "fp-lib-table").read_text(encoding="utf-8")
    assert result.symbol_registered and result.footprint_registered
    assert '(name "LCSC_Project")' in symbol
    assert "${KIPRJMOD}/libs/lcsc_project.kicad_sym" in symbol
    assert '(name "LCSC_Project")' in footprint
    assert "${KIPRJMOD}/libs/lcsc_project.pretty" in footprint


def test_register_project_libraries_is_idempotent_and_preserves_existing_text(
    tmp_path: Path,
) -> None:
    symbol_table = tmp_path / "sym-lib-table"
    original = """(sym_lib_table
  (version 7)
  (lib (name "Existing") (type "KiCad")
    (uri "${KIPRJMOD}/existing.kicad_sym") (options "") (descr "user (text)"))
)\n"""
    symbol_table.write_text(original, encoding="utf-8")

    first = register_project_libraries(tmp_path)
    first_content = symbol_table.read_text(encoding="utf-8")
    second = register_project_libraries(tmp_path)
    second_content = symbol_table.read_text(encoding="utf-8")

    assert first.symbol_registered
    assert not second.symbol_registered
    assert original.splitlines()[2] in first_content
    assert first_content == second_content
    assert first_content.count('(name "LCSC_Project")') == 1


def test_register_project_libraries_refuses_to_modify_corrupt_table(tmp_path: Path) -> None:
    table = tmp_path / "sym-lib-table"
    corrupt = '(sym_lib_table (version 7) (lib (name "broken"))'
    table.write_text(corrupt, encoding="utf-8")

    with pytest.raises(LibraryTableError, match="sym-lib-table"):
        register_project_libraries(tmp_path)

    assert table.read_text(encoding="utf-8") == corrupt
    assert not (tmp_path / "fp-lib-table").exists()


def test_register_project_libraries_leaves_no_temporary_files(tmp_path: Path) -> None:
    register_project_libraries(tmp_path)

    assert not tuple(tmp_path.glob("*.tmp"))


def test_build_table_updates_is_pure_until_transaction_commits(tmp_path: Path) -> None:
    updates, result = build_project_library_table_updates(tmp_path)

    assert {path.name for path in updates} == {"sym-lib-table", "fp-lib-table"}
    assert result.symbol_registered and result.footprint_registered
    assert not (tmp_path / "sym-lib-table").exists()
    assert '(name "LCSC_Project")' in updates[tmp_path / "sym-lib-table"]
