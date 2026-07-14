from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from jlceda2kicad.history import HistoryStore
from jlceda2kicad.main_window import MainWindow
from jlceda2kicad.models import (
    ArtifactSet,
    ImportOptions,
    ImportReport,
    ImportScope,
    ProjectContext,
)
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


def _window(
    tmp_path: Path, *, global_config_root: Path | None = None
) -> tuple[MainWindow, FakeProcessController]:
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
        global_backup_root=tmp_path / "backups" / "global",
        global_config_root=global_config_root or tmp_path / "kicad-config",
        process_controller=controller,
    )
    return window, controller


def _global_tables(config: Path, root: Path) -> None:
    config.mkdir(parents=True)
    symbol = root / "symbols" / "Harulib.kicad_sym"
    footprint = root / "footprints" / "Harulib.pretty"
    symbol.parent.mkdir(parents=True)
    footprint.mkdir(parents=True)
    symbol.write_text("(kicad_symbol_lib (version 20231120))", encoding="utf-8")
    (config / "sym-lib-table").write_text(
        f'(sym_lib_table (version 7) (lib (name "Harulib") (type "KiCad") '
        f'(uri "{symbol.as_posix()}")))',
        encoding="utf-8",
    )
    (config / "fp-lib-table").write_text(
        f'(fp_lib_table (version 7) (lib (name "Harulib") (type "KiCad") '
        f'(uri "{footprint.as_posix()}")))',
        encoding="utf-8",
    )


def _window_with_global_tables(
    tmp_path: Path,
) -> tuple[MainWindow, FakeProcessController]:
    config = tmp_path / "kicad-config"
    _global_tables(config, tmp_path / "global-libraries")
    window, controller = _window(tmp_path, global_config_root=config)
    window.library_target.symbol_library.setCurrentIndex(0)
    window.library_target.footprint_library.setCurrentIndex(0)
    return window, controller


def _preview_artifacts(root: Path) -> ArtifactSet:
    root.mkdir(parents=True)
    symbol = root / "preview.kicad_sym"
    symbol.write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Part" '
        '(property "Value" "Part") (property "Footprint" "Old:Foot") '
        '(property "LCSC Part" "C2040")))',
        encoding="utf-8",
    )
    footprint = root / "Foot.kicad_mod"
    footprint.write_text('(footprint "Foot")', encoding="utf-8")
    return ArtifactSet(
        root=root,
        symbol_libraries=(symbol,),
        footprints=(footprint,),
    )


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
    assert output_base.parent.is_dir()
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

    controller.completed.emit(ProcessResult(1, True, "", "", cancelled=True))

    assert window._phase == "idle"
    assert not window.cancel_button.isEnabled()


def test_preview_populates_editable_generated_names(qtbot: object, tmp_path: Path) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("C2040")
    window.preview_button.click()
    command = controller.commands[0]
    output_base = Path(command.arguments[command.arguments.index("--output") + 1])  # type: ignore[attr-defined]
    output_base.with_suffix(".kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Part" '
        '(property "Value" "Part") (property "Footprint" "Old:Foot") '
        '(property "LCSC Part" "C2040")))',
        encoding="utf-8",
    )
    pretty = output_base.with_suffix(".pretty")
    pretty.mkdir()
    (pretty / "Foot.kicad_mod").write_text('(footprint "Foot")', encoding="utf-8")
    controller.completed.emit(ProcessResult(0, True, "", ""))
    controller.completed.emit(ProcessResult(0, True, "", ""))

    assert window.library_target.symbol_name.text() == "Part"
    assert window.library_target.footprint_name.text() == "Foot"


