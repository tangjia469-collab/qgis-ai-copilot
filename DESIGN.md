# Native UI design

The screenshot button is a small outline capture frame beside the paperclip in the composer. It starts macOS area selection; a completed selection becomes a previewable, removable draft attachment. Escape returns without changing the draft. It never submits a prompt or toggles Execute. Selection is cancelled if the destination conversation, edit, router or project changes.

Keep the map central and the assistant quiet: native palette-derived surfaces, compact controls, one prominent Send/Stop action, and no second sidebar inside the dock.

## Approved reply layout

Copyable expressions and scripts use a compact code box with a language label and a small two-page Copy icon. The box uses a true monospace font, local scrolling for long content, and a maximum 240 px editor height. The local Copy action copies code only; the message-footer Copy retains the full original Markdown. Existing complete unindented fenced blocks preserve original whitespace independently of Qt's Markdown normalization; indented/nested code uses Qt's semantic code text. Inline identifiers remain inline. Code boxes appear at terminal rendering, not while a partial response is still streaming. Display and Copy never run an expression.

The native implementation follows the approved typography preview. Use a CJK-capable system sans-serif family (PingFang SC on macOS when available), 14 px body text, 15 px semibold headings, and 13 px code. Set these on the parsed QTextDocument, not only the widget stylesheet, so Markdown does not restore oversized headings or serif fallback. Use 22 px body / 23 px heading line boxes with restrained paragraph/list spacing. Tables fit their container.

Response text supports mouse and keyboard selection. The native context menu keeps Copy and Select All, and adds **Ask about selection** only when an assistant passage is highlighted. That action quotes the selected text into the composer without sending; existing draft text and chat history remain unchanged until the user chooses Send. Code boxes use the same action for selected lines, while their dedicated Copy icon copies the complete code block.

### Live work plan

During active work, show `Working on your request` with one current step, a compact completed checklist, and a right-aligned Stop control. Use a concrete status sentence such as `Checking dissolve field behavior`, `Waiting for the router`, or `Waiting for your approval`; do not fill the panel with repeated `QGIS / connection` or `Reasoning summary` headings. Show at most three completed rows plus the current row, with an explicit Next line only when the latest public update supplies it. Keep the event stream under a collapsed `Details · N updates` disclosure. When finished, collapse the plan to `Answer ready · N steps` and keep the answer card readable below it. Public commentary may update the current step; private reasoning remains excluded. All compact labels remain plain text, and obsolete rows are hidden immediately during rapid updates.

Assistant replies have a pale blue surface, subdued border, and readable blue text in light and dark palettes. User questions align right at up to 82% of the conversation width. The composer stays compact; the model/thinking control remains next to Send. Footer text shows model and thinking concisely, with timestamp and full metadata on hover; the small Copy icon stays at the bottom.

Parsed Markdown headings explicitly named `Layers and parameters`, `Parameter details`, `Raw log`, `Original warning`, or `Technical details` (and their supported Chinese equivalents) become inline disclosures. Only that section, through the next peer/parent heading, folds. Ordinary warnings, conclusions, code blocks, and unrecognized headings remain visible. Full original content is retained in history and Copy; no result is invented or rewritten to match the preview. Existing answers gain typography immediately, and responses using the named section convention gain disclosures.

The resting dock contains a header, the conversation, a composer, and a privacy/status footer. The action row is:

Composer controls use consistent 1.8 px outline paths: a bare paperclip, light text selectors with open chevrons, and a blue Send control with a white up-arrow. Do not rely on QGIS fallback folder/triangle icons. The model selector has no filled resting background and no persistent checked appearance. Hover/focus, disabled, dark palette, and Stop states remain explicit.

`Attachment · Add context ▾ · Model / Thinking ▾ · Send`

The QGIS Plugins toolbar uses a dedicated **Assist** button with the plugin icon. It toggles the dock, keeps its checked state synchronized with dock visibility, and raises the dock when opened.

Chat is the default mode after startup, reload, new/resumed chats and project changes. Select Execute in the header for approved project actions. A nonmodal approval dialog names the action, inputs and expected effect; Stop remains available. Memory-layer removal saves a private recovery copy first and its action card exposes Undo remove.

Answer footers replace usage counts with an unobtrusive **Est. $…** USD cost (or a bounded range). Keep the amount in its own non-eliding label before Copy; elide the model/time metadata when needed. Hover shows official Standard pricing source/date and explains this is not a router bill. Unknown pricing and incomplete responses say **Cost unavailable**, never a token-count fallback.

Responses Chat can inspect actual records, joins and geometry without offering write tools. **Allow read-only access to all loaded layers** is on by default: no metadata or per-read permission popups across questions/chats. The quiet status footer says **Read access: automatic · no project changes**. Settings explains that bounded requested data is sent to the configured router. Turning it off restores the nonmodal **Share layer data** review dialog and per-request scoped permissions. The legacy metadata-trust checkbox is disabled while automatic read access covers it. Read access never toggles Execute; mutation approvals and separate screenshot/file consent remain. Do not persist raw tool rows in the conversation; retain the agent's user-visible answer normally.

The context dropdown contains project identity, Current/Refresh, selected metadata count and removable chips, Checks, Preview, and Choose context. Changes in the full context picker are applied explicitly. The model popup contains search, the router catalogue, and available thinking levels. Both popups open upward when space permits, stay within the visible dock/screen, and return focus on Escape.

An optional **Memory** menu sits beside Checks/Preview inside Add context, not as another permanent sidebar row. It reports EverOS On/Off, opens the explicit Remember-note preview, offers Stop for an active save, and links to Settings. Settings owns the enabled toggle and local scope fields. Read-only memory lookups show only source counts in Activity; raw excerpts remain transient. A Save preview names the local destination and sends only user-entered text. Never silently turn ordinary chat or a question edit into a memory write.

![Synthetic context dropdown](docs/images/context-menu.png)

Draft file attachments have preview/removal controls and a height-bounded scroll strip. The attachment menu can capture the map canvas without QGIS chrome, the full QGIS window, or the screen after a short countdown. They do not appear as implicitly trusted metadata. The first visual send to a router asks for consent; an accepted decision is remembered for that Base URL and Authentication selection, including retained chat images and retries. Settings can revoke it, and changing the router/authentication clears it. During streaming, Send becomes Stop. Errors remain visible and retain partial answers; retry preserves the original model and request context.

An active answer has a compact status row: sending/waiting/receiving, elapsed `mm:ss`, time since router activity when relevant, and a text Stop button. Silence does not produce fake milestones or reveal internal reasoning. A terminal error is shown once, alongside any preserved partial answer.

When Responses activity summaries are enabled, the live work plan uses router-provided commentary/public reasoning summaries and local preparation milestones only; raw reasoning is omitted. Its Details disclosure retains the observed updates. The assistant answer remains blue-tinted below the compact plan.

Validate 360, 420, and 460 pixel docks. Long model names are elided visually but remain available in tooltips/accessibility labels. No permanent Model, Thinking, or context/status rows sit above the conversation.

Message metadata belongs below the body, not in a header. A compact footer shows model/Thinking/time and an unobtrusive 14 px overlapping-pages icon in a 22 px Copy target. Question cards show four lines by default and expand through Show more. Only the latest question exposes a small pencil icon. Editing uses the composer with a visible edit notice and Cancel; Send replaces that question and its following AI answers only after validation and consent. Local check rows remain. Cancel restores the pre-edit draft.
