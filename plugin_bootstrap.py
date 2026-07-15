"""Make PCM-bundled Python dependencies available to this process and its children."""

import os
import sys
from pathlib import Path


def bootstrap_vendor(plugin_root: Path | None = None) -> Path:
    """Prepend the plugin's bundled dependency directory to Python search paths."""

    root = (plugin_root or Path(__file__).resolve().parent).resolve()
    vendor = (root / "vendor").resolve()
    if not vendor.is_dir():
        raise RuntimeError(f"bundled dependency directory is missing: {vendor}")

    vendor_text = str(vendor)
    sys.path[:] = [vendor_text, *(entry for entry in sys.path if entry != vendor_text)]

    inherited = os.environ.get("PYTHONPATH", "")
    entries = [entry for entry in inherited.split(os.pathsep) if entry and entry != vendor_text]
    os.environ["PYTHONPATH"] = os.pathsep.join((vendor_text, *entries))
    return vendor
