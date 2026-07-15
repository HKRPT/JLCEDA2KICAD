# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.1.0] - 2026-07-15

### Added

- Global personal-library target selection with independent symbol and footprint
  libraries and names, automatic `<library>:<footprint>` association, normalized
  absolute 3D model references, and multi-root backup rollback.
- A deterministic Windows x64/Python 3.11 offline PCM archive containing the
  complete pinned runtime and third-party license inventory.
- Immutable GitHub Release assets and dual KiCad PCM v1/v2 repository indexes
  published through GitHub Pages.
- Official KiCad IPC action and Chinese PySide6 importer window.
- Safe asynchronous easyeda2kicad preview and formal shadow conversion.
- Symbol SVG, KiCad footprint, and WRL software previews.
- Component conflict policies and project-relative STEP/WRL handling.
- Manifest backups, atomic commit, rollback, and idempotent project library tables.
- Settings, history, rotating redacted logs, development install scripts, PCM packaging, and CI.

### Fixed

- Normalize legacy converter `(module ...)` roots to modern `(footprint ...)`
  files and explain that newly registered global libraries require a full KiCad
  restart, including Project Manager, before they are loaded.
- Rewrite project-library symbol associations to the registered
  `LCSC_Project:<footprint>` nickname.
- Install IPC plugins under the user's Documents-based KiCad plugin directory.
- Use a shorter plugin identifier so pinned PySide6 files stay below the Windows
  legacy 260-character path limit in KiCad's managed environment.
- Preview and import the legacy `(module ...)` footprints and angle-based arcs
  emitted by `easyeda2kicad==1.0.1`.
