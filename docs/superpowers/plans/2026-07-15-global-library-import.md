# Global Personal-Library Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rollback-safe KiCad global personal-library destination with independent library selection, symbol and footprint renaming, sibling 3D-model storage, and automatic symbol-to-footprint association while preserving project-local imports.

**Architecture:** Keep the converter and shadow workspace unchanged, then route promotion through either the existing project importer or a new global importer. Add focused pure-Python modules for global table discovery, structured artifact rewriting, and absolute-path backups; expose them through a dedicated Qt target widget so `main_window.py` remains an orchestrator.

**Tech Stack:** Python 3.11, PySide6 6.11.1, `easyeda2kicad==1.0.1`, `kicad-python==0.7.1`, pytest/pytest-qt, Ruff, mypy, KiCad S-expression files.

## Global Constraints

- Preserve the current `LCSC_Project` project-local import behavior and tests.
- Target KiCad 10 on Windows first; keep discovery version-aware for supported KiCad 9 installations.
- Read and modify only direct, writable `KiCad` global-library entries; never modify aggregate `Table` entries or installed system libraries.
- Keep symbol and footprint library nicknames and paths independent.
- Store global STEP/WRL files in a `.3dshapes` sibling of the selected `.pretty` directory and use normalized absolute model references.
- Use structure-aware S-expression edits; never rename by unrestricted text replacement.
- Commit symbol, footprint, models, and any global table updates as one multi-root transaction with SHA-256 backup and rollback.
- Automated tests must not read or write the user's real `%APPDATA%` library tables or `Harulib`.
- Keep Python at `>=3.11,<3.12` and all existing runtime dependency pins unchanged.
- Do not edit KiCad path variables, introduce a new environment variable, or auto-copy a library into other installed KiCad versions.
- Do not add batch import, library migration, BOM, inventory, pricing, login, server, database, or team features.
- Execute inline with one agent unless the user explicitly changes the previously approved single-agent preference.

---

## File Structure

- Create `src/jlceda2kicad/global_libraries.py`: version-aware global table paths, catalog discovery, eligibility checks, pending references, and idempotent registration planning.
- Create `src/jlceda2kicad/artifact_rewrite.py`: name validation, generated-name extraction, structured symbol/footprint renaming, association, and global model paths.
- Create `src/jlceda2kicad/absolute_backup.py`: absolute-target manifest backup, hashing, rollback, and retention for global imports.
- Create `src/jlceda2kicad/library_target_widget.py`: destination controls, global selectors, create-library dialog, and import-result dialog.
- Modify `src/jlceda2kicad/models.py`: shared scope, library reference, target, catalog, and report contracts.
- Modify `src/jlceda2kicad/settings.py`: persist last scope and selected global nicknames.
- Modify `src/jlceda2kicad/import_validation.py`: validate project-relative and approved global-absolute model references.
- Modify `src/jlceda2kicad/import_transaction.py`: add an allowlisted multi-root atomic transaction without changing project transaction semantics.
- Modify `src/jlceda2kicad/import_service.py`: global promotion path and shared conflict preflight.
- Modify `src/jlceda2kicad/main_window.py`: orchestrate the target widget and route import/report actions.
- Modify `src/jlceda2kicad/main.py`: inject global backup location.
- Add focused tests beside the existing test suite and update English/Chinese docs and manual verification.

---

### Task 1: Shared import-target contracts and settings

**Files:**
- Modify: `src/jlceda2kicad/models.py`
- Modify: `src/jlceda2kicad/settings.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_settings_history.py`

**Interfaces:**
- Produces: `ImportScope`, `LibraryKind`, `LibraryRef`, `GlobalLibraryCatalog`, `ImportTarget`.
- Produces: `ImportOptions.target: ImportTarget` with a project-local default.
- Produces: destination fields on `ImportReport` and persisted `AppSettings.last_import_scope`, `last_symbol_library`, and `last_footprint_library`.
- Consumes: existing `Path`, `Enum`, dataclass, and JSON-store behavior.

- [ ] **Step 1: Write failing model and settings tests**

Add these assertions to `tests/test_models.py`:

```python
from jlceda2kicad.models import (
    GlobalLibraryCatalog,
    ImportScope,
    ImportTarget,
    LibraryKind,
    LibraryRef,
)


def test_global_import_target_derives_model_directory(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    footprint = LibraryRef(
        nickname="Harulib",
        kind=LibraryKind.FOOTPRINT,
        path=tmp_path / "footprints" / "Harulib.pretty",
        table_path=table,
    )
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        footprint_library=footprint,
        symbol_name="电容 22uF",
        footprint_name="C0805-Haru",
    )

    assert target.model_dir == tmp_path / "footprints" / "Harulib.3dshapes"
    assert GlobalLibraryCatalog(footprints=(footprint,)).footprints == (footprint,)


def test_import_options_keep_project_scope_by_default() -> None:
    assert ImportOptions().target == ImportTarget()
    assert ImportOptions().target.scope is ImportScope.PROJECT
```

Extend the settings round-trip in `tests/test_settings_history.py`:

```python
from jlceda2kicad.models import ImportScope


def test_settings_round_trip_preserves_global_library_choices(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    expected = AppSettings(
        last_import_scope=ImportScope.GLOBAL,
        last_symbol_library="Harulib",
        last_footprint_library="Harulib",
    )

    store.save(expected)

    assert store.load() == expected
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["last_import_scope"] == "global"
```

- [ ] **Step 2: Run the focused tests and verify the contracts are missing**

Run:

```powershell
python -m pytest tests/test_models.py tests/test_settings_history.py -q
```

Expected: collection fails because `ImportScope`, `LibraryKind`, `LibraryRef`,
`GlobalLibraryCatalog`, and `ImportTarget` do not exist.

- [ ] **Step 3: Add immutable contracts to `models.py`**

Change the dataclass import to `from dataclasses import dataclass, field`, then add:

```python
class ImportScope(str, Enum):
    PROJECT = "project"
    GLOBAL = "global"


class LibraryKind(str, Enum):
    SYMBOL = "symbol"
    FOOTPRINT = "footprint"


@dataclass(frozen=True, slots=True)
class LibraryRef:
    nickname: str
    kind: LibraryKind
    path: Path
    table_path: Path
    registered: bool = True


@dataclass(frozen=True, slots=True)
class GlobalLibraryCatalog:
    symbols: tuple[LibraryRef, ...] = ()
    footprints: tuple[LibraryRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportTarget:
    scope: ImportScope = ImportScope.PROJECT
    symbol_library: LibraryRef | None = None
    footprint_library: LibraryRef | None = None
    symbol_name: str | None = None
    footprint_name: str | None = None

    @property
    def model_dir(self) -> Path | None:
        if self.footprint_library is None:
            return None
        return self.footprint_library.path.with_suffix(".3dshapes")
```

Add the target field to `ImportOptions`:

```python
    target: ImportTarget = field(default_factory=ImportTarget)
```

Add these fields to `ImportReport`:

```python
    symbol_destination: Path | None = None
    footprint_destination: Path | None = None
    model_directory: Path | None = None
    footprint_association: str | None = None
```

- [ ] **Step 4: Persist only stable global choices**

Import `ImportScope` in `settings.py` and add:

```python
    last_import_scope: ImportScope = ImportScope.PROJECT
    last_symbol_library: str = ""
    last_footprint_library: str = ""
```

In `SettingsStore.save`, explicitly serialize the enum:

```python
        data["last_import_scope"] = settings.last_import_scope.value
```

In `SettingsStore.load`, normalize it before the allowed-field filter:

```python
            data["last_import_scope"] = ImportScope(
                data.get("last_import_scope", ImportScope.PROJECT.value)
            )
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m pytest tests/test_models.py tests/test_settings_history.py -q
python -m ruff check src/jlceda2kicad/models.py src/jlceda2kicad/settings.py tests/test_models.py tests/test_settings_history.py
```

Expected: all focused tests pass and Ruff reports no errors.

Commit:

```powershell
git add src/jlceda2kicad/models.py src/jlceda2kicad/settings.py tests/test_models.py tests/test_settings_history.py
git commit -m "feat: add global import target contracts"
```

---

### Task 2: Version-aware global library catalog and registration

**Files:**
- Create: `src/jlceda2kicad/global_libraries.py`
- Create: `tests/test_global_libraries.py`

**Interfaces:**
- Consumes: `LibraryKind`, `LibraryRef`, `GlobalLibraryCatalog`, `parse_one`.
- Produces: `GlobalLibraryError`.
- Produces: `config_root_for_version(kicad_version: str, *, roaming_root: Path | None = None) -> Path`.
- Produces: `discover_global_libraries(kicad_version: str, *, config_root: Path | None = None, environ: Mapping[str, str] | None = None, install_roots: tuple[Path, ...] = ()) -> GlobalLibraryCatalog`.
- Produces: `pending_library(kind: LibraryKind, nickname: str, path: Path, table_path: Path) -> LibraryRef`.
- Produces: `validate_library_destination(reference: LibraryRef, *, environ: Mapping[str, str] | None = None, install_roots: tuple[Path, ...] = ()) -> None`.
- Produces: `build_global_registration(reference: LibraryRef, *, environ: Mapping[str, str] | None = None, install_roots: tuple[Path, ...] = ()) -> dict[Path, str]`.

- [ ] **Step 1: Write discovery and registration tests**

Create `tests/test_global_libraries.py` with temporary KiCad tables:

```python
from pathlib import Path

import pytest

from jlceda2kicad.global_libraries import (
    GlobalLibraryError,
    build_global_registration,
    config_root_for_version,
    discover_global_libraries,
    pending_library,
)
from jlceda2kicad.models import LibraryKind, LibraryRef


def _write_tables(root: Path, user_root: Path, install_root: Path) -> None:
    root.mkdir(parents=True)
    (user_root / "symbols").mkdir(parents=True)
    (user_root / "footprints" / "Harulib.pretty").mkdir(parents=True)
    install_root.mkdir(parents=True)
    system = install_root / "System.kicad_sym"
    system.write_text(
        "(kicad_symbol_lib (version 20231120))", encoding="utf-8"
    )
    (user_root / "symbols" / "Harulib.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20231120))", encoding="utf-8"
    )
    (root / "sym-lib-table").write_text(
        "(sym_lib_table (version 7)"
        f' (lib (name "KiCad") (type "Table") (uri "{install_root.as_posix()}"))'
        f' (lib (name "System") (type "KiCad") (uri "{system.as_posix()}"))'
        f' (lib (name "Harulib") (type "KiCad") (uri "{(user_root / "symbols" / "Harulib.kicad_sym").as_posix()}")))',
        encoding="utf-8",
    )
    (root / "fp-lib-table").write_text(
        "(fp_lib_table (version 7)"
        f' (lib (name "Harulib") (type "KiCad") (uri "{(user_root / "footprints" / "Harulib.pretty").as_posix()}")))',
        encoding="utf-8",
    )


def test_discovers_writable_direct_user_libraries(tmp_path: Path) -> None:
    config = tmp_path / "Roaming" / "kicad" / "10.0"
    user_root = tmp_path / "个人 库"
    install_root = tmp_path / "Program Files" / "KiCad"
    _write_tables(config, user_root, install_root)

    catalog = discover_global_libraries(
        "10.0.4", config_root=config, install_roots=(install_root,)
    )

    assert [item.nickname for item in catalog.symbols] == ["Harulib"]
    assert [item.nickname for item in catalog.footprints] == ["Harulib"]
    assert catalog.symbols[0].table_path == config / "sym-lib-table"


def test_config_root_uses_major_minor_version(tmp_path: Path) -> None:
    assert config_root_for_version("10.0.4", roaming_root=tmp_path) == tmp_path / "kicad" / "10.0"


def test_registration_is_idempotent_and_rejects_retarget(tmp_path: Path) -> None:
    table = tmp_path / "sym-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    reference = pending_library(
        LibraryKind.SYMBOL, "我的库", tmp_path / "我的库.kicad_sym", table
    )

    update = build_global_registration(reference)
    table.write_text(update[table], encoding="utf-8")

    assert build_global_registration(reference) == {}
    moved = pending_library(LibraryKind.SYMBOL, "我的库", tmp_path / "other.kicad_sym", table)
    with pytest.raises(GlobalLibraryError, match="different path"):
        build_global_registration(moved)


def test_malformed_global_table_is_never_modified(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    original = "(fp_lib_table (broken)"
    table.write_text(original, encoding="utf-8")
    reference = pending_library(LibraryKind.FOOTPRINT, "Haru", tmp_path / "Haru.pretty", table)

    with pytest.raises(GlobalLibraryError, match="fp-lib-table"):
        build_global_registration(reference)

    assert table.read_text(encoding="utf-8") == original


def test_registration_rejects_a_protected_install_destination(tmp_path: Path) -> None:
    protected = tmp_path / "Program Files" / "KiCad"
    protected.mkdir(parents=True)
    table = tmp_path / "sym-lib-table"
    table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    reference = pending_library(
        LibraryKind.SYMBOL, "System", protected / "System.kicad_sym", table
    )

    with pytest.raises(GlobalLibraryError, match="protected"):
        build_global_registration(reference, install_roots=(protected,))


def test_registered_library_that_disappeared_is_rejected(tmp_path: Path) -> None:
    table = tmp_path / "sym-lib-table"
    missing = tmp_path / "Missing.kicad_sym"
    table.write_text(
        f'(sym_lib_table (version 7) (lib (name "Missing") (type "KiCad") '
        f'(uri "{missing.as_posix()}")))',
        encoding="utf-8",
    )
    reference = LibraryRef("Missing", LibraryKind.SYMBOL, missing, table, registered=True)

    with pytest.raises(GlobalLibraryError, match="disappeared"):
        build_global_registration(reference)
```

