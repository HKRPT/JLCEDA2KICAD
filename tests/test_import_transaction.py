import os
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from jlceda2kicad.absolute_backup import AbsoluteBackupManager
from jlceda2kicad.backup import BackupManager
from jlceda2kicad.import_transaction import (
    AtomicImportTransaction,
    AtomicMultiRootTransaction,
    ImportTransactionError,
    prepare_shadow_project,
)


def _make_directory_link_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symlinks unavailable: {symlink_error}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        pytest.skip("directory links unavailable")


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
    (project / "sym-lib-table").write_text("(sym_lib_table (version 7))", encoding="utf-8")
    (libs / "unrelated.txt").write_text("private", encoding="utf-8")
    shadow = tmp_path / "shadow"

    output_base = prepare_shadow_project(project, shadow)

    assert output_base == shadow / "libs" / "lcsc_project"
    assert (shadow / "libs" / "lcsc_project.kicad_sym").is_file()
    assert (shadow / "libs" / "lcsc_project.pretty" / "demo.kicad_mod").is_file()
    assert (shadow / "sym-lib-table").is_file()
    assert not (shadow / "libs" / "unrelated.txt").exists()


def test_multi_root_transaction_rolls_back_after_second_replace_failure(
    tmp_path: Path,
) -> None:
    symbols = tmp_path / "symbols"
    footprints = tmp_path / "footprints" / "Haru.pretty"
    old = symbols / "Haru.kicad_sym"
    new = footprints / "New.kicad_mod"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    first_stage = tmp_path / "stage-symbol"
    second_stage = tmp_path / "stage-footprint"
    first_stage.write_text("new-symbol", encoding="utf-8")
    second_stage.write_text("new-footprint", encoding="utf-8")
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("locked")
        os.replace(source, target)

    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(symbols, footprints),
        replace=fail_second,
    )

    with pytest.raises(ImportTransactionError) as captured:
        transaction.commit({first_stage: old, second_stage: new})

    assert old.read_text(encoding="utf-8") == "old"
    assert not new.exists()
    assert not footprints.exists()
    assert not footprints.parent.exists()
    assert captured.value.report.rollback_result == ()


def test_multi_root_transaction_rejects_non_allowlisted_target(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(tmp_path / "allowed",),
    )

    with pytest.raises(ImportTransactionError, match="allowlisted"):
        transaction.commit({staged: tmp_path / "outside" / "file"})


def test_multi_root_transaction_accepts_explicitly_allowlisted_file(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    target = tmp_path / "outside" / "sym-lib-table"
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(tmp_path / "allowed",),
        allowed_files=(target,),
    )

    report = transaction.commit({staged: target})

    assert report.success
    assert target.read_text(encoding="utf-8") == "data"


def test_multi_root_transaction_rejects_relative_target_before_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(tmp_path / "allowed",),
    )

    with pytest.raises(ImportTransactionError, match="absolute"):
        transaction.commit({staged: Path("allowed") / "file"})

    assert not (tmp_path / "backups").exists()


def test_multi_root_transaction_freezes_mapping_and_uses_canonical_target(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    original_target = allowed / "unused" / ".." / "file"
    canonical_target = allowed / "file"
    outside_target = tmp_path / "outside" / "file"

    class ChangingTargets(Mapping[Path, Path]):
        def __init__(self) -> None:
            self.items_calls = 0

        def __getitem__(self, key: Path) -> Path:
            assert key == staged
            return outside_target

        def __iter__(self) -> Iterator[Path]:
            return iter((staged,))

        def __len__(self) -> int:
            return 1

        def items(self) -> tuple[tuple[Path, Path], ...]:
            self.items_calls += 1
            target = original_target if self.items_calls == 1 else outside_target
            return ((staged, target),)

    targets = ChangingTargets()
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(allowed,),
    )

    report = transaction.commit(targets)

    assert targets.items_calls == 1
    assert report.committed_paths == (canonical_target,)
    assert canonical_target.read_text(encoding="utf-8") == "data"
    assert not outside_target.exists()
    assert not (allowed / "unused").exists()


def test_multi_root_transaction_rejects_existing_directory_before_backup(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    target = tmp_path / "allowed" / "target"
    target.mkdir(parents=True)
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(target.parent,),
    )

    with pytest.raises(ImportTransactionError, match="regular file"):
        transaction.commit({staged: target})

    assert not (tmp_path / "backups").exists()


def test_multi_root_transaction_rejects_final_symlink_before_backup(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    actual = allowed / "actual"
    actual.mkdir()
    (actual / "original").write_text("original", encoding="utf-8")
    target = allowed / "target"
    _make_directory_link_or_skip(target, actual)
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(allowed,),
    )

    with pytest.raises(ImportTransactionError, match=r"link|reparse"):
        transaction.commit({staged: target})

    target.lstat()
    assert (actual / "original").read_text(encoding="utf-8") == "original"
    assert not (tmp_path / "backups").exists()


