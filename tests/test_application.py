from pathlib import Path

import pytest

from jlceda2kicad.main import create_window
from jlceda2kicad.models import ProjectContext

pytestmark = pytest.mark.usefixtures("qapp")


def test_create_window_wires_application_stores_under_selected_data_dir(
    qtbot: object, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context = ProjectContext(project_root=project, source="manual")
    data_dir = tmp_path / "app-data"

    window = create_window(data_dir=data_dir, context=context)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert window.settings_store.path == data_dir / "settings.json"
    assert window.history_store.path == data_dir / "history.json"
    assert window.temp_manager.root == data_dir / "temp"
    assert window.global_backup_root == data_dir / "backups" / "global"
    assert (data_dir / "logs" / "jlceda2kicad.log").is_file()
