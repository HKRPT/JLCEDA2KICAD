# JLCEDA2KICAD Global Library Import Design

## Summary

JLCEDA2KICAD will keep its existing project-local import mode and add a KiCad
global personal-library mode. In global mode, users select writable symbol and
footprint libraries from the global tables for the running KiCad version, may
create new personal libraries, independently rename the symbol and footprint,
and import the generated assets as one rollback-safe transaction.

The first target is KiCad 10 on Windows, while discovery remains version-aware
so the same behavior works when the plugin is launched by a supported KiCad 9
installation. Existing global libraries may point to another version's user
directory; for example, a `Harulib` entry in KiCad 10 may legitimately refer to
files under `Documents/KiCad/9.0`.

## Goals

- Preserve the current `LCSC_Project` project-local workflow unchanged.
- Add `Current project library` and `KiCad global personal library` import
  destinations.
- Discover writable user libraries from the running KiCad version's global
  `sym-lib-table` and `fp-lib-table`.
- Let users select existing symbol and footprint libraries independently or
  create new ones.
- Let users independently edit the symbol and footprint names for each import.
- Associate the imported symbol with the renamed footprint using
  `<footprint-library-nickname>:<footprint-name>`.
- Store STEP and WRL models in a `.3dshapes` directory next to the selected
  footprint library and rewrite model references so they resolve globally.
- Protect existing personal libraries with validation, manifest backups,
  atomic replacement, and rollback.
- Report exact destination and backup paths after import.

## Non-goals

- Modifying KiCad's installed system libraries.
- Copying an import automatically into every installed KiCad version.
- Making global personal libraries portable between computers.
- Editing KiCad path variables or introducing a new environment variable.
- Batch import or bulk library migration.
- Replacing the existing project-local import behavior.

## User experience

The main window gains a target-library section. The destination selector
defaults to the last successful choice and offers project-local and global
personal-library modes. Selecting global mode reveals:

- a symbol-library selector;
- a footprint-library selector;
- refresh, create-symbol-library, and create-footprint-library actions;
- an editable symbol name;
- an editable footprint name; and
- the derived sibling model directory.

Each selector displays the library nickname and resolved path. Only direct,
writable `KiCad` libraries are selectable. Table-type aggregate entries and
libraries inside protected installation directories are excluded.

After preview, the editable names are populated from the actual converted
symbol and selected footprint. Names are reset for every queried component;
only the destination mode and most recently selected library nicknames are
remembered.

When symbol and footprint import are both enabled, the symbol's `Footprint`
property is set to the selected footprint library nickname and renamed
footprint. A symbol-only import never creates a dangling association; it keeps
the converter's association and emits a warning when that association cannot
be resolved in the chosen destination.

On success, the report lists the symbol library and name, footprint directory
and name, model directory, final footprint association, and backup directory.
It provides actions to open the destination directories and copy their paths.
If KiCad cannot reload a newly registered library immediately, the report asks
the user to restart the relevant editor.

## Global library discovery and creation

The running KiCad version from `ProjectContext` selects the user configuration
directory. On Windows, KiCad 10 normally uses
`%APPDATA%/kicad/10.0/sym-lib-table` and `fp-lib-table`. Discovery parses the
tables structurally and resolves environment variables and normalized paths
without evaluating shell syntax.

An eligible entry must:

- have type `KiCad`;
- resolve to a `.kicad_sym` file for symbols or `.pretty` directory for
  footprints;
- be outside known KiCad installation directories; and
- have a writable existing target or a writable parent directory.

The selector keeps the table nickname separate from the physical path because
the nickname is used in symbol-footprint associations.

Creating a symbol library asks for its nickname and `.kicad_sym` destination.
Creating a footprint library independently asks for its nickname and `.pretty`
destination, then derives a sibling `.3dshapes` directory. Users may give the
two libraries the same nickname, such as `Harulib`, or select different
nicknames and locations. New entries are appended idempotently to the relevant
current-version global table. A nickname already registered to a different
path is an error rather than an implicit retarget. Malformed tables are never
modified.

## Structured renaming and association

Renaming operates on parsed KiCad S-expressions, not unrestricted text
replacement.

Symbol renaming updates the top-level component name, derived multi-unit symbol
names, and the `Value` property while preserving the LCSC identifier,
description, datasheet, fields, graphics, and pins. The imported symbol's
`Footprint` property becomes `<selected nickname>:<renamed footprint>` when both
assets are imported.

