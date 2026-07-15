from pathlib import Path

import pytest

from jlceda2kicad.absolute_backup import AbsoluteBackupManager
from jlceda2kicad.import_service import (
    ImportServiceError,
    find_import_conflicts,
    import_shadow_artifacts,
)
from jlceda2kicad.import_transaction import AtomicMultiRootTransaction, ImportTransactionError
from jlceda2kicad.models import (
    ArtifactSet,
    ConflictPolicy,
    ImportOptions,
    ImportReport,
    ImportScope,
    ImportTarget,
    LibraryKind,
    LibraryRef,
)


def _write_shadow_artifacts(shadow: Path) -> ArtifactSet:
    libs = shadow / "libs"
    pretty = libs / "lcsc_project.pretty"
    models = libs / "lcsc_project.3dshapes"
    pretty.mkdir(parents=True)
    models.mkdir()
    symbol = libs / "lcsc_project.kicad_sym"
    symbol.write_text(
        '''(kicad_symbol_lib (version 20231120)
          (symbol "NewPart"
            (property "Value" "NewPart")
            (property "Footprint" "easyeda2kicad:NewPart")
            (property "LCSC Part" "C2040")
            (symbol "NewPart_1_1" (pin passive line (at 0 0 0) (length 2.54)
              (name "A") (number "1")))))''',
        encoding="utf-8",
    )
    footprint = pretty / "NewPart.kicad_mod"
    footprint.write_text(
        '''(footprint "NewPart"
          (fp_text value "NewPart" (at 0 0) (layer "F.Fab"))
          (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
          (model "${KIPRJMOD}/libs/lcsc_project.3dshapes/NewPart.wrl"))''',
        encoding="utf-8",
    )
    step = models / "NewPart.step"
    wrl = models / "NewPart.wrl"
    step.write_text("ISO-10303-21;", encoding="utf-8")
    wrl.write_text("#VRML V2.0 utf8", encoding="utf-8")
    return ArtifactSet(
        shadow,
        symbol_libraries=(symbol,),
        footprints=(footprint,),
        step_models=(step,),
        wrl_models=(wrl,),
    )


def test_imports_custom_names_into_existing_global_libraries(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    config = tmp_path / "Roaming" / "kicad" / "10.0"
    config.mkdir(parents=True)
    symbols = tmp_path / "Documents" / "symbols" / "Harulib.kicad_sym"
    footprints = tmp_path / "Documents" / "footprints" / "Harulib.pretty"
    symbols.parent.mkdir(parents=True)
    footprints.mkdir(parents=True)
    symbols.write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Keep" (property "LCSC Part" "C1")))',
        encoding="utf-8",
    )
    sym_table = config / "sym-lib-table"
    fp_table = config / "fp-lib-table"
    sym_table.write_text(
        f'(sym_lib_table (version 7) (lib (name "Harulib") '
        f'(type "KiCad") (uri "{symbols.as_posix()}")))',
        encoding="utf-8",
    )
    fp_table.write_text(
        f'(fp_lib_table (version 7) (lib (name "Harulib") '
        f'(type "KiCad") (uri "{footprints.as_posix()}")))',
        encoding="utf-8",
    )
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef("Harulib", LibraryKind.SYMBOL, symbols, sym_table),
        footprint_library=LibraryRef("Harulib", LibraryKind.FOOTPRINT, footprints, fp_table),
        symbol_name="22uF 25V",
        footprint_name="C0805-Haru",
    )
    options = ImportOptions(step=True, wrl=False, target=target)

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        options,
        global_backup_root=tmp_path / "app-data" / "backups" / "global",
    )

    symbol_text = symbols.read_text(encoding="utf-8")
    footprint_file = footprints / "C0805-Haru.kicad_mod"
    footprint_text = footprint_file.read_text(encoding="utf-8")
    assert 'symbol "Keep"' in symbol_text
    assert 'symbol "22uF 25V"' in symbol_text
    assert 'property "Footprint" "Harulib:C0805-Haru"' in symbol_text
    assert footprint_file.is_file()
    assert (footprints.with_suffix(".3dshapes") / "NewPart.step").as_posix() in footprint_text
    assert report.footprint_association == "Harulib:C0805-Haru"
    assert report.symbol_destination == symbols
    assert report.footprint_destination == footprint_file
    assert report.backup_dir is not None


