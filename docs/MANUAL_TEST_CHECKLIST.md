# Manual test checklist — 0.1.0

Use disposable projects only. Run the full list separately in KiCad 9.0.6 and
10.0.4 on Windows.

- [ ] Install dependencies into the selected KiCad Python 3.11 runtime.
- [ ] Run `scripts/install_dev.ps1`; confirm only this plugin directory changes.
- [ ] Start PCB Editor and confirm the toolbar icon/action is visible.
- [ ] Launch the PySide6 window and confirm the IPC project path and KiCad version.
- [ ] Select a different disposable project manually, including a Chinese/space path.
- [ ] Query C2040; inspect streaming output and all available preview tabs.
- [ ] Cancel a running query; confirm the UI returns to idle without project writes.
- [ ] Import symbol, footprint, STEP, and WRL into an empty disposable project.
- [ ] Confirm `LCSC_Project` is registered once in both project library tables.
- [ ] Open the imported symbol and footprint in KiCad and verify pin/pad numbers.
- [ ] Open 3D Viewer and verify project-relative model references.
- [ ] Repeat import and exercise cancel, skip-existing, and overwrite-component.
- [ ] Disable WRL but keep STEP; verify the footprint references `.step`.
- [ ] Disable both model types; verify the staged footprint has no model node.
- [ ] Corrupt a disposable library table and confirm import refuses all changes.
- [ ] Simulate a locked target file and confirm backup/rollback reporting.
- [ ] Confirm proxy credentials and `KICAD_API_TOKEN` do not appear in logs.
- [ ] Confirm settings/history survive restart and malformed JSON is preserved/reset.
- [ ] Run `scripts/uninstall_dev.ps1`; confirm other plugins remain untouched.
- [ ] Optionally run uninstall with `-PurgeAppData` and confirm only this app's data is removed.

Record the exact KiCad build, Python version, command output, screenshots, and
any unchecked item in the release report. An unchecked item is not a pass.
