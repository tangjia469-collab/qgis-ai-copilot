# Live work plan redesign

## Delivery status

The work-plan UI shipped in `0.4.7-alpha`. Version `0.6.0-alpha` adds scoped actual-data inspection to default read-only Chat and retains explicit Execute mode with real approved actions and recoverable memory-layer removal from `0.5.0-alpha`. The earlier UI-only release boundary is historical.

## Goal

Replace the current repeated Activity log with a compact, understandable process view that answers three questions at a glance: what the agent is doing now, what it has already finished, and what it needs from the user. Keep technical details available behind a disclosure and keep Stop/approval behavior immediate.

## Scope

### In

- A structured live work plan for Chat responses, with text states ready for future Execute integration.
- One prominent current step with meaningful user-facing text.
- Completed steps shown once as a compact checklist.
- Approval, waiting, tool-running, completion, Stop, and error states.
- Public model commentary and reasoning summaries normalized into short progress updates.
- Existing raw/technical activity retained behind “Details” and deduplicated.
- Existing blue answer card, response selection, expression Copy boxes, attachments, editing, and retry behavior preserved.

### Out

- Showing private chain-of-thought or raw reasoning.
- Inventing percentages, fake progress bars, or guessed completion times.
- Automatically sending a follow-up or automatically repeating a QGIS action.
- Changing the QGIS tool allowlist or Execute approval policy.

## Proposed interaction

While a request is running, show a compact panel above the answer:

```text
Working on your request                         Stop
Step 2 of 3 · Selecting matching features

✓ Inspect project layers
→ Select green-space features by expression     current
○ Prepare the result for export

Details · 7 updates ▸
```

Use real step names from observed local checks, approved QGIS tools, and public router commentary. If the plan is not known, show the current transport state instead of guessing: “Waiting for the router”, “Receiving answer”, or “Waiting for your approval”.

When a step finishes, move it to the completed checklist and expose its concrete result, for example “68 features selected” or “Output layer created: Green_Space”. Keep paths, raw feature data, and private reasoning out of the compact view.

## Action items

- [x] Refactor `MessageCard`/`ActivityBrowser` in `qgis_ai_copilot/widgets.py` into a `WorkPlanPanel` with current-step, completed-step, waiting/approval, and collapsed-details regions.
- [x] Reuse existing Chat transport and public-summary signals without changing the router protocol.
- [x] Keep at most three completed checklist rows plus the current row visible; retain the full bounded event history under scrollable Details.
- [x] Add palette-aware styles in `qgis_ai_copilot/styles.py`; preserve blue assistant answers and compact composer controls.
- [x] Add native regression coverage for grouping, deduplication, current/next text, approval visibility, Stop, terminal states, narrow docks, plain-text safety, and rapid updates.
- [x] Render synthetic screenshots at 360, 420, and 460 pixels and compare them with the approved QGIS UI direction before installing.
- [x] Reload only Copilot after the tests pass; do not restart QGIS or save the user's project automatically.

Structured `plan`/`step_started`/`step_completed` events and `ExecuteSession` integration remain separate Execute-mode work, not blockers for this UI-only delivery.

## Done when

- The user can identify the current action and next action without reading a repeated event stream.
- Completed work is shown once with a concrete result.
- Stop remains visible and cancels network/queued work without undoing completed QGIS actions; approval/tool text states are ready for the separate Execute implementation.
- Details can be expanded for diagnosis, but the compact panel never exposes private reasoning or raw sensitive payloads.
- Existing chat, attachments, selection, expression Copy, editing, and retry tests remain green; Execute implementation and its dedicated tests remain separate and unreleased.

## Assumption

The panel is expanded while work is active and collapses to one summary row after completion; the technical Details disclosure remains available afterward.
