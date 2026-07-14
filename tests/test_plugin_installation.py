import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = (
    Path(os.environ.get("SYSTEMROOT", "C:\\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def test_plugin_identifier_avoids_windows_pyside_path_limit() -> None:
    plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
    identifier = plugin["identifier"]
    representative_cache = (
        "C:\\Users\\12345678901234567890\\AppData\\Local\\KiCad\\10.0"
        "\\python-environments"
    )
    longest_pyside_member = (
        "Lib\\site-packages\\PySide6\\qml\\Qt\\labs\\assetdownloader"
        "\\objects-RelWithDebInfo\\QmlAssetDownloaderPrivate_resources_1"
        "\\.qt\\rcc\\qrc_qmake_Qt_labs_assetdownloader_init.cpp.obj"
    )

    assert metadata["identifier"] == identifier
    assert len(f"{representative_cache}\\{identifier}\\{longest_pyside_member}") < 260


@pytest.mark.skipif(not POWERSHELL.is_file(), reason="Windows PowerShell is required")
def test_development_installer_targets_documents_ipc_plugin_directory() -> None:
    plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    expected = (
        Path.home()
        / "Documents"
        / "KiCad"
        / "10.0"
        / "plugins"
        / plugin["identifier"]
    )

    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-File",
            str(ROOT / "scripts" / "install_dev.ps1"),
            "-KiCadVersions",
            "10.0",
            "-WhatIf",
        ],
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert str(expected) in result.stdout
