"""Formal shadow conversion planning, validation, and transactional import."""

import shutil
from pathlib import Path

from .backup import BackupManager
from .conflicts import (
    ComponentConflictError,
    extract_symbol_component_library,
    merge_symbol_library,
    resolve_file_conflicts,
)
from .import_transaction import AtomicImportTransaction, ImportTransactionError
from .import_validation import validate_footprint, validate_symbol_library
from .library_tables import build_project_library_table_updates
from .models import (
    ArtifactSet,
    ConflictPolicy,
    ConversionMode,
    ConversionRequest,
    ImportOptions,
    ImportReport,
)
from .output_discovery import discover_artifacts
from .sexpr import rewrite_footprint_models
from .validation import normalize_lcsc_id


class ImportServiceError(RuntimeError):
    """Raised before or during a formal import that cannot be committed."""


def build_formal_requests(
    lcsc_id: str, shadow_root: Path, options: ImportOptions
) -> tuple[ConversionRequest, ...]:
    normalized = normalize_lcsc_id(lcsc_id)
    modes: list[ConversionMode] = []
    if options.symbol:
        modes.append(ConversionMode.SYMBOL)
    if options.footprint:
        modes.append(ConversionMode.FOOTPRINT)
    if options.step or options.wrl:
        modes.append(ConversionMode.MODEL_3D)
    output_base = shadow_root / "libs" / "lcsc_project"
    overwrite = options.conflict_policy is ConflictPolicy.OVERWRITE_COMPONENT
    return tuple(
        ConversionRequest(
            lcsc_id=normalized,
            modes=(mode,),
            output_base=output_base,
            working_dir=shadow_root,
            use_cache=options.use_cache,
            overwrite=overwrite,
            project_relative=True,
        )
        for mode in modes
    )


def _select_by_preview(
    formal_paths: tuple[Path, ...], preview_paths: tuple[Path, ...]
) -> tuple[Path, ...]:
    if not preview_paths:
        return formal_paths
    expected = {path.name.casefold() for path in preview_paths}
    return tuple(path for path in formal_paths if path.name.casefold() in expected)


