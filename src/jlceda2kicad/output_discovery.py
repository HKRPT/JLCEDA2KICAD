"""Discover converter artifacts without assuming component names."""

from collections.abc import Iterable
from pathlib import Path

from .models import ArtifactSet


class AmbiguousArtifactError(ValueError):
    """Raised when equally plausible artifacts require user selection."""


def _sorted(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(sorted(paths, key=lambda path: path.as_posix().casefold()))


def discover_artifacts(root: Path) -> ArtifactSet:
    """Recursively classify every supported, non-empty generated file."""

    buckets: dict[str, list[Path]] = {
        "symbol": [],
        "footprint": [],
        "step": [],
        "wrl": [],
        "symbol_svg": [],
        "footprint_svg": [],
    }
    warnings: list[str] = []
    if not root.is_dir():
        return ArtifactSet(root=root, warnings=(f"输出目录不存在：{root}",))

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.casefold()
        if suffix not in {".kicad_sym", ".kicad_mod", ".step", ".stp", ".wrl", ".svg"}:
            continue
        if path.stat().st_size == 0:
            warnings.append(f"忽略空文件：{path.name}")
            continue
        if suffix == ".kicad_sym":
            buckets["symbol"].append(path)
        elif suffix == ".kicad_mod":
            buckets["footprint"].append(path)
        elif suffix in {".step", ".stp"}:
            buckets["step"].append(path)
        elif suffix == ".wrl":
            buckets["wrl"].append(path)
        elif "symbol" in path.stem.casefold():
            buckets["symbol_svg"].append(path)
        elif "footprint" in path.stem.casefold():
            buckets["footprint_svg"].append(path)
        else:
            warnings.append(f"无法确定 SVG 类型：{path.name}")

    return ArtifactSet(
        root=root,
        symbol_libraries=_sorted(buckets["symbol"]),
        footprints=_sorted(buckets["footprint"]),
        step_models=_sorted(buckets["step"]),
        wrl_models=_sorted(buckets["wrl"]),
        symbol_svgs=_sorted(buckets["symbol_svg"]),
        footprint_svgs=_sorted(buckets["footprint_svg"]),
        warnings=tuple(warnings),
    )


def choose_best_candidate(
    candidates: tuple[Path, ...],
    lcsc_id: str,
    kind_hint: str,
) -> Path | None:
    """Choose a uniquely best candidate or require an explicit user choice."""

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    needle = lcsc_id.casefold()
    kind = kind_hint.casefold()
    scored = [
        (int(needle in path.stem.casefold()) + int(kind in path.stem.casefold()), path)
        for path in candidates
    ]
    best_score = max(score for score, _ in scored)
    best = [path for score, path in scored if score == best_score]
    if best_score > 0 and len(best) == 1:
        return best[0]
    raise AmbiguousArtifactError("存在多个同等候选文件，请手动选择。")
