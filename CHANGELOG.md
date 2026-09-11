# Changelog

## 0.7.0-alpha - Optional local EverOS memory

- Add opt-in local memory recall through the read-only `search_memory` tool, with source IDs, bounded relevant excerpts and visible lookup status.
- Connect only to a configured loopback EverOS origin; never forward router authentication or follow redirects. Scope/user fields are fixed by Settings, not model arguments.
- Add a compact Memory menu under Add context and a previewed Save flow for `/remember`, `Remember this:` and `记住：` notes. Ordinary chat and model output never write memories.
- Keep raw recall results transient; record only bounded save receipts locally. Handle add/extraction outcomes honestly, preserve drafts on failure, and avoid blind duplicate saves after uncertain outcomes.
- Preserve automatic GIS reads, explicit project-change approvals, cost estimates and all existing UI behavior.

## 0.6.2-alpha - Read without repeated approvals

- Enable automatic read-only access to all loaded layers by default, including metadata, records, joins, statistics and geometry across requests and chats.
- Remove per-read permission interruptions while keeping Chat non-mutating and preserving every Execute action approval, cancellation and recovery guard.
- Add **Allow read-only access to all loaded layers** in Settings; disabling it restores scoped data-sharing review. Keep screenshot/file consent separate.
- Keep bounded reads, sensitive-field exclusion, cost estimates and transient raw tool results unchanged.

## 0.6.1-alpha - Official-price money estimates

- Replace footer token counts with estimated USD model cost from verified official Standard API prices; keep time/model/thinking and compact Copy.
- Account for cached reads, cache writes and long-context tiers per model call. Bound missing cache details as a range; do not double-count reasoning output.
- Preserve dated decimal-string cost records and numeric per-call usage; keep unknown, stopped and incomplete costs explicitly unavailable.
- Give the monetary amount a non-eliding footer label and disclose its source and differences from router billing on hover.

## 0.6.0-alpha - Read actual layer data in Chat

- Give default Responses Chat read-only access to real attribute rows, joined values, statistics, join configuration and geometry checks; keep Execute required for project changes.
- Ask for per-request approval of the exact layer, fields, row scope and data kind before sharing values or geometry. Permit same-scope paging; invalidate changed selections/sources and keep statistics approval distinct from raw-row approval.
- Bound reads and report pagination, nulls, scan coverage, time/output limits, geometry units and omissions. Exclude sensitive credential/source fields.
- Keep raw tool results only in transient request context, not automatic local history. Preserve compact answers, attachments, timing, Stop, edit/retry and Execute recovery.

## 0.5.0-alpha - Opt-in project actions

- Ship the Execute switch and tool loop in the installed plugin; read-only Chat stays the default.
- Run approved Processing, style, visibility and zoom actions.
- Add confirmed memory-layer removal with a private pre-removal backup and Undo from history/Chats.
- Prevent action dispatch on cancelled/pending Responses, preserve continuation context, record approval before execution, and roll back supported actions if their completion audit fails.
- Preserve screenshot selection, attachments, response selection, compact layout and timing/usage.

## 0.4.8-alpha - Screenshot to draft

- Add a small screenshot button beside the paperclip. On macOS it opens native area selection and attaches the chosen image to the current draft without sending.
- Escape cancels; changing chats, editing context, router or project, and unloading Copilot discard pending captures.
- Temporary screenshots are removed after decoding; existing image compression, preview/removal and send consent remain unchanged.
- Keep the composer compact at 360, 420 and 460 pixels. Other platforms retain paste/window/map capture while the native area button is unavailable.

## 0.4.7-alpha - Understandable live work plan

- Replace repeated Activity labels with a compact current-step and completed-step plan.
- Show meaningful transport, public model, QGIS, approval, Stop, completion, and error states.
- Keep technical event details collapsed and available for diagnosis without exposing private reasoning.
- Bound the visible checklist, keep model text plain, clear stale Next steps, and hide replaced rows immediately during rapid updates.
- Preserve the UI-only release boundary; unfinished Execute modules are not included in the package.
- Document read-only Chat as the default mode for startup, reload, and new conversations.
- Add a map-canvas capture option that sends only the visible map, without QGIS window chrome.

