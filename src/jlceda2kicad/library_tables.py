"""Safe, idempotent editing of project-level KiCad library tables."""

import os
from dataclasses import dataclass
from pathlib import Path

from .sexpr import ListExpr, SExprError, parse_one


class LibraryTableError(ValueError):
    """Raised when an existing table cannot be safely preserved."""


@dataclass(frozen=True, slots=True)
class LibraryRegistrationResult:
    symbol_registered: bool
    footprint_registered: bool


_TABLES = {
    "sym-lib-table": (
        "sym_lib_table",
        "${KIPRJMOD}/libs/lcsc_project.kicad_sym",
    ),
    "fp-lib-table": (
        "fp_lib_table",
        "${KIPRJMOD}/libs/lcsc_project.pretty",
    ),
}


def _has_library(root: ListExpr, name: str) -> bool:
    for child in root.children:
        if child.head != "lib":
            continue
        for field in child.children:
            atoms = field.atoms
            if field.head == "name" and len(atoms) >= 2 and atoms[1].value == name:
                return True
    return False


def _load_table(path: Path, root_name: str) -> tuple[str | None, ListExpr | None]:
    if not path.exists():
        return None, None
    try:
        text = path.read_text(encoding="utf-8-sig")
        root = parse_one(text)
        if root.head != root_name:
            raise SExprError(f"根节点应为 {root_name}")
        return text, root
    except (OSError, UnicodeError, SExprError) as error:
        raise LibraryTableError(f"{path.name} 已损坏，未进行修改：{error}") from error


def _entry(uri: str) -> str:
    return (
        '(lib (name "LCSC_Project") (type "KiCad") '
        f'(uri "{uri}") (options "") (descr "JLCEDA2KICAD project library"))'
    )


def _updated_table(text: str | None, root: ListExpr | None, root_name: str, uri: str) -> str:
    entry = _entry(uri)
    if text is None or root is None:
        return f"({root_name}\n  (version 7)\n  {entry}\n)\n"
    insertion = root.end - 1
    prefix = "" if text[:insertion].endswith("\n") else "\n"
    return text[:insertion] + prefix + f"  {entry}\n" + text[insertion:]


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_project_library_table_updates(
    project_root: Path,
    *,
    register_symbol: bool = True,
    register_footprint: bool = True,
) -> tuple[dict[Path, str], LibraryRegistrationResult]:
    """Build table contents without touching disk, after validating both tables."""
    selected = {
        "sym-lib-table": register_symbol,
        "fp-lib-table": register_footprint,
    }
    loaded: dict[str, tuple[str | None, ListExpr | None]] = {}
    for filename, (root_name, _) in _TABLES.items():
        if selected[filename]:
            loaded[filename] = _load_table(project_root / filename, root_name)

    changed = {"sym-lib-table": False, "fp-lib-table": False}
    updates: dict[Path, str] = {}
    for filename, (root_name, uri) in _TABLES.items():
        if not selected[filename]:
            continue
        text, root = loaded[filename]
        already_registered = root is not None and _has_library(root, "LCSC_Project")
        changed[filename] = not already_registered
        if not already_registered:
            updates[project_root / filename] = _updated_table(text, root, root_name, uri)

    result = LibraryRegistrationResult(
        symbol_registered=changed["sym-lib-table"],
        footprint_registered=changed["fp-lib-table"],
    )
    return updates, result


def register_project_libraries(project_root: Path) -> LibraryRegistrationResult:
    """Register project-local libraries after validating every existing table."""

    updates, result = build_project_library_table_updates(project_root)
    project_root.mkdir(parents=True, exist_ok=True)
    for path, text in updates.items():
        _write_atomic(path, text)
    return result