- [ ] **Step 2: Run the new test module and verify import failure**

Run:

```powershell
python -m pytest tests/test_global_libraries.py -q
```

Expected: collection fails because `jlceda2kicad.global_libraries` is absent.

- [ ] **Step 3: Implement table paths, parsing, and eligibility**

Create `global_libraries.py` with these public contracts and helper rules:

```python
import os
import re
from collections.abc import Mapping
from pathlib import Path

from .models import GlobalLibraryCatalog, LibraryKind, LibraryRef
from .sexpr import ListExpr, SExprError, parse_one


class GlobalLibraryError(ValueError):
    pass


_VERSION = re.compile(r"^(\d+)\.(\d+)")
_VARIABLE = re.compile(r"\$\{([^}]+)\}")
_ROOT_NAMES = {
    LibraryKind.SYMBOL: ("sym-lib-table", "sym_lib_table", ".kicad_sym"),
    LibraryKind.FOOTPRINT: ("fp-lib-table", "fp_lib_table", ".pretty"),
}


def config_root_for_version(kicad_version: str, *, roaming_root: Path | None = None) -> Path:
    match = _VERSION.match(kicad_version.strip())
    if match is None:
        raise GlobalLibraryError(f"Unsupported KiCad version: {kicad_version}")
    root = roaming_root or Path(os.environ["APPDATA"])
    return root / "kicad" / f"{match.group(1)}.{match.group(2)}"


def _fields(node: ListExpr) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in node.children:
        atoms = child.atoms
        if child.head is not None and len(atoms) >= 2:
            result[child.head] = atoms[1].value
    return result


def _resolve_uri(uri: str, environ: Mapping[str, str]) -> Path | None:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        value = environ.get(match.group(1))
        if value is None:
            unresolved = True
            return match.group(0)
        return value

    expanded = _VARIABLE.sub(replace, uri)
    if unresolved:
        return None
    return Path(expanded).expanduser().resolve()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _writable(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.exists() and os.access(candidate, os.W_OK)
```

Add these complete discovery functions:

```python
def _default_install_roots(environ: Mapping[str, str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        value = environ.get(variable)
        if value:
            roots.append(Path(value) / "KiCad")
    return tuple(roots)


def _load_root(path: Path, expected_head: str) -> ListExpr | None:
    if not path.is_file():
        return None
    try:
        root = parse_one(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, SExprError) as error:
        raise GlobalLibraryError(f"{path.name} is malformed: {error}") from error
    if root.head != expected_head:
        raise GlobalLibraryError(
            f"{path.name} has root {root.head!r}, expected {expected_head!r}"
        )
    return root


def _discover_kind(
    kind: LibraryKind,
    table_path: Path,
    *,
    environ: Mapping[str, str],
    install_roots: tuple[Path, ...],
) -> tuple[LibraryRef, ...]:
    _, root_name, suffix = _ROOT_NAMES[kind]
    root = _load_root(table_path, root_name)
    if root is None:
        return ()
    discovered: list[LibraryRef] = []
    for node in root.children:
        if node.head != "lib":
            continue
        fields = _fields(node)
        if fields.get("type") != "KiCad":
            continue
        nickname = fields.get("name", "").strip()
        path = _resolve_uri(fields.get("uri", ""), environ)
        if not nickname or path is None or not path.name.endswith(suffix):
            continue
        if any(_within(path, protected) for protected in install_roots):
            continue
        expected_type = path.is_file() if kind is LibraryKind.SYMBOL else path.is_dir()
        if not expected_type:
            continue
        if not _writable(path):
            continue
        discovered.append(LibraryRef(nickname, kind, path, table_path, registered=True))
    return tuple(sorted(discovered, key=lambda item: item.nickname.casefold()))


def discover_global_libraries(
    kicad_version: str,
    *,
    config_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    install_roots: tuple[Path, ...] = (),
) -> GlobalLibraryCatalog:
    environment = dict(os.environ if environ is None else environ)
    root = config_root or config_root_for_version(kicad_version)
    protected = install_roots or _default_install_roots(environment)
    symbols = _discover_kind(
        LibraryKind.SYMBOL,
        root / "sym-lib-table",
        environ=environment,
        install_roots=protected,
    )
    footprints = _discover_kind(
        LibraryKind.FOOTPRINT,
        root / "fp-lib-table",
        environ=environment,
        install_roots=protected,
    )
    return GlobalLibraryCatalog(symbols=symbols, footprints=footprints)
```

- [ ] **Step 4: Implement pending references and pure registration updates**

Add nickname validation and update construction:

```python
def _validated_nickname(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(char in normalized for char in ':"/\\'):
        raise GlobalLibraryError("Library nickname is empty or contains an unsafe separator")
    return normalized


def pending_library(
    kind: LibraryKind, nickname: str, path: Path, table_path: Path
) -> LibraryRef:
    return LibraryRef(
        nickname=_validated_nickname(nickname),
        kind=kind,
        path=path.expanduser().resolve(),
        table_path=table_path.expanduser().resolve(),
        registered=False,
    )


def validate_library_destination(
    reference: LibraryRef,
    *,
    environ: Mapping[str, str] | None = None,
    install_roots: tuple[Path, ...] = (),
) -> None:
    environment = dict(os.environ if environ is None else environ)
    filename, _, expected_suffix = _ROOT_NAMES[reference.kind]
    if reference.table_path.name != filename or not reference.path.name.endswith(expected_suffix):
        raise GlobalLibraryError("Library kind does not match its table or path")
    if reference.registered:
        expected_type = (
            reference.path.is_file()
            if reference.kind is LibraryKind.SYMBOL
            else reference.path.is_dir()
        )
        if not expected_type:
            raise GlobalLibraryError(f"Registered library disappeared: {reference.path}")
    protected = install_roots or _default_install_roots(environment)
    if any(_within(reference.path, root) for root in protected):
        raise GlobalLibraryError(f"Library destination is protected: {reference.path}")
    if not _writable(reference.path):
        raise GlobalLibraryError(f"Library destination is not writable: {reference.path}")


def build_global_registration(
    reference: LibraryRef,
    *,
    environ: Mapping[str, str] | None = None,
    install_roots: tuple[Path, ...] = (),
) -> dict[Path, str]:
    validate_library_destination(
        reference, environ=environ, install_roots=install_roots
    )
    filename, root_name, _ = _ROOT_NAMES[reference.kind]
    if reference.table_path.exists():
        original = reference.table_path.read_text(encoding="utf-8-sig")
        try:
            root = parse_one(original)
        except (OSError, UnicodeError, SExprError) as error:
            raise GlobalLibraryError(f"{filename} is malformed: {error}") from error
        if root.head != root_name:
            raise GlobalLibraryError(f"{filename} has root {root.head!r}, expected {root_name!r}")
    else:
        original = f"({root_name}\n  (version 7)\n)\n"
        root = parse_one(original)
    for node in root.children:
        if node.head != "lib":
            continue
        fields = _fields(node)
        if fields.get("name") != reference.nickname:
            continue
        environment = dict(os.environ if environ is None else environ)
        existing = _resolve_uri(fields.get("uri", ""), environment)
        if existing == reference.path:
            return {}
        raise GlobalLibraryError(
            f"Library nickname {reference.nickname!r} is registered to a different path"
        )
    if not _writable(reference.table_path):
        raise GlobalLibraryError(f"Global table is not writable: {reference.table_path}")
    entry = (
        f'  (lib (name "{reference.nickname}") (type "KiCad") '
        f'(uri "{reference.path.as_posix()}") (options "") '
        '(descr "JLCEDA2KICAD personal library"))\n'
    )
    insertion = root.end - 1
    prefix = "" if original[:insertion].endswith("\n") else "\n"
    return {reference.table_path: original[:insertion] + prefix + entry + original[insertion:]}
```

- [ ] **Step 5: Run focused and project-table regression tests, then commit**

Run:

```powershell
python -m pytest tests/test_global_libraries.py tests/test_library_tables.py -q
python -m ruff check src/jlceda2kicad/global_libraries.py tests/test_global_libraries.py
python -m mypy src
```

Expected: all tests pass, Ruff is clean, and mypy reports success.

Commit:

```powershell
git add src/jlceda2kicad/global_libraries.py tests/test_global_libraries.py
git commit -m "feat: discover KiCad global libraries"
```

---

### Task 3: Structure-aware component renaming and global model validation

**Files:**
- Create: `src/jlceda2kicad/artifact_rewrite.py`
- Create: `tests/test_artifact_rewrite.py`
- Modify: `src/jlceda2kicad/import_validation.py`
- Modify: `tests/test_import_validation.py`

**Interfaces:**
- Consumes: `ArtifactSet`, the S-expression spans in `sexpr.py`, and existing `rewrite_footprint_models`.
- Produces: `validate_component_name(value: str, label: str) -> str`.
- Produces: `generated_names(artifacts: ArtifactSet, lcsc_id: str) -> tuple[str, str]`.
- Produces: `rewrite_symbol_component(text: str, lcsc_id: str, new_name: str, footprint_identifier: str | None) -> str`.
- Produces: `rewrite_footprint_component(text: str, new_name: str, *, model_mode: str, model_dir: Path) -> str`.
- Changes: `validate_footprint(path, *, model_root: Path | None = None)`; `None` keeps project-relative validation, a path requires absolute references within that root.

- [ ] **Step 1: Write failing rewrite and validation tests**

Create `tests/test_artifact_rewrite.py`:

```python
from pathlib import Path

import pytest

from jlceda2kicad.artifact_rewrite import (
    rewrite_footprint_component,
    rewrite_symbol_component,
    validate_component_name,
)
from jlceda2kicad.sexpr import parse_one


SYMBOL = '''(kicad_symbol_lib (version 20231120)
  (symbol "Old"
    (property "Value" "Old")
    (property "Footprint" "easyeda2kicad:Old")
    (property "LCSC Part" "C2040")
    (symbol "Old_1_1" (pin passive line (at 0 0 0) (length 2.54)
      (name "A") (number "1")))))'''


def test_renames_symbol_units_value_and_footprint_association() -> None:
    rewritten = rewrite_symbol_component(SYMBOL, "C2040", "电容 22uF", "Harulib:C0805-Haru")

    parse_one(rewritten)
    assert 'symbol "电容 22uF"' in rewritten
    assert 'symbol "电容 22uF_1_1"' in rewritten
    assert 'property "Value" "电容 22uF"' in rewritten
    assert 'property "Footprint" "Harulib:C0805-Haru"' in rewritten
    assert 'property "LCSC Part" "C2040"' in rewritten


@pytest.mark.parametrize("head", ['footprint "Old"', "module easyeda2kicad:Old"])
def test_renames_modern_and_legacy_footprint_with_absolute_model(
    tmp_path: Path, head: str
) -> None:
    text = f'''({head}
      (fp_text value "Old" (at 0 0) (layer "F.Fab"))
      (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
      (model "${{KIPRJMOD}}/libs/lcsc_project.3dshapes/Old.wrl"))'''
    models = tmp_path / "Haru Lib.3dshapes"

    rewritten = rewrite_footprint_component(
        text, "C0805-Haru", model_mode="step", model_dir=models
    )

    assert parse_one(rewritten).atoms[1].value == "C0805-Haru"
    assert 'fp_text value "C0805-Haru"' in rewritten
    assert (models / "Old.step").as_posix() in rewritten.replace("\\", "/")


@pytest.mark.parametrize("name", ["", "CON", "bad/name", "bad*name", "trailing. "])
def test_rejects_unsafe_component_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_component_name(name, "symbol")
```

Add to `tests/test_import_validation.py`:

