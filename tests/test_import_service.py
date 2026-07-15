from pathlib import Path

import pytest

from jlceda2kicad.import_service import (
    ImportServiceError,
    build_formal_requests,
    import_shadow_artifacts,
)
from jlceda2kicad.models import (
    ArtifactSet,
    ConflictPolicy,
    ConversionMode,
    ImportOptions,
)


def test_formal_requests_are_separate_and_shadow_relative(tmp_path: Path) -> None:
    shadow = tmp_path / "影子 工程"
    options = ImportOptions(symbol=True, footprint=True, step=True, wrl=True)

    requests = build_formal_requests("C2040", shadow, options)

    assert [request.modes for request in requests] == [
        (ConversionMode.SYMBOL,),
        (ConversionMode.FOOTPRINT,),
        (ConversionMode.MODEL_3D,),
    ]
    assert all(request.working_dir == shadow for request in requests)
    assert all(request.output_base == shadow / "libs" / "lcsc_project" for request in requests)
    assert all(request.project_relative for request in requests)


def _write_shadow_artifacts(shadow: Path) -> ArtifactSet:
    libs = shadow / "libs"
    pretty = libs / "lcsc_project.pretty"
    models = libs / "lcsc_project.3dshapes"
    pretty.mkdir(parents=True)
    models.mkdir()
    symbol = libs / "lcsc_project.kicad_sym"
    symbol.write_text(
        """(kicad_symbol_lib
  (version 20231120)
  (symbol "Existing" (property "LCSC Part" "C1"))
  (symbol "NewPart" (property "LCSC Part" "C2040")
    (property "Footprint" "lcsc_project:NewPart")
    (symbol "NewPart_1_1"
      (pin passive line (at 0 0 0) (length 2.54) (name "A") (number "1"))))
)""",
        encoding="utf-8",
    )
    footprint = pretty / "NewPart.kicad_mod"
    footprint.write_text(
        """(footprint "NewPart"
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (model "${KIPRJMOD}/libs/lcsc_project.3dshapes/NewPart.wrl"))""",
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


def test_import_shadow_commits_component_tables_and_step_only_reference(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "libs").mkdir(parents=True)
    (project / "libs" / "lcsc_project.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Existing" (property "LCSC Part" "C1")))',
        encoding="utf-8",
    )
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)
    preview = ArtifactSet(
        tmp_path / "preview",
        symbol_libraries=formal.symbol_libraries,
        footprints=formal.footprints,
        step_models=formal.step_models,
        wrl_models=formal.wrl_models,
    )
    options = ImportOptions(step=True, wrl=False, open_library_dir=False)

    report = import_shadow_artifacts(project, shadow, "C2040", preview, options)

    assert report.success
    symbol_text = (project / "libs" / "lcsc_project.kicad_sym").read_text(encoding="utf-8")
    footprint_text = (project / "libs" / "lcsc_project.pretty" / "NewPart.kicad_mod").read_text(
        encoding="utf-8"
    )
    assert 'symbol "Existing"' in symbol_text and 'symbol "NewPart"' in symbol_text
    assert 'property "Footprint" "LCSC_Project:NewPart"' in symbol_text
    assert "NewPart.step" in footprint_text and "NewPart.wrl" not in footprint_text
    assert (project / "libs" / "lcsc_project.3dshapes" / "NewPart.step").is_file()
    assert not (project / "libs" / "lcsc_project.3dshapes" / "NewPart.wrl").exists()
    assert (project / "sym-lib-table").is_file()
    assert (project / "fp-lib-table").is_file()
    assert set(report.library_registration) == {"LCSC_Project (symbol)", "LCSC_Project (footprint)"}
    assert report.footprint_association == "LCSC_Project:NewPart"


def test_import_shadow_accepts_easyeda_legacy_module(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)
    footprint = formal.footprints[0]
    footprint.write_text(
        footprint.read_text(encoding="utf-8").replace(
            '(footprint "NewPart"', "(module easyeda2kicad:NewPart", 1
        ),
        encoding="utf-8",
    )

    report = import_shadow_artifacts(
        project,
        shadow,
        "C2040",
        formal,
        ImportOptions(step=False, wrl=True),
    )

    assert report.success
    imported = project / "libs" / "lcsc_project.pretty" / "NewPart.kicad_mod"
    assert imported.read_text(encoding="utf-8").startswith('(footprint "NewPart"')


def test_skip_policy_skips_colliding_footprint_but_imports_missing_model(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    target_footprint = project / "libs" / "lcsc_project.pretty" / "NewPart.kicad_mod"
    target_footprint.parent.mkdir(parents=True)
    target_footprint.write_text("original footprint", encoding="utf-8")
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)
    options = ImportOptions(
        step=True,
        wrl=False,
        conflict_policy=ConflictPolicy.SKIP_EXISTING,
    )

    report = import_shadow_artifacts(project, shadow, "C2040", formal, options)

    assert report.success
    assert target_footprint.read_text(encoding="utf-8") == "original footprint"
    assert (project / "libs" / "lcsc_project.3dshapes" / "NewPart.step").is_file()
    assert any("跳过" in warning and "NewPart.kicad_mod" in warning for warning in report.warnings)


def test_corrupt_library_table_aborts_before_any_project_file_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    table = project / "sym-lib-table"
    table.write_text("(sym_lib_table (broken)", encoding="utf-8")
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)

    with pytest.raises(ImportServiceError, match="损坏"):
        import_shadow_artifacts(project, shadow, "C2040", formal, ImportOptions())

    assert table.read_text(encoding="utf-8") == "(sym_lib_table (broken)"
    assert not (project / ".jlceda2kicad_backup").exists()


def test_model_only_import_does_not_register_missing_component_libraries(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)
    options = ImportOptions(symbol=False, footprint=False, step=True, wrl=False)

    report = import_shadow_artifacts(project, shadow, "C2040", formal, options)

    assert report.success
    assert (project / "libs" / "lcsc_project.3dshapes" / "NewPart.step").is_file()
    assert not (project / "sym-lib-table").exists()
    assert not (project / "fp-lib-table").exists()
    assert report.library_registration == ()


def test_import_refuses_footprint_with_missing_selected_model(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)
    formal.wrl_models[0].unlink()
    options = ImportOptions(step=False, wrl=True)

    with pytest.raises(ImportServiceError, match="模型引用"):
        import_shadow_artifacts(project, shadow, "C2040", formal, options)

    assert not (project / ".jlceda2kicad_backup").exists()


def test_stp_model_is_promoted_as_step_to_match_rewritten_reference(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shadow = tmp_path / "shadow"
    formal = _write_shadow_artifacts(shadow)
    stp = formal.step_models[0].with_suffix(".stp")
    formal.step_models[0].rename(stp)
    preview = ArtifactSet(
        formal.root,
        symbol_libraries=formal.symbol_libraries,
        footprints=formal.footprints,
        step_models=(stp,),
        wrl_models=formal.wrl_models,
    )

    report = import_shadow_artifacts(
        project,
        shadow,
        "C2040",
        preview,
        ImportOptions(step=True, wrl=False),
    )

    assert report.success
    assert (project / "libs" / "lcsc_project.3dshapes" / "NewPart.step").is_file()
    assert not (project / "libs" / "lcsc_project.3dshapes" / "NewPart.stp").exists()
