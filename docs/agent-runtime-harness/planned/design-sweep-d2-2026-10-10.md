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
| D2.05 = L5.09 | PLAN | `runtime.settles.list` / `.rearm` (console tier) + `harness serve settles`; re-arm = `undelivered → pending`, attempts 0, same `settle_id`, `rearm_count` stamped |
| D2.06 = L4.30 | DROP | the mechanism landed: `persona_chat_turn` overlay carries `running_work` at start (h-turn1 C2) and `running_work_frame` ships at end; the yield docstring is what is stale |
| D2.07 = L1.25 | PLAN | `worker_app_functions.create_agent` is the one native factory chokepoint: resolve `permission_options_for_chat` there, keyed `profile:<name>` until an instance owns the route |
| D2.08 = L2.26 | PROGRAM-EXISTS | `instance-conversations-2026-10-01.md` § Remaining before cutover; next stage is the parity qualification, with D2.07 as its permission arm |

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

---

## D2.05 = L5.09 — Undelivered chat-turn settles have no operator verb

**Verdict: PLAN.** Size: ~140 production lines (store 30, RPC 60, CLI 50), ~180 test lines,
3 stages + a launcher diagnostics stage.

### What the code says

- `agent_runtime/chat_turn_settles.py` is the durable outbox: `SettleRecord` with
  `state ∈ {pending, acked, undelivered}`, `attempts`, `next_attempt_at`,
  `undelivered_reason ∈ {retry_budget_exhausted, no_listener}`; `settle_id_for(session_id,
  client_message_id)` is DETERMINISTIC (one settle per turn — a "new settle_id" on re-arm is
  not possible and would break the launcher's `settle_ack` by `client_message_id`).
  `note_push` moves a record to `undelivered` after `MAX_ATTEMPTS = 6` (2–32 s backoff) or
  `NO_LISTENER_SECONDS = 3600` with nobody attached; `ack_settle` accepts
  `undelivered → acked`; `list_settles(state=)` and `read_settle` are the reads;
  `_write` is the one writer (versioned receipt).
- The serve's pusher (`hermes_cli/harness_parts/serve/settle_push.py::_push_due_settles`)
  pushes `due_settles()` = pending records whose `next_attempt_at` has passed, every
  `SETTLE_PUSH_TICK_SECONDS = 1.0`, and logs `serve_settle_undelivered` once; `_op_settle_ack`
  is the only inbound settle op (local launcher only; refused on a gateway connection).
- The read-tier pattern for a serve twin is `serve_rpc/health.py::_runtime_health` (no
  params, a fork payload builder); `harness health` is registered in
  `hermes_cli/harness_parts/parser/machine.py`.

### The design decisions (the lane's question: what does re-arm do?)

1. **Re-arm is `undelivered → pending`, `attempts = 0`, `next_attempt_at = now`,
   `undelivered_reason = None`, same `settle_id`,** plus two new fields `rearm_count` (+1) and
   `rearmed_at`. Resetting attempts is what makes the record DUE again under the pusher's own
   rule; a re-arm that kept `attempts = 6` would be undelivered again on the first push. The
   history is kept by the count, not by a second record. `acked` is never re-armed (the
   launcher already took it); `pending` re-arm is a no-op returning the record.
2. **One new store function** `rearm_settle(settle_id) -> SettleRecord | None`, under the
   same per-settle lock `_write` uses (`locks.py` `chat_turn_settles/<id>.lock`), the only
   writer of this transition. The pusher needs no change: the next tick (≤ 1 s) pushes it.
3. **Two serve methods, console tier** (a settle names a session and a turn; `read` is a
   paired read device): `runtime.settles.list` params `{state?}` → `{counts: {pending,
   undelivered, acked}, settles: [frame fields + state, attempts, undelivered_reason,
   rearm_count, next_attempt_at]}`; `runtime.settles.rearm` params `{settle_id}` or
   `{client_message_id, session_id?}` (the same two addressings `_op_settle_ack` accepts) →
   the updated record, `{"rearmed": bool}`. The count the row wants "connections-adjacent"
   rides the list result; nothing is added to `runtime.health` (its contract is `harness
   health --json` verbatim) or to any frame envelope.
4. **CLI verbs**, RPC-first per the standing rule (argv is the fallback): `harness serve
   settles [--state S] [--json]` and `harness serve settles rearm <settle_id|client_message_id>
   [--session-id]`, both thin over the same two functions, so the CLI contract fixture is
   re-dumped once and the launcher re-vendors once.

### Files and symbols

- `agent_runtime/chat_turn_settles.py` — `rearm_settle`, `SettleRecord.rearm_count /
  rearmed_at` (schema version 2; v1 records read with 0/None), `settle_counts()`.
- `agent_runtime/serve_rpc/settles.py` (new) — the two methods; registered in the manifest
  with their tiers (`registry.method`).
- `hermes_cli/harness_parts/parser/machine.py` — the `serve settles` subcommands;
  `hermes_cli/harness_parts/serve/commands.py` — the handlers.
- Launcher half (new methods): the diagnostics panel lists undelivered settles and offers
  Re-arm; it keeps acking by `client_message_id` as today. Launcher queue row.

### Stages, tests, killing mutation

| stage | test | killing mutation |
|---|---|---|
| S1 store | `tests/agent_runtime/test_serve_settle_push.py`: an undelivered record re-armed is pushed on the next tick; `rearm_count` 1; acked is refused | keep `attempts` on re-arm → the first push marks it undelivered again → red |
| S2 RPC | `tests/agent_runtime/test_serve_rpc_*` manifest tier test (both console) + list/rearm round trip through the in-memory transport | register `list` at `read` → tier test red |
| S3 CLI | CLI contract fixture + one argv round trip | — |

### Risk

- A record re-armed with no launcher attached lives one more `NO_LISTENER_SECONDS` hour before
  it is undelivered again; the panel should say so. No owner question.

---

## D2.06 = L4.30 — Publish turn start/end as state patches so no core build runs during a turn

**Verdict: DROP** — the mechanism the row asks for already landed, under another name, and the
row's evidence is a docstring that was not updated.

### The evidence

- `agent_runtime/stream/frames.py::persona_chat_turn_frames` (plan h-turn1 §2 C2, 2026-10-05,
  `patch_coverage.PERSONA_CHAT_TURN_CAPABILITY`): a turn batch — `persona_chat.turn_started`,
  `.projected`, `.turn_ended` — is handed to a declaring subscriber as ONE
  `persona_chat_turn` frame per root carrying the sections the turn moved, and
  `_with_running_work` puts the serve's `running_work` section in it (read last, on the serve,
  because its lanes are in-process). `stream/build.py::_turn_batch_frames` yields only the
  overlays when the whole room declares the token — "no core, no job, no liveness".
