from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from jlceda2kicad.history import HistoryStore
from jlceda2kicad.main_window import MainWindow
from jlceda2kicad.models import ProjectContext
from jlceda2kicad.process_controller import ProcessResult
from jlceda2kicad.settings import SettingsStore
from jlceda2kicad.temp_manager import TemporaryWorkspaceManager

pytestmark = pytest.mark.usefixtures("qapp")


class FakeProcessController(QObject):
    output = Signal(str)
    started = Signal()
    completed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[object] = []
        self.timeouts: list[int] = []
        self.cancelled = False

    @property
    def is_running(self) -> bool:
        return bool(self.commands)

    def start(self, command: object, *, timeout_ms: int) -> None:
        self.commands.append(command)
        self.timeouts.append(timeout_ms)
        self.started.emit()

    def cancel(self) -> None:
        self.cancelled = True


def _window(tmp_path: Path) -> tuple[MainWindow, FakeProcessController]:
    project = tmp_path / "工程"
    project.mkdir()
    project_file = project / "demo.kicad_pro"
    board_file = project / "demo.kicad_pcb"
    project_file.write_text("{}", encoding="utf-8")
    board_file.write_text("(kicad_pcb)", encoding="utf-8")
    controller = FakeProcessController()
    window = MainWindow(
        context=ProjectContext(project, project_file, board_file, "10.0.4", "ipc"),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        history_store=HistoryStore(tmp_path / "history.json"),
        temp_manager=TemporaryWorkspaceManager(tmp_path / "temp"),
        process_controller=controller,
    )
    return window, controller


def test_main_window_has_chinese_workflow_and_four_preview_tabs(
    qtbot: object, tmp_path: Path
) -> None:
    window, _ = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert "JLCEDA2KICAD" in window.windowTitle()
    assert window.project_path.text().endswith("工程")
    assert [window.preview_tabs.tabText(index) for index in range(4)] == [
        "符号",
        "封装",
        "3D 模型",
        "日志",
    ]
    assert not window.import_button.isEnabled()


def test_invalid_lcsc_id_is_rejected_without_starting_process(
    qtbot: object, tmp_path: Path
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("C2040 & whoami")

    window.preview_button.click()

    assert controller.commands == []
    assert "C 编号" in window.status_label.text()


def test_preview_runs_full_then_svg_and_keeps_partial_artifacts(
    qtbot: object, tmp_path: Path
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("c2040")

    window.preview_button.click()

    assert len(controller.commands) == 1
    first = controller.commands[0]
    assert "--full" in first.arguments  # type: ignore[attr-defined]
    output_base = Path(first.arguments[first.arguments.index("--output") + 1])  # type: ignore[attr-defined]
    output_base.parent.mkdir(parents=True, exist_ok=True)
    (output_base.with_suffix(".kicad_sym")).write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Part" (property "LCSC Part" "C2040")))',
        encoding="utf-8",
    )
    pretty = output_base.with_suffix(".pretty")
    pretty.mkdir()
    (pretty / "Part.kicad_mod").write_text(
        '(footprint "Part" (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu")))',
        encoding="utf-8",
    )
    controller.completed.emit(ProcessResult(0, True, "full ok", ""))

    assert len(controller.commands) == 2
    second = controller.commands[1]
    assert "--svg" in second.arguments  # type: ignore[attr-defined]
    svg = output_base.parent / "Part_symbol.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<rect width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    # SVG failure must not discard artifacts from the successful full conversion.
    controller.completed.emit(ProcessResult(2, True, "", "svg failed"))

    assert window.artifacts is not None and window.artifacts.has_any
    assert window.import_button.isEnabled()
    assert window.symbol_preview.source_path == svg
    assert window.footprint_preview.preview is not None
    assert "部分命令失败" in window.status_label.text()


def test_cancel_button_delegates_to_running_process(qtbot: object, tmp_path: Path) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("C2040")
    window.preview_button.click()

    window.cancel_button.click()

    assert controller.cancelled