def _stage_text(staging_root: Path, name: str, text: str) -> Path:
    path = staging_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def import_shadow_artifacts(
    project_root: Path,
    shadow_root: Path,
    lcsc_id: str,
    preview_artifacts: ArtifactSet,
    options: ImportOptions,
    *,
    backup_count: int = 5,
) -> ImportReport:
    """Promote selected formal outputs from a shadow project in one transaction."""

    normalized = normalize_lcsc_id(lcsc_id)
    project_root = project_root.resolve()
    formal = discover_artifacts(shadow_root)
    staging_root = shadow_root / ".jlceda2kicad-commit"
    shutil.rmtree(staging_root, ignore_errors=True)
    mappings: dict[Path, Path] = {}
    warnings = list(formal.warnings)
    registration: list[str] = []
    symbol_validation = None
    footprint_validations = []
    target_symbol = project_root / "libs" / "lcsc_project.kicad_sym"
    target_footprint_dir = project_root / "libs" / "lcsc_project.pretty"
    target_model_dir = project_root / "libs" / "lcsc_project.3dshapes"

    try:
        if options.symbol:
            if not formal.symbol_libraries:
                raise ImportServiceError("正式转换没有生成符号库。")
            formal_symbol = formal.symbol_libraries[0]
            formal_text = formal_symbol.read_text(encoding="utf-8-sig")
            incoming_text = extract_symbol_component_library(formal_text, normalized)
            incoming_stage = _stage_text(staging_root, "incoming.kicad_sym", incoming_text)
            symbol_validation = validate_symbol_library(incoming_stage)
            existing_text = (
                target_symbol.read_text(encoding="utf-8-sig") if target_symbol.is_file() else None
            )
            merge = merge_symbol_library(
                existing_text, incoming_text, normalized, options.conflict_policy
            )
            if merge.skipped:
                warnings.append(f"符号 {normalized} 已存在，已按策略跳过。")
            else:
                merged_stage = _stage_text(staging_root, "libs/lcsc_project.kicad_sym", merge.text)
                validate_symbol_library(merged_stage)
                mappings[merged_stage] = target_symbol

        selected_footprints = (
            _select_by_preview(formal.footprints, preview_artifacts.footprints)
            if options.footprint
            else ()
        )
        if options.footprint and not selected_footprints:
            raise ImportServiceError("正式转换没有生成所选封装。")
        model_mode = "wrl" if options.wrl else "step" if options.step else "none"
        footprint_mappings: dict[Path, Path] = {}
        for footprint in selected_footprints:
            rewritten = rewrite_footprint_models(
                footprint.read_text(encoding="utf-8-sig"), model_mode
            )
            staged = _stage_text(
                staging_root, f"libs/lcsc_project.pretty/{footprint.name}", rewritten
            )
            footprint_validations.append(validate_footprint(staged))
            footprint_mappings[staged] = target_footprint_dir / footprint.name

        model_mappings: dict[Path, Path] = {}
        if options.step:
            selected_steps = _select_by_preview(formal.step_models, preview_artifacts.step_models)
            if not selected_steps:
                warnings.append("正式转换没有生成 STEP 模型。")
            for model in selected_steps:
                model_mappings[model] = target_model_dir / model.with_suffix(".step").name
        if options.wrl:
            selected_wrl = _select_by_preview(formal.wrl_models, preview_artifacts.wrl_models)
            if not selected_wrl:
                warnings.append("正式转换没有生成 WRL 模型。")
            for model in selected_wrl:
                model_mappings[model] = target_model_dir / model.name

        selected_files, skipped_files = resolve_file_conflicts(
            footprint_mappings | model_mappings, options.conflict_policy
        )
        mappings.update(selected_files)
        warnings.extend(f"文件已存在，按策略跳过：{path.name}" for path in skipped_files)

        planned_targets = set(selected_files.values())
        for validation in footprint_validations:
            for model_path in validation.model_paths:
                referenced_target = target_model_dir / Path(model_path).name
                if not referenced_target.is_file() and referenced_target not in planned_targets:
                    raise ImportServiceError(f"模型引用没有对应的可提交文件：{model_path}")

        if symbol_validation is not None:
            for validation in footprint_validations:
                warnings.extend(symbol_validation.compare_pad_numbers(validation))

        register_symbol = options.symbol and (
            target_symbol.is_file() or target_symbol in mappings.values()
        )
        register_footprint = options.footprint and (
            target_footprint_dir.is_dir()
            or any(target.parent == target_footprint_dir for target in mappings.values())
        )
        table_updates, table_result = build_project_library_table_updates(
            project_root,
            register_symbol=register_symbol,
            register_footprint=register_footprint,
        )
        for target, text in table_updates.items():
            staged = _stage_text(staging_root, f"tables/{target.name}", text)
            mappings[staged] = target
        if table_result.symbol_registered:
            registration.append("LCSC_Project (symbol)")
        if table_result.footprint_registered:
            registration.append("LCSC_Project (footprint)")
    except (OSError, ValueError, ComponentConflictError) as error:
        raise ImportServiceError(str(error)) from error

    if not mappings:
        return ImportReport(
            success=True,
            warnings=tuple(warnings) or ("没有需要提交的文件。",),
            library_registration=tuple(registration),
        )
    try:
        committed = AtomicImportTransaction(
            project_root,
            BackupManager(project_root, retention=backup_count),
        ).commit(mappings)
    except ImportTransactionError as error:
        raise ImportServiceError(str(error)) from error
    return ImportReport(
        success=committed.success,
        committed_paths=committed.committed_paths,
        warnings=tuple(warnings),
        library_registration=tuple(registration),
        backup_dir=committed.backup_dir,
        rollback_result=committed.rollback_result,
    )
