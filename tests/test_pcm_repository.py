import hashlib
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.build_package import build_package
from scripts.pcm_repository import (
    SiteBuildRequest,
    build_site,
    validate_site,
)
from scripts.release_policy import DistributionError, ReleasePayload, inspect_release

ROOT = Path(__file__).resolve().parents[1]


def _published(tmp_path: Path, version: str = "0.1.0"):
    result = build_package(tmp_path / "dist")
    payload = ReleasePayload(
        tag_name=f"v{version}",
        draft=False,
        prerelease=False,
        published_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        archive_name=result.archive.name,
        archive_url=(
            "https://github.com/HKRPT/JLCEDA2KICAD/releases/download/"
            f"v{version}/{result.archive.name}"
        ),
        archive=result.archive.read_bytes(),
        checksum=result.sha256_file.read_bytes(),
        manifest=result.manifest_file.read_bytes(),
    )
    return inspect_release(payload)


def _site_request(tmp_path: Path) -> SiteBuildRequest:
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
    return SiteBuildRequest(
        source_metadata=metadata,
        versions=(_published(tmp_path),),
        icon=(ROOT / "resources/icon_64.png").read_bytes(),
        index_html=b"<!doctype html><title>JLCEDA2KICAD</title>\n",
        base_url="https://hkrpt.github.io/JLCEDA2KICAD",
        updated_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        output=tmp_path / "site",
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_build_site_writes_both_schema_variants(tmp_path: Path) -> None:
    result = build_site(_site_request(tmp_path))

    v1_repository = json.loads((result.root / "v1/repository.json").read_text("utf-8"))
    v2_repository = json.loads((result.root / "v2/repository.json").read_text("utf-8"))
    v1_packages = json.loads((result.root / "v1/packages.json").read_text("utf-8"))
    v2_packages = json.loads((result.root / "v2/packages.json").read_text("utf-8"))

    assert "schema_version" not in v1_repository
    assert v2_repository["schema_version"] == 2
    assert v1_packages["packages"][0]["$schema"].endswith("/v1")
    assert v2_packages["packages"][0]["$schema"].endswith("/v2")
    assert v1_packages["packages"][0]["versions"] == v2_packages["packages"][0]["versions"]
    assert v1_repository["packages"]["url"].endswith("/v1/packages.json")
    assert v2_repository["packages"]["url"].endswith("/v2/packages.json")


def test_resources_zip_uses_identifier_icon_path(tmp_path: Path) -> None:
    result = build_site(_site_request(tmp_path))

    with zipfile.ZipFile(result.root / "resources.zip") as archive:
        assert archive.namelist() == ["io.hkrpt.jlc/icon.png"]
        assert archive.read("io.hkrpt.jlc/icon.png") == (
            ROOT / "resources/icon_64.png"
        ).read_bytes()


def test_site_is_deterministic_for_fixed_inputs(tmp_path: Path) -> None:
    first = build_site(_site_request(tmp_path / "one"))
    second = build_site(_site_request(tmp_path / "two"))

    assert _tree_hashes(first.root) == _tree_hashes(second.root)


def test_versions_are_newest_first_and_have_exact_release_fields(tmp_path: Path) -> None:
    request = _site_request(tmp_path)
    older = replace(request.versions[0], version="0.1.9")
    newer = replace(request.versions[0], version="0.1.10")
    request = replace(request, versions=(older, newer))

    result = build_site(request)
    package = json.loads((result.root / "v2/packages.json").read_text("utf-8"))["packages"][0]
    versions = package["versions"]

    assert [item["version"] for item in versions] == ["0.1.10", "0.1.9"]
    assert versions[0]["download_sha256"] == newer.sha256.lower()
    assert versions[0]["download_size"] == newer.download_size
    assert versions[0]["install_size"] == newer.install_size


def test_repository_timestamps_are_utc_and_hashes_are_lowercase(tmp_path: Path) -> None:
    result = build_site(_site_request(tmp_path))
    repository = json.loads((result.v2_repository).read_text("utf-8"))

    assert repository["packages"]["update_time_utc"] == "2026-07-15 08:00:00"
    assert repository["packages"]["update_timestamp"] == 1784102400
    assert repository["packages"]["sha256"] == repository["packages"]["sha256"].lower()


@pytest.mark.parametrize(
    ("url", "accepted"),
    [
        ("https://example.com/repository", True),
        ("http://127.0.0.1:8000", True),
        ("http://localhost:8000", False),
        ("http://example.com", False),
        ("relative/path", False),
    ],
)
def test_site_restricts_base_urls(tmp_path: Path, url: str, accepted: bool) -> None:
    request = replace(_site_request(tmp_path), base_url=url)
    if accepted:
        assert build_site(request).root.is_dir()
    else:
        with pytest.raises(DistributionError, match="URL"):
            build_site(request)


def test_site_rejects_duplicate_or_missing_versions(tmp_path: Path) -> None:
    request = _site_request(tmp_path)
    with pytest.raises(DistributionError, match="release"):
        build_site(replace(request, versions=()))
    with pytest.raises(DistributionError, match="duplicate"):
        build_site(replace(request, versions=(request.versions[0], request.versions[0])))


def test_site_rejects_invalid_icon_and_existing_output(tmp_path: Path) -> None:
    request = _site_request(tmp_path)
    with pytest.raises(DistributionError, match="PNG"):
        build_site(replace(request, icon=b"not png"))
    request.output.mkdir()
    with pytest.raises(DistributionError, match="exists"):
        build_site(request)


def test_schema_failure_leaves_no_output_directory(tmp_path: Path) -> None:
    request = _site_request(tmp_path)
    broken_metadata = dict(request.source_metadata)
    broken_metadata["author"] = {"name": "missing contact"}
    request = replace(request, source_metadata=broken_metadata)

    with pytest.raises(DistributionError, match=r"packages\.json"):
        build_site(request)
    assert not request.output.exists()


def test_validate_site_rejects_tampered_descriptor_hash(tmp_path: Path) -> None:
    result = build_site(_site_request(tmp_path))
    packages = result.root / "v2/packages.json"
    packages.write_bytes(packages.read_bytes() + b" ")

    with pytest.raises(DistributionError, match="sha256"):
        validate_site(result.root)
