# Offline PCM Local Validation Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behavior change, superpowers:systematic-debugging for any failure, and superpowers:verification-before-completion before claiming success.

**Goal:** Produce and locally prove a Windows x64/CPython 3.11 PCM ZIP that installs in the user's real KiCad 10 and KiCad 9 applications without downloading Python packages or requiring access to PyPI/GitHub/overseas mirrors, launches the importer through the real IPC action, and survives uninstall/reinstall in a mainland China environment.

**Architecture:** Keep KiCad's normal IPC plugin and PCM lifecycle. Package the complete, pinned runtime dependency closure as pre-expanded wheel contents under `plugins/vendor`, make the packaged `requirements.txt` comment-only so KiCad's mandatory pip step succeeds offline, and bootstrap `vendor` onto both `sys.path` and inherited `PYTHONPATH` before importing the application. Build the large offline artifact locally from CPython 3.11 Windows x64 wheels, with strict wheel validation and binary-safe deterministic ZIP output. Real KiCad 10 is the acceptance environment; disposable projects and shadow conversion directories protect user data but are not substitutes for the installed KiCad application.

**Tech Stack:** Python 3.11.5, PySide6 6.11.1, easyeda2kicad 1.0.1, kicad-python 0.7.1, pytest, Ruff, mypy, KiCad PCM/IPC, PowerShell, KiCad 10.0.4 and 9.0.6.

**Safety and scope:** Do not tag, publish, push, or update GitHub during this plan. Preserve `C:\Users\HKRPTS\AppData\Local\HKRPT\JLCEDA2KICAD`, all real projects, project libraries, and backups. Cleanup is authorized only for plugin directories and KiCad-created Python environments whose final path component is exactly `io.hkrpt.jlc` or `com.github.hkrpt.jlceda2kicad` under KiCad 9/10 plugin or `python-environments` roots. Close real KiCad windows before cleanup, and never discard an unexpected unsaved-document prompt.

---

## Task 1: Bootstrap bundled dependencies before application import

**Files:**
- Create: `plugin_bootstrap.py`
- Modify: `plugin_entry.py`
- Modify: `scripts/build_package.py`
- Create: `tests/test_plugin_bootstrap.py`
- Modify: `tests/test_packaging.py`

**Step 1: Write failing bootstrap tests**

Add tests that create a temporary `vendor` directory and verify:

- `bootstrap_vendor(plugin_root)` inserts the resolved vendor directory at index 0 of `sys.path` exactly once.
- It prepends the same directory to `PYTHONPATH` without deleting inherited entries.
- Repeated calls are idempotent.
- A missing vendor directory raises a clear `RuntimeError` for packaged execution.
- `plugin_entry.py` invokes bootstrap before `from jlceda2kicad.main import run`.
- The PCM ZIP contains `plugins/plugin_bootstrap.py`.

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_plugin_bootstrap.py tests/test_packaging.py -q
```

Expected: FAIL because the bootstrap module and packaged member do not exist.

**Step 2: Implement the minimal bootstrap**

Create a standard-library-only `plugin_bootstrap.py`. Resolve the plugin root from `__file__` by default, reject a missing/non-directory `vendor`, prepend it to `sys.path`, and rebuild `PYTHONPATH` using `os.pathsep`. Change `plugin_entry.py` so no `jlceda2kicad`, PySide6, kipy, or easyeda2kicad import occurs before bootstrap. Package the bootstrap file.

**Step 3: Run focused tests and static checks**

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_plugin_bootstrap.py tests/test_packaging.py -q
\.\.venv\Scripts\python.exe -m ruff check plugin_bootstrap.py plugin_entry.py scripts/build_package.py tests/test_plugin_bootstrap.py tests/test_packaging.py
```

Expected: PASS.

**Step 4: Commit**

```powershell
git add plugin_bootstrap.py plugin_entry.py scripts/build_package.py tests/test_plugin_bootstrap.py tests/test_packaging.py
git commit -m "feat: bootstrap bundled PCM dependencies"
```

## Task 2: Propagate the bundled runtime to converter child processes

**Files:**
- Modify: `src/jlceda2kicad/process_controller.py`
- Modify: `tests/test_process_controller.py`

**Step 1: Write a failing process environment test**

