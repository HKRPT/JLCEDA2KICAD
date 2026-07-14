import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jlceda2kicad.history import HistoryEntry, HistoryStore
from jlceda2kicad.models import ImportScope
from jlceda2kicad.settings import AppSettings, SettingsStore


def test_settings_round_trip_preserves_unicode_paths(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "设置.json")
    settings = AppSettings(
        cache_dir=tmp_path / "缓存 目录",
        log_dir=tmp_path / "日志",
        backup_count=7,
        timeout_seconds=240,
        recent_project=tmp_path / "中文 项目.kicad_pro",
    )

    store.save(settings)

    assert store.load() == settings
    assert not tuple(tmp_path.glob("*.tmp"))


def test_corrupt_settings_are_preserved_and_defaults_are_returned(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    store = SettingsStore(path)

    settings = store.load()

    assert settings == AppSettings()
    assert not path.exists()
    assert len(tuple(tmp_path.glob("settings.json.broken-*"))) == 1


def test_settings_file_never_contains_proxy_credentials(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    SettingsStore(path).save(AppSettings())

    content = path.read_text(encoding="utf-8").casefold()
    assert "proxy" not in content
    assert "password" not in content


def test_settings_round_trip_preserves_global_library_choices(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    expected = AppSettings(
        last_import_scope=ImportScope.GLOBAL,
        last_symbol_library="Harulib",
        last_footprint_library="Harulib",
    )

    store.save(expected)

    assert store.load() == expected
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["last_import_scope"] == "global"


def test_history_store_keeps_newest_ten_entries(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json", limit=10)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(12):
        store.add(
            HistoryEntry(
                lcsc_id=f"C{index + 1}",
                timestamp=start + timedelta(minutes=index),
                project=f"project-{index}",
                symbol=f"symbol-{index}",
                footprint=f"footprint-{index}",
                result="success",
            )
        )

    loaded = store.load()

    assert len(loaded) == 10
    assert loaded[0].lcsc_id == "C12"
    assert loaded[-1].lcsc_id == "C3"


def test_history_corruption_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

    assert HistoryStore(path).load() == []
    assert len(tuple(tmp_path.glob("history.json.broken-*"))) == 1
