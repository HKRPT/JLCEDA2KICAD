"""Application settings stored outside KiCad project files."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ._json_store import preserve_broken, write_json_atomic


@dataclass(frozen=True, slots=True)
class AppSettings:
    cache_dir: Path | None = None
    log_dir: Path | None = None
    use_cache: bool = True
    import_symbol: bool = True
    import_footprint: bool = True
    import_step: bool = True
    import_wrl: bool = True
    open_library_dir: bool = True
    backup_count: int = 5
    timeout_seconds: int = 120
    recent_project: Path | None = None
    window_geometry: str = ""


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, settings: AppSettings) -> None:
        data = asdict(settings)
        data["cache_dir"] = str(settings.cache_dir) if settings.cache_dir else None
        data["log_dir"] = str(settings.log_dir) if settings.log_dir else None
        data["recent_project"] = str(settings.recent_project) if settings.recent_project else None
        write_json_atomic(self.path, data)

    def load(self) -> AppSettings:
        if not self.path.is_file():
            return AppSettings()
        try:
            data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings root must be an object")
            for key in ("cache_dir", "log_dir", "recent_project"):
                if data.get(key):
                    data[key] = Path(data[key])
            allowed = AppSettings.__dataclass_fields__.keys()
            return AppSettings(**{key: value for key, value in data.items() if key in allowed})
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            preserve_broken(self.path)
            return AppSettings()