```python
def test_global_model_reference_must_be_absolute_and_within_model_root(tmp_path: Path) -> None:
    model_root = tmp_path / "Haru.3dshapes"
    model_root.mkdir()
    footprint = tmp_path / "Haru.kicad_mod"
    footprint.write_text(
        f'(footprint "Haru" (model "{(model_root / "Haru.step").as_posix()}"))',
        encoding="utf-8",
    )

    result = validate_footprint(footprint, model_root=model_root)

    assert result.model_paths == ((model_root / "Haru.step").as_posix(),)
    footprint.write_text(
        f'(footprint "Haru" (model "{(tmp_path / "outside.step").as_posix()}"))',
        encoding="utf-8",
    )
    with pytest.raises(ImportValidationError, match="outside"):
        validate_footprint(footprint, model_root=model_root)
```

- [ ] **Step 2: Run tests and verify missing rewrite module/signature**

Run:

```powershell
python -m pytest tests/test_artifact_rewrite.py tests/test_import_validation.py -q
```

Expected: collection fails for the missing module and `model_root` parameter.

- [ ] **Step 3: Implement safe span replacements and symbol rewriting**

Create `artifact_rewrite.py` with name validation and span application:

```python
import json
import re
from pathlib import Path

from .models import ArtifactSet
from .sexpr import Atom, ListExpr, parse_one, rewrite_footprint_models


_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')
_WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)


def validate_component_name(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} name is empty")
    if normalized.endswith((".", " ")) or _WINDOWS_RESERVED.fullmatch(normalized):
        raise ValueError(f"{label} name is reserved on Windows")
    if any(ord(char) < 32 or char in _WINDOWS_FORBIDDEN for char in normalized):
        raise ValueError(f"{label} name contains a forbidden filename character")
    return normalized


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _apply(text: str, replacements: list[tuple[int, int, str]]) -> str:
    result = text
    for start, end, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _property_atom(symbol: ListExpr, name: str) -> Atom | None:
    for child in symbol.children:
        atoms = child.atoms
        if child.head == "property" and len(atoms) >= 3 and atoms[1].value == name:
            return atoms[2]
    return None


def rewrite_symbol_component(
    text: str, lcsc_id: str, new_name: str, footprint_identifier: str | None
) -> str:
    normalized = validate_component_name(new_name, "symbol")
    root = parse_one(text)
    symbols = tuple(child for child in root.children if child.head == "symbol")
    matches = tuple(
        symbol for symbol in symbols
        if (_property_atom(symbol, "LCSC Part") or Atom("", 0, 0)).value == lcsc_id
    )
    if len(matches) != 1:
        raise ValueError(f"expected one symbol for {lcsc_id}, found {len(matches)}")
    symbol = matches[0]
    old_name = symbol.atoms[1].value
    replacements = [(symbol.atoms[1].start, symbol.atoms[1].end, _quoted(normalized))]
    for child in symbol.children:
        if child.head == "symbol" and len(child.atoms) >= 2:
            child_name = child.atoms[1]
            if child_name.value.startswith(old_name + "_"):
                renamed = normalized + child_name.value[len(old_name):]
                replacements.append((child_name.start, child_name.end, _quoted(renamed)))
    for property_name, property_value in (
        ("Value", normalized),
        ("Footprint", footprint_identifier),
    ):
        if property_value is None:
            continue
        atom = _property_atom(symbol, property_name)
        if atom is None:
            insertion = f'\n    (property "{property_name}" {_quoted(property_value)})'
            replacements.append((symbol.end - 1, symbol.end - 1, insertion))
        else:
            replacements.append((atom.start, atom.end, _quoted(property_value)))
    return _apply(text, replacements)
```

Add the complete generated-name reader:

```python
def generated_names(artifacts: ArtifactSet, lcsc_id: str) -> tuple[str, str]:
    symbol_name = ""
    footprint_name = ""
    if artifacts.symbol_libraries:
        root = parse_one(artifacts.symbol_libraries[0].read_text(encoding="utf-8-sig"))
        matches = tuple(
            child
            for child in root.children
            if child.head == "symbol"
            and (_property_atom(child, "LCSC Part") or Atom("", 0, 0)).value == lcsc_id
        )
        if len(matches) != 1 or len(matches[0].atoms) < 2:
            raise ValueError(f"expected one generated symbol for {lcsc_id}")
        symbol_name = matches[0].atoms[1].value
    if artifacts.footprints:
        root = parse_one(artifacts.footprints[0].read_text(encoding="utf-8-sig"))
        if root.head not in {"footprint", "module"} or len(root.atoms) < 2:
            raise ValueError("generated footprint has no root name")
        footprint_name = root.atoms[1].value.rsplit(":", 1)[-1]
    return symbol_name, footprint_name
```

When inserting a missing symbol property, use a KiCad-valid hidden property
body rather than a bare two-atom property:

```python
            insertion = (
                f'\n    (property "{property_name}" {_quoted(property_value)} '
                '(at 0 0 0) (effects (font (size 1.27 1.27)) hide))'
            )
```

- [ ] **Step 4: Implement footprint rewriting and dual validation policy**

Add to `artifact_rewrite.py`:

```python
def rewrite_footprint_component(
    text: str, new_name: str, *, model_mode: str, model_dir: Path
) -> str:
    normalized = validate_component_name(new_name, "footprint")
    selected = rewrite_footprint_models(text, model_mode)
    root = parse_one(selected)
    if root.head not in {"footprint", "module"} or len(root.atoms) < 2:
        raise ValueError("converted output is not a footprint or module")
    replacements = [(root.atoms[1].start, root.atoms[1].end, _quoted(normalized))]
    for child in root.children:
        atoms = child.atoms
        if child.head == "fp_text" and len(atoms) >= 3 and atoms[1].value == "value":
            replacements.append((atoms[2].start, atoms[2].end, _quoted(normalized)))
        if child.head == "property" and len(atoms) >= 3 and atoms[1].value == "Value":
            replacements.append((atoms[2].start, atoms[2].end, _quoted(normalized)))
        if child.head == "model" and len(atoms) >= 2:
            filename = Path(atoms[1].value).name
            if model_mode == "step":
                filename = Path(filename).with_suffix(".step").name
            destination = (model_dir.resolve() / filename).as_posix()
            replacements.append((atoms[1].start, atoms[1].end, _quoted(destination)))
    return _apply(selected, replacements)
```

Change `validate_footprint` to accept `model_root`. Keep `_validate_model_path` unchanged for project mode; for global mode require `Path(model_path).is_absolute()`, reject temporary path segments, and require `Path(model_path).resolve().relative_to(model_root.resolve())` to succeed. Raise `ImportValidationError` with the offending path when it does not.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -m pytest tests/test_artifact_rewrite.py tests/test_import_validation.py tests/test_import_service.py::test_import_shadow_accepts_easyeda_legacy_module -q
python -m ruff check src/jlceda2kicad/artifact_rewrite.py src/jlceda2kicad/import_validation.py tests/test_artifact_rewrite.py tests/test_import_validation.py
python -m mypy src
```

Expected: all focused tests pass; legacy project import remains green.

Commit:

```powershell
git add src/jlceda2kicad/artifact_rewrite.py src/jlceda2kicad/import_validation.py tests/test_artifact_rewrite.py tests/test_import_validation.py
git commit -m "feat: rename imported KiCad artifacts"
```

---

### Task 4: Absolute backups and allowlisted multi-root transaction

**Files:**
- Create: `src/jlceda2kicad/absolute_backup.py`
- Create: `tests/test_absolute_backup.py`
- Modify: `src/jlceda2kicad/import_transaction.py`
- Modify: `tests/test_import_transaction.py`

**Interfaces:**
- Produces: `AbsoluteBackupRecord`, `AbsoluteBackupManifest`, `AbsoluteBackupManager` with `create`, `rollback`, and `prune` methods.
- Produces: `AtomicMultiRootTransaction(backup_manager, allowed_roots, allowed_files=(), replace=os.replace)` and `commit(staged_to_target) -> ImportReport`.
- Consumes: the existing `ImportReport` and same-volume staging behavior.

- [ ] **Step 1: Write failing absolute-backup and multi-root tests**

Create `tests/test_absolute_backup.py`:

```python
import hashlib
from pathlib import Path

from jlceda2kicad.absolute_backup import AbsoluteBackupManager


def test_absolute_backup_hashes_and_restores_multiple_roots(tmp_path: Path) -> None:
    first = tmp_path / "Roaming" / "sym-lib-table"
    second = tmp_path / "Documents" / "Harulib.kicad_sym"
    created = tmp_path / "Documents" / "Harulib.pretty" / "New.kicad_mod"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("table", encoding="utf-8")
    second.write_text("symbols", encoding="utf-8")
    manager = AbsoluteBackupManager(tmp_path / "app-data" / "backups", retention=5)

    manifest = manager.create((first, second, created))

    assert manifest.manifest_path.is_file()
    assert manifest.records[0].sha256 == hashlib.sha256(b"table").hexdigest()
    first.write_text("changed", encoding="utf-8")
    created.parent.mkdir(parents=True)
    created.write_text("partial", encoding="utf-8")
    assert manager.rollback(manifest) == ()
    assert first.read_text(encoding="utf-8") == "table"
    assert not created.exists()


def test_absolute_backup_prune_keeps_newest_five(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    manager = AbsoluteBackupManager(root, retention=5)
    for index in range(7):
        (root / f"20260715T00000{index}000000Z").mkdir(parents=True)

    removed = manager.prune()

    assert [path.name for path in removed] == [
        "20260715T000000000000Z",
        "20260715T000001000000Z",
    ]
    assert len(tuple(root.iterdir())) == 5
```

Add to `tests/test_import_transaction.py`:

```python
from jlceda2kicad.absolute_backup import AbsoluteBackupManager
from jlceda2kicad.import_transaction import AtomicMultiRootTransaction


def test_multi_root_transaction_rolls_back_after_second_replace_failure(tmp_path: Path) -> None:
    symbols = tmp_path / "symbols"
    footprints = tmp_path / "footprints" / "Haru.pretty"
    old = symbols / "Haru.kicad_sym"
    new = footprints / "New.kicad_mod"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    first_stage = tmp_path / "stage-symbol"
    second_stage = tmp_path / "stage-footprint"
    first_stage.write_text("new-symbol", encoding="utf-8")
    second_stage.write_text("new-footprint", encoding="utf-8")
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("locked")
        os.replace(source, target)

    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(symbols, footprints),
        replace=fail_second,
    )

    with pytest.raises(ImportTransactionError) as captured:
        transaction.commit({first_stage: old, second_stage: new})

    assert old.read_text(encoding="utf-8") == "old"
    assert not new.exists()
    assert captured.value.report.rollback_result == ()


def test_multi_root_transaction_rejects_non_allowlisted_target(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.write_text("data", encoding="utf-8")
    transaction = AtomicMultiRootTransaction(
        AbsoluteBackupManager(tmp_path / "backups"),
        allowed_roots=(tmp_path / "allowed",),
    )

    with pytest.raises(ImportTransactionError, match="allowlisted"):
        transaction.commit({staged: tmp_path / "outside" / "file"})
```

- [ ] **Step 2: Run focused tests and verify missing classes**

Run:

```powershell
python -m pytest tests/test_absolute_backup.py tests/test_import_transaction.py -q
```

Expected: collection fails for the absent backup manager and transaction.

- [ ] **Step 3: Implement absolute-path backup records and rollback**

Create `absolute_backup.py`. Store backup payloads by deterministic index and target-path digest so Windows drive letters never become relative path components. Use these imports and complete implementation:

```python
import hashlib
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ._json_store import write_json_atomic


@dataclass(frozen=True, slots=True)
class AbsoluteBackupRecord:
    target_path: str
    backup_name: str
    existed: bool
    size: int = 0
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class AbsoluteBackupManifest:
    backup_dir: Path
    records: tuple[AbsoluteBackupRecord, ...]

    @property
    def manifest_path(self) -> Path:
        return self.backup_dir / "manifest.json"


def _payload_name(index: int, target: Path) -> str:
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"{index:04d}-{digest}.bak"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class AbsoluteBackupManager:
    def __init__(self, backup_root: Path, retention: int = 5) -> None:
        self.backup_root = backup_root.resolve()
        self.retention = max(1, retention)

    def create(self, paths: tuple[Path, ...]) -> AbsoluteBackupManifest:
        targets = tuple(dict.fromkeys(path.resolve() for path in paths))
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = self.backup_root / stamp
        files_dir = backup_dir / "files"
        records: list[AbsoluteBackupRecord] = []
        for index, target in enumerate(targets):
            backup_name = _payload_name(index, target)
            if target.is_file():
                files_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, files_dir / backup_name)
                records.append(
                    AbsoluteBackupRecord(
                        str(target), backup_name, True, target.stat().st_size, _hash(target)
                    )
                )
            else:
                records.append(AbsoluteBackupRecord(str(target), backup_name, False))
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest = AbsoluteBackupManifest(backup_dir, tuple(records))
        write_json_atomic(
            manifest.manifest_path,
            {
                "created_at": stamp,
                "records": [asdict(record) for record in records],
            },
        )
        return manifest

    def rollback(self, manifest: AbsoluteBackupManifest) -> tuple[str, ...]:
        errors: list[str] = []
        for record in manifest.records:
            target = Path(record.target_path)
            try:
                if record.existed:
                    source = manifest.backup_dir / "files" / record.backup_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(f".{target.name}.{os.getpid()}.restore")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as error:
                errors.append(f"{target}: {error}")
        return tuple(errors)

    def prune(self) -> tuple[Path, ...]:
        if not self.backup_root.is_dir():
            return ()
        directories = sorted(path for path in self.backup_root.iterdir() if path.is_dir())
        removed: list[Path] = []
        for path in directories[: max(0, len(directories) - self.retention)]:
            shutil.rmtree(path)
            removed.append(path)
        return tuple(removed)