Set a synthetic vendor directory in parent `PYTHONPATH`, start a child through `ProcessController`, and assert the child sees that exact leading entry while proxy variables and remaining inherited `PYTHONPATH` entries remain intact. Also assert UTF-8 variables remain forced.

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
\.\.venv\Scripts\python.exe -m pytest tests/test_process_controller.py -q
```

Expected: The new assertion must demonstrate the current behavior before any implementation is changed. If Qt's system environment already preserves the parent value, retain the test as a regression test and do not add redundant production code.

**Step 2: Make only the necessary implementation change**

If the failing test shows `PYTHONPATH` loss, explicitly copy the current process value into `QProcessEnvironment`. If it already passes, document in the code that bootstrap mutates `os.environ` before controllers are constructed and the system environment is intentionally inherited.

**Step 3: Verify and commit**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
\.\.venv\Scripts\python.exe -m pytest tests/test_process_controller.py -q
\.\.venv\Scripts\python.exe -m ruff check src/jlceda2kicad/process_controller.py tests/test_process_controller.py
git add src/jlceda2kicad/process_controller.py tests/test_process_controller.py
git commit -m "test: preserve bundled runtime for converter processes"
```

## Task 3: Resolve and safely expand the pinned Windows runtime wheel set

**Files:**
- Create: `offline-requirements-win-x64-cp311.txt`
- Create: `scripts/offline_vendor.py`
- Create: `tests/test_offline_vendor.py`
- Modify: `.gitignore`

**Step 1: Write failing safe-extraction and inventory tests**

Build tiny synthetic wheels in tests and cover:

- distribution name/version parsing from `.dist-info/METADATA`;
- extraction of root files and `.data/purelib`/`.data/platlib` into one vendor tree;
- preservation of `.dist-info`, DLL/PYD/data bytes, and executable-neutral file modes;
- rejection of absolute paths, `..` traversal, backslash traversal, symlinks, unsupported `.data` schemes, malformed RECORD/METADATA, and conflicting duplicate files;
- acceptance of byte-identical duplicates;
- deterministic sorted dependency inventory and collected license/notice files;
- rejection of non-Windows, non-x86_64, and incompatible Python wheel tags;
- rejection of RECORD mismatches except an exact audited exception that pins
  whole-wheel SHA-256 plus recorded and actual member hashes/sizes;
- successful import closure check using `importlib.metadata` from the staged vendor directory.

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_offline_vendor.py -q
```

Expected: FAIL because `scripts.offline_vendor` does not exist.

**Step 2: Implement wheel acquisition and extraction**

Pin the top-level runtime dependencies in `offline-requirements-win-x64-cp311.txt`. Implement `scripts/offline_vendor.py` with these commands/functions:

- `download`: invoke the current CPython 3.11 as `python -m pip download --only-binary=:all: --platform win_amd64 --python-version 311 --implementation cp --abi cp311 --abi abi3 --dest .offline-build\wheelhouse -r offline-requirements-win-x64-cp311.txt`; network is allowed only at build time. Respect the builder's existing `pip.ini`/environment so a mainland China mirror can be used, accept an optional explicit `--index-url`, and support a local `--find-links`/`--no-index` wheel cache. Never hard-code or package a mirror URL.
- `expand`: validate every wheel and safely copy supported paths into a fresh staging vendor directory.
- `inventory`: record distribution, version, filename, SHA-256, license expression, and included license files in sorted JSON/text output.
- `verify`: ensure all pinned top-level packages plus their recursive `Requires-Dist` closure are present, with environment markers evaluated for Windows/CPython 3.11.

The published `kicad-python` 0.7.1 wheel has one stale METADATA hash/size in its
RECORD. Track that single upstream defect in
`offline-wheel-record-exceptions.json`; do not weaken validation globally.

Use `packaging` only in the build environment, not at plugin runtime. Ignore `.offline-build/`, wheelhouses, expanded vendor trees, and generated reports.

**Step 3: Run focused tests, build-time download, and inventory verification**

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_offline_vendor.py -q
\.\.venv\Scripts\python.exe -m ruff check scripts/offline_vendor.py tests/test_offline_vendor.py
\.\.venv\Scripts\python.exe -m mypy scripts/offline_vendor.py
\.\.venv\Scripts\python.exe scripts/offline_vendor.py download --wheelhouse .offline-build\wheelhouse
\.\.venv\Scripts\python.exe scripts/offline_vendor.py expand --wheelhouse .offline-build\wheelhouse --output .offline-build\vendor
\.\.venv\Scripts\python.exe scripts/offline_vendor.py verify --vendor .offline-build\vendor
```

