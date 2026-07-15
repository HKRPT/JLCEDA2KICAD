"""Build a dual-schema PCM repository from local or GitHub Release assets."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from scripts.github_releases import GitHubClient, load_public_release_payloads
from scripts.pcm_repository import SiteBuildRequest, build_site
from scripts.release_policy import (
    DistributionError,
    PublishedVersion,
    ReleasePayload,
    inspect_release,
)

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "metadata.json"
ICON = ROOT / "resources" / "icon_64.png"
INDEX_HTML = ROOT / "resources" / "pages" / "index.html"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    local = subparsers.add_parser("local")
    local.add_argument("--tag", required=True)
    local.add_argument("--archive", type=Path, required=True)
    local.add_argument("--checksum", type=Path, required=True)
    local.add_argument("--manifest", type=Path, required=True)
    local.add_argument("--download-url", required=True)
    local.add_argument("--base-url", required=True)
    local.add_argument("--output", type=Path, required=True)
    local.add_argument("--published-at", required=True)

    github = subparsers.add_parser("github")
    github.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    github.add_argument("--base-url", required=True)
    github.add_argument("--output", type=Path, required=True)
    github.add_argument("--token-env", default="GITHUB_TOKEN")
    return parser


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DistributionError(f"invalid publication time: {value}") from error
    if parsed.tzinfo is None:
        raise DistributionError("publication time must include a timezone")
    return parsed.astimezone(UTC)


def _request(
    *,
    versions: Sequence[PublishedVersion],
    base_url: str,
    output: Path,
    updated_at: datetime,
) -> SiteBuildRequest:
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    return SiteBuildRequest(
        source_metadata=metadata,
        versions=versions,
        icon=ICON.read_bytes(),
        index_html=INDEX_HTML.read_bytes(),
        base_url=base_url,
        updated_at=updated_at,
        output=output,
    )


def _local(args: argparse.Namespace) -> int:
    published_at = _parse_time(args.published_at)
    payload = ReleasePayload(
        tag_name=args.tag,
        draft=False,
        prerelease=False,
        published_at=published_at,
        archive_name=args.archive.name,
        archive_url=args.download_url,
        archive=args.archive.read_bytes(),
        checksum=args.checksum.read_bytes(),
        manifest=args.manifest.read_bytes(),
    )
    published = inspect_release(payload)
    result = build_site(
        _request(
            versions=(published,),
            base_url=args.base_url,
            output=args.output,
            updated_at=published_at,
        )
    )
    shutil.copy2(args.archive, result.root / args.archive.name)
    print(result.root)
    return 0


def _github(args: argparse.Namespace) -> int:
    if not args.repository:
        raise DistributionError("GITHUB_REPOSITORY or --repository is required")
    token = os.environ.get(args.token_env)
    if not token:
        raise DistributionError(f"{args.token_env} is required")
    payloads = load_public_release_payloads(GitHubClient(args.repository, token))
    published = tuple(inspect_release(payload) for payload in payloads)
    if not published:
        raise DistributionError("no supported public GitHub releases were found")
    updated_at = max(item.published_at for item in published)
    result = build_site(
        _request(
            versions=published,
            base_url=args.base_url,
            output=args.output,
            updated_at=updated_at,
        )
    )
    print(result.root)
    return 0


def _run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "local":
        return _local(args)
    if args.command == "github":
        return _github(args)
    raise AssertionError(args.command)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _run(argv)
    except (DistributionError, OSError, json.JSONDecodeError) as error:
        print(f"repository build failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
