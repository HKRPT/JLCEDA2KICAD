import sys
from pathlib import Path

import pytest

from jlceda2kicad.easyeda_cli import CommandSpec
from jlceda2kicad.process_controller import ProcessController, ProcessResult

pytestmark = pytest.mark.usefixtures("qapp")


def _command(code: str, working_dir: Path) -> CommandSpec:
    return CommandSpec(Path(sys.executable), ("-c", code), working_dir)


def test_process_controller_streams_both_channels_and_reports_success(
    qtbot: object, tmp_path: Path
) -> None:
    controller = ProcessController()
    lines: list[str] = []
    controller.output.connect(lines.append)

    with qtbot.waitSignal(controller.completed, timeout=5_000) as blocker:  # type: ignore[attr-defined]
        controller.start(
            _command(
                "import sys; print('standard output', flush=True); "
                "print('standard error', file=sys.stderr, flush=True)",
                tmp_path,
            ),
            timeout_ms=2_000,
        )

    result = blocker.args[0]
    assert isinstance(result, ProcessResult)
    assert result.succeeded
    assert "standard output" in result.stdout
    assert "standard error" in result.stderr
    assert any("standard output" in line for line in lines)
    assert any("standard error" in line for line in lines)


def test_process_controller_uses_exact_unicode_working_directory_and_inherits_env(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working_dir = tmp_path / "中文 工程"
    working_dir.mkdir()
    monkeypatch.setenv("JLCEDA2KICAD_TEST_PROXY", "inherited")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    controller = ProcessController()

    with qtbot.waitSignal(controller.completed, timeout=5_000) as blocker:  # type: ignore[attr-defined]
        controller.start(
            _command(
                "import os; print(os.getcwd()); print('转换成功'); "
                "print(os.environ['JLCEDA2KICAD_TEST_PROXY'])",
                working_dir,
            ),
            timeout_ms=2_000,
        )

    result = blocker.args[0]
    assert result.succeeded
    assert str(working_dir) in result.stdout
    assert "转换成功" in result.stdout
    assert "inherited" in result.stdout


def test_process_controller_timeout_terminates_process(qtbot: object, tmp_path: Path) -> None:
    controller = ProcessController(kill_grace_ms=50)

    with qtbot.waitSignal(controller.completed, timeout=5_000) as blocker:  # type: ignore[attr-defined]
        controller.start(_command("import time; time.sleep(30)", tmp_path), timeout_ms=100)

    result = blocker.args[0]
    assert result.timed_out
    assert not result.succeeded
    assert not controller.is_running


def test_process_controller_can_be_cancelled(qtbot: object, tmp_path: Path) -> None:
    controller = ProcessController(kill_grace_ms=50)
    with qtbot.waitSignal(controller.started, timeout=2_000):  # type: ignore[attr-defined]
        controller.start(_command("import time; time.sleep(30)", tmp_path), timeout_ms=5_000)

    with qtbot.waitSignal(controller.completed, timeout=5_000) as blocker:  # type: ignore[attr-defined]
        controller.cancel()

    result = blocker.args[0]
    assert result.cancelled
    assert not result.timed_out
    assert not controller.is_running


def test_process_output_redacts_proxy_credentials(qtbot: object, tmp_path: Path) -> None:
    controller = ProcessController()

    with qtbot.waitSignal(controller.completed, timeout=5_000) as blocker:  # type: ignore[attr-defined]
        controller.start(
            _command("print('HTTPS_PROXY=https://user:secret@example.test')", tmp_path),
            timeout_ms=2_000,
        )

    result = blocker.args[0]
    assert "secret" not in result.stdout
    assert "***:***@" in result.stdout
