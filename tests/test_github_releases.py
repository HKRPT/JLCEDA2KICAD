import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.github_releases import (
    GitHubAsset,
    GitHubClient,
    GitHubRelease,
    HttpRequest,
    HttpResponse,
    ensure_release_assets,
)
from scripts.release_policy import DistributionError, SourceRelease, parse_release_tag


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def _response(status: int, body: object, headers: dict[str, str] | None = None) -> HttpResponse:
    encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
    return HttpResponse(status, headers or {}, encoded)


def _asset_json(asset_id: int, name: str, data: bytes = b"") -> dict[str, object]:
    return {
        "id": asset_id,
        "name": name,
        "url": f"https://api.github.com/repos/owner/repo/releases/assets/{asset_id}",
        "browser_download_url": f"https://github.com/owner/repo/releases/download/v0.1.0/{name}",
        "size": len(data),
    }


def _release_json(
    release_id: int,
    tag: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    assets: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": release_id,
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": None if draft else "2026-07-15T08:00:00Z",
        "upload_url": f"https://uploads.github.com/repos/owner/repo/releases/{release_id}/assets{{?name,label}}",
        "assets": assets or [],
    }


def test_list_releases_follows_link_pagination_without_leaking_token() -> None:
    transport = FakeTransport(
        [
            _response(
                200,
                [_release_json(2, "v0.2.0")],
                {
                    "Link": '<https://api.github.com/repos/owner/repo/releases?page=2>; rel="next"'
                },
            ),
            _response(200, [_release_json(1, "v0.1.0")]),
        ]
    )
    client = GitHubClient("owner/repo", "secret-token", transport)

    releases = client.list_releases()

    assert [release.tag_name for release in releases] == ["v0.2.0", "v0.1.0"]
    assert all(
        request.headers["Authorization"] == "Bearer secret-token"
        for request in transport.requests
    )
    assert "secret-token" not in repr(client)
    assert "secret-token" not in repr(releases)


@pytest.mark.parametrize("status", [403, 404, 500])
def test_api_errors_are_redacted(status: int) -> None:
    transport = FakeTransport([_response(status, {"token": "secret-token"})])
    client = GitHubClient("owner/repo", "secret-token", transport)

    with pytest.raises(DistributionError, match=str(status)) as caught:
        client.list_releases()
    assert "secret-token" not in str(caught.value)


def test_list_releases_rejects_malformed_json_and_bad_next_url() -> None:
    client = GitHubClient("owner/repo", "token", FakeTransport([_response(200, b"{")]))
    with pytest.raises(DistributionError, match="JSON"):
        client.list_releases()

    transport = FakeTransport(
        [_response(200, [], {"Link": '<not-a-url>; rel="next"'})]
    )
    client = GitHubClient("owner/repo", "token", transport)
    with pytest.raises(DistributionError, match="pagination"):
        client.list_releases()


def test_list_releases_stops_when_link_header_has_no_next_relation() -> None:
    transport = FakeTransport(
        [_response(200, [], {"Link": '<https://api.github.com/page=1>; rel="prev"'})]
    )

    assert GitHubClient("owner/repo", "token", transport).list_releases() == ()


def test_asset_requests_reject_untrusted_hosts_before_sending_token() -> None:
    transport = FakeTransport([])
    client = GitHubClient("owner/repo", "token", transport)
    asset = GitHubAsset(1, "asset.zip", "https://example.invalid/asset", "", 1)

    with pytest.raises(DistributionError, match="asset API URL"):
        client.download_asset(asset)
    with pytest.raises(DistributionError, match="upload URL"):
        client.upload_asset(
            "https://example.invalid/assets{?name}",
            "asset.zip",
            b"x",
            "application/zip",
        )
    assert transport.requests == []


def test_upload_strips_template_and_sets_content_type() -> None:
    asset = _asset_json(7, "demo.zip")
    transport = FakeTransport([_response(201, asset)])
    client = GitHubClient("owner/repo", "token", transport)

    uploaded = client.upload_asset(
        "https://uploads.github.com/repos/owner/repo/releases/3/assets{?name,label}",
        "demo.zip",
        b"zip",
        "application/zip",
    )

    assert uploaded.name == "demo.zip"
    request = transport.requests[0]
    assert request.url.endswith("/assets?name=demo.zip")
    assert request.headers["Content-Type"] == "application/zip"
    assert request.timeout_seconds == 600


