import csv
import hashlib
import json
import stat
import zipfile
from io import StringIO
from pathlib import Path

import pytest

from scripts.offline_vendor import (
    VendorError,
    expand_wheels,
    verify_runtime_closure,
    write_inventory,
)


def _wheel(
    directory: Path,
    name: str,
    version: str,
    *,
    tag: str = "py3-none-any",
    files: dict[str, bytes] | None = None,
    requires: tuple[str, ...] = (),
    license_expression: str = "MIT",
    include_license_file: bool = True,
) -> Path:
    normalized = name.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    members = dict(files or {f"{normalized}/__init__.py": b"VALUE = 1\r\n"})
    metadata = [
        "Metadata-Version: 2.4",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if license_expression:
        metadata.append(f"License-Expression: {license_expression}")
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requires)
    members[f"{dist_info}/METADATA"] = ("\n".join(metadata) + "\n").encode()
    members[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n" f"Tag: {tag}\n"
    ).encode()
    if include_license_file:
        members[f"{dist_info}/LICENSE"] = b"sample license\r\n"
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for member, data in sorted(members.items()):
        digest = hashlib.sha256(data).digest()
        import base64

        encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        writer.writerow((member, f"sha256={encoded}", str(len(data))))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    members[f"{dist_info}/RECORD"] = output.getvalue().encode()
    path = directory / f"{normalized}-{version}-{tag}.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return path


def _rewrite_member(wheel: Path, member: str, data: bytes) -> None:
    with zipfile.ZipFile(wheel) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members[member] = data
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _record_exception(wheel: Path, member: str) -> dict[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        record_name = next(name for name in archive.namelist() if name.endswith("/RECORD"))
        rows = {row[0]: row[1:] for row in csv.reader(archive.read(record_name).decode().splitlines())}
        data = archive.read(member)
    import base64

    actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return {
        "filename": wheel.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "member": member,
        "record_digest": rows[member][0],
        "record_size": rows[member][1],
        "actual_digest": f"sha256={actual}",
        "actual_size": str(len(data)),
        "reason": "audited synthetic upstream defect",
    }


def test_expand_wheels_maps_library_data_and_preserves_binary_bytes(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    binary = b"MZ\x00\r\n\xff\x10"
    _wheel(
        wheelhouse,
        "demo-pkg",
        "1.2.3",
        files={
            "demo_pkg/__init__.py": b"VALUE = 1\r\n",
            "demo_pkg-1.2.3.data/purelib/pure.py": b"PURE\r\n",
            "demo_pkg-1.2.3.data/platlib/native.pyd": binary,
        },
    )
    vendor = tmp_path / "vendor"
    licenses = tmp_path / "licenses"

    records = expand_wheels(wheelhouse, vendor, licenses)

    assert (vendor / "demo_pkg" / "__init__.py").read_bytes() == b"VALUE = 1\r\n"
    assert (vendor / "pure.py").read_bytes() == b"PURE\r\n"
    assert (vendor / "native.pyd").read_bytes() == binary
    assert (vendor / "demo_pkg-1.2.3.dist-info" / "METADATA").is_file()
    assert (licenses / "demo-pkg" / "LICENSE").read_bytes() == b"sample license\r\n"
    assert [(record.name, record.version) for record in records] == [("demo-pkg", "1.2.3")]


@pytest.mark.parametrize(
    "member",
    ["../escape.py", "/absolute.py", "nested\\escape.py", "demo.data/scripts/run.exe"],
)
def test_expand_wheels_rejects_unsafe_or_unsupported_members(
    tmp_path: Path, member: str
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "demo", "1.0", files={member: b"bad"})

    with pytest.raises(VendorError):
        expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")


def test_expand_wheels_rejects_symlink_member(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    wheel = _wheel(wheelhouse, "demo", "1.0")
    with zipfile.ZipFile(wheel, "a") as archive:
        info = zipfile.ZipInfo("demo/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")

    with pytest.raises(VendorError, match="symlink"):
        expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")


def test_expand_wheels_rejects_conflicting_duplicate_output(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "first", "1.0", files={"shared.py": b"first"})
    _wheel(wheelhouse, "second", "1.0", files={"shared.py": b"second"})

    with pytest.raises(VendorError, match="conflicting wheel members"):
        expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")


def test_expand_wheels_allows_byte_identical_duplicate_output(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "first", "1.0", files={"shared.py": b"same"})
    _wheel(wheelhouse, "second", "1.0", files={"shared.py": b"same"})

    records = expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")

    assert (tmp_path / "vendor" / "shared.py").read_bytes() == b"same"
    assert [record.name for record in records] == ["first", "second"]


def test_expand_wheels_rejects_incompatible_platform_tag(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "demo", "1.0", tag="cp311-cp311-manylinux_2_17_x86_64")

    with pytest.raises(VendorError, match="incompatible wheel tag"):
        expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")


def test_expand_wheels_rejects_distribution_without_license_evidence(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(
        wheelhouse,
        "demo",
        "1.0",
        license_expression="",
        include_license_file=False,
    )

    with pytest.raises(VendorError, match="no license evidence"):
        expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")


def test_expand_wheels_rejects_unlisted_record_hash_mismatch(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    wheel = _wheel(wheelhouse, "demo", "1.0")
    _rewrite_member(wheel, "demo/__init__.py", b"changed after RECORD")

    with pytest.raises(VendorError, match="RECORD hash mismatch"):
        expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")


def test_expand_wheels_accepts_only_exact_audited_record_exception(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    wheel = _wheel(wheelhouse, "demo", "1.0")
    member = "demo/__init__.py"
    _rewrite_member(wheel, member, b"known upstream content")
    exception_file = tmp_path / "exceptions.json"
    exception_file.write_text(
        json.dumps([_record_exception(wheel, member)]),
        encoding="utf-8",
    )

    records = expand_wheels(
        wheelhouse,
        tmp_path / "vendor",
        tmp_path / "licenses",
        record_exceptions=exception_file,
    )

    assert records[0].integrity_exceptions == (
        "demo-1.0-py3-none-any.whl:demo/__init__.py: audited synthetic upstream defect",
    )


def test_inventory_is_sorted_and_contains_hash_and_license(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "zeta", "2.0")
    _wheel(wheelhouse, "alpha", "1.0", requires=("zeta>=2",))
    records = expand_wheels(wheelhouse, tmp_path / "vendor", tmp_path / "licenses")
    inventory = tmp_path / "inventory.json"

    write_inventory(records, inventory)
    payload = json.loads(inventory.read_text(encoding="utf-8"))

    assert [item["name"] for item in payload] == ["alpha", "zeta"]
    assert payload[0]["requires_dist"] == ["zeta>=2"]
    assert payload[0]["license_expression"] == "MIT"
    assert len(payload[0]["sha256"]) == 64


def test_verify_runtime_closure_checks_recursive_requirements(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "demo", "1.0", requires=("dependency>=2",))
    _wheel(wheelhouse, "dependency", "2.1")
    vendor = tmp_path / "vendor"
    expand_wheels(wheelhouse, vendor, tmp_path / "licenses")

    verified = verify_runtime_closure(vendor, ("demo==1.0",))

    assert verified == ("demo==1.0", "dependency==2.1")


def test_verify_runtime_closure_reports_missing_dependency(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "demo", "1.0", requires=("missing>=1",))
    vendor = tmp_path / "vendor"
    expand_wheels(wheelhouse, vendor, tmp_path / "licenses")

    with pytest.raises(VendorError, match="missing runtime dependency"):
        verify_runtime_closure(vendor, ("demo==1.0",))
