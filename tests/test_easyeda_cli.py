from pathlib import Path

import pytest

from jlceda2kicad.easyeda_cli import build_command
from jlceda2kicad.models import ConversionMode, ConversionRequest
from jlceda2kicad.validation import LcscIdError


def test_build_command_uses_argument_list_and_exact_output_path(tmp_path: Path) -> None:
    output = (tmp_path / "中文 项目" / "libs" / "lcsc_project").resolve()
    request = ConversionRequest(
        lcsc_id="C2040",
        modes=(ConversionMode.SYMBOL, ConversionMode.FOOTPRINT, ConversionMode.MODEL_3D),
        output_base=output,
        working_dir=tmp_path.resolve(),
        use_cache=True,
        overwrite=True,
        project_relative=True,
    )

    command = build_command(request, python_executable=Path("C:/Python/python.exe"))

    assert command.program == Path("C:/Python/python.exe")
    assert command.working_dir == tmp_path.resolve()
    assert command.arguments == (
        "-m",
        "easyeda2kicad",
        "--symbol",
        "--footprint",
        "--3d",
        "--lcsc_id=C2040",
        "--output",
        str(output),
        "--overwrite",
        "--project-relative",
        "--use-cache",
    )
    assert not hasattr(command, "shell")


def test_build_command_rejects_injection_before_constructing_arguments(tmp_path: Path) -> None:
    request = ConversionRequest(
        lcsc_id="C2040 & whoami",
        modes=(ConversionMode.FULL,),
        output_base=tmp_path / "out",
        working_dir=tmp_path,
    )

    with pytest.raises(LcscIdError):
        build_command(request)


def test_build_command_requires_at_least_one_mode(tmp_path: Path) -> None:
    request = ConversionRequest(
        lcsc_id="C2040",
        modes=(),
        output_base=tmp_path / "out",
        working_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="mode"):
        build_command(request)

