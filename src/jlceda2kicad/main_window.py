"""Chinese PySide6 main window and asynchronous preview/import workflow."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .artifact_rewrite import generated_names
from .easyeda_cli import CommandSpec, build_command
from .history import HistoryEntry, HistoryStore
from .import_service import (
    ImportServiceError,
    build_formal_requests,
    find_import_conflicts,
    import_shadow_artifacts,
)
from .import_transaction import prepare_shadow_project
from .library_target_widget import ImportResultDialog, LibraryTargetWidget
from .models import (
    ArtifactSet,
    ConflictPolicy,
    ConversionMode,
    ConversionRequest,
    ImportOptions,
    ImportScope,
    ProjectContext,
)
from .output_discovery import discover_artifacts
from .preview_widgets import FootprintPreviewWidget, SymbolPreviewWidget, WrlPreviewWidget
from .process_controller import ProcessController, ProcessResult
from .project_context import context_from_path
from .settings import AppSettings, SettingsStore
from .temp_manager import TemporaryWorkspaceManager
from .validation import LcscIdError, normalize_lcsc_id


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JLCEDA2KICAD 设置")
        layout = QFormLayout(self)
        self.use_cache = QCheckBox("启用 easyeda2kicad 缓存")
        self.use_cache.setChecked(settings.use_cache)
        self.symbol = QCheckBox("导入符号")
        self.symbol.setChecked(settings.import_symbol)
        self.footprint = QCheckBox("导入封装")
        self.footprint.setChecked(settings.import_footprint)
        self.step = QCheckBox("导入 STEP")
        self.step.setChecked(settings.import_step)
        self.wrl = QCheckBox("导入 WRL")
        self.wrl.setChecked(settings.import_wrl)
        self.open_dir = QCheckBox("导入后打开库目录")
        self.open_dir.setChecked(settings.open_library_dir)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 900)
        self.timeout.setValue(settings.timeout_seconds)
        self.timeout.setSuffix(" 秒")
        self.backups = QSpinBox()
        self.backups.setRange(1, 50)
        self.backups.setValue(settings.backup_count)
        layout.addRow(self.use_cache)
        layout.addRow(self.symbol)
        layout.addRow(self.footprint)
        layout.addRow(self.step)
        layout.addRow(self.wrl)
        layout.addRow(self.open_dir)
        layout.addRow("命令超时", self.timeout)
        layout.addRow("保留备份", self.backups)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def apply(self, settings: AppSettings) -> AppSettings:
        return replace(
            settings,
            use_cache=self.use_cache.isChecked(),
            import_symbol=self.symbol.isChecked(),
            import_footprint=self.footprint.isChecked(),
            import_step=self.step.isChecked(),
            import_wrl=self.wrl.isChecked(),
            open_library_dir=self.open_dir.isChecked(),
            timeout_seconds=self.timeout.value(),
            backup_count=self.backups.value(),
        )


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        context: ProjectContext,
        settings_store: SettingsStore,
        history_store: HistoryStore,
        temp_manager: TemporaryWorkspaceManager,
        global_backup_root: Path,
        global_config_root: Path | None = None,
        process_controller: Any | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("JLCEDA2KICAD Importer 0.1.0")
        self.resize(1080, 760)
        self.context = context
        self.settings_store = settings_store
        self.history_store = history_store
        self.temp_manager = temp_manager
        self.global_backup_root = global_backup_root
        self.global_config_root = global_config_root
        self.controller = process_controller or ProcessController(self)
        self.settings = self.settings_store.load()
        self.artifacts: ArtifactSet | None = None
        self._workspace: Path | None = None
        self._shadow: Path | None = None
        self._queue: list[CommandSpec] = []
        self._phase = "idle"
        self._closing = False
        self._failures: list[str] = []
        self._import_options: ImportOptions | None = None
        self._build_ui()
        if self.library_target.catalog_error:
            self._append_log(f"无法读取全局库表：{self.library_target.catalog_error}")
        self._set_context(context)
        self.controller.output.connect(self._append_log)
        self.controller.completed.connect(self._process_completed)
        if self.settings.window_geometry:
            self.restoreGeometry(
                QByteArray.fromBase64(self.settings.window_geometry.encode("ascii"))
            )
        self.temp_manager.cleanup_expired()

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        project_group = QGroupBox("当前 KiCad 工程")
        project_layout = QHBoxLayout(project_group)
        self.project_path = QLineEdit()
        self.project_path.setReadOnly(True)
        self.project_source = QLabel("未识别")
        choose = QPushButton("选择工程…")
        choose.clicked.connect(self._choose_project)
        project_layout.addWidget(self.project_path, 1)
        project_layout.addWidget(self.project_source)
        project_layout.addWidget(choose)
        outer.addWidget(project_group)

        query_group = QGroupBox("元件查询")
        query_layout = QGridLayout(query_group)
        self.lcsc_input = QLineEdit()
        self.lcsc_input.setPlaceholderText("输入单个 C 编号，例如 C2040")
        self.lcsc_input.returnPressed.connect(self.start_preview)
        self.preview_button = QPushButton("查询并预览")
        self.preview_button.clicked.connect(self.start_preview)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_process)
        self.component_name = QLabel("—")
        self.component_files = QLabel("尚未查询")
        query_layout.addWidget(QLabel("LCSC C 编号"), 0, 0)
        query_layout.addWidget(self.lcsc_input, 0, 1)
        query_layout.addWidget(self.preview_button, 0, 2)
        query_layout.addWidget(self.cancel_button, 0, 3)
        query_layout.addWidget(QLabel("元件"), 1, 0)
        query_layout.addWidget(self.component_name, 1, 1)
        query_layout.addWidget(self.component_files, 1, 2, 1, 2)
        outer.addWidget(query_group)

        self.library_target = LibraryTargetWidget(
            self.settings,
            kicad_version=self.context.kicad_version or "",
            config_root=self.global_config_root,
        )
        outer.addWidget(self.library_target)

        self.preview_tabs = QTabWidget()
        self.symbol_preview = SymbolPreviewWidget()
        self.footprint_preview = FootprintPreviewWidget()
        self.model_preview = WrlPreviewWidget()
        model_page = QWidget()
        model_layout = QVBoxLayout(model_page)
        view_buttons = QHBoxLayout()
        for caption, view in (("顶视", "top"), ("正视", "front"), ("等轴测", "isometric")):
            button = QPushButton(caption)
            button.clicked.connect(
                lambda _checked=False, name=view: self.model_preview.set_named_view(name)
            )
            view_buttons.addWidget(button)
        view_buttons.addStretch()
        self.model_fallback = QLabel("暂无模型")
        self.model_fallback.setWordWrap(True)
        open_model_dir = QPushButton("打开模型目录")
        open_model_dir.clicked.connect(self._open_artifact_directory)
        view_buttons.addWidget(open_model_dir)
        model_layout.addLayout(view_buttons)
        model_layout.addWidget(self.model_preview, 1)
        model_layout.addWidget(self.model_fallback)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.preview_tabs.addTab(self.symbol_preview, "符号")
        self.preview_tabs.addTab(self.footprint_preview, "封装")
        self.preview_tabs.addTab(model_page, "3D 模型")
        self.preview_tabs.addTab(self.log_view, "日志")
        outer.addWidget(self.preview_tabs, 1)

        status_row = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.import_button = QPushButton("导入当前工程")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.start_import)
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(self._show_settings)
        history_button = QPushButton("历史")
        history_button.clicked.connect(self._show_history)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress)
        status_row.addWidget(history_button)
        status_row.addWidget(settings_button)
        status_row.addWidget(self.import_button)
        outer.addLayout(status_row)
        self.setCentralWidget(central)

    def _set_context(self, context: ProjectContext) -> None:
        self.context = context
        if context.kicad_version:
            self.library_target.kicad_version = context.kicad_version
        self.library_target.refresh()
        if self.library_target.catalog_error:
            self._append_log(f"无法读取全局库表：{self.library_target.catalog_error}")
        self.project_path.setText(str(context.project_root) if context.project_root else "")
        source = {"ipc": "IPC 自动识别", "manual": "手动选择", "none": "未识别"}
        version = f" · KiCad {context.kicad_version}" if context.kicad_version else ""
        self.project_source.setText(source[context.source] + version)
        self.import_button.setEnabled(bool(self.artifacts and context.is_valid))

    def _choose_project(self) -> None:
        start = str(self.context.project_root or self.settings.recent_project or Path.home())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择 KiCad 工程或 PCB",
            start,
            "KiCad 工程 (*.kicad_pro *.kicad_pcb)",
        )
        selected = filename
        if not selected:
            selected = QFileDialog.getExistingDirectory(self, "选择 KiCad 工程目录", start)
        if not selected:
            return
        detected_version = self.context.kicad_version
        context = context_from_path(Path(selected))
        if context.kicad_version is None and detected_version is not None:
            context = replace(context, kicad_version=detected_version)
        if not context.is_valid:
            self.status_label.setText("所选位置不包含 KiCad 工程。")
            return
        self._set_context(context)
        self.settings = replace(self.settings, recent_project=context.project_root)
        self.settings_store.save(self.settings)

    def start_preview(self) -> None:
        try:
            lcsc_id = normalize_lcsc_id(self.lcsc_input.text())
        except LcscIdError as error:
            self.status_label.setText(f"C 编号无效：{error}")
            return
        self.lcsc_input.setText(lcsc_id)
        self.library_target.set_generated_names("", "")
        self.artifacts = None
        self.import_button.setEnabled(False)
        self._workspace = self.temp_manager.create(f"preview-{lcsc_id}")
        output_base = self._workspace / "preview" / "lcsc_component"
        output_base.parent.mkdir(parents=True, exist_ok=True)
        requests = (
            ConversionRequest(
                lcsc_id,
                (ConversionMode.FULL,),
                output_base,
                self._workspace,
                use_cache=self.settings.use_cache,
            ),
            ConversionRequest(
                lcsc_id,
                (ConversionMode.SVG,),
                output_base,
                self._workspace,
                use_cache=self.settings.use_cache,
            ),
        )
        self._queue = [build_command(request) for request in requests]
        self._phase = "preview"
        self._failures.clear()
        self._set_busy(True, "正在转换预览…")
        self._run_next()

    def start_import(self) -> None:
        if not self.context.is_valid or self.context.project_root is None:
            self.status_label.setText("请先选择有效的 KiCad 工程。")
            return
        if self.artifacts is None:
            self.status_label.setText("请先查询并预览元件。")
            return
        try:
            target = self.library_target.build_target(
                import_symbol=self.settings.import_symbol,
                import_footprint=self.settings.import_footprint,
                import_models=self.settings.import_step or self.settings.import_wrl,
            )
        except ValueError as error:
            self.status_label.setText(f"导入目标无效：{error}")
            return
        self.settings = self.library_target.apply_settings(self.settings, target)
        self.settings_store.save(self.settings)
        options = ImportOptions(
            symbol=self.settings.import_symbol,
            footprint=self.settings.import_footprint,
            step=self.settings.import_step,
            wrl=self.settings.import_wrl,
            use_cache=self.settings.use_cache,
            open_library_dir=self.settings.open_library_dir,
            target=target,
        )
        policy = self._choose_conflict_policy(options)
        if policy is None:
            self.status_label.setText("已取消导入。")
            return
        options = replace(options, conflict_policy=policy)
        self._import_options = options
        self._shadow = self.temp_manager.create(f"import-{self.lcsc_input.text()}")
        if target.scope is ImportScope.PROJECT:
            prepare_shadow_project(self.context.project_root, self._shadow)
        else:
            (self._shadow / "libs").mkdir(parents=True, exist_ok=True)
        requests = build_formal_requests(self.lcsc_input.text(), self._shadow, options)
        if not requests:
            self.status_label.setText("设置中没有选择任何导入产物。")
            return
        self._queue = [build_command(request) for request in requests]
        self._phase = "import"
        self._failures.clear()
        self._set_busy(True, "正在影子工程中正式转换…")
        self._run_next()

    def _choose_conflict_policy(self, options: ImportOptions) -> ConflictPolicy | None:
        conflicts = self._find_conflicts(options)
        if not conflicts:
            return ConflictPolicy.CANCEL
        box = QMessageBox(self)
        box.setWindowTitle("检测到工程库冲突")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("检测到已有元件或同名文件：\n" + "\n".join(conflicts))
        skip = box.addButton("跳过已有项", QMessageBox.ButtonRole.AcceptRole)
        overwrite = box.addButton("覆盖当前元件", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skip:
            return ConflictPolicy.SKIP_EXISTING
        if clicked is overwrite:
            return ConflictPolicy.OVERWRITE_COMPONENT
        if clicked is cancel:
            return None
        return None

    def _find_conflicts(self, options: ImportOptions) -> list[str]:
        if self.artifacts is None or self.context.project_root is None:
            return []
        return list(
            find_import_conflicts(
                self.context.project_root,
                self.artifacts,
                self.lcsc_input.text(),
                options,
            )
        )

    def _run_next(self) -> None:
        if self._closing:
            return
        if not self._queue:
            if self._phase == "preview":
                self._finish_preview()
            elif self._phase == "import":
                self._finish_import()
            return
        command = self._queue.pop(0)
        self._append_log(f"> {command.program} " + " ".join(command.arguments))
        self.controller.start(command, timeout_ms=self.settings.timeout_seconds * 1_000)

    def _process_completed(self, result: ProcessResult) -> None:
        if self._closing:
            return
        if not result.succeeded:
            if result.timed_out:
                reason = "命令超时"
            elif result.cancelled:
                reason = "命令已取消"
            else:
                reason = f"命令退出码 {result.exit_code}"
            self._failures.append(reason)
            self._append_log(reason)
            if self._phase == "import":
                self._queue.clear()
        self._run_next()

    def _finish_preview(self) -> None:
        if self._closing:
            return
        assert self._workspace is not None
        self.artifacts = discover_artifacts(self._workspace)
        self._render_artifacts(self.artifacts)
        available = self.artifacts.has_any
        self.import_button.setEnabled(available and self.context.is_valid)
        if available and self._failures:
            status = "预览完成，但部分命令失败；已保留可用产物。"
        elif available:
            status = "预览完成，可核对后导入。"
        else:
            status = "转换未生成可用产物，请查看日志。"
        self._phase = "idle"
        self._set_busy(False, status)

    def _render_artifacts(self, artifacts: ArtifactSet) -> None:
        if artifacts.symbol_svgs:
            try:
                self.symbol_preview.load_svg(artifacts.symbol_svgs[0])
            except ValueError as error:
                self._append_log(str(error))
        if artifacts.footprints:
            try:
                self.footprint_preview.load_file(artifacts.footprints[0])
                for warning in self.footprint_preview.warnings:
                    self._append_log(warning)
            except (OSError, UnicodeError, ValueError) as error:
                self._append_log(f"封装预览失败：{error}")
        if artifacts.wrl_models:
            model = artifacts.wrl_models[0]
            try:
                self.model_preview.load_file(model)
                self.model_fallback.setText(f"{model.name} · {model.stat().st_size} 字节")
            except (OSError, UnicodeError, ValueError) as error:
                self.model_fallback.setText(
                    f"WRL 预览失败：{error}\n{model}\n{model.stat().st_size} 字节"
                )
        elif artifacts.step_models:
            model = artifacts.step_models[0]
            self.model_fallback.setText(
                f"STEP 文件可导入，首版不直接渲染：\n{model}\n{model.stat().st_size} 字节"
            )
        self.component_name.setText(
            artifacts.footprints[0].stem if artifacts.footprints else self.lcsc_input.text()
        )
        counts = (
            f"符号 {len(artifacts.symbol_libraries)} · 封装 {len(artifacts.footprints)} · "
            f"STEP {len(artifacts.step_models)} · WRL {len(artifacts.wrl_models)}"
        )
        self.component_files.setText(counts)
        for warning in artifacts.warnings:
            self._append_log(warning)
        try:
            symbol_name, footprint_name = generated_names(artifacts, self.lcsc_input.text())
            self.library_target.set_generated_names(symbol_name, footprint_name)
        except (OSError, UnicodeError, ValueError) as error:
            self._append_log(f"无法读取转换名称：{error}")

    def _finish_import(self) -> None:
        if self._closing:
            return
        if self._failures:
            self._phase = "idle"
            self._set_busy(False, "正式转换失败，真实工程未修改。")
            QMessageBox.critical(self, "导入失败", "正式转换失败，未修改工程。请查看日志。")
            return
        assert self.context.project_root is not None
        assert self._shadow is not None
        assert self.artifacts is not None
        assert self._import_options is not None
        try:
            report = import_shadow_artifacts(
                self.context.project_root,
                self._shadow,
                self.lcsc_input.text(),
                self.artifacts,
                self._import_options,
                backup_count=self.settings.backup_count,
                global_backup_root=self.global_backup_root,
            )
        except ImportServiceError as error:
            details = [str(error)]
            if error.report.backup_dir is not None:
                details.append(f"备份：{error.report.backup_dir}")
            if error.report.rollback_result:
                details.append("回滚失败：\n" + "\n".join(error.report.rollback_result))
            elif error.report.backup_dir is not None:
                details.append("已完成回滚。")
            message = "\n\n".join(details)
            self._phase = "idle"
            self._set_busy(False, f"导入失败：{error}")
            QMessageBox.critical(self, "导入失败", message)
            return
        self.settings = self.library_target.apply_settings(
            self.settings, self._import_options.target
        )
        self.settings_store.save(self.settings)
        symbol_name = self._import_options.target.symbol_name or (
            report.symbol_destination.name if report.symbol_destination else ""
        )
        footprint_name = self._import_options.target.footprint_name or (
            report.footprint_destination.name if report.footprint_destination else ""
        )
        self.history_store.add(
            HistoryEntry(
                lcsc_id=self.lcsc_input.text(),
                timestamp=datetime.now(UTC),
                project=str(self.context.project_root),
                symbol=symbol_name,
                footprint=footprint_name,
                result="成功",
            )
        )
        self._phase = "idle"
        self._set_busy(False, "导入成功。")
        ImportResultDialog(report, self).exec()

    def cancel_process(self) -> None:
        self.controller.cancel()
        self._queue.clear()

    def _set_busy(self, busy: bool, status: str) -> None:
        self.preview_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy and bool(self.artifacts and self.context.is_valid))
        self.cancel_button.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(0)
        self.status_label.setText(status)

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text.rstrip())

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.apply(self.settings)
            self.settings_store.save(self.settings)

    def _show_history(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("最近导入历史")
        dialog.resize(760, 360)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["时间", "C 编号", "工程", "封装", "结果"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for entry in self.history_store.load():
            row = table.rowCount()
            table.insertRow(row)
            values = (
                entry.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                entry.lcsc_id,
                entry.project,
                entry.footprint,
                entry.result,
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _open_artifact_directory(self) -> None:
        if self.artifacts is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.artifacts.root)))

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._queue.clear()
        if getattr(self.controller, "is_running", False):
            self.controller.cancel()
        encoded_geometry = self.saveGeometry().toBase64().data()
        if isinstance(encoded_geometry, memoryview):
            encoded_geometry = encoded_geometry.tobytes()
        geometry = bytes(encoded_geometry).decode("ascii")
        self.settings = replace(self.settings, window_geometry=geometry)
        self.settings_store.save(self.settings)
        super().closeEvent(event)
