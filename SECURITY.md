# Security and privacy

This project is experimental. Use a narrowly scoped router API key and review model answers before making GIS changes yourself.

## Reporting

Please do not put credentials, personal data, or exploitable security details in a public issue. Prefer GitHub's private vulnerability reporting if enabled on the repository. If it is unavailable, open a minimal issue asking for a private contact channel without disclosing the vulnerability or private data.

Reports should describe affected versions, expected versus actual behavior, and a synthetic reproduction. Do not include real QGIS project files, raw feature data, screenshots of accounts, local authentication databases, or access tokens.

## Boundaries

- Remote router traffic uses HTTPS; loopback HTTP is allowed for local development.
- Authentication is delegated to QGIS Authentication Manager. The plugin does not persist API keys in settings, project files, or chat exports.
- Automatic read access is enabled by default for all loaded layers. The agent can send bounded metadata, actual records, join information, statistics and geometry to the configured router without per-read prompts. This does not authorize project/layer edits. Disable **Allow read-only access to all loaded layers** in Settings for manual review.
- In optional review mode, actual data requires per-request layer/fields/row-scope/data-kind approval; metadata trust alone does not grant it. Selected feature IDs and layer state are checked. Metadata trust and separate visual-file consent remain router/authentication-bound; automatic read access itself is a persistent preference for the configured router, not a one-time trust record.
- Raw layer-tool payloads live only in active request memory, not automatic local tool records or chat history. User-visible answers may quote values and are retained as chat text. Credential/source fields are excluded and returned strings are bounded/redacted; use manual review mode when loaded layers contain data that should not be sent automatically to the configured provider.
- Local chat history contains user-visible text and sanitized metadata. The plugin cannot guarantee that text typed by a user or returned by a provider contains no sensitive information.
- Attachment bytes remain in bounded process memory; only manifests are persisted. In-memory data is not encrypted, and process dumps may expose it.
- PDF rendering uses system Poppler with private temporary files and timeouts. Keep QGIS, Qt, and Poppler updated.
- Model-supplied links require confirmation; remote images in answers are not automatically loaded.
- Model-generated code is display-only. Default Chat has no write tools. Opt-in Execute offers allowlisted actions with individual approval, not unattended GIS writes or arbitrary Python execution.
- EverOS is an optional separate opt-in. Only bounded scoped recall is exposed to the model; endpoints and user/scope IDs come from Settings, never tool arguments. Loopback-only URLs, no proxies/redirects/router credentials, response limits, strict returned scopes and cancellation protect the adapter boundary. Retrieved notes remain untrusted and may be stale.
- Saving an EverOS note requires a user-operated preview and Save, separate from GIS Execute. Only the supplied note is sent, with a unique operation ID; uncertain outcomes are not blindly retried. The service may use its configured extraction provider. Neither test fixtures nor connection checks write to the real memory library.

The plugin does not control the router's logging, routing, billing, or retention. Deleting local history has no effect on provider-side copies.
