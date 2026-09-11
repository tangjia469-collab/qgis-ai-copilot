# Screenshot button implementation plan

**Goal:** Adjust the installed QGIS Copilot: click a small composer screenshot button, select an area, and attach it to the same draft without sending.

**Architecture:** Keep native area capture in `qgis_ai_copilot/screen_capture.py`, using asynchronous QProcess and the fixed macOS screencapture utility. Decode the private temporary PNG through the existing image preparation path, then remove the temporary file. Bind completion to the starting draft, project, router and edit context.

**Tech stack:** PyQGIS, PyQt5, macOS native area selection.

## Constraints

- Read-only Chat remains the installed default; preserve unfinished Execute source separately.
- Preserve typed text, existing attachments, image compression, consent, history and Copy behavior.
- Escape, timeout, project/chat switch, editing cancellation and plugin unload discard pending results.
- Do not monitor the clipboard, change screenshot defaults or send anything to the router automatically.
- Keep the screenshot icon beside the paperclip and model/thinking beside Send at 360/420/460 px.
- On non-macOS hosts keep existing paste/window/map capture available; disable the native area button.

## Execution

- [x] Add native tests for selected-image preparation, no-send draft behavior, private-file cleanup, Escape, repeated clicks, failed start, invalid PNG, timeout, stale results and narrow layouts.
- [x] Observe tests fail because the feature is absent, then implement the controller and composer button.
- [x] Fix narrow-layout sizing and test non-blocking cancellation with failing regressions.
- [x] Run all 13 native UI suites and 46 candidate pure tests; feature tests also pass in the main tree. Ruff and public-source audit pass.
- [x] Build UI-only 0.4.8-alpha; verify ZIP includes screen_capture.py and excludes Execute modules.
- [x] Back up, install and reload; verify the real button is visible/enabled and the loaded version is 0.4.8-alpha.

Live native-capture acceptance remains gated by macOS: CoreGraphics reports QGIS Screen Recording permission is false. The button starts the selector process, but no image is returned until the user grants that permission. No image was sent, no draft text was changed, and the QGIS project remains unmodified.

Native test entry: `python3 -m tests.qgis_area_capture` in QGIS's Python environment. Full UI entry: `python3 scripts/run_qgis_tests.py`. Both run against synthetic fixtures in separate processes from the user's QGIS instance.
