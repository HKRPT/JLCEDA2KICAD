from pathlib import Path

import pytest

from jlceda2kicad.output_discovery import (
    AmbiguousArtifactError,
    choose_best_candidate,
    discover_artifacts,
)


def _write(path: Path, text: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_discover_artifacts_classifies_real_nonempty_outputs(tmp_path: Path) -> None:
    symbol = _write(tmp_path / "lcsc_project.kicad_sym")
    footprint = _write(tmp_path / "lcsc_project.pretty" / "RP2040.kicad_mod")
    step = _write(tmp_path / "lcsc_project.3dshapes" / "RP2040.step")
    wrl = _write(tmp_path / "lcsc_project.3dshapes" / "RP2040.WRL")
    symbol_svg = _write(tmp_path / "preview.svgs" / "C2040_symbol.svg")
    footprint_svg = _write(tmp_path / "preview.svgs" / "C2040_footprint.svg")
    _write(tmp_path / "empty.step", "")

    artifacts = discover_artifacts(tmp_path)

    assert artifacts.symbol_libraries == (symbol,)
    assert artifacts.footprints == (footprint,)
    assert artifacts.step_models == (step,)
    assert artifacts.wrl_models == (wrl,)
    assert artifacts.symbol_svgs == (symbol_svg,)
    assert artifacts.footprint_svgs == (footprint_svg,)
    assert "empty.step" in " ".join(artifacts.warnings)


def test_choose_best_candidate_prefers_lcsc_and_kind_hint(tmp_path: Path) -> None:
    generic = _write(tmp_path / "generic.svg")
    expected = _write(tmp_path / "C2040_symbol.svg")

    assert choose_best_candidate((generic, expected), "C2040", "symbol") == expected


def test_choose_best_candidate_rejects_unresolvable_ambiguity(tmp_path: Path) -> None:
    candidates = (_write(tmp_path / "one.svg"), _write(tmp_path / "two.svg"))

    with pytest.raises(AmbiguousArtifactError):
        choose_best_candidate(candidates, "C2040", "symbol")

