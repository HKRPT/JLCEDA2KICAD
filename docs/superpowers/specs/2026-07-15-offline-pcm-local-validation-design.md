# Offline PCM Local Validation Design

**Date:** 2026-07-15
**Status:** Approved for local implementation and validation
**Scope:** Windows x64, CPython 3.11, KiCad 9.0.6 and 10.0.4

## Goal

Prove locally that one KiCad PCM ZIP can install JLCEDA2KICAD without contacting
PyPI, expose the IPC action after KiCad finishes its environment setup, launch
the PySide6 UI, and run the bundled `easyeda2kicad` command from the same
offline dependency payload.

This phase does not create a GitHub tag, Release, Pages repository, or public
binary. Public distribution remains blocked until the local proof succeeds and
third-party license evidence is complete.

## User-visible contract

- The user installs one ZIP through Plugin and Content Manager's **Install from
  File** action.
- The user must enable the KiCad API once in PCB Editor preferences. The plugin
  cannot change this KiCad security preference.
- KiCad may spend a few seconds creating its isolated Python environment, but
  dependency setup must not access PyPI or another package index.
- Installation must also work in a typical mainland China environment without
  access to PyPI, GitHub, or an overseas package mirror.
- The action then appears as **JLCEDA2KICAD Importer** under **Tools > External
  Plugins** and opens normally.
- Installing Python dependencies is offline. Querying a new LCSC component is
  not offline because EasyEDA/JLC data still comes from its network service;
  cached component data may be usable without that service.

## Architecture

The PCM package keeps the current Python IPC runtime and adds a pre-expanded
dependency tree:

```text
metadata.json
plugins/
  plugin.json
  plugin_entry.py
  requirements.txt
  jlceda2kicad/
  vendor/
    easyeda2kicad/
    kipy/
    PySide6/
    shiboken6/
    ...recursive runtime dependencies...
    *.dist-info/
  third_party_licenses/
resources/
```

`requirements.txt` remains readable but contains no installable requirement,
so KiCad's mandatory isolated pip step succeeds without an index lookup.
`plugin_entry.py` prepends `vendor` to both `sys.path` and the inherited
`PYTHONPATH` before importing application code. The environment update is
inherited by `QProcess`, so `sys.executable -m easyeda2kicad` resolves the
vendored CLI as well as in-process PySide6 and kicad-python imports.

The local build consumes only wheels compatible with Windows x64 and CPython
3.11/abi3. Wheel members are extracted with traversal, symlink, and duplicate
content checks. `purelib` and `platlib` wheel data is mapped into `vendor`;
unsupported wheel installation schemes fail the build. Package metadata stays
available because `dist-info` content is retained.

All files below `vendor` are treated as binary-safe package content. The
existing CRLF-to-LF normalization is limited to first-party known text files so
that DLL, PYD, Qt plugin, archive, metadata, and resource bytes cannot be
silently modified.

## Local build inputs

The feasibility build uses an explicit runtime dependency inventory pinned to
the current application requirements:

- `easyeda2kicad==1.0.1`
- `kicad-python==0.7.1`
- `PySide6==6.11.1`
- every recursively required Windows x64/Python 3.11 wheel

The local builder downloads or reuses these wheels only during construction,
records their filenames and SHA-256 values, and verifies the hashes before
extraction. It respects the builder's existing pip configuration, including a
mainland China mirror, and also accepts an explicit index URL, local wheelhouse,
or no-index cache mode without embedding any mirror into the plugin. The
resulting installed plugin must not need those source wheels or network access.

For the local proof, generated wheels, the expanded vendor tree, smoke
directories, and ZIP artifacts remain ignored and uncommitted. A later public
release design will decide the permanent lock-file, cache, license, and CI
policy after feasibility is established.

## Cleanup and isolation

Before installation, close KiCad and remove only known JLCEDA2KICAD plugin
copies and KiCad-managed environments for identifiers `io.hkrpt.jlc` and
`com.github.hkrpt.jlceda2kicad` under the KiCad 9.0 and 10.0 user plugin/cache
roots.

Do not remove or modify:

- KiCad projects, project-local libraries, or global library tables;
- `.jlceda2kicad_backup` directories;
- imported symbols, footprints, or 3D models;
- `%LOCALAPPDATA%\HKRPT\JLCEDA2KICAD` settings, history, cache, or logs.

Every recursive removal must resolve and verify the absolute target remains
inside its expected KiCad plugin or `python-environments` parent before it is
performed.

## Validation sequence

1. Run the complete existing offline test baseline.
2. Build the vendored runtime and PCM ZIP.
3. Validate the ZIP structure, member safety, hashes, dependency inventory, and
   `kipy.packaging` result.
4. Prove with a fresh Python 3.11 environment and package-index access disabled
   (including an unreachable index/proxy configuration) that all runtime imports
   resolve from the staged `vendor` directory.
5. Prove a child `sys.executable -m easyeda2kicad --help` invocation inherits
   the vendor path and succeeds.
6. Close KiCad and clean the authorized old plugin/environment locations.
7. Install the candidate ZIP through KiCad 10 PCM.
8. Confirm the PCM extraction path, newly created KiCad environment, no legacy
   copy, action availability, import origins, main window launch, and project
   detection.
9. Run C2040 query/preview and a disposable-project import. Network use here is
   limited to LCSC/EasyEDA component retrieval, not Python package setup. Verify
   inherited mainland-network proxy variables are preserved and credentials are
   redacted from logs.
10. Uninstall through PCM and confirm the PCM plugin files and action disappear
    while project and application data remain.
11. Reinstall the same ZIP and repeat action launch.
12. Repeat install, launch, and uninstall with KiCad 9 using the same ZIP after
    KiCad 10 succeeds.

## Error handling and evidence

- A missing, incompatible, unlicensed, hash-mismatched, unsafe, or conflicting
  wheel aborts before a ZIP is produced.
- An import must report its resolved `__file__`; a system or old environment
  origin is a failure.
- A failed KiCad environment job, missing action, process launch error, UI
  exception, conversion failure, uninstall residue, or unexpected filesystem
  mutation is recorded as a failed acceptance item, not inferred as passing.
- Debug changes follow a failing regression test before implementation.
- Evidence records command exit codes, ZIP hash/size/member count, import
  origins, KiCad versions, plugin/environment paths, PCM install/uninstall
  outcomes, and any unverified item. Credentials and proxy secrets are never
  recorded.

## Acceptance criteria

The local feasibility phase succeeds only when:

- all automated tests and static checks pass;
- one deterministic offline PCM ZIP validates successfully;
- clean KiCad 10 PCM installation exposes and launches the plugin without PyPI;
- that installation does not require GitHub or an overseas mirror and remains
  successful with package-index access deliberately made unreachable;
- PySide6, kicad-python, and easyeda2kicad load from the installed `vendor`;
- the easyeda2kicad child process, preview, and disposable-project import work;
- PCM uninstall removes the plugin action and managed files;
- reinstall works; and
- the same ZIP passes the corresponding KiCad 9 install/launch/uninstall smoke.

No GitHub Release is authorized by this specification.
