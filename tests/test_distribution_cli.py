import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_repository_site, publish_release
from scripts.build_package import build_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script",
    ["check_release.py", "publish_release.py", "build_repository_site.py"],
)
def test_distribution_scripts_support_direct_file_execution(script: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_publish_cli_requires_token_without_printing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert (
        publish_release.main(
            [
                "--repository",
                "HKRPT/JLCEDA2KICAD",
                "--tag",
                "v0.1.0",
                "--dist",
                "dist",
            ]
        )
        == 2
    )
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_local_site_cli_copies_archive_for_http_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = build_package(tmp_path / "dist")
    output = tmp_path / "site"
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>test</title>", encoding="utf-8")
    monkeypatch.setattr(build_repository_site, "INDEX_HTML", index)

    code = build_repository_site.main(
        [
            "local",
            "--tag",
            "v0.1.0",
            "--archive",
            str(result.archive),
            "--checksum",
            str(result.sha256_file),
            "--manifest",
            str(result.manifest_file),
            "--download-url",
            f"http://127.0.0.1:8765/{result.archive.name}",
            "--base-url",
            "http://127.0.0.1:8765",
            "--output",
            str(output),
            "--published-at",
            "2026-07-15T08:00:00Z",
        ]
    )

    assert code == 0
    assert (output / result.archive.name).read_bytes() == result.archive.read_bytes()


def test_publish_cli_uses_exact_changelog_section_as_draft_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    result = build_package(dist)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [0.1.0] - 2026-07-15\n\n- Exact notes.\n\n## [0.0.9]\n- Old.\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, repository: str, token: str) -> None:
            captured["client"] = (repository, token)

    def fake_ensure(client, release, assets, notes):
        captured["notes"] = notes
        captured["assets"] = assets
        return type("Release", (), {"release_id": 7, "tag_name": "v0.1.0", "assets": ()})()

    monkeypatch.setenv("TOKEN", "secret")
    monkeypatch.setattr(publish_release, "CHANGELOG", changelog)
    monkeypatch.setattr(publish_release, "GitHubClient", Client)
    monkeypatch.setattr(publish_release, "ensure_release_assets", fake_ensure)

    assert publish_release.main(
        [
            "--repository",
            "HKRPT/JLCEDA2KICAD",
            "--tag",
            "v0.1.0",
            "--dist",
            str(dist),
            "--token-env",
            "TOKEN",
        ]
    ) == 0
    assert captured["notes"] == "## [0.1.0] - 2026-07-15\n\n- Exact notes."
    assert set(captured["assets"]) == {
        result.archive.name,
        result.sha256_file.name,
        result.manifest_file.name,
    }


def test_publish_cli_rejects_missing_changelog_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    build_package(dist)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN", "secret")
    monkeypatch.setattr(publish_release, "CHANGELOG", changelog)

    assert publish_release.main(
        [
            "--repository",
            "HKRPT/JLCEDA2KICAD",
            "--tag",
            "v0.1.0",
            "--dist",
            str(dist),
            "--token-env",
            "TOKEN",
        ]
    ) == 2
