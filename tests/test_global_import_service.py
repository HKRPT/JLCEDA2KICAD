from pathlib import Path

import pytest

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
    assert report.footprint_association is None
