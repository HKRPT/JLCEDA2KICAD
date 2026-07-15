# GitHub PCM Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one validated JLCEDA2KICAD PCM ZIP through GitHub Releases and expose version-specific KiCad 9/v1 and KiCad 10/v2 custom repository URLs through GitHub Pages.

**Architecture:** Keep the existing deterministic package builder as the only producer of installable ZIPs. Add pure, offline-testable release-policy, GitHub API, and PCM repository-generation modules under `scripts`; a tag-only GitHub Actions workflow composes them with least privilege, creates immutable Release assets, and atomically deploys one Pages artifact containing both schema variants.

**Tech Stack:** Python 3.11, standard-library `urllib`, `zipfile`, `hashlib`, `json`, `kicad-python==0.7.1` bundled PCM schemas, `jsonschema`, pytest, Ruff, mypy, GitHub Actions, GitHub Releases REST API, and GitHub Pages.

## Global Constraints

- Preserve Python `>=3.11,<3.12` and the pinned runtime dependencies `easyeda2kicad==1.0.1`, `kicad-python==0.7.1`, and `PySide6==6.11.1`.
- Preserve package identifier `io.hkrpt.jlc`, package type `plugin`, runtime `ipc`, minimum KiCad `9.0.1`, platform `windows`, and license `MIT`.
- Use one installable PCM ZIP for KiCad 9 and 10; archive `metadata.json` remains v1 and contains no `download_*` fields.
- Publish `https://hkrpt.github.io/JLCEDA2KICAD/v1/repository.json` for KiCad 9 and `https://hkrpt.github.io/JLCEDA2KICAD/v2/repository.json` for KiCad 10.
- Do not build an EXE/MSI, submit to KiCad's official repository, commit generated `dist`/Pages artifacts, or add a dynamic server.
- Ordinary tests are offline. Only a tag publication job and explicit live acceptance may access GitHub or the deployed Pages site.
- KiCad package tags are numeric `vMAJOR.MINOR.PATCH`; metadata status is `stable` or `testing`, and a `testing` package becomes a GitHub prerelease. KiCad schemas do not permit prerelease suffixes in package versions.
- Never overwrite a same-version public asset whose bytes differ. A partial v1/v2 site must never be deployed.
- Every implementation task follows red-green-refactor, ends with its focused tests passing, and makes one Conventional Commit.

## File Structure

- Modify `metadata.json`: mark the first public version stable and keep archive-only metadata free of download fields.
- Modify `scripts/build_package.py`: derive all package names from `jlceda2kicad.version.__version__`.
- Modify `scripts/render_icons.py`: make the existing icon renderer pass strict mypy when scripts enter type checking.
- Create `scripts/release_policy.py`: parse release tags, validate source metadata, inspect ZIP/checksum/manifest triples, and produce typed published-version records.
- Create `scripts/check_release.py`: tag/main-ancestry preflight CLI with subprocess argument lists and no shell.
- Create `scripts/pcm_repository.py`: deterministic v1/v2 JSON, `resources.zip`, schema validation, and all-or-nothing site construction.
- Create `scripts/github_releases.py`: a small injected-transport GitHub REST adapter for listing, downloading, creating, updating, and uploading Release assets.
- Create `scripts/publish_release.py`: idempotently create a draft Release, upload or compare three assets, and publish it only when complete.
- Create `scripts/build_repository_site.py`: build Pages from public GitHub Releases or a local release triple for offline smoke tests.
- Create `resources/pages/index.html`: bilingual static landing page and installation links.
- Create `tests/test_release_policy.py`, `tests/test_pcm_repository.py`, `tests/test_github_releases.py`, `tests/test_distribution_cli.py`, `tests/test_distribution_docs.py`, and `tests/test_release_workflow.py`.
- Modify `.github/workflows/ci.yml`: type-check distribution scripts and exercise local repository generation without publishing.
- Create `.github/workflows/release.yml`: tag-only test, package, Release, repository-build, and Pages deployment jobs.
- Modify `README.md`, `README_zh-CN.md`, `docs/DEVELOPMENT.md`, `docs/MANUAL_TEST_CHECKLIST.md`, `CHANGELOG.md`, and `THIRD_PARTY_NOTICES.md`.
- Create `docs/releases/0.1.0-release-checklist.md`: retain preflight and live-publication evidence without committing binary artifacts.

---

### Task 1: Make package version and release metadata authoritative

**Files:**
- Modify: `metadata.json`
- Modify: `scripts/build_package.py`
- Modify: `scripts/render_icons.py`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `jlceda2kicad.version.__version__: str` from `src/jlceda2kicad/version.py`.
- Produces: `scripts.build_package.VERSION`, `ARCHIVE_NAME`, and `BuildResult` whose names always match the application and metadata version.

- [ ] **Step 1: Write failing version and archive-metadata tests**

Add these tests to `tests/test_packaging.py`:

```python
import json

from jlceda2kicad.version import __version__
from scripts.build_package import ARCHIVE_NAME, VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_package_version_has_one_stable_archive_metadata_entry() -> None:
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
    versions = metadata["versions"]

    assert VERSION == __version__ == "0.1.0"
    assert ARCHIVE_NAME == f"JLCEDA2KICAD-{__version__}.zip"
    assert len(versions) == 1
    assert versions[0]["version"] == __version__
    assert versions[0]["status"] == "stable"
    assert versions[0]["kicad_version"] == "9.0.1"
    assert versions[0]["platforms"] == ["windows"]
    assert versions[0]["runtime"] == "ipc"
    assert not any(key.startswith("download_") for key in versions[0])


def test_built_archive_contains_the_same_metadata_bytes(tmp_path: Path) -> None:
    result = build_package(tmp_path)

    with zipfile.ZipFile(result.archive) as archive:
        packaged = json.loads(archive.read("metadata.json"))
    source = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))

    assert packaged == source
```

- [ ] **Step 2: Run the focused tests and strict script type check to observe failure**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_packaging.py -v
./.venv/Scripts/python.exe -m mypy src scripts
```

Expected: the metadata status assertion fails with `development`, and mypy reports the `QImage.save` string-format overload error.

- [ ] **Step 3: Remove the duplicated build version and finalize metadata**

Change the top of `scripts/build_package.py` to:

```python
from jlceda2kicad.version import __version__

