"""Validate a release tag against source metadata and main ancestry."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src")]

from jlceda2kicad.version import __version__
from scripts.release_policy import (
    DistributionError,
    parse_release_tag,
    validate_source_release,
)

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"))
    parser.add_argument("--github-output", action="store_true")
    return parser


def _run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.tag:
        raise DistributionError("A release tag is required")
    tag = parse_release_tag(args.tag)
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
    main_ref = "origin/main" if args.github_output else "main"
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tag.tag_name, main_ref],
        cwd=ROOT,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    validated = validate_source_release(
        tag.tag_name,
        __version__,
        metadata,
        ancestry.returncode == 0,
    )
    if args.github_output:
        output_path = os.environ.get("GITHUB_OUTPUT")
        if not output_path:
            raise DistributionError("GITHUB_OUTPUT is required with --github-output")
        with Path(output_path).open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"version={validated.tag.version}\n")
            output.write(f"prerelease={str(validated.prerelease).lower()}\n")
    print(f"release preflight passed: {tag.tag_name}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _run(argv)
    except (DistributionError, OSError, json.JSONDecodeError) as error:
        print(f"release preflight failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
