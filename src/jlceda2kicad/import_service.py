"""Formal shadow conversion planning, validation, and transactional import."""

import shutil
from pathlib import Path

from .absolute_backup import AbsoluteBackupManager
from .artifact_rewrite import (
    rewrite_footprint_component,
    rewrite_symbol_component,
    validate_component_name,
)
from .backup import BackupManager
from .conflicts import (
    ComponentConflictError,
    extract_symbol_component_library,
    merge_symbol_library,
    resolve_file_conflicts,
)
from .global_libraries import build_global_registration
from .import_transaction import (
    AtomicImportTransaction,
    AtomicMultiRootTransaction,
    ImportTransactionError,
)
from .import_validation import ArtifactValidation, validate_footprint, validate_symbol_library
from .library_tables import build_project_library_table_updates
from .models import (
    ArtifactSet,
    ConflictPolicy,
    ConversionMode,
    ConversionRequest,
    ImportOptions,
    ImportReport,
    ImportScope,
    LibraryKind,
    LibraryRef,
)
from .output_discovery import discover_artifacts
from .sexpr import rewrite_footprint_models
from .validation import normalize_lcsc_id


class ImportServiceError(RuntimeError):
    """Raised before or during a formal import that cannot be committed."""

    def __init__(self, message: str, report: ImportReport | None = None) -> None:
        super().__init__(message)
        self.report = report or ImportReport(success=False)


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


def find_import_conflicts(
    project_root: Path,
    artifacts: ArtifactSet,
    lcsc_id: str,
    options: ImportOptions,
) -> tuple[str, ...]:
    """Report conflicts that would be handled by the selected import policy."""

    normalized = normalize_lcsc_id(lcsc_id)
    if options.target.scope is ImportScope.GLOBAL:
        return tuple(_global_conflicts(artifacts, normalized, options))
    return tuple(_project_conflicts(project_root.resolve(), artifacts, normalized))


def _project_conflicts(
    project_root: Path, artifacts: ArtifactSet, lcsc_id: str
) -> list[str]:
    conflicts: list[str] = []
    symbol_target = project_root / "libs" / "lcsc_project.kicad_sym"
    if artifacts.symbol_libraries and symbol_target.is_file():
        try:
            merge_symbol_library(
                symbol_target.read_text(encoding="utf-8-sig"),
                artifacts.symbol_libraries[0].read_text(encoding="utf-8-sig"),
                lcsc_id,
                ConflictPolicy.CANCEL,
            )
        except ComponentConflictError as error:
            conflicts.append(str(error))
        except (OSError, UnicodeError, ValueError) as error:
            conflicts.append(f"{symbol_target}: cannot be safely checked: {error}")
    for path, directory in (
        *((path, "lcsc_project.pretty") for path in artifacts.footprints),
        *((path, "lcsc_project.3dshapes") for path in artifacts.step_models),
        *((path, "lcsc_project.3dshapes") for path in artifacts.wrl_models),
    ):
        target = project_root / "libs" / directory / path.name
        try:
            if target.exists():
                conflicts.append(path.name)
        except OSError as error:
            conflicts.append(f"{target}: cannot be safely checked: {error}")
    return conflicts


