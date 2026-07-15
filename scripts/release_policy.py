"""Validate immutable GitHub Release inputs for KiCad PCM distribution."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, cast

Status = Literal["stable", "testing"]
_TAG = re.compile(r"^v(\d{1,4})\.(\d{1,4})\.(\d{1,6})$")
_DOWNLOAD_FIELDS = {"download_url", "download_sha256", "download_size", "install_size"}


class DistributionError(RuntimeError):
    """A release or repository input is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ReleaseTag:
    tag_name: str
    version: str
    sort_key: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SourceRelease:
    tag: ReleaseTag
    status: Status
    prerelease: bool


@dataclass(frozen=True, slots=True)
class ReleasePayload:
    tag_name: str
    draft: bool
    prerelease: bool
    published_at: datetime
    archive_name: str
    archive_url: str
    archive: bytes
    checksum: bytes
    manifest: bytes


@dataclass(frozen=True, slots=True)
class PublishedVersion:
    version: str
    status: Status
    kicad_version: str
    platforms: tuple[str, ...]
    runtime: str
    published_at: datetime
    download_url: str
    sha256: str
    download_size: int
    install_size: int
    archive: bytes = field(repr=False)


def parse_release_tag(tag_name: str) -> ReleaseTag:
    match = _TAG.fullmatch(tag_name)
    if match is None:
        raise DistributionError(f"Unsupported release tag: {tag_name}")
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    return ReleaseTag(tag_name, f"{major}.{minor}.{patch}", (major, minor, patch))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DistributionError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def validate_source_release(
    tag_name: str,
    project_version: str,
    metadata: Mapping[str, object],
    is_main_ancestor: bool,
) -> SourceRelease:
    tag = parse_release_tag(tag_name)
    if project_version != tag.version:
        raise DistributionError(
            f"release tag {tag.version} does not match project version {project_version}"
        )
    versions = metadata.get("versions")
    if not isinstance(versions, list) or len(versions) != 1:
        raise DistributionError("PCM metadata must contain exactly one version")
    version = _mapping(versions[0], "PCM version")
    if version.get("version") != tag.version:
        raise DistributionError("PCM metadata version does not match the release tag")
    status = version.get("status")
    if status not in {"stable", "testing"}:
        raise DistributionError("PCM status must be stable or testing")
    if metadata.get("identifier") != "io.hkrpt.jlc":
        raise DistributionError("PCM identifier must be io.hkrpt.jlc")
    if metadata.get("type") != "plugin":
        raise DistributionError("PCM type must be plugin")
    if version.get("platforms") != ["windows"]:
        raise DistributionError("PCM platforms must contain only windows")
    if version.get("runtime") != "ipc":
        raise DistributionError("PCM runtime must be ipc")
    if version.get("kicad_version") != "9.0.1":
        raise DistributionError("PCM minimum KiCad version must be 9.0.1")
    present_download_fields = sorted(_DOWNLOAD_FIELDS.intersection(version))
    if present_download_fields:
        raise DistributionError(
            "source PCM metadata must not contain download fields: "
            + ", ".join(present_download_fields)
        )
    if not is_main_ancestor:
        raise DistributionError("release tag must be reachable from main")
    typed_status = cast(Status, status)
    return SourceRelease(tag, typed_status, typed_status == "testing")


def _safe_member_names(infos: list[zipfile.ZipInfo]) -> list[str]:
    names: list[str] = []
    folded: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise DistributionError(f"unsafe PCM archive member: {name!r}")
        if name.casefold() in folded:
            raise DistributionError(f"duplicate PCM archive member: {name}")
        folded.add(name.casefold())
        names.append(name)
    return names


def inspect_release(payload: ReleasePayload) -> PublishedVersion:
    if payload.draft:
        raise DistributionError("draft releases cannot be published to a PCM repository")
    tag = parse_release_tag(payload.tag_name)
    expected_archive = f"JLCEDA2KICAD-{tag.version}.zip"
    if payload.archive_name != expected_archive:
        raise DistributionError("release archive name does not match the release tag")
    digest = hashlib.sha256(payload.archive).hexdigest()
    expected_checksum = f"{digest}  {expected_archive}\n".encode("ascii")
    if payload.checksum != expected_checksum:
        raise DistributionError("release checksum sidecar does not match the archive")
    if not payload.archive_url.startswith("https://") or not payload.archive_url.endswith(
        f"/{expected_archive}"
    ):
        raise DistributionError("release archive URL is invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(payload.archive)) as archive:
            infos = archive.infolist()
            member_names = _safe_member_names(infos)
            manifest_text = payload.manifest.decode("utf-8")
            manifest_names = manifest_text.splitlines()
            if manifest_text != "\n".join(manifest_names) + "\n":
                raise DistributionError("release manifest must end with one newline")
            if manifest_names != sorted(member_names) or len(set(manifest_names)) != len(
                manifest_names
            ):
                raise DistributionError("release manifest does not match archive members")
            if "metadata.json" not in member_names:
                raise DistributionError("PCM archive is missing metadata.json")
            metadata_raw = json.loads(archive.read("metadata.json").decode("utf-8"))
            metadata = _mapping(metadata_raw, "PCM metadata")
            source = validate_source_release(
                payload.tag_name,
                tag.version,
                metadata,
                True,
            )
            install_size = sum(info.file_size for info in infos)
    except DistributionError:
        raise
    except (KeyError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise DistributionError("release assets are not a valid PCM package") from error
    if payload.prerelease != source.prerelease:
        raise DistributionError("GitHub prerelease flag does not match PCM status")
    version_record = _mapping(cast(list[object], metadata["versions"])[0], "PCM version")
    return PublishedVersion(
        version=tag.version,
        status=source.status,
        kicad_version=cast(str, version_record["kicad_version"]),
        platforms=tuple(cast(list[str], version_record["platforms"])),
        runtime=cast(str, version_record["runtime"]),
        published_at=payload.published_at,
        download_url=payload.archive_url,
        sha256=digest,
        download_size=len(payload.archive),
        install_size=install_size,
        archive=payload.archive,
    )
