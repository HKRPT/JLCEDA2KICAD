"""Safe construction of easyeda2kicad command lines."""

import sys
from dataclasses import dataclass
from pathlib import Path

from .models import ConversionMode, ConversionRequest
from .validation import normalize_lcsc_id

_MODE_FLAGS = {
    ConversionMode.SYMBOL: "--symbol",
    ConversionMode.FOOTPRINT: "--footprint",
    ConversionMode.MODEL_3D: "--3d",
    ConversionMode.FULL: "--full",
    ConversionMode.SVG: "--svg",
}


@dataclass(frozen=True, slots=True)
class CommandSpec:
    program: Path
    arguments: tuple[str, ...]
    working_dir: Path


def build_command(
    request: ConversionRequest,
    *,
    python_executable: Path | None = None,
) -> CommandSpec:
    """Build a shell-free command specification from validated values."""

    lcsc_id = normalize_lcsc_id(request.lcsc_id)
    if not request.modes:
        raise ValueError("At least one conversion mode is required")

    arguments = ["-m", "easyeda2kicad"]
    arguments.extend(_MODE_FLAGS[mode] for mode in request.modes)
    arguments.extend((f"--lcsc_id={lcsc_id}", "--output", str(request.output_base)))
    if request.overwrite:
        arguments.append("--overwrite")
    if request.project_relative:
        arguments.append("--project-relative")
    if request.use_cache:
        arguments.append("--use-cache")

    return CommandSpec(
        program=python_executable or Path(sys.executable),
        arguments=tuple(arguments),
        working_dir=request.working_dir,
    )