class MemoryClient:
    def __init__(
        self,
        releases: list[GitHubRelease],
        bytes_by_asset: dict[int, bytes],
    ) -> None:
        self.releases = releases
        self.bytes_by_asset = bytes_by_asset
        self.uploads: list[tuple[str, bytes, str]] = []
        self.created: list[tuple[str, str, str, bool]] = []
        self.patches: list[tuple[int, bool, bool]] = []
        self.next_asset_id = 100

    def list_releases(self) -> tuple[GitHubRelease, ...]:
        return tuple(self.releases)

    def download_asset(self, asset: GitHubAsset) -> bytes:
        return self.bytes_by_asset[asset.asset_id]

    def create_release(
        self, tag_name: str, title: str, body: str, prerelease: bool
    ) -> GitHubRelease:
        self.created.append((tag_name, title, body, prerelease))
        release = GitHubRelease(
            9,
            tag_name,
            True,
            prerelease,
            None,
            "https://uploads.github.com/repos/owner/repo/releases/9/assets{?name,label}",
            (),
        )
        self.releases.append(release)
        return release

    def upload_asset(
        self, upload_url: str, name: str, data: bytes, content_type: str
    ) -> GitHubAsset:
        self.uploads.append((name, data, content_type))
        asset_id = self.next_asset_id
        self.next_asset_id += 1
        asset = GitHubAsset(
            asset_id,
            name,
            f"https://api.github.com/assets/{asset_id}",
            f"https://github.com/download/{name}",
            len(data),
        )
        self.bytes_by_asset[asset_id] = data
        release = self.releases[-1]
        self.releases[-1] = GitHubRelease(
            release.release_id,
            release.tag_name,
            release.draft,
            release.prerelease,
            release.published_at,
            release.upload_url,
            (*release.assets, asset),
        )
        return asset

    def get_release(self, release_id: int) -> GitHubRelease:
        return next(item for item in self.releases if item.release_id == release_id)

    def update_release(
        self, release_id: int, *, draft: bool, prerelease: bool
    ) -> GitHubRelease:
        self.patches.append((release_id, draft, prerelease))
        release = self.get_release(release_id)
        updated = GitHubRelease(
            release.release_id,
            release.tag_name,
            draft,
            prerelease,
            datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
            release.upload_url,
            release.assets,
        )
        self.releases[self.releases.index(release)] = updated
        return updated


def _source(status: str = "stable") -> SourceRelease:
    return SourceRelease(parse_release_tag("v0.1.0"), status, status == "testing")  # type: ignore[arg-type]


def _asset_paths(tmp_path: Path) -> dict[str, Path]:
    values = {
        "JLCEDA2KICAD-0.1.0.zip": b"zip",
        "JLCEDA2KICAD-0.1.0.zip.sha256": b"sha",
        "JLCEDA2KICAD-0.1.0.zip.manifest.txt": b"manifest",
    }
    paths: dict[str, Path] = {}
    for name, data in values.items():
        path = tmp_path / name
        path.write_bytes(data)
        paths[name] = path
    return paths


def _existing_release(paths: dict[str, Path]) -> tuple[GitHubRelease, dict[int, bytes]]:
    assets = tuple(
        GitHubAsset(
            index,
            name,
            f"https://api/{index}",
            f"https://download/{name}",
            path.stat().st_size,
        )
        for index, (name, path) in enumerate(paths.items(), start=1)
    )
    return (
        GitHubRelease(
            1,
            "v0.1.0",
            False,
            False,
            datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
            "https://uploads/1/assets{?name,label}",
            assets,
        ),
        {asset.asset_id: paths[asset.name].read_bytes() for asset in assets},
    )


def test_ensure_release_reuses_identical_assets(tmp_path: Path) -> None:
    paths = _asset_paths(tmp_path)
    release, data = _existing_release(paths)
    client = MemoryClient([release], data)

    result = ensure_release_assets(client, _source(), paths, "notes")  # type: ignore[arg-type]

    assert result.draft is False
    assert not client.uploads
    assert not client.patches


def test_ensure_release_rejects_different_existing_bytes(tmp_path: Path) -> None:
    paths = _asset_paths(tmp_path)
    release, data = _existing_release(paths)
    data[release.assets[0].asset_id] = b"changed"
    client = MemoryClient([release], data)

    with pytest.raises(DistributionError, match="refusing to overwrite"):
        ensure_release_assets(client, _source(), paths, "notes")  # type: ignore[arg-type]
    assert not client.uploads


@pytest.mark.parametrize(("status", "prerelease"), [("stable", False), ("testing", True)])
def test_ensure_release_creates_draft_uploads_three_then_publishes(
    tmp_path: Path, status: str, prerelease: bool
) -> None:
    paths = _asset_paths(tmp_path)
    client = MemoryClient([], {})

    result = ensure_release_assets(client, _source(status), paths, "release notes")  # type: ignore[arg-type]

    assert client.created == [
        ("v0.1.0", "JLCEDA2KICAD 0.1.0", "release notes", prerelease)
    ]
    assert [item[0] for item in client.uploads] == list(paths)
    assert [item[2] for item in client.uploads] == [
        "application/zip",
        "text/plain",
        "text/plain",
    ]
    assert client.patches == [(9, False, prerelease)]
    assert (result.draft, result.prerelease) == (False, prerelease)


def test_ensure_release_rejects_duplicate_matching_tags(tmp_path: Path) -> None:
    paths = _asset_paths(tmp_path)
    release, data = _existing_release(paths)
    client = MemoryClient([release, release], data)

    with pytest.raises(DistributionError, match="duplicate"):
        ensure_release_assets(client, _source(), paths, "notes")  # type: ignore[arg-type]
