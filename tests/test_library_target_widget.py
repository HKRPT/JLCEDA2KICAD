from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from jlceda2kicad.global_libraries import pending_library
from jlceda2kicad.library_target_widget import (
    ImportResultDialog,
    LibraryTargetWidget,
    NewLibraryDialog,
)
from jlceda2kicad.models import ImportReport, ImportScope, LibraryKind
from jlceda2kicad.settings import AppSettings

pytestmark = pytest.mark.usefixtures("qapp")


def _global_tables(config: Path, root: Path) -> None:
    config.mkdir(parents=True)
    symbol = root / "symbols" / "Harulib.kicad_sym"
    footprint = root / "footprints" / "Harulib.pretty"
    symbol.parent.mkdir(parents=True)
    footprint.mkdir(parents=True)
    symbol.write_text("(kicad_symbol_lib (version 20231120))", encoding="utf-8")
    (config / "sym-lib-table").write_text(
        f'(sym_lib_table (version 7) (lib (name "Harulib") (type "KiCad") '
        f'(uri "{symbol.as_posix()}")))',
        encoding="utf-8",
    )
    (config / "fp-lib-table").write_text(
        f'(fp_lib_table (version 7) (lib (name "Harulib") (type "KiCad") '
        f'(uri "{footprint.as_posix()}")))',
        encoding="utf-8",
    )