- `agent_runtime/stream/session.py::flush` ships `running_work_frame` alone when a batch ends
  a turn (2026-10-01), before any core.
- The launcher declares the token (`mission_stream_lane.dart`: `'persona_chat_turn'`), so on
  the operator's own console the start row rides an overlay, not a core build.
- `tests/agent_runtime/test_stream_turn_section.py` and
  `test_stream_running_work_on_turn_end.py` are the gates; the row's cited test
  (`test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane`) pairs a device
  client that does not declare the token, so it exercises the demote core — the fallback,
  by design ("every mixed pair degrades to today's wire").

What is stale is `agent_runtime/snapshot_turn_yield.py`'s docstring ("between those windows
the stream lane's builds are what carry the turn's own start row … so they must still
happen during a turn") and the yield rule it justifies: with every attached subscriber
declaring `persona_chat_turn`, a build may stand aside for the WHOLE admitted turn, not only
its hot windows. That is a fix-lane row, not a design: one predicate (`accepted_fold_entities`
∋ the token for every subscriber) widening the hot-window test in `_turns_admitted`, with
`test_snapshot_turn_yield.py` as the gate (mutation: drop the predicate → a build leads
mid-turn with all subscribers declaring → red). Filed as a runtime-queue row from this lane's
report; the L4.30 row is deleted on landing.

---

## D2.07 = L1.25 — The native conversation engine has no permission mode

**Verdict: PLAN**, as the permission stage of the cutover remainder (D2.08). Size: ~100
production lines, ~160 test lines, 2 stages.

### What the code says

- The operator lane resolves "what may this turn do" ONCE in
  `agent_runtime/tool_permissions.py::permission_options_for_chat(persona, session_id=…)`:
  the `ChatToolPermissionStore` record keyed `_key(persona_id, session_id)` wins when it has
  an opinion, else `default_permission_mode()`; the answer's `blocked_tool_names` is
  `extra_blocked_tools_for_permission_mode(mode)`, which already includes every Launcher app
  function whose entry is mutating (`launcher_app_functions` entry `read_only is False`, or
  `requires_confirmation` when the mark is absent). The runner applies it through
  `AgentRunRequest.blocked_tool_names` → `profile_runner/execute.py::_blocked_tool_names_for_run`.