def _global_conflicts(
    artifacts: ArtifactSet, lcsc_id: str, options: ImportOptions
) -> list[str]:
    target = options.target
    conflicts: list[str] = []
    if options.symbol and target.symbol_library and target.symbol_name:
        existing = target.symbol_library.path
        try:
            if existing.exists() and not existing.is_file():
                raise OSError("symbol library target is not a regular file")
            if existing.is_file() and artifacts.symbol_libraries:
                incoming = extract_symbol_component_library(
                    artifacts.symbol_libraries[0].read_text(encoding="utf-8-sig"), lcsc_id
                )
                incoming = rewrite_symbol_component(
                    incoming, lcsc_id, target.symbol_name, None
                )
                merge_symbol_library(
                    existing.read_text(encoding="utf-8-sig"),
                    incoming,
                    lcsc_id,
                    ConflictPolicy.CANCEL,
                )
        except ComponentConflictError as error:
            conflicts.append(str(error))
        except (OSError, UnicodeError, ValueError) as error:
            conflicts.append(f"{existing}: cannot be safely checked: {error}")
    if options.footprint and target.footprint_library and target.footprint_name:
        path = target.footprint_library.path / f"{target.footprint_name}.kicad_mod"
        try:
            if path.exists():
                conflicts.append(str(path))
        except OSError as error:
            conflicts.append(f"{path}: cannot be safely checked: {error}")
    if target.model_dir is not None:
        selected_models = (
            (artifacts.step_models if options.step else ())
            + (artifacts.wrl_models if options.wrl else ())
        )
        for model in selected_models:
            name = (
                model.with_suffix(".step").name
                if model.suffix.lower() == ".stp"
                else model.name
            )
            destination = target.model_dir / name
            try:
                if destination.exists():
                    conflicts.append(str(destination))
            except OSError as error:
                conflicts.append(f"{destination}: cannot be safely checked: {error}")
    return conflicts


def _required_library(options: ImportOptions, kind: LibraryKind) -> LibraryRef:
    reference = (
        options.target.symbol_library
        if kind is LibraryKind.SYMBOL
        else options.target.footprint_library
    )
    if reference is None or reference.kind is not kind:
        raise ImportServiceError(f"Global {kind.value} library is not selected")
    return reference


def _required_name(value: str | None, label: str) -> str:
    if value is None:
        raise ImportServiceError(f"Global {label} name is not set")
    try:
        return validate_component_name(value, label)
    except ValueError as error:
        raise ImportServiceError(str(error)) from error


def _validate_models_only_library(reference: LibraryRef) -> None:
    if not reference.registered:
        raise ImportServiceError(
            "Global models-only import requires an existing registered footprint library: "
            f"{reference.path}"
        )
    try:
        registration_updates = build_global_registration(reference)
    except (OSError, UnicodeError, ValueError) as error:
        raise ImportServiceError(str(error)) from error
    if registration_updates:
        raise ImportServiceError(
            "Global models-only import requires an existing registered footprint library: "
            f"{reference.path}"
        )


