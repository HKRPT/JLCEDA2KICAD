import hashlib
import io
import json
import subprocess
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.build_package import build_package
from scripts.check_release import main as check_release_main
from scripts.release_policy import (
    DistributionError,
    ReleasePayload,
    inspect_release,
    parse_release_tag,
    validate_source_release,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("tag", "version", "sort_key"),
    [
        ("v0.1.0", "0.1.0", (0, 1, 0)),
        ("v10.20.300", "10.20.300", (10, 20, 300)),
    ],
)
def test_parse_supported_release_tags(
    tag: str, version: str, sort_key: tuple[int, int, int]
) -> None:
    parsed = parse_release_tag(tag)

    assert (parsed.version, parsed.sort_key) == (version, sort_key)


@pytest.mark.parametrize(
    "tag", ["0.1.0", "v1", "v1.2", "v1.2.3-beta", "v1.2.3-rc.1"]
)
def test_reject_unsupported_release_tags(tag: str) -> None:
    with pytest.raises(DistributionError, match="Unsupported release tag"):
        parse_release_tag(tag)


def test_validate_source_release_requires_version_status_and_main() -> None:
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))

    validated = validate_source_release("v0.1.0", "0.1.0", metadata, True)
    assert (validated.status, validated.prerelease) == ("stable", False)
    metadata["versions"][0]["status"] = "testing"
    testing = validate_source_release("v0.1.0", "0.1.0", metadata, True)
    assert (testing.status, testing.prerelease) == ("testing", True)
    with pytest.raises(DistributionError, match="project version"):
        validate_source_release("v0.1.0", "0.1.1", metadata, True)
    with pytest.raises(DistributionError, match="reachable from main"):
        validate_source_release("v0.1.0", "0.1.0", metadata, False)


def _payload(tmp_path: Path) -> ReleasePayload:
    result = build_package(tmp_path)
    return ReleasePayload(
        tag_name="v0.1.0",
        draft=False,
        prerelease=False,
        published_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        archive_name=result.archive.name,
        archive_url=(
            "https://github.com/HKRPT/JLCEDA2KICAD/releases/download/"
            "v0.1.0/JLCEDA2KICAD-0.1.0.zip"
        ),
        archive=result.archive.read_bytes(),
        checksum=result.sha256_file.read_bytes(),
        manifest=result.manifest_file.read_bytes(),
    )


def _rewrite_archive(payload: ReleasePayload, updates: dict[str, bytes]) -> ReleasePayload:
    source = io.BytesIO(payload.archive)
    destination = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(destination, "w") as new:
        for info in old.infolist():
            new.writestr(info, updates.get(info.filename, old.read(info.filename)))
    archive = destination.getvalue()
    checksum = f"{hashlib.sha256(archive).hexdigest()}  {payload.archive_name}\n".encode()
    return replace(payload, archive=archive, checksum=checksum)


def test_inspect_release_calculates_repository_fields(tmp_path: Path) -> None:
    published = inspect_release(_payload(tmp_path))

    assert published.version == "0.1.0"
    assert published.status == "stable"
    assert published.sha256 == hashlib.sha256(published.archive).hexdigest()
    assert published.download_size == len(published.archive)
    with zipfile.ZipFile(io.BytesIO(published.archive)) as archive:
        expected_install_size = sum(member.file_size for member in archive.infolist())
    assert published.install_size == expected_install_size
    assert published.download_url.endswith("/JLCEDA2KICAD-0.1.0.zip")


@pytest.mark.parametrize("field", ["checksum", "manifest", "archive"])
def test_inspect_release_rejects_mutated_assets(tmp_path: Path, field: str) -> None:
    payload = _payload(tmp_path)
    broken = replace(payload, **{field: getattr(payload, field) + b"changed"})

    with pytest.raises(DistributionError):
        inspect_release(broken)


def test_inspect_release_rejects_draft_and_wrong_prerelease_flag(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    with pytest.raises(DistributionError, match="draft"):
        inspect_release(replace(payload, draft=True))
    with pytest.raises(DistributionError, match="prerelease"):
        inspect_release(replace(payload, prerelease=True))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"identifier": "wrong.id"}, "identifier"),
        ({"versions": [{"version": "0.1.0"}, {"version": "0.2.0"}]}, "one version"),
    ],
)
def test_inspect_release_rejects_invalid_archive_metadata(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    payload = _payload(tmp_path)
    metadata = json.loads(
        zipfile.ZipFile(io.BytesIO(payload.archive)).read("metadata.json").decode()
    )
    metadata.update(mutation)
    broken = _rewrite_archive(
        payload,
        {"metadata.json": json.dumps(metadata).encode("utf-8")},
    )

    with pytest.raises(DistributionError, match=message):
        inspect_release(broken)


def test_inspect_release_rejects_download_fields_in_source_metadata(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    metadata = json.loads(
        zipfile.ZipFile(io.BytesIO(payload.archive)).read("metadata.json").decode()
    )
    metadata["versions"][0]["download_sha256"] = "0" * 64
    broken = _rewrite_archive(
        payload,
        {"metadata.json": json.dumps(metadata).encode("utf-8")},
    )

    with pytest.raises(DistributionError, match="download"):
        inspect_release(broken)


def test_inspect_release_rejects_duplicate_manifest_line(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    first = payload.manifest.splitlines()[0]

    with pytest.raises(DistributionError, match="manifest"):
        inspect_release(replace(payload, manifest=payload.manifest + first + b"\n"))


def test_release_sort_keys_use_semantic_order() -> None:
    tags = [parse_release_tag(tag) for tag in ("v0.1.9", "v0.2.0", "v0.1.10")]

    assert [tag.version for tag in sorted(tags, key=lambda item: item.sort_key, reverse=True)] == [
        "0.2.0",
        "0.1.10",
        "0.1.9",
    ]


def test_check_release_uses_list_command_and_writes_validated_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "github-output"
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("GITHUB_REF_NAME", "v0.1.0")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert check_release_main(["--github-output"]) == 0
    assert calls[0][0] == ["git", "merge-base", "--is-ancestor", "v0.1.0", "origin/main"]
    assert calls[0][1].get("shell") is None
    assert output.read_text(encoding="utf-8") == "version=0.1.0\nprerelease=false\n"


def test_check_release_rejects_tag_not_on_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )

    assert check_release_main(["--tag", "v0.1.0"]) == 2
