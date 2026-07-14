"""Manifest-based project backup and rollback."""

import hashlib
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ._json_store import write_json_atomic


@dataclass(frozen=True, slots=True)
class BackupRecord:
    relative_path: str
    existed: bool
    size: int = 0
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class BackupManifest:
    backup_dir: Path
    records: tuple[BackupRecord, ...]

    @property
    def manifest_path(self) -> Path:
        return self.backup_dir / "manifest.json"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BackupManager:
    def __init__(self, project_root: Path, retention: int = 5) -> None:
        self.project_root = project_root.resolve()
        self.retention = max(1, retention)
        self.backup_root = self.project_root / ".jlceda2kicad_backup"

    def _relative(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.project_root)
        except ValueError as error:
            raise ValueError(f"backup path is outside project: {path}") from error

    def create(self, paths: tuple[Path, ...]) -> BackupManifest:
        relative_paths = tuple(self._relative(path) for path in paths)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = self.backup_root / stamp
        files_dir = backup_dir / "files"
        records: list[BackupRecord] = []
        for path, relative in zip(paths, relative_paths, strict=True):
            if path.is_file():
                destination = files_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                records.append(
                    BackupRecord(relative.as_posix(), True, path.stat().st_size, _hash(path))
                )
            else:
                records.append(BackupRecord(relative.as_posix(), False))
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest = BackupManifest(backup_dir, tuple(records))
        write_json_atomic(
            manifest.manifest_path,
            {
                "created_at": stamp,
                "project_root": str(self.project_root),
                "records": [asdict(record) for record in records],
            },
        )
        return manifest

    def rollback(self, manifest: BackupManifest) -> tuple[str, ...]:
        errors: list[str] = []
        for record in manifest.records:
            target = self.project_root / Path(record.relative_path)
            try:
                if record.existed:
                    source = manifest.backup_dir / "files" / Path(record.relative_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(f".{target.name}.{os.getpid()}.restore")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as error:
                errors.append(f"{record.relative_path}: {error}")
        return tuple(errors)

    def prune(self) -> tuple[Path, ...]:
        if not self.backup_root.is_dir():
            return ()
        directories = sorted(path for path in self.backup_root.iterdir() if path.is_dir())
        remove_count = max(0, len(directories) - self.retention)
        removed: list[Path] = []
        for path in directories[:remove_count]:
            shutil.rmtree(path)
            removed.append(path)
        return tuple(removed)
