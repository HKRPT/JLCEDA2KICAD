"""Discover and plan registration of writable KiCad global libraries."""

import os
import re
from collections.abc import Mapping
from pathlib import Path

from .models import GlobalLibraryCatalog, LibraryKind, LibraryRef
from .sexpr import ListExpr, SExprError, parse_one


class GlobalLibraryError(ValueError):
    """Raised when a global library or its registration table is unsafe."""


_VERSION = re.compile(r"^(\d+)\.(\d+)")
_VARIABLE = re.compile(r"\$\{([^}]+)\}")
_ROOT_NAMES = {
    LibraryKind.SYMBOL: ("sym-lib-table", "sym_lib_table", ".kicad_sym"),
    LibraryKind.FOOTPRINT: ("fp-lib-table", "fp_lib_table", ".pretty"),
}


def config_root_for_version(
    kicad_version: str,
    *,
    roaming_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the roaming configuration directory for a KiCad major/minor version."""
    match = _VERSION.match(kicad_version.strip())
    if match is None:
        raise GlobalLibraryError(f"Unsupported KiCad version: {kicad_version}")
    if roaming_root is not None:
        root = roaming_root
    else:
        environment = os.environ if environ is None else environ
        appdata = _environment_value(environment, "APPDATA")
        if not appdata:
            raise GlobalLibraryError("APPDATA is not set in the selected environment")
        root = Path(appdata)
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


def _environment_value(environ: Mapping[str, str], variable: str) -> str | None:
    normalized = variable.casefold()
    for key, value in environ.items():
        if key.casefold() == normalized:
            return value
    return None


def _default_install_roots(environ: Mapping[str, str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        value = _environment_value(environ, variable)
        if value:
            roots.append(Path(value) / "KiCad")
    return tuple(roots)


def _read_table(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise GlobalLibraryError(f"{path.name} could not be read: {error}") from error


def _load_root(path: Path, expected_head: str) -> ListExpr | None:
    original = _read_table(path)
    if original is None:
        return None
    try:
        root = parse_one(original)
    except SExprError as error:
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
    """Discover direct, writable user libraries from KiCad global tables."""
    environment = dict(os.environ if environ is None else environ)
    root = (
        config_root
        if config_root is not None
        else config_root_for_version(kicad_version, environ=environment)
    )
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


def _validated_nickname(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(char in normalized for char in ':"/\\'):
        raise GlobalLibraryError("Library nickname is empty or contains an unsafe separator")
    return normalized


def pending_library(
    kind: LibraryKind, nickname: str, path: Path, table_path: Path
) -> LibraryRef:
    """Create an unregistered global-library reference after validating its nickname."""
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
    """Reject missing registered libraries and unsafe or unwritable destinations."""
    environment = dict(os.environ if environ is None else environ)
    filename, _, expected_suffix = _ROOT_NAMES[reference.kind]
    if reference.table_path.name != filename or not reference.path.name.endswith(
        expected_suffix
    ):
        raise GlobalLibraryError("Library kind does not match its table or path")
    expected_type = (
        reference.path.is_file()
        if reference.kind is LibraryKind.SYMBOL
        else reference.path.is_dir()
    )
    if reference.path.exists() and not expected_type:
        raise GlobalLibraryError(
            f"Existing library destination has the wrong type: {reference.path}"
        )
    if reference.registered and not expected_type:
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
    """Build, but never write, a global library table update."""
    validate_library_destination(
        reference, environ=environ, install_roots=install_roots
    )
    filename, root_name, _ = _ROOT_NAMES[reference.kind]
    original = _read_table(reference.table_path)
    if original is not None:
        try:
            root = parse_one(original)
        except SExprError as error:
            raise GlobalLibraryError(f"{filename} is malformed: {error}") from error
        if root.head != root_name:
            raise GlobalLibraryError(
                f"{filename} has root {root.head!r}, expected {root_name!r}"
            )
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
        if fields.get("type") == "KiCad" and existing == reference.path:
            return {}
        raise GlobalLibraryError(
            f"Library nickname {reference.nickname!r} is registered to a different path or type"
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
    return {
        reference.table_path: original[:insertion] + prefix + entry + original[insertion:]
    }
