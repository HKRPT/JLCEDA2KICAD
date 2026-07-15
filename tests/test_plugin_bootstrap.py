import os
import sys
from pathlib import Path

import pytest

from plugin_bootstrap import bootstrap_vendor


def test_bootstrap_vendor_prepends_paths_and_preserves_inherited_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_root = tmp_path / "plugin"
    vendor = plugin_root / "vendor"
    vendor.mkdir(parents=True)
    inherited = str(tmp_path / "inherited")
    monkeypatch.setattr(sys, "path", [inherited, *sys.path])
    monkeypatch.setenv("PYTHONPATH", inherited)

    resolved = bootstrap_vendor(plugin_root)

    expected = str(vendor.resolve())
    assert resolved == vendor.resolve()
    assert sys.path[0] == expected
    assert os.environ["PYTHONPATH"].split(os.pathsep) == [expected, inherited]


def test_bootstrap_vendor_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugin"
    vendor = plugin_root / "vendor"
    vendor.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("PYTHONPATH", raising=False)

    bootstrap_vendor(plugin_root)
    bootstrap_vendor(plugin_root)

    expected = str(vendor.resolve())
    assert sys.path.count(expected) == 1
    assert os.environ["PYTHONPATH"].split(os.pathsep).count(expected) == 1


def test_bootstrap_vendor_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="bundled dependency directory is missing"):
        bootstrap_vendor(tmp_path / "plugin")


def test_plugin_entry_bootstraps_before_application_import() -> None:
    source = (Path(__file__).resolve().parents[1] / "plugin_entry.py").read_text(
        encoding="utf-8"
    )

    assert source.index("bootstrap_vendor()") < source.index(
        "from jlceda2kicad.main import run"
    )
