# QGIS AI Copilot

A compact, native AI chat dock for QGIS. Bring your own OpenAI-compatible router, choose a model and thinking level, and discuss maps, screenshots, and PDF pages without leaving QGIS.

[![CI](https://github.com/tangjia469-collab/qgis-ai-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/tangjia469-collab/qgis-ai-copilot/actions/workflows/ci.yml)
[![License: GPL v3+](https://img.shields.io/badge/License-GPLv3%2B-blue.svg)](LICENSE)

**Experimental alpha · QGIS 3.44.x / Qt 5 · Python 3.10+**

This is an independent community project, not an official QGIS or OpenAI product. It uses your router's API, not a ChatGPT website login or subscription.

## What it does

- Loads the router's model catalogue and keeps model/thinking selection next to Send.
- Streams answers, stops generation, retries failed requests, and saves project-bound chat history.
- Keeps project/context status, removable context chips, local Checks, and Preview inside `Add context ▾`.
- Accepts images and PDFs through a file picker or drag-and-drop, pasted screenshots, QGIS-window capture, and delayed screen capture.
- Uses lossless screenshot compression first, then a bounded JPEG/resize fallback for large images.
- Renders explicitly selected PDF pages locally, so the model can see forms, tables, and page layout.
- Defaults to read-only Chat, with real attribute rows, joined values, statistics, join configuration and geometry inspection through a Responses-capable router. Optional **Execute** runs approved Processing, styling/view actions and recoverable memory-layer removal. No model-generated Python or source-file deletion.
- Optionally connects to local EverOS for relevant long-term memory recall and explicitly saved notes; it never imports the whole memory library or auto-saves chat.

![Native composer with compact context and model controls](docs/images/composer.png)

Screenshots in this repository use generated test data only.

## Install

1. Use the locally built **qgis_ai_copilot-0.7.0-alpha.zip** for optional EverOS memory, automatic read access, official-price estimates and Execute support, or a published plugin ZIP from the [Releases page](https://github.com/tangjia469-collab/qgis-ai-copilot/releases). Older releases may lack these features. This local candidate is not automatically published to GitHub.
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP and enable **QGIS AI Copilot**.
4. Open the **Assist** button in the QGIS Plugins toolbar, then open its settings, enter your router's Base URL, and configure authentication as described below.

For an existing installation, unload the plugin before upgrading. Save any temporary layers before restarting QGIS. This project is distributed through GitHub; it has not been submitted to the official QGIS Plugin Repository.

### Connect your router

- Base URL: an HTTPS endpoint such as `https://router.example/v1`.
- Supported API: `GET /v1/models`, `POST /v1/chat/completions`, and `POST /v1/responses`. Data inspection and Execute require Responses function calls.
- Authentication: select a QGIS Authentication Manager configuration. For bearer-key routers, create an **API Header** configuration with header `Authorization` and value `Bearer YOUR_API_KEY`. Set or unlock the QGIS authentication master password as prompted.
- Click **Test and load models**, then select a model from the switch immediately left of Send.
- `Thinking: Auto` omits `reasoning_effort`; explicit values come from router metadata or your local capability configuration. Models are never silently changed.
- Choose **Responses (live model activity)** in Settings when your router supports `/v1/responses`. Enable **Request model activity summaries** to see user-facing commentary and public reasoning summaries in the expandable Activity panel. Raw chain-of-thought is never requested or displayed; routers may provide no summary.

API usage is billed by your router/provider. No credentials are included in this repository. ChatGPT subscription access alone is not an API key.

### Live activity, long requests, and Stop

Each active answer shows real request status (**Sending request → Waiting for answer → Receiving answer**), elapsed time, and time since recent router activity. These are transport milestones, not a fabricated completion percentage or the model's private reasoning.

Responses mode adds an expandable **Activity** section above the final answer. It shows only router-provided commentary and public reasoning summaries, plus small local milestones such as context preparation. The final answer remains a separate blue card. The Activity panel is open while the response is running and collapses when it completes; updates are bounded and deduplicated. If the router sends no activity text, the panel says so.

The default **Chat idle timeout** is 600 seconds (Settings allows 30–3600 seconds). Receiving bytes or heartbeat events resets it, so an active stream is not cut off by the old 90-second total timer. A one-hour total cap and 32 MiB response cap still apply. Catalog timeout is separate. QGIS's reply-local timeout is aligned without changing the application's global network timeout.

### Live work plan

While an answer is running, Copilot shows a compact work plan instead of repeating every Activity label. It identifies the current step, completed steps, and the observed next state, with Stop visible in the plan header. Transport states such as sending, waiting, and receiving are shown when no public plan is available. Router commentary and public reasoning summaries become short Agent updates; private reasoning is never shown. Technical events remain under **Details**. After completion, the plan collapses to **Answer ready · N steps** and keeps Details available.

Copilot starts and reloads in **Chat**, the read-only mode. New/resumed chats and project changes reset to Chat. Select **Execute** in the header to request actual QGIS actions; every project change is shown for approval.

### Inspect actual layer data in Chat

With **Responses** selected in Settings, ask in normal Chat: “Inspect this layer's green_area values and join configuration.” The assistant can read actual rows (including joined columns), compute field statistics, inspect join keys and prefixes, and check geometry validity, bounds and planar measurements. No Execute switch is needed, and no write tools are exposed in Chat. Chat Completions remains chat/metadata-only.

**Reading is allowed by default.** Copilot can inspect any loaded layer's metadata, records, joined values, statistics and geometry as needed, sending the bounded results to your configured router without per-read approval popups. This continues across questions and new chats. It does not enable Execute or permit any project/layer changes.

For optional manual review, turn off **Settings → Allow read-only access to all loaded layers**. Then **Share layer data → Allow reading** names the layer, fields, row scope and data kind; approval applies only to that request and scope. Declining stops the task. In review mode, metadata trust alone does not approve raw data sharing. Saving settings stops an active tool session before applying the new preference. Screenshot/file consent remains separate.

Rows and geometry checks return up to 200 features per page. Statistics scan up to 10,000 rows or five seconds locally and return aggregates plus up to ten common actual values. Reads are time/output bounded and report partial coverage; large WKT shapes and expensive validity checks are explicitly omitted. Sensitive credential/source fields are excluded. Geometry area/length is planar in the stated CRS units, not an ellipsoidal measurement. The assistant must report what was actually inspected, not claim complete coverage from a sample.

### Make changes with Execute

Use a Responses-capable router/model, select **Execute**, then send a new instruction, for example “Remove the temporary layers.” Copilot inspects real layer IDs and shows the exact layer and feature count before removal. Approve the action to proceed, or Stop to leave it unchanged.

Supported tools include Buffer, Reproject, Clip, Intersection, Dissolve, Fix geometries, Centroids, Count points in polygon, uniform styling, visibility and zoom. Processing outputs are new memory layers; save them manually to persist. Filtered/joined or actively edited memory layers must be resolved before removal.

**Undo remove** restores removed memory layers. Private GeoPackage/style recovery copies are made in the QGIS profile before removal and are not sent to the router. The Chats menu also lists recoverable removals. Copies are retained separately from chat retention; no source files are deleted. For an unsaved project, use Undo before closing or reloading that project.

Execution stops if an approval record cannot be saved; an audit write failure after a supported action triggers rollback. Stop does not undo actions that already completed. Editing or retrying a question stays chat-only so it cannot repeat old changes.

Click **Stop** on the active message or the composer Stop icon to disconnect immediately; partial answer text is retained and late events are ignored. Upstream routers may have shorter timeouts or may continue computation/billing after a client disconnect. Retry is explicit, never automatic.

### Optional EverOS memory

In Settings, enable **Use local EverOS memory** and set its loopback URL (normally `http://127.0.0.1:8000`), EverOS user ID, app scope and memory scope. The default user ID comes from the local OS username; verify that it matches your EverOS identity. `default/default` searches the existing shared EverOS namespace; these fields are EverOS namespaces, not QGIS project or layer IDs. Use **Test local EverOS** to check connectivity. This add-on is off by default and changing the router/authentication disables recall until you explicitly enable it again.

With a Responses/function-capable model, questions about prior preferences or project decisions can invoke `search_memory`. Search needs no repeated approval popup once enabled. The model receives at most five short, filtered excerpts, not the entire library or profile. Activity reports the source count. Current layer data remains authoritative; memories can be old or irrelevant.

To save a note, choose **Add context → Memory → Remember a note…**, or type `/remember Your note` (`Remember this: …` and `记住：…` also work). Review the exact text and click **Save**. No chat history, attachments or GIS records are appended automatically. Saving does not require Execute or change any QGIS layer. Ordinary prompts and model responses never write to EverOS.

See [EverOS integration details](docs/EVEROS.md) for privacy, limits, interrupted saves and scope behavior.

### Compact messages and editing the latest question

The answer footer shows elapsed time and **Est. $… USD** instead of a token count. Estimates use verified, dated official OpenAI Standard API list prices, not the router's bill. Hover over the amount for its source and exclusions. Missing cache details produce a bounded range; unknown prices or incomplete usage show **Cost unavailable**. Multi-step answers price each model call separately. See [pricing methodology](docs/PRICING.md).

Assistant answers keep their model, thinking level, timestamp, and small two-page Copy icon in the footer. Long model labels are elided with full details on hover. User questions use compact neutral cards; **Show more** expands the full original text.

Click the **pencil icon on the latest question** to edit it in the composer, then Send to replace that question and its old answer. Nothing changes in history until validation and any send confirmation succeed. Cancel restores the draft that was in the composer before editing. Stop a running answer first. Retained files are reused; unavailable files must be re-attached or explicitly removed before resending. Local check results are preserved. A replaced answer's Retry button cannot revive the old prompt.

### Select a passage for a follow-up

Response text is selectable with the mouse and keyboard. Highlight a passage, right-click, and choose **Ask about selection** to quote it into the composer. Copilot preserves any draft you already typed and waits for you to add your question and press **Send**. The standard **Copy** command copies only the highlighted text; the footer Copy icon still copies the complete answer.

### Images, PDFs, and screen sharing

On macOS, click the **screenshot button beside the paperclip**, then drag to select an area. The screenshot appears as an attachment in your current draft; it is not sent until you press Send. Press Escape to cancel. Draft text stays intact. If macOS blocks capture, allow QGIS under Privacy & Security → Screen Recording. No clipboard monitoring or automatic screen sharing is enabled.

Area selection uses the Mac's native screenshot utility and a private temporary file which is removed after preparation. On other platforms, use clipboard paste or the existing map/window capture actions.

Use the attachment icon beside Add context. Capture the map canvas without QGIS chrome, capture the full QGIS window, or capture the screen after a short countdown. Click an attachment to preview the exact prepared image or selected PDF pages before sending.

- PNG, JPEG, WebP, and non-animated GIF inputs; PDFs are sent as rendered page images, not uploaded as original documents.
- Six files per message, 12 MiB per source file/prepared image, up to 20 images or PDF pages, and 24 MiB of encoded visual content per request.
- PDF page selection accepts `all`, `1-5`, or `1-3,8`. There is no silent page truncation or text-only fallback.
- PDF rendering requires **Poppler** (`pdfinfo` and `pdftoppm`) on PATH. Install it with `brew install poppler` on macOS or `sudo apt install poppler-utils` on Debian/Ubuntu. Windows needs a compatible Poppler installation on PATH.
- Screen capture may need OS permission. On macOS, grant QGIS Screen Recording permission, or use an OS screenshot and paste it into the composer. Capture is user-triggered, never continuous.
- Your selected router/model must accept Chat Completions image parts. Declared text-only models are blocked; unknown capabilities are tried only when you explicitly send an attachment, and provider errors remain visible. The first visual send to a router asks for consent; after you approve, Copilot remembers that approval for the same Base URL and Authentication configuration. Revoke it in Settings or change the router/authentication.

## Privacy and safety

The attached QGIS context snapshot contains metadata: active layer, field schema, selection count, and map-view summary. It is not a bulk dump of all records. With default automatic read access, the model can additionally request bounded actual layer records and geometry without another confirmation. Credentials and provider paths are excluded; screenshots are still explicitly attached.

**Allow read-only access to all loaded layers** is enabled by default and applies to the configured router; disable it for manual data-sharing review. The older **Automatically send selected QGIS metadata** setting remains available in review mode and is tied to one router/authentication configuration. Changing that identity revokes its metadata trust. Image/PDF sending is separate: the first visual send asks for consent, then Copilot remembers that approval for this router/authentication. Revoke it with **Remember approval for image/PDF attachments** in Settings.

Automatic read access removes read prompts, not safeguards on changes. Raw tool results are held only in the active request's memory and are not automatically stored in local tool records or chat history. User-visible answers may quote values and are retained as ordinary chat text, including reuse as context for follow-up questions. Join configuration contains layer IDs and matching fields, not provider paths or credentials.

Visual payloads remain in a bounded in-memory cache. Only attachment manifests are saved locally; image/PDF bytes, source paths, API keys, raw SSE events, and private reasoning are not saved in chat history. Public Activity text is sanitized and bounded before optional local retention. Private PDF rendering scratch files are removed after preparation. Restarting, switching chats/projects/routers, or cache eviction may require re-attaching an earlier image. Chat text and sanitized metadata are retained for 30 days by default (configurable).

Explicit screenshots/files may contain personal data. Review them before sending. Your router and upstream model provider have their own retention policies; deleting local chats does not delete their copies. See [SECURITY.md](SECURITY.md).

## Development

```sh
git clone https://github.com/tangjia469-collab/qgis-ai-copilot.git
cd qgis-ai-copilot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests
ruff check qgis_ai_copilot tests scripts
python scripts/check_public_release.py
python scripts/build_plugin.py
```

QGIS is a system application/dependency; do not install an unrelated `qgis` PyPI package. Run native tests with QGIS's Python environment:

```sh
QT_QPA_PLATFORM=offscreen QGIS_PREFIX_PATH=/usr /usr/bin/python3 scripts/run_qgis_tests.py
QT_QPA_PLATFORM=offscreen QGIS_PREFIX_PATH=/usr /usr/bin/python3 scripts/run_execute_tests.py
```

See [the development guide](docs/DEVELOPMENT.md) for the macOS bundled runtime and CI setup. All GIS fixtures are generated in memory; no private projects or API credentials are required.

## Status and contributions

The current alpha has been exercised with native QGIS 3.44.6 on macOS. CI targets QGIS 3.44.6 on Linux. Windows and QGIS 4/Qt 6 are not yet verified. Both Chat Completions and Responses are supported; tool use requires Responses. The plugin does not assume every router supports every tool, image or thinking option.

Read [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), [the product scope](PRD.md), and [the UI design](DESIGN.md). Please report bugs through [GitHub Issues](https://github.com/tangjia469-collab/qgis-ai-copilot/issues) without uploading secrets or private GIS data.

## License

Copyright (C) 2026 QGIS AI Copilot contributors.

Licensed under the **GNU General Public License, version 3 or (at your option) any later version**. See [LICENSE](LICENSE). Distributed without warranty. Qt example attribution and external dependency notes are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
