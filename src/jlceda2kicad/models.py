"""Shared immutable data contracts used by the core and Qt adapters."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


class ConversionMode(str, Enum):
    SYMBOL = "symbol"
    FOOTPRINT = "footprint"
    MODEL_3D = "3d"
    FULL = "full"
    SVG = "svg"


class ConflictPolicy(str, Enum):
    CANCEL = "cancel"
    SKIP_EXISTING = "skip_existing"
    OVERWRITE_COMPONENT = "overwrite_component"


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


@dataclass(frozen=True, slots=True)
class ProjectContext:
    project_root: Path | None = None
    project_file: Path | None = None
    board_file: Path | None = None
    kicad_version: str | None = None
    source: Literal["ipc", "manual", "none"] = "none"

    @property
    def is_valid(self) -> bool:
        return self.project_root is not None and self.project_root.is_dir()

    @property
    def library_base(self) -> Path | None:
        if self.project_root is None:
            return None
        return self.project_root / "libs" / "lcsc_project"


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    lcsc_id: str
    modes: tuple[ConversionMode, ...]
    output_base: Path
    working_dir: Path
    use_cache: bool = True
    overwrite: bool = False
    project_relative: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    root: Path
    symbol_libraries: tuple[Path, ...] = ()
    footprints: tuple[Path, ...] = ()
    step_models: tuple[Path, ...] = ()
    wrl_models: tuple[Path, ...] = ()
    symbol_svgs: tuple[Path, ...] = ()
    footprint_svgs: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def all_files(self) -> tuple[Path, ...]:
        return (
            self.symbol_libraries
            + self.footprints
            + self.step_models
            + self.wrl_models
            + self.symbol_svgs
            + self.footprint_svgs
        )

    @property
    def has_any(self) -> bool:
        return bool(self.all_files)


@dataclass(frozen=True, slots=True)
class ImportOptions:
    symbol: bool = True
    footprint: bool = True
    step: bool = True
    wrl: bool = True
    use_cache: bool = True
    open_library_dir: bool = True
    conflict_policy: ConflictPolicy = ConflictPolicy.CANCEL
    target: ImportTarget = field(default_factory=ImportTarget)


@dataclass(frozen=True, slots=True)
class ImportReport:
    success: bool
    committed_paths: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    library_registration: tuple[str, ...] = ()
    backup_dir: Path | None = None
    rollback_result: tuple[str, ...] = ()
    symbol_destination: Path | None = None
    footprint_destination: Path | None = None
    model_directory: Path | None = None
    footprint_association: str | None = None
