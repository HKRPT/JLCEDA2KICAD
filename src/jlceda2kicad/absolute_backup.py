"""Absolute-path backups for transactions spanning multiple roots."""

import hashlib
import os
import shutil
import stat
import uuid
from contextlib import suppress
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
    digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:16]
    return f"{index:04d}-{digest}.bak"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_and_fsync(source: Path, destination: Path) -> None:
    with source.open("rb") as source_stream, destination.open("wb") as destination_stream:
        shutil.copyfileobj(source_stream, destination_stream)
        destination_stream.flush()
        os.fsync(destination_stream.fileno())


def _validate_target(path: Path) -> bool:
    if not path.is_absolute():
        raise ValueError("Absolute backups require absolute target paths.")
    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(status, "st_file_attributes", 0)
    if stat.S_ISLNK(status.st_mode) or bool(file_attributes & reparse_flag):
        raise OSError(f"Backup target cannot be a link or reparse point: {path}")
    if not stat.S_ISREG(status.st_mode):
        raise OSError(f"Backup target must be a regular file or missing: {path}")
    return True


class AbsoluteBackupManager:
    def __init__(self, backup_root: Path, retention: int = 5) -> None:
        self.backup_root = backup_root.resolve()
        self.retention = max(1, retention)

    def create(self, paths: tuple[Path, ...]) -> AbsoluteBackupManifest:
        targets = tuple(dict.fromkeys(paths))
        existed = tuple(_validate_target(target) for target in targets)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        while True:
            unique_name = f"{stamp}-{uuid.uuid4().hex}"
            backup_dir = self.backup_root / unique_name
            incomplete_dir = self.backup_root / f".{unique_name}.incomplete"
            try:
                incomplete_dir.mkdir()
            except FileExistsError:
                continue
            if backup_dir.exists():
                incomplete_dir.rmdir()
                continue
            break

        try:
            files_dir = incomplete_dir / "files"
            records: list[AbsoluteBackupRecord] = []
            for index, (target, target_existed) in enumerate(
                zip(targets, existed, strict=True)
            ):
                backup_name = _payload_name(index, target)
                if target_existed:
                    files_dir.mkdir(parents=True, exist_ok=True)
                    payload = files_dir / backup_name
                    _copy_and_fsync(target, payload)
                    shutil.copystat(target, payload)
                    payload_status = payload.stat()
                    records.append(
                        AbsoluteBackupRecord(
                            str(target),
                            backup_name,
                            True,
                            payload_status.st_size,
                            _hash(payload),
                        )
                    )
                else:
                    records.append(AbsoluteBackupRecord(str(target), backup_name, False))
            write_json_atomic(
                incomplete_dir / "manifest.json",
                {
                    "created_at": stamp,
                    "records": [asdict(record) for record in records],
                },
            )
            os.replace(incomplete_dir, backup_dir)
        except Exception:
            with suppress(OSError):
                shutil.rmtree(incomplete_dir)
            raise
        return AbsoluteBackupManifest(backup_dir, tuple(records))

    def rollback(self, manifest: AbsoluteBackupManifest) -> tuple[str, ...]:
        errors: list[str] = []
        for record in manifest.records:
            target = Path(record.target_path)
            temporary: Path | None = None
            try:
                if record.existed:
                    source = manifest.backup_dir / "files" / record.backup_name
                    if not _validate_target(source):
                        raise OSError(f"Backup payload is missing: {source}")
                    source_status = source.stat()
                    source_hash = _hash(source)
                    if source_status.st_size != record.size or source_hash != record.sha256:
                        raise OSError(f"Backup payload size or hash mismatch: {source}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(
                        f".{target.name}.{uuid.uuid4().hex}.restore"
                    )
                    _copy_and_fsync(source, temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as error:
                errors.append(f"{target}: {error}")
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as error:
                        errors.append(f"{temporary}: cleanup failed: {error}")
        return tuple(errors)

    def prune(self) -> tuple[Path, ...]:
        if not self.backup_root.is_dir():
            return ()
        directories = sorted(
            path
            for path in self.backup_root.iterdir()
            if path.is_dir() and not path.name.endswith(".incomplete")
        )
        removed: list[Path] = []
        for path in directories[: max(0, len(directories) - self.retention)]:
            shutil.rmtree(path)
            removed.append(path)
        return tuple(removed)