ROOT = Path(__file__).resolve().parents[1]
VERSION = __version__
ARCHIVE_NAME = f"JLCEDA2KICAD-{VERSION}.zip"
```

Change the only `metadata.json` version status to:

```json
"status": "stable"
```

Change the icon save call in `scripts/render_icons.py` to use the typed byte format:

```python
if not image.save(str(output), b"PNG"):
    raise RuntimeError(f"failed to save icon: {output}")
```

- [ ] **Step 4: Verify package tests, type checking, and PCM validation pass**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_packaging.py tests/test_plugin_installation.py -v
./.venv/Scripts/python.exe -m mypy src scripts
./.venv/Scripts/python.exe scripts/build_package.py
./.venv/Scripts/python.exe -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
```

Expected: all tests pass, mypy reports `Success`, and the package validator reports no errors.

- [ ] **Step 5: Commit the authoritative release metadata**

```powershell
git add metadata.json scripts/build_package.py scripts/render_icons.py tests/test_packaging.py
git commit -m "build: align package release metadata"
```

### Task 2: Implement release-tag policy and archive inspection

**Files:**
- Create: `scripts/release_policy.py`
- Create: `scripts/check_release.py`
- Create: `tests/test_release_policy.py`

**Interfaces:**
- Consumes: a tag name, project version, source metadata, main-ancestry result, and the three Release asset byte sequences.
- Produces: `ReleaseTag`, `SourceRelease`, `ReleasePayload`, and `PublishedVersion`; `parse_release_tag(tag_name: str) -> ReleaseTag`; `validate_source_release(tag_name: str, project_version: str, metadata: Mapping[str, object], is_main_ancestor: bool) -> SourceRelease`; `inspect_release(payload: ReleasePayload) -> PublishedVersion`.

- [ ] **Step 1: Write tag-policy tests**

Create `tests/test_release_policy.py` with these cases:

```python
import json
from pathlib import Path

import pytest

from scripts.release_policy import (
    DistributionError,
    parse_release_tag,
    validate_source_release,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("tag", "version", "sort_key"),
    [
        ("v0.1.0", "0.1.0", (0, 1, 0)),
        ("v10.20.300", "10.20.300", (10, 20, 300)),
    ],
)
def test_parse_supported_release_tags(
    tag: str, version: str, sort_key: tuple[int, int, int]
) -> None:
    parsed = parse_release_tag(tag)

    assert (parsed.version, parsed.sort_key) == (version, sort_key)


@pytest.mark.parametrize(
    "tag", ["0.1.0", "v1", "v1.2", "v1.2.3-beta", "v1.2.3-rc.1"]
)
def test_reject_unsupported_release_tags(tag: str) -> None:
    with pytest.raises(DistributionError, match="Unsupported release tag"):
        parse_release_tag(tag)


def test_validate_source_release_requires_version_status_and_main() -> None:
    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))

    validated = validate_source_release("v0.1.0", "0.1.0", metadata, True)
    assert (validated.status, validated.prerelease) == ("stable", False)
    metadata["versions"][0]["status"] = "testing"
    testing = validate_source_release("v0.1.0", "0.1.0", metadata, True)
    assert (testing.status, testing.prerelease) == ("testing", True)
    with pytest.raises(DistributionError, match="project version"):
        validate_source_release("v0.1.0", "0.1.1", metadata, True)
    with pytest.raises(DistributionError, match="reachable from main"):
        validate_source_release("v0.1.0", "0.1.0", metadata, False)
```

- [ ] **Step 2: Write archive/checksum/manifest inspection tests**

Use the real builder and a small payload helper in the same test file:

```python
from datetime import UTC, datetime

from scripts.build_package import build_package
from scripts.release_policy import ReleasePayload, inspect_release


def _payload(tmp_path: Path) -> ReleasePayload:
    result = build_package(tmp_path)
    return ReleasePayload(
        tag_name="v0.1.0",
        draft=False,
        prerelease=False,
        published_at=datetime(2026, 7, 15, 8, 0, tzinfo=UTC),
        archive_name=result.archive.name,
        archive_url=(
            "https://github.com/HKRPT/JLCEDA2KICAD/releases/download/"
            "v0.1.0/JLCEDA2KICAD-0.1.0.zip"
        ),
        archive=result.archive.read_bytes(),
        checksum=result.sha256_file.read_bytes(),
        manifest=result.manifest_file.read_bytes(),
    )


def test_inspect_release_calculates_repository_fields(tmp_path: Path) -> None:
    published = inspect_release(_payload(tmp_path))

    assert published.version == "0.1.0"
    assert published.status == "stable"
    assert published.sha256 == hashlib.sha256(published.archive).hexdigest()
    assert published.download_size == len(published.archive)
    with zipfile.ZipFile(io.BytesIO(published.archive)) as archive:
        expected_install_size = sum(member.file_size for member in archive.infolist())
    assert published.install_size == expected_install_size
    assert published.download_url.endswith("/JLCEDA2KICAD-0.1.0.zip")


@pytest.mark.parametrize("field", ["checksum", "manifest", "archive"])
def test_inspect_release_rejects_mutated_assets(tmp_path: Path, field: str) -> None:
    payload = _payload(tmp_path)
    broken = replace(payload, **{field: getattr(payload, field) + b"changed"})

    with pytest.raises(DistributionError):
        inspect_release(broken)
```

Also add explicit tests for a draft, mismatched GitHub prerelease flag, wrong identifier, two metadata versions, a `download_sha256` inside the archive, a duplicate manifest line, unsupported prerelease-suffixed versions, and semantic ordering `0.2.0 > 0.1.10 > 0.1.9`.

- [ ] **Step 3: Run the new tests to verify the module is missing**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_release_policy.py -v
```

Expected: collection fails with `ModuleNotFoundError: scripts.release_policy`.

- [ ] **Step 4: Implement the typed release policy**

Create `scripts/release_policy.py` with these public types and validation order:

```python
Status = Literal["stable", "testing"]
_TAG = re.compile(r"^v(\d{1,4})\.(\d{1,4})\.(\d{1,6})$")
_DOWNLOAD_FIELDS = {"download_url", "download_sha256", "download_size", "install_size"}


