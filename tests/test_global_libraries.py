from pathlib import Path

import pytest

from jlceda2kicad.global_libraries import (
    GlobalLibraryError,
    build_global_registration,
    config_root_for_version,
    discover_global_libraries,
    pending_library,
    validate_library_destination,
)
from jlceda2kicad.models import LibraryKind, LibraryRef


def _write_tables(root: Path, user_root: Path, install_root: Path) -> None:
    root.mkdir(parents=True)
    (user_root / "symbols").mkdir(parents=True)
    (user_root / "footprints" / "Harulib.pretty").mkdir(parents=True)
    install_root.mkdir(parents=True)
    system = install_root / "System.kicad_sym"
    system.write_text("(kicad_symbol_lib (version 20231120))", encoding="utf-8")
    (user_root / "symbols" / "Harulib.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20231120))", encoding="utf-8"
    )
    (root / "sym-lib-table").write_text(
        "(sym_lib_table (version 7)"
        f' (lib (name "KiCad") (type "Table") (uri "{install_root.as_posix()}"))'
        f' (lib (name "System") (type "KiCad") (uri "{system.as_posix()}"))'
        f' (lib (name "Harulib") (type "KiCad") '
        f'(uri "{(user_root / "symbols" / "Harulib.kicad_sym").as_posix()}")))',
        encoding="utf-8",
    )
    (root / "fp-lib-table").write_text(
        "(fp_lib_table (version 7)"
        f' (lib (name "Harulib") (type "KiCad") '
        f'(uri "{(user_root / "footprints" / "Harulib.pretty").as_posix()}")))',
        encoding="utf-8",
    )


def test_discovers_writable_direct_user_libraries(tmp_path: Path) -> None:
    config = tmp_path / "Roaming" / "kicad" / "10.0"
    user_root = tmp_path / "个人 库"
    install_root = tmp_path / "Program Files" / "KiCad"
    _write_tables(config, user_root, install_root)

    catalog = discover_global_libraries(
        "10.0.4", config_root=config, install_roots=(install_root,)
    )

    assert [item.nickname for item in catalog.symbols] == ["Harulib"]
    assert [item.nickname for item in catalog.footprints] == ["Harulib"]
    assert catalog.symbols[0].table_path == config / "sym-lib-table"


def test_config_root_uses_major_minor_version(tmp_path: Path) -> None:
    assert config_root_for_version("10.0.4", roaming_root=tmp_path) == (
        tmp_path / "kicad" / "10.0"
    )


def test_config_root_uses_supplied_case_insensitive_appdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "real-process-appdata"
    supplied = tmp_path / "supplied-appdata"
    monkeypatch.setenv("APPDATA", str(decoy))

    assert config_root_for_version(
        "10.0.4", environ={"appdata": str(supplied)}
    ) == supplied / "kicad" / "10.0"


def test_discovery_uses_supplied_appdata_instead_of_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "real-process-appdata"
    supplied = tmp_path / "supplied-appdata"
    config = supplied / "kicad" / "10.0"
    user_root = tmp_path / "personal"
    install_root = tmp_path / "Program Files" / "KiCad"
    monkeypatch.setenv("APPDATA", str(decoy))
    _write_tables(config, user_root, install_root)

    catalog = discover_global_libraries(
        "10.0.4",
        environ={"APPDATA": str(supplied)},
        install_roots=(install_root,),
    )

    assert [item.nickname for item in catalog.symbols] == ["Harulib"]


def test_supplied_environment_without_appdata_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "real-process-appdata"))

    with pytest.raises(GlobalLibraryError, match="APPDATA"):
        config_root_for_version("10.0.4", environ={})


def test_registration_is_idempotent_and_rejects_retarget(tmp_path: Path) -> None:
    table = tmp_path / "sym-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    reference = pending_library(
        LibraryKind.SYMBOL, "我的库", tmp_path / "我的库.kicad_sym", table
    )

    update = build_global_registration(reference)
    table.write_text(update[table], encoding="utf-8")

    assert build_global_registration(reference) == {}
    moved = pending_library(LibraryKind.SYMBOL, "我的库", tmp_path / "other.kicad_sym", table)
    with pytest.raises(GlobalLibraryError, match="different path"):
        build_global_registration(moved)


def test_registration_rejects_same_name_table_aggregate_without_modifying_it(
    tmp_path: Path,
) -> None:
    table = tmp_path / "sym-lib-table"
    destination = tmp_path / "Haru.kicad_sym"
    original = (
        f'(sym_lib_table (version 7) (lib (name "Haru") (type "Table") '
        f'(uri "{destination.as_posix()}")))'
    )
    table.write_text(original, encoding="utf-8")
    reference = pending_library(LibraryKind.SYMBOL, "Haru", destination, table)

    with pytest.raises(GlobalLibraryError, match="different path"):
        build_global_registration(reference)

    assert table.read_text(encoding="utf-8") == original


