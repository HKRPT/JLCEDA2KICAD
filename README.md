# JLCEDA2KICAD

[中文说明](README_zh-CN.md)

JLCEDA2KICAD is an unofficial, Windows-first KiCad IPC plugin for previewing and
importing one LCSC component at a time. It launches `easyeda2kicad` with
`QProcess`, validates the formal conversion in a shadow project, and promotes
selected files into project-local libraries with backups and rollback.

Version 0.1.0 targets KiCad 9.0.1+ and KiCad 10 on Windows. Core logic is tested
on Windows and Ubuntu, but the first PCM release declares Windows only.

## What it does

- Resolves the active PCB project through the official KiCad IPC API, with a
  manual project/file fallback.
- Normalizes one `C` number, invokes `easyeda2kicad==1.0.1` without a shell, and
  streams redacted output into the UI.
- Previews symbol SVG, supported KiCad footprint primitives, and WRL geometry.
- Converts symbol, footprint, and 3D artifacts separately in a shadow project.
- Registers `LCSC_Project` in project-level symbol and footprint library tables.
- Backs up every affected file with SHA-256 metadata, atomically replaces files,
  rolls back failures, and retains the latest five backups by default.
- Supports cancel, skip-existing, and component-only overwrite policies.

It does not provide batch import, BOM, stock or pricing data, login, telemetry,
server, database, or team features.

## Requirements

- Windows 10/11
- KiCad 9.0.1 or newer, including KiCad 10
- KiCad's Python 3.11 runtime
- `easyeda2kicad==1.0.1`, `kicad-python==0.7.1`, `PySide6==6.11.1`

The plugin metadata uses `runtime: ipc`; no legacy `pcbnew` SWIG API is used.

## Development install

Copy only this plugin into the user IPC plugin directories:

```powershell
./scripts/install_dev.ps1
```

Restart PCB Editor and select **Tools > External Plugins > Refresh Plugins** if
the action is not loaded automatically. KiCad creates a dedicated Python
environment and installs the pinned packages from `requirements.txt`; do not
install them into KiCad's base Python with `--user`. The action is named
**JLCEDA2KICAD Importer** and appears as the green JLC button in the PCB toolbar.
To uninstall only this plugin:

```powershell
./scripts/uninstall_dev.ps1
```

Add `-PurgeAppData` only when you also want to delete this application's settings,
cache, history, and logs.

## Use

1. Open a disposable KiCad project in PCB Editor and launch the importer.
2. Confirm the detected project or choose a `.kicad_pro`, `.kicad_pcb`, or folder.
3. Enter one LCSC identifier such as `C2040` and select **Query and Preview**.
4. Inspect all available tabs and warnings. A failed preview tab does not discard
   artifacts produced successfully by another conversion step.
5. Select **Import into Current Project** and choose a conflict policy if prompted.
6. Review the report and the `libs` directory. Backups are stored under
   `.jlceda2kicad_backup` in that project.

Do initial validation in an isolated project. This tool downloads and converts
third-party component data; always verify symbol pins, footprint pads, dimensions,
orientation, and the 3D model before manufacturing.

## Build and verify

```powershell
python -m ruff check .
python -m mypy src
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest --cov=jlceda2kicad
python scripts/build_package.py
python -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
```

Network access is disabled by default in tests. Set `RUN_LIVE_LCSC_TESTS=1` to
opt into the C2040 live conversion test.

See [development notes](docs/DEVELOPMENT.md), the
[manual test checklist](docs/MANUAL_TEST_CHECKLIST.md), and
[third-party notices](THIRD_PARTY_NOTICES.md).

## License and disclaimer

Project code is MIT licensed. Dependencies retain their own licenses, including
the AGPL-3.0 `easyeda2kicad` command-line tool. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This project is not affiliated
with JLCPCB, LCSC, EasyEDA, or KiCad.
