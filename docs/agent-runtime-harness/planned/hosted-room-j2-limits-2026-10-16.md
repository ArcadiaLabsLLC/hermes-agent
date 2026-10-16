# J2 hosted-room host limits, redesigned against upstream/main (design)

Status: PLAN — written 2026-10-16 (lane q-j2, design only); owner decisions owed.
Row: runtime-queue § "Filed on arrival — 2026-10-15 (door PR lanes doors-a, doors-b)",
"J2 hosted-room host limits needs a re-design against upstream acc3cada0da …".
Supersedes §J2 of `upstream-doors-2026-10-06.md` (branch `h-doors-2`) for the PR shape;
§J1 and §J3 of that sheet stand. No branch is cut by this lane: the owner's PR branches
stay idle (ruling 2026-10-16); this is the spec a build lane builds from.

## In plain English

The fork lets a host say how big a Group Chat discussion may be (members, rounds,
messages, prompt bytes), which members may speak now, whether one member writes a closing
summary, how many policy events the checkpoint keeps, and that a finished meeting's log
must outlive the deleted-chat sweep. That was going upstream as one PR (J2). Meanwhile
upstream rebuilt the same planner around file attachments: every member turn now carries
a frozen list of the exact messages it was built from (`input_context`), chosen by
`_bounded_task_delta`, and reconstruction after a restart checks that list. The fork has
NONE of that yet, because the fork merges release tags only and v0.22.2's tree predates it.

Two halves. (A) On the fork's `main`, nothing shrinks today: the J2 carry stays as it is
until the next release tag brings `input_context`, and at that merge the conclusion turn
and the checkpoint budget are re-expressed on upstream's new pieces (two small CHANGE
slices, both specified here so the merge lane does not design under conflict). (B) The
upstream PR is redesigned so the conclusion is one more ordinary planned turn built on
`_bounded_task_delta` with a frozen `input_context`, the turn-id regex stops encoding the
limits, and the checkpoint's transcript bound scales with the instance budget. Recommended
split: J2a (limits, active members, conclusion, budget; ~150 lines) and J2b (history pins;
~70 lines). Either shape sits under the 300-line cap; together they are ~225.

## Evidence (fork `main` be5c0027c2e / worktree 3dbb62ff9f2; upstream tag v0.22.2 d923a5eb487; upstream/main e6899c8090d; J1 branch 30cd5141bab on acc3cada0da)

- **The fork's base tree is v0.22.2, not acc3cada0da.** `git merge-base main upstream/main`
  answers 297552a9d64 (which carries `input_context`), but that is a parent pointer of the
  release commit d923a5eb487, whose TREE has no `gateway/hosted_room_attachments.py` and zero
  `input_context` hits in `gateway/hosted_room_discussion.py`. The fork's file on `main` has
  zero hits too. Diffs in this doc are tree-to-tree against d923a5eb487.
- **Fork carry (v0.22.2 → main), five upstream files, +164/−62:** `gateway/hosted_room_discussion.py`
  (`DiscussionRoom.limits`; `limits=` on `validate_roster`, `validate_room`, `derive_member_watermarks`,
  `plan_next_task`, `reconstruct_task_plan`, `plan_publication`; `_TURN_ID_RE` widened to
  `r[0-3]` / `p(0|[1-9][0-9]*)`; `_validate_turn_coordinates` bounded by `room.limits`; `_build_prompt`
  gains `active_members`, `conclusion`, `room.limits.guidance`, `room.limits.prompt_bytes` and the
  omission-notice reserve fix; `plan_next_task` wraps every bounded/settled exit in
  `finish = partial(_conclude, …)` and returns `conclusion_finished` once the `round_index == max_rounds`
  terminal exists; `reconstruct_task_plan` re-checks `position` and `task_round_index`) — plus the J3
  hunks (`response`, `ready_tasks`, `independent`, `published_watermark`), which this doc does not move.
  `gateway/hosted_room_policy_checkpoint.py` (`HostedRoomPolicyCheckpoint(db_path, *, max_active_events=64)`,
  `self.max_active_events` in `_discussion_events`). `gateway/hosted_rooms.py`
  (`MAX_RETAINED_ROOM_HISTORIES`, `RoomHistoryRetentionFullError`, the `_DEPENDENT_TABLES` entry, the
  pinned set and stable sort in `_prune_disbanded_rooms_locked`). `tui_gateway/hosted_room_driver.py`
  (J1's four fixes + J3's `with_independent_members`; and `member_id=_member_id(task)` on `submit`, which
  upstream now has itself).
