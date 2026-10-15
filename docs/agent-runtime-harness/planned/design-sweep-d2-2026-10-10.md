# Design sweep D2 — fourteen rows the fix lanes returned as too big (2026-10-10)

**Status:** IN PROGRESS — per-row entries and domain queues own remaining work. D2.01 and D2.04 producers are built; their Launcher consumers remain queued.

Lane fable-design-D2. Rows: `lanes-1011d/D2-rows.md` (the queue rows carry the claims).
One section per row, verdict first: **PLAN** (implementation-ready for an Opus lane),
**PROGRAM-EXISTS** (a plan already owns it), **INVESTIGATION** (the cause is unknown; the
protocol that names it), **DROP** (stale or wrong, with the evidence). Code is cited by file
and symbol. Where rows share a mechanism the design is written once and the others point at
it. House format: `busy-root-queue-2026-10-10.md`.

Verdict table (filled as batches land):

| row | verdict | one line |
|---|---|---|
| D2.01 = L2.09 | PRODUCER BUILT | `d3ce04dfc1` + `5a374d46ec`, recovery qualification `75da78162d`; Launcher C019 consumes capability v3 |
| D2.02 = L2.07 | PLAN | `provider_submitted` is set before the provider is resolved, so a no-provider turn settles `outcome_unknown`; refuse pre-flight, classify by phase after |
| D2.03 = L5.03 | PLAN (gated on PR #7) | branch the LINEAGE display rows the way upstream's `/branch` already does; the child is a root, never a compression descendant |
| D2.04 = L5.04 | PRODUCER BUILT | `e09b0e15e2` + `052c76306d`, follow-up `f1d1affc66`; Launcher send/render consumer remains queued |
| D2.05 = L5.09 | PLAN | `runtime.settles.list` / `.rearm` (console tier) + `harness serve settles`; re-arm = `undelivered → pending`, attempts 0, same `settle_id`, `rearm_count` stamped |
| D2.06 = L4.30 | DROP | the mechanism landed: `persona_chat_turn` overlay carries `running_work` at start (h-turn1 C2) and `running_work_frame` ships at end; the yield docstring is what is stale |
| D2.07 = L1.25 | PLAN (redesigned 2026-10-10, fable-design-D2.07b) — S2 (the `profile:<name>` operator subject) and decision 8 (`facts.permission`) BUILT by wave w1015b-con-x; S1a/S1b (the worker bind that enforces it) still owed | the serve resolves per turn in `ConversationService.send` (subject `profile:<name>`, session = route id) and sends the typed MODE to the worker over a fork method `eternia.permission.bind`; the worker binds the block inside the existing per-turn `bind`/`reset` seam; no upstream edit |
| D2.08 = L2.26 | PROGRAM-EXISTS | `instance-conversations-2026-10-01.md` § Remaining before cutover; next stage is the parity qualification, with D2.07 as its permission arm |
| D2.09 = L3.07 | PLAN | the fork modules already exist (`tui_gateway/session_execution.py` and five siblings); two MOVE clusters shrink 7 files to one-line call sites, three files are door PRs, not moves |
| D2.10 = L4.25 | PLAN | four read-tier twins over the existing payload builders; pixels as the `runtime.media.get` block shape, bounded by `withinConsoleBudget`; one MOVE first |
| D2.11 = L4.26 | PLAN — hermes half BUILT 904edb1105 + 53b623e684 + e2a5bec6bc (build-1011-C4); launcher row owed | six console-tier twins in `serve_rpc/board.py` over `BoardStore`, the office write twin as template; no fold in this lane |
| D2.12 = L2.28 | PLAN | the THIRD whole-document family files the class: `realm_sync/document_family.py` carries level, map and prefab; prefab is one descriptor |
| D2.13 = L1.27 | PROGRAM-EXISTS | `eternia-lens-in-hermes.md` §5 L0; all four §6 rulings given 2026-10-02; nothing under `agent_runtime/lens/` yet |
| D2.14 = L1.30 | PROGRAM-EXISTS | `phone-gate-to-zero-plan-2026-09-30.md`; G2/G3/G6 landed (gate 164 → 16 before G6); next is a re-take, then G5 on the owner's D2–D5 |

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
| S1 contract — BUILT d3ce04dfc1 (+ f59b371f11) | `validate` files arm, `Refusal` members, capability v3 | `tests/agent_runtime/test_conversation_worker_protocol_input.py` (+ `test_native_conversation_rpc.py` capability golden) | drop the per-file bound → the 4 MiB+1 file passes `validate` → red; remove `files` from the key set → old-shape prompt accepted → red |
| S2 submit — BUILT 5a374d46ec | `submit` attaches each file (`file.attach`/`pdf.attach` by media type) then submits | `tests/agent_runtime/test_native_conversation.py` (scripted peer) | skip the `attached` check → a refused attach still submits → red; attach after submit → order assertion red |
| S3 recovery — BUILT 45965f78f9 | digest covers files; `observe_execution` round trip | `tests/agent_runtime/test_native_conversation_roundtrip.py` | exclude `files` from `digest(payload)` → resend with changed file bytes is not `CONFLICT` → red |
| S4 launcher | C019: composer Files action gated on capability `files` | launcher | — |

Built by lane build-1011-C3, where the code differed from this plan: limits are the launcher
composer's (`AgentAttachmentLimits`: 8 files, 256 KiB each, 512 KiB total — owner ruling);
`files` is OPTIONAL (absent = none) so the shipped launcher's `{text, images}` packet keeps
working; S1's tests live in `test_conversation_prompt_files.py` (the named file is a pipe test);
S3 runs against a real native worker.

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

**Build (lane build-1011-B3):** S0+S1 BUILT `7fbd3688e6` (the phase fact is
`TurnCommit.provider_request_started`, set beside the mark — `TurnPhaseMarks` forbids
branching on a mark; a resend replays the unavailable pair). S2 NOT BUILT per the owner
ruling below (phase rule only). S3 OWED: operator live proof; launcher copy row filed.

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

**Build (lane build-1011-B3):** S1 BUILT `e09b0e15e2`, S2 BUILT `052c76306d` (operator row is
`curation._OperatorCurator`, and `operator_channels/history_messages.py` carries both keys),
S3 BUILT `f1d1affc66`. Launcher half filed as a launcher queue row.

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

**Build (lane build-1011-B3):** S1 BUILT `bed4892f54` (fields additive under schema v1 —
`read_versioned_receipt` refuses a foreign version, so v2 would orphan every v1 record; the
no-listener hour restarts at the re-arm), S2 BUILT `7308e844a9`, S3 BUILT `05d7589b5e`.
Launcher diagnostics half filed as a launcher queue row.

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

**Verdict: PLAN (redesigned 2026-10-10, lane fable-design-D2.07b)**, as the permission arm of
the cutover remainder (D2.08). Size: ~200 production lines, ~310 test lines, 3 stages. No upstream
file is edited; the two unknowns the build lane left are answered below.

### Build lane build-1011-C2 (2026-10-11): RETURNED — the record

Neither stage of the first design was built. The code refuted it three ways: the worker never
holds the route id (`session.create` / `prompt.submit` params are upstream contracts with
`extra="forbid"`); a factory-time resolve freezes the mode for the agent's life while the operator
lane resolves per turn; `AIAgent` takes no `blocked_tool_names`. The lane pointed at the per-turn
`worker_app_functions.bind` / `reset` seam. This section is the redesign it asked for.

### What the code says (the two unknowns, answered)

**1. The eternia-harness plugin loads in the native worker — yes, by the same door as everywhere.**
`plugins/eternia-harness/plugin.yaml` is bundled, `kind: backend`;
`hermes_cli/plugins_discovery.py::gate_manifest` returns `load_now` for a bundled backend with no
`plugins.enabled` entry needed. `agent/agent_init.py::_load_tools` calls `discover_plugins()` on
EVERY `AIAgent` construction, and the worker constructs its agent through
`tui_gateway/server.py::_make_agent` → `worker_app_functions.create_agent(AIAgent, …)`. The bundled
directory is `hermes_cli/plugins.py::get_bundled_plugins_dir` = `<repo>/plugins`, the same tree the
worker runs from (`conversations/worker.py::start_worker` spawns `sys.executable -m
agent_runtime.conversations.worker_entry` with `cwd` = the repo root). Both tool-block doors the
plugin owns receive the agent's session id: `brief_tool_descriptions` (`llm_request` middleware) gets
`session_id=agent.session_id` from `agent/turn_api_request.py`, and `refuse_tool_call`
(`pre_tool_call`) gets it from `agent/inline_tool_executors.py::tool_hook_ids`. The construction door
(`tool_blocks.prune_agent_tools`) and `reprune_turn_agent` are NO-OPs in the worker:
`current_persona_turn_agent()` is None there, so the persistent native agent keeps its full tool list
and only the wire and the call are filtered — which is exactly what a mode that changes per turn needs.
One exposure, shared with the operator lane: a profile `config.yaml` with `plugins.disabled:
[eternia-harness]` removes both doors. Decision 5 turns that into a refusal.

**2. The worker does NOT reliably see the serve's store root — so the worker never reads the
permission store.** `agent_runtime/paths.py::store_root` → `resolution.py::resolve_runtime`:
`HERMES_AGENT_RUNTIME_ROOT` env wins, else `<HERMES_HOME>/config.yaml agent_runtime.store_root`,
else `<platform default home>/agent-runtime`. The worker's env is `tools/environments/local.py::
served_profile_child_env(target_home=<profile home>)`: `os.environ.copy()` (so an env pin IS
inherited) but `HERMES_HOME` is rewritten to the PROFILE home. A serve whose root came from the
CONFIG layer (the machine root anchor `hermes_cli/harness_parts/serve/session.py::
_boot_anchor_and_skills` writes it into the platform-default home's config) therefore spawns a worker
that resolves the profile home's config — unset — and lands on the default root: a different
`tool_permissions.json`. Only the Launcher's env pin (`root_anchor.py`: "the Launcher pins
HERMES_AGENT_RUNTIME_ROOT on every serve child") makes the two agree; a hand-started `hermes harness
serve` does not. Resolution therefore happens in the SERVE, which owns the store, the route and
`runtime.persona.permission.set`; the worker receives a typed MODE per turn.

**The seams that already exist.** `ConversationService.send` (fork-owned) runs once per turn, holds
`live.operations`, and already calls `live.app_functions.bind(execution_id, …)` before
`prompt.submit`. The worker already registers fork methods through the public
`tui_gateway.server.register_method` (`conversations/worker_skills.py::install`, contracts declared
into the fork-owned `tui_gateway/contract_catalog_data.py` by `scripts/gen_contract_catalog.py`).
`prompt_turn.py::_prepare_turn_input` (upstream; the fork hunk is ledger row `tui_gateway/
prompt_turn.py`, "binds and resets the existing Launcher link in the native turn context") calls
`worker_app_functions.bind(sid, session)` at the start of EVERY turn and `reset(token)` in the
finally; it stores whatever `bind` returns. `session_execution.admit` (fork-owned) writes
`session["native_execution"] = {"id": execution_id, …}` inside the turn claim, before the turn
thread starts. `tool_blocks.bound_tool_block` binds a block by session id, read by both doors
through `blocked_tools_for(session_id)`. `permission_options_for_chat(persona, session_id=…)` reads
only `persona.id`; `ChatToolPermissionStore` keys `persona_id::session_id`.

### The design decisions

1. **The serve resolves, per turn, in `ConversationService.send`.** After `store.admit` says
   `admitted`, before `submit`: `subject = permission_subject(route)` and `options =
   permission_options_for_subject(subject, session_id=route.id)`. One resolver for both lanes:
   `permission_options_for_chat(persona, …)` becomes a one-line delegate to the new
   `permission_options_for_subject(persona.id, …)` in `agent_runtime/tool_permissions.py`. The store
   key's `session_id` is the ROUTE id (`conversation-…`), the id the Launcher holds and the operator
   names — stable across worker restarts, unlike the native sid.
2. **The subject (the key's first half).** `conversations/model.py::permission_subject(route) -> str`
   is the one spelling: today `f"profile:{route.profile}"` (`PROFILE_SUBJECT_PREFIX = "profile:"`
   lives in `tool_permissions`); when D2.08 lets an instance own a route, that function returns the
   instance's persona id and nothing else changes. Owner ruling 2026-10-10: a PROFILE conversation
   honours `default_permission_mode()` — which is what the resolver already does for a subject with
   no record or a no-opinion record.
3. **What crosses to the worker is the MODE, not the list.** The serve calls a new fork worker method
   `eternia.permission.bind {session_id: native_id, execution_id, permission_mode}` before
   `prompt.submit`. The worker derives the block itself with
   `extra_blocked_tools_for_permission_mode(mode)` at bind time, because that table reads the
   REGISTERED Launcher catalog of the process it runs in (`launcher_app_functions.
   mutating_app_function_tools` reads `_state.registered`) — the worker's catalog is the live one
   (refreshed from the Launcher at `create_agent`); the serve's may be empty when no operator chat
   has run. Same table, both lanes, evaluated where the catalog is.
4. **The worker binds per turn inside the existing `bind` / `reset` seam.** New fork module
   `agent_runtime/conversations/worker_permissions.py`: `install()` (contract + `register_method`),
   a locked `_pending: dict[sid, TurnPermission(execution_id, mode)]` the RPC handler writes, and
   `bind(sid, session) -> token | None` / `reset(token)`. `worker_app_functions.bind(sid, session)`
   returns a `TurnScopes(launcher, permission)` composite and `reset` undoes both — the upstream
   `_prepare_turn_input` hunk is untouched (it only stores and hands back the token). `bind` is a
   no-op unless `enabled(session)` (a direct TUI session is never touched). For an enabled session it
   pops the pending record whose `execution_id` equals `session["native_execution"]["id"]` and binds
   the block through a token pair added to `tool_blocks` (`bind_tool_block(names, session_ids) ->
   BlockToken`, `reset_tool_block(token)`; `bound_tool_block` is rewritten over them — one write path)
   with `session_ids=(sid, session["session_key"])`: `session_key` is what `_make_agent` passes as
   `session_id`, so `agent.session_id` — the id both hooks look up — hits `_by_session` from any
   thread (the `ContextVar` fallback does not reach tool-pool threads; `agent/tool_executor.py` copies
   no context, the operator lane has the same shape).
5. **Fail closed, with a positive runtime check.** No pending record for this execution (or a stale
   one) binds the `read_only` block and logs `permission_bind_missing` — nothing the runtime failed to
   read hands out more capability than the operator wrote (the rule `default_permission_mode`
   already follows). If `hermes_cli.plugins.has_middleware("llm_request")` or `has_hook("pre_tool_call")`
   is False at bind time for an enabled session, `bind` raises `RuntimeError("tool-block doors are
   not installed")`: the turn fails visibly rather than running unfiltered. That raise is the gate
   that proves the plugin is present at runtime, not a source walk.
6. **`permission.set` mid-conversation takes effect on the next turn** by construction: every `send`
   re-reads the store; the agent is never rebuilt; the previous turn's token was reset in
   `_prepare_turn_input`'s finally. **Turns-bounded grants** are consumed ONCE, by the serve, after
   `submit` returned `streaming` (a turn that was never admitted spends nothing), mirroring
   `persona_runtime.py`'s single `consume_turn` after the run. The worker never consumes.
7. **The operator surface accepts the profile subject.** `runtime.persona.permission.set/preview`
   (`serve_rpc/console_operations.py::_permission` → `hermes_cli/harness_parts/persona/
   inspect_commands.py`) resolve `persona_id` through `chat_target._persona_by_id`, which refuses an
   unknown id. A subject starting with `profile:` skips the persona lookup, requires the profile to
   exist (`hermes_cli.profiles.get_profile_dir`), writes the record under the subject, and previews
   `{mode, source, blocked_tool_names, turns_remaining, expires_at}` only — a profile conversation has
   no persona toolset table to diff.
8. **The conversation `facts` carry the resolved permission** (`ConversationService._facts`, a
   fork-owned RPC result, not the parity envelope): `permission: {mode, source, turns_remaining,
   expires_at}` from the same resolver without consuming — what the Console's permission control
   binds to in the cutover.

### Files and symbols (fork-owned only)

- `agent_runtime/tool_permissions.py` — `PROFILE_SUBJECT_PREFIX`, `profile_permission_subject(name)`,
  `is_profile_subject(subject)`, `permission_options_for_subject(subject, *, session_id, …)`;
  `permission_options_for_chat` delegates.
- `agent_runtime/tool_blocks.py` — `BlockToken`, `bind_tool_block`, `reset_tool_block`;
  `bound_tool_block` over them.
- `agent_runtime/conversations/model.py` — `permission_subject(route)`.
- `agent_runtime/conversations/worker_permissions.py` (new) — `METHOD = "eternia.permission.bind"`,
  `TurnPermission`, `declare_contracts`, `install`, `bind`, `reset`, `_pending`.
- `agent_runtime/conversations/worker_app_functions.py` — `TurnScopes`; `bind`/`reset` compose.
- `agent_runtime/conversations/worker_entry.py`, `in_process_peer.py::_install_gateway_methods` —
  call `worker_permissions.install()` beside the app-functions install.
- `agent_runtime/conversations/live.py` — `LiveConversation.bind_permission(execution_id, mode)` →
  `peer.call(METHOD, …)`.
- `agent_runtime/conversations/service.py::send` — resolve, bind, submit, consume; `_facts` —
  `permission`.
- `tui_gateway/contract_catalog_data.py` — regenerated by `scripts/gen_contract_catalog.py`
  (`tests/tui_gateway/test_contract_catalog.py::test_the_committed_catalog_is_the_live_models` is the gate).
- `hermes_cli/harness_parts/persona/inspect_commands.py::_cmd_persona_permission_set`,
  `_cmd_persona_tool_diff` — the profile-subject branch.
- Launcher: nothing in S1–S3; the Console binds its permission control to
  `runtime.conversation.facts.permission` and `runtime.persona.permission.set(persona_id=
  "profile:<name>", session_id=<route>)` — one row for `mission-control-queue.md`, filed by the parent.
- Upstream: none. `prompt_turn.py`, `methods_prompt.py`, `contracts/prompt_voice.py` are not edited;
  the existing `bind`/`reset` hunk's ledger row stands as is.

### Stages, tests, killing mutations

| stage | test (`scripts/run_tests.sh <file>`) | killing mutation |
|---|---|---|
| S1a worker bind (~90 prod / ~120 test) | new `tests/agent_runtime/test_native_worker_permissions.py`, no process (the `test_native_worker_app_function_lifetime.py` shape): `install()` registers the method; a bind RPC for `(sid, X, "read_only")` then `worker_app_functions.bind(sid, {"source": "eternia_intelligence", "session_key": K, "native_execution": {"id": X}})` makes `blocked_tools_for(K)` equal `extra_blocked_tools_for_permission_mode("read_only")` with a registered mutating app function in it, and the plugin's own `refuse_tool_call(tool_name="terminal", session_id=K)` returns a block; `reset` empties it; a bind for execution Y with `native_execution` X binds the `read_only` block and logs `permission_bind_missing`; `has_middleware` patched False → `RuntimeError`; a session without `source` is untouched | ignore the pending record in `bind` → empty block → red; drop the `session_key` from `session_ids` → `blocked_tools_for(K)` empty → red |
| S1b serve resolve + carry (~60 prod / ~110 test) | extend `tests/agent_runtime/test_native_conversation.py` over `conversation_support.NativeWorker` (teach the fake `eternia.permission.bind`): a record under `profile:<p>::<route id>` at `read_only` makes `send` call the bind with `read_only` BEFORE `prompt.submit` with the same `execution_id`; no record → `default_permission_mode()`; `permission.set` between two sends changes the second bind's mode; a 2-turn grant lapses after two sends and a refused (`busy`) send consumes nothing; `facts()["permission"]["mode"]` reads the store without consuming | resolve from `default_permission_mode()` only → the first case red; consume before `submit` → the refused-send case red; call `submit` before `bind` → order assertion red |
| S2 operator subject (~40 prod / ~60 test) | `tests/agent_runtime/test_native_console_operations.py`: `runtime.persona.permission.set(persona_id="profile:base", session_id=<route>, mode="read_only", reason=…)` writes the record a following `send` binds; `profile:nope` → refused; preview returns the mode and blocked names and no toolset diff | drop the `is_profile_subject` branch → "persona not found" → red |
| S3 contract catalog + docs (~10 prod / ~20 test) | `scripts/gen_contract_catalog.py` run; `test_every_method_has_a_contract` green; `docs/agent-runtime-harness/05-chat-turn-lane.md` (permission modes: both lanes, one resolver) and `03-transport-and-wire.md` § Native conversation methods (the `eternia.permission.bind` worker method) gain the paragraph | register the method without the contract → `test_every_method_has_a_contract` red |

Landing: one MOVE is not needed (no file moves); one CHANGE commit per stage or S1a+S1b together;
landing gate `scripts/run_tests_bundled.sh tests` once for the batch (`Running the tests.md`).

### Risks

- **Compression mid-turn** rotates the agent onto a child session id; `_by_session` misses and the
  `ContextVar` fallback does not reach tool-pool threads — the same gap the operator lane carries
  (`tool_blocks` docstring). Not widened here; one row for `runtime-queue.md` § Fork-owned if it is
  not already filed.
- **Prompt guidance names a blocked tool.** The native agent's `tools` stay unpruned (decision 4);
  upstream's tool-conditional guidance may mention `terminal` while the wire has dropped it. The
  model gets the typed refusal on a call. Accepted for S1; the cutover's parity qualification
  re-reads it.
- **Catalog freshness.** `mutating_app_function_tools()` in the worker reflects the catalog refreshed
  at `create_agent`; a Launcher that registers a new mutating function later is blocked once the
  catalog refreshes — identical to the operator lane today.
- **Version skew is impossible by construction** (the serve spawns the worker from its own tree), so
  the fail-closed path in decision 5 fires only on a bug; its log receipt is what makes that bug
  visible.
- **In-process worker (phone).** `_install_gateway_methods` installs the same method; the serve and
  the worker are one process there, and the bind travels the same `dispatch` door — covered by the
  S1b test when run with `start_in_process_worker` (an extra parametrisation, ~15 test lines).

### Owner question

- When the per-turn bind is missing or stale (a bug, never a configuration), the plan fails closed to
  the `read_only` block. The alternative is the operator-lane spelling (`bounded`, which blocks
  nothing at this door). Recommend `read_only`: the narrowest tier is the only one that cannot be
  wider than what the operator wrote.

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

---

## D2.09 = L3.07 — Native conversation recovery lives inside ~15 upstream `tui_gateway/` files

**Verdict: PLAN** — a MOVE program of two clusters plus a PR cluster, after the next release
merge lands (the row's own gate). Size: cluster A ~−120/+40 lines across 4 upstream files,
cluster B ~−60/+20 across 3; the PR cluster moves nothing.

### What the code says (the row's premise is half stale)

The fork module that owns recovery EXISTS, as six fork-only files inside the upstream package
directory (not in `upstream/main`): `tui_gateway/session_execution.py` (the execution fence:
`admit`, `submitted`, `uncertain`, `rejected`, `snapshot`, `request_stop`, `interrupt`, `adopt`,
`control`, `checkpoint_guard`), `session_recovery.py`, `session_retirement.py`,
`recovery_history.py`, `recovery_history_delivery.py`, `answer_receipts.py`, plus
`contracts/recovery.py`, `inflight_recovery.py`, `execution_result.py`,
`compute_model_selection.py`. What remains in upstream files is the CALL SITES, and
`git diff upstream/main -- tui_gateway/` shows them in three shapes:

| file (ledger +/−) | fork hunks | shape | disposition |
|---|---|---|---|
| `compute_host.py` (46/5) | `_handle_observe` (12-line method), the `expected_execution_id` interrupt arm, the turn-start `adopt`/`control` block + `_persist_session_row_for_submit` refusal, `@session_construction`, `"observe"` route entry | additive bodies | **MOVE A**: bodies → `session_recovery.handle_observe(server, frame, reply)` and `session_execution.begin_turn(server, sid, session, frame, reply) -> bool`; each site one line |
| `compute_host_bridge.py` (30/7) | `_answer_compute_host_request` (ack/expired protocol), `_compute_host_active` on native execution | mixed: a rewrite of `_relay_compute_host_response`'s tail | **MOVE A** for the new function (→ `answer_receipts`); the 7 deleted lines are a door: upstream's relay drops the ack — PR candidate "answer acknowledgement result" |
| `prompt_turn.py` (39/18) | `submitted`/`rejected`/`uncertain` calls, `admit` on `execution_id`, `reject_if_busy`, cancel-requested completion, `spawn_context_thread` | 1–3-line calls already | **leave**: already one-liners; the 18 deletions are the `reject_if_busy` carry (ledger S2) |
| `session_lifecycle.py` (13/3), `session_reaper.py` (11/2), `session_auto_continue.py` (1/1) | `control(session)` inside the work scope; `close_app_functions`, `discard_history`, `forget_session` on finalize; `observe_only` skips | 1–2-line calls | **MOVE B**: the three finalize calls → one `session_retirement.on_finalize(session)`; the rest stays as single lines |
| `methods_session.py` (17/7) | `observe_only` threading into the resume ctor (`lazy or observe_only`, `record["observe_only"]`, `retire` skipped, `child_history(repair=not observing)`), `@session_construction` on the branch build | in-place flag threading | **door PR**: `observe_only` on `session.resume` upstream (ledger: carry until then) |
| `event_replay.py` (20/0) | `checkpoint(sid, last_seen, include_events)`, `forget_session` over module privates | additive functions on private state | **door PR**: a replay checkpoint API; cannot move without reaching `_replay_lock` |
| `server_requests.py` (11/2) | `AnswerReceipts` hook in `resolve_response(session_id=)` | 3 in-place lines | **door PR** with the bridge's ack result |
| `rpc_dispatch.py` (34/24) | `_enqueue_rpc` (retirement hold on queued work) + `_relay_response` onto the pool | a RESTRUCTURE of upstream's enqueue | **door PR** ("queued RPC work holds retirement"); not movable |
| `contracts/sessions.py` (3/0) | `observe_only`, `expected_execution_id`, `include_events` fields | additive contract fields | rides the `observe_only` PR |

So: seven files get smaller by MOVE; four need upstream doors and are PR rows in the ledger,
not lanes. The ~15-file count in the row includes the fork-only modules themselves.

### Stages (one MOVE commit each, no CHANGE)

| lane | files | done-test | killing mutation |
|---|---|---|---|
| MOVE A (compute host) | `compute_host.py`, `compute_host_bridge.py` → `session_recovery.py`, `session_execution.py`, `answer_receipts.py` | `tests/tui_gateway/test_compute_host*.py`, `tests/agent_runtime/test_native_conversation_worker.py`, `test_native_conversation_roundtrip.py` byte-identical before/after; `[up-fp]` line for the two files drops | — (a move; the existing recovery tests are the gate) |
| MOVE B (lifecycle) | `session_lifecycle.py`, `session_reaper.py` → `session_retirement.on_finalize` | `test_native_conversation_retention.py` | drop `forget_session` from `on_finalize` → the replay buffer survives retirement → red |
| PR cluster | `methods_session.py`, `event_replay.py`, `server_requests.py`, `rpc_dispatch.py` | three ledger rows named `door PR` with the hunk inventory above | — |

Owner question: none. Risk: the daily integration branch resolves these files on every merge;
the MOVE must land between two merges and the rerere cache re-trained after it.

---

## D2.10 = L4.25 — Read twins `runtime.characters.list/status/thumb/sprite`

**Verdict: PLAN.** Size: one MOVE (~120 lines relocated), one CHANGE (~180 production, ~220
test lines), 2 stages + launcher.

### What the code says

- The four argv verbs are thin: `hermes_cli/harness_parts/characters/commands.py`
  `_cmd_characters_list` → `CharacterDraft.list_drafts()` + `_characters_draft_summary` /
  `_characters_installed_rows` (`characters/payloads.py`); `_cmd_characters_status` →
  `CharacterDraft.load(id).status_payload()` (`agent/charsheet/draft/status.py`);
  `_cmd_characters_thumb` → `draft.row_thumb` / `draft.direction_thumb`
  (`agent/charsheet/draft/thumbs.py`), answering a PATH by design (plan A-4: the launcher reads
  the disk) plus `withinConsoleBudget` / `withinOwnSheet`; `_cmd_characters_sprite` →
  `agent/charsheet/draft/installed.py::sprite_payload(slug, include_sheet)`, which inlines
  `spritesheetBase64` (468 KiB on the live sheet) unless `--no-sheet`. `agent/charsheet/` is
  fork-owned. `_characters_emit` adds the draftsman block to every payload.
- The media-style pixel payload already has one shape: `serve_rpc/media.py::_media_get_frame`
  → `{contract, handle, media_type, size_bytes, encoding: "base64", data}` (`MEDIA_CONTRACT`).
- The launcher sites are WARM (`dispatch_argv` through serve; census rows 16–19), so the twin
  buys a typed contract and remote (Mac) readability — a path answer is useless off-box.

### The design decisions

1. **One MOVE first**: `_characters_draft_summary`, `_characters_installed_rows` and the
   draftsman block builder leave `hermes_cli/harness_parts/characters/payloads.py` for
   `agent/charsheet/draft/payloads.py` (fork-owned, importable from `agent_runtime`); the argv
   handlers call the moved names. `agent_runtime` must not import `hermes_cli`.
2. **Four methods, `TIER_READ`** (views; the census marks all four R), in
   `agent_runtime/serve_rpc/characters.py`: `list` (no params) and `status` (`draft`) return
   the argv payloads verbatim; `thumb` (`draft`, `row` | `direction`, `attempt`, `frame`,
   `scale`, `square`) returns the crop result dict PLUS `media`: the `_media_get_frame` block
   (extracted to `media_handles.media_block(data, media_type)` so the shape has one owner)
   when `withinConsoleBudget`, else `media: null` and the existing `path` + which bound was
   missed; `sprite` (`slug`, `include_sheet`) returns the metadata-only `sprite_payload` and,
   when asked, `sheet_media` as the same block in place of a bare base64 string. The argv
   payload shapes do not change.
3. **Refusals** map `_CHARACTERS_EXPECTED` to `ERR_INVALID_PARAMS` / `ERR_HANDLER_FAILED` with
   the same `reason` codes `_characters_error` already emits (one vocabulary).
4. Honoured keys are module constants (`CHARACTERS_*_PARAMS`) so the manifest `params` block
   can publish them (the L4.22 ruling's mechanism, D1/D3's lane).

### Stages, tests, killing mutation

| stage | test | killing mutation |
|---|---|---|
| MOVE — BUILT f6ddc22c0d | `tests/agent_runtime/test_serve_charsheet_fake_draftsman_child_e2e.py` + the characters CLI tests byte-identical | — |
| CHANGE — BUILT 67adcaf393 | `tests/agent_runtime/test_serve_rpc_characters.py` (new): each twin equals its argv payload; thumb over budget → `media: null` + path; tier test (all `read`) | skip the budget check → an over-ceiling crop ships inline → red; register `thumb` at `console` → tier test red |
| launcher | `hermes_character_client.dart` list/readStatus/thumb/sprite RPC-first, argv on Unavailable | — |

Built by lane build-1011-C3, where the code differed: the MOVE also carried the thumb dispatch
(`thumb_result`, it lived in the argv closure); `media_block` lives in `serve_rpc/media.py`
(`media_handles.py` is already 992 lines); honoured keys in `serve_rpc/twin_params.py` (a models
table the registry can read); `not_found` answers `ERR_NOT_FOUND`; `sheet_media` is null past
`MAX_FETCH_BYTES`.

Owner question: none.

---

## D2.11 = L4.26 — `runtime.board.card.add/move/edit/archive/restore`, `runtime.board.resolve_conflict`

**Verdict: PLAN.** Size: one MOVE (~90 lines), one CHANGE (~220 production, ~260 test), 2
stages + launcher. The 2026-08-22 plan `board-surface-rpc-lane.md` asked "measure before
designing" because the argument was spawn latency; the 2026-10-03 census retired that argument
(the sites are warm through `dispatch_argv`) and the standing RPC-first ruling makes the twin
the lane. Its other two rules still bind: refusals terminal, the ack echoes store truth; and
**no fold in this lane** (rule 3: a fold needs a producer inside the store lock — a follow-on
row).

### What the code says

- `hermes_cli/harness_parts/board.py` `_cmd_board_card_*` / `_cmd_board_resolve_conflict` are
  thin over `agent_runtime/board_store/store.py::BoardStore.add_card / edit_card / move_card /
  archive_card / restore_card / resolve_conflict`; they project with `_card_row(card,
  full=True)` (and `_board_row`, `_column_kind`) which live in the CLI module.
- The store raises typed errors: `errors.NotFound`, `errors.AlreadyExists`,
  `store_conflicts.check_revision` → `errors.StaleRevision`, `ValueError("invalid_request")`,
  and `card_mechanics.IdempotentReplayUnresolved` / `IdempotencyKeyVerbMismatch`. It already
  takes `expect_revision` and `idempotency_key`.
- The template is `serve_rpc/office_surface_writes.py::_runtime_office_surface_update`:
  validate params → store call → `office_errors.translate(exc, TABLE, scope)` →
  `log_office_write` → ack with the store's normalized row and post-write revision.

### The design decisions

1. **MOVE first**: `_card_row`, `_board_row`, `_column_kind`, `_board_active_card_count` →
   `agent_runtime/board_store/rows.py`; the CLI imports them.
2. **Six methods, `TIER_CONSOLE`**, in `agent_runtime/serve_rpc/board.py`, params = the argv
   flags by name (`board_id`, `workspace_id`, `title`, `description`, `column_id`, `priority`,
   `labels` (list), `assignee`, `clear_assignee`, `before`/`after`, `take`, `expect_revision`,
   `idempotency_key`, `correlation_id`); result = `{"card": rows.card_row(card, full=True)}`
   from the STORE's return (never the request echoed). `resolve_conflict` with an archived
   outcome answers `{"card": null, "card_id", "state": "archived", "take"}` as the CLI does.
3. **One error table** `BOARD_WRITE_ERRORS` for `office_errors.translate`: `StaleRevision →
   stale_revision` (the office's spelling), `NotFound → unknown_card | unknown_board` (by the
   message prefix the store already writes), `AlreadyExists → card_exists`, `ValueError →
   invalid params`, the two idempotency classes → `idempotent_replay_unresolved` /
   `idempotency_key_verb_mismatch`. A refusal is terminal; no argv retry.
4. Honoured keys as `BOARD_*_PARAMS` constants (L4.22's manifest publication).
5. `expect_revision` stays the client's guard (the board already sends it; the office does
   not) — the twin passes it through unchanged.

### Stages, tests, killing mutation

**BUILT (build-1011-C4, 2026-10-10):** MOVE BUILT 904edb1105 (names kept with their
underscore: `test_s48_cli_entity_row_consolidation` reads `_board_active_card_count` by that
spelling); CHANGE BUILT 53b623e684 + e2a5bec6bc (helper renames for W0-G3). Followed the code
where it differs: `card_id` and `created_by` are honoured too, and `SyncConflict` maps to
`card_conflict` (writes) / `conflict_not_found` (resolve). Launcher stage open.

| stage | test | killing mutation |
|---|---|---|
| MOVE | `tests/agent_runtime/test_board_store.py` + board CLI tests byte-identical | — |
| CHANGE | `tests/agent_runtime/test_serve_rpc_board.py` (new): each verb's ack equals the store's row; stale `expect_revision` → `stale_revision` and no write; same `idempotency_key` twice → one card; tier test (all `console`) | ack built from params instead of the store row → red; drop `expect_revision` passthrough → the stale write lands → red |
| launcher | `harness_board_capabilities.dart` the six capabilities RPC-first, argv on Unavailable | — |

Owner question: none. Follow-on row (not this lane): a `board_card` fold with its producer
inside `board_lock`, per `board-surface-rpc-lane.md` rule 3.

---

## D2.12 = L2.28 — User prefabs do not travel: a realm-sync family beside `map_sync`

**Verdict: PLAN**, and the design decision is that prefab is the THIRD instance of one class,
so the class is built first. Size: MOVE ~−550 net lines (two ~600-line modules onto one
~450-line family module plus two ~80-line descriptors), CHANGE ~140 production + ~200 test for
prefab. Prerequisite (the row's own): the launcher binds `UserPrefabStore` to
`runtime.prefab.*` first (launcher queue).

### What the code says

- `agent_runtime/level_sync.py` (599 lines) and `agent_runtime/map_sync.py` (633) are the same
  module twice: `validate_*_document`, `*_document_hash`, `stored_*_sha256`,
  `*_expectation_matches`, `*_document_row`, a `*Store` (read/write/clear/list), `read_*_baseline`
  / `write_*_baseline` / `update_*_baseline_after_publish`, `read_remote_*`, a `*PullSummary`
  with the same six arms (`adopted`, `converged`, `kept_local`, `held`, `upstream_absent`,
  `refused`, `source`), `apply_*_pull` over `agent_runtime/sync_merge.py::classify_three_way_pull`,
  and `_write_conflict_sidecar`. They plug into realm sync at four seams:
  `realm_sync/families.py` (`SyncFamily.LEVEL/MAP`, `SyncPathFamily(..., owner=...)` so the
  generic pull skips `store/levels/*`, `store/maps/*`), `publish_scans.py::_level_publish_scan /
  _map_publish_scan`, `pull.py::_pull_level / _pull_map`, `status.py::_level_status_row /
  _map_status_row` (top-level rows, deliberately not `store_drift` because neither has a revert
  arm — runtime-queue row "A realm-synced LEVEL has no revert arm"), and
  `publish.py` (`_published_row`, `update_*_baseline_after_publish`).
- `agent_runtime/prefab_store.py::PrefabStore` already has the store half (validate, hash,
  read/write/clear/list, `label_holder`), per PROFILE under `paths.prefabs_root(profile)`;
  `serve_rpc/prefab.py` owns the four verbs. Nothing in `realm_sync/` knows prefabs.

A third copy would be the third patch on one class (the weakness-escalation rule: the third
instance files the CLASS). The class is "a whole-document family: adopt, keep or HOLD, never
merged, baseline-keyed, sidecar on hold, no revert arm".

### The design decisions

1. **`agent_runtime/realm_sync/document_family.py`** — a `DocumentFamily` descriptor
   (`family: SyncFamily`, `published_prefix`, `baseline_key(token)`, `store_for(token)` →
   read/write, `validate(raw)`, `document_hash(raw)`, `tokens()` (what this install publishes),
   `conflict_path(realm_id, token)`, `summary_key` (`level_sync` / `map_sync` / `prefab_sync`,
   the wire names kept)) and the generic functions `read_remote_documents(subtree, family)`,
   `apply_document_pull(realm_id, subtree, family) -> DocumentPullSummary`,
   `document_publish_scan(family) -> DocumentPublishScan`, `document_status_row(realm_id,
   family)`, `update_document_baseline_after_publish`. The arms, the refusal codes and the
   sidecar schema are the map module's, verbatim.
2. **MOVE level and map onto it** behaviour-preserving: `level_sync.py` and `map_sync.py` keep
   their public names as thin re-exports (`apply_level_pull = partial(apply_document_pull,
   family=LEVEL_FAMILY)`), their `*PullSummary.as_dict()` key sets unchanged (the pull ack's
   `result["level_sync"]` / `result["map_sync"]` are wire), their tests green unchanged.
3. **Prefab is one descriptor**: `SyncFamily.PREFAB = "prefab"`, published prefix
   `store/prefabs/<profile-token>/<prefab-token>.json` (the token pair IS the family token:
   `"<profile>/<prefab>"`), `store_for` → `PrefabStore(profile)`, `validate_prefab_document`,
   `stored_prefab_sha256`, `paths.prefab_conflict_path(realm_id, profile, prefab)` (new),
   `paths.prefab_baseline_path(realm_id)` (new), `summary_key = "prefab_sync"`. Plugged in at
   the four seams: `SyncPathFamily(SyncFamily.PREFAB, _prefix("store/prefabs/"),
   owner="document_family.apply_document_pull")`, `_pull_prefab(run)`, the publish scan fold,
   the status row `prefabs`. A profile's shelf follows the profile NAME across machines (the
   row's ask); a profile the peer does not have gets the files and nothing reads them until
   it does — the same rule profile files already follow (`_profile_home_for_token`).
4. **No revert arm**, like level and map; the class makes the later revert arm one function
   over three families instead of three — that row stays open and now names the class.

### Files and symbols

- new `agent_runtime/realm_sync/document_family.py`; `agent_runtime/level_sync.py`,
  `agent_runtime/map_sync.py` shrunk to descriptors + re-exports (MOVE).
- `agent_runtime/realm_sync/families.py`, `publish_scans.py`, `pull.py`, `status.py`,
  `publish.py` — the prefab seam entries (CHANGE); `agent_runtime/paths.py` two path helpers.
- `agent_runtime/prefab_store.py` — `prefab_document_hash` if the canonical hash differs from
  `stored_prefab_sha256` (maps distinguish the two; keep the distinction).
- Launcher: binds `UserPrefabStore` to `runtime.prefab.*` (prerequisite row); then reads
  `prefab_sync` on the realm sync detail sheet beside `maps`.

### Stages, tests, killing mutation

| stage | test | killing mutation |
|---|---|---|
| MOVE | `tests/agent_runtime/test_level_sync.py`, `test_realm_sync_level_artifact.py`, `test_map_rpc.py`, `test_realm_sync_publish_accounting.py` byte-identical before/after | — |
| CHANGE prefab | `tests/agent_runtime/test_prefab_sync.py` (new): adopt / converge / keep_local / held with sidecar / upstream_absent never deletes / refused unreadable; publish scan lists the shelf; status row counts | adopt on CONFLICT → a locally changed prefab is overwritten → red; delete on `upstream_absent` → red |
| launcher | detail sheet row | — |

### Owner question

- A shelf is per PROFILE NAME across the realm (proposed) — or merged realm-wide into one
  shelf per install? The per-profile reading is the row's and the store's.

---

## D2.13 = L1.27 — Eternia Lens as a fork-owned plugin

**Verdict: PROGRAM-EXISTS.** Plan: `docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md`
§5 (stages L0–L4, each with its red-first gate). All four §6 rulings were given 2026-10-02
(`eternia-lens` / `runtime.lens.*`; per-manifest persona defaulting to the selected one; no
`act` level; phones run no poller), so L0 may start; nothing exists under `agent_runtime/lens/`
or `plugins/eternia-lens/` on `main`, so L0 has not started. Next stage: **L0** — skeleton and
contracts (`wire_value`, `manifest`, `seal`, `feed`, `rules`, `episode`, `evidence`), the
conformance corpus ported from Companion as the test oracle, `runtime.lens.list` only, with
§6a's four additions to `rules.py` (`changed`, `moved_by`, `below`/`above`, `best_of`,
`ends_within`) in L0's contract. §6c (Luau) is recorded as not adopted; L0 lands the declarative
rule contract and does not wait on it. No design added here. Owner question: none blocking.

---

## D2.14 = L1.30 — Stage 2 remainder: the phone profile gate to zero

**Verdict: PROGRAM-EXISTS.** Plan: `docs/downstream/phone-gate-to-zero-plan-2026-09-30.md`
(six lanes G1–G6 in §4, owner decisions D1–D5 in §5); the row closes when
`scripts/bundle_profile_gate.py --profile bundled-phone` prints PASS. Status read off `main`'s
history, not the queue (the lane rows under "Filed on arrival — 2026-09-30 (lane s2-plan)" are
gone, so they landed or were folded): G3 landed (`1309210ad2`, gate 104 → 34), G2 merged with
it (`6dad554dd1`, gate → 16), G6 landed (`5911418efb`, the sibling tree that retires `pinned`),
the G4 landing heading is empty, and G1's switch-offs are the 164 → 104 step. G5 is owner-gated.
Next stage: **re-take the gate on `main`** (background, `timeout` ≥ 900 s, `--markdown
docs/downstream/bundled-phone-gate-2026-09-28.md`, the gate's own rules in plan §4) to name the
remaining findings, then **G5** against the owner's D2–D5. Blocking owner questions, one line
each, unchanged from plan §5:

- D2 — HEIC/AVIF on phones: omit `pillow-heif` and let the Launcher's picker transcode (recommended)?
- D3 — the secrets vault on phones: drop `agent.vault_store` + `agent.vault_backends.*` (recommended)?
- D4 — DuckDuckGo on phones: drop the `ddgs` provider (HTTP-API providers only)?
- D5 — slash commands on phones: build the in-process slash runner, or rule "no slash commands" for Stage 2?

---

## Structural findings from this sweep (filed by the parent; one line each)

- **The provider boundary flag is set before the provider is resolved, so every pre-request
  failure classifies as an ambiguous outcome** · fork-owned (`chat_turn_commit/run.py::
  _cross_provider_boundary`, `mission_chat_outcome.classify_turn_failure`) · evidence D2.02 ·
  queue: `runtime-queue.md` § Fork-owned (the D2.02 PLAN is the fix).
- **Two whole-document realm-sync appliers are one module twice (`level_sync.py`,
  `map_sync.py`); the third family would be the third copy** · fork-owned · evidence D2.12 ·
  queue: `runtime-queue.md` § Fork-owned (the class is `realm_sync/document_family.py`).
- **The snapshot yield rule stands aside only for hot windows because its docstring predates
  the `persona_chat_turn` overlay; with every subscriber declaring the token a build may stand
  aside for the whole admitted turn** · fork-owned (`snapshot_turn_yield.py::_turns_admitted`) ·
  evidence D2.06 · queue: `runtime-queue.md` § Fork-owned (fix-lane sized; replaces L4.30).

## Owner rulings — 2026-10-10

The owner took every recommendation ("go with recommendation").

- D2.01: the aggregate decoded file limit is the composer's lower bound, so server and UI agree.
- D2.02: no pre-flight refusal for a configured-but-unresolvable credential; the post-boundary phase rule only.
- D2.03: a compressed-lineage branch child starts UNCOMPRESSED with full display rows (TUI behaviour).
- D2.07: yes, a PROFILE conversation (no persona) honours `default_permission_mode()`.
- D2.12: the prefab shelf is per profile NAME across the realm.
- D2.14: plan §5 D2–D5 (HEIC, vault, ddgs, slash) remain OPEN for the owner's picks; G5 waits.