Footprint renaming updates the `.kicad_mod` filename, modern `footprint` or
legacy `module` root name, and value text while preserving pads, graphics,
layers, properties, and attributes. Legacy EasyEDA output remains accepted and
is validated after rewriting.

Model filenames retain their converter-provided names. Models are stored in a
`.3dshapes` directory next to the selected footprint library. Model nodes use a
normalized absolute path because no project directory or user-defined KiCad
path variable can be assumed for a global personal library.

Names may contain Unicode, spaces, underscores, and hyphens. Validation rejects
control characters, path separators, Windows-forbidden filename characters,
trailing dots or spaces, reserved device names, empty names, and path
traversal. Library nicknames also reject the separator syntax that would make a
KiCad library identifier ambiguous.

## Conflicts

Conflict detection covers the requested symbol name, requested footprint name,
LCSC identifier, and every selected model filename. The existing cancel, skip,
and overwrite policies remain available.

- Cancel performs no writes.
- Skip omits only colliding artifacts and still imports independent missing
  artifacts when their associations remain valid.
- Overwrite replaces only the matching symbol node and same-named footprint or
  model files.

If the same LCSC identifier already exists under a different symbol name, the
conflict dialog shows both names before applying the policy. The importer never
rebuilds an unrelated personal library from scratch.

## Transaction and backup model

Global imports can span the roaming KiCad configuration directory and one or
more user-library directories, so they use a multi-root transaction rather
than the project-root-only transaction.

Before writing, the importer validates all source and destination
S-expressions, resolves every destination, verifies write access, and rejects
protected or unsafe paths. It then creates a backup under the application's
data directory, with an absolute-path manifest recording existence, size, and
SHA-256 for every file that may change. The default retention remains five
successful import backups.

Each replacement is staged next to its destination to preserve same-volume
atomic `os.replace` semantics. Commit includes the merged symbol library,
renamed footprint, selected models, and any changed global table. If a commit
step fails, rollback restores pre-existing files and removes files created by
the failed transaction. The result reports rollback failures separately and
never claims success after a partial commit.

Project-local imports continue using their existing project backup directory.
Global imports never place backups inside the active KiCad project.

## Settings and data model

Settings add the last destination mode and the last selected global symbol and
footprint nicknames. Missing or stale nicknames fall back to no selection and
do not prevent the window from opening. Component-specific names are not
persisted.

Core types distinguish a library nickname from its path and include its kind,
source table, and write eligibility. Import options carry a destination
description plus requested symbol and footprint names. Import reports add the
resolved association and destination directories while retaining existing
warnings, committed paths, backup path, and rollback result.

Qt remains responsible for selectors, file dialogs, and result actions. Pure
Python services own global-table discovery, eligibility checks, structured
renaming, conflict planning, transaction construction, and validation.

## Error handling

The operation stops before committing when a selected library disappears,
becomes read-only, fails parsing, resolves into a protected directory, or no
longer matches its registered path. Disk failures, file locks, and atomic
replacement failures enter rollback. User-facing errors include the affected
path and stage without exposing proxy credentials or unrelated configuration.

An existing library does not require a table edit. A newly created library may
require a KiCad editor restart before it appears; this is reported as a refresh
instruction rather than an import failure when files and tables committed
successfully.

## Testing and acceptance

Automated tests use temporary directories and never modify real user library
tables. Coverage includes:

- KiCad 9/10 version-aware global table discovery;
- direct versus aggregate table entries;
- protected, missing, read-only, malformed, Unicode, and space-containing
  paths;
- existing-library selection and idempotent new-library registration;
- symbol, multi-unit symbol, modern footprint, and legacy module renaming;
- automatic footprint association;
- STEP and WRL destination/reference rewriting;
- symbol-name, footprint-name, LCSC-ID, and model conflicts under every policy;
- multi-root backup manifests, hashes, atomic commit, rollback, and rollback
  failure reporting;
- persistence and recovery of the new settings;
- global-mode Qt interactions under the offscreen platform; and
- regression coverage for project-local import.

Final verification runs Ruff, mypy, the full pytest/coverage suite, package
build, and PCM validation. A KiCad 10 smoke test uses a disposable global test
library, checks symbol and footprint visibility and association, and then
removes the test entry and files while restoring the original tables. Automated
verification does not write to the user's real `Harulib`.