def test_new_preview_does_not_keep_names_when_generated_name_parsing_fails(
    qtbot: object, tmp_path: Path
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("C2040")
    window.preview_button.click()
    first = controller.commands[0]
    first_base = Path(first.arguments[first.arguments.index("--output") + 1])  # type: ignore[attr-defined]
    first_base.with_suffix(".kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "OldSymbol" '
        '(property "LCSC Part" "C2040")))',
        encoding="utf-8",
    )
    first_pretty = first_base.with_suffix(".pretty")
    first_pretty.mkdir()
    (first_pretty / "OldFootprint.kicad_mod").write_text(
        '(footprint "OldFootprint")', encoding="utf-8"
    )
    controller.completed.emit(ProcessResult(0, True, "", ""))
    controller.completed.emit(ProcessResult(0, True, "", ""))
    assert window.library_target.symbol_name.text() == "OldSymbol"
    assert window.library_target.footprint_name.text() == "OldFootprint"

    window.lcsc_input.setText("C2041")
    window.preview_button.click()
    second = controller.commands[2]
    second_base = Path(second.arguments[second.arguments.index("--output") + 1])  # type: ignore[attr-defined]
    second_base.with_suffix(".kicad_sym").write_text("not a symbol library", encoding="utf-8")
    second_pretty = second_base.with_suffix(".pretty")
    second_pretty.mkdir()
    (second_pretty / "FreshFootprint.kicad_mod").write_text(
        '(footprint "FreshFootprint")', encoding="utf-8"
    )
    controller.completed.emit(ProcessResult(0, True, "", ""))
    controller.completed.emit(ProcessResult(0, True, "", ""))

    assert window.artifacts is not None and window.artifacts.has_any
    assert window.library_target.symbol_name.text() == ""
    assert window.library_target.footprint_name.text() == ""


def test_closing_during_preview_does_not_start_the_queued_svg_command(
    qtbot: object, tmp_path: Path
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("C2040")
    window.preview_button.click()
    assert len(controller.commands) == 1

    window.close()
    controller.completed.emit(ProcessResult(1, True, "", "", cancelled=True))

    assert controller.cancelled
    assert len(controller.commands) == 1


def test_closing_during_import_does_not_show_a_completion_dialog(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.artifacts = _preview_artifacts(tmp_path / "preview")
    window.lcsc_input.setText("C2040")
    window.start_import()
    assert len(controller.commands) == 1
    dialogs: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "jlceda2kicad.main_window.QMessageBox.critical",
        lambda *args: dialogs.append(args),
    )

    window.close()
    controller.completed.emit(ProcessResult(1, True, "", "", cancelled=True))

    assert controller.cancelled
    assert len(controller.commands) == 1
    assert dialogs == []


def test_global_import_builds_formal_commands_without_seeding_project_library(
    qtbot: object, tmp_path: Path
) -> None:
    window, controller = _window_with_global_tables(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.artifacts = _preview_artifacts(tmp_path / "preview")
    window.lcsc_input.setText("C2040")
    window.library_target.scope.setCurrentIndex(1)
    window.library_target.set_generated_names("CustomSymbol", "CustomFootprint")

    window.start_import()

    assert len(controller.commands) == 1
    assert window._import_options is not None
    assert window._import_options.target.scope is ImportScope.GLOBAL
    assert window._shadow is not None
    assert not (window._shadow / "libs" / "lcsc_project.kicad_sym").exists()


def test_manual_project_selection_keeps_running_kicad_version(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    window, _ = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    other = tmp_path / "other"
    other.mkdir()
    project = other / "other.kicad_pro"
    project.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(project), "")),
    )

    window._choose_project()

    assert window.context.project_root == other
    assert window.context.kicad_version == "10.0.4"


def test_finish_global_import_routes_backup_report_history_and_settings(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, _ = _window_with_global_tables(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.artifacts = _preview_artifacts(tmp_path / "preview")
    window.lcsc_input.setText("C2040")
    window.library_target.scope.setCurrentIndex(1)
    window.library_target.symbol_library.setCurrentIndex(0)
    window.library_target.footprint_library.setCurrentIndex(0)
    window.library_target.set_generated_names("CustomSymbol", "CustomFootprint")
    target = window.library_target.build_target()
    window._import_options = ImportOptions(target=target)
    window._shadow = tmp_path / "shadow"
    window._shadow.mkdir()
    window._phase = "import"
    captured: dict[str, object] = {}
    report = ImportReport(
        success=True,
        symbol_destination=tmp_path / "Harulib.kicad_sym",
        footprint_destination=tmp_path / "Harulib.pretty" / "CustomFootprint.kicad_mod",
        footprint_association="Harulib:CustomFootprint",
    )

    def fake_import(*args: object, **kwargs: object) -> ImportReport:
        captured["backup"] = kwargs["global_backup_root"]
        return report

    def fake_dialog_exec(dialog: object) -> int:
        captured["report"] = dialog.report  # type: ignore[attr-defined]
        return 0

    monkeypatch.setattr("jlceda2kicad.main_window.import_shadow_artifacts", fake_import)
    monkeypatch.setattr("jlceda2kicad.main_window.ImportResultDialog.exec", fake_dialog_exec)

    window._finish_import()

    assert captured["backup"] == window.global_backup_root
    assert captured["report"] == report
    assert window.settings_store.load().last_symbol_library == "Harulib"
    history = window.history_store.load()
    assert history[0].symbol == "CustomSymbol"
    assert history[0].footprint == "CustomFootprint"
