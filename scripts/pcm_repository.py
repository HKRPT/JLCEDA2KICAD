"""Build deterministic KiCad PCM v1 and v2 repository trees."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from jsonschema import Draft7Validator

from scripts.release_policy import (
    DistributionError,
    PublishedVersion,
    parse_release_tag,
)

_SCHEMA_BASE = "https://go.kicad.org/pcm/schemas"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ZIP_DATE = (2020, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class SiteBuildRequest:
    source_metadata: Mapping[str, object]
    versions: Sequence[PublishedVersion]
    icon: bytes
    index_html: bytes
    base_url: str
    updated_at: datetime
    output: Path


@dataclass(frozen=True, slots=True)
class SiteBuildResult:
    root: Path
    v1_repository: Path
    v2_repository: Path
    resources: Path


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DistributionError(f"URL contains unsupported components: {value}")
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.netloc:
        return value.rstrip("/")
    raise DistributionError(f"URL must use HTTPS or local 127.0.0.1 HTTP: {value}")


def _timestamp_fields(updated_at: datetime) -> dict[str, int | str]:
    if updated_at.tzinfo is None:
        raise DistributionError("repository update time must be timezone-aware")
    utc = updated_at.astimezone(UTC)
    return {
        "update_timestamp": int(utc.timestamp()),
        "update_time_utc": utc.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _version_record(item: PublishedVersion) -> dict[str, object]:
    _validate_url(item.download_url)
    if item.sha256 != item.sha256.lower() or len(item.sha256) != 64:
        raise DistributionError(f"release {item.version} SHA-256 must be lowercase hex")
    return {
        "version": item.version,
        "status": item.status,
        "kicad_version": item.kicad_version,
        "platforms": list(item.platforms),
        "runtime": item.runtime,
        "download_url": item.download_url,
        "download_sha256": item.sha256,
        "download_size": item.download_size,
        "install_size": item.install_size,
    }


def _ordered_versions(versions: Sequence[PublishedVersion]) -> list[PublishedVersion]:
    if not versions:
        raise DistributionError("at least one published release is required")
    seen: set[str] = set()
    keyed: list[tuple[tuple[int, int, int], PublishedVersion]] = []
    for item in versions:
        if item.version in seen:
            raise DistributionError(f"duplicate published version: {item.version}")
        seen.add(item.version)
        tag = parse_release_tag(f"v{item.version}")
        keyed.append((tag.sort_key, item))
    return [item for _, item in sorted(keyed, key=lambda pair: pair[0], reverse=True)]


def _resource_zip(path: Path, icon: bytes) -> None:
    if not icon.startswith(_PNG_SIGNATURE):
        raise DistributionError("repository icon must be a PNG file")
    info = zipfile.ZipInfo("io.hkrpt.jlc/icon.png", _ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, icon, compresslevel=9)


def _package_metadata(
    source: Mapping[str, object],
    versions: Sequence[PublishedVersion],
    schema_version: int,
) -> dict[str, object]:
    metadata = copy.deepcopy(dict(source))
    metadata["$schema"] = f"{_SCHEMA_BASE}/v{schema_version}"
    metadata["versions"] = [_version_record(item) for item in versions]
    return metadata


def _resource_descriptor(url: str, path: Path, updated_at: datetime) -> dict[str, object]:
    return {
        "url": url,
        "sha256": _sha256(path),
        **_timestamp_fields(updated_at),
    }


def _repository_descriptor(
    *,
    schema_version: int,
    base_url: str,
    packages_path: Path,
    resources_path: Path,
    updated_at: datetime,
) -> dict[str, object]:
    descriptor: dict[str, object] = {
        "$schema": f"{_SCHEMA_BASE}/v{schema_version}#/definitions/Repository",
        "name": "JLCEDA2KICAD Addon Repository",
        "maintainer": {
            "name": "HKRPT",
            "contact": {"web": "https://github.com/HKRPT/JLCEDA2KICAD"},
        },
        "packages": _resource_descriptor(
            f"{base_url}/v{schema_version}/packages.json",
            packages_path,
            updated_at,
        ),
        "resources": _resource_descriptor(
            f"{base_url}/resources.zip",
            resources_path,
            updated_at,
        ),
    }
    if schema_version == 2:
        descriptor["schema_version"] = 2
    return descriptor


def _schema(name: str, definition: str) -> dict[str, object]:
    raw = files("kipy.packaging.schemas").joinpath(name).read_text(encoding="utf-8")
    schema = cast(dict[str, object], json.loads(raw))
    schema["$ref"] = f"#/definitions/{definition}"
    return schema


def _validate_json(
    value: object,
    schema_name: str,
    definition: str,
    relative_path: str,
) -> None:
    errors = sorted(
        Draft7Validator(_schema(schema_name, definition)).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = "/".join(str(part) for part in error.absolute_path) or "$"
    raise DistributionError(f"{relative_path} at {location}: {error.message}")


def _load_json(path: Path, root: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DistributionError(f"{path.relative_to(root).as_posix()} is invalid JSON") from error


def _validate_resource_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if [info.filename for info in infos] != ["io.hkrpt.jlc/icon.png"]:
                raise DistributionError("resources.zip contains unexpected members")
            if not archive.read(infos[0]).startswith(_PNG_SIGNATURE):
                raise DistributionError("resources.zip icon is not PNG data")
    except zipfile.BadZipFile as error:
        raise DistributionError("resources.zip is invalid") from error


def validate_site(root: Path) -> None:
    resources_path = root / "resources.zip"
    _validate_resource_zip(resources_path)
    for schema_version in (1, 2):
        schema_name = f"pcm.v{schema_version}.schema.json"
        repository_path = root / f"v{schema_version}" / "repository.json"
        packages_path = root / f"v{schema_version}" / "packages.json"
        repository = _load_json(repository_path, root)
        packages = _load_json(packages_path, root)
        relative_repository = repository_path.relative_to(root).as_posix()
        relative_packages = packages_path.relative_to(root).as_posix()
        _validate_json(repository, schema_name, "Repository", relative_repository)
        _validate_json(packages, schema_name, "PackageArray", relative_packages)
        repository_mapping = cast(Mapping[str, object], repository)
        for key, target in (("packages", packages_path), ("resources", resources_path)):
            descriptor = cast(Mapping[str, object], repository_mapping[key])
            _validate_url(cast(str, descriptor["url"]))
            actual_hash = _sha256(target)
            if descriptor.get("sha256") != actual_hash:
                raise DistributionError(
                    f"{relative_repository} {key}.sha256 does not match {target.name}"
                )


def build_site(request: SiteBuildRequest) -> SiteBuildResult:
    output = request.output.resolve()
    if output.exists():
        raise DistributionError(f"repository output already exists: {output}")
    base_url = _validate_url(request.base_url)
    ordered_versions = _ordered_versions(request.versions)
    if not request.index_html.strip():
        raise DistributionError("repository landing page is empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="jlceda2kicad-site-", dir=output.parent))
    try:
        (temporary / "index.html").write_bytes(request.index_html)
        resources_path = temporary / "resources.zip"
        _resource_zip(resources_path, request.icon)
        for schema_version in (1, 2):
            directory = temporary / f"v{schema_version}"
            packages_path = directory / "packages.json"
            repository_path = directory / "repository.json"
            package = _package_metadata(
                request.source_metadata,
                ordered_versions,
                schema_version,
            )
            _write_json(packages_path, {"packages": [package]})
            descriptor = _repository_descriptor(
                schema_version=schema_version,
                base_url=base_url,
                packages_path=packages_path,
                resources_path=resources_path,
                updated_at=request.updated_at,
            )
            _write_json(repository_path, descriptor)
        validate_site(temporary)
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return SiteBuildResult(
        root=output,
        v1_repository=output / "v1" / "repository.json",
        v2_repository=output / "v2" / "repository.json",
        resources=output / "resources.zip",
    )
