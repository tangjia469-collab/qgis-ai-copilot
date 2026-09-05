## Live Activity and Interruptible Requests

This release adds a Codex-like Activity panel for QGIS AI Copilot.

- Optional Responses API adapter with model-provided commentary and public reasoning summaries.
- Activity stays separate from the final answer and is expandable/collapsible.
- Raw chain-of-thought, encrypted reasoning, unknown event payloads, and tool arguments are ignored.
- Chat Completions remains the default compatibility adapter and shows honest transport milestones.
- A message-level Stop action cancels immediately, preserves partial output, and ignores late events.
- Chat idle timeout defaults to 10 minutes and resets on observed router activity; maximum request duration remains one hour.
- Images, screenshots, and selected PDF pages remain supported with explicit consent.
- Final assistant responses use a blue-tinted card; user messages are compact neutral cards.

Install the attached `qgis_ai_copilot-0.4.0-alpha.zip` in QGIS via Plugins -> Manage and Install Plugins -> Install from ZIP.

This is an experimental GitHub release, not an official QGIS Plugin Repository submission. Router/model support for Responses and summaries varies; the plugin never silently falls back or claims progress it did not observe.

SHA-256: `dc8a8913d9e917e3f5f1d3f6b630b8bc281fce563b54469acb29195273cd33ac`
