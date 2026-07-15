"""Minimal immutable GitHub Releases adapter with injectable HTTP transport."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from scripts.release_policy import (
    DistributionError,
    ReleasePayload,
    SourceRelease,
    parse_release_tag,
)

_API = "https://api.github.com"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class GitHubAsset:
    asset_id: int
    name: str
    api_url: str
    browser_download_url: str
    size: int


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    release_id: int
    tag_name: str
    draft: bool
    prerelease: bool
    published_at: datetime | None
    upload_url: str
    assets: tuple[GitHubAsset, ...]


class ReleaseClient(Protocol):
    def list_releases(self) -> tuple[GitHubRelease, ...]: ...

    def download_asset(self, asset: GitHubAsset) -> bytes: ...

    def create_release(
        self,
        tag_name: str,
        title: str,
        body: str,
        prerelease: bool,
    ) -> GitHubRelease: ...

    def upload_asset(
        self,
        upload_url: str,
        name: str,
        data: bytes,
        content_type: str,
    ) -> GitHubAsset: ...

    def get_release(self, release_id: int) -> GitHubRelease: ...

    def update_release(
        self,
        release_id: int,
        *,
        draft: bool,
        prerelease: bool,
    ) -> GitHubRelease: ...


class UrllibTransport:
    """Send one GitHub request without exposing credentials in errors."""

    def send(self, request: HttpRequest) -> HttpResponse:
        raw = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with urllib.request.urlopen(raw, timeout=30) as response:
                return HttpResponse(
                    response.status,
                    dict(response.headers.items()),
                    response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, dict(error.headers.items()), error.read())
        except urllib.error.URLError as error:
            raise DistributionError("GitHub API transport failed") from error


def _sanitized_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DistributionError("GitHub release timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DistributionError("GitHub release timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise DistributionError("GitHub release timestamp has no timezone")
    return parsed.astimezone(UTC)


def _asset(value: object) -> GitHubAsset:
    if not isinstance(value, Mapping):
        raise DistributionError("GitHub asset response is invalid")
    try:
        return GitHubAsset(
            asset_id=int(cast(int, value["id"])),
            name=cast(str, value["name"]),
            api_url=cast(str, value["url"]),
            browser_download_url=cast(str, value["browser_download_url"]),
            size=int(cast(int, value["size"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DistributionError("GitHub asset response is invalid") from error


def _release(value: object) -> GitHubRelease:
    if not isinstance(value, Mapping):
        raise DistributionError("GitHub release response is invalid")
    assets = value.get("assets")
    if not isinstance(assets, list):
        raise DistributionError("GitHub release assets are invalid")
    try:
        return GitHubRelease(
            release_id=int(cast(int, value["id"])),
            tag_name=cast(str, value["tag_name"]),
            draft=cast(bool, value["draft"]),
            prerelease=cast(bool, value["prerelease"]),
            published_at=_datetime(value.get("published_at")),
            upload_url=cast(str, value["upload_url"]),
            assets=tuple(_asset(item) for item in assets),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DistributionError("GitHub release response is invalid") from error


class GitHubClient:
    def __init__(
        self,
        repository: str,
        token: str,
        transport: Transport | None = None,
    ) -> None:
        if not _REPOSITORY.fullmatch(repository):
            raise DistributionError("GitHub repository must be owner/name")
        if not token:
            raise DistributionError("GitHub token is required")
        self.repository = repository
        self._token = token
        self.transport = transport or UrllibTransport()

    def __repr__(self) -> str:
        return f"GitHubClient(repository={self.repository!r})"

    def _headers(self, **extra: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            **extra,
        }

    def _send(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        response = self.transport.send(
            HttpRequest(method, url, self._headers(**dict(headers or {})), body)
        )
        if not 200 <= response.status < 300:
            raise DistributionError(
                f"GitHub API {method} {_sanitized_url(url)} returned {response.status}"
            )
        return response

    def _json(self, response: HttpResponse) -> object:
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DistributionError("GitHub API returned malformed JSON") from error

    def list_releases(self) -> tuple[GitHubRelease, ...]:
        url: str | None = f"{_API}/repos/{self.repository}/releases?per_page=100"
        releases: list[GitHubRelease] = []
        pages = 0
        while url is not None:
            pages += 1
            if pages > 100:
                raise DistributionError("GitHub release pagination exceeded the safe limit")
            response = self._send("GET", url)
            raw = self._json(response)
            if not isinstance(raw, list):
                raise DistributionError("GitHub releases response must be an array")
            releases.extend(_release(item) for item in raw)
            url = self._next_link(response.headers)
        return tuple(releases)

    @staticmethod
    def _next_link(headers: Mapping[str, str]) -> str | None:
        link = next((value for key, value in headers.items() if key.casefold() == "link"), None)
        if not link:
            return None
        for item in link.split(","):
            if 'rel="next"' not in item:
                continue
            match = re.search(r"<([^>]+)>", item)
            if match is None:
                break
            url = match.group(1)
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme == "https" and parsed.hostname == "api.github.com":
                return url
            raise DistributionError("GitHub pagination next URL is invalid")
        return None

    def get_release(self, release_id: int) -> GitHubRelease:
        response = self._send(
            "GET", f"{_API}/repos/{self.repository}/releases/{release_id}"
        )
        return _release(self._json(response))

    def create_release(
        self,
        tag_name: str,
        title: str,
        body: str,
        prerelease: bool,
    ) -> GitHubRelease:
        payload = json.dumps(
            {
                "tag_name": tag_name,
                "name": title,
                "body": body,
                "draft": True,
                "prerelease": prerelease,
            }
        ).encode("utf-8")
        response = self._send(
            "POST",
            f"{_API}/repos/{self.repository}/releases",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        return _release(self._json(response))

    def update_release(
        self,
        release_id: int,
        *,
        draft: bool,
        prerelease: bool,
    ) -> GitHubRelease:
        payload = json.dumps({"draft": draft, "prerelease": prerelease}).encode("utf-8")
        response = self._send(
            "PATCH",
            f"{_API}/repos/{self.repository}/releases/{release_id}",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        return _release(self._json(response))

    def upload_asset(
        self,
        upload_url: str,
        name: str,
        data: bytes,
        content_type: str,
    ) -> GitHubAsset:
        base = upload_url.split("{", 1)[0]
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != "https" or parsed.hostname != "uploads.github.com":
            raise DistributionError("GitHub release upload URL is invalid")
        url = f"{base}?{urllib.parse.urlencode({'name': name})}"
        response = self._send(
            "POST",
            url,
            body=data,
            headers={"Content-Type": content_type},
        )
        return _asset(self._json(response))

    def download_asset(self, asset: GitHubAsset) -> bytes:
        parsed = urllib.parse.urlsplit(asset.api_url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise DistributionError("GitHub asset API URL is invalid")
        response = self._send(
            "GET",
            asset.api_url,
            headers={"Accept": "application/octet-stream"},
        )
        return response.body


def _expected_asset_names(version: str) -> tuple[str, str, str]:
    archive = f"JLCEDA2KICAD-{version}.zip"
    return archive, f"{archive}.sha256", f"{archive}.manifest.txt"


def ensure_release_assets(
    client: ReleaseClient,
    release: SourceRelease,
    assets: Mapping[str, Path],
    notes: str,
) -> GitHubRelease:
    names = _expected_asset_names(release.tag.version)
    if set(assets) != set(names):
        raise DistributionError("release publication requires exactly three named assets")
    expected_bytes: dict[str, bytes] = {}
    for name in names:
        path = assets[name]
        try:
            expected_bytes[name] = path.read_bytes()
        except OSError as error:
            raise DistributionError(f"release asset is unreadable: {name}") from error
    matches = [item for item in client.list_releases() if item.tag_name == release.tag.tag_name]
    if len(matches) > 1:
        raise DistributionError(f"duplicate GitHub releases for tag {release.tag.tag_name}")
    current = matches[0] if matches else None
    if current is not None:
        by_name: dict[str, GitHubAsset] = {}
        for asset in current.assets:
            if asset.name not in names:
                continue
            if asset.name in by_name:
                raise DistributionError(f"duplicate expected release asset: {asset.name}")
            by_name[asset.name] = asset
        for name, asset in by_name.items():
            if client.download_asset(asset) != expected_bytes[name]:
                raise DistributionError(
                    f"refusing to overwrite different existing release asset: {name}"
                )
    else:
        current = client.create_release(
            release.tag.tag_name,
            f"JLCEDA2KICAD {release.tag.version}",
            notes,
            release.prerelease,
        )
        by_name = {}
    content_types = {
        names[0]: "application/zip",
        names[1]: "text/plain",
        names[2]: "text/plain",
    }
    for name in names:
        if name not in by_name:
            client.upload_asset(
                current.upload_url,
                name,
                expected_bytes[name],
                content_types[name],
            )
    refreshed = client.get_release(current.release_id)
    refreshed_names = [asset.name for asset in refreshed.assets if asset.name in names]
    if len(refreshed_names) != len(names) or set(refreshed_names) != set(names):
        raise DistributionError("GitHub release does not contain all expected assets")
    if refreshed.draft or refreshed.prerelease != release.prerelease:
        refreshed = client.update_release(
            refreshed.release_id,
            draft=False,
            prerelease=release.prerelease,
        )
    return refreshed


def load_public_release_payloads(client: ReleaseClient) -> tuple[ReleasePayload, ...]:
    releases = client.list_releases()
    supported: dict[str, tuple[tuple[int, int, int], GitHubRelease]] = {}
    for release in releases:
        if release.draft:
            continue
        try:
            tag = parse_release_tag(release.tag_name)
        except DistributionError:
            continue
        if tag.version in supported:
            raise DistributionError(f"duplicate public release tag: {release.tag_name}")
        supported[tag.version] = (tag.sort_key, release)
    payloads: list[tuple[tuple[int, int, int], ReleasePayload]] = []
    for version, (sort_key, release) in supported.items():
        names = _expected_asset_names(version)
        selected: dict[str, GitHubAsset] = {}
        for asset in release.assets:
            if asset.name not in names:
                continue
            if asset.name in selected:
                raise DistributionError(f"duplicate public release asset: {asset.name}")
            selected[asset.name] = asset
        if set(selected) != set(names):
            raise DistributionError(f"public release v{version} is missing required assets")
        if release.published_at is None:
            raise DistributionError(f"public release v{version} has no publication time")
        archive_asset = selected[names[0]]
        payloads.append(
            (
                sort_key,
                ReleasePayload(
                    tag_name=release.tag_name,
                    draft=False,
                    prerelease=release.prerelease,
                    published_at=release.published_at,
                    archive_name=names[0],
                    archive_url=archive_asset.browser_download_url,
                    archive=client.download_asset(archive_asset),
                    checksum=client.download_asset(selected[names[1]]),
                    manifest=client.download_asset(selected[names[2]]),
                ),
            )
        )
    return tuple(payload for _, payload in sorted(payloads, reverse=True))