class DistributionError(RuntimeError):
    """A release or repository input is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ReleaseTag:
    tag_name: str
    version: str
    sort_key: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SourceRelease:
    tag: ReleaseTag
    status: Status
    prerelease: bool


@dataclass(frozen=True, slots=True)
class ReleasePayload:
    tag_name: str
    draft: bool
    prerelease: bool
    published_at: datetime
    archive_name: str
    archive_url: str
    archive: bytes
    checksum: bytes
    manifest: bytes


@dataclass(frozen=True, slots=True)
class PublishedVersion:
    version: str
    status: Status
    kicad_version: str
    platforms: tuple[str, ...]
    runtime: str
    published_at: datetime
    download_url: str
    sha256: str
    download_size: int
    install_size: int
    archive: bytes = field(repr=False)


def parse_release_tag(tag_name: str) -> ReleaseTag:
    match = _TAG.fullmatch(tag_name)
    if match is None:
        raise DistributionError(f"Unsupported release tag: {tag_name}")
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    return ReleaseTag(tag_name, f"{major}.{minor}.{patch}", (major, minor, patch))
```

Implement `validate_source_release` to require one metadata version, exact tag/project/metadata version equality, status in `{"stable", "testing"}`, `io.hkrpt.jlc`, `plugin`, `windows`, `ipc`, `9.0.1`, no download fields, and `is_main_ancestor=True`. Return `SourceRelease(tag, status, status == "testing")`.

Implement `inspect_release` in this exact sequence: reject drafts; derive the expected three names from the tag; verify the lowercase checksum sidecar line; open the ZIP; reject duplicate/unsafe member names; compare the sorted manifest exactly with members; parse `metadata.json`; call `validate_source_release(..., True)`; require `payload.prerelease == source_release.prerelease`; sum `ZipInfo.file_size` for install size; return `PublishedVersion`. Wrap invalid ZIP/UTF-8/JSON errors as `DistributionError` without including archive bytes or credentials.

- [ ] **Step 5: Add the no-shell tag preflight CLI**

Create `scripts/check_release.py` with a `main(argv: Sequence[str] | None = None) -> int` that accepts an optional `--tag` defaulting to `GITHUB_REF_NAME` and a `--github-output` flag:

```python
parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"))
parser.add_argument("--github-output", action="store_true")
args = parser.parse_args(argv)
if not args.tag:
    raise DistributionError("A release tag is required")
tag = parse_release_tag(args.tag)
metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
ancestry = subprocess.run(
    ["git", "merge-base", "--is-ancestor", tag.tag_name, "origin/main"],
    cwd=ROOT,
    check=False,
    stdin=subprocess.DEVNULL,
)
validated = validate_source_release(tag.tag_name, __version__, metadata, ancestry.returncode == 0)
if args.github_output:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise DistributionError("GITHUB_OUTPUT is required with --github-output")
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"version={validated.tag.version}\n")
        output.write(f"prerelease={str(validated.prerelease).lower()}\n")
print(f"release preflight passed: {tag.tag_name}")
return 0
```

Catch `DistributionError` only at the command boundary, print one redacted error to stderr, and return 2. Add subprocess-mocked tests proving the command uses a list, rejects non-main tags, never sets `shell=True`, reads `GITHUB_REF_NAME`, and writes only validated numeric values to `GITHUB_OUTPUT`.

- [ ] **Step 6: Run focused quality checks**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_release_policy.py -v
./.venv/Scripts/python.exe -m ruff check scripts/release_policy.py scripts/check_release.py tests/test_release_policy.py
./.venv/Scripts/python.exe -m mypy scripts/release_policy.py scripts/check_release.py
```

Expected: all tests pass and both static checks are clean.

- [ ] **Step 7: Commit the release policy**

```powershell
git add scripts/release_policy.py scripts/check_release.py tests/test_release_policy.py
git commit -m "feat: validate PCM release inputs"
```

### Task 3: Generate and validate deterministic v1/v2 PCM repositories

**Files:**
- Create: `scripts/pcm_repository.py`
- Create: `tests/test_pcm_repository.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: source package metadata, `Sequence[PublishedVersion]`, icon bytes, complete landing-page bytes, a base URL, UTC update time, and a nonexistent output path. Task 3 tests pass fixture HTML directly; Task 5 adds the production HTML file.
- Produces: `SiteBuildResult`; `build_site(request: SiteBuildRequest) -> SiteBuildResult`; `validate_site(root: Path) -> None`; deterministic `v1/repository.json`, `v1/packages.json`, `v2/repository.json`, `v2/packages.json`, and `resources.zip`.

- [ ] **Step 1: Write repository shape and determinism tests**

Create `tests/test_pcm_repository.py` using `build_package` plus `inspect_release` to create a real `PublishedVersion`, then assert:

```python
def test_build_site_writes_both_schema_variants(tmp_path: Path) -> None:
    request = _site_request(tmp_path)
    result = build_site(request)

    v1_repository = json.loads((result.root / "v1/repository.json").read_text("utf-8"))
    v2_repository = json.loads((result.root / "v2/repository.json").read_text("utf-8"))
    v1_packages = json.loads((result.root / "v1/packages.json").read_text("utf-8"))
    v2_packages = json.loads((result.root / "v2/packages.json").read_text("utf-8"))

    assert "schema_version" not in v1_repository
    assert v2_repository["schema_version"] == 2
    assert v1_packages["packages"][0]["$schema"].endswith("/v1")
    assert v2_packages["packages"][0]["$schema"].endswith("/v2")
    assert v1_packages["packages"][0]["versions"] == v2_packages["packages"][0]["versions"]
    assert v1_repository["packages"]["url"].endswith("/v1/packages.json")
    assert v2_repository["packages"]["url"].endswith("/v2/packages.json")


def test_resources_zip_uses_identifier_icon_path(tmp_path: Path) -> None:
    result = build_site(_site_request(tmp_path))

    with zipfile.ZipFile(result.root / "resources.zip") as archive:
        assert archive.namelist() == ["io.hkrpt.jlc/icon.png"]
        assert archive.read("io.hkrpt.jlc/icon.png") == (ROOT / "resources/icon_64.png").read_bytes()


def test_site_is_deterministic_for_fixed_inputs(tmp_path: Path) -> None:
    first = build_site(_site_request(tmp_path / "one"))
    second = build_site(_site_request(tmp_path / "two"))

    assert _tree_hashes(first.root) == _tree_hashes(second.root)
```

Add tests for newest-first semantic ordering, exact SHA-256 references, UTC timestamp formatting, lowercase hashes, absolute HTTPS production URLs, the explicitly allowed `http://127.0.0.1` local-smoke URL, rejection of all other HTTP URLs, duplicate versions, no releases, invalid icon bytes, existing output path, schema validation failure, and leaving no output directory when either schema variant fails.

- [ ] **Step 2: Run tests to verify the generator is missing**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_pcm_repository.py -v
```

Expected: collection fails with `ModuleNotFoundError: scripts.pcm_repository`.

- [ ] **Step 3: Implement deterministic repository serialization**

Create `scripts/pcm_repository.py` with these public request/result types:

```python
@dataclass(frozen=True, slots=True)
class SiteBuildRequest:
    source_metadata: Mapping[str, object]
    versions: Sequence[PublishedVersion]
    icon: bytes
    index_html: bytes
    base_url: str
    updated_at: datetime
    output: Path


@dataclass(frozen=True, slots=True)
class SiteBuildResult:
    root: Path
    v1_repository: Path
    v2_repository: Path
    resources: Path
```

Use `json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"`. Build the resource archive with one `ZipInfo("io.hkrpt.jlc/icon.png", (2020, 1, 1, 0, 0, 0))`, mode `0o100644`, deflate level 9, and the supplied 64px PNG.

Construct the version dictionaries only from `PublishedVersion` fields:

```python
{
    "version": item.version,
    "status": item.status,
    "kicad_version": item.kicad_version,
    "platforms": list(item.platforms),
    "runtime": item.runtime,
    "download_url": item.download_url,
    "download_sha256": item.sha256,
    "download_size": item.download_size,
    "install_size": item.install_size,
}
```

Deep-copy the descriptive source metadata, replace its versions, and switch `$schema` to v1 or v2. Build repository descriptors with `$schema` ending in `#/definitions/Repository`, name `JLCEDA2KICAD Addon Repository`, maintainer `HKRPT`, and package/resource hashes calculated after writing their files. Use `updated_at.astimezone(UTC)` for both timestamp fields.

- [ ] **Step 4: Validate against the schemas bundled by pinned kicad-python**

Load `pcm.v1.schema.json` and `pcm.v2.schema.json` using:

```python
from importlib.resources import files
from jsonschema import Draft7Validator


def _schema(name: str, definition: str) -> dict[str, object]:
    raw = files("kipy.packaging.schemas").joinpath(name).read_text(encoding="utf-8")
    schema = cast(dict[str, object], json.loads(raw))
    schema["$ref"] = f"#/definitions/{definition}"
    return schema
```

Validate each repository with definition `Repository` and each package list with `PackageArray`. Then verify every descriptor hash against the files on disk, every version download field has the expected type, and `resources.zip` has the one safe icon member. Raise `DistributionError` with the relative file and JSON path.

Build into `TemporaryDirectory(dir=request.output.parent)`, validate the complete tree, and rename it to `request.output` only after success. Reject an existing output path rather than deleting it.

- [ ] **Step 5: Add schema-validation typing support and run focused checks**

Because `jsonschema` is already required by pinned `kicad-python==0.7.1`, add a mypy override rather than another runtime dependency:

```toml
[[tool.mypy.overrides]]
module = "jsonschema.*"
ignore_missing_imports = true
```

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_pcm_repository.py -v
./.venv/Scripts/python.exe -m ruff check scripts/pcm_repository.py tests/test_pcm_repository.py
./.venv/Scripts/python.exe -m mypy scripts/pcm_repository.py
```

Expected: all checks pass, including both official schema validators.

- [ ] **Step 6: Commit the repository generator**

```powershell
git add pyproject.toml scripts/pcm_repository.py tests/test_pcm_repository.py
git commit -m "feat: generate dual PCM repositories"
```

### Task 4: Add an idempotent GitHub Release adapter and distribution CLIs

**Files:**
- Create: `scripts/github_releases.py`
- Create: `scripts/publish_release.py`
- Create: `scripts/build_repository_site.py`
- Create: `tests/test_github_releases.py`
- Create: `tests/test_distribution_cli.py`

**Interfaces:**
- Consumes: `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_REF_NAME`, three local package assets, GitHub REST release responses, and the pure policy/generator services.
- Produces: `GitHubClient`, `GitHubRelease`, `GitHubAsset`, `ensure_release_assets(client: GitHubClient, release: SourceRelease, assets: Mapping[str, Path], notes: str) -> GitHubRelease`, `load_public_release_payloads(...) -> tuple[ReleasePayload, ...]`, `publish_release.main(...)`, and `build_repository_site.main(...)`.

- [ ] **Step 1: Write injected-transport GitHub API tests**

Create `tests/test_github_releases.py` with a `FakeTransport` that records `HttpRequest` values and returns queued `HttpResponse` values. Cover:

```python
def test_list_releases_follows_link_pagination_without_leaking_token() -> None:
    transport = FakeTransport([...page_one_with_next, page_two])
    client = GitHubClient("owner/repo", "secret-token", transport)

    releases = client.list_releases()

    assert [release.tag_name for release in releases] == ["v0.2.0", "v0.1.0"]
    assert all(request.headers["Authorization"] == "Bearer secret-token"
               for request in transport.requests)
    assert "secret-token" not in repr(releases)


def test_ensure_release_reuses_identical_assets() -> None:
    client = _client_with_existing_release_and_asset_bytes(_expected_assets())

    release = ensure_release_assets(client, _stable_source_release(), _asset_paths(), "notes")

    assert release.draft is False
    assert not client.transport.upload_requests


def test_ensure_release_rejects_different_existing_bytes() -> None:
    client = _client_with_existing_release_and_asset_bytes({"archive": b"changed"})

    with pytest.raises(DistributionError, match="refusing to overwrite"):
        ensure_release_assets(client, _stable_source_release(), _asset_paths(), "notes")
```

Also cover draft creation, three missing uploads, publishing only after all uploads, numeric `testing` metadata producing a GitHub prerelease, duplicate matching tags, HTTP 403/404/500, malformed JSON, missing pagination URL, upload URL template stripping, correct content types, and exception text that contains neither token nor response authorization headers.

- [ ] **Step 2: Run the API tests to verify failure**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_github_releases.py -v
```

Expected: collection fails because `scripts.github_releases` does not exist.

- [ ] **Step 3: Implement the standard-library GitHub adapter**

Create these boundaries in `scripts/github_releases.py`:

```python
@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class GitHubAsset:
    asset_id: int
    name: str
    api_url: str
    browser_download_url: str
    size: int


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    release_id: int
    tag_name: str
    draft: bool
    prerelease: bool
    published_at: datetime | None
    upload_url: str
    assets: tuple[GitHubAsset, ...]
```

`UrllibTransport.send` uses `urllib.request.Request`, a 30-second timeout, and returns HTTP error bodies as ordinary `HttpResponse` values. `GitHubClient` always sends `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, and `Authorization: Bearer ...`; errors mention method, sanitized URL, and status only.

Implement paginated list, asset-byte download with `Accept: application/octet-stream`, draft creation with an explicit title and body, asset upload to the upload host, and release patch. Never put the token in a dataclass representation or command output.

- [ ] **Step 4: Implement immutable Release publication**

`ensure_release_assets` receives exactly these paths:

```python
expected = {
    f"JLCEDA2KICAD-{release.tag.version}.zip": (archive_path, "application/zip"),
    f"JLCEDA2KICAD-{release.tag.version}.zip.sha256": (checksum_path, "text/plain"),
    f"JLCEDA2KICAD-{release.tag.version}.zip.manifest.txt": (manifest_path, "text/plain"),
}
```

Find one release with `release.tag.tag_name` or create it as a draft titled `JLCEDA2KICAD VERSION` with the validated changelog notes. For every expected name, download an existing asset and compare bytes, upload only when missing, and raise before any overwrite when bytes differ. Re-list the release, require all three exact assets, then patch `draft=false` and `prerelease=release.prerelease`. Ignore unrelated assets but reject duplicate expected names.

- [ ] **Step 5: Write CLI tests and implement both entry points**

In `tests/test_distribution_cli.py`, monkeypatch clients and test:

```python
def test_publish_cli_requires_token_without_printing_it(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert publish_release.main(["--repository", "HKRPT/JLCEDA2KICAD",
                                 "--tag", "v0.1.0", "--dist", "dist"]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_local_site_cli_copies_archive_for_http_smoke(tmp_path: Path) -> None:
    result = build_package(tmp_path / "dist")
    output = tmp_path / "site"

    code = build_repository_site.main([
        "local", "--tag", "v0.1.0", "--archive", str(result.archive),
        "--checksum", str(result.sha256_file), "--manifest", str(result.manifest_file),
        "--download-url", f"http://127.0.0.1:8765/{result.archive.name}",
        "--base-url", "http://127.0.0.1:8765", "--output", str(output),
        "--published-at", "2026-07-15T08:00:00Z",
    ])

    assert code == 0
    assert (output / result.archive.name).read_bytes() == result.archive.read_bytes()
```

`scripts/publish_release.py` reads the repository from optional `--repository` or `GITHUB_REPOSITORY`, the tag from optional `--tag` or `GITHUB_REF_NAME`, and the token from `--token-env` defaulting to `GITHUB_TOKEN`. Before HTTP calls it loads source metadata and calls `validate_source_release`, extracts the exact `## [VERSION]` section from `CHANGELOG.md` as the Release body, checks the three paths in `--dist`, invokes `ensure_release_assets` with the returned `SourceRelease` and changelog body, and prints only tag, release ID, and public asset names. Tests require failure when the version section is missing or empty and require the created draft body to equal the extracted section.

`scripts/build_repository_site.py` provides two subcommands:

- `github --repository --base-url --output --token-env`: default the repository to `GITHUB_REPOSITORY`, enumerate all releases, skip drafts and unsupported tags, require every eligible public release to have exactly the expected three assets, download and inspect them, sort semantically, and call `build_site`.
- `local --tag --archive --checksum --manifest --download-url --base-url --output --published-at`: construct one `ReleasePayload`, call `build_site`, and copy the archive into the new site only after successful validation for local HTTP smoke tests.

Both commands load current descriptive metadata, `resources/icon_64.png`, and `resources/pages/index.html` from the repository root. Until Task 5 creates the page, tests supply a temporary HTML fixture through a monkeypatched `INDEX_HTML` path.

- [ ] **Step 6: Run API, CLI, style, and type tests**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_github_releases.py tests/test_distribution_cli.py -v
./.venv/Scripts/python.exe -m ruff check scripts/github_releases.py scripts/publish_release.py scripts/build_repository_site.py tests/test_github_releases.py tests/test_distribution_cli.py
./.venv/Scripts/python.exe -m mypy scripts/github_releases.py scripts/publish_release.py scripts/build_repository_site.py
```

Expected: all commands pass with no network access.

- [ ] **Step 7: Commit the GitHub distribution adapter**

```powershell
git add scripts/github_releases.py scripts/publish_release.py scripts/build_repository_site.py tests/test_github_releases.py tests/test_distribution_cli.py
git commit -m "feat: automate immutable GitHub releases"
```

### Task 5: Add the Pages landing page and public installation documentation

**Files:**
- Create: `resources/pages/index.html`
- Create: `tests/test_distribution_docs.py`
- Modify: `README.md`
- Modify: `README_zh-CN.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/MANUAL_TEST_CHECKLIST.md`
- Modify: `CHANGELOG.md`
- Modify: `THIRD_PARTY_NOTICES.md`

**Interfaces:**
- Consumes: the two fixed Pages repository URLs and GitHub Releases URL.
- Produces: a self-contained static landing page and matching English/Chinese install, launch, update, uninstall, first-run, and troubleshooting instructions.

- [ ] **Step 1: Write documentation-link tests**

Create `tests/test_distribution_docs.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1 = "https://hkrpt.github.io/JLCEDA2KICAD/v1/repository.json"
V2 = "https://hkrpt.github.io/JLCEDA2KICAD/v2/repository.json"
RELEASES = "https://github.com/HKRPT/JLCEDA2KICAD/releases"


def test_public_install_links_match_in_all_user_docs() -> None:
    for path in (ROOT / "README.md", ROOT / "README_zh-CN.md",
                 ROOT / "resources/pages/index.html"):
        text = path.read_text(encoding="utf-8")
        assert V1 in text
        assert V2 in text
        assert RELEASES in text


def test_user_docs_explain_where_to_launch_the_plugin() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README_zh-CN.md").read_text(encoding="utf-8")

    assert "Tools → External Plugins" in english
    assert "工具 → 外部插件" in chinese
    assert "Install from File" in english
    assert "从文件安装" in chinese
```

- [ ] **Step 2: Run the tests and verify missing public instructions**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_distribution_docs.py -v
```

Expected: failure because the landing page does not exist and the README files lack the Pages URLs.

- [ ] **Step 3: Create a self-contained bilingual landing page**

Create `resources/pages/index.html` with UTF-8, responsive viewport, accessible headings, inline CSS only, and these visible blocks:

```html
<main>
  <h1>JLCEDA2KICAD Importer</h1>
  <p>Install and update the Windows IPC plugin from a custom KiCad repository.</p>
  <h2>KiCad 10 / 推荐</h2>
  <code>https://hkrpt.github.io/JLCEDA2KICAD/v2/repository.json</code>
  <h2>KiCad 9</h2>
  <code>https://hkrpt.github.io/JLCEDA2KICAD/v1/repository.json</code>
  <ol>
    <li>Open Plugin and Content Manager / 打开扩展内容管理器。</li>
    <li>Open Manage, add the matching URL, save, and refresh / 管理仓库、添加地址、保存并刷新。</li>
    <li>Search for JLCEDA2KICAD Importer and install / 搜索并安装插件。</li>
    <li>Open a board, then Tools → External Plugins / 打开 PCB 后选择工具 → 外部插件。</li>
  </ol>
  <p><a href="https://github.com/HKRPT/JLCEDA2KICAD/releases">GitHub Releases / 从文件安装</a></p>
  <p><a href="https://github.com/HKRPT/JLCEDA2KICAD">Source</a> ·
     <a href="https://github.com/HKRPT/JLCEDA2KICAD/issues">Issues</a> · MIT</p>
</main>
```

Keep the page code-native and do not add generated images, JavaScript, analytics, remote fonts, cookies, or third-party assets.

- [ ] **Step 4: Add public install and troubleshooting sections to both READMEs**

Before the development-install sections, document:

- exact v1/v2 copyable repository URLs;
- Project Manager → Plugin and Content Manager → Manage → add repository → refresh → search/install;
- Release ZIP → `Install from File` without extracting;
- PCB Editor → `Tools → External Plugins → JLCEDA2KICAD Importer`;
- first launch creates the KiCad-managed isolated Python environment and downloads pinned dependencies;
- Windows support, internet/proxy requirements, restart/refresh guidance, logs, update, and uninstall; and
- removal of an older development copy when it conflicts with the PCM-installed identifier.

Use native Chinese UI labels in `README_zh-CN.md` and equivalent English labels in `README.md`.

- [ ] **Step 5: Document maintainer and manual-test workflows**

Add to `docs/DEVELOPMENT.md`:

```powershell
./.venv/Scripts/python.exe -m mypy src scripts
./.venv/Scripts/python.exe scripts/check_release.py --tag v0.1.0
./.venv/Scripts/python.exe scripts/build_repository_site.py local `
  --tag v0.1.0 `
  --archive dist/JLCEDA2KICAD-0.1.0.zip `
  --checksum dist/JLCEDA2KICAD-0.1.0.zip.sha256 `
  --manifest dist/JLCEDA2KICAD-0.1.0.zip.manifest.txt `
  --download-url http://127.0.0.1:8765/JLCEDA2KICAD-0.1.0.zip `
  --base-url http://127.0.0.1:8765 `
  --published-at 2026-07-15T08:00:00Z `
  --output .smoke/pcm-site
```

Add repository install, Release file install, launch, update-fixture, uninstall, isolated `KICAD_CONFIG_HOME`/`KICAD_DOCUMENTS_HOME`, URL/hash, and evidence checkboxes to `docs/MANUAL_TEST_CHECKLIST.md`.

Move the already-implemented global-library entries from `Unreleased` into the initial `0.1.0` section, set its publication date to `2026-07-15`, and add GitHub Release/Pages distribution under `0.1.0`. Keep an empty `Unreleased` heading for future changes. Add an attribution in `THIRD_PARTY_NOTICES.md` noting that repository validation uses the PCM schemas bundled with `kicad-python==0.7.1` under that package's licensing terms.

- [ ] **Step 6: Run documentation and local-site tests**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_distribution_docs.py tests/test_distribution_cli.py tests/test_pcm_repository.py -v
./.venv/Scripts/python.exe -m ruff check tests/test_distribution_docs.py
```

Expected: all tests pass and the local site contains both endpoints and the packaged icon.

- [ ] **Step 7: Commit public installation documentation**

```powershell
git add resources/pages/index.html tests/test_distribution_docs.py README.md README_zh-CN.md docs/DEVELOPMENT.md docs/MANUAL_TEST_CHECKLIST.md CHANGELOG.md THIRD_PARTY_NOTICES.md
git commit -m "docs: add GitHub PCM installation guide"
```

### Task 6: Add tag-only Release and Pages workflows

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `tests/test_release_workflow.py`

**Interfaces:**
- Consumes: a validated `v*` tag on `main`, the repository `GITHUB_TOKEN`, package artifacts, and all distribution CLIs.
- Produces: one public GitHub Release and one complete GitHub Pages deployment; no publication on ordinary push or pull request.

- [ ] **Step 1: Write workflow-policy tests before YAML**

Create `tests/test_release_workflow.py`:

```python
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


def test_normal_ci_never_runs_publication_commands() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "publish_release.py" not in workflow
    assert "deploy-pages" not in workflow
    assert "python -m mypy src scripts" in workflow
```

- [ ] **Step 2: Run the test and verify release.yml is missing**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_release_workflow.py -v
```

Expected: failure reading `.github/workflows/release.yml`.

- [ ] **Step 3: Extend ordinary CI without adding publication authority**

In `.github/workflows/ci.yml`, keep `permissions: contents: read`, change both type-check invocations to:

```yaml
- run: python -m mypy src scripts
```

After package validation, add a local-site build with a fixed timestamp and localhost URLs, then upload `_site` as an ordinary artifact. Do not call Release or Pages actions from this workflow.

- [ ] **Step 4: Create the tag-only release workflow**

Create `.github/workflows/release.yml` with this job graph and exact permission boundaries:

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  preflight:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.release.outputs.version }}
      prerelease: ${{ steps.release.outputs.prerelease }}
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: git fetch origin main:refs/remotes/origin/main
      - name: Validate release tag and metadata
        id: release
        run: python scripts/check_release.py --github-output

  test:
    needs: preflight
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    env:
      QT_QPA_PLATFORM: offscreen
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - name: Install Qt runtime libraries
        if: runner.os == 'Linux'
        run: |
          sudo apt-get update
          sudo apt-get install --yes libegl1
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e ".[dev]"
      - run: python -m ruff check .
      - run: python -m mypy src scripts
      - run: python -m pytest --cov=jlceda2kicad --cov-report=term-missing --cov-report=xml

  package:
    needs: [preflight, test]
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e ".[dev]"
      - run: python scripts/build_package.py
      - run: python -m kipy.packaging validate dist/JLCEDA2KICAD-${{ needs.preflight.outputs.version }}.zip
      - uses: actions/upload-artifact@v4
        with:
          name: pcm-release-assets
          path: dist/JLCEDA2KICAD-${{ needs.preflight.outputs.version }}.zip*

  publish-release:
    needs: [preflight, package]
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - uses: actions/download-artifact@v4
        with:
          name: pcm-release-assets
          path: dist
      - run: python -m pip install -e ".[dev]"
      - run: python scripts/publish_release.py --dist dist
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  build-pages:
    needs: publish-release
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: read
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: python scripts/build_repository_site.py github --base-url "https://hkrpt.github.io/JLCEDA2KICAD" --output _site
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v4
        with:
          path: _site

  deploy-pages:
    needs: build-pages
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

The broad `v*` GitHub glob is intentional because Actions tag filters are globs, not regular expressions. `check_release.py` is the strict numeric-version gate and stops unsupported tags before tests or publication. The workflow uses only its validated numeric `version` output in file paths; Python reads the raw ref and repository from GitHub's environment rather than interpolating them into shell commands.

- [ ] **Step 5: Run workflow and full offline checks**

Run:

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_release_workflow.py tests/test_distribution_cli.py tests/test_pcm_repository.py -v
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m mypy src scripts
```

Expected: all checks pass; text inspection confirms only the intended two jobs hold write permissions.

- [ ] **Step 6: Commit CI and publication workflows**

```powershell
git add .github/workflows/ci.yml .github/workflows/release.yml tests/test_release_workflow.py
git commit -m "ci: publish PCM releases and Pages repository"
```

### Task 7: Perform local release-candidate verification

**Files:**
- Create: `docs/releases/0.1.0-release-checklist.md`

**Interfaces:**
- Consumes: the complete release candidate and local KiCad package/site outputs.
- Produces: a clean, tag-ready `main` commit plus a text evidence record; no Release, tag, or Pages mutation yet.

- [ ] **Step 1: Run the complete offline quality gate from a clean build**

Run:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m mypy src scripts
./.venv/Scripts/python.exe -m pytest --cov=jlceda2kicad --cov-report=term-missing --cov-report=xml
$workspace = (Get-Location).Path
$dist = [System.IO.Path]::GetFullPath((Join-Path $workspace "dist"))
if (-not $dist.StartsWith($workspace + [System.IO.Path]::DirectorySeparatorChar)) { throw "Unsafe dist path" }
Remove-Item -LiteralPath $dist -Recurse -Force -ErrorAction SilentlyContinue
./.venv/Scripts/python.exe scripts/build_package.py
./.venv/Scripts/python.exe -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
./.venv/Scripts/python.exe scripts/check_release.py --tag v0.1.0
```

Expected: every command exits 0. Before the ancestry check, create the local tag temporarily only if necessary, run the check, then delete the local tag; never push it during this task.

- [ ] **Step 2: Build and serve a local two-schema PCM repository**

Run:

```powershell
$workspace = (Get-Location).Path
$site = [System.IO.Path]::GetFullPath((Join-Path $workspace ".smoke/pcm-site"))
if (-not $site.StartsWith($workspace + [System.IO.Path]::DirectorySeparatorChar)) { throw "Unsafe smoke path" }
Remove-Item -LiteralPath $site -Recurse -Force -ErrorAction SilentlyContinue
./.venv/Scripts/python.exe scripts/build_repository_site.py local `
  --tag v0.1.0 `
  --archive dist/JLCEDA2KICAD-0.1.0.zip `
  --checksum dist/JLCEDA2KICAD-0.1.0.zip.sha256 `
  --manifest dist/JLCEDA2KICAD-0.1.0.zip.manifest.txt `
  --download-url http://127.0.0.1:8765/JLCEDA2KICAD-0.1.0.zip `
  --base-url http://127.0.0.1:8765 `
  --published-at 2026-07-15T08:00:00Z `
  --output .smoke/pcm-site
Push-Location .smoke/pcm-site
../../.venv/Scripts/python.exe -m http.server 8765
```

In another PowerShell session, request `/v1/repository.json`, `/v2/repository.json`, both package lists, `resources.zip`, and the PCM ZIP. Expected: HTTP 200 for all; descriptor hashes match the downloaded files. Stop the server with Ctrl+C and `Pop-Location`.

- [ ] **Step 3: Record deterministic artifact evidence**

Run the package and local-site build a second time into new directories and compare:

```powershell
(Get-FileHash dist/JLCEDA2KICAD-0.1.0.zip -Algorithm SHA256).Hash.ToLower()
Get-ChildItem .smoke/pcm-site -Recurse -File | Sort-Object FullName |
  ForEach-Object { "$(($_.FullName).Substring((Resolve-Path .smoke/pcm-site).Path.Length + 1)) $((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())" }
```

Expected: the package and site hashes match the second build for fixed inputs.

- [ ] **Step 4: Create and fill the pre-publication evidence checklist**

Create `docs/releases/0.1.0-release-checklist.md` with:

- commit hash, Windows/Python versions, exact command exit status, pytest totals, and coverage;
- ZIP SHA-256, byte size, install size, manifest member count, and kipy result;
- v1/v2 local descriptor/package/resource hashes and local HTTP results;
- `git status --short --branch` and `git log --oneline --decorate -10`;
- unchecked sections for GitHub workflow run, Release URLs, Pages URLs, KiCad 9, KiCad 10, update-fixture, manual ZIP installation, and uninstall; and
- an explicit statement that unchecked live items are not yet passes.

Do not include tokens, proxy credentials, temporary absolute user paths, or generated binaries.

- [ ] **Step 5: Fix any discovered problem through a failing regression test**

For each failure, add the smallest failing test to its owning test file, verify the failure, fix the owning module, rerun its focused suite, and repeat the full Step 1 gate. Do not weaken schema, hash, or workflow assertions to make the gate pass.

- [ ] **Step 6: Commit release-candidate evidence**

```powershell
git add docs/releases/0.1.0-release-checklist.md
git commit -m "docs: record 0.1.0 release preflight"
git status --short --branch
```

Expected: the worktree is clean and `main` is ready to push and tag.

### Task 8: Publish and verify the real GitHub repository

**Files:**
- Modify: `docs/releases/0.1.0-release-checklist.md`

**Interfaces:**
- Consumes: the tag-ready main commit, GitHub repository administrator access, the tag workflow, installed KiCad 9.0.6 and 10.0.4, and isolated smoke directories.
- Produces: pushed `main`, immutable `v0.1.0`, public Release assets, live v1/v2 Pages endpoints, verified KiCad installations, and a final evidence commit.

- [ ] **Step 1: Push main and enable GitHub Actions as the Pages source**

Run:

```powershell
git push origin main
```

In `https://github.com/HKRPT/JLCEDA2KICAD/settings/pages`, set **Build and deployment → Source → GitHub Actions**. Confirm the `github-pages` environment exists or will be created by the first deployment. If repository/API permissions prevent enablement, stop and report that single external blocker; do not create a `gh-pages` branch as a workaround.

- [ ] **Step 2: Create and push the immutable initial tag**

Confirm `metadata.json`, `src/jlceda2kicad/version.py`, and `CHANGELOG.md` all say `0.1.0`, then run:

```powershell
git tag -a v0.1.0 -m "JLCEDA2KICAD 0.1.0"
git push origin v0.1.0
```

Expected: the Release workflow starts. Do not move or force-push this tag after publication.

- [ ] **Step 3: Monitor the workflow and verify public artifacts**

Record the Release workflow run URL and require every matrix, package, publish-release, build-pages, and deploy-pages job to pass. Then run:

```powershell
$base = "https://hkrpt.github.io/JLCEDA2KICAD"
$release = "https://github.com/HKRPT/JLCEDA2KICAD/releases/download/v0.1.0"
Invoke-WebRequest "$base/v1/repository.json" -OutFile .smoke/live-v1-repository.json
Invoke-WebRequest "$base/v2/repository.json" -OutFile .smoke/live-v2-repository.json
Invoke-WebRequest "$base/v1/packages.json" -OutFile .smoke/live-v1-packages.json
Invoke-WebRequest "$base/v2/packages.json" -OutFile .smoke/live-v2-packages.json
Invoke-WebRequest "$base/resources.zip" -OutFile .smoke/live-resources.zip
Invoke-WebRequest "$release/JLCEDA2KICAD-0.1.0.zip" -OutFile .smoke/live-package.zip
Invoke-WebRequest "$release/JLCEDA2KICAD-0.1.0.zip.sha256" -OutFile .smoke/live-package.zip.sha256
(Get-FileHash .smoke/live-package.zip -Algorithm SHA256).Hash.ToLower()
```

Expected: every request returns 200, the computed ZIP hash equals the sidecar and both package lists, each descriptor hash matches its downloaded package/resource file, v1 omits `schema_version`, and v2 contains `schema_version: 2`.

- [ ] **Step 4: Test KiCad 9 with isolated config and documents roots**

Completely exit KiCad, then launch KiCad 9 from a PowerShell process with:

```powershell
$env:KICAD_CONFIG_HOME = (New-Item -ItemType Directory -Force .smoke/pcm-kicad9/config).FullName
$env:KICAD_DOCUMENTS_HOME = (New-Item -ItemType Directory -Force .smoke/pcm-kicad9/documents).FullName
& "C:\Program Files\KiCad\9.0\bin\kicad.exe"
```

In the isolated Project Manager, add the v1 URL, refresh, search and install `JLCEDA2KICAD Importer`, open `.smoke/kicad9/smoke9.kicad_pro`, launch it from **Tools → External Plugins**, allow first-run dependency setup, open the window, close it, and uninstall through PCM. Confirm only the two isolated roots and disposable project changed.

- [ ] **Step 5: Test KiCad 10 repository and manual-file installation**

Completely exit KiCad, then launch KiCad 10 with:

```powershell
$env:KICAD_CONFIG_HOME = (New-Item -ItemType Directory -Force .smoke/pcm-kicad10/config).FullName
$env:KICAD_DOCUMENTS_HOME = (New-Item -ItemType Directory -Force .smoke/pcm-kicad10/documents).FullName
& "C:\Program Files\KiCad\10.0\bin\kicad.exe"
```

Add the v2 URL, refresh, install, open `.smoke/kicad10/smoke10.kicad_pro`, and launch from **Tools → External Plugins**. Confirm the PySide6 window identifies KiCad 10.0.4 and the disposable project. Uninstall, then use **Install from File** with `.smoke/live-package.zip`, relaunch the same action, and uninstall again.

- [ ] **Step 6: Exercise update semantics without inventing a second public version**

Run the automated local two-version fixture from `tests/test_pcm_repository.py` and the manual update-fixture checklist. Confirm KiCad recognizes the newer testing/stable ordering from a local disposable repository. Mark real public update as `not applicable until the second public version`, not as passed.

- [ ] **Step 7: Complete and commit the publication record**

Update `docs/releases/0.1.0-release-checklist.md` with the workflow run URL, Release asset URLs, Pages URLs, actual hashes, KiCad builds, isolated roots, screenshots or evidence paths, first-run result, install/launch/uninstall results, manual-file result, and every unverified item. Then run:

```powershell
git status --short --branch
git log --oneline --decorate -10
git add docs/releases/0.1.0-release-checklist.md
git commit -m "docs: record 0.1.0 publication"
git push origin main
```

Expected: `v0.1.0` remains on the immutable release commit, `main` contains the later evidence commit, and no `dist`, `.smoke`, cache, log, settings, or token files are tracked.

- [ ] **Step 8: Report delivery without overstating evidence**

The final report must list branch, Release URL, KiCad 9/v1 URL, KiCad 10/v2 URL, ZIP/SHA/manifest assets, workflow run, commit and tag hashes, local command results, KiCad 9 and 10 outcomes, manual-file outcome, push status, unverified items, and next improvements. Claim a check passed only when its command output or recorded manual evidence exists.