def test_global_widget_selects_existing_libraries_and_custom_names(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "用户 库")
    widget = LibraryTargetWidget(
        AppSettings(
            last_import_scope=ImportScope.GLOBAL,
            last_symbol_library="Harulib",
            last_footprint_library="Harulib",
        ),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    widget.set_generated_names("OriginalSymbol", "OriginalFootprint")
    widget.symbol_name.setText("22uF 25V")
    widget.footprint_name.setText("C0805-Haru")
    target = widget.build_target()

    assert target.scope is ImportScope.GLOBAL
    assert target.symbol_library is not None
    assert target.symbol_library.nickname == "Harulib"
    assert target.footprint_library is not None
    assert target.footprint_library.nickname == "Harulib"
    assert target.symbol_name == "22uF 25V"
    assert target.footprint_name == "C0805-Haru"
    assert "Harulib.3dshapes" in widget.model_path.text()


def test_project_scope_hides_global_controls(qtbot: object, tmp_path: Path) -> None:
    widget = LibraryTargetWidget(AppSettings(), kicad_version="10.0.4", config_root=tmp_path)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget.build_target().scope is ImportScope.PROJECT
    assert widget.global_fields.isHidden()


def test_pending_symbol_and_footprint_libraries_remain_independent(
    qtbot: object, tmp_path: Path
) -> None:
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=tmp_path / "config",
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    symbol = pending_library(
        LibraryKind.SYMBOL,
        "MySymbols",
        tmp_path / "symbols" / "MySymbols.kicad_sym",
        tmp_path / "config" / "sym-lib-table",
    )
    footprint = pending_library(
        LibraryKind.FOOTPRINT,
        "MyFootprints",
        tmp_path / "footprints" / "MyFootprints.pretty",
        tmp_path / "config" / "fp-lib-table",
    )

    widget.add_pending_library(symbol)
    widget.add_pending_library(footprint)
    widget.set_generated_names("Symbol", "Footprint")
    target = widget.build_target()

    assert target.symbol_library == symbol
    assert target.footprint_library == footprint


def test_refresh_preserves_pending_libraries_in_their_own_selectors(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    symbol = pending_library(
        LibraryKind.SYMBOL,
        "NewSymbols",
        tmp_path / "NewSymbols.kicad_sym",
        config / "sym-lib-table",
    )
    footprint = pending_library(
        LibraryKind.FOOTPRINT,
        "NewFootprints",
        tmp_path / "NewFootprints.pretty",
        config / "fp-lib-table",
    )
    widget.add_pending_library(symbol)
    widget.add_pending_library(footprint)

    widget.refresh()

    assert [widget.symbol_library.itemData(index) for index in range(2)] == [
        widget.symbol_library.itemData(0),
        symbol,
    ]
    assert widget.symbol_library.itemData(0).kind is LibraryKind.SYMBOL
    assert [widget.footprint_library.itemData(index) for index in range(2)] == [
        widget.footprint_library.itemData(0),
        footprint,
    ]
    assert widget.footprint_library.itemData(0).kind is LibraryKind.FOOTPRINT


def test_stale_saved_nicknames_do_not_select_an_unrelated_library(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(
            last_import_scope=ImportScope.GLOBAL,
            last_symbol_library="Missing",
            last_footprint_library="Missing",
        ),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget.symbol_library.currentIndex() == -1
    assert widget.footprint_library.currentIndex() == -1


def test_unsafe_custom_name_is_rejected(qtbot: object, tmp_path: Path) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(0)
    widget.footprint_library.setCurrentIndex(0)
    widget.set_generated_names("bad/name", "Footprint")

    with pytest.raises(ValueError, match="forbidden"):
        widget.build_target()


def test_symbol_only_target_does_not_require_a_footprint_library(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(0)
    widget.footprint_library.setCurrentIndex(-1)
    widget.set_generated_names("SymbolOnly", "")

    target = widget.build_target(
        import_symbol=True, import_footprint=False, import_models=False
    )

    assert target.symbol_library is not None
    assert target.footprint_library is None
    assert target.symbol_name == "SymbolOnly"
    assert target.footprint_name is None


def test_footprint_only_target_does_not_require_a_symbol_library(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(-1)
    widget.footprint_library.setCurrentIndex(0)
    widget.set_generated_names("", "FootprintOnly")

    target = widget.build_target(
        import_symbol=False, import_footprint=True, import_models=False
    )

    assert target.symbol_library is None
    assert target.footprint_library is not None
    assert target.symbol_name is None
    assert target.footprint_name == "FootprintOnly"


def test_models_only_target_does_not_require_component_names(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(-1)
    widget.footprint_library.setCurrentIndex(0)

    target = widget.build_target(
        import_symbol=False, import_footprint=False, import_models=True
    )

    assert target.symbol_library is None
    assert target.footprint_library is not None
    assert target.symbol_name is None
    assert target.footprint_name is None


def test_malformed_catalog_does_not_prevent_widget_creation(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "sym-lib-table").write_text("(sym_lib_table (broken)", encoding="utf-8")

    widget = LibraryTargetWidget(
        AppSettings(), kicad_version="10.0.4", config_root=config
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget.symbol_library.count() == 0
    assert "sym-lib-table" in widget.catalog_error


def test_refreshing_a_malformed_catalog_keeps_the_widget_usable(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    (config / "sym-lib-table").write_text("(sym_lib_table (broken)", encoding="utf-8")

    widget.refresh()

    assert widget.symbol_library.count() == 0
    assert widget.footprint_library.count() == 0
    assert "sym-lib-table" in widget.catalog_error


@pytest.mark.parametrize(
    ("kind", "path", "table_name"),
    [
        (LibraryKind.SYMBOL, Path("Symbols.kicad_sym"), "sym-lib-table"),
        (LibraryKind.FOOTPRINT, Path("Footprints.pretty"), "fp-lib-table"),
    ],
)
def test_new_library_dialog_only_builds_a_pending_reference(
    qtbot: object,
    tmp_path: Path,
    kind: LibraryKind,
    path: Path,
    table_name: str,
) -> None:
    config = tmp_path / "config"
    destination = tmp_path / "libraries" / path
    dialog = NewLibraryDialog(kind, config)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.nickname.setText(path.stem)
    dialog.path.setText(str(destination))

    reference = dialog.library_ref()

    assert reference.kind is kind
    assert reference.path == destination.resolve()
    assert reference.table_path == (config / table_name).resolve()
    assert not reference.registered
    assert not destination.exists()
    assert not config.exists()


def test_apply_settings_only_updates_global_library_nicknames(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    original = AppSettings(last_import_scope=ImportScope.GLOBAL)
    widget = LibraryTargetWidget(
        original,
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(0)
    widget.footprint_library.setCurrentIndex(0)
    widget.set_generated_names("Symbol", "Footprint")

    updated = widget.apply_settings(original)

    assert updated.last_import_scope is ImportScope.GLOBAL
    assert updated.last_symbol_library == "Harulib"
    assert updated.last_footprint_library == "Harulib"


def test_result_dialog_copies_every_reported_path(qtbot: object, tmp_path: Path) -> None:
    report = ImportReport(
        success=True,
        symbol_destination=tmp_path / "Symbols.kicad_sym",
        footprint_destination=tmp_path / "Footprints.pretty" / "Part.kicad_mod",
        model_directory=tmp_path / "Footprints.3dshapes",
        backup_dir=tmp_path / "backups" / "one",
        footprint_association="Footprints:Part",
    )
    dialog = ImportResultDialog(report)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog._copy_paths()

    copied = QApplication.clipboard().text().splitlines()
    assert copied == [
        str(report.symbol_destination),
        str(report.footprint_destination),
        str(report.model_directory),
        str(report.backup_dir),
    ]


def test_result_dialog_only_displays_reported_details(
    qtbot: object, tmp_path: Path
) -> None:
    report = ImportReport(
        success=True,
        committed_paths=(tmp_path / "Symbols.kicad_sym",),
        symbol_destination=tmp_path / "Symbols.kicad_sym",
        backup_dir=tmp_path / "backups" / "one",
        warnings=("Needs attention",),
        library_registration=("Symbols",),
    )
    dialog = ImportResultDialog(report)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    details = dialog.findChild(QPlainTextEdit).toPlainText()

    assert str(report.symbol_destination) in details
    assert str(report.backup_dir) in details
    assert "Needs attention" in details
    assert "Symbols" in details
    assert "KiCad" in details
    assert "重启" in details
    assert "3D 模型目录" not in details
    assert "封装关联" not in details
