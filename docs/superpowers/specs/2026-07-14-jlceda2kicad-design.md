# JLCEDA2KICAD 0.1.0 Design

JLCEDA2KICAD is a Windows-first KiCad 9.0.1+/10 IPC plugin that opens a
standalone PySide6 window from PCB Editor. It validates one LCSC identifier,
runs `easyeda2kicad` asynchronously in a temporary directory, previews every
artifact that was actually produced, and imports selected artifacts only after
the user confirms them.

The plugin separates pure Python services from Qt adapters. Core services own
validation, command construction, artifact discovery, S-expression scanning,
conflict detection, shadow-project import, backups, rollback, settings,
history, and logging. Qt owns `QProcess`, window state, dialogs, and drawing.

Formal import never runs the converter against the real project. It seeds a
shadow project with the existing local libraries, runs independent symbol,
footprint, and 3D conversions there, validates the result, creates a manifest
backup, and atomically promotes only the affected files. Project library tables
are edited with a structure-aware scanner and are never changed when malformed.

Symbol SVGs use a zoomable graphics view. Footprints are rendered from a
bounded subset of KiCad S-expressions. WRL models use a lightweight parser and
software projection; parse or render failures fall back to file information and
never prevent import.

The application stores no credentials and provides no server, login, database,
telemetry, batch import, BOM, stock, pricing, or ordering functions.

