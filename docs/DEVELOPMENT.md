# Development

Use Python 3.11. The Windows reference environment uses the Python 3.11.5
runtime shipped with KiCad 10.

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
$env:QT_QPA_PLATFORM = "offscreen"
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m mypy src
./.venv/Scripts/python.exe -m pytest --cov=jlceda2kicad
```

Pure services live under `src/jlceda2kicad`; Qt owns only process scheduling,
dialogs, state, and drawing. Add a failing test before changing behavior. Normal
tests must not access the network.

Formal conversion invariants:

- call `sys.executable -m easyeda2kicad` with a list of arguments;
- use `<shadow>/libs/lcsc_project --project-relative`;
- set the process working directory to the shadow project root;
- run symbol, footprint, and 3D modes separately;
- validate and stage all project files before one atomic transaction.

## Core test routing and global backups

Keep filesystem and rewrite behavior in pure core modules, with Qt limited to
collecting an `ImportTarget` and presenting the resulting `ImportReport`:

- `tests/test_global_libraries.py` covers global-table discovery and pending
  registration planning.
- `tests/test_artifact_rewrite.py` and `tests/test_import_validation.py` cover
  independent names, symbol-to-footprint association, and normalized absolute
  model references.
- `tests/test_absolute_backup.py` and `tests/test_import_transaction.py` cover
  multi-root backup, atomic commit, rollback, and cleanup.
- `tests/test_global_import_service.py` routes those pure services end to end.
  Widget/window routing belongs in `tests/test_library_target_widget.py` and
  `tests/test_main_window.py` and runs with `QT_QPA_PLATFORM=offscreen`.

Tests use `tmp_path` for every selected library and table. Fixture nicknames such
as `Harulib` are only labels for temporary paths; automated tests must never read
or write the user's real `Harulib.kicad_sym`.

Project imports keep their snapshots under
`<project>/.jlceda2kicad_backup/<timestamp>`. A global import can span the user
symbol library, footprint directory, sibling `.3dshapes` directory, and KiCad
global tables, so it uses an absolute-path backup rooted at
`<AppLocalDataLocation>/backups/global/<timestamp-UUID>`. `manifest.json` stores
`target_path`, `backup_name`, `existed`, `size`, and `sha256` for each target;
payloads for existing files live under `files/`. The default retention is the
latest five completed backup directories. All mappings are validated and staged
before one multi-root transaction, and any commit failure rolls every root back.

To run the optional network probe:

```powershell
$env:RUN_LIVE_LCSC_TESTS = "1"
./.venv/Scripts/python.exe -m pytest -m live -v
```

Build artifacts are intentionally ignored by Git:

```powershell
./.venv/Scripts/python.exe scripts/render_icons.py
./.venv/Scripts/python.exe scripts/offline_vendor.py download `
  --wheelhouse .offline-build/wheelhouse
./.venv/Scripts/python.exe scripts/offline_vendor.py expand `
  --wheelhouse .offline-build/wheelhouse `
  --output .offline-build/vendor
./.venv/Scripts/python.exe scripts/build_package.py `
  --vendor-dir .offline-build/vendor
./.venv/Scripts/python.exe -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
```

`offline_vendor.py download` respects the builder's normal pip configuration.
Mainland-China builders can configure their preferred reachable mirror in
`pip.ini` or pass it explicitly with `--index-url`; the project does not hard-code
or redistribute a mirror URL. A fully disconnected build can instead use a
previously populated wheel directory with `--no-index --find-links <directory>`.
These choices affect only release construction. The resulting PCM ZIP installs
and starts without contacting any package index because its runtime is already
expanded under `plugins/vendor`.

The ZIP is deterministic and is accompanied by a SHA-256 sidecar and sorted
file manifest. Do not commit `dist`.

## Release candidate and local PCM repository

Before tagging a release, build the bundled runtime and run the complete source
and package gates. The source, tag, metadata, and three immutable assets can be
checked without contacting GitHub:

```powershell
./.venv/Scripts/python.exe -m mypy src scripts
./.venv/Scripts/python.exe scripts/check_release.py --tag v0.1.0
./.venv/Scripts/python.exe scripts/build_repository_site.py local `
  --tag v0.1.0 `
  --archive dist/JLCEDA2KICAD-0.1.0.zip `
  --checksum dist/JLCEDA2KICAD-0.1.0.zip.sha256 `
  --manifest dist/JLCEDA2KICAD-0.1.0.zip.manifest.txt `
  --download-url http://127.0.0.1:8765/JLCEDA2KICAD-0.1.0.zip `
  --base-url http://127.0.0.1:8765 `
  --published-at 2026-07-15T08:00:00Z `
  --output .smoke/pcm-site
```

Serve `.smoke/pcm-site` on `127.0.0.1:8765` and add the generated v1 and v2
repository URLs to isolated KiCad 9 and 10 configurations. Record package hashes
and screenshots; do not treat an unchecked GUI step as passed. The tag-only
GitHub workflow validates that `vVERSION`, package metadata, and `main` agree,
creates an immutable Release with the ZIP/checksum/manifest trio, then rebuilds
and deploys the dual-schema Pages repository.
