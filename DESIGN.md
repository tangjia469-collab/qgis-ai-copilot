# Native UI design

Keep the map central and the assistant quiet: native palette-derived surfaces, compact controls, one prominent Send/Stop action, and no second sidebar inside the dock.

The resting dock contains a header, the conversation, a composer, and a privacy/status footer. The action row is:

`Attachment · Add context ▾ · Model / Thinking ▾ · Send`

The context dropdown contains project identity, Current/Refresh, selected metadata count and removable chips, Checks, Preview, and Choose context. Changes in the full context picker are applied explicitly. The model popup contains search, the router catalogue, and available thinking levels. Both popups open upward when space permits, stay within the visible dock/screen, and return focus on Escape.

![Synthetic context dropdown](docs/images/context-menu.png)

Draft file attachments have preview/removal controls and a height-bounded scroll strip. They do not appear as implicitly trusted metadata. During streaming, Send becomes Stop. Errors remain visible and retain partial answers; retry preserves the original model and request context.

An active answer has a compact status row: sending/waiting/receiving, elapsed `mm:ss`, time since router activity when relevant, and a text Stop button. Silence does not produce fake milestones or reveal internal reasoning. A terminal error is shown once, alongside any preserved partial answer.

When Responses activity summaries are enabled, an expandable Activity panel appears above the final answer. It contains router-provided commentary/public reasoning summaries and local preparation milestones only; raw reasoning is omitted. The assistant answer is a separate blue-tinted card.

Validate 360, 420, and 460 pixel docks. Long model names are elided visually but remain available in tooltips/accessibility labels. No permanent Model, Thinking, or context/status rows sit above the conversation.

Message metadata belongs below the body, not in a header. A compact footer shows model/Thinking/time and an unobtrusive 14 px overlapping-pages icon in a 22 px Copy target. Question cards show four lines by default and expand through Show more. Only the latest question exposes a small pencil icon. Editing uses the composer with a visible edit notice and Cancel; Send replaces that question and its following AI answers only after validation and consent. Local check rows remain. Cancel restores the pre-edit draft.
