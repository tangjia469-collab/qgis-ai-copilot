# Changelog

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