- The native engine builds its agent at ONE fork site: `tui_gateway/server.py` calls
  `agent_runtime/conversations/worker_app_functions.py::create_agent(AIAgent, sid, session,
  **kwargs)`, which already rewrites `kwargs["enabled_toolsets"]` to add the app-functions
  toolset when the Launcher link answers `refresh_app_function_tools`. Nothing in that path
  consults a permission; a native conversation gets every listed app function.
- The native route carries `ConversationScope(actor, client, profile)` and a route id (the
  conversation `session_id`); a profile conversation has no persona, an instance conversation
  (the cutover) has one.

### The design decisions

1. **Resolve in `create_agent`, nowhere else.** It is the chokepoint for every native agent
   build (eager and deferred), it runs inside the worker where the toolset is decided, and it
   already edits the kwargs. It reads `permission_options_for_chat` and passes
   `blocked_tool_names` (and the HUD's `permission_mode`) into the factory kwargs the same way
   the runner does; `read_only` therefore blocks the same app functions on both lanes by the
   same table.
2. **The key (the lane's question).** The store key is `(persona_id, session_id)`. For an
   instance conversation the persona is the instance's persona and `session_id` is the native
   route id — the SAME record an operator sets with `runtime.persona.permission.set` on that
   chat. For a profile conversation (no persona) the persona slot is the typed sentinel
   `profile:<profile name>` and `session_id` the route id; `permission.preview/set` accept
   that sentinel so a profile conversation can be held at `read_only` too. One store, one
   resolver, two key spellings, both typed (`conversations/model.py::permission_key(scope,
   route)`).
3. **Where the worker learns it.** `ChatToolPermissionStore()` reads one JSON file under the
   runtime store root; the worker child inherits the root through
   `tools/environments/local.py::served_profile_child_env`. Stage 1 asserts the child resolves
   the same path as the serve (a receipt on `session.create`), or the test is red before any
   permission test can pass.
4. **Turns-bounded grants** (`consume_turn`) are consumed by the conversation `send`
   (`ConversationService.send`, after `store.admit`), not by the worker — one consumer per
   lane, as the operator lane does in its admit phase.

### Files and symbols

- `agent_runtime/conversations/worker_app_functions.py::create_agent` — resolve + kwargs.
- `agent_runtime/conversations/model.py::permission_key` — the two spellings.
- `agent_runtime/conversations/service.py::send` — `consume_turn`.
- `agent_runtime/serve_rpc/console_operations.py` `runtime.persona.permission.preview/set` —
  accept the `profile:` sentinel (validation in `tool_permissions`).
- Launcher: none for stage 1 (the HUD already renders `permission_mode`); the Console's
  permission control binds to the native route in the cutover.

### Stages, tests, killing mutation

| stage | test | killing mutation |
|---|---|---|
| S1 resolve | `tests/agent_runtime/test_native_conversation_worker.py`: a route held `read_only` builds an agent whose `blocked_tool_names` equals `extra_blocked_tools_for_permission_mode("read_only")`, mutating app functions included; the child's store path equals the serve's | ignore the record in `create_agent` → the blocked list is empty → red |
| S2 consume | a 2-turn `read_only` grant lapses after two native sends | consume in the worker too → lapses after one → red |

### Owner question

- Should a PROFILE conversation (no persona) honour `default_permission_mode()` at all, or
  stay unbounded as today until an instance owns the route? Recommend: honour it (one
  default, both engines).

---

## D2.08 = L2.26 — Instance-conversation cutover remainder

**Verdict: PROGRAM-EXISTS.** Plan:
`docs/agent-runtime-harness/planned/instance-conversations-2026-10-01.md`, § "Remaining before
cutover" (the foundation landed 2026-10-02; the resident-identity repair and native model
controls landed 2026-10-03). Next stage, in the plan's words: rich model/skills/context/
attachment and recovery parity with the Direct transport, then the neutral Launcher
contracts and current-account history, qualified end to end before any Launcher glue or the
profile worker retires. This sweep adds two arms to that stage without new design:
D2.01 (reviewed files — the "attachment parity" item) and D2.07 (permission mode). The row
stays; it is the program's pointer. No owner question.
