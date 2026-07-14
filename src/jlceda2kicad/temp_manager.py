"""Lifecycle management for preview and import workspaces."""

import shutil
import tempfile
import time
from pathlib import Path


class TemporaryWorkspaceManager:
    def __init__(self, root: Path, expiry_hours: int = 24) -> None:
        self.root = root
        self.expiry_seconds = expiry_hours * 60 * 60

    def create(self, prefix: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=self.root))

    def cleanup_expired(self) -> tuple[Path, ...]:
        if not self.root.is_dir():
            return ()
        cutoff = time.time() - self.expiry_seconds
        removed: list[Path] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
                removed.append(path)
        return tuple(removed)

    @staticmethod
    def remove(path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
