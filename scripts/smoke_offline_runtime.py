"""Prove a PCM ZIP runtime works with package indexes and site-packages disabled."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import cast

PROBE_MODULES = (
    "PySide6",
    "shiboken6",
    "easyeda2kicad",
    "kipy",
    "google.protobuf",
    "pynng",
    "cffi",
    "jsonschema",
    "jsonschema_specifications",
    "referencing",
    "rpds",
    "attrs",
    "sniffio",
    "typing_extensions",
)
_MARKER = "JLCEDA2KICAD_PROBE="
_PROBE_CODE = r'''
import importlib
import json
import subprocess
import sys
from pathlib import Path

plugin_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(plugin_root))
from plugin_bootstrap import bootstrap_vendor

vendor = bootstrap_vendor(plugin_root)
module_names = json.loads(sys.argv[2])
origins = {}
for module_name in module_names:
    module = importlib.import_module(module_name)
    origin = getattr(module, "__file__", None)
    if not origin:
        raise RuntimeError(f"module has no file origin: {module_name}")
    origins[module_name] = str(Path(origin).resolve())

import jlceda2kicad.main

completed = subprocess.run(
    [sys.executable, "-m", "easyeda2kicad", "--help"],
    cwd=plugin_root,
    text=True,
    encoding="utf-8",
    errors="replace",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    check=False,
)
payload = {
    "python": sys.executable,
    "vendor": str(vendor),
    "origins": origins,
    "app_origin": str(Path(jlceda2kicad.main.__file__).resolve()),
    "cli_exit_code": completed.returncode,
    "cli_output": completed.stdout,
}
print("JLCEDA2KICAD_PROBE=" + json.dumps(payload, ensure_ascii=True, sort_keys=True))
'''.strip()


class OfflineSmokeError(RuntimeError):
    """Raised when the self-contained PCM runtime cannot be proven."""


def build_probe_command(python: Path, plugin_root: Path) -> tuple[str, ...]:
    return (
        str(python),
        "-I",
        "-S",
        "-c",
        _PROBE_CODE,
        str(plugin_root.resolve()),
        json.dumps(PROBE_MODULES),
    )


def extract_pcm_archive(archive_path: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    root = output.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name = info.filename
            path = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or (path.parts and ":" in path.parts[0])
            ):
                raise OfflineSmokeError(f"unsafe archive member: {name!r}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise OfflineSmokeError(f"unsafe archive member symlink: {name!r}")
            destination = output.joinpath(*path.parts).resolve()
            if not destination.is_relative_to(root):
                raise OfflineSmokeError(f"unsafe archive member: {name!r}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))


def validate_origins(
    payload: Mapping[str, object],
    vendor: Path,
    required_modules: Sequence[str] = PROBE_MODULES,
) -> None:
    raw_origins = payload.get("origins")
    if not isinstance(raw_origins, dict):
        raise OfflineSmokeError("probe did not return module origins")
    origins = cast(dict[str, object], raw_origins)
    vendor_root = vendor.resolve()
    for module_name in required_modules:
        raw_origin = origins.get(module_name)
        if not isinstance(raw_origin, str):
            raise OfflineSmokeError(f"missing probe origin: {module_name}")
        origin = Path(raw_origin).resolve()
        if not origin.is_relative_to(vendor_root):
            raise OfflineSmokeError(
                f"module resolved outside bundled vendor: {module_name} -> {origin}"
            )
    if payload.get("cli_exit_code") != 0:
        raise OfflineSmokeError(f"converter CLI failed: {payload.get('cli_output', '')}")


def run_smoke(archive_path: Path, python: Path) -> dict[str, object]:
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    if not python.is_file():
        raise FileNotFoundError(python)
    with tempfile.TemporaryDirectory(prefix="jlceda2kicad-offline-smoke-") as temporary:
        extraction_root = Path(temporary)
        extract_pcm_archive(archive_path, extraction_root)
        plugin_root = extraction_root / "plugins"
        vendor = plugin_root / "vendor"
        environment = os.environ.copy()
        environment.update(
            {
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_INDEX_URL": "http://127.0.0.1:9/unreachable",
                "PIP_NO_INDEX": "1",
                "PYTHONNOUSERSITE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        completed = subprocess.run(
            build_probe_command(python, plugin_root),
            cwd=plugin_root,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise OfflineSmokeError(
                f"isolated Python probe failed with {completed.returncode}:\n{completed.stdout}"
            )
        marker_lines = [
            line for line in completed.stdout.splitlines() if line.startswith(_MARKER)
        ]
        if len(marker_lines) != 1:
            raise OfflineSmokeError(
                f"isolated probe returned no unique result:\n{completed.stdout}"
            )
        raw_payload = json.loads(marker_lines[0][len(_MARKER) :])
        if not isinstance(raw_payload, dict):
            raise OfflineSmokeError("isolated probe result is not an object")
        payload = cast(dict[str, object], raw_payload)
        validate_origins(payload, vendor)
        raw_app_origin = payload.get("app_origin")
        if not isinstance(raw_app_origin, str) or not Path(
            raw_app_origin
        ).resolve().is_relative_to(plugin_root.resolve()):
            raise OfflineSmokeError(
                f"application resolved outside extracted plugin: {raw_app_origin}"
            )
        return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--python", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = run_smoke(args.archive, args.python)
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
