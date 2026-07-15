"""Build a deterministic KiCad PCM ZIP, SHA-256 sidecar, and file manifest."""

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from jlceda2kicad.version import __version__

ROOT = Path(__file__).resolve().parents[1]
VERSION = __version__
ARCHIVE_NAME = f"JLCEDA2KICAD-{VERSION}.zip"
_ZIP_DATE = (2020, 1, 1, 0, 0, 0)
_BINARY_SUFFIXES = {".png"}


@dataclass(frozen=True, slots=True)
class BuildResult:
    archive: Path
    sha256_file: Path
    manifest_file: Path


def _source_files() -> dict[str, Path]:
    files: dict[str, Path] = {
        "metadata.json": ROOT / "metadata.json",
        "resources/icon.svg": ROOT / "resources" / "icon.svg",
        "resources/icon_128.png": ROOT / "resources" / "icon_128.png",
        "plugins/plugin.json": ROOT / "plugin.json",
        "plugins/plugin_entry.py": ROOT / "plugin_entry.py",
        "plugins/plugin_bootstrap.py": ROOT / "plugin_bootstrap.py",
        "plugins/requirements.txt": ROOT / "requirements.txt",
        "plugins/LICENSE": ROOT / "LICENSE",
    }
    for name in (
        "README.md",
        "README_zh-CN.md",
        "CHANGELOG.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        path = ROOT / name
        if path.is_file():
            files[f"plugins/{name}"] = path
    for path in sorted((ROOT / "src" / "jlceda2kicad").rglob("*.py")):
        relative = path.relative_to(ROOT / "src").as_posix()
        files[f"plugins/{relative}"] = path
    for path in sorted((ROOT / "resources").glob("icon*")):
        files[f"plugins/resources/{path.name}"] = path
    missing = [archive_path for archive_path, source in files.items() if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "package source files are missing; run scripts/render_icons.py: " + ", ".join(missing)
        )
    return files


def _write_member(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    normalized = PurePosixPath(name).as_posix()
    info = zipfile.ZipInfo(normalized, _ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    data = source.read_bytes()
    if source.suffix.lower() not in _BINARY_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    archive.writestr(info, data, compresslevel=9)


def build_package(output_dir: Path | None = None) -> BuildResult:
    destination = (output_dir or ROOT / "dist").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / ARCHIVE_NAME
    sha256_path = destination / f"{ARCHIVE_NAME}.sha256"
    manifest_path = destination / f"{ARCHIVE_NAME}.manifest.txt"
    files = _source_files()
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, source in sorted(files.items()):
            _write_member(archive, name, source)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    sha256_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    manifest_path.write_text("\n".join(sorted(files)) + "\n", encoding="utf-8")
    return BuildResult(archive_path, sha256_path, manifest_path)


if __name__ == "__main__":
    result = build_package()
    print(result.archive)
    print(result.sha256_file)
    print(result.manifest_file)