- **Fork-only modules (Phase B, pb-g 912eb11b0b2):** `gateway/hosted_room_limits.py` (`DiscussionLimits`,
  `DEFAULT_LIMITS`, `_conclude`, `task_round_index`; entered only through `hosted_room_discussion`, the
  import-order row is TAKEN by lane q-hosted) and `gateway/hosted_room_history_pins.py`
  (`pin_room_history`, `unpin_room_history`, reading `hosted_rooms._*` at call time).
- **Fork consumers:** `agent_runtime/discussions/room_state.py::RoomState.limits` builds
  `DiscussionLimits(max_members=128, max_rounds=settings["rounds"], max_messages=capacity*rounds,
  shared_profiles=True, prompt_bytes=12000, guidance=…, conclusion_member_id=…)`;
  `agent_runtime/discussions/service.py::DiscussionService.initialize` builds
  `HostedRoomPolicyCheckpoint(db_path, max_active_events=256)`.
- **Upstream advance (v0.22.2 → upstream/main) on the same files:** `hosted_room_discussion.py` +129
  (`validate_user_payload` optional `attachments`; member messages with `attachments` /
  `recipient_member_ids`; `_event_attachments`; `_bounded_task_delta(messages, *, watermark, member) ->
  (selected, attachments)`; `plan_next_task(…, freeze_input_context=False)` with per-member
  `seen_through_seq = delta[-1].seq`; `_make_task_plan(…, input_context=, attachments=)`;
  `reconstruct_task_plan` verifies `input_context["event_seqs"][-1] == turn_id.seen` and that every seq
  exists). `hosted_room_policy_checkpoint.py` +123 (`_TRANSCRIPT_SCHEMA_VERSION = 4` with rebuild-by-replay;
  `MAX_TRANSCRIPT_POLICY_EVENTS = MAX_THREAD_TRANSCRIPT_EVENTS * (MAX_ACTIVE_POLICY_EVENTS + 2)` as a
  `LIMIT` on `_TRANSCRIPT_EVENTS_SQL` with a `RuntimeError` past it; `events_for_task(…, input_context=,
  task_id=)`; `_published_task_events`; a concurrent-worker cursor reload). `hosted_room_driver.py` +54
  (`validate_bound_task_manifest`; `input_context` / `attachments` as optional payload fields;
  `capture_transition_locked`; `get_task_for_turn`). `hosted_rooms.py` +31 (`EventCursorConflictError`,
  `append_event(expected_latest_seq=)`, `create_room(admit=)`, attachment retention).
  `tui_gateway/hosted_room_driver.py` +20 (`AttachmentsUnsupportedError`, `accepts_attachments`,
  `submit(…, member_id=, attachments=)`). New modules: `hosted_room_attachments.py` (1363),
  `hosted_room_task_input.py` (`validate_task_input`, `MAX_TASK_INPUT_EVENTS = 128`),
  `hosted_room_work_records.py` / `_storage.py` / `_lineage.py`, `hosted_room_authority_history.py`.
- **Where the two designs meet:** with no attachments in the thread, `_bounded_task_delta(messages,
  watermark=w, member=m)` selects every message with `seq > w`, so `delta[-1].seq` equals the fork's
  thread-maximum `seen_through_seq`. The fork's `_conclude` already computes exactly that with
  `watermark=0`. The only semantic gap is that upstream's `validate_task_input` refuses more than 128
  seqs, and the fork's `max_messages` may exceed 128.
- **Tests that move with the PR:** `tests/gateway/test_hosted_rooms_downstream.py`
  (`test_pinned_history_is_exempt_from_the_age_sweep`, `test_byte_budget_reclaims_unpinned_history_before_pinned_history`,
  `test_byte_budget_still_reclaims_pinned_history_and_drops_its_pin`, `test_retention_limit_is_typed_and_unpin_frees_a_slot`,
  `test_unpin_rejects_stale_authority_and_tolerates_an_unused_store`);
  `tests/gateway/test_hosted_room_policy_checkpoint.py` (`test_active_policy_event_budget_bounds_the_projection_it_is_given`,
  `test_active_policy_event_budget_refuses_values_it_cannot_honour`). The fork's conclusion proofs are
  service-level (`tests/agent_runtime/test_discussion_conclusion.py`); the PR needs policy-level cases
  written new (B3 below).