## 0.4.6-alpha - Select and ask from responses

- Select response text with the mouse or keyboard and use the native context menu to Copy or Ask about selection.
- Quoted passages are appended to the composer as a follow-up draft; nothing is sent automatically and existing draft text stays intact.
- Code-box selections use the same follow-up action, while the code-box Copy icon still copies the complete expression only.

## 0.4.5-alpha - Remembered attachment approval

- After one accepted visual send, reuse attachment consent for the same router and QGIS authentication configuration.
- Existing sent attachment messages restore that approval after a Copilot reload, so retained chat images do not trigger a duplicate prompt.
- Router or authentication changes revoke the remembered approval; the Settings dialog exposes the current attachment-consent state.

## 0.4.4-alpha - Copyable expression boxes

- Display code and QGIS expressions in compact read-only boxes with their own small Copy icon.
- Copy only the expression/script, retaining quotes, tabs, internal blank lines, and trailing spaces from complete top-level fences.
- Keep full-answer Copy unchanged, preserve technical disclosures, and bound long code with local scrolling.
- Code is never executed by the display or Copy control.

## 0.4.3-alpha - Composer matches the approved preview

- Replace native folder/triangle fallback icons with palette-aware paperclip, arrow, stop, and chevron outlines.
- Use a flat, normal-weight model switch next to a blue Send button with a white arrow.
- Preserve dropdown menus and Send/Stop behavior, with verified narrow widths and disabled/dark states.

## 0.4.2-alpha - Readable native chat

- Explicit CJK-aware sans-serif typography, compact Markdown headings, consistently sized code, and width-bounded tables.
- Pale blue replies with blue text, right-aligned compact question bubbles, smaller composer, and metadata/copy icons at the bottom.
- Named technical-detail sections fold without changing the original message or full-copy behavior; warnings and normal answer text remain visible.
- Preserve streaming, Activity, Stop, retries, editing, attachment consent, protected links, and remote-image blocking.
- This UI-only release does not include the in-progress Execute capability.

## 0.4.1-alpha — Compact message footers and question editing

- Move model, thinking, and timestamp to a one-line footer with a small overlapping-pages Copy icon.
- Compact user questions with a Show more/Show less control, preserving full text.
- Edit the latest question and resend to replace its answer, with one pre-dispatch history commit.
- Cancel restores the previous draft; cancelled/invalid sends leave the original answer untouched.
- Retain attachment consent, require explicit handling of missing visuals, preserve local check records, and reject stale retries.


## 0.4.0-alpha — Live model activity and interruptible work

- Optional Responses adapter with OpenAI public reasoning summaries and commentary events.
- Expandable, deduplicated Activity panel separated from the final answer; raw reasoning is ignored.
- Settings controls for Responses mode and model activity summaries; no silent adapter fallback.
- Chat Completions remains the default compatibility path and shows honest local/transport milestones.
- Progress/attachment tests cover activity privacy, cancellation, non-streaming Responses, unsupported endpoints, and persisted sanitization.

## 0.3.1-alpha — First packaged public release

- Observable sending/waiting/receiving status, elapsed time, and a message-level Stop button.
- Separate ten-minute chat inactivity budget; active streams and heartbeats reset the deadline, with an independent one-hour hard cap.
- Immediate local cancellation, partial-answer retention, no private reasoning display, and no duplicate timeout message.
- QGIS 3.44.6 Linux CI, including native window-decoration-aware layout checks.

## 0.3.0-alpha — Initial public source

- Native QGIS chat dock with dynamically loaded router models and optional thinking levels.
- Composer-based model/thinking switch and folded Add context status/chips dropdown.
- Streaming, Stop, retry, local project-bound chats, and read-only GIS checks.
- Images, clipboard screenshots, window/screen capture, PDF page selection and local rendering.
- Lossless screenshot compression with bounded JPEG/resize fallback.
- Router-bound metadata trust, explicit visual-attachment confirmation, and manifest-only attachment history.
- Portable synthetic test fixtures, public documentation, GPL-3.0-or-later licensing, and reproducible packaging.

This is a GitHub-distributed experimental release, not an official QGIS Plugin Repository submission. Earlier local prototypes were not public releases.
