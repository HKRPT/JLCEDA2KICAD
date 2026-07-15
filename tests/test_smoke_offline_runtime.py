import json
import zipfile
from pathlib import Path

import pytest

from scripts.smoke_offline_runtime import (
    OfflineSmokeError,
    build_probe_command,
    extract_pcm_archive,
    validate_origins,
)


def test_build_probe_command_uses_isolated_no_site_python(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    plugin_root = tmp_path / "extracted" / "plugins"

    command = build_probe_command(python, plugin_root)

    assert command[:4] == (str(python), "-I", "-S", "-c")
    assert command[-2] == str(plugin_root.resolve())
    assert "easyeda2kicad" in command[4]
    assert "JLCEDA2KICAD_PROBE=" in command[4]


def test_validate_origins_requires_every_module_under_vendor(tmp_path: Path) -> None:
    vendor = (tmp_path / "plugins" / "vendor").resolve()
    vendor.mkdir(parents=True)
    payload = {
        "origins": {
            "PySide6": str(vendor / "PySide6" / "__init__.py"),
            "easyeda2kicad": str(vendor / "easyeda2kicad" / "__init__.py"),
        },
        "cli_exit_code": 0,
        "cli_output": "easyeda2kicad --help",
    }

    validate_origins(payload, vendor, ("PySide6", "easyeda2kicad"))

    payload["origins"]["easyeda2kicad"] = str(tmp_path / ".venv" / "easyeda2kicad.py")
    with pytest.raises(OfflineSmokeError, match="outside bundled vendor"):
        validate_origins(payload, vendor, ("PySide6", "easyeda2kicad"))


def test_validate_origins_rejects_missing_module_and_failed_cli(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    payload: dict[str, object] = {
        "origins": {"PySide6": str(vendor / "PySide6" / "__init__.py")},
        "cli_exit_code": 1,
        "cli_output": "failed",
    }

    with pytest.raises(OfflineSmokeError, match="missing probe origin"):
        validate_origins(payload, vendor, ("PySide6", "easyeda2kicad"))

    payload["origins"] = {
        "PySide6": str(vendor / "PySide6" / "__init__.py"),
        "easyeda2kicad": str(vendor / "easyeda2kicad" / "__init__.py"),
    }
    with pytest.raises(OfflineSmokeError, match="converter CLI failed"):
        validate_origins(payload, vendor, ("PySide6", "easyeda2kicad"))


def test_extract_pcm_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("metadata.json", json.dumps({}))
        package.writestr("../escape.py", "bad")

    with pytest.raises(OfflineSmokeError, match="unsafe archive member"):
        extract_pcm_archive(archive, tmp_path / "output")