```

- [ ] **Step 4: Implement the allowlisted transaction**

Import `AbsoluteBackupManager`, then add this target guard and complete class to `import_transaction.py`:

```python
def _is_allowed_target(
    path: Path, allowed_roots: tuple[Path, ...], allowed_files: tuple[Path, ...]
) -> bool:
    resolved = path.resolve()
    if any(resolved == item.resolve() for item in allowed_files):
        return True
    return any(_is_within(resolved, root) for root in allowed_roots)


class AtomicMultiRootTransaction:
    def __init__(
        self,
        backup_manager: AbsoluteBackupManager,
        *,
        allowed_roots: tuple[Path, ...],
        allowed_files: tuple[Path, ...] = (),
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.backup_manager = backup_manager
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self.allowed_files = tuple(path.resolve() for path in allowed_files)
        self.replace = replace

    def commit(self, staged_to_target: Mapping[Path, Path]) -> ImportReport:
        if not staged_to_target:
            raise ImportTransactionError("没有可提交的文件。")
        for staged, target in staged_to_target.items():
            if not staged.is_file() or staged.stat().st_size == 0:
                raise ImportTransactionError(f"暂存输出为空或不存在：{staged}")
            if not _is_allowed_target(target, self.allowed_roots, self.allowed_files):
                raise ImportTransactionError(f"全局导入目标不在 allowlisted 路径中：{target}")
        targets = tuple(staged_to_target.values())
        manifest = self.backup_manager.create(targets)
        committed: list[Path] = []
        temporaries: list[Path] = []
        try:
            for staged, target in staged_to_target.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                temporaries.append(temporary)
                with staged.open("rb") as source, temporary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                self.replace(temporary, target)
                committed.append(target)
        except OSError as error:
            rollback_result = self.backup_manager.rollback(manifest)
            report = ImportReport(
                success=False,
                committed_paths=tuple(committed),
                backup_dir=manifest.backup_dir,
                rollback_result=rollback_result,
            )
            raise ImportTransactionError(f"全局导入提交失败：{error}", report) from error
        finally:
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)
        self.backup_manager.prune()
        return ImportReport(
            success=True,
            committed_paths=tuple(committed),
            backup_dir=manifest.backup_dir,
        )
```

- [ ] **Step 5: Run transaction regressions and commit**

Run:

```powershell
python -m pytest tests/test_absolute_backup.py tests/test_backup.py tests/test_import_transaction.py -q
python -m ruff check src/jlceda2kicad/absolute_backup.py src/jlceda2kicad/import_transaction.py tests/test_absolute_backup.py tests/test_import_transaction.py
python -m mypy src
```

Expected: new multi-root tests and all existing project transaction tests pass.

Commit:

```powershell
git add src/jlceda2kicad/absolute_backup.py src/jlceda2kicad/import_transaction.py tests/test_absolute_backup.py tests/test_import_transaction.py
git commit -m "feat: add multi-root import transactions"
```

---

### Task 5: Global artifact promotion and conflict preflight

**Files:**
- Modify: `src/jlceda2kicad/import_service.py`
- Modify: `src/jlceda2kicad/conflicts.py`
- Create: `tests/test_global_import_service.py`
- Modify: `tests/test_conflicts.py`

**Interfaces:**
- Consumes: `ImportOptions.target`, global registration updates, artifact rewrite functions, `AbsoluteBackupManager`, and `AtomicMultiRootTransaction`.
- Produces: global routing inside `import_shadow_artifacts(..., global_backup_root: Path | None = None)`.
- Produces: `find_import_conflicts(project_root: Path, artifacts: ArtifactSet, lcsc_id: str, options: ImportOptions) -> tuple[str, ...]` for both scopes.
- Changes: `ImportServiceError` retains an optional failed `ImportReport` so rollback details reach the UI.
- Preserves: `build_formal_requests` and existing project import behavior.

- [ ] **Step 1: Write an end-to-end global import test**

Create `tests/test_global_import_service.py` with these imports and the complete artifact fixture:

```python
from pathlib import Path

import pytest

from jlceda2kicad.import_service import ImportServiceError, import_shadow_artifacts
from jlceda2kicad.import_transaction import AtomicMultiRootTransaction, ImportTransactionError
from jlceda2kicad.models import (
    ArtifactSet,
    ConflictPolicy,
    ImportOptions,
    ImportReport,
    ImportScope,
    ImportTarget,
    LibraryKind,
    LibraryRef,
)


def _write_shadow_artifacts(shadow: Path) -> ArtifactSet:
    libs = shadow / "libs"
    pretty = libs / "lcsc_project.pretty"
    models = libs / "lcsc_project.3dshapes"
    pretty.mkdir(parents=True)
    models.mkdir()
    symbol = libs / "lcsc_project.kicad_sym"
    symbol.write_text(
        '''(kicad_symbol_lib (version 20231120)
          (symbol "NewPart"
            (property "Value" "NewPart")
            (property "Footprint" "easyeda2kicad:NewPart")
            (property "LCSC Part" "C2040")
            (symbol "NewPart_1_1" (pin passive line (at 0 0 0) (length 2.54)
              (name "A") (number "1")))))''',
        encoding="utf-8",
    )
    footprint = pretty / "NewPart.kicad_mod"
    footprint.write_text(
        '''(footprint "NewPart"
          (fp_text value "NewPart" (at 0 0) (layer "F.Fab"))
          (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
          (model "${KIPRJMOD}/libs/lcsc_project.3dshapes/NewPart.wrl"))''',
        encoding="utf-8",
    )
    step = models / "NewPart.step"
    wrl = models / "NewPart.wrl"
    step.write_text("ISO-10303-21;", encoding="utf-8")
    wrl.write_text("#VRML V2.0 utf8", encoding="utf-8")
    return ArtifactSet(
        shadow,
        symbol_libraries=(symbol,),
        footprints=(footprint,),
        step_models=(step,),
        wrl_models=(wrl,),
    )
```

Add this main acceptance test:

```python
def test_imports_custom_names_into_existing_global_libraries(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    config = tmp_path / "Roaming" / "kicad" / "10.0"
    config.mkdir(parents=True)
    symbols = tmp_path / "Documents" / "symbols" / "Harulib.kicad_sym"
    footprints = tmp_path / "Documents" / "footprints" / "Harulib.pretty"
    symbols.parent.mkdir(parents=True)
    footprints.mkdir(parents=True)
    symbols.write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Keep" (property "LCSC Part" "C1")))',
        encoding="utf-8",
    )
    sym_table = config / "sym-lib-table"
    fp_table = config / "fp-lib-table"
    sym_table.write_text(
        f'(sym_lib_table (version 7) (lib (name "Harulib") (type "KiCad") (uri "{symbols.as_posix()}")))',
        encoding="utf-8",
    )
    fp_table.write_text(
        f'(fp_lib_table (version 7) (lib (name "Harulib") (type "KiCad") (uri "{footprints.as_posix()}")))',
        encoding="utf-8",
    )
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef("Harulib", LibraryKind.SYMBOL, symbols, sym_table),
        footprint_library=LibraryRef("Harulib", LibraryKind.FOOTPRINT, footprints, fp_table),
        symbol_name="22uF 25V",
        footprint_name="C0805-Haru",
    )
    options = ImportOptions(step=True, wrl=False, target=target)

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        options,
        global_backup_root=tmp_path / "app-data" / "backups" / "global",
    )

    symbol_text = symbols.read_text(encoding="utf-8")
    footprint_file = footprints / "C0805-Haru.kicad_mod"
    footprint_text = footprint_file.read_text(encoding="utf-8")
    assert 'symbol "Keep"' in symbol_text
    assert 'symbol "22uF 25V"' in symbol_text
    assert 'property "Footprint" "Harulib:C0805-Haru"' in symbol_text
    assert footprint_file.is_file()
    assert (footprints.with_suffix(".3dshapes") / "NewPart.step").as_posix() in footprint_text
    assert report.footprint_association == "Harulib:C0805-Haru"
    assert report.symbol_destination == symbols
    assert report.footprint_destination == footprint_file
    assert report.backup_dir is not None


def _pending_target(tmp_path: Path) -> ImportTarget:
    config = tmp_path / "config"
    config.mkdir()
    sym_table = config / "sym-lib-table"
    fp_table = config / "fp-lib-table"
    sym_table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    fp_table.write_text("(fp_lib_table (version 7))", encoding="utf-8")
    return ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Symbols", LibraryKind.SYMBOL, tmp_path / "Symbols.kicad_sym",
            sym_table, registered=False
        ),
        footprint_library=LibraryRef(
            "Footprints", LibraryKind.FOOTPRINT, tmp_path / "Footprints.pretty",
            fp_table, registered=False
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )


@pytest.mark.parametrize(
    ("policy", "outcome"),
    [
        (ConflictPolicy.CANCEL, "cancel"),
        (ConflictPolicy.SKIP_EXISTING, "original"),
        (ConflictPolicy.OVERWRITE_COMPONENT, "rewritten"),
    ],
)
def test_global_footprint_conflict_policies(
    tmp_path: Path, policy: ConflictPolicy, outcome: str
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = _pending_target(tmp_path)
    assert target.footprint_library is not None
    target.footprint_library.path.mkdir()
    destination = target.footprint_library.path / "CustomFootprint.kicad_mod"
    destination.write_text("original", encoding="utf-8")
    options = ImportOptions(
        step=False, wrl=False, conflict_policy=policy, target=target
    )

    if outcome == "cancel":
        with pytest.raises(ImportServiceError, match="CustomFootprint"):
            import_shadow_artifacts(
                tmp_path / "project",
                shadow,
                "C2040",
                artifacts,
                options,
                global_backup_root=tmp_path / "backups",
            )
        assert destination.read_text(encoding="utf-8") == "original"
        return

    import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        options,
        global_backup_root=tmp_path / "backups",
    )
    content = destination.read_text(encoding="utf-8")
    if outcome == "original":
        assert content == "original"
    else:
        assert 'footprint "CustomFootprint"' in content
```

Add these registration and guard tests to the same module:

```python
def test_pending_libraries_register_both_global_tables(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    config = tmp_path / "config"
    config.mkdir()
    sym_table = config / "sym-lib-table"
    fp_table = config / "fp-lib-table"
    sym_table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    fp_table.write_text("(fp_lib_table (version 7))", encoding="utf-8")
    symbols = tmp_path / "新库" / "Symbols.kicad_sym"
    footprints = tmp_path / "新库" / "Footprints.pretty"
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "MySymbols", LibraryKind.SYMBOL, symbols, sym_table, registered=False
        ),
        footprint_library=LibraryRef(
            "MyFootprints", LibraryKind.FOOTPRINT, footprints, fp_table, registered=False
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )

    report = import_shadow_artifacts(
        tmp_path / "project",
        shadow,
        "C2040",
        artifacts,
        ImportOptions(step=True, wrl=False, target=target),
        global_backup_root=tmp_path / "backups",
    )

    assert '(name "MySymbols")' in sym_table.read_text(encoding="utf-8")
    assert '(name "MyFootprints")' in fp_table.read_text(encoding="utf-8")
    assert set(report.library_registration) == {
        "MySymbols (symbol)",
        "MyFootprints (footprint)",
    }


