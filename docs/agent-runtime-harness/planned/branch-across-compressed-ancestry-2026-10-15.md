# Branching a chat whose history was compressed (design, refreshed)

Status: PLAN — written 2026-10-15; owner approval owed (one owner question,
open since 2026-10-10). Row: runtime-queue, "Extend lossless prefix branching
across native compressed ancestry". Refreshes
`docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.03,
which was gated on PR #7 — that code is now on `main`.

## In plain English

In the Console you can branch a conversation at any message: a new chat starts
with everything before that point. When a long chat has been compressed (hermes
moved it into a fresh "tip" session and summarised the old part), branching is
refused today, because copying only the tip would silently lose the earlier
part. This plan makes branch copy the **whole** visible history across the
compressed ancestors, in one transaction, without touching the original chat.

## Evidence (tree at `origin/main` 428e2b0dd09)

- The refusal: `agent_runtime/operator_history.py::_plan` (l.150–153) refuses
  `branch_compressed_history_unavailable` when `target["tip"] !=
  params["session_id"]`; `_target` addresses rows on the tip's repaired
  projection.
- The door: fork-owned `hermes_state_history_controls.py::branch_before_message`
  (l.109–156) — ONE transaction: guards (active turn lease, compression lock),
  `check_history_digest` on the source, copy of session settings, clone of the
  source session's **active** rows before the target (`_clone_message_rows`),
  counts, receipt. It reads only one session id, so an ancestor's rows are
  never copied — which is why the refusal exists.
- Lineage helpers already used here: `_resume_lineage_ids`
  (`archived_history_message_ids`, l.95), public lineage read
  `hermes_state_messages.py::get_messages_as_conversation(include_ancestors=True,
  include_row_ids=True)`; compression archives rows with `active = 0,
  compacted = 1` (`hermes_state_messages.py` `_ARCHIVE_ACTIVE_SQL`).
- Upstream's own `/branch` spans compression by copying the DISPLAY projection
  (`tui_gateway/methods_session_branch.py::_branch_source_history`), per D2.03.

## Target shape

- `branch_before_message` takes the **chat root** and resolves the lineage
  inside the transaction: `ids = _resume_lineage_ids(root)` (root → tip).
- Prefix = the DISPLAY rows of the lineage in order (ancestors' rows including
  compaction-archived ones, deduped exactly as the display read dedupes), cut
  before the target row (or after it for `after_reply`), with tool call/result
  pairs kept whole. The target may sit in any lineage session (row ids are
  global).
- The digest guard covers the lineage (digest per session id, combined), so a
  compression that rotates the tip between preview and apply refuses
  `history_changed` rather than branching a moved history.
- Child rows are inserted `active = 1, compacted = 0` (the child starts
  uncompressed); the source sessions get no write at all (digest proven equal
  before/after).
- `_plan` drops the compressed refusal; a target NOT in the lineage still
  refuses (`target_unavailable`).

## Owner decisions (recommendation first)

1. **The child starts uncompressed with the full display history** (recommended,
   same as upstream's TUI `/branch`; its first turn recompresses if needed),
   vs inheriting the summary + recent tail (smaller first turn, loses the
   re-expandable history). This is the D2.03 question still owed.
2. **Child's `parent_session_id`.** Today it is set to the source. Recommend
   keeping that (branch sessions are exempt from the lineage walk — the walk
   follows only `end_reason = 'compression'` parents) and pinning the exemption
   with a test, instead of D2.03's "unset" — no wire or UI change.

## Slices (build order)

- **S1 — lineage prefix in the door.** Test fixture: root (ended by
  compression) → tip, target in the tip and target in the root. Assert the
  child's rows byte-equal the display projection before the target. Killing
  mutation: read only `session_id` (today's code) → ancestor rows missing →
  red.
- **S2 — lineage digest.** Killing mutation: digest only the tip → a test that
  compresses between preview and apply branches anyway → red.
- **S3 — tool correspondence.** Fixture with a tool call in the root and its
  result in the tip around the cut; assert pairs stay whole. Killing mutation:
  cut by row id without pairing → orphaned tool result → red.
- **S4 — lifecycle.** Source digests equal before/after; a lineage read of the
  root never reaches the child. Killing mutation: give the child
  `end_reason='compression'` linkage → the root's ancestor read returns child
  rows → red.
- **S5 — drop the refusal in `_plan`**; the Console offers branch on compressed
  chats (launcher already renders `_branched_from`; no launcher change).

## Blast radius

`hermes_state_history_controls.py` (fork-owned), `agent_runtime/operator_history.py`,
their tests. No upstream file; no launcher change.

## What it retires

The `branch_compressed_history_unavailable` refusal and the last history action
the Console cannot perform on a long (compressed) chat.
