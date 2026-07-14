import hashlib
from pathlib import Path

import pytest

from jlceda2kicad.backup import BackupManager


def test_backup_manifest_and_rollback_restore_existing_and_remove_new_files(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "libs" / "lcsc_project.kicad_sym"
    new_file = tmp_path / "libs" / "lcsc_project.pretty" / "demo.kicad_mod"
    existing.parent.mkdir(parents=True)
    existing.write_text("original", encoding="utf-8")
    manager = BackupManager(tmp_path, retention=5)

    manifest = manager.create((existing, new_file))

    assert manifest.manifest_path.is_file()
    existing_record = next(record for record in manifest.records if record.relative_path.endswith("kicad_sym"))
    assert existing_record.sha256 == hashlib.sha256(b"original").hexdigest()
    assert not next(record for record in manifest.records if not record.existed).sha256

    existing.write_text("changed", encoding="utf-8")
    new_file.parent.mkdir(parents=True)
    new_file.write_text("partial", encoding="utf-8")

    assert manager.rollback(manifest) == ()
    assert existing.read_text(encoding="utf-8") == "original"
    assert not new_file.exists()


def test_backup_rejects_paths_outside_project(tmp_path: Path) -> None:
    manager = BackupManager(tmp_path / "project")

    with pytest.raises(ValueError, match="outside"):
        manager.create((tmp_path / "other.txt",))


def test_backup_prune_keeps_newest_directories(tmp_path: Path) -> None:
    manager = BackupManager(tmp_path, retention=2)
    backup_root = tmp_path / ".jlceda2kicad_backup"
    for name in ("20260101T000000000000Z", "20260102T000000000000Z", "20260103T000000000000Z"):
        (backup_root / name).mkdir(parents=True)

    removed = manager.prune()

    assert [path.name for path in removed] == ["20260101T000000000000Z"]
    assert sorted(path.name for path in backup_root.iterdir()) == [
        "20260102T000000000000Z",
        "20260103T000000000000Z",
    ]