def test_global_import_requires_backup_root_before_writing(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Symbols",
            LibraryKind.SYMBOL,
            tmp_path / "Symbols.kicad_sym",
            tmp_path / "sym-lib-table",
            registered=False,
        ),
        footprint_library=LibraryRef(
            "Footprints",
            LibraryKind.FOOTPRINT,
            tmp_path / "Footprints.pretty",
            tmp_path / "fp-lib-table",
            registered=False,
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )

    with pytest.raises(ImportServiceError, match="backup"):
        import_shadow_artifacts(
            tmp_path / "project", shadow, "C2040", artifacts, ImportOptions(target=target)
        )

    assert not target.symbol_library.path.exists()
    assert not target.footprint_library.path.exists()


def test_conflicting_global_nickname_aborts_before_library_write(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    table = tmp_path / "sym-lib-table"
    table.write_text(
        f'(sym_lib_table (version 7) (lib (name "Haru") (type "KiCad") '
        f'(uri "{(tmp_path / "old.kicad_sym").as_posix()}")))',
        encoding="utf-8",
    )
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Haru", LibraryKind.SYMBOL, tmp_path / "new.kicad_sym", table, registered=False
        ),
        footprint_library=LibraryRef(
            "Foot", LibraryKind.FOOTPRINT, tmp_path / "Foot.pretty",
            tmp_path / "fp-lib-table", registered=False
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )

    with pytest.raises(ImportServiceError, match="different path"):
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(target=target),
            global_backup_root=tmp_path / "backups",
        )

    assert not target.symbol_library.path.exists()


def test_transaction_failure_report_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow = tmp_path / "shadow"
    artifacts = _write_shadow_artifacts(shadow)
    sym_table = tmp_path / "sym-lib-table"
    fp_table = tmp_path / "fp-lib-table"
    sym_table.write_text("(sym_lib_table (version 7))", encoding="utf-8")
    fp_table.write_text("(fp_lib_table (version 7))", encoding="utf-8")
    target = ImportTarget(
        scope=ImportScope.GLOBAL,
        symbol_library=LibraryRef(
            "Sym", LibraryKind.SYMBOL, tmp_path / "Sym.kicad_sym", sym_table, False
        ),
        footprint_library=LibraryRef(
            "Foot", LibraryKind.FOOTPRINT, tmp_path / "Foot.pretty", fp_table, False
        ),
        symbol_name="CustomSymbol",
        footprint_name="CustomFootprint",
    )
    failed = ImportReport(
        success=False,
        backup_dir=tmp_path / "backups" / "failed",
        rollback_result=("locked restore",),
    )

    def fail_commit(self: object, mappings: object) -> ImportReport:
        raise ImportTransactionError("forced failure", failed)

    monkeypatch.setattr(AtomicMultiRootTransaction, "commit", fail_commit)

    with pytest.raises(ImportServiceError) as captured:
        import_shadow_artifacts(
            tmp_path / "project",
            shadow,
            "C2040",
            artifacts,
            ImportOptions(target=target),
            global_backup_root=tmp_path / "backups",
        )

    assert captured.value.report == failed
```

- [ ] **Step 2: Run the new service test and verify project-only behavior fails it**

Run:

```powershell
python -m pytest tests/test_global_import_service.py -q
```

Expected: tests fail because `import_shadow_artifacts` ignores `ImportScope.GLOBAL` and does not accept `global_backup_root`.

- [ ] **Step 3: Add exact-name collision support to symbol merging**

Keep `merge_symbol_library`'s API. Ensure its incoming-name set comes from the already-renamed incoming component, and keep collision matching as:

```python
    collisions = tuple(
        symbol
        for symbol in _top_level_symbols(existing_root)
        if _symbol_name(symbol) in incoming_names
        or _property_value(symbol, "LCSC Part") == lcsc_id
    )
```

Add this exact regression to `tests/test_conflicts.py`:

```python
def test_overwrite_removes_name_and_lcsc_collisions_only() -> None:
    existing = '''(kicad_symbol_lib (version 20231120)
      (symbol "Keep" (property "LCSC Part" "C1"))
      (symbol "Custom" (property "LCSC Part" "C2"))
      (symbol "OldName" (property "LCSC Part" "C2040")))'''
    incoming = '''(kicad_symbol_lib (version 20231120)
      (symbol "Custom" (property "LCSC Part" "C2040")))'''

    result = merge_symbol_library(
        existing, incoming, "C2040", ConflictPolicy.OVERWRITE_COMPONENT
    )

    assert 'symbol "Keep"' in result.text
    assert 'symbol "OldName"' not in result.text
    assert result.text.count('symbol "Custom"') == 1
    assert set(result.overwritten_names) == {"Custom", "OldName"}


def test_cancel_reports_the_existing_name_for_same_lcsc_id() -> None:
    existing = '''(kicad_symbol_lib (version 20231120)
      (symbol "OldName" (property "LCSC Part" "C2040")))'''
    incoming = '''(kicad_symbol_lib (version 20231120)
      (symbol "NewName" (property "LCSC Part" "C2040")))'''

    with pytest.raises(ComponentConflictError, match="OldName"):
        merge_symbol_library(existing, incoming, "C2040", ConflictPolicy.CANCEL)
```

- [ ] **Step 4: Implement the global promotion branch**

Change the public signature:

```python
def import_shadow_artifacts(
    project_root: Path,
    shadow_root: Path,
    lcsc_id: str,
    preview_artifacts: ArtifactSet,
    options: ImportOptions,
    *,
    backup_count: int = 5,
    global_backup_root: Path | None = None,
) -> ImportReport:
```

Change the error type before routing:

```python
class ImportServiceError(RuntimeError):
    def __init__(self, message: str, report: ImportReport | None = None) -> None:
        super().__init__(message)
        self.report = report or ImportReport(success=False)
```

At its start, route global targets to `_import_global_shadow_artifacts`. That helper must perform this exact sequence:

1. Validate required symbol/footprint references and custom names.
2. Discover formal outputs and clear the commit staging directory.
3. Extract the LCSC symbol, compute `nickname:footprint_name`, structurally rename it, merge it into the selected symbol library, and stage the merged library.
4. Require exactly one selected footprint for the single custom footprint name, rewrite it and its models, validate with `model_root=target.model_dir`, and stage `<footprint_name>.kicad_mod`.
5. Map selected `.stp`/`.step` to `.step` and WRL files to their original names under `target.model_dir`.
6. Apply file conflict policy before checking that every rewritten model node has an existing or planned target.
7. Build registration updates only for selected libraries that will exist after the transaction and stage those table texts.
8. Allowlist the symbol parent, footprint directory, model directory, and exact global table files; commit with `AtomicMultiRootTransaction` and `AbsoluteBackupManager(global_backup_root, backup_count)`.
9. Return `ImportReport` with committed paths, warnings, registration strings, backup/rollback data, destinations, model directory, and association.

Use these validation guards:

```python
def _required_library(options: ImportOptions, kind: LibraryKind) -> LibraryRef:
    reference = (
        options.target.symbol_library
        if kind is LibraryKind.SYMBOL
        else options.target.footprint_library
    )
    if reference is None or reference.kind is not kind:
        raise ImportServiceError(f"Global {kind.value} library is not selected")
    return reference


def _required_name(value: str | None, label: str) -> str:
    if value is None:
        raise ImportServiceError(f"Global {label} name is not set")
    try:
        return validate_component_name(value, label)
    except ValueError as error:
        raise ImportServiceError(str(error)) from error
```

If no staged mappings remain after skip policy, return a successful no-op report with warnings and destination metadata without creating a backup.

Implement the helper with the following complete control flow; keep the current
project-local body as the non-global branch:

```python
def _import_global_shadow_artifacts(
    shadow_root: Path,
    lcsc_id: str,
    preview_artifacts: ArtifactSet,
    options: ImportOptions,
    *,
    backup_count: int,
    global_backup_root: Path | None,
) -> ImportReport:
    if global_backup_root is None:
        raise ImportServiceError("Global import backup root is not configured")
    normalized = normalize_lcsc_id(lcsc_id)
    symbol_ref = _required_library(options, LibraryKind.SYMBOL) if options.symbol else None
    needs_footprint_library = options.footprint or options.step or options.wrl
    footprint_ref = (
        _required_library(options, LibraryKind.FOOTPRINT)
        if needs_footprint_library
        else None
    )
    symbol_name = _required_name(options.target.symbol_name, "symbol") if options.symbol else None
    footprint_name = (
        _required_name(options.target.footprint_name, "footprint")
        if options.footprint
        else None
    )
    model_dir = footprint_ref.path.with_suffix(".3dshapes") if footprint_ref else None
    association = (
        f"{footprint_ref.nickname}:{footprint_name}"
        if options.symbol and options.footprint and footprint_ref and footprint_name
        else None
    )
    formal = discover_artifacts(shadow_root)
    staging_root = shadow_root / ".jlceda2kicad-global-commit"
    shutil.rmtree(staging_root, ignore_errors=True)
    mappings: dict[Path, Path] = {}
    warnings = list(formal.warnings)
    registration: list[str] = []
    symbol_validation = None
    footprint_validations: list[ArtifactValidation] = []
    try:
        if options.symbol and symbol_ref and symbol_name:
            if not formal.symbol_libraries:
                raise ImportServiceError("正式转换没有生成符号库。")
            incoming = extract_symbol_component_library(
                formal.symbol_libraries[0].read_text(encoding="utf-8-sig"), normalized
            )
            incoming = rewrite_symbol_component(incoming, normalized, symbol_name, association)
            incoming_stage = _stage_text(staging_root, "incoming.kicad_sym", incoming)
            symbol_validation = validate_symbol_library(incoming_stage)
            existing = (
                symbol_ref.path.read_text(encoding="utf-8-sig")
                if symbol_ref.path.is_file()
                else None
            )
            merge = merge_symbol_library(
                existing, incoming, normalized, options.conflict_policy
            )
            if merge.skipped:
                warnings.append(f"符号 {symbol_name} 已存在，已按策略跳过。")
            else:
                merged_stage = _stage_text(
                    staging_root, f"symbols/{symbol_ref.path.name}", merge.text
                )
                validate_symbol_library(merged_stage)
                mappings[merged_stage] = symbol_ref.path

        selected_footprints = (
            _select_by_preview(formal.footprints, preview_artifacts.footprints)
            if options.footprint
            else ()
        )
        if options.footprint and len(selected_footprints) != 1:
            raise ImportServiceError(
                f"全局自定义名称要求一个封装，实际发现 {len(selected_footprints)} 个。"
            )
        model_mode = "wrl" if options.wrl else "step" if options.step else "none"
        footprint_mappings: dict[Path, Path] = {}
        if selected_footprints and footprint_ref and footprint_name and model_dir:
            source = selected_footprints[0]
            rewritten = rewrite_footprint_component(
                source.read_text(encoding="utf-8-sig"),
                footprint_name,
                model_mode=model_mode,
                model_dir=model_dir,
            )
            staged = _stage_text(
                staging_root,
                f"footprints/{footprint_name}.kicad_mod",
                rewritten,
            )
            footprint_validations.append(validate_footprint(staged, model_root=model_dir))
            footprint_mappings[staged] = footprint_ref.path / f"{footprint_name}.kicad_mod"

        model_mappings: dict[Path, Path] = {}
        if options.step and model_dir:
            selected_steps = _select_by_preview(formal.step_models, preview_artifacts.step_models)
            if not selected_steps:
                warnings.append("正式转换没有生成 STEP 模型。")
            for model in selected_steps:
                model_mappings[model] = model_dir / model.with_suffix(".step").name
        if options.wrl and model_dir:
            selected_wrl = _select_by_preview(formal.wrl_models, preview_artifacts.wrl_models)
            if not selected_wrl:
                warnings.append("正式转换没有生成 WRL 模型。")
            for model in selected_wrl:
                model_mappings[model] = model_dir / model.name

        selected_files, skipped_files = resolve_file_conflicts(
            footprint_mappings | model_mappings, options.conflict_policy
        )
        mappings.update(selected_files)
        warnings.extend(f"文件已存在，按策略跳过：{path.name}" for path in skipped_files)
        planned_targets = set(selected_files.values())
        for validation in footprint_validations:
            for model_path in validation.model_paths:
                target_path = Path(model_path).resolve()
                if not target_path.is_file() and target_path not in planned_targets:
                    raise ImportServiceError(f"模型引用没有对应的可提交文件：{model_path}")
        if symbol_validation is not None:
            for validation in footprint_validations:
                warnings.extend(symbol_validation.compare_pad_numbers(validation))

        registration_updates: dict[Path, str] = {}
        if symbol_ref and (symbol_ref.path.is_file() or symbol_ref.path in mappings.values()):
            updates = build_global_registration(symbol_ref)
            registration_updates.update(updates)
            if updates:
                registration.append(f"{symbol_ref.nickname} (symbol)")
        if footprint_ref and (
            footprint_ref.path.is_dir()
            or any(target.parent == footprint_ref.path for target in mappings.values())
        ):
            updates = build_global_registration(footprint_ref)
            registration_updates.update(updates)
            if updates:
                registration.append(f"{footprint_ref.nickname} (footprint)")
        for table_path, table_text in registration_updates.items():
            staged = _stage_text(staging_root, f"tables/{table_path.name}", table_text)
            mappings[staged] = table_path
    except (OSError, UnicodeError, ValueError, ComponentConflictError) as error:
        raise ImportServiceError(str(error)) from error

    symbol_destination = symbol_ref.path if symbol_ref and symbol_name else None
    footprint_destination = (
        footprint_ref.path / f"{footprint_name}.kicad_mod"
        if footprint_ref and footprint_name
        else None
    )
    if not mappings:
        return ImportReport(
            success=True,
            warnings=tuple(warnings) or ("没有需要提交的文件。",),
            library_registration=tuple(registration),
            symbol_destination=symbol_destination,
            footprint_destination=footprint_destination,
            model_directory=model_dir,
            footprint_association=association,
        )
    allowed_roots = tuple(
        dict.fromkeys(
            path.resolve()
            for path in (
                symbol_ref.path.parent if symbol_ref else None,
                footprint_ref.path if footprint_ref else None,
                model_dir,
            )
            if path is not None
        )
    )
    allowed_files = tuple(path.resolve() for path in registration_updates)
    try:
        committed = AtomicMultiRootTransaction(
            AbsoluteBackupManager(global_backup_root, retention=backup_count),
            allowed_roots=allowed_roots,
            allowed_files=allowed_files,
        ).commit(mappings)
    except ImportTransactionError as error:
        raise ImportServiceError(str(error), error.report) from error
    return ImportReport(
        success=committed.success,
        committed_paths=committed.committed_paths,
        warnings=tuple(warnings),
        library_registration=tuple(registration),
        backup_dir=committed.backup_dir,
        rollback_result=committed.rollback_result,
        symbol_destination=symbol_destination,
        footprint_destination=footprint_destination,
        model_directory=model_dir,
        footprint_association=association,
    )
