"""Application bootstrap shared by KiCad IPC and standalone development runs."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from .history import HistoryStore
from .logging_config import configure_logging
from .main_window import MainWindow
from .models import ProjectContext
from .project_context import context_from_path, detect_ipc_context
from .settings import SettingsStore
from .temp_manager import TemporaryWorkspaceManager
from .version import __version__


def _application() -> QApplication:
    instance = QApplication.instance()
    if isinstance(instance, QApplication):
        return instance
    application = QApplication(sys.argv)
    application.setOrganizationName("HKRPT")
    application.setApplicationName("JLCEDA2KICAD")
    application.setApplicationVersion(__version__)
    return application


def default_data_dir() -> Path:
    override = os.environ.get("JLCEDA2KICAD_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(location).resolve()


def create_window(
    *, data_dir: Path | None = None, context: ProjectContext | None = None
) -> MainWindow:
    _application()
    root = (data_dir or default_data_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings_store = SettingsStore(root / "settings.json")
    history_store = HistoryStore(root / "history.json", limit=10)
    settings = settings_store.load()
    configure_logging(settings.log_dir or root / "logs")
    resolved_context = context or detect_ipc_context()
    if not resolved_context.is_valid and settings.recent_project:
        resolved_context = context_from_path(settings.recent_project)
    return MainWindow(
        context=resolved_context,
        settings_store=settings_store,
        history_store=history_store,
        temp_manager=TemporaryWorkspaceManager(settings.cache_dir or root / "temp"),
        global_backup_root=root / "backups" / "global",
    )


def run() -> int:
    application = _application()
    window = create_window()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(run())
