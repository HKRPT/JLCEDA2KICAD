import hashlib
import os
from pathlib import Path

import pytest

from jlceda2kicad.absolute_backup import AbsoluteBackupManager


def test_absolute_backup_hashes_and_restores_multiple_roots(tmp_path: Path) -> None:
    first = tmp_path / "Roaming" / "sym-lib-table"
    second = tmp_path / "Documents" / "Harulib.kicad_sym"
    created = tmp_path / "Documents" / "Harulib.pretty" / "New.kicad_mod"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("table", encoding="utf-8")
    second.write_text("symbols", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "app-data" / "backups", retention=5)

    manifest = manager.create((first, second, created))

    assert manifest.manifest_path.is_file()
    assert manifest.records[0].sha256 == hashlib.sha256(b"table").hexdigest()
    first.write_text("changed", encoding="utf-8")
    created.parent.mkdir(parents=True)
    created.write_text("partial", encoding="utf-8")
    assert manager.rollback(manifest) == ()
    assert first.read_text(encoding="utf-8") == "table"
    assert not created.exists()


def test_absolute_backup_prune_keeps_newest_five(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    manager = AbsoluteBackupManager(root, retention=5)
    for index in range(7):
        (root / f"20260715T00000{index}000000Z").mkdir(parents=True)

    removed = manager.prune()

    assert [path.name for path in removed] == [
        "20260715T000000000000Z",
        "20260715T000001000000Z",
    ]
    assert len(tuple(root.iterdir())) == 5


def test_absolute_backup_rejects_relative_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = Path("target")
    monkeypatch.chdir(tmp_path)
    relative.write_text("data", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "backups")

    with pytest.raises(ValueError, match="absolute"):
        manager.create((relative,))

    assert not manager.backup_root.exists()


def test_absolute_backup_rejects_existing_directory_before_creating_backup(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    manager = AbsoluteBackupManager(tmp_path / "backups")

    with pytest.raises(OSError, match="regular file"):
        manager.create((target,))

    assert not manager.backup_root.exists()


def test_absolute_backup_records_and_fsyncs_actual_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    manager = AbsoluteBackupManager(tmp_path / "backups")
    fsynced: list[int] = []
    original_fsync = os.fsync

    def track_fsync(file_descriptor: int) -> None:
        fsynced.append(file_descriptor)
        original_fsync(file_descriptor)

    monkeypatch.setattr("jlceda2kicad.absolute_backup.os.fsync", track_fsync)

    manifest = manager.create((target,))

    record = manifest.records[0]
    payload = manifest.backup_dir / "files" / record.backup_name
    payload_bytes = payload.read_bytes()
    assert record.size == len(payload_bytes)
    assert record.sha256 == hashlib.sha256(payload_bytes).hexdigest()
    assert len(fsynced) >= 2


def test_absolute_backup_refuses_corrupt_payload_without_changing_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"original")
    manager = AbsoluteBackupManager(tmp_path / "backups")
    manifest = manager.create((target,))
    record = manifest.records[0]
    payload = manifest.backup_dir / "files" / record.backup_name
    payload.write_bytes(b"corrupt!")
    target.write_bytes(b"changed!")

    errors = manager.rollback(manifest)

    assert any("hash" in error or "checksum" in error for error in errors)
    assert target.read_bytes() == b"changed!"
    assert not tuple(target.parent.glob(f".{target.name}.*.restore"))


def test_absolute_backup_fsyncs_restore_and_cleans_temporary_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"original")
    manager = AbsoluteBackupManager(tmp_path / "backups")
    manifest = manager.create((target,))
    target.write_bytes(b"changed!")
    fsynced: list[int] = []
    original_fsync = os.fsync

    def track_fsync(file_descriptor: int) -> None:
        fsynced.append(file_descriptor)
        original_fsync(file_descriptor)

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError(f"locked: {source} -> {destination}")

    monkeypatch.setattr("jlceda2kicad.absolute_backup.os.fsync", track_fsync)
    monkeypatch.setattr("jlceda2kicad.absolute_backup.os.replace", fail_replace)

    errors = manager.rollback(manifest)

    assert errors
    assert fsynced
    assert target.read_bytes() == b"changed!"
    assert not tuple(target.parent.glob(f".{target.name}.*.restore"))


def test_absolute_backup_uses_unique_final_directories_for_same_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_text("data", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "backups")

    class FrozenNow:
        def strftime(self, format_string: str) -> str:
            assert format_string
            return "20260715T000000000000Z"

    class FrozenDateTime:
        @classmethod
        def now(cls, timezone: object) -> FrozenNow:
            assert timezone
            return FrozenNow()

    monkeypatch.setattr("jlceda2kicad.absolute_backup.datetime", FrozenDateTime)

    first = manager.create((target,))
    second = manager.create((target,))

    assert first.backup_dir != second.backup_dir
    assert first.manifest_path.is_file()
    assert second.manifest_path.is_file()
    assert not tuple(manager.backup_root.glob("*.incomplete"))


def test_absolute_backup_cleans_incomplete_directory_when_create_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_text("data", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "backups")

    def fail_manifest(path: Path, data: object) -> None:
        raise PermissionError(f"manifest locked: {path}")

    monkeypatch.setattr("jlceda2kicad.absolute_backup.write_json_atomic", fail_manifest)

    with pytest.raises(PermissionError, match="manifest locked"):
        manager.create((target,))

    assert not manager.backup_root.exists() or not tuple(manager.backup_root.iterdir())


def test_absolute_backup_prune_excludes_incomplete_directories(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    manager = AbsoluteBackupManager(root, retention=5)
    for index in range(7):
        (root / f"20260715T00000{index}000000Z").mkdir(parents=True)
    incomplete = root / ".20260715T000007000000Z-deadbeef.incomplete"
    incomplete.mkdir()

    removed = manager.prune()

    assert [path.name for path in removed] == [
        "20260715T000000000000Z",
        "20260715T000001000000Z",
    ]
    assert incomplete.is_dir()
    assert len(tuple(path for path in root.iterdir() if not path.name.endswith(".incomplete"))) == 5
