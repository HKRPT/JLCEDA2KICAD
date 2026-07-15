from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_is_tag_only_and_uses_distribution_clis() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert '- "v*"' in workflow
    assert "scripts/check_release.py" in workflow
    assert "scripts/publish_release.py" in workflow
    assert "scripts/build_repository_site.py github" in workflow
    assert "branches:" not in workflow.split("jobs:", 1)[0]
    assert "-rc" not in workflow


def test_release_workflow_scopes_write_permissions_to_publish_jobs() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert workflow.count("contents: write") == 1
    assert workflow.count("pages: write") == 1
    assert workflow.count("id-token: write") == 1
    assert "environment:\n      name: github-pages" in workflow


def test_release_package_stages_and_verifies_offline_runtime() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "scripts/offline_vendor.py download" in workflow
    assert "scripts/offline_vendor.py expand" in workflow
    assert "scripts/offline_vendor.py verify" in workflow
    assert "python -m kipy.packaging validate" in workflow


def test_normal_ci_tests_scripts_and_never_publishes() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "publish_release.py" not in workflow
    assert "deploy-pages" not in workflow
    assert "python -m mypy src scripts" in workflow
    assert "scripts/build_repository_site.py local" in workflow
    assert "scripts/offline_vendor.py download" in workflow