Expected: PASS, with only Windows x64 CPython 3.11/abi3 wheels in the inventory.

**Step 4: Commit source and tests only**

```powershell
git add offline-requirements-win-x64-cp311.txt scripts/offline_vendor.py tests/test_offline_vendor.py .gitignore
git commit -m "build: stage pinned offline PCM runtime"
```

## Task 4: Build a binary-safe deterministic offline PCM ZIP

**Files:**
- Modify: `requirements.txt`
- Modify: `scripts/build_package.py`
- Modify: `tests/test_packaging.py`
- Create: `tests/test_offline_package.py`

**Step 1: Write failing packaging tests**

Add tests proving:

- packaged `plugins/requirements.txt` contains comments/blank lines only and no install requirement;
- `build_package(..., vendor_dir=...)` includes every vendor file under `plugins/vendor/` and license files under `plugins/third_party_licenses/`;
- vendor bytes are copied exactly, including a synthetic `.pyd`, DLL, PNG, metadata, and arbitrary binary file containing CRLF bytes;
- first-party text remains normalized deterministically, but no vendor content is newline-normalized;
- path collisions and symlinks fail the build;
- two builds from the same inputs have identical ZIP SHA-256 and sorted manifests;
- the archive passes `kipy.packaging.validate`.

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_packaging.py tests/test_offline_package.py -q
```

Expected: FAIL because the builder has no vendor input and currently rewrites most binary content.

**Step 2: Implement offline package assembly**

Make vendor inclusion explicit and required for the distributable offline artifact. Restrict newline normalization to a known set of first-party text members; never transform vendor bytes. Replace runtime requirements with explanatory comments stating that dependencies are bundled in `vendor`. Keep vendor artifacts out of Git.

**Step 3: Build and verify the actual artifact**

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_packaging.py tests/test_offline_package.py -q
\.\.venv\Scripts\python.exe -m ruff check scripts/build_package.py tests/test_packaging.py tests/test_offline_package.py
\.\.venv\Scripts\python.exe scripts/build_package.py --vendor-dir .offline-build\vendor --output-dir dist
\.\.venv\Scripts\python.exe -m kipy.packaging validate dist\JLCEDA2KICAD-0.1.0.zip
Get-FileHash -Algorithm SHA256 dist\JLCEDA2KICAD-0.1.0.zip
```

Expected: all tests and validator pass; ZIP is substantially larger than the previous online-dependency package and contains `plugins/vendor/PySide6`, `easyeda2kicad`, `kipy`, native DLL/PYD files, and their `.dist-info` metadata.

**Step 4: Commit**

```powershell
git add requirements.txt scripts/build_package.py tests/test_packaging.py tests/test_offline_package.py
git commit -m "build: create self-contained offline PCM archive"
```

## Task 5: Prove the staged runtime works without site-packages or PyPI

**Files:**
- Create: `scripts/smoke_offline_runtime.py`
- Create: `tests/test_smoke_offline_runtime.py`

**Step 1: Write failing smoke-runner tests**

Test command construction and result parsing for a clean CPython 3.11 subprocess started with `-I -S` where appropriate, no user site, proxy variables pointed to an unreachable local endpoint, and only the staged plugin/vendor paths made available by an explicit bootstrap script. Require import-origin assertions for `PySide6`, `easyeda2kicad`, `kipy`, `google.protobuf`, `pynng`, and all recursive runtime dependencies.

