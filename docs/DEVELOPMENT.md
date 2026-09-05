# Development and testing

The Python package is imported by QGIS through `classFactory`. The protocol and storage layers also run without QGIS for fast unit testing.

## Test layers

- `python3 -m unittest discover -s tests`: pure protocol/storage/attachment helpers.
- `python3 scripts/check_public_release.py`: repository privacy checks.
- `python3 scripts/build_plugin.py`: deterministic, source-only plugin ZIP.
- `python3 scripts/run_qgis_tests.py`: eight native suites using the current interpreter's QGIS installation, including network, lifecycle, attachments, image compression, composer layout, request progress, Responses activity, and message footers/question editing.

The native suites generate polygon/point layers, image pixels, and PDF pages. They never require a real project, router endpoint, or credential. Set `QT_QPA_PLATFORM=offscreen` for headless execution. `QGIS_PREFIX_PATH` is respected; otherwise normal installation defaults are used, with a standard macOS bundle fallback.

## macOS QGIS bundle

Some QGIS macOS packages contain a Python 3.12 launcher with resources in a directory named `python3.11`. For that bundle layout:

```sh
QGIS_TEST_LIBS="/Applications/QGIS.app/Contents/Resources/python3.11:/Applications/QGIS.app/Contents/Resources/python3.11/lib-dynload:/Applications/QGIS.app/Contents/Resources/python3.11/site-packages"
PYTHONPATH="$PWD:$QGIS_TEST_LIBS" \
PROJ_DATA=/Applications/QGIS.app/Contents/Resources/qgis/proj \
GDAL_DATA=/Applications/QGIS.app/Contents/Resources/qgis/gdal \
QT_QPA_PLATFORM=offscreen \
/Applications/QGIS.app/Contents/MacOS/python3.12 scripts/run_qgis_tests.py
```

Adjust paths for your QGIS distribution. A plain Python virtual environment does not contain PyQGIS. Poppler must be installed for PDF tests. Qt offscreen/platform/font messages can occur; suite assertions and exit codes determine failure.

## Local install

Build the plugin ZIP and use QGIS's **Install from ZIP**. For development, copy `qgis_ai_copilot/` into the active profile's `python/plugins/` directory, which can be located from **Settings → User Profiles → Open Active Profile Folder**. Do not copy a whole QGIS profile or store API keys in this repository. Unload the plugin before replacing files, and save temporary layers before restarting QGIS.

## Continuous integration

CI runs pure tests/lint/packaging on standard Python and native suites in a digest-pinned official QGIS 3.44.6 Linux container. The workflow uses read-only repository permissions and no router secrets. Screenshots produced by tests go to ignored `artifacts/`; only manually reviewed synthetic examples belong in documentation.

Floating-window decorations differ by platform. Layout tests retain child-control bounds and exact requested sizing where supported, allowing only the toolkit's bounded minimum-size expansion for a narrow floating dock.
