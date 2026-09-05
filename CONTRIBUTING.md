# Contributing

Issues and pull requests are welcome. Keep changes focused and include a small reproduction or regression test.

1. Fork the repository and create a branch.
2. Run the pure-Python tests, Ruff, and public-release audit listed in README.
3. For UI, network, context, or image changes, also run the native QGIS suites.
4. Use synthetic GIS data and fake router credentials in tests. Never commit real projects, screenshots of private work, chat history, authentication databases, API keys, or local account paths.
5. Update documentation when behavior or requirements change.

Preserve the main product boundaries: router-neutral models, explicit attachment consent, metadata-only automatic context, credentials in QGIS Authentication Manager, and no arbitrary model-generated code execution. A catalog entry does not prove that a router supports a given capability.

By contributing, you agree that your contributions are licensed under GPL-3.0-or-later, consistent with this project. Preserve third-party notices. No contributor license agreement is required.

## Releases

Update `PLUGIN_VERSION` and `metadata.txt` together. Run `scripts/build_plugin.py`; it creates a deterministic plugin ZIP and SHA-256 file under ignored `dist/`. Publish the ZIP as a GitHub prerelease while the plugin is experimental. Do not attach user data or a copy of a local QGIS profile.