## Target shape

**One planner, one delta.** A conclusion is an ordinary planned turn at `round_index == limits.max_rounds`
for `limits.conclusion_member_id`, whose delta is `_bounded_task_delta(thread_messages, watermark=w0,
member)` with `w0` chosen so the delta holds at most `MAX_TASK_INPUT_EVENTS` messages, and whose
`input_context` is ALWAYS frozen. Reconstruction then needs no special case: upstream's own
`event_seqs[-1] == turn_id.seen` check covers it. Attachments ride along through upstream's path.

**Coordinates carry no policy.** `_TURN_ID_RE` matches `r(?P<round>0|[1-9][0-9]*)` and
`p(?P<position>0|[1-9][0-9]*)`; the bounds live in `limits` and are enforced in
`_validate_turn_coordinates` and `reconstruct_task_plan` (`position ≤ max_members−1`,
`round ≤ last_round_index`). Under `DEFAULT_LIMITS` the accepted set is exactly today's `r[0-2]` / `p[0-5]`.

**One budget, two bounds.** `HostedRoomPolicyCheckpoint(db_path, *, max_active_events=MAX_ACTIVE_POLICY_EVENTS)`
derives `self.max_transcript_events = MAX_THREAD_TRANSCRIPT_EVENTS * (self.max_active_events + 2)` and uses
it where upstream uses the module constant. Default instance: byte-identical SQL parameters.

**Retention is its own PR.** `pin_room_history` / `unpin_room_history` and the prune ordering touch
`hosted_rooms.py` only and share no symbol with the limits; they go as J2b.

**Fork side after the next tag merge:** `hosted_room_limits.py` keeps `DiscussionLimits` / `DEFAULT_LIMITS`
(identity unchanged, consumers untouched); `_conclude` is rewritten on `_bounded_task_delta` +
`validate_task_input` (A2); the checkpoint's budget line gains the transcript bound (A3). Nothing on `main`
moves before that merge: the fork merges release tags only, never `upstream/main`, and upstream files are
edited additively or not at all.

## Owner decisions (recommendation first)

1. **PR shape.** Recommend **split**: J2a `feat(gateway): host-declared Group Chat limits, active members,
   scheduled conclusion, checkpoint budget` (~150 lines) and J2b `feat(gateway): opt-in Group Chat history
   retention (pin/unpin)` (~70 lines), independent, either order. Alternative: one PR (~225, under the cap)
   whose reviewer cost is the pins table on top of the planner change — the sheet's own stated risk.
2. **Conclusion input.** Recommend the conclusion ALWAYS freezes `input_context`, and bounds its delta to the
   last `MAX_TASK_INPUT_EVENTS` (128) messages by choosing `w0`; `_build_prompt` already keeps only the last
   `MAX_DISCUSSION_DELTA_LINES`, so no visible prompt changes. Alternative: freeze only under
   `freeze_input_context` as upstream does for member turns — cheaper, but a conclusion admitted before a late
   member message then fails deterministic reconstruction.
3. **Fork `main` timing.** Recommend **wait for the next release tag** that carries upstream 676238c81b8
   ("bind hosted discussion attachment tasks to source events") and land A2/A3 in that merge's follow-up.
   Alternative: cherry-pick the attachments series onto `main` now — faster, against the merge-tags-only
   ruling (`feedback_merge_upstream_per_release`), and it imports 2.5k upstream lines the fork does not use.
4. **J2 branch base.** Recommend cutting J2a/J2b from `upstream/main` directly, not from J1
   (`fix/hosted-room-driver-settlement`): J2 touches none of J1's hunks (`_reconcile_indeterminate`,
   `_find_terminal_receipt`, `stop_unresolved`, `request_reconciliation`), and J1 itself rebases clean onto
   upstream's `_execute_attempt` attachments guard (different region; verify at build).
5. **`_conclude` location on `main`.** Recommend it stays in `gateway/hosted_room_limits.py` until J2a is
   accepted, then the module retires with the ledger's S3 rows; the q-hosted import-order fix lands first
   and A2 edits the rewritten module.

## Slices (build order)

### Half A — the fork's carry on `main` (gated on the next tag merge)

- **A0 — record the merge rule (docs only, now).** Add to the four S3 ledger rows
  (`upstream-footprint-ledger.md`, `hosted_room_discussion.py` / `_driver.py` / `_policy_checkpoint.py` /
  `hosted_rooms.py`): "at the next tag merge, take upstream's hunk and re-apply the q/j2 shape (this doc §B)".
  Killing mutation: none (a pointer); the merge lane's commit body names this doc.
