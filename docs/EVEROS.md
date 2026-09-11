# Optional local EverOS memory

This is an optional adapter, not a replacement for project-bound chat history. No EverOS package is installed or started by Copilot. The existing local service must be running.

## Connection and retrieval

- Default off for new installations. Settings stores only enabled state, loopback origin and user/app/project IDs, never credentials. Configure the actual EverOS user ID; OS username is only a starting suggestion.
- Only `localhost`, `127.0.0.1` and `::1` origins are accepted. No URL credentials, paths, queries or fragments. Requests use a separate network manager with no proxy and no router authorization; redirects are refused.
- The enabled model gets only `search_memory(query)`, never a write, filesystem, shell or arbitrary-URL tool. Agent recall requires Responses/function calling; note saving is a direct local UI action independent of model selection.
- At most three distinct searches per model task, five returned notes and 1,200 characters per excerpt. Queries are limited to 500 characters, HTTP responses to 512 KiB and searches to 15 seconds. A failed lookup returns an ordinary tool error so the model can continue without inventing memories.
- The local search asks for `top_k=5`, `include_profile=false`, `method=hybrid`. Returned episodes must exactly match the configured user/app/project fields. Credential-like entries, duplicates and weak irrelevant matches are omitted; strings are redacted and bounded. This is a relevance/scope filter, not a guarantee that the configured service contains no sensitive personal data.
- Relevant excerpts go to the selected router/model as transient tool results. They are historical, untrusted references, not instructions and not live GIS state. Do not treat an old layer name, field value or geometry as a fresh observation.
- Scope settings select EverOS's own hard partition. The default `default/default` reuses the user's shared memory library. It does not create a private namespace per QGIS project; include project/topic names in notes and queries or explicitly configure a dedicated scope if wanted.
- Stop, project change, plugin unload or settings save closes active agent memory lookups. Changing the router/authentication disables memory until explicitly enabled again.

## Explicit saves only

Use Add context → Memory → Remember a note, or a leading `/remember`, `Remember this:` or `记住：` command. These open the same editable preview. Only clicking Save writes. Question editing cannot turn into a memory write, and cancelling preserves the draft. Notes are limited to 4,000 characters and credential-like content is rejected.

The write calls `/api/v1/memory/add` with one user-authored note and a unique `qgis-note-…` session ID. If it is only accumulated, Copilot calls `/api/v1/memory/flush`. `extracted` is reported as saved; `no_extraction` is not reported as a durable memory and keeps the command draft for refinement. Search indexing may finish later. EverOS may use its own extraction provider, whose costs are not included in Copilot's model-cost footer.

Add waits up to 30 seconds; extraction waits up to 120 seconds. A timeout, interruption or lost response can leave an uncertain outcome: the service may already have accepted the note. Copilot does not blindly retry. It keeps up to 20 local receipts containing only operation ID, content/scope hash and status to guard against accidental repeated submissions. Check EverOS before resubmitting an uncertain note. This is not a server-side exactly-once guarantee. There is no memory delete/edit API in this add-on.

Raw recall payloads are not automatically saved to chat history or local tool records. The final answer may quote or summarize a memory and is retained as normal chat text. Note content is sent only to the local service after explicit Save; the service's own storage, extraction and retention rules still apply.

## API contract and verification

The installed EverOS service exposes `/health` and POST `/api/v1/memory/search`, `/api/v1/memory/add`, `/api/v1/memory/flush`. Its `/openapi.json` is absent in the verified local build, so integration was checked against the installed public helper and route/DTO source. No credential files were read. Public tests use isolated loopback fixtures, not real memory writes.

Native release tests cover scoped recall reaching the model, disabled memory, cancellation/late replies, redirect and size limits, explicit Save/Cancel, extraction outcomes, uncertain-save dedupe, draft preservation and router-change revocation.
