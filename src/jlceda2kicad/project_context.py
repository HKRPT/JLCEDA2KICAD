"""Resolve the current KiCad project from IPC or a manual path."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import ProjectContext


def _first(directory: Path, pattern: str) -> Path | None:
    return next(iter(sorted(directory.glob(pattern), key=lambda path: path.name.casefold())), None)


def context_from_path(path: Path) -> ProjectContext:
    """Create a manual project context from a project file, board, or directory."""

    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        project = _first(resolved, "*.kicad_pro")
        board = _first(resolved, "*.kicad_pcb")
        if project is None and board is None:
            return ProjectContext()
        return ProjectContext(resolved, project, board, source="manual")
    if not resolved.is_file():
        return ProjectContext()
    if resolved.suffix.casefold() == ".kicad_pro":
        board = resolved.with_suffix(".kicad_pcb")
        return ProjectContext(
            resolved.parent,
            resolved,
            board if board.is_file() else _first(resolved.parent, "*.kicad_pcb"),
            source="manual",
        )
    if resolved.suffix.casefold() == ".kicad_pcb":
        project = resolved.with_suffix(".kicad_pro")
        return ProjectContext(
            resolved.parent,
            project if project.is_file() else _first(resolved.parent, "*.kicad_pro"),
            resolved,
            source="manual",
        )
    return ProjectContext()


def _default_kicad_factory() -> Any:
    from kipy import KiCad

    return KiCad()


def detect_ipc_context(
    kicad_factory: Callable[[], Any] = _default_kicad_factory,
) -> ProjectContext:
    """Read the project fields exposed by the official KiCad IPC binding."""

    try:
        kicad = kicad_factory()
        board = kicad.get_board()
        document = board.document
        root = Path(document.project.path).expanduser().resolve()
        board_file = root / document.board_filename
        project_name = getattr(document.project, "name", "") or board_file.stem
        project_file = root / f"{project_name}.kicad_pro"
        version = kicad.get_version()
        version_text = getattr(version, "full_version", None) or str(version)
        return ProjectContext(root, project_file, board_file, version_text, "ipc")
    except Exception:
        return ProjectContext()