- **A1 — MOVE (at the merge, inside the merge commit).** Upstream's `_bounded_task_delta`, `_event_attachments`,
  `validate_task_input`, the checkpoint's schema-4 replay, `MAX_TRANSCRIPT_POLICY_EVENTS` arrive as upstream
  lines. The fork's `member_id=` hunk on `submit` retires (upstream has it). No fork line changes meaning.
- **A2 — CHANGE: `_conclude` on upstream's delta.** In `hosted_room_limits.py::_conclude`: replace
  `seen = max(e.seq for e in messages)` + `_build_prompt(watermark=0, …)` with `w0 = messages[-MAX_TASK_INPUT_EVENTS-1].seq
  if len(messages) > MAX_TASK_INPUT_EVENTS else 0`, `delta, attachments = _discussion._bounded_task_delta(messages,
  watermark=w0, member=member)`, `seen = delta[-1].seq`, and pass `input_context=validate_task_input({"watermark": w0,
  "event_seqs": [e.seq for e in delta]})`, `attachments=attachments` to `_make_task_plan`. Killing mutation:
  drop the `input_context=` kwarg → a new `tests/gateway/test_hosted_room_discussion.py` case that admits a
  conclusion, appends one more member message, then `reconstruct_task_plan`s the admitted task reds with
  "driver task failed deterministic reconstruction" (the frozen context is what makes it pass).
- **A3 — CHANGE: per-instance transcript bound.** In `HostedRoomPolicyCheckpoint.__init__`:
  `self.max_transcript_events = MAX_THREAD_TRANSCRIPT_EVENTS * (self.max_active_events + 2)`; `_discussion_events`
  passes it as the `LIMIT` and compares against it. Killing mutation: keep the module constant in the
  comparison → `test_active_policy_event_budget_bounds_the_projection_it_is_given` extended with a thread
  whose transcript exceeds 1584 rows under `max_active_events=256` reds with "thread policy transcript
  exceeded its bound".
- **A4 — gate.** `scripts/run_tests_bundled.sh tests` once for the batch (one gate per batch); the
  import-layers fixture loses the `_conclude` → `_thread_messages` / `_build_prompt` reaches only when the
  q-hosted lane's constant owner lands, not here.

### Half B — the upstream PR, prepared branch only (cut from `upstream/main`; nothing touches `main`)

Line budget (production lines, tests separate):

| slice | file | lines |
|---|---|---|
| B1 limits value + threading + coordinates | `hosted_room_discussion.py` | 34 + 26 + 12 = 72 |
| B2 active members, guidance, prompt_bytes | `hosted_room_discussion.py` | 14 + 14 = 28 |
| B3 conclusion turn | `hosted_room_discussion.py` | 38 |
| B4 checkpoint budget + transcript bound | `hosted_room_policy_checkpoint.py` | 12 |
| **J2a total** | | **~150** |
| B5 pins (J2b) | `hosted_rooms.py` | 5 + 4 + 1 + 12 + 45 = 67 |
| B0 omission-notice reserve fix (own PR, bug-fix shaped) | `hosted_room_discussion.py` | 6 |

- **B0 — `fix(gateway): reserve the omission notice inside the Discussion prompt budget`.** The fork's
  reserve arithmetic in `_build_prompt` (`reserved = len(omission) + 2`; truncate to `available − reserved`;
  append the notice only when it fits). Bug-fix shaped, goes ahead of J2a like J1. Killing mutation: restore
  upstream's `available > 32` branch → a case with `available` just under the notice length reds on
  "Discussion prompt exceeds the driver limit".
- **B1 — limits value, threading, coordinates.** `DiscussionLimits` (frozen; `max_members`, `max_rounds`,
  `max_messages`, `prompt_bytes`, `shared_profiles`, `guidance`, `conclusion_member_id`; `last_round_index`;
  `__post_init__` bounds `2..MAX_MEMBERS`, `1..MAX_DISCUSSION_ROUNDS`, `1..384`, `2048..MAX_PROMPT_BYTES`,
  guidance ≤ 1000 bytes, `conclusion_member_id` an identifier); `DEFAULT_LIMITS`; `DiscussionRoom.limits`;
  `limits=DEFAULT_LIMITS` on the six public functions; `_TURN_ID_RE` unbounded digits; `task_round_index`;
  the two bound checks in `reconstruct_task_plan`; `_validate_turn_coordinates` from `room.limits`. Killing
  mutation: delete the `position ≤ max_members−1` check → a `p6` turn-id under `DEFAULT_LIMITS` is
  reconstructed instead of refused → red. Positive control: every existing discussion test passes unchanged
  (default reproduces today).
