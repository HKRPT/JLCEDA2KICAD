"""Publish one immutable GitHub Release after local policy validation."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src")]

from jlceda2kicad.version import __version__
from scripts.github_releases import GitHubClient, ensure_release_assets
from scripts.release_policy import (
    DistributionError,
    validate_source_release,
)

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "metadata.json"
CHANGELOG = ROOT / "CHANGELOG.md"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"))
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    return parser


def _release_notes(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n.*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None or not match.group(0).strip():
        raise DistributionError(f"CHANGELOG has no section for {version}")
    notes = match.group(0).strip()
    if notes == f"## [{version}]":
        raise DistributionError(f"CHANGELOG section for {version} is empty")
    return notes


def _run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.repository:
        raise DistributionError("GITHUB_REPOSITORY or --repository is required")
    if not args.tag:
        raise DistributionError("GITHUB_REF_NAME or --tag is required")
    token = os.environ.get(args.token_env)
    if not token:
        raise DistributionError(f"{args.token_env} is required")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    source = validate_source_release(args.tag, __version__, metadata, True)
    archive_name = f"JLCEDA2KICAD-{source.tag.version}.zip"
    names = (
        archive_name,
        f"{archive_name}.sha256",
        f"{archive_name}.manifest.txt",
    )
    assets = {name: args.dist / name for name in names}
    missing = [name for name, path in assets.items() if not path.is_file()]
    if missing:
        raise DistributionError("release assets are missing: " + ", ".join(missing))
    notes = _release_notes(CHANGELOG, source.tag.version)
    client = GitHubClient(args.repository, token)
    published = ensure_release_assets(client, source, assets, notes)
    public_names = sorted(asset.name for asset in published.assets if asset.name in names)
    print(f"published {published.tag_name} release_id={published.release_id}")
    print("assets: " + ", ".join(public_names))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _run(argv)
    except (DistributionError, OSError, json.JSONDecodeError) as error:
        print(f"release publication failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
