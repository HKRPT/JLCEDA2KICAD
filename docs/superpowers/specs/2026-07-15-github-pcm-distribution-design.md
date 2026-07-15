# JLCEDA2KICAD GitHub PCM Distribution Design

## Summary

JLCEDA2KICAD will use GitHub as its public distribution channel instead of
building a Windows installer. Every published version will have one validated
KiCad PCM ZIP in GitHub Releases. The same ZIP will be available through a
static GitHub Pages repository with separate v1 and v2 metadata endpoints for
KiCad 9 and KiCad 10.

The design preserves the existing package layout, bootstrap environment, and
Windows-only platform declaration. It adds release automation, deterministic
repository generation, a bilingual Pages landing page, and installation
documentation. It does not submit the package to KiCad's official repository.

## Goals

- Let users install a release ZIP with KiCad's `Install from File` action.
- Let KiCad 9 users install and update from a v1 custom repository URL.
- Let KiCad 10 users install and update from a v2 custom repository URL.
- Publish both repository variants from static GitHub Pages without an
  external server or personal access token.
- Make release artifacts immutable by rejecting a same-version asset with a
  different hash.
- Preserve all valid public release versions in repository metadata.
- Prevent failed or partial builds from replacing the last valid Pages
  repository.
- Document how to locate and launch the installed plugin in the PCB editor.

## Non-goals

- Building an EXE, MSI, Inno Setup, NSIS, or other native installer.
- Hosting a dynamic service that negotiates schema versions from HTTP headers.
- Submitting to the official KiCad addon repository.
- Supporting macOS or declaring Linux GUI support in version 0.1.0.
- Bundling the Python dependencies into the PCM ZIP instead of using the
  existing first-run bootstrap.
- Publishing ordinary branch builds, pull-request artifacts, drafts, or
  untagged development versions to the public repository.

## Public endpoints and package topology

The public site is rooted at:

```text
https://hkrpt.github.io/JLCEDA2KICAD/
```

It exposes these installation endpoints:

```text
KiCad 9:  https://hkrpt.github.io/JLCEDA2KICAD/v1/repository.json
KiCad 10: https://hkrpt.github.io/JLCEDA2KICAD/v2/repository.json
```

The deployed Pages artifact has this logical layout:

```text
/
|- index.html
|- resources.zip
|- v1/
|  |- repository.json
|  `- packages.json
`- v2/
   |- repository.json
   `- packages.json
