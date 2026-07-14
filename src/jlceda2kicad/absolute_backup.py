"""Absolute-path backups for transactions spanning multiple roots."""

import hashlib
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ._json_store import write_json_atomic


@dataclass(frozen=True, slots=True)
class AbsoluteBackupRecord:
    target_path: str
    backup_name: str
    existed: bool
    size: int = 0
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class AbsoluteBackupManifest:
    backup_dir: Path
    records: tuple[AbsoluteBackupRecord, ...]

    @property
    def manifest_path(self) -> Path:
        return self.backup_dir / "manifest.json"


def _payload_name(index: int, target: Path) -> str:
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"{index:04d}-{digest}.bak"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class AbsoluteBackupManager:
    def __init__(self, backup_root: Path, retention: int = 5) -> None:
        self.backup_root = backup_root.resolve()
        self.retention = max(1, retention)

    def create(self, paths: tuple[Path, ...]) -> AbsoluteBackupManifest:
        targets = tuple(dict.fromkeys(path.resolve() for path in paths))
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = self.backup_root / stamp
        files_dir = backup_dir / "files"
        records: list[AbsoluteBackupRecord] = []
        for index, target in enumerate(targets):
            backup_name = _payload_name(index, target)
            if target.is_file():
                files_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, files_dir / backup_name)
                records.append(
                    AbsoluteBackupRecord(
                        str(target), backup_name, True, target.stat().st_size, _hash(target)
                    )
                )
            else:
                records.append(AbsoluteBackupRecord(str(target), backup_name, False))
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest = AbsoluteBackupManifest(backup_dir, tuple(records))
        write_json_atomic(
            manifest.manifest_path,
            {
                "created_at": stamp,
                "records": [asdict(record) for record in records],
            },
        )
        return manifest

    def rollback(self, manifest: AbsoluteBackupManifest) -> tuple[str, ...]:
        errors: list[str] = []
        for record in manifest.records:
            target = Path(record.target_path)
            try:
                if record.existed:
                    source = manifest.backup_dir / "files" / record.backup_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(f".{target.name}.{os.getpid()}.restore")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as error:
                errors.append(f"{target}: {error}")
        return tuple(errors)

    def prune(self) -> tuple[Path, ...]:
        if not self.backup_root.is_dir():
            return ()
        directories = sorted(path for path in self.backup_root.iterdir() if path.is_dir())
        removed: list[Path] = []
        for path in directories[: max(0, len(directories) - self.retention)]:
            shutil.rmtree(path)
            removed.append(path)
        return tuple(removed)