```

- [ ] **Step 5: Move conflict preflight into the service**

Implement `find_import_conflicts`. For project scope, move the existing `_find_conflicts` logic without changing paths. For global scope:

```python
def _global_conflicts(artifacts: ArtifactSet, lcsc_id: str, options: ImportOptions) -> list[str]:
    target = options.target
    conflicts: list[str] = []
    if options.symbol and target.symbol_library and target.symbol_name:
        existing = target.symbol_library.path
        if existing.is_file() and artifacts.symbol_libraries:
            incoming = extract_symbol_component_library(
                artifacts.symbol_libraries[0].read_text(encoding="utf-8-sig"), lcsc_id
            )
            incoming = rewrite_symbol_component(incoming, lcsc_id, target.symbol_name, None)
            try:
                merge_symbol_library(
                    existing.read_text(encoding="utf-8-sig"),
                    incoming,
                    lcsc_id,
                    ConflictPolicy.CANCEL,
                )
            except ComponentConflictError as error:
                conflicts.append(str(error))
    if options.footprint and target.footprint_library and target.footprint_name:
        path = target.footprint_library.path / f"{target.footprint_name}.kicad_mod"
        if path.exists():
            conflicts.append(str(path))
    if target.model_dir is not None:
        for model in artifacts.step_models + artifacts.wrl_models:
            name = model.with_suffix(".step").name if model.suffix.lower() == ".stp" else model.name
            if (target.model_dir / name).exists():
                conflicts.append(str(target.model_dir / name))
    return conflicts
```

Wrap filesystem and parse failures into a conflict message that names the unreadable target rather than silently treating it as conflict-free.

Before finishing this task, populate destination metadata in the existing
project-local return paths so replacing the old message box does not remove its
“open library directory” behavior:

```python
    project_footprint_destination = next(
        (
            target
            for target in mappings.values()
            if target.suffix.casefold() == ".kicad_mod"
        ),
        None,
    )
    project_symbol_destination = (
        target_symbol
        if options.symbol
        and (target_symbol.is_file() or target_symbol in mappings.values())
        else None
    )
```

Add `symbol_destination=project_symbol_destination`,
`footprint_destination=project_footprint_destination`, and
`model_directory=target_model_dir if options.step or options.wrl else None` to
both the project no-op report and its final successful report. Do not invent a
project association value; leave `footprint_association=None` because this
feature only guarantees rewritten associations in global mode.

- [ ] **Step 6: Run global and project import suites, then commit**

Run:

```powershell
python -m pytest tests/test_global_import_service.py tests/test_import_service.py tests/test_conflicts.py -q
python -m ruff check src/jlceda2kicad/import_service.py src/jlceda2kicad/conflicts.py tests/test_global_import_service.py tests/test_conflicts.py
python -m mypy src
```

Expected: global acceptance tests pass and every existing project import test remains green.

Commit:

```powershell
git add src/jlceda2kicad/import_service.py src/jlceda2kicad/conflicts.py tests/test_global_import_service.py tests/test_conflicts.py
git commit -m "feat: import into global personal libraries"
```

---

### Task 6: Target-library and result Qt widgets

**Files:**
- Create: `src/jlceda2kicad/library_target_widget.py`
- Create: `tests/test_library_target_widget.py`

**Interfaces:**
- Consumes: `AppSettings`, `ImportScope`, `ImportTarget`, `LibraryRef`, catalog discovery, pending-library construction, and `ImportReport`.
- Produces: `LibraryTargetWidget` with `refresh`, `set_generated_names`, `build_target(import_symbol, import_footprint, import_models)`, and `apply_settings`.
- Produces: `NewLibraryDialog` for an uncommitted symbol or footprint reference.
- Produces: `ImportResultDialog` with open-directory and copy-path actions.

- [ ] **Step 1: Write offscreen widget tests**

Create `tests/test_library_target_widget.py`:

```python
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from jlceda2kicad.library_target_widget import ImportResultDialog, LibraryTargetWidget
from jlceda2kicad.models import ImportReport, ImportScope
from jlceda2kicad.settings import AppSettings

pytestmark = pytest.mark.usefixtures("qapp")


def _global_tables(config: Path, root: Path) -> None:
    config.mkdir(parents=True)
    symbol = root / "symbols" / "Harulib.kicad_sym"
    footprint = root / "footprints" / "Harulib.pretty"
    symbol.parent.mkdir(parents=True)
    footprint.mkdir(parents=True)
    symbol.write_text("(kicad_symbol_lib (version 20231120))", encoding="utf-8")
    (config / "sym-lib-table").write_text(
        f'(sym_lib_table (version 7) (lib (name "Harulib") (type "KiCad") (uri "{symbol.as_posix()}")))',
        encoding="utf-8",
    )
    (config / "fp-lib-table").write_text(
        f'(fp_lib_table (version 7) (lib (name "Harulib") (type "KiCad") (uri "{footprint.as_posix()}")))',
        encoding="utf-8",
    )