def _pending_target(tmp_path: Path) -> ImportTarget:
    config = tmp_path / "config"
    config.mkdir()
    sym_table = config / "sym-lib-table"
    fp_table = config / "fp-lib-table"
    sym_table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    fp_table.write_text("(fp_lib_table (version 7))", encoding="utf-8")
    return ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Symbols",
            LibraryKind.SYMBOL,
            tmp_path / "Symbols.kicad_sym",
            sym_table,
            registered=False,
        ),
        footprint_library=LibraryRef(
            "Footprints",
            LibraryKind.FOOTPRINT,
            tmp_path / "Footprints.pretty",
            fp_table,
            registered=False,
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )


@pytest.mark.parametrize(
    ("policy", "outcome"),
    [
        (ConflictPolicy.CANCEL, "cancel"),
        (ConflictPolicy.SKIP_EXISTING, "original"),
        (ConflictPolicy.OVERWRITE_COMPONENT, "rewritten"),
    ],
)
def test_global_footprint_conflict_policies(
    tmp_path: Path, policy: ConflictPolicy, outcome: str
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.footprint_library is not None
    target.footprint_library.path.mkdir()
    destination = target.footprint_library.path / "CustomFootprint.kicad_mod"
    destination.write_text("original", encoding="utf-8")
    options = ImportOptions(step=False, wrl=False, conflict_policy=policy, target=target)

    if outcome == "cancel":
        with pytest.raises(ImportServiceError, match="CustomFootprint"):
            import_shadow_artifacts(
                tmp_path / "project",
                shadow,
                "C2040",
                artifacts,
                options,
                global_backup_root=tmp_path / "backups",
            )
        assert destination.read_text(encoding="utf-8") == "original"
        return

    import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        options,
        global_backup_root=tmp_path / "backups",
    )
    content = destination.read_text(encoding="utf-8")
    if outcome == "original":
        assert content == "original"
    else:
        assert 'footprint "CustomFootprint"' in content


def test_skip_existing_symbol_clears_unapplied_association_but_imports_footprint(
    tmp_path: Path,
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.symbol_library is not None
    assert target.footprint_library is not None
    original_symbol = (
        '(kicad_symbol_lib (version 20231120) '
        '(symbol "CustomSymbol" (property "Footprint" "Old:Foot") '
        '(property "LCSC Part" "C2040")))'
    )
    target.symbol_library.path.write_text(original_symbol, encoding="utf-8")

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        ImportOptions(
            step=False,
            wrl=False,
            conflict_policy=ConflictPolicy.SKIP_EXISTING,
            target=target,
        ),
        global_backup_root=tmp_path / "backups",
    )

    destination = target.footprint_library.path / "CustomFootprint.kicad_mod"
    assert destination.is_file()
    assert target.symbol_library.path.read_text(encoding="utf-8") == original_symbol
    assert report.footprint_association is None
    assert any("关联未应用" in warning for warning in report.warnings)


def test_symbol_only_preserves_converter_footprint_and_warns_unverified_association(
    tmp_path: Path,
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.symbol_library is not None

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        ImportOptions(
            footprint=False,
            step=False,
            wrl=False,
            target=target,
        ),
        global_backup_root=tmp_path / "backups",
    )

    symbol_text = target.symbol_library.path.read_text(encoding="utf-8")
    assert 'property "Footprint" "easyeda2kicad:NewPart"' in symbol_text
    assert report.footprint_association is None
    assert any("关联未在所选全局目标中验证" in warning for warning in report.warnings)


def test_pending_libraries_register_both_global_tables(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    config = tmp_path / "config"
    config.mkdir()
    sym_table = config / "sym-lib-table"
    fp_table = config / "fp-lib-table"
    sym_table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    fp_table.write_text("(fp_lib_table (version 7))", encoding="utf-8")
    symbols = tmp_path / "新库" / "Symbols.kicad_sym"
    footprints = tmp_path / "新库" / "Footprints.pretty"
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "MySymbols", LibraryKind.SYMBOL, symbols, sym_table, registered=False
        ),
        footprint_library=LibraryRef(
            "MyFootprints", LibraryKind.FOOTPRINT, footprints, fp_table, registered=False
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        ImportOptions(step=True, wrl=False, target=target),
        global_backup_root=tmp_path / "backups",
    )

    assert '(name "MySymbols")' in sym_table.read_text(encoding="utf-8")
    assert '(name "MyFootprints")' in fp_table.read_text(encoding="utf-8")
    assert set(report.library_registration) == {
        "MySymbols (symbol)",
        "MyFootprints (footprint)",
    }


