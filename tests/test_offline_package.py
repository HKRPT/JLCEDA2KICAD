import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_package import build_package

ROOT = Path(__file__).resolve().parents[1]


def _runtime(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, bytes]]:
    vendor = tmp_path / "vendor"
    licenses = tmp_path / "licenses"
    vendor.mkdir()
    licenses.mkdir()
    payloads = {
        "demo/__init__.py": b"VALUE = 1\r\n",
        "demo/native.pyd": b"MZ\x00\r\n\xff\x10",
        "demo/runtime.dll": b"DLL\r\n\x00\xfe",
        "demo/data.bin": b"arbitrary\r\nbinary\x00",
        "demo-1.0.dist-info/METADATA": b"Name: demo\r\nVersion: 1.0\r\n",
    }
    for name, data in payloads.items():
        destination = vendor / Path(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    license_file = licenses / "demo" / "LICENSE"
    license_file.parent.mkdir(parents=True)
    license_file.write_bytes(b"license\r\ntext")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps([{"name": "demo", "version": "1.0"}]) + "\n",
        encoding="utf-8",
    )
    return vendor, licenses, inventory, payloads


def test_pcm_requirements_contains_no_installable_requirement() -> None:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert not [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_offline_package_includes_vendor_and_licenses_without_byte_changes(
    tmp_path: Path,
) -> None:
    vendor, licenses, inventory, payloads = _runtime(tmp_path)

    result = build_package(
        tmp_path / "dist",
        vendor_dir=vendor,
        licenses_dir=licenses,
        inventory_file=inventory,
    )

    with zipfile.ZipFile(result.archive) as archive:
        for name, data in payloads.items():
            assert archive.read(f"plugins/vendor/{name}") == data
        assert archive.read("plugins/third_party_licenses/demo/LICENSE") == b"license\r\ntext"
        assert json.loads(
            archive.read("plugins/third_party_licenses/inventory.json")
        ) == [{"name": "demo", "version": "1.0"}]


def test_offline_package_is_deterministic(tmp_path: Path) -> None:
    vendor, licenses, inventory, _payloads = _runtime(tmp_path)

    first = build_package(
        tmp_path / "first",
        vendor_dir=vendor,
        licenses_dir=licenses,
        inventory_file=inventory,
    )
    second = build_package(
        tmp_path / "second",
        vendor_dir=vendor,
        licenses_dir=licenses,
        inventory_file=inventory,
    )

    assert hashlib.sha256(first.archive.read_bytes()).digest() == hashlib.sha256(
        second.archive.read_bytes()
    ).digest()
    assert first.manifest_file.read_bytes() == second.manifest_file.read_bytes()


def test_offline_package_requires_complete_runtime_inputs(tmp_path: Path) -> None:
    vendor, licenses, inventory, _payloads = _runtime(tmp_path)

    with pytest.raises(FileNotFoundError, match="vendor directory"):
        build_package(
            tmp_path / "dist-a",
            vendor_dir=tmp_path / "missing",
            licenses_dir=licenses,
            inventory_file=inventory,
        )
    with pytest.raises(FileNotFoundError, match="license directory"):
        build_package(
            tmp_path / "dist-b",
            vendor_dir=vendor,
            licenses_dir=tmp_path / "missing",
            inventory_file=inventory,
        )
    with pytest.raises(FileNotFoundError, match="inventory file"):
        build_package(
            tmp_path / "dist-c",
            vendor_dir=vendor,
            licenses_dir=licenses,
            inventory_file=tmp_path / "missing.json",
        )


def test_offline_package_rejects_vendor_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vendor, licenses, inventory, _payloads = _runtime(tmp_path)
    original = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        return path.name == "data.bin" or original(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(ValueError, match="symlink"):
        build_package(
            tmp_path / "dist",
            vendor_dir=vendor,
            licenses_dir=licenses,
            inventory_file=inventory,
        )
