# Design sweep D2 — fourteen rows the fix lanes returned as too big (2026-10-10)

Lane fable-design-D2. Rows: `lanes-1011d/D2-rows.md` (the queue rows carry the claims).
One section per row, verdict first: **PLAN** (implementation-ready for an Opus lane),
**PROGRAM-EXISTS** (a plan already owns it), **INVESTIGATION** (the cause is unknown; the
protocol that names it), **DROP** (stale or wrong, with the evidence). Code is cited by file
and symbol. Where rows share a mechanism the design is written once and the others point at
it. House format: `busy-root-queue-2026-10-10.md`.

Verdict table (filled as batches land):

| row | verdict | one line |
|---|---|---|
| D2.01 = L2.09 | PLAN | reviewed files ride upstream's `file.attach` data-url arm behind the existing submit owner; capability v3 |
| D2.02 = L2.07 | PLAN | `provider_submitted` is set before the provider is resolved, so a no-provider turn settles `outcome_unknown`; refuse pre-flight, classify by phase after |
| D2.03 = L5.03 | PLAN (gated on PR #7) | branch the LINEAGE display rows the way upstream's `/branch` already does; the child is a root, never a compression descendant |
| D2.04 = L5.04 | PLAN | `retry_of` written once on the new record; `retried_as` projected onto the old marker from it; no write-back |

---

## D2.01 = L2.09 — Native reviewed conversation input: arbitrary file contents

**Verdict: PLAN.** Size: ~130 production lines (fork-owned only), ~250 test lines, 3 stages
+ the launcher's C019 stage. No upstream file is edited.

### What the code says

- `agent_runtime/conversations/prompt.py::validate` accepts exactly `{"text","images"}`,
  900 KiB serialized (`MAX_PROMPT_BYTES`), every image `{"name","data"}` base64; `submit`
  calls native `image.attach_bytes` per image then `prompt.submit` with `reject_if_busy`.
- `ConversationService.send` (`conversations/service.py`) is the one admission owner:
  `store.admit(route, turn_id, prompt)` keys the receipt on `digest(payload)` — a resend of
  the same `turn_id` with different bytes is already `Refusal.CONFLICT`. That IS the
  same-turn changed-content guard the row asks for; files only have to be inside the digest.
- Upstream already has the native door: `tui_gateway/methods_prompt.py` `file.attach`
  (`contracts/prompt_voice.py::FileAttachParams`: `path` | `data_url` + `name`) staging bytes
  into `<session home>/attachments/<name>` through
  `tui_gateway/prompt_attachments.py::_stage_session_file_attachment` and answering a
  `@file:` ref the agent reads by tool. Any media type; bare base64 accepted; 25 MiB roof
  (`_ATTACH_BYTES_MAX_BYTES`). The fork's `tui_gateway/methods_pdf.py` (`pdf.attach`) is the
  rendered-pages arm for PDFs. Neither is dereferencing a client path when only `data_url`
  is sent.
- `ConversationService.capabilities()` advertises `"version": 2, "images": True`; the
  launcher gates its composer on these (C019 workorder
  `EterniaLauncher/docs/mission_control/planned/console-file-input-native-workorder-2026-10-07.md`).

### The design decisions

1. **Bytes inline, reviewed by the client, never a reference.** The row allows "bytes or an
   install-owned opaque reference". A reference is a second upload authority with its own
   expiry and ownership; the row forbids a separate upload/send authority. Inline base64 in
   the same `prompt` packet keeps one owner (`send`), one digest, one admission.
2. **Delivery is an attachment the agent reads by tool, not text spliced into the prompt.**
   That is upstream's `@file:` contract; splicing would blow the prompt-cache prefix and the
   900 KiB bound for every turn after.
3. **The packet** — `prompt = {"text", "images", "files"}`, `files` a list of
   `{"name", "media_type", "data"}`; `sha256` and `size_bytes` are COMPUTED server-side from
   `data` and echoed on the receipt (a client-supplied digest proves nothing). `files` is
   required in the key set (an old client omitting it is `INVALID_REQUEST` — the capability
   version tells it to send `[]`).
4. **Limits as one table** in `prompt.py`: `MAX_FILE_COUNT = 8`, `MAX_FILE_BYTES = 4 MiB`
   decoded, `MAX_FILES_TOTAL_BYTES = 16 MiB` decoded; `MAX_PROMPT_BYTES` keeps bounding
   `text` + `images` only (files are measured decoded, separately). Media types: an
   allow-list table `FILE_MEDIA_TYPES` (text/*, application/json, application/xml,
   application/yaml, text/csv, application/pdf). `application/pdf` routes to `pdf.attach`;
   everything else to `file.attach`.
5. **Typed refusals** — three new `Refusal` members in `conversations/model.py`:
   `FILE_UNSUPPORTED = "file_unsupported"`, `FILE_OVERSIZE = "file_oversize"`,
   `FILE_INVALID = "file_invalid"`. Expired / wrong-owner refusals the row lists already
   exist for the turn (`WRONG_OWNER`, `CONFLICT`); a file has no lifetime of its own.
6. **Ownership and identity.** Nothing new: profile/session/turn/execution ownership is the
   route + turn receipt (`store.admit`); the stored content identity is the native session's
   `attachments/<name>` plus the `@file:` ref on the submit user row, under the fork's
   `display_metadata` (ledger row `tui_gateway/session_workdir.py`). The route store keeps
   only the digest, never bytes.
7. **Recovery / restored draft.** `observe_execution` already answers `admitted: False` for
   an unknown `turn_id` (safe to resend) and the receipt state otherwise; a changed draft
   resent under the old `turn_id` is `CONFLICT`. The client's rule: `admitted: False` →
   resend; `admitted: True` → read, never resend. No new verb.
8. **Capability v3**: `"version": 3, "files": {"max_count", "max_file_bytes",
   "max_total_bytes", "media_types": [...]}` so the launcher never hardcodes a limit.

### Files and symbols

- `agent_runtime/conversations/prompt.py` — `validate` (files arm + table), `submit`
  (files attach loop before `prompt.submit`; `attached is not True` → `NATIVE_REFUSAL`),
  the limits/media tables.
- `agent_runtime/conversations/model.py` — `Refusal` three members.
- `agent_runtime/conversations/service.py::capabilities` — version 3 + `files` block.
- `agent_runtime/conversations/rpc.py` — unchanged (`params["prompt"]` passes through).
- Launcher half (wire change: `prompt.files`, capability `files`): the C019 workorder.

### Stages, tests, killing mutation

| stage | lands | test file | killing mutation |
|---|---|---|---|
| S1 contract | `validate` files arm, `Refusal` members, capability v3 | `tests/agent_runtime/test_conversation_worker_protocol_input.py` (+ `test_native_conversation_rpc.py` capability golden) | drop the per-file bound → the 4 MiB+1 file passes `validate` → red; remove `files` from the key set → old-shape prompt accepted → red |
| S2 submit | `submit` attaches each file (`file.attach`/`pdf.attach` by media type) then submits | `tests/agent_runtime/test_native_conversation.py` (scripted peer) | skip the `attached` check → a refused attach still submits → red; attach after submit → order assertion red |
| S3 recovery | digest covers files; `observe_execution` round trip | `tests/agent_runtime/test_native_conversation_roundtrip.py` | exclude `files` from `digest(payload)` → resend with changed file bytes is not `CONFLICT` → red |
| S4 launcher | C019: composer Files action gated on capability `files` | launcher | — |

### Risks

- A half-attached set followed by a failed `prompt.submit` leaves staged files in the native
  session home with no turn (upstream's own behaviour for `file.attach`); the turn settles
  `UNKNOWN` by the existing path. Record, do not fix here.
- Frame size on the serve socket: a 16 MiB decoded aggregate is ~22 MiB of JSON; confirm the
  serve's inbound frame bound (`hermes_cli/harness_parts/serve/handle_message.py`) before
  fixing `MAX_FILES_TOTAL_BYTES`; lower it if the bound is smaller.

### Owner question (blocks S1)

- Aggregate decoded limit: 16 MiB as proposed, or the launcher's composer limit if lower?

---

## D2.02 = L2.07 — Empty Base console after a provider-unavailable turn

**Verdict: PLAN** (stage 0 is the reproduction the row asks for; the mechanism is read off
the code, the exception class is not yet proven). Size: ~90 production lines, ~160 test
lines, 3 stages + a launcher copy stage.

### What the code says (the mechanism the row left unproven)

- `chat_turn_commit/run.py::_run_model` calls `self._cross_provider_boundary()` FIRST, then
  constructs `GPTPersonaRuntime(...)` and calls `mission_chat_reply`, which resolves the
  provider/credentials and builds the runner request (`persona_runtime.py::mission_chat_reply`
  → `self._runner.run(AgentRunRequest(provider=runtime_provider, ...))`).
- `_cross_provider_boundary` journals `executing` with `provider_submitted: True` and sets
  `self.provider_submitted = True`. So every exception raised between the journal write and
  the first HTTP byte — no provider configured (`hermes_cli/auth.py` `no_provider_configured`),
  a credential that will not resolve, a client that will not construct — reaches
  `settle.py::_settle_failure` with `provider_submitted=True`.
- `mission_chat_outcome.classify_turn_failure` then answers `_FAILURE_TABLE[(False, True)]`
  = `ExecutionState.BLOCKED` / `chat_turn_outcome_unknown`; `_record_failure` journals
  `TURN_STATE_OUTCOME_UNKNOWN`; `next_expected` says "resolve with action=abandon". Zero
  elements, no reply, and the launcher's
  `agent_console_composer_activity_binding.dart` renders exactly "Response status needs
  checking" for that state. The incident's `TURN_MODEL_RECEIPT` `provider=- model=-`
  (`persona_chat_session.py::_resolve_turn_model_selection`, logged from `admit.py`) says the
  selection had no provider BEFORE the boundary was crossed.
- The boundary already records the evidence that distinguishes the cases:
  `turn_phases.mark("provider_request_started")` in `run.py::_agent_ready_for_steer` fires
  when the request is actually dispatched, and `provider_first_byte` on the first byte. A
  record with `provider_submitted: True` and no `provider_request_started` phase is a turn
  whose request never left the process — a KNOWN outcome, not an ambiguous one.

The row's stated cause ("the marker alone does not prove an HTTP request succeeded") is
right; the design consequence is that the classifier must not key on the marker alone.

### The design decisions

1. **Refuse pre-flight when there is no provider to submit to.** In the plan/admit phase
   (`chat_turn_commit/admit.py`, right after `_resolve_turn_model_selection`), when
   `effective_provider` is empty, resolve runtime auth for the persona's profile the way the
   runner would (`hermes_cli/auth.py` resolution, no network) and refuse the turn before the
   write-ahead: `ExecutionState.REJECTED`, new `ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE =
   "chat_turn_provider_unavailable"` (family: pre-write-lane request refusals), `data` carrying
   `{"profile", "setup_action": "configure_provider"}`. Exit 2. No journal record, no frozen
   row, the reservation settles with the refusal (the serve's settle frame already carries
   refusals). This is `chat_turn.py`'s own rule: the boundary is where a request that cannot
   be honoured is refused. Cost in the normal case: nothing (the check runs only on the empty
   provider).
2. **Classify by phase after the boundary.** `classify_turn_failure` gains the phase evidence:
   `provider_submitted and not request_started` → `FAILED` /
   `CHAT_TURN_PROVIDER_UNAVAILABLE` (nothing ran; no turn-resolve), journaled as
   `TURN_STATE_PROVIDER_REFUSED` with a `provider_refusal` block whose `reason` is
   `provider_unavailable` and `status_code` 0. `_JOURNAL_TRANSITIONS[EXECUTING]` already
   allows `provider_refused`, which is TERMINAL and needs no operator resolution — no new
   journal state, no new marker. The classifier stays pure: `request_started` is a boolean
   argument read off `self.turn_phases.snapshot()` by `_settle_failure`.
3. **`outcome_unknown` keeps its meaning** — a request that started and whose answer is lost.
   The `_FAILURE_TABLE` stays two booleans; the phase rule is looked up BEFORE the table,
   beside `provider_refusal`, with the same justification that module gives for keeping the
   refusal out of the table.

### Files and symbols

- `agent_runtime/mission_chat_outcome.py` — `ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE`
  (wire addition: one new `error_kind` value), `classify_turn_failure(exc, *,
  provider_submitted, request_started)`, `PROVIDER_UNAVAILABLE_OUTCOME`, the import-time
  guard extended for the new outcome.
- `hermes_cli/harness_parts/persona/chat_turn_commit/admit.py` — the pre-flight refusal
  after `_resolve_turn_model_selection`.
- `hermes_cli/harness_parts/persona/chat_turn_commit/settle.py` — `_settle_failure` passes
  `request_started`; `_record_failure` journals the harness-authored refusal block.
- `agent_runtime/mission_chat_turns/records.py::safe_provider_refusal` — accepts
  `status_code` 0 with `reason` `provider_unavailable` (check the bounds table).
- Launcher half (wire: new `error_kind` and `provider_refusal.reason`):
  `agent_console_composer_activity_binding.dart` / `harness_chat_refusal.dart` render "No
  model provider is configured for this profile" with an Intelligence → Providers action
  instead of "Response status needs checking". Launcher queue row.

### Stages, tests, killing mutation

| stage | lands | test | killing mutation |
|---|---|---|---|
| S0 reproduce | a `TurnCommit` test with a runner that raises the no-provider error after the boundary; asserts today's `outcome_unknown` (the red that names the defect) | `tests/agent_runtime/test_mission_chat_outcome.py` + `tests/agent_runtime/test_terminal_turn_settlement.py` | — (this IS the red) |
| S1 classify | phase-aware `classify_turn_failure`; `_settle_failure` → `provider_refused` + typed block | same | pass `request_started=True` unconditionally → S0's turn settles `outcome_unknown` → red |
| S2 pre-flight | admit-phase refusal on empty provider | `tests/agent_runtime/test_serve_rpc_chat_turn.py` (refusal in the settle frame) | remove the check → a write-ahead record exists for the refused turn → red |
| S3 live | one no-credential turn through serve + Launcher; the composer shows the setup step; `TURN_MODEL_RECEIPT` and the settle frame kept as evidence | operator | — |

### Risks / owner question

- The pre-flight auth resolution must stay off the hot path: only when `effective_provider`
  is empty. Measure one warm turn before/after (h-turn1 numbers).
- Owner: is a provider that is configured but whose credential fails to resolve ALSO a
  pre-flight refusal (one more local resolution per turn) or only the post-boundary phase
  rule? Recommend phase rule only (zero cost on the hot path).

---

## D2.03 = L5.03 — Lossless prefix branching across compressed ancestry

**Verdict: PLAN, gated**: the Console branch/rewind it extends is NOT on `main`. It lives on
`origin/codex/console-history-runtime-verified` (draft PR #7;
`console-history-controls-review-2026-10-10.md` says changes requested). This section designs
the compressed-lineage arm to land in the SAME module once PR #7 lands; it is one stage of
that landing, not a lane of its own. Size: ~80 production lines, ~150 test lines.

### What the code says

- On the PR branch, `agent_runtime/operator_history.py::_plan` refuses
  `branch_compressed_history_unavailable` when `target["tip"] != params["session_id"]`,
  i.e. when the chat root has rotated into a compression descendant. `_target` addresses
  rows on the TIP's repaired projection only.
- `hermes_state_rewind.py` (UPSTREAM-owned) is the rewind door; it is not a branch door and
  the row's framing around it is a misdirection. Upstream's own branch,
  `tui_gateway/methods_session_branch.py::_branch_source_history`, already spans compression:
  it copies the persisted DISPLAY projection (`get_resume_conversations` → root→tip rows,
  archived turns included) reconciled with live memory, and `_persist_branch` /
  `_seed_branch_row` / `_persist_branch_seed` (`methods_session.py`, `session_workdir.py`)
  write the child in bounded chunks with `_branch_seed_persisted` set only when complete, and
  `_branched_from` on the child's `model_config`.
- `hermes_state_messages.py::get_messages_as_conversation(session_id, include_ancestors=True,
  include_row_ids=True)` is the public lineage read (root→tip via `parent_session_id`,
  `end_reason='compression'`; branch sessions exempt by design). Row ids are global, so a
  `row_id` target addresses any row in the lineage; a `client_message_id` target resolves
  through the root-keyed turn journal, which is lineage-independent.

### The design decisions

1. **Branch the lineage display rows, exactly as upstream's `/branch` does.** The target is
   resolved on the merged lineage projection (`include_ancestors=True`), not the tip; the
   child is seeded with the lineage's visible rows before the target (tool pairs kept whole
   by `history_before_user_originated_turn`, upstream's own cut). The child is a fresh ROOT:
   `_branched_from` = the chat root (so the console history row nests under it),
   `parent_session_id` unset (a branch is not a compression descendant). No partial prefix
   can be produced: the cut is on the full projection or refused.
2. **The child starts uncompressed.** It carries the display rows, not the model projection
   (summary + tail); its own first turn recompresses it if needed. Same behaviour as the TUI,
   one rule for both surfaces.
3. **Atomicity is upstream's seed protocol + the receipt order:** seed in bounded chunks;
   `_branch_seed_persisted` last; the console receipt (`_receipt_key` → `get_meta`) written
   only after the seed flag. A crash leaves a child with no receipt and `status` answers
   `not_recorded`; the same `operation_id` re-applies idempotently (the branch idempotency
   registry returns the same child). A child with an unset seed flag is garbage the retry
   overwrites.
4. **No upstream private reach.** The seed write goes through public `SessionDB` methods in
   the fork-only `hermes_state_history_controls.py`; if `_persist_branch` is the only way, that
   is a door request (ledger row), not an import — the review already flagged this module's
   six private dependencies.

### Files and symbols (all on the PR #7 landing)

- `agent_runtime/operator_history.py` — `_target` (lineage read), `_plan` (drop the
  compressed refusal; keep it for a target that is not in the lineage at all),
  `apply_operator_history` (seed → flag → receipt order).
- `hermes_state_history_controls.py` — the branch seed writer on public `SessionDB`.
- Launcher: none (the refusal reason disappears; the console already draws
  `_branched_from`).

### Stages, tests, killing mutation

| stage | test | killing mutation |
|---|---|---|
| S1 lineage target | compressed fixture (root `end_reason='compression'` → tip): preview no longer refuses; child rows byte-equal the lineage rows before the target (review gap "no test for `branch_compressed_history_unavailable` or a real compaction carrier") | drop `include_ancestors=True` → archived rows missing from the child → red |
| S2 atomicity | injected failure mid-seed: no receipt, `status` `not_recorded`, retry yields one child | write the receipt before the seed flag → red |
| S3 lifecycle | source untouched (digest), child `_branched_from`=root, `parent_session_id` None, no lineage walk reaches the child | set `parent_session_id` on the child → `include_ancestors` read of the root returns the child's rows → red |

### Owner question

- Confirm decision 2 (child starts uncompressed, as the TUI does) over "inherit the summary +
  tail" (smaller first turn, loses re-expandable history).

---

## D2.04 = L5.04 — A retried turn carries no lineage (`retry_of`)

**Verdict: PLAN.** Size: ~90 production lines, ~150 test lines, 3 stages + launcher.

### What the code says

- The launcher's Retry (`agent_console_send_lane.dart::retryInterruptedTurn`) re-enqueues the
  original text through the normal send lane with a fresh `turn_request_id`; hermes sees an
  unrelated send.
- `agent_runtime/chat_turn.py::normalize_chat_message` is the door: the honoured key set is
  `CHAT_MESSAGE_PARAMS` (the manifest advertises it and a drift test walks it); each param
  lowers to one argv flag of `harness mission-chat message`.
- The turn record (`mission_chat_turns/journal.py::persist_mission_chat_turn`) accepts only
  whitelisted metadata: `records.py::_safe_journal_metadata` / `_JOURNAL_TEXT_FIELDS`.
- Terminal reply-less turns are projected as marker rows by
  `persona_chat_history/markers.py::_terminal_turn_marker_rows` from `TERMINAL_TURN_MARKERS`
  (`interrupted`, `budget_exhausted`), each carrying `client_message_id`, `turn_id`,
  `settled_state`; it reads the whole journal (`records`) for the session.
- `states.py::_JOURNAL_TRANSITIONS` gives a terminal record no transition but itself and
  `native_committed`; `TERMINAL_TURN_STATES` is what a repair sweep must never flip.

### The design decision (the lane's question)

**`retried_as` is projected from the new turn alone; the old record is never written.** The
old record is terminal; a write-back is a second writer of a settled state and would need a
new legal transition. The projection already holds every record of the session when it builds
the marker row, so `retried_as` is a lookup (`retry_of == this client_message_id`), not a
write. One stored field, both rows on the wire.

Rules:

- `retry_of` (the original `client_message_id`) REQUIRES `session_id`: a retry is always in an
  existing root. Door refusal `ChatTurnInvalid("retry_of_requires_session")`.
- The admit phase validates it names a record of THIS root whose state is a key of
  `TERMINAL_TURN_MARKERS` (`interrupted`, `budget_exhausted`); anything else is refused
  `ExecutionState.REJECTED` with `ChatErrorKind.CHAT_TURN_RETRY_TARGET_INVALID =
  "chat_turn_retry_target_invalid"` (one new error_kind; wire addition). A retry of a completed
  turn is "regenerate", out of scope.
- The value is stamped at the write-ahead (`run.py::_write_ahead` metadata) and whitelisted in
  `_JOURNAL_TEXT_FIELDS` (`"retry_of": 240`); it survives every later persist because the
  journal merges `prior`.
- Projection: the operator row of the new turn carries `retry_of`; the marker row of the old
  turn carries `retried_as` (the newest retry's `client_message_id`; a retry of a retry chains
  by following `retry_of`).
- The busy-root queue (`chat_root_send_queue`) persists the send's params, so a retry queued
  behind a running turn keeps its `retry_of` for free; assert it.

### Files and symbols

- `agent_runtime/chat_turn.py` — `CHAT_MESSAGE_PARAMS` + `retry_of`; `normalize_chat_message`
  lowers `--retry-of`; door rule.
- `hermes_cli/harness_parts/parser/persona.py` — `--retry-of` on `mission-chat message`.
- `hermes_cli/harness_parts/persona/chat_turn_commit/admit.py` — validation against
  `mission_chat_turn_records(session_id=root)`; `run.py::_write_ahead` metadata.
- `agent_runtime/mission_chat_turns/records.py::_JOURNAL_TEXT_FIELDS` — `retry_of`.
- `agent_runtime/mission_chat_outcome.py` — `CHAT_TURN_RETRY_TARGET_INVALID`.
- `agent_runtime/persona_chat_history/markers.py::_terminal_turn_marker_rows` — `retried_as`;
  the operator-row builder in `persona_chat_history/messages.py` — `retry_of`.
- Launcher half (wire: `retry_of` param; `retry_of` / `retried_as` on rows):
  `agent_console_send_lane.dart::retryInterruptedTurn` sends `retry_of:
  marker.client_message_id`; `agent_console_turn_interrupted_content_renderer.dart` draws
  "retried as …" from the row, dropping its local memory.

### Stages, tests, killing mutation

| stage | test | killing mutation |
|---|---|---|
| S1 door + journal | `tests/agent_runtime/test_serve_rpc_chat_turn.py` (param → argv, manifest drift), `tests/agent_runtime/test_mission_chat_turn_journal*.py` (record carries `retry_of` after a terminal persist) | drop `retry_of` from `_JOURNAL_TEXT_FIELDS` → absent on the record → red; drop the session rule → `retry_of` without `session_id` accepted → red |
| S2 projection | marker test beside `test_terminal_turn_settlement.py`: interrupted marker carries `retried_as`, new operator row carries `retry_of` | build `retried_as` from the marker's own record instead of the lookup → red |
| S3 queue | busy-root queue entry replays `retry_of` | strip it from the persisted params → red |

### Risks

- A retry target that was garbage-collected from the journal (the END publish's `"absent"`
  case) is refused `retry_target_invalid`; the launcher should fall back to a plain send,
  not fail the click. Name it in the launcher row.
