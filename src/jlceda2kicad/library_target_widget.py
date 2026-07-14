"""Qt controls for choosing global import targets and presenting import results."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .artifact_rewrite import validate_component_name
from .global_libraries import (
    GlobalLibraryError,
    config_root_for_version,
    discover_global_libraries,
    pending_library,
)
from .models import ImportReport, ImportScope, ImportTarget, LibraryKind, LibraryRef
from .settings import AppSettings


def _library_identity(reference: LibraryRef) -> tuple[LibraryKind, str, Path, Path]:
    return (
        reference.kind,
        reference.nickname,
        reference.path,
        reference.table_path,
    )


class LibraryTargetWidget(QGroupBox):
    """Collect the project/global destination and generated component names."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        kicad_version: str,
        config_root: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("导入目标与名称", parent)
        self.settings = settings
        self.kicad_version = kicad_version
        self.config_root = config_root
        self.catalog_error = ""

        self.scope = QComboBox()
        self.scope.addItem("当前工程库", ImportScope.PROJECT.value)
        self.scope.addItem("KiCad 全局个人库", ImportScope.GLOBAL.value)
        self.symbol_library = QComboBox()
        self.footprint_library = QComboBox()
        self.symbol_name = QLineEdit()
        self.footprint_name = QLineEdit()
        self.model_path = QLineEdit()
        self.model_path.setReadOnly(True)
        self.refresh_button = QPushButton("刷新库列表")
        self.new_symbol_button = QPushButton("新建符号库")
        self.new_footprint_button = QPushButton("新建封装库")

        self.global_fields = QWidget()
        fields = QFormLayout(self.global_fields)
        symbol_row = QWidget()
        symbol_layout = QHBoxLayout(symbol_row)
        symbol_layout.setContentsMargins(0, 0, 0, 0)
        symbol_layout.addWidget(self.symbol_library, 1)
        symbol_layout.addWidget(self.new_symbol_button)
        footprint_row = QWidget()
        footprint_layout = QHBoxLayout(footprint_row)
        footprint_layout.setContentsMargins(0, 0, 0, 0)
        footprint_layout.addWidget(self.footprint_library, 1)
        footprint_layout.addWidget(self.new_footprint_button)
        fields.addRow("符号库", symbol_row)
        fields.addRow("封装库", footprint_row)
        fields.addRow("符号名称", self.symbol_name)
        fields.addRow("封装名称", self.footprint_name)
        fields.addRow("3D 模型目录", self.model_path)
        fields.addRow(self.refresh_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.scope)
        layout.addWidget(self.global_fields)

        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.footprint_library.currentIndexChanged.connect(self._update_model_path)
        self.refresh_button.clicked.connect(self.refresh)
        self.new_symbol_button.clicked.connect(
            lambda: self._create_library(LibraryKind.SYMBOL)
        )
        self.new_footprint_button.clicked.connect(
            lambda: self._create_library(LibraryKind.FOOTPRINT)
        )

        index = self.scope.findData(settings.last_import_scope.value)
        self.scope.setCurrentIndex(max(0, index))
        self.refresh()
        self._scope_changed()

    def add_pending_library(self, reference: LibraryRef) -> None:
        """Add and select an unregistered library in its matching selector."""
        combo = (
            self.symbol_library
            if reference.kind is LibraryKind.SYMBOL
            else self.footprint_library
        )
        identity = _library_identity(reference)
        for index in range(combo.count()):
            existing = combo.itemData(index)
            if isinstance(existing, LibraryRef) and _library_identity(existing) == identity:
                combo.setCurrentIndex(index)
                return
        combo.addItem(f"{reference.nickname}（待创建） — {reference.path}", reference)
        combo.setCurrentIndex(combo.count() - 1)

    def _scope_changed(self) -> None:
        self.global_fields.setVisible(
            self.scope.currentData() == ImportScope.GLOBAL.value
        )

    def refresh(self) -> None:
        """Reload writable libraries while retaining unregistered selections."""
        symbol_pending, current_symbol = self._combo_state(self.symbol_library)
        footprint_pending, current_footprint = self._combo_state(
            self.footprint_library
        )
        if not self.kicad_version and self.config_root is None:
            self.catalog_error = ""
            self._populate(
                self.symbol_library,
                (),
                self.settings.last_symbol_library,
                pending=symbol_pending,
                current=current_symbol,
            )
            self._populate(
                self.footprint_library,
                (),
                self.settings.last_footprint_library,
                pending=footprint_pending,
                current=current_footprint,
            )
            self._update_model_path()
            return
        try:
            catalog = discover_global_libraries(
                self.kicad_version,
                config_root=self.config_root,
            )
        except GlobalLibraryError as error:
            self.catalog_error = str(error)
            self._populate(
                self.symbol_library,
                (),
                self.settings.last_symbol_library,
                pending=symbol_pending,
                current=current_symbol,
            )
            self._populate(
                self.footprint_library,
                (),
                self.settings.last_footprint_library,
                pending=footprint_pending,
                current=current_footprint,
            )
            self._update_model_path()
            return
        self.catalog_error = ""
        self._populate(
            self.symbol_library,
            catalog.symbols,
            self.settings.last_symbol_library,
            pending=symbol_pending,
            current=current_symbol,
        )
        self._populate(
            self.footprint_library,
            catalog.footprints,
            self.settings.last_footprint_library,
            pending=footprint_pending,
            current=current_footprint,
        )
        self._update_model_path()

    def _combo_state(
        self, combo: QComboBox
    ) -> tuple[tuple[LibraryRef, ...], LibraryRef | None]:
        pending = tuple(
            reference
            for index in range(combo.count())
            if isinstance((reference := combo.itemData(index)), LibraryRef)
            and not reference.registered
        )
        current = combo.currentData()
        return pending, current if isinstance(current, LibraryRef) else None

    def _populate(
        self,
        combo: QComboBox,
        references: tuple[LibraryRef, ...],
        preferred: str,
        *,
        pending: tuple[LibraryRef, ...],
        current: LibraryRef | None,
    ) -> None:
        combo.clear()
        merged: list[LibraryRef] = []
        identities: set[tuple[LibraryKind, str, Path, Path]] = set()
        for reference in (*references, *pending):
            identity = _library_identity(reference)
            if identity in identities:
                continue
            identities.add(identity)
            merged.append(reference)
        for reference in merged:
            suffix = "（待创建）" if not reference.registered else ""
            combo.addItem(f"{reference.nickname}{suffix} — {reference.path}", reference)
        if current is not None:
            selected_identity = _library_identity(current)
            selected_index = next(
                (
                    index
                    for index, reference in enumerate(merged)
                    if _library_identity(reference) == selected_identity
                ),
                -1,
            )
        else:
            selected_index = next(
                (
                    index
                    for index, reference in enumerate(merged)
                    if reference.nickname == preferred
                ),
                -1,
            )
        combo.setCurrentIndex(selected_index)

    def _update_model_path(self) -> None:
        reference = self.footprint_library.currentData()
        path = (
            reference.path.with_suffix(".3dshapes")
            if isinstance(reference, LibraryRef)
            else None
        )
        self.model_path.setText(str(path) if path else "")

    def set_generated_names(self, symbol_name: str, footprint_name: str) -> None:
        """Replace both editable component-name defaults."""
        self.symbol_name.setText(symbol_name)
        self.footprint_name.setText(footprint_name)

    def build_target(
        self,
        *,
        import_symbol: bool = True,
        import_footprint: bool = True,
        import_models: bool = True,
    ) -> ImportTarget:
        """Validate only enabled artifact targets and return an immutable request."""
        try:
            scope = ImportScope(self.scope.currentData())
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid import scope selection") from error
        if scope is ImportScope.PROJECT:
            return ImportTarget()
        symbol = self.symbol_library.currentData()
        footprint = self.footprint_library.currentData()
        if import_symbol and not isinstance(symbol, LibraryRef):
            raise ValueError("请选择全局符号库")
        if (import_footprint or import_models) and not isinstance(footprint, LibraryRef):
            raise ValueError("请选择全局封装库")
        return ImportTarget(
            scope=scope,
            symbol_library=(
                symbol if import_symbol and isinstance(symbol, LibraryRef) else None
            ),
            footprint_library=(
                footprint
                if (import_footprint or import_models)
                and isinstance(footprint, LibraryRef)
                else None
            ),
            symbol_name=(
                validate_component_name(self.symbol_name.text(), "symbol")
                if import_symbol
                else None
            ),
            footprint_name=(
                validate_component_name(self.footprint_name.text(), "footprint")
                if import_footprint
                else None
            ),
        )

    def apply_settings(
        self, settings: AppSettings, target: ImportTarget | None = None
    ) -> AppSettings:
        """Return settings updated with the current scope and selected nicknames."""
        selected = target or self.build_target()
        if selected.scope is ImportScope.PROJECT:
            updated = replace(settings, last_import_scope=selected.scope)
        else:
            updated = replace(
                settings,
                last_import_scope=selected.scope,
                last_symbol_library=(
                    selected.symbol_library.nickname
                    if selected.symbol_library
                    else settings.last_symbol_library
                ),
                last_footprint_library=(
                    selected.footprint_library.nickname
                    if selected.footprint_library
                    else settings.last_footprint_library
                ),
            )
        self.settings = updated
        return updated

    def _create_library(self, kind: LibraryKind) -> None:
        if self.config_root is None:
            try:
                self.config_root = config_root_for_version(self.kicad_version)
            except GlobalLibraryError as error:
                self.catalog_error = str(error)
                QMessageBox.warning(self, "无法确定 KiCad 配置目录", self.catalog_error)
                return
        dialog = NewLibraryDialog(kind, self.config_root, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_pending_library(dialog.library_ref())


class NewLibraryDialog(QDialog):
    """Collect a new library reference without writing any files or tables."""

    def __init__(
        self,
        kind: LibraryKind,
        config_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.config_root = config_root
        self.nickname = QLineEdit()
        self.path = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.path, 1)
        path_layout.addWidget(browse)
        layout = QFormLayout(self)
        layout.addRow("库别名", self.nickname)
        layout.addRow("保存路径", path_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse(self) -> None:
        if self.kind is LibraryKind.SYMBOL:
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "新建 KiCad 符号库",
                self.path.text(),
                "KiCad 符号库 (*.kicad_sym)",
            )
            if selected:
                path = Path(selected)
                if path.suffix.casefold() != ".kicad_sym":
                    path = path.with_suffix(".kicad_sym")
                self.path.setText(str(path))
            return
        parent = QFileDialog.getExistingDirectory(
            self, "选择封装库父目录", self.path.text()
        )
        nickname = self.nickname.text().strip()
        if parent and nickname:
            self.path.setText(str(Path(parent) / f"{nickname}.pretty"))

    def library_ref(self) -> LibraryRef:
        """Validate the fields and construct an unregistered library reference."""
        nickname = self.nickname.text().strip()
        path = Path(self.path.text()).expanduser()
        if self.kind is LibraryKind.SYMBOL:
            if path.suffix.casefold() != ".kicad_sym":
                raise ValueError("符号库路径必须以 .kicad_sym 结尾")
            path = path.with_suffix(".kicad_sym")
            table = self.config_root / "sym-lib-table"
        else:
            if path.suffix.casefold() != ".pretty":
                raise ValueError("封装库路径必须以 .pretty 结尾")
            path = path.with_suffix(".pretty")
            table = self.config_root / "fp-lib-table"
        return pending_library(self.kind, nickname, path, table)

    def accept(self) -> None:
        try:
            self.library_ref()
        except ValueError as error:
            QMessageBox.warning(self, "库设置无效", str(error))
            return
        super().accept()


class ImportResultDialog(QDialog):
    """Present the paths and diagnostics produced by one completed import."""

    def __init__(self, report: ImportReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report
        self.paths = tuple(
            path
            for path in (
                report.symbol_destination,
                report.footprint_destination,
                report.model_directory,
                report.backup_dir,
            )
            if path is not None
        )
        lines = [f"已提交 {len(report.committed_paths)} 个文件。"]
        for label, value in (
            ("符号库", report.symbol_destination),
            ("封装", report.footprint_destination),
            ("3D 模型目录", report.model_directory),
            ("封装关联", report.footprint_association),
            ("备份", report.backup_dir),
        ):
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            lines.append(f"{label}：{value}")
        registrations = tuple(
            item for item in report.library_registration if item.strip()
        )
        if registrations:
            lines.append("新注册：" + "、".join(registrations))
            lines.append("新注册的库若未立即出现，请重启相应的 KiCad 编辑器。")
        warnings = tuple(item for item in report.warnings if item.strip())
        if warnings:
            lines.append("警告：\n" + "\n".join(warnings))

        text = QPlainTextEdit("\n\n".join(lines))
        text.setReadOnly(True)
        open_button = QPushButton("打开库目录")
        copy_button = QPushButton("复制路径")
        open_button.clicked.connect(self._open_primary_directory)
        copy_button.clicked.connect(self._copy_paths)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        actions = QHBoxLayout()
        actions.addWidget(open_button)
        actions.addWidget(copy_button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(buttons)

    def _copy_paths(self) -> None:
        QApplication.clipboard().setText("\n".join(str(path) for path in self.paths))

    def _open_primary_directory(self) -> None:
        destination = (
            self.report.footprint_destination or self.report.symbol_destination
        )
        directory: Path | None
        if destination is not None:
            directory = destination if destination.is_dir() else destination.parent
        else:
            directory = self.report.model_directory or self.report.backup_dir
        if directory is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
