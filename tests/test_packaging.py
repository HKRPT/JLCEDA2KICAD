import hashlib
import json
import zipfile
from pathlib import Path

from kipy.packaging.validate import validate

from jlceda2kicad.version import __version__
from scripts.build_package import ARCHIVE_NAME, VERSION, _write_member, build_package

ROOT = Path(__file__).resolve().parents[1]


def test_package_version_has_one_stable_archive_metadata_entry() -> None:
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
    versions = metadata["versions"]

    assert VERSION == __version__ == "0.1.0"
    assert ARCHIVE_NAME == f"JLCEDA2KICAD-{__version__}.zip"
    assert len(versions) == 1
    assert versions[0]["version"] == __version__
    assert versions[0]["status"] == "stable"
    assert versions[0]["kicad_version"] == "9.0.1"
    assert versions[0]["platforms"] == ["windows"]
    assert versions[0]["runtime"] == "ipc"
    assert not any(key.startswith("download_") for key in versions[0])


def test_built_archive_contains_the_same_metadata_bytes(tmp_path: Path) -> None:
    result = build_package(tmp_path)

    with zipfile.ZipFile(result.archive) as archive:
        packaged = json.loads(archive.read("metadata.json"))
    source = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))

    assert packaged == source


def test_build_package_has_pcm_root_and_direct_ipc_plugin_layout(tmp_path: Path) -> None:
    result = build_package(tmp_path)

    assert result.archive.name == "JLCEDA2KICAD-0.1.0.zip"
    with zipfile.ZipFile(result.archive) as archive:
        names = set(archive.namelist())
    assert "metadata.json" in names
    assert "resources/icon_128.png" in names
    assert "plugins/plugin.json" in names
    assert "plugins/plugin_entry.py" in names
    assert "plugins/plugin_bootstrap.py" in names
    assert "plugins/requirements.txt" in names
    assert "plugins/jlceda2kicad/main.py" in names
    assert "plugins/resources/icon_24.png" in names
    assert not any(
        forbidden in name
        for name in names
        for forbidden in (".git", ".venv", "__pycache__", "settings.json", ".log")
    )


def test_build_package_writes_matching_sha256_and_sorted_manifest(tmp_path: Path) -> None:
    result = build_package(tmp_path)
    digest = hashlib.sha256(result.archive.read_bytes()).hexdigest()

    assert result.sha256_file.read_text(encoding="ascii").strip() == (
        f"{digest}  {result.archive.name}"
    )
    manifest = result.manifest_file.read_text(encoding="utf-8").splitlines()
    assert manifest == sorted(manifest)
    assert "plugins/plugin.json" in manifest


def test_built_package_passes_official_kipy_validator(tmp_path: Path) -> None:
    result = build_package(tmp_path)
    report = validate(result.archive)

    errors = [message.message for message in report.messages if message.level == "error"]
    assert errors == []


def test_package_normalizes_text_members_to_lf(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_bytes(b"first\r\nsecond\r\n")
    archive_path = tmp_path / "normalized.zip"

    with zipfile.ZipFile(archive_path, "w") as archive:
        _write_member(archive, "plugins/sample.py", source)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("plugins/sample.py") == b"first\nsecond\n"
