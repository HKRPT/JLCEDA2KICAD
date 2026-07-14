# Changelog

All notable changes to this project are documented here.

## [0.1.0] - 2026-07-14

### Added

- Official KiCad IPC action and Chinese PySide6 importer window.
- Safe asynchronous easyeda2kicad preview and formal shadow conversion.
- Symbol SVG, KiCad footprint, and WRL software previews.
- Component conflict policies and project-relative STEP/WRL handling.
- Manifest backups, atomic commit, rollback, and idempotent project library tables.
- Settings, history, rotating redacted logs, development install scripts, PCM packaging, and CI.

### Fixed

- Install IPC plugins under the user's Documents-based KiCad plugin directory.
- Use a shorter plugin identifier so pinned PySide6 files stay below the Windows
  legacy 260-character path limit in KiCad's managed environment.
- Preview and import the legacy `(module ...)` footprints and angle-based arcs
  emitted by `easyeda2kicad==1.0.1`.