def _import_global_shadow_artifacts(
    shadow_root: Path,
    lcsc_id: str,
    preview_artifacts: ArtifactSet,
    options: ImportOptions,
    *,
    backup_count: int,
    global_backup_root: Path | None,
) -> ImportReport:
    if global_backup_root is None:
        raise ImportServiceError("Global import backup root is not configured")
    normalized = normalize_lcsc_id(lcsc_id)
    symbol_ref = _required_library(options, LibraryKind.SYMBOL) if options.symbol else None
    needs_footprint_library = options.footprint or options.step or options.wrl
    footprint_ref = (
        _required_library(options, LibraryKind.FOOTPRINT)
        if needs_footprint_library
        else None
    )
    if not options.footprint and (options.step or options.wrl) and footprint_ref:
        _validate_models_only_library(footprint_ref)
    symbol_name = _required_name(options.target.symbol_name, "symbol") if options.symbol else None
    footprint_name = (
        _required_name(options.target.footprint_name, "footprint")
        if options.footprint
        else None
    )
    model_dir = footprint_ref.path.with_suffix(".3dshapes") if footprint_ref else None
    association = (
        f"{footprint_ref.nickname}:{footprint_name}"
        if options.symbol and options.footprint and footprint_ref and footprint_name
        else None
    )
    effective_association = association
    formal = discover_artifacts(shadow_root)
    staging_root = shadow_root / ".jlceda2kicad-global-commit"
    shutil.rmtree(staging_root, ignore_errors=True)
    mappings: dict[Path, Path] = {}
    warnings = list(formal.warnings)
    if options.symbol and not options.footprint:
        warnings.append("符号原有封装关联未在所选全局目标中验证。")
    registration: list[str] = []
    symbol_validation = None
    footprint_validations: list[ArtifactValidation] = []
    try:
        if options.symbol and symbol_ref and symbol_name:
            if not formal.symbol_libraries:
                raise ImportServiceError("正式转换没有生成符号库。")
            incoming = extract_symbol_component_library(
                formal.symbol_libraries[0].read_text(encoding="utf-8-sig"), normalized
            )
            incoming = rewrite_symbol_component(incoming, normalized, symbol_name, association)
            incoming_stage = _stage_text(staging_root, "incoming.kicad_sym", incoming)
            symbol_validation = validate_symbol_library(incoming_stage)
            existing = (
                symbol_ref.path.read_text(encoding="utf-8-sig")
                if symbol_ref.path.is_file()
                else None
            )
            merge = merge_symbol_library(
                existing, incoming, normalized, options.conflict_policy
            )
            if merge.skipped:
                warnings.append(f"符号 {symbol_name} 已存在，已按策略跳过。")
                if association is not None:
                    effective_association = None
                    warnings.append("符号未提交，因此封装关联未应用。")
            else:
                merged_stage = _stage_text(
                    staging_root, f"symbols/{symbol_ref.path.name}", merge.text
                )
                validate_symbol_library(merged_stage)
                mappings[merged_stage] = symbol_ref.path

        selected_footprints = (
            _select_by_preview(formal.footprints, preview_artifacts.footprints)
            if options.footprint
            else ()
        )
        if options.footprint and len(selected_footprints) != 1:
            raise ImportServiceError(
                f"全局自定义名称要求一个封装，实际发现 {len(selected_footprints)} 个。"
            )
        model_mode = "wrl" if options.wrl else "step" if options.step else "none"
        footprint_mappings: dict[Path, Path] = {}
        if selected_footprints and footprint_ref and footprint_name and model_dir:
            source = selected_footprints[0]
            rewritten = rewrite_footprint_component(
                source.read_text(encoding="utf-8-sig"),
                footprint_name,
                model_mode=model_mode,
                model_dir=model_dir,
            )
            staged = _stage_text(
                staging_root,
                f"footprints/{footprint_name}.kicad_mod",
                rewritten,
            )
            footprint_validations.append(validate_footprint(staged, model_root=model_dir))
            footprint_mappings[staged] = footprint_ref.path / f"{footprint_name}.kicad_mod"

        model_mappings: dict[Path, Path] = {}
        if options.step and model_dir:
            selected_steps = _select_by_preview(
                formal.step_models, preview_artifacts.step_models
            )
            if not selected_steps:
                warnings.append("正式转换没有生成 STEP 模型。")
            for model in selected_steps:
                model_mappings[model] = model_dir / model.with_suffix(".step").name
        if options.wrl and model_dir:
            selected_wrl = _select_by_preview(formal.wrl_models, preview_artifacts.wrl_models)
            if not selected_wrl:
                warnings.append("正式转换没有生成 WRL 模型。")
            for model in selected_wrl:
                model_mappings[model] = model_dir / model.name

        selected_files, skipped_files = resolve_file_conflicts(
            footprint_mappings | model_mappings, options.conflict_policy
        )
        mappings.update(selected_files)
        warnings.extend(f"文件已存在，按策略跳过：{path.name}" for path in skipped_files)
        planned_targets = {path.resolve() for path in selected_files.values()}
        for validation in footprint_validations:
            for model_path in validation.model_paths:
                target_path = Path(model_path).resolve()
                if not target_path.is_file() and target_path not in planned_targets:
                    raise ImportServiceError(f"模型引用没有对应的可提交文件：{model_path}")
        if symbol_validation is not None:
            for validation in footprint_validations:
                warnings.extend(symbol_validation.compare_pad_numbers(validation))

        registration_updates: dict[Path, str] = {}
        if symbol_ref and (symbol_ref.path.is_file() or symbol_ref.path in mappings.values()):
            updates = build_global_registration(symbol_ref)
            registration_updates.update(updates)
            if updates:
                registration.append(f"{symbol_ref.nickname} (symbol)")
        if footprint_ref and (
            footprint_ref.path.is_dir()
            or any(target.parent == footprint_ref.path for target in mappings.values())
        ):
            updates = build_global_registration(footprint_ref)
            registration_updates.update(updates)
            if updates:
                registration.append(f"{footprint_ref.nickname} (footprint)")
        for table_path, table_text in registration_updates.items():
            staged = _stage_text(staging_root, f"tables/{table_path.name}", table_text)
            mappings[staged] = table_path
    except (OSError, UnicodeError, ValueError, ComponentConflictError) as error:
        raise ImportServiceError(str(error)) from error

    symbol_destination = symbol_ref.path if symbol_ref and symbol_name else None
    footprint_destination = (
        footprint_ref.path / f"{footprint_name}.kicad_mod"
        if footprint_ref and footprint_name
        else None
    )
    if not mappings:
        return ImportReport(
            success=True,
            warnings=tuple(warnings) or ("没有需要提交的文件。",),
            library_registration=tuple(registration),
            symbol_destination=symbol_destination,
            footprint_destination=footprint_destination,
            model_directory=model_dir,
            footprint_association=effective_association,
        )
    allowed_roots = tuple(
        dict.fromkeys(
            path.resolve()
            for path in (
                symbol_ref.path.parent if symbol_ref else None,
                footprint_ref.path if footprint_ref else None,
                model_dir,
            )
            if path is not None
        )
    )
    allowed_files = tuple(path.resolve() for path in registration_updates)
    try:
        committed = AtomicMultiRootTransaction(
            AbsoluteBackupManager(global_backup_root, retention=backup_count),
            allowed_roots=allowed_roots,
            allowed_files=allowed_files,
        ).commit(mappings)
    except ImportTransactionError as error:
        raise ImportServiceError(str(error), error.report) from error
    return ImportReport(
        success=committed.success,
        committed_paths=committed.committed_paths,
        warnings=tuple(warnings) + committed.warnings,
        library_registration=tuple(registration),
        backup_dir=committed.backup_dir,
        rollback_result=committed.rollback_result,
        symbol_destination=symbol_destination,
        footprint_destination=footprint_destination,
        model_directory=model_dir,
        footprint_association=effective_association,
    )


