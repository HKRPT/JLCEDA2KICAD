# JLCEDA2KICAD

[中文说明](README_zh-CN.md)

JLCEDA2KICAD is an unofficial, Windows-first KiCad IPC plugin for previewing and
importing one LCSC component at a time. It launches `easyeda2kicad` with
`QProcess`, validates the formal conversion in a shadow project, and promotes
selected files into project-local or KiCad global personal libraries with
backups and rollback.

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
- Imports into independently selected existing or pending KiCad global symbol
  and footprint libraries with independently editable component names.
- Backs up every affected file with SHA-256 metadata, atomically replaces files,
  rolls back failures, and retains the latest five backups by default.
- Supports cancel, skip-existing, and component-only overwrite policies.

It does not provide batch import, BOM, stock or pricing data, login, telemetry,
server, database, or team features.

## Requirements

- Windows 10/11
- KiCad 9.0.1 or newer, including KiCad 10
- KiCad's Python 3.11 runtime
- the offline PCM ZIP, which bundles `easyeda2kicad==1.0.1`,
  `kicad-python==0.7.1`, `PySide6==6.11.1`, and their complete Windows
  x64/Python 3.11 dependency closure

The plugin metadata uses `runtime: ipc`; no legacy `pcbnew` SWIG API is used.

## Install from the GitHub PCM repository

KiCad 10 users should add this v2 repository URL:

```text
https://hkrpt.github.io/JLCEDA2KICAD/v2/repository.json
```

KiCad 9 users should add this v1 repository URL:

```text
https://hkrpt.github.io/JLCEDA2KICAD/v1/repository.json
```

1. In KiCad Project Manager, open **Plugin and Content Manager** and choose
   **Manage**.
2. Add the URL matching your KiCad major version, save, refresh the repository,
   search for **JLCEDA2KICAD Importer**, and install it.
3. Open a board in PCB Editor. Launch the importer from the teal JLC button in
   the top toolbar. Depending on the KiCad build, it can also appear under
   **Tools → External Plugins → JLCEDA2KICAD Importer**.

The repository indexes and release assets are hosted on GitHub, so repository
installation and updates require access to GitHub Pages and GitHub Releases.
For an offline or restricted network, download the exact PCM asset from
[GitHub Releases](https://github.com/HKRPT/JLCEDA2KICAD/releases), transfer it
to the target computer, and use **Install from File** without extracting it.
Do not use GitHub's automatically generated “Source code” archives.

On first discovery, KiCad creates its managed isolated Python environment. The
published PCM asset already contains the pinned Windows x64/Python 3.11 runtime
under `plugins/vendor`, so environment setup and plugin launch do not contact
PyPI, GitHub, or another package mirror. Only an uncached EasyEDA/LCSC component
query needs network access; the converter inherits the system proxy environment.

Use Plugin and Content Manager to update or uninstall the PCM copy. After either
operation, close every KiCad window, including Project Manager, and reopen the
project. If the action is missing, use **Tools → External Plugins → Refresh
Plugins** and check the top toolbar again. Also remove an older development copy
with the same `io.hkrpt.jlc` identifier; PCM uninstall intentionally leaves
application settings, cache, logs, and history in place.

## Local offline installation (recommended)

1. Download `JLCEDA2KICAD-0.1.0.zip` and do not extract it.
2. In KiCad Project Manager, open **Plugin and Content Manager**, select
   **Install from File**, and choose that ZIP.
3. Open a PCB project. On the first scan, wait while KiCad creates the plugin's
   dedicated Python environment.
4. In PCB Editor, click the teal JLC icon in the top toolbar. Its tooltip is
   **JLCEDA2KICAD Importer**.

On KiCad 10 the IPC action may appear only in the top toolbar and not as an item
under **Tools > External Plugins**. That submenu's **Refresh Plugins** command
rescans plugins. If the button is still absent after a refresh, exit all KiCad
windows, including Project Manager, and reopen the project.

Installation, first launch, and converter-process startup do not contact PyPI,
GitHub, or an overseas package mirror, and users do not install Python packages
separately. Querying an uncached LCSC identifier still needs access to the
EasyEDA/LCSC component-data service; the plugin inherits the system proxy
environment. A mainland-China-ready release must be the offline PCM ZIP that
contains `plugins/vendor`, not GitHub's automatically generated source ZIP.

## Development install

Stage `.offline-build/vendor` as described under development and packaging,
then copy only this plugin and that bundled runtime into the user IPC plugin
directories:

```powershell
./scripts/install_dev.ps1
```

Restart PCB Editor and select **Tools > External Plugins > Refresh Plugins** if
the action is not loaded automatically. Do not install dependencies into KiCad's
base Python with `--user`. The action is named **JLCEDA2KICAD Importer** and
appears as the teal JLC button in the PCB toolbar.
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

## Global personal libraries

Project mode keeps using `libs/lcsc_project.kicad_sym`,
`libs/lcsc_project.pretty`, and `libs/lcsc_project.3dshapes` in the selected
project. To import into libraries registered for the current KiCad user instead:

1. Query and preview one LCSC component.
2. Select **KiCad global personal library** as the import target.
3. Select the symbol and footprint libraries independently. Either selector can
   use an existing writable library or create a pending library that is
   registered only when the import commits.
4. Edit the symbol and footprint names independently.
5. Verify the displayed sibling `.3dshapes` directory and the final
   `<footprint-library>:<footprint>` association. The association is applied
   when both the symbol and footprint are imported.
6. Import and inspect the result dialog for the exact symbol, footprint, model,
   and backup paths. A newly registered global library is loaded on the next
   KiCad start, so completely exit KiCad (including the Project Manager) and
   reopen it before searching for the new library.

Global imports store backups under the application-local
`backups/global/<timestamp-UUID>` directory (normally
`%LOCALAPPDATA%\HKRPT\JLCEDA2KICAD\backups\global` on Windows). Its manifest
records every absolute target path, original size, and SHA-256 value. Footprints
in the current machine's selected global library receive normalized absolute
STEP/WRL references into the displayed sibling `.3dshapes` directory, so review
those references before moving a library to another machine. Automated tests
use temporary stand-in libraries and never write the real `Harulib` library.

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
