# Product scope

## Purpose

Help GIS users ask questions about their current work without repeatedly switching to an external chat application. The assistant can inspect explicitly selected metadata, images, screenshots, and PDF pages, while remaining independent of any one model provider.

## Alpha requirements

- One OpenAI-compatible router profile; credentials held by QGIS Authentication Manager.
- Dynamic model catalogue, searchable selection, `Thinking: Auto` by default, and optional explicit router/local capability settings.
- Streamed/non-streamed chat, cancellation, visible errors, and retry without silently switching models.
- Active requests expose observable transport stages, elapsed time, and Stop. Ten-minute idle timeout resets on network activity; a one-hour hard cap bounds even active connections. No fabricated progress percentages or raw reasoning are shown.
- Project-bound local conversations with configurable retention.
- User-inspectable metadata categories, optional router-bound automatic metadata trust, and per-request visual consent.
- Local read-only inspection tools; no autonomous state-changing GIS actions or arbitrary code execution.
- Image/PDF attachment intake, previews, removal, clipboard paste, and user-triggered screenshots.
- Compact native UI: context details in Add context; model/thinking immediately beside Send.

## Release acceptance

Tests cover protocol validation, bounded history, sanitization, metadata trust invalidation, image compression, PDF selected pages, cancellation, retries, lifecycle cleanup, and 360/420/460-pixel layouts. Public tests use generated data and a loopback router; paid API access is not required.

## Out of scope

Responses/Files adapters, multi-router switching, autonomous agents, live screen monitoring, public QGIS repository submission, and verified QGIS 4/Qt 6 compatibility. These require separate design and validation.
