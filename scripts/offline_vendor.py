"""Download, validate, and expand a Windows CPython 3.11 wheel runtime."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import stat
import subprocess
import sys
import zipfile
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD_EXCEPTIONS = ROOT / "offline-wheel-record-exceptions.json"


class VendorError(RuntimeError):
    """Raised when a wheel set cannot safely form the bundled runtime."""


@dataclass(frozen=True, slots=True)
class WheelRecord:
    name: str
    version: str
    filename: str
    sha256: str
    license_expression: str
    requires_dist: tuple[str, ...]
    license_files: tuple[str, ...]
    integrity_exceptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RecordException:
    filename: str
    wheel_sha256: str
    member: str
    record_digest: str
    record_size: str
    actual_digest: str
    actual_size: str
    reason: str


@dataclass(frozen=True, slots=True)
class _InspectedWheel:
    path: Path
    record: WheelRecord
    dist_info: str


def _safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise VendorError(f"unsafe wheel member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise VendorError(f"unsafe wheel member path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise VendorError(f"unsafe wheel member path: {name!r}")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def _urlsafe_sha256(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def _inspect_wheel(
    path: Path,
    record_exceptions: dict[tuple[str, str], _RecordException],
) -> _InspectedWheel:
    try:
        filename_name, filename_version, _build, wheel_tags = parse_wheel_filename(path.name)
    except Exception as exc:
        raise VendorError(f"invalid wheel filename: {path.name}") from exc
    supported = frozenset(sys_tags())
    if wheel_tags.isdisjoint(supported):
        raise VendorError(f"incompatible wheel tag: {path.name}")

    wheel_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        seen_names: set[str] = set()
        for info in infos:
            _safe_member_path(info.filename)
            if _is_symlink(info):
                raise VendorError(f"wheel contains symlink: {path.name}:{info.filename}")
            if info.filename in seen_names:
                raise VendorError(f"duplicate member in wheel: {path.name}:{info.filename}")
            seen_names.add(info.filename)

        metadata_names = [
            info.filename
            for info in infos
            if info.filename.endswith(".dist-info/METADATA")
        ]
        record_names = [
            info.filename for info in infos if info.filename.endswith(".dist-info/RECORD")
        ]
        if len(metadata_names) != 1 or len(record_names) != 1:
            raise VendorError(f"wheel must contain one METADATA and one RECORD: {path.name}")
        dist_info = metadata_names[0].rsplit("/", 1)[0]
        if record_names[0].rsplit("/", 1)[0] != dist_info:
            raise VendorError(f"METADATA and RECORD use different dist-info paths: {path.name}")

        message = BytesParser().parsebytes(archive.read(metadata_names[0]))
        metadata_name = message.get("Name")
        metadata_version = message.get("Version")
        if not metadata_name or not metadata_version:
            raise VendorError(f"wheel METADATA is missing Name or Version: {path.name}")
        if (
            canonicalize_name(metadata_name) != filename_name
            or str(filename_version) != metadata_version
        ):
            raise VendorError(f"wheel filename and METADATA disagree: {path.name}")

        integrity_exceptions = _validate_record(
            archive,
            record_names[0],
            infos,
            path.name,
            wheel_sha256,
            record_exceptions,
        )
        license_members = tuple(
            sorted(
                info.filename
                for info in infos
                if info.filename.startswith(f"{dist_info}/")
                and PurePosixPath(info.filename).name.upper().startswith(
                    ("LICENSE", "COPYING", "NOTICE")
                )
            )
        )
        declared_license = str(
            message.get("License-Expression") or message.get("License") or ""
        )
        if not declared_license and not license_members:
            raise VendorError(f"wheel contains no license evidence: {path.name}")
        requirements = tuple(message.get_all("Requires-Dist") or ())
        record = WheelRecord(
            name=str(filename_name),
            version=metadata_version,
            filename=path.name,
            sha256=wheel_sha256,
            license_expression=declared_license,
            requires_dist=requirements,
            license_files=tuple(PurePosixPath(member).name for member in license_members),
            integrity_exceptions=integrity_exceptions,
        )
    return _InspectedWheel(path=path, record=record, dist_info=dist_info)


def _validate_record(
    archive: zipfile.ZipFile,
    record_name: str,
    infos: Sequence[zipfile.ZipInfo],
    wheel_name: str,
    wheel_sha256: str,
    exceptions: dict[tuple[str, str], _RecordException],
) -> tuple[str, ...]:
    try:
        rows = list(csv.reader(archive.read(record_name).decode("utf-8").splitlines()))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise VendorError(f"malformed wheel RECORD: {wheel_name}") from exc
    entries: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            raise VendorError(f"malformed wheel RECORD row: {wheel_name}")
        member, digest, size = row
        _safe_member_path(member)
        if member in entries:
            raise VendorError(f"duplicate wheel RECORD row: {wheel_name}:{member}")
        entries[member] = (digest, size)
    accepted: list[str] = []
    for info in infos:
        if info.filename not in entries:
            raise VendorError(f"wheel member is absent from RECORD: {wheel_name}:{info.filename}")
        if info.filename == record_name:
            continue
        digest, size = entries[info.filename]
        data = archive.read(info.filename)
        actual_digest = f"sha256={_urlsafe_sha256(data)}"
        actual_size = str(len(data))
        if digest != actual_digest or size != actual_size:
            exception = exceptions.get((wheel_name, info.filename))
            observed = (
                wheel_name,
                wheel_sha256,
                info.filename,
                digest,
                size,
                actual_digest,
                actual_size,
            )
            expected = None
            if exception is not None:
                expected = (
                    exception.filename,
                    exception.wheel_sha256,
                    exception.member,
                    exception.record_digest,
                    exception.record_size,
                    exception.actual_digest,
                    exception.actual_size,
                )
            if observed != expected:
                raise VendorError(f"wheel RECORD hash mismatch: {wheel_name}:{info.filename}")
            assert exception is not None
            accepted.append(f"{wheel_name}:{info.filename}: {exception.reason}")
    return tuple(accepted)


def _load_record_exceptions(path: Path | None) -> dict[tuple[str, str], _RecordException]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("root must be a list")
        result: dict[tuple[str, str], _RecordException] = {}
        for item in payload:
            if not isinstance(item, dict):
                raise TypeError("entries must be objects")
            exception = _RecordException(**item)
            key = (exception.filename, exception.member)
            if key in result:
                raise TypeError(f"duplicate entry: {key}")
            result[key] = exception
        return result
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise VendorError(f"invalid RECORD exception file: {path}") from exc


def _vendor_member_path(member: str) -> PurePosixPath:
    path = _safe_member_path(member)
    if path.parts[0].endswith(".data"):
        if len(path.parts) < 3 or path.parts[1] not in {"purelib", "platlib"}:
            raise VendorError(f"unsupported wheel data scheme: {member}")
        return PurePosixPath(*path.parts[2:])
    return path


def _write_exact(destination: Path, data: bytes, owner: str, owners: dict[Path, str]) -> None:
    if destination in owners:
        if destination.read_bytes() != data:
            raise VendorError(
                f"conflicting wheel members at {destination}: {owners[destination]} and {owner}"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    owners[destination] = owner


def expand_wheels(
    wheelhouse: Path,
    vendor: Path,
    licenses: Path,
    *,
    record_exceptions: Path | None = DEFAULT_RECORD_EXCEPTIONS,
) -> tuple[WheelRecord, ...]:
    """Validate and expand all wheels into fresh vendor and license directories."""

    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.lower())
    if not wheels:
        raise VendorError(f"wheelhouse contains no wheels: {wheelhouse}")
    for output in (vendor, licenses):
        if output.exists() and any(output.iterdir()):
            raise VendorError(f"output directory must be empty: {output}")
        output.mkdir(parents=True, exist_ok=True)
    vendor_root = vendor.resolve()
    license_root = licenses.resolve()
    owners: dict[Path, str] = {}
    license_owners: dict[Path, str] = {}
    records: list[WheelRecord] = []
    exceptions = _load_record_exceptions(record_exceptions)

    for inspected in (_inspect_wheel(path, exceptions) for path in wheels):
        records.append(inspected.record)
        with zipfile.ZipFile(inspected.path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                if info.is_dir():
                    continue
                relative = _vendor_member_path(info.filename)
                destination = vendor.joinpath(*relative.parts).resolve()
                if not destination.is_relative_to(vendor_root):
                    raise VendorError(f"wheel member escapes vendor directory: {info.filename}")
                data = archive.read(info.filename)
                _write_exact(destination, data, inspected.path.name, owners)

                if (
                    info.filename.startswith(f"{inspected.dist_info}/")
                    and relative.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))
                ):
                    license_destination = (
                        licenses / inspected.record.name / relative.name
                    ).resolve()
                    if not license_destination.is_relative_to(license_root):
                        raise VendorError(
                            f"license member escapes license directory: {info.filename}"
                        )
                    _write_exact(
                        license_destination,
                        data,
                        inspected.path.name,
                        license_owners,
                    )
    return tuple(sorted(records, key=lambda item: item.name))


def write_inventory(records: Iterable[WheelRecord], destination: Path) -> None:
    payload = [asdict(record) for record in sorted(records, key=lambda item: item.name)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def verify_runtime_closure(vendor: Path, roots: Sequence[str]) -> tuple[str, ...]:
    """Verify root requirements and all active recursive metadata requirements."""

    distributions: dict[str, importlib.metadata.Distribution] = {}
    for distribution in importlib.metadata.distributions(path=[str(vendor)]):
        distribution_name = distribution.metadata["Name"]
        if distribution_name:
            distributions[canonicalize_name(distribution_name)] = distribution
    marker_environment = {
        key: str(value) for key, value in default_environment().items()
    }
    marker_environment.update(
        {
            "implementation_name": "cpython",
            "platform_machine": "AMD64",
            "platform_system": "Windows",
            "python_full_version": "3.11.5",
            "python_version": "3.11",
            "sys_platform": "win32",
        }
    )
    queue = deque(Requirement(root) for root in roots)
    seen: set[str] = set()
    verified: list[str] = []
    while queue:
        requirement = queue.popleft()
        if requirement.marker and not requirement.marker.evaluate(
            marker_environment | {"extra": ""}
        ):
            continue
        name = canonicalize_name(requirement.name)
        current_distribution = distributions.get(name)
        if current_distribution is None:
            raise VendorError(f"missing runtime dependency: {requirement}")
        version = current_distribution.version
        if requirement.specifier and version not in requirement.specifier:
            raise VendorError(
                f"runtime dependency version mismatch: {requirement}, installed {version}"
            )
        if name in seen:
            continue
        seen.add(name)
        verified.append(f"{name}=={version}")
        for child in current_distribution.requires or ():
            parsed = Requirement(child)
            if parsed.marker and not parsed.marker.evaluate(marker_environment | {"extra": ""}):
                continue
            queue.append(parsed)
    return tuple(verified)


def _download(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--platform",
        "win_amd64",
        "--python-version",
        "311",
        "--implementation",
        "cp",
        "--abi",
        "cp311",
        "--abi",
        "abi3",
        "--dest",
        str(args.wheelhouse),
        "-r",
        str(args.requirements),
    ]
    if args.no_index:
        command.append("--no-index")
    if args.index_url:
        command.extend(("--index-url", args.index_url))
    for location in args.find_links:
        command.extend(("--find-links", location))
    args.wheelhouse.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--wheelhouse", type=Path, required=True)
    download.add_argument(
        "--requirements",
        type=Path,
        default=Path("offline-requirements-win-x64-cp311.txt"),
    )
    download.add_argument("--index-url")
    download.add_argument("--find-links", action="append", default=[])
    download.add_argument("--no-index", action="store_true")

    expand = subparsers.add_parser("expand")
    expand.add_argument("--wheelhouse", type=Path, required=True)
    expand.add_argument("--output", type=Path, required=True)
    expand.add_argument("--licenses", type=Path)
    expand.add_argument("--inventory", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--vendor", type=Path, required=True)
    verify.add_argument(
        "--requirements",
        type=Path,
        default=Path("offline-requirements-win-x64-cp311.txt"),
    )
    return parser


def _read_requirements(path: Path) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "download":
        _download(args)
    elif args.command == "expand":
        licenses = args.licenses or args.output.with_name("third_party_licenses")
        records = expand_wheels(args.wheelhouse, args.output, licenses)
        write_inventory(records, args.inventory or args.output.with_name("inventory.json"))
    elif args.command == "verify":
        for item in verify_runtime_closure(args.vendor, _read_requirements(args.requirements)):
            print(item)
    else:  # pragma: no cover - argparse enforces the choices
        raise AssertionError(args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