def import_shadow_artifacts(
    project_root: Path,
    shadow_root: Path,
    lcsc_id: str,
    preview_artifacts: ArtifactSet,
    options: ImportOptions,
    *,
    backup_count: int = 5,
    global_backup_root: Path | None = None,
) -> ImportReport:
    """Promote selected formal outputs from a shadow project in one transaction."""

    if options.target.scope is ImportScope.GLOBAL:
        return _import_global_shadow_artifacts(
            shadow_root,
            lcsc_id,
            preview_artifacts,
            options,
            backup_count=backup_count,
            global_backup_root=global_backup_root,
        )

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

    project_footprint_destination = next(
        (
            target
            for target in mappings.values()
            if target.suffix.casefold() == ".kicad_mod"
        ),
        None,
    )
    project_symbol_destination = (
        target_symbol
        if options.symbol and (target_symbol.is_file() or target_symbol in mappings.values())
        else None
    )
    if not mappings:
        return ImportReport(
            success=True,
            warnings=tuple(warnings) or ("没有需要提交的文件。",),
            library_registration=tuple(registration),
            symbol_destination=project_symbol_destination,
            footprint_destination=project_footprint_destination,
            model_directory=target_model_dir if options.step or options.wrl else None,
        )
    try:
        committed = AtomicImportTransaction(
            project_root,
            BackupManager(project_root, retention=backup_count),
        ).commit(mappings)
    except ImportTransactionError as error:
        raise ImportServiceError(str(error), error.report) from error
    return ImportReport(
        success=committed.success,
        committed_paths=committed.committed_paths,
        warnings=tuple(warnings),
        library_registration=tuple(registration),
        backup_dir=committed.backup_dir,
        rollback_result=committed.rollback_result,
        symbol_destination=project_symbol_destination,
        footprint_destination=project_footprint_destination,
        model_directory=target_model_dir if options.step or options.wrl else None,
    )
