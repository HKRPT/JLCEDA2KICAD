# JLCEDA2KICAD 0.1.0 Implementation Plan

> **For agentic workers:** Execute inline with `superpowers:executing-plans` and
> use `superpowers:test-driven-development` for every behavior change.

**Goal:** Deliver a tested, installable KiCad IPC plugin that safely previews
and imports one LCSC component at a time.

**Architecture:** A pure Python core is wrapped by a PySide6 UI and `QProcess`
adapter. Formal imports are built and validated in a shadow project before an
atomic, backed-up commit to project-local libraries.

**Tech Stack:** Python 3.11, PySide6 6.11.1, kicad-python 0.7.1,
easyeda2kicad 1.0.1, pytest, Ruff, mypy, GitHub Actions.

## Execution Checklist

- [ ] Add failing tests for core models, validation, commands, discovery, and stores.
- [ ] Implement the minimal core and keep the suite green.
- [ ] Add failing tests for S-expressions, library tables, backups, and rollback.
- [ ] Implement transactional shadow-project import and post-import validation.
- [ ] Add failing parser tests, then implement footprint and WRL previews.
- [ ] Implement the PySide6 application, IPC entrypoint, and asynchronous workflow.
- [ ] Add packaging, installation, CI, bilingual documentation, and notices.
- [ ] Run offline checks, optional C2040 live conversion, package validation, and GUI smoke tests.
- [ ] Commit logical increments and push `codex/initial-kicad-plugin` without merging.
