from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1 = "https://hkrpt.github.io/JLCEDA2KICAD/v1/repository.json"
V2 = "https://hkrpt.github.io/JLCEDA2KICAD/v2/repository.json"
RELEASES = "https://github.com/HKRPT/JLCEDA2KICAD/releases"


def test_public_install_links_match_in_all_user_docs() -> None:
    for path in (
        ROOT / "README.md",
        ROOT / "README_zh-CN.md",
        ROOT / "resources/pages/index.html",
    ):
        text = path.read_text(encoding="utf-8")
        assert V1 in text
        assert V2 in text
        assert RELEASES in text


def test_user_docs_explain_file_install_and_plugin_launch() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README_zh-CN.md").read_text(encoding="utf-8")

    assert "Install from File" in english
    assert "Tools → External Plugins" in english
    assert "从文件安装" in chinese
    assert "工具 → 外部插件" in chinese
    assert "plugins/vendor" in english
    assert "plugins/vendor" in chinese


def test_initial_release_and_schema_attribution_are_documented() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "## [0.1.0] - 2026-07-15" in changelog
    assert "GitHub Release" in changelog
    assert "PCM schemas" in notices
