import os
from pathlib import Path

import pytest

from jlceda2kicad.backup import BackupManager
from jlceda2kicad.import_transaction import (
    AtomicImportTransaction,
    ImportTransactionError,
    prepare_shadow_project,
)


def test_atomic_import_commits_only_selected_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    staged = tmp_path / "shadow" / "libs" / "lcsc_project.kicad_sym"
    target = project / "libs" / "lcsc_project.kicad_sym"
    staged.parent.mkdir(parents=True)
    staged.write_text("new library", encoding="utf-8")
    transaction = AtomicImportTransaction(project, BackupManager(project))

    report = transaction.commit({staged: target})

    assert report.success
    assert report.committed_paths == (target,)
    assert target.read_text(encoding="utf-8") == "new library"
    assert report.backup_dir is not None and report.backup_dir.is_dir()


def test_atomic_import_rolls_back_when_later_replace_fails(tmp_path: Path) -> None:
    project = tmp_path / "project"
    first_target = project / "libs" / "first.txt"
    second_target = project / "libs" / "second.txt"
    first_target.parent.mkdir(parents=True)
    first_target.write_text("original", encoding="utf-8")
    first_stage = tmp_path / "shadow" / "first.txt"
    second_stage = tmp_path / "shadow" / "second.txt"
    first_stage.parent.mkdir(parents=True)
    first_stage.write_text("changed", encoding="utf-8")
    second_stage.write_text("new", encoding="utf-8")
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("locked")
        os.replace(source, target)

    transaction = AtomicImportTransaction(
        project,
        BackupManager(project),
        replace=fail_second,
    )

    with pytest.raises(ImportTransactionError) as captured:
        transaction.commit({first_stage: first_target, second_stage: second_target})

    assert not captured.value.report.success
    assert captured.value.report.rollback_result == ()
    assert first_target.read_text(encoding="utf-8") == "original"
    assert not second_target.exists()


def test_atomic_import_rejects_empty_staged_file_before_backup(tmp_path: Path) -> None:
    project = tmp_path / "project"
    staged = tmp_path / "empty"
    staged.write_text("", encoding="utf-8")

    with pytest.raises(ImportTransactionError, match="空文件"):
        AtomicImportTransaction(project, BackupManager(project)).commit(
            {staged: project / "target"}
        )

    assert not (project / ".jlceda2kicad_backup").exists()


def test_prepare_shadow_project_copies_only_managed_library_tree(tmp_path: Path) -> None:
    project = tmp_path / "project"
    libs = project / "libs"
    (libs / "lcsc_project.pretty").mkdir(parents=True)
    (libs / "lcsc_project.3dshapes").mkdir()
    (libs / "lcsc_project.kicad_sym").write_text("symbols", encoding="utf-8")
    (libs / "lcsc_project.pretty" / "demo.kicad_mod").write_text("footprint", encoding="utf-8")
    (libs / "unrelated.txt").write_text("private", encoding="utf-8")
    shadow = tmp_path / "shadow"

    output_base = prepare_shadow_project(project, shadow)

    assert output_base == shadow / "libs" / "lcsc_project"
    assert (shadow / "libs" / "lcsc_project.kicad_sym").is_file()
    assert (shadow / "libs" / "lcsc_project.pretty" / "demo.kicad_mod").is_file()
    assert not (shadow / "libs" / "unrelated.txt").exists()
