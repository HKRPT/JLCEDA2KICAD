import os
import subprocess
import sys
from pathlib import Path

import pytest

from jlceda2kicad.output_discovery import discover_artifacts


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LCSC_TESTS") != "1",
    reason="set RUN_LIVE_LCSC_TESTS=1 to allow the C2040 network conversion",
)
def test_live_c2040_full_and_svg_conversion(tmp_path: Path) -> None:
    output = tmp_path / "preview" / "lcsc_component"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "easyeda2kicad",
            "--full",
            "--svg",
            "--lcsc_id=C2040",
            "--output",
            str(output),
            "--use-cache",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    artifacts = discover_artifacts(tmp_path)
    assert artifacts.symbol_libraries
    assert artifacts.footprints
    assert artifacts.symbol_svgs or artifacts.footprint_svgs
