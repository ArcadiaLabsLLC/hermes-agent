# Console history controls — review of draft PR #7 (2026-10-10)

This note is the evidence behind the rows filed under "Fork-owned → Filed on
arrival — 2026-10-10 (Console history PR #7 review)" in
`Harness_Brain/20 — Active Initiatives/runtime-queue.md`. It reviews
[PR #7](https://github.com/ArcadiaLabsLLC/hermes-agent/pull/7) at `91b79fd19`.
The launcher half has its own note:
`eternia_launcher/docs/mission_control/planned/console-history-controls-review-2026-10-10.md`.

**Verdict: changes requested before landing.** Data integrity holds: branch is
atomic, the parent is untouched, and rewind archives rather than deletes. The
defects are elsewhere. Some definite no-write refusals are reported as
"outcome unknown". The new admission lock now sits in front of every chat
accept. A killed serve can block history controls forever.

## What was re-verified

- The PR's four focused test files pass: **30 passed, 0 failed**
  (`scripts/run_tests.sh` with the four files the PR names, 8 workers).
- The reviewer re-measured the upstream footprint: 186 files, 962 deleted
  lines, 4 heavy. That matches the ledger and `tests/fixtures/upstream_footprint.json`.
  The fixture's prose still says `checkpoint_manager` is "170/0", and the
  measured value is 181/0.

## Author claims

| Claim | Verdict |
|---|---|
| Branch is one atomic transaction and leaves the parent untouched | Holds (`hermes_state_history_controls.py`, single `BEGIN IMMEDIATE`) |
| Rewind archives and returns the prompt as a draft | Holds |
| Revision pin is checked inside the writer | Holds |
| Serialized against queued sends and workspace edits | Partly. In-process runs and this chat's root lease are covered; other processes and chats sharing the directory are not. See findings 2 and 3 |
| Receipt is committed in the same transaction as the change | Holds for history. Restore uses a pending receipt followed by a final one, which is honest |
| Replaying a receipt is idempotent | Holds |
| Recovery snapshot is verified before restoring | Holds (`_restore_backup_matches` content-checks every selected path) |
| External edits are kept; stale previews and untrusted paths are rejected | Holds |
| Partial and interrupted outcomes are reported truthfully | Partly. File receipts are honest, but findings 1 and 4 report definite refusals as "unknown" |
| Compressed or ambiguous prompts are refused | Holds |

## Findings

1. **Native write-guard refusals come back as `turn_outcome_unknown`.**
   Severity medium, confidence high, confirmed by probe.
   - Cause: `agent_runtime/operator_history.py` catches only
     `SessionActiveWriteGuardError`, which only session deletion raises. The
     writer guards raise `SessionTurnLeaseLostError`,
     `SessionCompressionInProgressError` and `CompressionSessionClosedError`.
     These fall through to `serve_rpc/operator_history.py` and become -32000
     `turn_outcome_unknown`.
   - Probe: with a live native turn lease, branch and rewind both raised
     `SessionTurnLeaseLostError`. Neither a child nor a receipt was written.

2. **Every `reserve_chat_turn` caller now sits under a non-blocking
   `chat_history_admission_lock`.** Severity medium.
   - Cause: the lock is acquired with `timeout_seconds=0.0` and wraps
     `chat_turn_reservation_lock`, whose own docstring says it is held "around
     no other lock". It covers send, steer, peer execute, and the status and
     stop reservations.
   - Failure: two accepts on one scope at the same moment, or any accept during
     a seconds-long restore, get `chat_turn_lock_unavailable` — "another accept
     for this turn_request_id is still in progress". That reason is wrong,
     because the request ids differ.

3. **Orphaned ACCEPTED receipts block history controls permanently.** Severity
   medium.
   - Cause: `require_history_idle` treats any unsettled ACCEPTED receipt as
     busy. Receipts are settled only in the worker's `finally`, and nothing
     repairs them at boot. `settle_chat_turn`'s docstring says a killed serve
     leaves one "accepted forever".
   - Failure: a serve killed mid-turn blocks rewind, branch and restore on
     that chat for good. A new-chat orphan, scoped to the instance or
     `persona:<id>`, blocks every chat of that instance or persona. The check
     also re-reads every receipt ever written, three times per call.

4. **A busy checkpoint store is not mapped to a refusal.** Severity
   medium-low.
   - Cause: `store_lock` is non-blocking and raises `PruneError`. Preview,
     restore and status do not map it, so restore reports "outcome unknown"
     even though nothing ran.
   - Reverse effect: while a preview holds the profile-wide lock across
     `git add -A` and the diff, another chat's `ensure_checkpoint` silently
     skips its pre-edit snapshot. `record_agent_write` also drops ledger
     entries during that time.

5. **Minor issues.**
   - `CurationState.for_session` now reads the DB and parses `model_config`
     outside the try block that types read failures.
   - Restore enters `history_write_scope` before validating its target, so a
     missing persona id surfaces as "outcome unknown".
   - `history_write_scope` maps lock errors raised anywhere in its body to
     `conversation_busy`, including errors raised after a commit.
   - Files the agent deleted can never be restored: `record_agent_write` skips
     missing files, so the preview marks them `changed_externally`.
   - `hermes_state_history_controls.py` is the only fork-only `hermes_state_*`
     module. It depends on six `SessionDB` private members and has no Seams
     row of its own, so a drift on upstream sync would not be caught.

## Test quality

- **Strong:**
  - source byte-identity after branch;
  - replay and status;
  - warm-actor rehydration through the real registry;
  - the downstream restore suite: human edits, replay never rewriting, partial
    and interrupted receipts, the recovery round trip, foreign projects.
- **The branch kill-mutation is discriminating:** with the digest check
  disabled, the child exists.
- **The rewind kill-mutation is not.** With the digest check disabled, the
  existing `expected_active_ids` pin still refuses the write, so the test goes
  red only on the reason string, and its no-archival assertion passes either
  way. The audit note's claim that the race test proves the digest check is
  therefore false. What the digest actually adds is detecting in-place edits
  to non-target rows, and nothing tests that.
- **Gaps:**
  - no test for `branch_compressed_history_unavailable` or for a real
    compaction carrier;
  - no symlink or junction test;
  - no test of admission-lock ordering or of concurrent accepts;
  - the rewind test never asserts the returned draft;
  - `test_archived_marker`'s negative assertion has no positive control.