```

Both package lists point to the same immutable release asset, for example:

```text
https://github.com/HKRPT/JLCEDA2KICAD/releases/download/v0.1.0/
JLCEDA2KICAD-0.1.0.zip
```

GitHub Pages is static and cannot inspect the KiCad 10 media-type `Accept`
header. Separate endpoints therefore provide unambiguous v1 and v2 responses
without adding a server. The landing page gives users the correct URL for each
KiCad version and links to the GitHub Releases fallback.

## Metadata model

The `metadata.json` inside the installable ZIP remains v1 metadata so one
archive can be validated and installed by both KiCad 9 and KiCad 10. It
contains exactly the packaged version and never contains `download_url`,
`download_sha256`, `download_size`, or `install_size`.

The generated repository metadata uses the same package identity and static
descriptive fields as the archive metadata:

- identifier: `io.hkrpt.jlc`;
- type: `plugin`;
- platform: `windows`;
- runtime: `ipc`;
- minimum KiCad version: `9.0.1`; and
- license: `MIT`.

Repository `packages.json` may contain multiple versions. Each published
version adds:

- an immutable GitHub Release download URL;
- the lowercase SHA-256 of the actual ZIP bytes;
- compressed download size in bytes;
- uncompressed install size in bytes; and
- a release status derived from its tag.

The v1 package list conforms to the KiCad v1 Packages schema. The v2 list is a
v2 representation of the same v1-compatible plugin and conforms to the KiCad
v2 Packages schema. The v2 repository descriptor includes `schema_version: 2`;
the v1 descriptor does not.

Each `repository.json` records the URL, lowercase SHA-256, UTC update time, and
Unix update timestamp for its adjacent `packages.json` and the common
`resources.zip`. The resource archive contains the package-manager icon at
`io.hkrpt.jlc/icon.png`, matching the package-identifier directory layout used
by KiCad's repository builder. All URLs in deployed metadata are absolute HTTPS
URLs.

## Version and release policy

Only tags matching the supported SemVer release forms trigger publication:

```text
vMAJOR.MINOR.PATCH
vMAJOR.MINOR.PATCH-rc.NUMBER
```

The tag without the leading `v` must match the single project version source
and the sole version in the archive metadata. A final tag is `stable`; an RC
tag is `testing`. The source metadata must have the corresponding status before
the tag is accepted. The tagged commit must be reachable from `main`.

The initial public version is `v0.1.0`. Future releases use the same asset name
pattern, with the package version substituted. Draft releases and releases
whose tags do not follow the supported tag policy are excluded. Once a public
release has an eligible tag, missing or malformed expected assets are an error
rather than a reason to hide that version.

The repository generator rebuilds version history from GitHub Releases rather
than depending on the previous Pages deployment. For every eligible non-draft
release it:

1. selects the one expected PCM ZIP asset;
2. downloads its ZIP, checksum sidecar, and file manifest;
3. calculates the hash and sizes and verifies the checksum sidecar;
4. extracts and validates its archive metadata;
5. verifies tag, version, identifier, type, platform, runtime, status, and
   archive manifest; and
6. adds the version to both compatible package lists.

Any eligible historical release that is malformed, ambiguous, or mutable makes
generation fail visibly. Versions are sorted newest first using parsed version
semantics, not lexical string order.

## Release and deployment workflow

A version tag starts a release workflow with the following dependency order:

1. Run Ruff, mypy, and pytest/coverage on Windows and Ubuntu with Qt offscreen.
2. Build the deterministic PCM ZIP on Windows.
3. Validate the archive with `python -m kipy.packaging validate`.
4. Check the tag, project version, archive metadata, manifest, SHA-256, and
   tagged commit ancestry.
5. Create or safely reuse the GitHub Release and upload the ZIP, checksum, and
   file manifest.
6. Query all eligible GitHub Releases and construct a complete temporary Pages
   tree.
7. Validate both repository descriptors, both package lists, every referenced
   hash and size, the resource archive, and every public download URL.
8. Upload one Pages artifact and deploy it atomically.

Normal push and pull-request CI continues to test and build artifacts for
inspection but never creates a Release or deploys Pages. The release workflow
may reuse the same scripts as CI, while publication remains a separate job with
explicit tag conditions.

The workflow uses the repository-provided `GITHUB_TOKEN`. Ordinary CI has only
`contents: read`. Release publication receives only `contents: write`. Pages
deployment receives only `pages: write` and `id-token: write`. No personal
token, cloud account, dynamic service, or manually maintained `gh-pages`
branch is required.

## Idempotency and failure handling

Every public artifact is content-addressed before it can be referenced. A
workflow rerun may reuse an existing release asset only when its SHA-256 equals
the freshly built archive. If the same tag or asset name already exists with
different bytes, the workflow fails and never overwrites it.

Failure behavior is stage-specific:

- Test, build, package validation, or version validation failure creates no
  Release and does not update Pages.
- Release upload success followed by repository generation or Pages deployment
  failure leaves the manual Release installation available and leaves the
  previous Pages deployment active.
- Failure to generate either v1 or v2 output prevents deployment of both.
- A missing asset, duplicate expected asset, invalid historical archive,
  mismatched identifier, incorrect checksum, unreachable download, or malformed
  JSON fails publication instead of silently dropping a version.
- GitHub Pages deployment uses one complete artifact, so users never observe a
  new `repository.json` paired with an old `packages.json`.

Generated timestamps come from the release being published or another stable
workflow input. ZIP and JSON serialization are deterministic for identical
inputs so local tests can assert exact hashes and reruns do not produce
unexplained changes.

## User experience and documentation

The bilingual README and Pages landing page present two installation paths.

For repository installation, users open KiCad's Plugin and Content Manager,
open repository management, add the version-specific URL, refresh, search for
`JLCEDA2KICAD Importer`, and install it. KiCad 9 users copy the v1 URL and
KiCad 10 users copy the v2 URL.

For manual installation, users download the PCM ZIP from a GitHub Release and
choose `Install from File`. They do not extract the ZIP.

After installation, users open a PCB in the PCB Editor and launch
`JLCEDA2KICAD Importer` from `Tools -> External Plugins`. The documentation
states that the first launch creates the existing isolated Python environment
and downloads its pinned dependencies, so internet access and a short wait are
expected. Troubleshooting covers repository refresh, first-run dependency
errors, removal of an older development install, and where to find plugin logs.

The release page includes concise installation links and notes generated from
the changelog. The Pages home page links to the source repository, current
Release, checksum, license, issue tracker, and both repository endpoints.

## Components and boundaries

Repository generation is a pure Python service separate from GitHub Actions
orchestration. It accepts validated release records, archive bytes, an icon,
the Pages base URL, and an output directory. It produces deterministic v1/v2
JSON and `resources.zip` without publishing anything.

A GitHub release adapter owns API enumeration and asset download. It converts
API responses into the generator's release records but does not construct PCM
JSON. A release-policy unit validates tags, statuses, asset names, project
versions, and main-branch ancestry. Existing package-building code remains the
single owner of the installable archive layout.

The workflow only sequences these units, assigns least privilege, passes
immutable artifacts between jobs, and invokes GitHub Release and Pages
publication. This separation keeps repository logic locally testable without
network access or GitHub credentials.

## Testing

Ordinary tests remain offline. New unit and integration coverage includes:

- valid v1 and v2 repository descriptors and package lists;
- omission of `schema_version` in v1 and its required value in v2;
- repository-only download fields and archive metadata without them;
- exact SHA-256, download size, and install size calculation;
- deterministic JSON and resource ZIP output;
- stable and RC tag parsing, status mapping, and version mismatch rejection;
- semantic version ordering across multiple releases;
- draft, malformed, missing, duplicate, and mismatched release assets;
- same-version same-hash reuse and different-hash rejection;
- Unicode descriptive metadata and safe URL serialization;
- all-or-nothing construction of the two Pages variants; and
- regression tests for the existing package builder and bootstrap contents.

CI validates the package ZIP with `kipy.packaging`, validates generated JSON
against pinned KiCad v1 and v2 schemas, checks every local reference and hash,
and performs a local static-HTTP repository smoke test. Network-dependent
GitHub API tests use recorded fixtures or mocks in ordinary CI.

Final live acceptance uses disposable KiCad 9 and KiCad 10 configurations. For
each version it adds the matching Pages URL, refreshes the repository, finds
and installs the plugin, launches it from the PCB Editor, verifies uninstall
behavior, and records the result. Update behavior is covered with a local
two-version repository fixture for the first public release and becomes a live
acceptance requirement when a second public version exists. A separate test
downloads the Release ZIP and installs it with `Install from File`. These tests
do not modify the user's production plugin configuration or real project
libraries.

## Delivery and operational notes

GitHub Pages must use `GitHub Actions` as its source. The first implementation
will configure this through the repository settings or GitHub API when the
authenticated account permits it; otherwise the remaining one-time setting is
reported explicitly rather than claiming the repository is live.

Generated `dist` files and Pages artifacts are not committed to `main`. Source
scripts, workflow definitions, tests, pinned schema inputs, README changes, and
release documentation are committed. The first publication is complete only
after the real Pages URLs and GitHub Release asset are reachable and the two
isolated KiCad smoke tests have evidence.

## References

- [KiCad Addons developer documentation](https://dev-docs.kicad.org/en/addons/)
- [KiCad v1 PCM schema](https://go.kicad.org/pcm/schemas/v1)
- [KiCad v2 PCM schema](https://go.kicad.org/pcm/schemas/v2)
- [Official KiCad addon repository](https://gitlab.com/kicad/addons/repository)
- [Official KiCad addon metadata repository](https://gitlab.com/kicad/addons/metadata)