def test_malformed_global_table_is_never_modified(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    original = "(fp_lib_table (broken)"
    table.write_text(original, encoding="utf-8")
    reference = pending_library(
        LibraryKind.FOOTPRINT, "Haru", tmp_path / "Haru.pretty", table
    )

    with pytest.raises(GlobalLibraryError, match="fp-lib-table"):
        build_global_registration(reference)

    assert table.read_text(encoding="utf-8") == original


def test_discovery_rejects_a_global_table_directory(tmp_path: Path) -> None:
    config = tmp_path / "kicad" / "10.0"
    (config / "sym-lib-table").mkdir(parents=True)

    with pytest.raises(GlobalLibraryError, match="sym-lib-table"):
        discover_global_libraries("10.0.4", config_root=config)


def test_registration_rejects_a_global_table_directory(tmp_path: Path) -> None:
    table = tmp_path / "sym-lib-table"
    table.mkdir()
    reference = pending_library(
        LibraryKind.SYMBOL, "Haru", tmp_path / "Haru.kicad_sym", table
    )

    with pytest.raises(GlobalLibraryError, match="sym-lib-table"):
        build_global_registration(reference)


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("access denied"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["permission", "unicode"],
)
def test_registration_wraps_global_table_read_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    table = tmp_path / "sym-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    reference = pending_library(
        LibraryKind.SYMBOL, "Haru", tmp_path / "Haru.kicad_sym", table
    )

    def fail_read_text(*args: object, **kwargs: object) -> str:
        raise error

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with pytest.raises(GlobalLibraryError, match="sym-lib-table"):
        build_global_registration(reference)


def test_registration_rejects_a_protected_install_destination(tmp_path: Path) -> None:
    protected = tmp_path / "Program Files" / "KiCad"
    protected.mkdir(parents=True)
    table = tmp_path / "sym-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    reference = pending_library(
        LibraryKind.SYMBOL, "System", protected / "System.kicad_sym", table
    )

    with pytest.raises(GlobalLibraryError, match="protected"):
        build_global_registration(reference, install_roots=(protected,))


def test_pending_symbol_destination_cannot_be_an_existing_directory(tmp_path: Path) -> None:
    destination = tmp_path / "Haru.kicad_sym"
    destination.mkdir()
    reference = pending_library(
        LibraryKind.SYMBOL, "Haru", destination, tmp_path / "sym-lib-table"
    )

    with pytest.raises(GlobalLibraryError, match="type"):
        validate_library_destination(reference)


def test_pending_footprint_destination_cannot_be_an_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "Haru.pretty"
    destination.write_text("not a directory", encoding="utf-8")
    reference = pending_library(
        LibraryKind.FOOTPRINT, "Haru", destination, tmp_path / "fp-lib-table"
    )

    with pytest.raises(GlobalLibraryError, match="type"):
        validate_library_destination(reference)


def test_default_programfiles_protection_is_case_insensitive_for_discovery(
    tmp_path: Path,
) -> None:
    config = tmp_path / "Roaming" / "kicad" / "10.0"
    user_root = tmp_path / "personal"
    program_files = tmp_path / "Program Files"
    install_root = program_files / "KiCad"
    _write_tables(config, user_root, install_root)

    catalog = discover_global_libraries(
        "10.0.4", config_root=config, environ={"PROGRAMFILES": str(program_files)}
    )

    assert [item.nickname for item in catalog.symbols] == ["Harulib"]


def test_default_programfiles_x86_protection_is_case_insensitive_for_registration(
    tmp_path: Path,
) -> None:
    program_files_x86 = tmp_path / "Program Files (x86)"
    protected = program_files_x86 / "KiCad"
    protected.mkdir(parents=True)
    table = tmp_path / "sym-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    reference = pending_library(
        LibraryKind.SYMBOL, "System", protected / "System.kicad_sym", table
    )

    with pytest.raises(GlobalLibraryError, match="protected"):
        build_global_registration(
            reference, environ={"PROGRAMFILES(X86)": str(program_files_x86)}
        )


def test_registered_library_that_disappeared_is_rejected(tmp_path: Path) -> None:
    table = tmp_path / "sym-lib-table"
    missing = tmp_path / "Missing.kicad_sym"
    table.write_text(
        f'(sym_lib_table (version 7) (lib (name "Missing") (type "KiCad") '
        f'(uri "{missing.as_posix()}")))',
        encoding="utf-8",
    )
    reference = LibraryRef("Missing", LibraryKind.SYMBOL, missing, table, registered=True)

    with pytest.raises(GlobalLibraryError, match="disappeared"):
        build_global_registration(reference)