- **B2 — active members, guidance, prompt bytes.** `plan_next_task(…, active_member_ids=None)`: the subset
  must be within the catalog (`DiscussionValidationError` otherwise); round-0 mention resolution and
  later-round citations filter to `active`; `_build_prompt(active_members=)` names only active peers;
  `room.limits.guidance` appended to the rules; `room.limits.prompt_bytes` replaces `driver.MAX_PROMPT_BYTES`
  in `_build_prompt` and `reconstruct_task_plan`. Killing mutation: pass `room.members` instead of `active`
  to `_build_prompt` → the case asserting an inactive member's handle is absent from the prompt reds.
- **B3 — conclusion turn.** `_conclusion_turn(room, validated, discussion, active, decision)` in
  `hosted_room_discussion.py` (the fork's `_conclude` built as A2 specifies, on `_bounded_task_delta` with a
  frozen `input_context`); `finish = partial(_conclusion_turn, …)` wraps `max_messages`, `silent_round`,
  `max_rounds`; `conclusion_finished` early return when the `round_index == max_rounds` terminal exists;
  reasons `conclusion_turn`, `conclusion_completed|failed|cancelled|deferred|empty|member_unavailable`;
  `_build_prompt(conclusion=True)` swaps the rules block. With `conclusion_member_id=None`, `finish` returns
  its argument: every decision byte-identical. Killing mutation: drop the `conclusion_finished` early return →
  the new "exactly once across reconstruction" policy case (plan → terminal at `max_rounds` → plan again)
  reds by planning a second conclusion. Tests new (~80 lines): opt-in, exactly-once, member-unavailable,
  reconstruction with a late message (A2's case), `(pass)` → `conclusion_empty`.
- **B4 — checkpoint budget + transcript bound.** The A3 shape, on upstream's constant. Killing mutation: A3's.
  Tests: the two budget cases move in, plus A3's extension.
- **B5 — J2b pins.** `MAX_RETAINED_ROOM_HISTORIES`, `RoomHistoryRetentionFullError`, the `_DEPENDENT_TABLES`
  entry, the pinned set + stable sort in `_prune_disbanded_rooms_locked`, `pin_room_history` /
  `unpin_room_history` inside `hosted_rooms.py` (the fork's module bodies, docstrings cut to one paragraph).
  Killing mutation: delete `candidates.difference_update(pinned)` → `test_pinned_history_is_exempt_from_the_age_sweep`
  reds. The five downstream tests move in.
- **B6 — PR bodies** in `docs/agent-runtime-harness/planned/pr-bodies/` (J2a, J2b, B0), each ≤ 10 lines,
  the J2a body stating "default limits: every decision, prompt and prune order byte-identical; no attachments
  behaviour changed". Branches stay idle until the owner opens them; #125258 gets the three titles first.

## Blast radius

Half A: `gateway/hosted_room_limits.py` (A2), `gateway/hosted_room_policy_checkpoint.py` (A3, the fork's
existing budget hunk), two tests; `DiscussionLimits` fields and `HostedRoomPolicyCheckpoint(max_active_events=)`
unchanged, so `agent_runtime/discussions/room_state.py` and `service.py` do not move; the import-layers
fixture unchanged by this plan. Half B: `gateway/hosted_room_discussion.py`, `gateway/hosted_room_policy_checkpoint.py`
(J2a), `gateway/hosted_rooms.py` (J2b), their tests; no change to `hosted_room_driver.py`,
`tui_gateway/hosted_room_driver.py`, the attachments modules or the RPC surface. J3 (`response`, `ready_tasks`,
`independent`) is untouched and still layers on J2a.

## What it retires

On acceptance of J2a + J2b: `gateway/hosted_room_limits.py` and `gateway/hosted_room_history_pins.py`
(the fork imports upstream's names), the four S3 ledger rows, the import-layers exceptions those modules
hold, and the `_TURN_ID_RE` / `last_round_index` fork hunks. At the next tag merge regardless: the fork's
`member_id=` hunk on `submit`.