@pytest.mark.parametrize("library_exists", [False, True])
def test_models_only_rejects_pending_footprint_library_without_writes(
    tmp_path: Path, library_exists: bool
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.footprint_library is not None
    if library_exists:
        target.footprint_library.path.mkdir()
    before_table = target.footprint_library.table_path.read_text(encoding="utf-8")

    with pytest.raises(ImportServiceError, match="registered footprint library"):
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(
                symbol=False,
                footprint=False,
                step=True,
                wrl=False,
                target=target,
            ),
            global_backup_root=tmp_path / "backups",
        )

    assert target.model_dir is not None and not target.model_dir.exists()
    assert target.footprint_library.path.exists() is library_exists
    if library_exists:
        assert not tuple(target.footprint_library.path.iterdir())
    assert target.footprint_library.table_path.read_text(encoding="utf-8") == before_table
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("destination_state", ["missing", "wrong_type"])
def test_models_only_rejects_invalid_registered_footprint_library_without_writes(
    tmp_path: Path, destination_state: str
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    footprint_library = tmp_path / "Footprints.pretty"
    if destination_state == "wrong_type":
        footprint_library.write_text("not a directory", encoding="utf-8")
    table = tmp_path / "fp-lib-table"
    table_text = (
        '(fp_lib_table (version 7) (lib (name "Footprints") (type "KiCad") '
        f'(uri "{footprint_library.as_posix()}")))'
    )
    table.write_text(table_text, encoding="utf-8")
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        footprint_library=LibraryRef(
            "Footprints",
            LibraryKind.FOOTPRINT,
            footprint_library,
            table,
            registered=True,
        ),
    )

    with pytest.raises(ImportServiceError, match=r"Footprints\.pretty"):
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(
                symbol=False,
                footprint=False,
                step=True,
                wrl=False,
                target=target,
            ),
            global_backup_root=tmp_path / "backups",
        )

    assert target.model_dir is not None and not target.model_dir.exists()
    assert table.read_text(encoding="utf-8") == table_text
    assert not (tmp_path / "backups").exists()
    if destination_state == "wrong_type":
        assert footprint_library.read_text(encoding="utf-8") == "not a directory"


def test_models_only_accepts_existing_registered_footprint_library(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    footprint_library = tmp_path / "Footprints.pretty"
    footprint_library.mkdir()
    table = tmp_path / "fp-lib-table"
    table_text = (
        '(fp_lib_table (version 7) (lib (name "Footprints") (type "KiCad") '
        f'(uri "{footprint_library.as_posix()}")))'
    )
    table.write_text(table_text, encoding="utf-8")
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        footprint_library=LibraryRef(
            "Footprints",
            LibraryKind.FOOTPRINT,
            footprint_library,
            table,
            registered=True,
        ),
    )

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        ImportOptions(
            symbol=False,
            footprint=False,
            step=True,
            wrl=False,
            target=target,
        ),
        global_backup_root=tmp_path / "backups",
    )

    assert target.model_dir is not None
    assert (target.model_dir / "NewPart.step").is_file()
    assert table.read_text(encoding="utf-8") == table_text
    assert report.library_registration == ()


def test_models_only_rejects_mismatched_registered_table_without_writes(
    tmp_path: Path,
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    footprint_library = tmp_path / "Footprints.pretty"
    footprint_library.mkdir()
    table = tmp_path / "fp-lib-table"
    table_text = (
        '(fp_lib_table (version 7) (lib (name "Footprints") (type "KiCad") '
        f'(uri "{(tmp_path / "Other.pretty").as_posix()}")))'
    )
    table.write_text(table_text, encoding="utf-8")
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        footprint_library=LibraryRef(
            "Footprints",
            LibraryKind.FOOTPRINT,
            footprint_library,
            table,
            registered=True,
        ),
    )

    with pytest.raises(ImportServiceError, match="different path"):
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(
                symbol=False,
                footprint=False,
                step=True,
                wrl=False,
                target=target,
            ),
            global_backup_root=tmp_path / "backups",
        )

    assert target.model_dir is not None and not target.model_dir.exists()
    assert not tuple(footprint_library.iterdir())
    assert table.read_text(encoding="utf-8") == table_text
    assert not (tmp_path / "backups").exists()