Run:

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_smoke_offline_runtime.py -q
```

Expected: FAIL because the smoke runner does not exist.

**Step 2: Implement and execute the offline smoke runner**

The runner must extract the completed PCM ZIP to a fresh directory, use the KiCad 10 Python 3.11.5 interpreter, deny package downloads through environment/config (an unreachable index URL plus unreachable HTTP/HTTPS proxy), run bootstrap, import the application and dependency closure, print every module origin, and launch this child command successfully:

```text
<KiCad Python> -m easyeda2kicad --help
```

No origin may resolve to the repository `.venv`, a pre-existing KiCad plugin environment, or global/user site-packages except Python standard-library modules.

**Step 3: Verify and commit**

```powershell
\.\.venv\Scripts\python.exe -m pytest tests/test_smoke_offline_runtime.py -q
\.\.venv\Scripts\python.exe scripts/smoke_offline_runtime.py dist\JLCEDA2KICAD-0.1.0.zip --python "C:\Program Files\KiCad\10.0\bin\python.exe"
git add scripts/smoke_offline_runtime.py tests/test_smoke_offline_runtime.py
git commit -m "test: verify bundled runtime without package downloads"
```

## Task 6: Run the complete automated gate before touching installed KiCad

**Files:** none unless failures require scoped fixes and regression tests.

Run from the worktree:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
\.\.venv\Scripts\python.exe -m ruff check .
\.\.venv\Scripts\python.exe -m mypy src scripts
\.\.venv\Scripts\python.exe -m pytest --cov=jlceda2kicad
\.\.venv\Scripts\python.exe scripts/build_package.py --vendor-dir .offline-build\vendor --output-dir dist
\.\.venv\Scripts\python.exe -m kipy.packaging validate dist\JLCEDA2KICAD-0.1.0.zip
\.\.venv\Scripts\python.exe scripts/smoke_offline_runtime.py dist\JLCEDA2KICAD-0.1.0.zip --python "C:\Program Files\KiCad\10.0\bin\python.exe"
```

Expected: all commands pass. If any command fails, use systematic debugging, add a regression test, and commit the fix before proceeding.

## Task 7: Safely remove only authorized legacy plugin copies and environments

**Files:** local KiCad installation state only; preserve repository and app/project data.

**Step 1: Inspect and close the real applications**

Use computer-use to inspect the open KiCad 10 PCB Editor and manager windows. Save only if KiCad presents an expected prompt and the user document is already in a safe saved state; never choose discard for an unexpected modified file. Close KiCad 10 and KiCad 9 completely, then confirm their processes have exited.

**Step 2: Enumerate exact authorized targets**

For KiCad versions `9.0` and `10.0`, inspect these roots only:

- `%USERPROFILE%\Documents\KiCad\<version>\plugins`
- `%APPDATA%\kicad\<version>\plugins`
- `%LOCALAPPDATA%\KiCad\<version>\python-environments`
- the PCM package root reported by KiCad's “Open package directory” action

Candidate final names must equal `io.hkrpt.jlc` or `com.github.hkrpt.jlceda2kicad`.

**Step 3: Validate and delete with PowerShell end-to-end**

Resolve every target and parent with `[IO.Path]::GetFullPath`, require `target.StartsWith(parent + separator)`, require the exact final component, print the verified target, then use `Remove-Item -LiteralPath ... -Recurse -Force`. Do not remove `%LOCALAPPDATA%\HKRPT\JLCEDA2KICAD` or any directory below a project.

**Step 4: Verify clean precondition**

Re-enumerate all authorized roots and confirm neither identifier remains. Start the real KiCad 10 PCB Editor once and confirm `JLCEDA2KICAD Importer` is absent, proving there is no hidden development copy; close it again before PCM installation.

## Task 8: Install and validate in the real, formally installed KiCad 10.0.4

**Files:** local PCM/plugin state and a new disposable project outside user projects.

**Hard rule:** This is not the repository smoke app, not a mock IPC socket, and not an isolated shadow KiCad installation. Launch `C:\Program Files\KiCad\10.0\bin\kicad.exe`/its PCB Editor and verify the displayed version is 10.0.4.

**Step 1: Create a disposable KiCad 10 project**

Use a new directory under `.smoke\real-kicad-10-offline` and a minimal saved `.kicad_pro`/`.kicad_pcb`. Never open or import into the user's existing real projects.

**Step 2: Install the actual ZIP through PCM**

Open “Plugin and Content Manager → Install from File”, select `dist\JLCEDA2KICAD-0.1.0.zip`, apply pending changes, and observe installation to completion. Keep package-index access deliberately unreachable for dependency setup so a successful install cannot be attributed to PyPI, GitHub, or an overseas mirror. This must model a mainland China machine that only has the ZIP.

