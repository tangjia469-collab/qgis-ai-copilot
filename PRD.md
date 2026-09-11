# Product scope

## Purpose

Help GIS users ask questions about their current work without repeatedly switching to an external chat application. The assistant can inspect selected metadata, approved actual layer records/joins/geometry, images, screenshots and PDF pages, while remaining independent of any one model provider.

## Alpha requirements

- One OpenAI-compatible router profile; credentials held by QGIS Authentication Manager.
- Dynamic model catalogue, searchable selection, `Thinking: Auto` by default, and optional explicit router/local capability settings.
- Read-only Chat mode is the default on startup, reload, new/resumed conversations and project changes. Execute requires an explicit user switch and approval for each project change.
- Streamed/non-streamed chat, cancellation, visible errors, and retry without silently switching models.
- Active requests expose observable transport stages, elapsed time, and Stop. Ten-minute idle timeout resets on network activity; a one-hour hard cap bounds even active connections. No fabricated progress percentages or raw reasoning are shown.
- Responses mode can opt into public model commentary and reasoning summaries in a separate bounded Activity panel. Raw chain-of-thought, encrypted reasoning, unknown event payloads, and tool arguments are ignored. The final answer remains separate. Chat Completions stays the default compatibility adapter and states when the router supplies no model activity.
- Project-bound local conversations with configurable retention.
- Optional local EverOS add-on: default-off scoped recall via read-only model tool; bounded relevant excerpts and visible lookup counts; graceful failure without invented memories. No implicit full-profile or full-library attachment.
- Memory writes require an explicit Remember-note preview and Save. Ordinary chat/model responses never write memory. Note extraction outcomes, cancellation and uncertain saves remain visible; no automatic replay. EverOS memory is historical context, not current GIS ground truth.
- Answer footer shows estimated USD at verified official Standard API list prices, not token counts or a claimed router bill. Preserve duration/model/thinking; keep the amount visible at narrow widths. Price multi-step requests per call; retain a dated source snapshot, bound missing cache detail as a range, and show unavailable for unknown prices or incomplete usage.
- User-inspectable metadata categories, optional router-bound automatic metadata trust, and one-time router-bound visual consent that the user can revoke. Responses support selecting passages for explicit quoted follow-up drafts; selection never sends automatically.
- Default Responses Chat exposes read-only tools for actual attribute rows (including joined fields), statistics, join configuration and bounded geometry inspection. Chat Completions remains metadata-only. No state-changing GIS tools or arbitrary code are exposed in default Chat.
- Automatic read access is the default across questions, new/resumed chats and loaded layers. Metadata, actual records/joins/statistics and geometry can be sent to the configured router without per-read permission. This never enables edits. Settings can restore per-request scoped review; rejecting that optional review stops the task. Empty selection still means zero rows. Raw tool payloads are transient, not automatically persisted; user-visible answers may contain values.
- Optional Execute: validated Processing to new memory layers, styling, zoom, visibility and removal of explicitly confirmed memory layers. Raw Python, arbitrary file paths and source-file deletion are excluded.
- Before temporary-layer removal, create and validate a private GeoPackage/style recovery copy. Undo restores data; backup failure prevents removal. Refuse disk/database/raster, filtered/joined and actively edited layers.
- Image/PDF attachment intake, previews, removal, clipboard paste, and user-triggered screenshots. The first visual send per router/authentication asks for consent; accepted consent is remembered until that identity changes or the user revokes it in Settings.
- The attachment menu includes a map-canvas capture that omits QGIS window chrome so the agent can inspect the visible map when the user chooses to share it.
- Live process visibility: grouped current/completed steps, explicit waiting/approval/Stop states, and folded technical details without private reasoning.
- Activity visibility: show local preparation milestones and, when explicitly enabled with Responses, router-provided commentary/public reasoning summaries with cancellation and error state.
- Compact native UI: context details in Add context; model/thinking immediately beside Send.
- Answer metadata and icon-only Copy belong in the message footer. User prompts are compact and expandable. The latest question may be edited and resent atomically; cancellation and invalid input do not change history. Revisions exclude the superseded answer from outgoing context and preserve local tool records.

## Release acceptance

Tests cover protocol validation, bounded history, sanitization, metadata trust invalidation, image compression, PDF selected pages, cancellation, retries, lifecycle cleanup, and 360/420/460-pixel layouts. Public tests use generated data and a loopback router; paid API access is not required.

Data-inspection acceptance covers prompt-free reads across tools/requests, settings persistence and optional scoped review, real paginated values, joined columns/configuration, nulls, selected/empty-selected rows, selection changes during optional approval, sensitive field rejection, partial scan reporting, geometry units/omissions, bounded output, no automatic raw-result persistence and rejection of all mutating tool types in Chat. Source layers remain unchanged.

## Out of scope

Files adapters, multi-router switching, unattended changes, raw Python, source-file deletion, live screen monitoring, public QGIS repository submission, and verified QGIS 4/Qt 6 compatibility remain out of scope. Execute uses Responses function calls with explicit approvals and bounded local tools.