def test_global_import_requires_backup_root_before_writing(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Symbols",
            LibraryKind.SYMBOL,
            tmp_path / "Symbols.kicad_sym",
            tmp_path / "sym-lib-table",
            registered=False,
        ),
        footprint_library=LibraryRef(
            "Footprints",
            LibraryKind.FOOTPRINT,
            tmp_path / "Footprints.pretty",
            tmp_path / "fp-lib-table",
            registered=False,
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )

    with pytest.raises(ImportServiceError, match="backup"):
        import_shadow_artifacts(
            tmp_path / "project", shadow, "C2040", artifacts, ImportOptions(target=target)
        )

    assert not target.symbol_library.path.exists()
    assert not target.footprint_library.path.exists()


def test_conflicting_global_nickname_aborts_before_library_write(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    table = tmp_path / "sym-lib-table"
    table.write_text(
        f'(sym_lib_table (version 7) (lib (name "Haru") (type "KiCad") '
        f'(uri "{(tmp_path / "old.kicad_sym").as_posix()}")))',
        encoding="utf-8",
    )
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Haru",
            LibraryKind.SYMBOL,
            tmp_path / "new.kicad_sym",
            table,
            registered=False,
        ),
        footprint_library=LibraryRef(
            "Foot",
            LibraryKind.FOOTPRINT,
            tmp_path / "Foot.pretty",
            tmp_path / "fp-lib-table",
            registered=False,
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )

    with pytest.raises(ImportServiceError, match="different path"):
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(target=target),
            global_backup_root=tmp_path / "backups",
        )

    assert not target.symbol_library.path.exists()


def test_transaction_failure_report_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    sym_table = tmp_path / "sym-lib-table"
    fp_table = tmp_path / "fp-lib-table"
    sym_table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    fp_table.write_text("(fp_lib_table (version 7))", encoding="utf-8")
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Sym", LibraryKind.SYMBOL, tmp_path / "Sym.kicad_sym", sym_table, False
        ),
        footprint_library=LibraryRef(
            "Foot", LibraryKind.FOOTPRINT, tmp_path / "Foot.pretty", fp_table, False
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )
    failed = ImportReport(
        success=False,
        backup_dir=tmp_path / "backups" / "failed",
        rollback_result=("locked restore",),
    )

    def fail_commit(self: object, mappings: object) -> ImportReport:
        raise ImportTransactionError("forced failure", failed)

    monkeypatch.setattr(AtomicMultiRootTransaction, "commit", fail_commit)

    with pytest.raises(ImportServiceError) as captured:
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(target=target),
            global_backup_root=tmp_path / "backups",
        )

    assert captured.value.report == failed


def test_backup_creation_failure_reaches_service_report_without_target_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.symbol_library is not None
    assert target.footprint_library is not None
    symbol_table_before = target.symbol_library.table_path.read_text(encoding="utf-8")
    footprint_table_before = target.footprint_library.table_path.read_text(encoding="utf-8")

    def fail_create(self: object, paths: tuple[Path, ...]) -> object:
        raise PermissionError(f"backup root locked for {len(paths)} targets")

    monkeypatch.setattr(AbsoluteBackupManager, "create", fail_create)

    with pytest.raises(ImportServiceError, match="backup") as captured:
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(step=False, wrl=False, target=target),
            global_backup_root=tmp_path / "backups",
        )

    assert not captured.value.report.success
    assert not target.symbol_library.path.exists()
    assert not target.footprint_library.path.exists()
    assert target.symbol_library.table_path.read_text(encoding="utf-8") == symbol_table_before
    assert (
        target.footprint_library.table_path.read_text(encoding="utf-8")
        == footprint_table_before
    )
    assert not (tmp_path / "backups").exists()


