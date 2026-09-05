# Security and privacy

This project is experimental. Use a narrowly scoped router API key and review model answers before making GIS changes yourself.

## Reporting

Please do not put credentials, personal data, or exploitable security details in a public issue. Prefer GitHub's private vulnerability reporting if enabled on the repository. If it is unavailable, open a minimal issue asking for a private contact channel without disclosing the vulnerability or private data.

Reports should describe affected versions, expected versus actual behavior, and a synthetic reproduction. Do not include real QGIS project files, raw feature data, screenshots of accounts, local authentication databases, or access tokens.

## Boundaries

- Remote router traffic uses HTTPS; loopback HTTP is allowed for local development.
- Authentication is delegated to QGIS Authentication Manager. The plugin does not persist API keys in settings, project files, or chat exports.
- Automatic metadata trust is explicit and tied to router URL/authentication selection. Visual files always require separate per-request consent.
- Local chat history contains user-visible text and sanitized metadata. The plugin cannot guarantee that text typed by a user or returned by a provider contains no sensitive information.
- Attachment bytes remain in bounded process memory; only manifests are persisted. In-memory data is not encrypted, and process dumps may expose it.
- PDF rendering uses system Poppler with private temporary files and timeouts. Keep QGIS, Qt, and Poppler updated.
- Model-supplied links require confirmation; remote images in answers are not automatically loaded.
- Model-generated code is display-only. This alpha does not offer autonomous GIS writes or arbitrary Python execution.

The plugin does not control the router's logging, routing, billing, or retention. Deleting local history has no effect on provider-side copies.

