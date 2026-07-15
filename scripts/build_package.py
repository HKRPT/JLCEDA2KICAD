"""Build a deterministic KiCad PCM ZIP, SHA-256 sidecar, and file manifest."""

import argparse
import hashlib
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from jlceda2kicad.version import __version__  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
VERSION = __version__
ARCHIVE_NAME = f"JLCEDA2KICAD-{VERSION}.zip"
_ZIP_DATE = (2020, 1, 1, 0, 0, 0)
_TEXT_SUFFIXES = {".json", ".md", ".py", ".svg", ".txt"}
_TEXT_FILENAMES = {"LICENSE"}


@dataclass(frozen=True, slots=True)
class BuildResult:
    archive: Path
    sha256_file: Path
    manifest_file: Path


def _add_tree(files: dict[str, Path], root: Path, prefix: str, label: str) -> None:
    if not root.is_dir():
        raise FileNotFoundError(f"{label} directory is missing: {root}")
    found = False
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{label} tree contains a symlink: {path}")
        if not path.is_file():
            continue
        found = True
        relative = path.relative_to(root).as_posix()
        files[f"{prefix}/{relative}"] = path
    if not found:
        raise FileNotFoundError(f"{label} directory contains no files: {root}")


def _source_files(
    *,
    vendor_dir: Path | None = None,
    licenses_dir: Path | None = None,
    inventory_file: Path | None = None,
) -> dict[str, Path]:
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
    runtime_inputs = (vendor_dir, licenses_dir, inventory_file)
    if any(item is not None for item in runtime_inputs):
        if vendor_dir is None or not vendor_dir.is_dir():
            raise FileNotFoundError(f"vendor directory is missing: {vendor_dir}")
        if licenses_dir is None or not licenses_dir.is_dir():
            raise FileNotFoundError(f"license directory is missing: {licenses_dir}")
        if inventory_file is None or not inventory_file.is_file():
            raise FileNotFoundError(f"inventory file is missing: {inventory_file}")
        _add_tree(files, vendor_dir, "plugins/vendor", "vendor")
        _add_tree(
            files,
            licenses_dir,
            "plugins/third_party_licenses",
            "license",
        )
        files["plugins/third_party_licenses/inventory.json"] = inventory_file
    missing = [archive_path for archive_path, source in files.items() if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "package source files are missing; run scripts/render_icons.py: " + ", ".join(missing)
        )
    casefolded: dict[str, str] = {}
    for name in files:
        folded = name.casefold()
        if folded in casefolded and casefolded[folded] != name:
            raise ValueError(
                f"case-insensitive package path collision: {casefolded[folded]}, {name}"
            )
        casefolded[folded] = name
    return files


def _write_member(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    normalized = PurePosixPath(name).as_posix()
    info = zipfile.ZipInfo(normalized, _ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    data = source.read_bytes()
    is_bundled_runtime = normalized.startswith(
        ("plugins/vendor/", "plugins/third_party_licenses/")
    )
    is_known_text = source.suffix.lower() in _TEXT_SUFFIXES or source.name in _TEXT_FILENAMES
    if not is_bundled_runtime and is_known_text:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    archive.writestr(info, data, compresslevel=9)


def build_package(
    output_dir: Path | None = None,
    *,
    vendor_dir: Path | None = None,
    licenses_dir: Path | None = None,
    inventory_file: Path | None = None,
) -> BuildResult:
    destination = (output_dir or ROOT / "dist").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / ARCHIVE_NAME
    sha256_path = destination / f"{ARCHIVE_NAME}.sha256"
    manifest_path = destination / f"{ARCHIVE_NAME}.manifest.txt"
    files = _source_files(
        vendor_dir=vendor_dir,
        licenses_dir=licenses_dir,
        inventory_file=inventory_file,
    )
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, source in sorted(files.items()):
            _write_member(archive, name, source)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    sha256_path.write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    manifest_path.write_text(
        "\n".join(sorted(files)) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return BuildResult(archive_path, sha256_path, manifest_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--vendor-dir", type=Path, default=ROOT / ".offline-build" / "vendor")
    parser.add_argument("--licenses-dir", type=Path)
    parser.add_argument("--inventory-file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runtime_root = args.vendor_dir.parent
    result = build_package(
        args.output_dir,
        vendor_dir=args.vendor_dir,
        licenses_dir=args.licenses_dir or runtime_root / "third_party_licenses",
        inventory_file=args.inventory_file or runtime_root / "inventory.json",
    )
    print(result.archive)
    print(result.sha256_file)
    print(result.manifest_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