def test_global_report_includes_transaction_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)

    def fail_prune(self: object) -> tuple[Path, ...]:
        raise PermissionError("prune locked")

    monkeypatch.setattr(AbsoluteBackupManager, "prune", fail_prune)

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        ImportOptions(step=False, wrl=False, target=target),
        global_backup_root=tmp_path / "backups",
    )

    assert any("prune locked" in warning for warning in report.warnings)


def test_global_conflict_preflight_uses_custom_names_and_model_targets(
    tmp_path: Path,
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.symbol_library is not None
    assert target.footprint_library is not None
    target.symbol_library.path.write_text(
        '(kicad_symbol_lib (version 20231120) '
        '(symbol "CustomSymbol" (property "LCSC Part" "C1")))',
        encoding="utf-8",
    )
    target.footprint_library.path.mkdir()
    footprint = target.footprint_library.path / "CustomFootprint.kicad_mod"
    footprint.write_text("existing", encoding="utf-8")
    assert target.model_dir is not None
    target.model_dir.mkdir()
    model = target.model_dir / "NewPart.step"
    model.write_text("existing", encoding="utf-8")

    conflicts = find_import_conflicts(
        tmp_path / "project",
        artifacts,
        "C2040",
        ImportOptions(wrl=False, target=target),
    )

    assert any("CustomSymbol" in conflict for conflict in conflicts)
    assert str(footprint) in conflicts
    assert str(model) in conflicts


@pytest.mark.parametrize(
    ("step", "wrl", "expected_names"),
    [
        (False, False, set()),
        (True, False, {"NewPart.step"}),
        (False, True, {"NewPart.wrl"}),
    ],
)
def test_global_model_conflicts_follow_selected_model_modes(
    tmp_path: Path, step: bool, wrl: bool, expected_names: set[str]
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    stp = artifacts.step_models[0].with_suffix(".stp")
    artifacts.step_models[0].rename(stp)
    artifacts = ArtifactSet(
        artifacts.root,
        symbol_libraries=artifacts.symbol_libraries,
        footprints=artifacts.footprints,
        step_models=(stp,),
        wrl_models=artifacts.wrl_models,
    )
    target = _pending_target(tmp_path)
    assert target.model_dir is not None
    target.model_dir.mkdir()
    for name in ("NewPart.step", "NewPart.wrl"):
        (target.model_dir / name).write_text("existing", encoding="utf-8")

    conflicts = find_import_conflicts(
        tmp_path / "project",
        artifacts,
        "C2040",
        ImportOptions(
            symbol=False,
            footprint=False,
            step=step,
            wrl=wrl,
            target=target,
        ),
    )

    assert {Path(conflict).name for conflict in conflicts} == expected_names


def test_global_conflict_preflight_names_unreadable_symbol_target(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.symbol_library is not None
    target.symbol_library.path.write_text("not an s-expression", encoding="utf-8")

    conflicts = find_import_conflicts(
        tmp_path / "project",
        artifacts,
        "C2040",
        ImportOptions(footprint=False, step=False, wrl=False, target=target),
    )

    assert len(conflicts) == 1
    assert str(target.symbol_library.path) in conflicts[0]


def test_global_conflict_preflight_names_wrong_type_symbol_target(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.symbol_library is not None
    target.symbol_library.path.mkdir()

    conflicts = find_import_conflicts(
        tmp_path / "project",
        artifacts,
        "C2040",
        ImportOptions(footprint=False, step=False, wrl=False, target=target),
    )

    assert len(conflicts) == 1
    assert str(target.symbol_library.path) in conflicts[0]


def test_project_import_report_preserves_destination_metadata(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)

    report = import_shadow_artifacts(
        project,
        shadow,
        "C2040",
        artifacts,
        ImportOptions(step=True, wrl=False),
    )

    assert report.symbol_destination == project / "libs" / "lcsc_project.kicad_sym"
    assert report.footprint_destination == (
        project / "libs" / "lcsc_project.pretty" / "NewPart.kicad_mod"
    )
    assert report.model_directory == project / "libs" / "lcsc_project.3dshapes"
    assert report.footprint_association == "LCSC_Project:NewPart"
