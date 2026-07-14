import hashlib
from pathlib import Path

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
