import os
import time
from pathlib import Path

from jlceda2kicad.logging_config import redact_text
from jlceda2kicad.temp_manager import TemporaryWorkspaceManager


def test_redact_text_hides_proxy_credentials_and_api_tokens() -> None:
    text = (
        "HTTPS_PROXY=http://alice:secret@example.com:8080 "
        "KICAD_API_TOKEN=super-secret --lcsc_id=C2040"
    )

    redacted = redact_text(text)

    assert "alice" not in redacted
    assert "secret" not in redacted
    assert "super-secret" not in redacted
    assert "example.com:8080" in redacted
    assert "C2040" in redacted


def test_temporary_workspace_cleanup_removes_only_expired_directories(tmp_path: Path) -> None:
    manager = TemporaryWorkspaceManager(tmp_path, expiry_hours=24)
    old = tmp_path / "old"
    recent = tmp_path / "recent"
    old.mkdir()
    recent.mkdir()
    old_time = time.time() - 25 * 60 * 60
    os.utime(old, (old_time, old_time))

    removed = manager.cleanup_expired()

    assert removed == (old,)
    assert not old.exists()
    assert recent.exists()


def test_temporary_workspace_create_uses_unique_directory(tmp_path: Path) -> None:
    manager = TemporaryWorkspaceManager(tmp_path)

    first = manager.create("preview")
    second = manager.create("preview")

    assert first != second
    assert first.is_dir() and second.is_dir()
