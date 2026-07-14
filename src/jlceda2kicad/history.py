"""Recent import history with bounded atomic persistence."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._json_store import preserve_broken, write_json_atomic


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    lcsc_id: str
    timestamp: datetime
    project: str
    symbol: str
    footprint: str
    result: str


class HistoryStore:
    def __init__(self, path: Path, limit: int = 10) -> None:
        self.path = path
        self.limit = limit

    def load(self) -> list[HistoryEntry]:
        if not self.path.is_file():
            return []
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("history root must be a list")
            entries = [
                HistoryEntry(
                    lcsc_id=item["lcsc_id"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    project=item["project"],
                    symbol=item["symbol"],
                    footprint=item["footprint"],
                    result=item["result"],
                )
                for item in raw
            ]
            return sorted(entries, key=lambda entry: entry.timestamp, reverse=True)[: self.limit]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            preserve_broken(self.path)
            return []

    def add(self, entry: HistoryEntry) -> None:
        entries = [entry, *self.load()]
        entries.sort(key=lambda item: item.timestamp, reverse=True)
        serialized: list[dict[str, Any]] = []
        for item in entries[: self.limit]:
            data = asdict(item)
            timestamp = item.timestamp
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            data["timestamp"] = timestamp.isoformat()
            serialized.append(data)
        write_json_atomic(self.path, serialized)
