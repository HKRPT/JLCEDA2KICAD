"""Shadow-project preparation and atomic promotion into a real project."""

import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from .absolute_backup import AbsoluteBackupManager
from .backup import BackupManager
from .models import ImportReport


class ImportTransactionError(RuntimeError):
    def __init__(self, message: str, report: ImportReport | None = None) -> None:
        super().__init__(message)
        self.report = report or ImportReport(success=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_allowed_target(
    path: Path, allowed_roots: tuple[Path, ...], allowed_files: tuple[Path, ...]
) -> bool:
    resolved = path.resolve()
    if any(resolved == item.resolve() for item in allowed_files):
        return True
    return any(_is_within(resolved, root) for root in allowed_roots)


class AtomicImportTransaction:
    def __init__(
        self,
        project_root: Path,
        backup_manager: BackupManager,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.project_root = project_root.resolve()
        self.backup_manager = backup_manager
        self.replace = replace

    def commit(self, staged_to_target: Mapping[Path, Path]) -> ImportReport:
        if not staged_to_target:
            raise ImportTransactionError("没有可提交的文件。")
        for staged, target in staged_to_target.items():
            if not staged.is_file() or staged.stat().st_size == 0:
                raise ImportTransactionError(f"暂存输出是空文件或不存在：{staged}")
            if not _is_within(target, self.project_root):
                raise ImportTransactionError(f"目标位于工程之外：{target}")

        targets = tuple(staged_to_target.values())
        manifest = self.backup_manager.create(targets)
        committed: list[Path] = []
        temporaries: list[Path] = []
        try:
            for staged, target in staged_to_target.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                temporaries.append(temporary)
                with staged.open("rb") as source, temporary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                self.replace(temporary, target)
                committed.append(target)
        except OSError as error:
            rollback_result = self.backup_manager.rollback(manifest)
            report = ImportReport(
                success=False,
                committed_paths=tuple(committed),
                backup_dir=manifest.backup_dir,
                rollback_result=rollback_result,
            )
            raise ImportTransactionError(f"导入提交失败：{error}", report) from error
        finally:
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)

        self.backup_manager.prune()
        return ImportReport(
            success=True,
            committed_paths=tuple(committed),
            backup_dir=manifest.backup_dir,
        )


class AtomicMultiRootTransaction:
    def __init__(
        self,
        backup_manager: AbsoluteBackupManager,
        *,
        allowed_roots: tuple[Path, ...],
        allowed_files: tuple[Path, ...] = (),
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.backup_manager = backup_manager
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self.allowed_files = tuple(path.resolve() for path in allowed_files)
        self.replace = replace

    def commit(self, staged_to_target: Mapping[Path, Path]) -> ImportReport:
        if not staged_to_target:
            raise ImportTransactionError("No files to commit.")
        for staged, target in staged_to_target.items():
            if not staged.is_file() or staged.stat().st_size == 0:
                raise ImportTransactionError(f"Staged output is empty or missing: {staged}")
            if not _is_allowed_target(target, self.allowed_roots, self.allowed_files):
                raise ImportTransactionError(f"Target is not in an allowlisted path: {target}")

        targets = tuple(staged_to_target.values())
        manifest = self.backup_manager.create(targets)
        committed: list[Path] = []
        temporaries: list[Path] = []
        try:
            for staged, target in staged_to_target.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                temporaries.append(temporary)
                with staged.open("rb") as source, temporary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                self.replace(temporary, target)
                committed.append(target)
        except OSError as error:
            rollback_result = self.backup_manager.rollback(manifest)
            report = ImportReport(
                success=False,
                committed_paths=tuple(committed),
                backup_dir=manifest.backup_dir,
                rollback_result=rollback_result,
            )
            raise ImportTransactionError(f"Global import commit failed: {error}", report) from error
        finally:
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)

        self.backup_manager.prune()
        return ImportReport(
            success=True,
            committed_paths=tuple(committed),
            backup_dir=manifest.backup_dir,
        )


def prepare_shadow_project(project_root: Path, shadow_root: Path) -> Path:
    """Seed only the managed library tree into a clean shadow project."""

    source_libs = project_root / "libs"
    target_libs = shadow_root / "libs"
    target_libs.mkdir(parents=True, exist_ok=True)
    symbol = source_libs / "lcsc_project.kicad_sym"
    if symbol.is_file():
        shutil.copy2(symbol, target_libs / symbol.name)
    for directory_name in ("lcsc_project.pretty", "lcsc_project.3dshapes"):
        source = source_libs / directory_name
        if source.is_dir():
            shutil.copytree(source, target_libs / directory_name, dirs_exist_ok=True)
    for table_name in ("sym-lib-table", "fp-lib-table"):
        source = project_root / table_name
        if source.is_file():
            shutil.copy2(source, shadow_root / table_name)
    return target_libs / "lcsc_project"