Record evidence of:

- PCM shows version 0.1.0 installed;
- the PCM-extracted plugin contains `vendor`;
- KiCad's environment setup exits successfully with the comment-only requirements file;
- no legacy development plugin directory exists;
- the action appears exactly once under PCB Editor “Tools → External Plugins” and/or toolbar.

**Step 3: Launch through the real IPC action**

Enable KiCad API if required, click `JLCEDA2KICAD Importer`, and confirm:

- a PySide6 window opens;
- current project path and KiCad 10.0.4 are detected via the real IPC socket;
- the plugin process uses the KiCad-created `io.hkrpt.jlc` CPython 3.11 environment;
- `PySide6`, `easyeda2kicad`, `kipy`, native extensions, and converter child process resolve from the PCM plugin's `vendor`, not PyPI-installed copies.

**Step 4: Exercise real preview and import**

Using C2040 (or the last known stable online test ID if C2040 is unavailable), run preview and verify symbol, footprint, STEP, WRL, and available SVG tabs. Import into the disposable project, then verify the project-local symbol library, footprint library, models, library table entries, and model references. Network here is only the LCSC/EasyEDA query, never Python dependency installation. Confirm system HTTP/HTTPS proxy variables are inherited when present and that proxy credentials are redacted from logs.

**Step 5: Verify uninstall and reinstall**

Uninstall through PCM, apply changes, restart/refresh PCB Editor, and confirm the action and PCM plugin files disappear while `%LOCALAPPDATA%\HKRPT\JLCEDA2KICAD` and disposable imported project files remain. Reinstall the same ZIP through PCM and prove the action launches again.

Any failure in this task blocks acceptance. Diagnose it in the branch, add automated regression coverage where possible, rebuild the ZIP, clean only the failed plugin/env state, and repeat the entire KiCad 10 install sequence.

## Task 9: Validate the same ZIP in the real KiCad 9.0.6

**Files:** local PCM/plugin state and `.smoke\real-kicad-9-offline` only.

Repeat Task 8 with the formally installed KiCad 9.0.6 executable and a separate disposable project. At minimum prove PCM install without PyPI, one action entry, PySide6 launch, real IPC project/version detection, converter child startup, preview, uninstall, and absence after refresh. Reuse the exact ZIP hash validated in KiCad 10; do not rebuild between versions.

If KiCad 9 is not installed or its formal executable/version differs, record the exact evidence and treat KiCad 9 as not verified rather than passing it by inference.

## Task 10: Final evidence and local handoff

**Files:**
- Create: `docs/testing/2026-07-15-offline-pcm-local-validation.md`

Record:

- branch and commit list;
- exact ZIP path, byte size, SHA-256, and manifest path;
- wheel inventory and licenses;
- Ruff, mypy, pytest/coverage, build, kipy validation, and isolated smoke outputs;
- real KiCad 10 executable/version, PCM install location, environment path, import origins, IPC project, C2040 preview/import results, uninstall/reinstall evidence;
- equivalent KiCad 9 evidence;
- proof that PCM dependency setup did not need PyPI, GitHub, or an overseas mirror, plus the exact distinction between offline installation and online LCSC/EasyEDA queries;
- preserved application/project data;
- every unverified item or residual limitation, especially that new LCSC queries still require network;
- explicit conclusion: suitable or not suitable for a later public 0.1.0 release.

Then run a fresh final gate:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
\.\.venv\Scripts\python.exe -m ruff check .
\.\.venv\Scripts\python.exe -m mypy src scripts
\.\.venv\Scripts\python.exe -m pytest --cov=jlceda2kicad
\.\.venv\Scripts\python.exe -m kipy.packaging validate dist\JLCEDA2KICAD-0.1.0.zip
git status --short --branch
git log --oneline --decorate -12
```

Commit the evidence only after it accurately reflects observed results:

```powershell
git add docs/testing/2026-07-15-offline-pcm-local-validation.md
git commit -m "test: document real KiCad offline PCM validation"
```

Do not merge, tag, push, or create a GitHub release. Report the local outcome and wait for separate publication authorization.
