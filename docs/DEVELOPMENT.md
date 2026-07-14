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

To run the optional network probe:

```powershell
$env:RUN_LIVE_LCSC_TESTS = "1"
./.venv/Scripts/python.exe -m pytest -m live -v
```

Build artifacts are intentionally ignored by Git:

```powershell
./.venv/Scripts/python.exe scripts/render_icons.py
./.venv/Scripts/python.exe scripts/build_package.py
./.venv/Scripts/python.exe -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
```

The ZIP is deterministic and is accompanied by a SHA-256 sidecar and sorted
file manifest. Do not commit `dist`.