def test_global_widget_selects_existing_libraries_and_custom_names(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "用户 库")
    widget = LibraryTargetWidget(
        AppSettings(
            last_import_scope=ImportScope.GLOBAL,
            last_symbol_library="Harulib",
            last_footprint_library="Harulib",
        ),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    widget.set_generated_names("OriginalSymbol", "OriginalFootprint")
    widget.symbol_name.setText("22uF 25V")
    widget.footprint_name.setText("C0805-Haru")
    target = widget.build_target()

    assert target.scope is ImportScope.GLOBAL
    assert target.symbol_library is not None
    assert target.symbol_library.nickname == "Harulib"
    assert target.footprint_library is not None
    assert target.footprint_library.nickname == "Harulib"
    assert target.symbol_name == "22uF 25V"
    assert target.footprint_name == "C0805-Haru"
    assert "Harulib.3dshapes" in widget.model_path.text()


def test_project_scope_hides_global_controls(qtbot: object, tmp_path: Path) -> None:
    widget = LibraryTargetWidget(AppSettings(), kicad_version="10.0.4", config_root=tmp_path)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget.build_target().scope is ImportScope.PROJECT
    assert widget.global_fields.isHidden()
```

Add these exact edge-case tests:

```python
from jlceda2kicad.global_libraries import pending_library
from jlceda2kicad.models import LibraryKind


def test_pending_symbol_and_footprint_libraries_remain_independent(
    qtbot: object, tmp_path: Path
) -> None:
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=tmp_path / "config",
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    symbol = pending_library(
        LibraryKind.SYMBOL,
        "MySymbols",
        tmp_path / "symbols" / "MySymbols.kicad_sym",
        tmp_path / "config" / "sym-lib-table",
    )
    footprint = pending_library(
        LibraryKind.FOOTPRINT,
        "MyFootprints",
        tmp_path / "footprints" / "MyFootprints.pretty",
        tmp_path / "config" / "fp-lib-table",
    )

    widget.add_pending_library(symbol)
    widget.add_pending_library(footprint)
    widget.set_generated_names("Symbol", "Footprint")
    target = widget.build_target()

    assert target.symbol_library == symbol
    assert target.footprint_library == footprint


def test_stale_saved_nicknames_do_not_select_an_unrelated_library(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(
            last_import_scope=ImportScope.GLOBAL,
            last_symbol_library="Missing",
            last_footprint_library="Missing",
        ),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget.symbol_library.currentIndex() == -1
    assert widget.footprint_library.currentIndex() == -1


def test_unsafe_custom_name_is_rejected(qtbot: object, tmp_path: Path) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(0)
    widget.footprint_library.setCurrentIndex(0)
    widget.set_generated_names("bad/name", "Footprint")

    with pytest.raises(ValueError, match="forbidden"):
        widget.build_target()


def test_symbol_only_target_does_not_require_a_footprint_library(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    _global_tables(config, tmp_path / "libraries")
    widget = LibraryTargetWidget(
        AppSettings(last_import_scope=ImportScope.GLOBAL),
        kicad_version="10.0.4",
        config_root=config,
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.symbol_library.setCurrentIndex(0)
    widget.footprint_library.setCurrentIndex(-1)
    widget.set_generated_names("SymbolOnly", "")

    target = widget.build_target(
        import_symbol=True, import_footprint=False, import_models=False
    )

    assert target.symbol_library is not None
    assert target.footprint_library is None
    assert target.symbol_name == "SymbolOnly"
    assert target.footprint_name is None


def test_malformed_catalog_does_not_prevent_widget_creation(
    qtbot: object, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "sym-lib-table").write_text("(sym_lib_table (broken)", encoding="utf-8")

    widget = LibraryTargetWidget(
        AppSettings(), kicad_version="10.0.4", config_root=config
    )
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget.symbol_library.count() == 0
    assert "sym-lib-table" in widget.catalog_error


def test_result_dialog_copies_every_reported_path(qtbot: object, tmp_path: Path) -> None:
    report = ImportReport(
        success=True,
        symbol_destination=tmp_path / "Symbols.kicad_sym",
        footprint_destination=tmp_path / "Footprints.pretty" / "Part.kicad_mod",
        model_directory=tmp_path / "Footprints.3dshapes",
        backup_dir=tmp_path / "backups" / "one",
        footprint_association="Footprints:Part",
    )
    dialog = ImportResultDialog(report)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog._copy_paths()

    copied = QApplication.clipboard().text().splitlines()
    assert copied == [
        str(report.symbol_destination),
        str(report.footprint_destination),
        str(report.model_directory),
        str(report.backup_dir),
    ]
```

- [ ] **Step 2: Run the widget tests and verify the module is missing**

Run with the offscreen platform:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/test_library_target_widget.py -q
```

Expected: collection fails because `library_target_widget.py` does not exist.

- [ ] **Step 3: Implement the target widget and pending selectors**

Build `LibraryTargetWidget` as a `QGroupBox("导入目标与名称")`. Its public controls are `scope`, `symbol_library`, `footprint_library`, `symbol_name`, `footprint_name`, `model_path`, and `global_fields`. Populate scope data with string enum values, store each `LibraryRef` as combo item data, and preserve pending entries when refreshing. The constructor and pending method must use this structure:

```python
class LibraryTargetWidget(QGroupBox):
    def __init__(
        self,
        settings: AppSettings,
        *,
        kicad_version: str,
        config_root: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("导入目标与名称", parent)
        self.settings = settings
        self.kicad_version = kicad_version
        self.config_root = config_root
        self.catalog_error = ""
        self.scope = QComboBox()
        self.scope.addItem("当前工程库", ImportScope.PROJECT.value)
        self.scope.addItem("KiCad 全局个人库", ImportScope.GLOBAL.value)
        self.symbol_library = QComboBox()
        self.footprint_library = QComboBox()
        self.symbol_name = QLineEdit()
        self.footprint_name = QLineEdit()
        self.model_path = QLineEdit()
        self.model_path.setReadOnly(True)
        self.refresh_button = QPushButton("刷新库列表")
        self.new_symbol_button = QPushButton("新建符号库")
        self.new_footprint_button = QPushButton("新建封装库")
        self.global_fields = QWidget()
        fields = QFormLayout(self.global_fields)
        symbol_row = QWidget()
        symbol_layout = QHBoxLayout(symbol_row)
        symbol_layout.setContentsMargins(0, 0, 0, 0)
        symbol_layout.addWidget(self.symbol_library, 1)
        symbol_layout.addWidget(self.new_symbol_button)
        footprint_row = QWidget()
        footprint_layout = QHBoxLayout(footprint_row)
        footprint_layout.setContentsMargins(0, 0, 0, 0)
        footprint_layout.addWidget(self.footprint_library, 1)
        footprint_layout.addWidget(self.new_footprint_button)
        fields.addRow("符号库", symbol_row)
        fields.addRow("封装库", footprint_row)
        fields.addRow("符号名称", self.symbol_name)
        fields.addRow("封装名称", self.footprint_name)
        fields.addRow("3D 模型目录", self.model_path)
        fields.addRow(self.refresh_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.scope)
        layout.addWidget(self.global_fields)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.footprint_library.currentIndexChanged.connect(self._update_model_path)
        self.refresh_button.clicked.connect(self.refresh)
        self.new_symbol_button.clicked.connect(
            lambda: self._create_library(LibraryKind.SYMBOL)
        )
        self.new_footprint_button.clicked.connect(
            lambda: self._create_library(LibraryKind.FOOTPRINT)
        )
        index = self.scope.findData(settings.last_import_scope.value)
        self.scope.setCurrentIndex(max(0, index))
        try:
            self.refresh()
        except GlobalLibraryError as error:
            self.catalog_error = str(error)
            self.symbol_library.clear()
            self.footprint_library.clear()
        self._scope_changed()

    def add_pending_library(self, reference: LibraryRef) -> None:
        combo = (
            self.symbol_library
            if reference.kind is LibraryKind.SYMBOL
            else self.footprint_library
        )
        combo.addItem(f"{reference.nickname}（待创建） — {reference.path}", reference)
        combo.setCurrentIndex(combo.count() - 1)

    def _scope_changed(self) -> None:
        self.global_fields.setVisible(
            ImportScope(self.scope.currentData()) is ImportScope.GLOBAL
        )
```

Use these public methods:

```python
    def refresh(self) -> None:
        if not self.kicad_version and self.config_root is None:
            self.symbol_library.clear()
            self.footprint_library.clear()
            self._update_model_path()
            return
        catalog = discover_global_libraries(
            self.kicad_version,
            config_root=self.config_root,
        )
        self._populate(self.symbol_library, catalog.symbols, self.settings.last_symbol_library)
        self._populate(
            self.footprint_library,
            catalog.footprints,
            self.settings.last_footprint_library,
        )
        self._update_model_path()

    def _populate(
        self,
        combo: QComboBox,
        references: tuple[LibraryRef, ...],
        preferred: str,
    ) -> None:
        pending = tuple(
            combo.itemData(index)
            for index in range(combo.count())
            if isinstance(combo.itemData(index), LibraryRef)
            and not combo.itemData(index).registered
        )
        combo.clear()
        for reference in (*references, *pending):
            suffix = "（待创建）" if not reference.registered else ""
            combo.addItem(f"{reference.nickname}{suffix} — {reference.path}", reference)
        preferred_index = next(
            (
                index
                for index in range(combo.count())
                if isinstance(combo.itemData(index), LibraryRef)
                and combo.itemData(index).nickname == preferred
            ),
            -1,
        )
        combo.setCurrentIndex(preferred_index)

    def _update_model_path(self) -> None:
        reference = self.footprint_library.currentData()
        path = (
            reference.path.with_suffix(".3dshapes")
            if isinstance(reference, LibraryRef)
            else None
        )
        self.model_path.setText(str(path) if path else "")

    def set_generated_names(self, symbol_name: str, footprint_name: str) -> None:
        self.symbol_name.setText(symbol_name)
        self.footprint_name.setText(footprint_name)

    def build_target(
        self,
        *,
        import_symbol: bool = True,
        import_footprint: bool = True,
        import_models: bool = True,
    ) -> ImportTarget:
        scope = ImportScope(self.scope.currentData())
        if scope is ImportScope.PROJECT:
            return ImportTarget()
        symbol = self.symbol_library.currentData()
        footprint = self.footprint_library.currentData()
        if import_symbol and not isinstance(symbol, LibraryRef):
            raise ValueError("请选择全局符号库")
        if (import_footprint or import_models) and not isinstance(footprint, LibraryRef):
            raise ValueError("请选择全局封装库")
        return ImportTarget(
            scope=scope,
            symbol_library=symbol if isinstance(symbol, LibraryRef) else None,
            footprint_library=footprint if isinstance(footprint, LibraryRef) else None,
            symbol_name=(
                validate_component_name(self.symbol_name.text(), "symbol")
                if import_symbol
                else None
            ),
            footprint_name=(
                validate_component_name(self.footprint_name.text(), "footprint")
                if import_footprint
                else None
            ),
        )

    def apply_settings(
        self, settings: AppSettings, target: ImportTarget | None = None
    ) -> AppSettings:
        selected = target or self.build_target()
        if selected.scope is ImportScope.PROJECT:
            updated = replace(settings, last_import_scope=selected.scope)
        else:
            updated = replace(
                settings,
                last_import_scope=selected.scope,
                last_symbol_library=(
                    selected.symbol_library.nickname
                    if selected.symbol_library
                    else settings.last_symbol_library
                ),
                last_footprint_library=(
                    selected.footprint_library.nickname
                    if selected.footprint_library
                    else settings.last_footprint_library
                ),
            )
        self.settings = updated
        return updated
```

`NewLibraryDialog` collects nickname and target path without creating either. Implement these methods:

```python
class NewLibraryDialog(QDialog):
    def __init__(
        self,
        kind: LibraryKind,
        config_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.config_root = config_root
        self.nickname = QLineEdit()
        self.path = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.path, 1)
        path_layout.addWidget(browse)
        layout = QFormLayout(self)
        layout.addRow("库别名", self.nickname)
        layout.addRow("保存路径", path_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse(self) -> None:
        if self.kind is LibraryKind.SYMBOL:
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "新建 KiCad 符号库",
                self.path.text(),
                "KiCad 符号库 (*.kicad_sym)",
            )
            if selected:
                path = Path(selected)
                if path.suffix.casefold() != ".kicad_sym":
                    path = path.with_suffix(".kicad_sym")
                self.path.setText(str(path))
            return
        parent = QFileDialog.getExistingDirectory(
            self, "选择封装库父目录", self.path.text()
        )
        nickname = self.nickname.text().strip()
        if parent and nickname:
            self.path.setText(str(Path(parent) / f"{nickname}.pretty"))

    def library_ref(self) -> LibraryRef:
        nickname = self.nickname.text().strip()
        path = Path(self.path.text()).expanduser()
        if self.kind is LibraryKind.SYMBOL:
            if path.suffix.casefold() != ".kicad_sym":
                raise ValueError("符号库路径必须以 .kicad_sym 结尾")
            table = self.config_root / "sym-lib-table"
        else:
            if path.suffix.casefold() != ".pretty":
                raise ValueError("封装库路径必须以 .pretty 结尾")
            table = self.config_root / "fp-lib-table"
        return pending_library(self.kind, nickname, path, table)

    def accept(self) -> None:
        try:
            self.library_ref()
        except ValueError as error:
            QMessageBox.warning(self, "库设置无效", str(error))
            return
        super().accept()
```

Add this widget method for both create buttons:

```python
    def _create_library(self, kind: LibraryKind) -> None:
        if self.config_root is None:
            self.config_root = config_root_for_version(self.kicad_version)
        dialog = NewLibraryDialog(kind, self.config_root, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_pending_library(dialog.library_ref())
```

- [ ] **Step 4: Implement the result dialog**

`ImportResultDialog` receives one `ImportReport`, displays only non-`None` destinations and association, includes the backup path, warnings, and library registrations, and uses this constructor plus actions:

```python
class ImportResultDialog(QDialog):
    def __init__(self, report: ImportReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report
        self.paths = tuple(
            path
            for path in (
                report.symbol_destination,
                report.footprint_destination,
                report.model_directory,
                report.backup_dir,
            )
            if path is not None
        )
        lines = [f"已提交 {len(report.committed_paths)} 个文件。"]
        for label, value in (
            ("符号库", report.symbol_destination),
            ("封装", report.footprint_destination),
            ("3D 模型目录", report.model_directory),
            ("封装关联", report.footprint_association),
            ("备份", report.backup_dir),
        ):
            if value is not None:
                lines.append(f"{label}：{value}")
        if report.library_registration:
            lines.append("新注册：" + "、".join(report.library_registration))
            lines.append("新注册的库若未立即出现，请重启相应 KiCad 编辑器。")
        if report.warnings:
            lines.append("警告：\n" + "\n".join(report.warnings))
        text = QPlainTextEdit("\n\n".join(lines))
        text.setReadOnly(True)
        open_button = QPushButton("打开库目录")
        copy_button = QPushButton("复制路径")
        open_button.clicked.connect(self._open_primary_directory)
        copy_button.clicked.connect(self._copy_paths)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        actions = QHBoxLayout()
        actions.addWidget(open_button)
        actions.addWidget(copy_button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(buttons)

    def _copy_paths(self) -> None:
        QApplication.clipboard().setText("\n".join(str(path) for path in self.paths))

    def _open_primary_directory(self) -> None:
        path = self.report.footprint_destination or self.report.symbol_destination
        if path is not None:
            directory = path if path.is_dir() else path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
```

Use `QDialogButtonBox.Close`, plus explicit `打开库目录` and `复制路径` buttons. The dialog text must state that a newly registered global library may require restarting the relevant KiCad editor.

- [ ] **Step 5: Run widget tests and commit**

Run:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/test_library_target_widget.py -q
python -m ruff check src/jlceda2kicad/library_target_widget.py tests/test_library_target_widget.py
python -m mypy src
```

Expected: all target/result widget tests pass under offscreen Qt.

Commit:

```powershell
git add src/jlceda2kicad/library_target_widget.py tests/test_library_target_widget.py
git commit -m "feat: add global library target controls"
```

---

### Task 7: Main-window workflow integration

**Files:**
- Modify: `src/jlceda2kicad/main_window.py`
- Modify: `src/jlceda2kicad/main.py`
- Modify: `tests/test_main_window.py`
- Modify: `tests/test_application.py`

**Interfaces:**
- Consumes: `LibraryTargetWidget`, `ImportResultDialog`, `generated_names`, and service-level `find_import_conflicts`.
- Changes: `MainWindow.__init__` accepts `global_backup_root: Path` and optional `global_config_root: Path | None`.
- Changes: `create_window` passes `<app-data>/backups/global`.
- Preserves: asynchronous preview/full/SVG/formal conversion and cancel behavior.

- [ ] **Step 1: Write main-window integration tests**

Extend the `_window` helper in `tests/test_main_window.py` to pass temporary global config and backup roots. Add:

```python
def test_preview_populates_editable_generated_names(qtbot: object, tmp_path: Path) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.lcsc_input.setText("C2040")
    window.preview_button.click()
    command = controller.commands[0]
    output_base = Path(command.arguments[command.arguments.index("--output") + 1])  # type: ignore[attr-defined]
    output_base.with_suffix(".kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (symbol "Part" '
        '(property "Value" "Part") (property "Footprint" "Old:Foot") '
        '(property "LCSC Part" "C2040")))',
        encoding="utf-8",
    )
    pretty = output_base.with_suffix(".pretty")
    pretty.mkdir()
    (pretty / "Foot.kicad_mod").write_text('(footprint "Foot")', encoding="utf-8")
    controller.completed.emit(ProcessResult(0, True, "", ""))
    controller.completed.emit(ProcessResult(0, True, "", ""))

    assert window.library_target.symbol_name.text() == "Part"
    assert window.library_target.footprint_name.text() == "Foot"


def test_global_import_builds_formal_commands_without_seeding_project_library(
    qtbot: object, tmp_path: Path
) -> None:
    window, controller = _window_with_global_tables(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.artifacts = _preview_artifacts(tmp_path / "preview")
    window.lcsc_input.setText("C2040")
    window.library_target.scope.setCurrentIndex(1)
    window.library_target.set_generated_names("CustomSymbol", "CustomFootprint")

    window.start_import()

    assert len(controller.commands) == 1
    assert window._import_options is not None
    assert window._import_options.target.scope is ImportScope.GLOBAL
    assert window._shadow is not None
    assert not (window._shadow / "libs" / "lcsc_project.kicad_sym").exists()


def test_manual_project_selection_keeps_running_kicad_version(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    window, _ = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    other = tmp_path / "other"
    other.mkdir()
    project = other / "other.kicad_pro"
    project.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(project), "")),
    )

    window._choose_project()

    assert window.context.project_root == other
    assert window.context.kicad_version == "10.0.4"
```

Add this result-routing test (the helper returns a window whose global target
combos are populated and whose preview artifacts already exist):

```python
def test_finish_global_import_routes_backup_report_history_and_settings(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, _ = _window_with_global_tables(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.artifacts = _preview_artifacts(tmp_path / "preview")
    window.lcsc_input.setText("C2040")
    window.library_target.scope.setCurrentIndex(1)
    window.library_target.symbol_library.setCurrentIndex(0)
    window.library_target.footprint_library.setCurrentIndex(0)
    window.library_target.set_generated_names("CustomSymbol", "CustomFootprint")
    target = window.library_target.build_target()
    window._import_options = ImportOptions(target=target)
    window._shadow = tmp_path / "shadow"
    window._shadow.mkdir()
    window._phase = "import"
    captured: dict[str, object] = {}
    report = ImportReport(
        success=True,
        symbol_destination=tmp_path / "Harulib.kicad_sym",
        footprint_destination=tmp_path / "Harulib.pretty" / "CustomFootprint.kicad_mod",
        footprint_association="Harulib:CustomFootprint",
    )

    def fake_import(*args: object, **kwargs: object) -> ImportReport:
        captured["backup"] = kwargs["global_backup_root"]
        return report

    def fake_dialog_exec(dialog: object) -> int:
        captured["report"] = dialog.report  # type: ignore[attr-defined]
        return 0

    monkeypatch.setattr("jlceda2kicad.main_window.import_shadow_artifacts", fake_import)
    monkeypatch.setattr("jlceda2kicad.main_window.ImportResultDialog.exec", fake_dialog_exec)

    window._finish_import()

    assert captured["backup"] == window.global_backup_root
    assert captured["report"] == report
    assert window.settings_store.load().last_symbol_library == "Harulib"
    history = window.history_store.load()
    assert history[0].symbol == "CustomSymbol"
    assert history[0].footprint == "CustomFootprint"
```

- [ ] **Step 2: Run the integration tests and verify constructor/UI failures**

Run:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/test_main_window.py tests/test_application.py -q
```

Expected: failures because `MainWindow` lacks the injected paths and target widget.

- [ ] **Step 3: Add the target widget and populate names after preview**

Extend `MainWindow.__init__`:

```python
        global_backup_root: Path,
        global_config_root: Path | None = None,
```

Store both paths. In `_build_ui`, insert:

```python
        self.library_target = LibraryTargetWidget(
            self.settings,
            kicad_version=self.context.kicad_version or "",
            config_root=self.global_config_root,
        )
        outer.addWidget(self.library_target)
```

Immediately after `_build_ui()` returns in `__init__`, surface a catalog error
in the log without failing project mode:

```python
        if self.library_target.catalog_error:
            self._append_log(f"无法读取全局库表：{self.library_target.catalog_error}")
```

When `_choose_project` receives a manual context, preserve the running version:

```python
        detected_version = self.context.kicad_version
        context = context_from_path(Path(selected))
        if context.kicad_version is None and detected_version is not None:
            context = replace(context, kicad_version=detected_version)
```

In `_set_context`, update the widget version only when the new context supplies
one, then refresh its catalog. Catch `GlobalLibraryError`, leave the selectors
empty, and log the error without preventing project mode:

```python
        if context.kicad_version:
            self.library_target.kicad_version = context.kicad_version
        try:
            self.library_target.refresh()
        except GlobalLibraryError as error:
            self.library_target.symbol_library.clear()
            self.library_target.footprint_library.clear()
            self._append_log(f"无法读取全局库表：{error}")
```

At the end of `_render_artifacts`, call:

```python
        try:
            symbol_name, footprint_name = generated_names(artifacts, self.lcsc_input.text())
            self.library_target.set_generated_names(symbol_name, footprint_name)
        except (OSError, UnicodeError, ValueError) as error:
            self._append_log(f"无法读取转换名称：{error}")
```

- [ ] **Step 4: Route start, conflict detection, finish, and settings**

At the start of `start_import`, build and persist the target with the enabled
artifact flags, and show a `ValueError` in `status_label`:

```python
        try:
            target = self.library_target.build_target(
                import_symbol=self.settings.import_symbol,
                import_footprint=self.settings.import_footprint,
                import_models=self.settings.import_step or self.settings.import_wrl,
            )
        except ValueError as error:
            self.status_label.setText(f"导入目标无效：{error}")
            return
        self.settings = self.library_target.apply_settings(self.settings, target)
        self.settings_store.save(self.settings)
```

Put `target` in `ImportOptions.target` before conflict preflight.

Replace `_find_conflicts` with:

```python
    def _find_conflicts(self, options: ImportOptions) -> list[str]:
        if self.artifacts is None or self.context.project_root is None:
            return []
        return list(
            find_import_conflicts(
                self.context.project_root,
                self.artifacts,
                self.lcsc_input.text(),
                options,
            )
        )
```

Build options before opening the conflict dialog so custom targets participate in preflight. For project scope call `prepare_shadow_project`; for global scope create only `shadow/libs` so conversion cannot read or mutate personal libraries.

In `_finish_import`, pass:

```python
                global_backup_root=self.global_backup_root,
```

Replace the error message construction so rollback evidence is visible:

```python
        except ImportServiceError as error:
            details = [str(error)]
            if error.report.backup_dir is not None:
                details.append(f"备份：{error.report.backup_dir}")
            if error.report.rollback_result:
                details.append("回滚失败：\n" + "\n".join(error.report.rollback_result))
            elif error.report.backup_dir is not None:
                details.append("已完成回滚。")
            message = "\n\n".join(details)
            self._phase = "idle"
            self._set_busy(False, f"导入失败：{error}")
            QMessageBox.critical(self, "导入失败", message)
            return
```

Use report destinations and custom names for history. Replace the simple information box with `ImportResultDialog(report, self).exec()`. Do not separately open the project `libs` directory; the result dialog owns path actions for both scopes.

- [ ] **Step 5: Inject the application backup root and test it**

In `main.create_window`, pass:

```python
        global_backup_root=root / "backups" / "global",
```

Update `tests/test_application.py`:

```python
    assert window.global_backup_root == data_dir / "backups" / "global"
```

- [ ] **Step 6: Run all Qt workflow tests and commit**

Run:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/test_main_window.py tests/test_library_target_widget.py tests/test_application.py tests/test_process_controller.py -q
python -m ruff check src/jlceda2kicad/main_window.py src/jlceda2kicad/main.py tests/test_main_window.py tests/test_application.py
python -m mypy src
```

Expected: all Qt workflow tests pass; preview/cancel behavior is unchanged.

Commit:

```powershell
git add src/jlceda2kicad/main_window.py src/jlceda2kicad/main.py tests/test_main_window.py tests/test_application.py
git commit -m "feat: integrate global library imports"
```

---

### Task 8: Documentation, package verification, installation, and KiCad 10 smoke test

**Files:**
- Modify: `README.md`
- Modify: `README_zh-CN.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/MANUAL_TEST_CHECKLIST.md`
- Modify: `CHANGELOG.md`
- Verify only: `scripts/install_dev.ps1`
- Verify only: `dist/JLCEDA2KICAD-0.1.0.zip`

**Interfaces:**
- Consumes: all finished feature behavior.
- Produces: user instructions for project/global modes, exact storage rules, refresh caveat, backup location, and disposable smoke-test evidence.
- Does not produce or commit binary `dist` artifacts.

- [ ] **Step 1: Add English and Chinese usage documentation**

Add a `Global personal libraries` section to `README.md` and `全局个人库` to `README_zh-CN.md` with these exact user steps:

1. Query and preview one LCSC component.
2. Select `KiCad global personal library`.
3. Select symbol and footprint libraries independently, or create pending libraries.
4. Edit symbol and footprint names independently.
5. Verify the displayed `.3dshapes` directory and final `<library>:<footprint>` association.
6. Import, inspect exact paths and backup location, and restart the relevant KiCad editor only when a newly registered library is not immediately visible.

Document that the current machine's selected library receives normalized absolute model paths and that automated tests never write `Harulib`.

- [ ] **Step 2: Extend development and manual test documentation**

Add pure-core test routing and global backup layout to `docs/DEVELOPMENT.md`. Add these checkboxes to `docs/MANUAL_TEST_CHECKLIST.md`:

```markdown
- [ ] Select the existing Harulib entries read-only and confirm their resolved paths are shown.
- [ ] Create disposable Codex_Global_Smoke symbol and footprint libraries in a disposable directory.
- [ ] Import C6119899 as symbol `Codex_C6119899` and footprint `Codex_C0805`.
- [ ] Confirm the symbol Footprint property is `Codex_Global_Smoke:Codex_C0805`.
- [ ] Confirm STEP/WRL files are under the sibling `Codex_Global_Smoke.3dshapes` directory.
- [ ] Exercise cancel, skip, and overwrite without changing unrelated symbols or footprints.
- [ ] Confirm the global backup manifest contains absolute paths, sizes, and SHA-256 values.
- [ ] Remove the disposable table entries and files, restore original table bytes, and confirm Harulib hashes are unchanged.
```

Add an `Unreleased` entry to `CHANGELOG.md` describing global target selection, independent renaming, automatic association, and multi-root rollback.

- [ ] **Step 3: Run the full automated acceptance suite**

Run from the repository root:

```powershell
python -m ruff check .
python -m mypy src
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest --cov=jlceda2kicad
python scripts/build_package.py
python -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
```

Expected:

- Ruff exits 0 with no diagnostics.
- mypy exits 0 with no errors.
- pytest exits 0; the network-marked live test remains skipped unless explicitly enabled.
- coverage does not regress below the repository's current measured 78%.
- package build emits the ZIP, SHA-256, and manifest.
- `kipy.packaging validate` reports a valid package.

- [ ] **Step 4: Commit documentation after verification**

Do not add `dist`. Commit only source documentation:

```powershell
git add README.md README_zh-CN.md docs/DEVELOPMENT.md docs/MANUAL_TEST_CHECKLIST.md CHANGELOG.md
git commit -m "docs: explain global library imports"
```

- [ ] **Step 5: Install the updated development plugin for KiCad 10**

Run:

```powershell
.\scripts\install_dev.ps1 -KiCadVersions 10.0
```

Expected: the installer updates only `C:\Users\HKRPTS\Documents\KiCad\10.0\plugins\io.hkrpt.jlc` in place and reports that path. Restart PCB Editor and use `工具 → 外部插件 → 刷新插件` if needed.

- [ ] **Step 6: Perform the disposable KiCad 10 smoke test**

Before the test, record SHA-256 for:

```powershell
Get-FileHash -Algorithm SHA256 'C:\Users\HKRPTS\AppData\Roaming\kicad\10.0\sym-lib-table'
Get-FileHash -Algorithm SHA256 'C:\Users\HKRPTS\AppData\Roaming\kicad\10.0\fp-lib-table'
Get-FileHash -Algorithm SHA256 'C:\Users\HKRPTS\Documents\KiCad\9.0\symbols\Harulib.kicad_sym'
```

Use a disposable `Codex_Global_Smoke` library, never `Harulib`, and import C6119899 with the custom names from the checklist. In KiCad's symbol chooser confirm the symbol exists, open its properties to confirm the footprint association, open the footprint and 3D viewer, then exercise one overwrite. Remove the disposable entries/files through KiCad's library managers and restore the original table bytes if KiCad reformats unrelated entries. Re-run the three hashes and record that the real `Harulib.kicad_sym` hash is unchanged.

- [ ] **Step 7: Record final repository and push evidence**

Run:

```powershell
git status --short --branch
git log --oneline --decorate -12
git push origin codex/initial-kicad-plugin
```

Expected: source worktree is clean except ignored `dist`, the log contains the focused commits from this plan, and the remote feature branch advances without merging into `main`.

Final report must list automated command results, package paths and SHA-256, installed plugin path, KiCad 10 smoke-test evidence, unchanged `Harulib` evidence, commit hashes, push status, and every unchecked/manual item as not verified.
