# Product scope

## Purpose

Help GIS users ask questions about their current work without repeatedly switching to an external chat application. The assistant can inspect explicitly selected metadata, images, screenshots, and PDF pages, while remaining independent of any one model provider.

## Alpha requirements

- One OpenAI-compatible router profile; credentials held by QGIS Authentication Manager.
- Dynamic model catalogue, searchable selection, `Thinking: Auto` by default, and optional explicit router/local capability settings.
- Streamed/non-streamed chat, cancellation, visible errors, and retry without silently switching models.
- Active requests expose observable transport stages, elapsed time, and Stop. Ten-minute idle timeout resets on network activity; a one-hour hard cap bounds even active connections. No fabricated progress percentages or raw reasoning are shown.
- Responses mode can opt into public model commentary and reasoning summaries in a separate bounded Activity panel. Raw chain-of-thought, encrypted reasoning, unknown event payloads, and tool arguments are ignored. The final answer remains separate. Chat Completions stays the default compatibility adapter and states when the router supplies no model activity.
- Project-bound local conversations with configurable retention.
- User-inspectable metadata categories, optional router-bound automatic metadata trust, and per-request visual consent.
- Local read-only inspection tools; no autonomous state-changing GIS actions or arbitrary code execution.
- Image/PDF attachment intake, previews, removal, clipboard paste, and user-triggered screenshots.
- Activity visibility: show local preparation milestones and, when explicitly enabled with Responses, router-provided commentary/public reasoning summaries with cancellation and error state.
- Compact native UI: context details in Add context; model/thinking immediately beside Send.
- Answer metadata and icon-only Copy belong in the message footer. User prompts are compact and expandable. The latest question may be edited and resent atomically; cancellation and invalid input do not change history. Revisions exclude the superseded answer from outgoing context and preserve local tool records.

## Release acceptance

Tests cover protocol validation, bounded history, sanitization, metadata trust invalidation, image compression, PDF selected pages, cancellation, retries, lifecycle cleanup, and 360/420/460-pixel layouts. Public tests use generated data and a loopback router; paid API access is not required.

## Out of scope

Files adapters, multi-router switching, autonomous agents, live screen monitoring, public QGIS repository submission, and verified QGIS 4/Qt 6 compatibility. Responses streaming is now an explicitly enabled, public-summary-only adapter; deeper tool/file capabilities require separate design and validation.
