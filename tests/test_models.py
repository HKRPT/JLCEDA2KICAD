from pathlib import Path

from jlceda2kicad.models import (
    ArtifactSet,
    ConflictPolicy,
    ConversionMode,
    ConversionRequest,
    GlobalLibraryCatalog,
    ImportOptions,
    ImportScope,
    ImportTarget,
    LibraryKind,
    LibraryRef,
    ProjectContext,
)
from jlceda2kicad.version import __version__


def test_version_has_single_release_value() -> None:
    assert __version__ == "0.1.0"


def test_project_context_derives_project_library_base(tmp_path: Path) -> None:
    project_file = tmp_path / "中文 项目.kicad_pro"
    context = ProjectContext(
        project_root=tmp_path,
        project_file=project_file,
        board_file=tmp_path / "中文 项目.kicad_pcb",
        kicad_version="10.0.4",
        source="manual",
    )

    assert context.is_valid
    assert context.library_base == tmp_path / "libs" / "lcsc_project"


def test_empty_artifact_set_reports_no_artifacts(tmp_path: Path) -> None:
    artifacts = ArtifactSet(root=tmp_path)

    assert not artifacts.has_any
    assert artifacts.all_files == ()


def test_conversion_request_keeps_modes_and_safe_paths(tmp_path: Path) -> None:
    request = ConversionRequest(
        lcsc_id="C2040",
        modes=(ConversionMode.SYMBOL, ConversionMode.FOOTPRINT),
        output_base=tmp_path / "out" / "lcsc_project",
        working_dir=tmp_path,
        use_cache=True,
        overwrite=False,
        project_relative=True,
    )

    assert request.modes == (ConversionMode.SYMBOL, ConversionMode.FOOTPRINT)
    assert request.output_base.is_absolute()


def test_import_options_default_to_safe_complete_import() -> None:
    options = ImportOptions()

    assert options.symbol and options.footprint and options.step and options.wrl
    assert options.use_cache and options.open_library_dir
    assert options.conflict_policy is ConflictPolicy.CANCEL


def test_global_import_target_derives_model_directory(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    footprint = LibraryRef(
        nickname="Harulib",
        kind=LibraryKind.FOOTPRINT,
        path=tmp_path / "footprints" / "Harulib.pretty",
        table_path=table,
    )
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        footprint_library=footprint,
        symbol_name="鐢靛 22uF",
        footprint_name="C0805-Haru",
    )

    assert target.model_dir == tmp_path / "footprints" / "Harulib.3dshapes"
    assert GlobalLibraryCatalog(footprints=(footprint,)).footprints == (footprint,)


def test_import_options_keep_project_scope_by_default() -> None:
    assert ImportOptions().target == ImportTarget()
    assert ImportOptions().target.scope is ImportScope.PROJECT