def test_multi_root_transaction_rejects_broken_final_symlink_before_backup(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    missing = allowed / "missing"
    missing.mkdir()
    target = allowed / "target"
    _make_directory_link_or_skip(target, missing)
    missing.rmdir()
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(allowed,),
    )

    with pytest.raises(ImportTransactionError, match=r"link|reparse"):
        transaction.commit({staged: target})

    target.lstat()
    assert not (tmp_path / "backups").exists()


def test_multi_root_transaction_preserves_main_error_when_temp_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "allowed" / "target"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    staged = tmp_path / "staged"
    staged.write_text("new", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_transaction_temp_cleanup(path: Path, missing_ok: bool = False) -> None:
        if path.parent == target.parent and path.name.endswith(".tmp"):
            raise PermissionError("temp cleanup locked")
        original_unlink(path, missing_ok=missing_ok)

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError(f"commit locked: {source} -> {destination}")

    monkeypatch.setattr(Path, "unlink", fail_transaction_temp_cleanup)
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(target.parent,),
        replace=fail_replace,
    )

    with pytest.raises(ImportTransactionError, match="Global import commit failed") as captured:
        transaction.commit({staged: target})

    assert target.read_text(encoding="utf-8") == "old"
    assert any("temp cleanup locked" in error for error in captured.value.report.rollback_result)


def test_multi_root_transaction_preserves_main_error_when_rollback_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "allowed" / "target"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    staged = tmp_path / "staged"
    staged.write_text("new", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "backups")

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError(f"commit locked: {source} -> {destination}")

    def fail_rollback(manifest: object) -> tuple[str, ...]:
        raise PermissionError("rollback unavailable")

    monkeypatch.setattr(manager, "rollback", fail_rollback)
    transaction = AtomicMultiRootTransaction(
        manager,
        allowed_roots=(target.parent,),
        replace=fail_replace,
    )

    with pytest.raises(ImportTransactionError, match="Global import commit failed") as captured:
        transaction.commit({staged: target})

    assert any("rollback unavailable" in error for error in captured.value.report.rollback_result)


def test_multi_root_transaction_reports_success_cleanup_failure_as_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "allowed" / "target"
    staged = tmp_path / "staged"
    staged.write_text("new", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_transaction_temp_cleanup(path: Path, missing_ok: bool = False) -> None:
        if path.parent == target.parent and path.name.endswith(".tmp"):
            raise PermissionError("temp cleanup locked")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_transaction_temp_cleanup)
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(target.parent,),
    )

    report = transaction.commit({staged: target})

    assert report.success
    assert any("temp cleanup locked" in warning for warning in report.warnings)
    assert target.read_text(encoding="utf-8") == "new"


def test_multi_root_transaction_reports_prune_failure_as_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "allowed" / "target"
    staged = tmp_path / "staged"
    staged.write_text("new", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "backups")

    def fail_prune() -> tuple[Path, ...]:
        raise PermissionError("prune locked")

    monkeypatch.setattr(manager, "prune", fail_prune)
    transaction = AtomicMultiRootTransaction(
        manager,
        allowed_roots=(target.parent,),
    )

    report = transaction.commit({staged: target})

    assert report.success
    assert any("prune locked" in warning for warning in report.warnings)
    assert target.read_text(encoding="utf-8") == "new"


def test_multi_root_transaction_removes_new_parent_directories_after_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "allowed" / "nested" / "target"
    staged = tmp_path / "staged"
    staged.write_text("new", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError(f"commit locked: {source} -> {destination}")

    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(tmp_path / "allowed",),
        replace=fail_replace,
    )

    with pytest.raises(ImportTransactionError) as captured:
        transaction.commit({staged: target})

    assert captured.value.report.rollback_result == ()
    assert not target.parent.exists()
    assert not (tmp_path / "allowed").exists()


def test_multi_root_transaction_reports_new_parent_directory_cleanup_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "allowed" / "nested" / "target"
    staged = tmp_path / "staged"
    staged.write_text("new", encoding="utf-8")
    blocker = target.parent / "unrelated"

    def fail_replace(source: Path, destination: Path) -> None:
        blocker.write_text("keep", encoding="utf-8")
        raise PermissionError(f"commit locked: {source} -> {destination}")

    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(tmp_path / "allowed",),
        replace=fail_replace,
    )

    with pytest.raises(ImportTransactionError) as captured:
        transaction.commit({staged: target})

    assert blocker.read_text(encoding="utf-8") == "keep"
    assert any(
        "directory cleanup" in error for error in captured.value.report.rollback_result
    )
