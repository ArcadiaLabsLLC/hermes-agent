# A cheap SessionDB lineage stamp, and the two reads it unlocks (design)

Status: PLAN — written 2026-10-15; owner approval owed. Rows (runtime-queue),
one cluster because both need the same missing piece:
- "Windowed transcript reads scan the conversation for every requested window."
- "Native history is re-read from SessionDB and re-filtered against the turn
  ledger on every turn …" (owner RULED 2026-10-10: a reused actor with an
  unchanged `native_revision` hands its messages to the turn; SessionDB stays
  the authority, the revision is the guard).

## In plain English

Two hot paths re-read a whole conversation from the database just to answer a
small question. (1) Showing a long tool output 16,000 characters at a time
reads every message of the chat for every page. (2) Every new turn re-reads the
chat's history even when the agent already holding it in memory is up to date.
Both need a cheap way to ask the database "has this conversation changed since
revision X?" and "give me just this one row". Today the only revision is a hash
of the full read — so checking it costs the read it was meant to save.

## Evidence (tree at `origin/main` 428e2b0dd09)

- Windowed reads: `agent_runtime/persona_chat_history/content.py`
  `read_chat_content` → `_message_text` runs `_safe_curated_messages` over the
  whole session; `_tool_text` walks `_read_raw_messages` (whole lineage,
  `curation.py` l.130–148) to find one `tool_call_id`.
- Turn context: `hermes_cli/harness_parts/persona/chat_turn_commit/run.py`
  `_build_context` (l.107–145) reads `_persona_chat_native_history` then filters
  against the ledger; measured as `context_native_history_ms`; turn `15c73e0c`
  had 168 ms unattributed.
- Revision today: `agent_runtime/persona_chat_continuity/wire.py`
  `native_history_revision` (l.341) = sha256 of the ancestor-inclusive safe
  history — a full read.
- SessionDB (upstream): `hermes_state_messages.py` `get_messages_as_conversation`
  (l.1529, `include_ancestors`, `include_row_ids`, `through_row_id`), private
  `_resume_lineage_ids`; messages are also **updated in place**
  (`agent/transcript_repair.py` content/display updates, `active`/`compacted`
  flips in `hermes_state_messages.py` l.70/852, `hermes_state_history_controls.py`
  l.87). So "max row id + count" is NOT a sound stamp.

## Target shape

- **Stamp:** a fork-owned table `fork_session_revision(session_id PRIMARY KEY,
  revision INTEGER)` plus SQLite triggers on `messages` INSERT/UPDATE/DELETE
  that bump the row's session revision — every writer, upstream or fork, is
  covered without touching upstream code paths. Created by a fork migration on
  connect (`agent_runtime/session_lineage_stamp.py`, through
  `agent_runtime/_upstream_doors.py` for `_resume_lineage_ids`).
  `lineage_stamp(db, root) -> (tip, tuple(revision per lineage session))`.
- **Indexed content lookup:** `lineage_row(db, root, *, tool_call_id=None,
  message_id=None)` — one indexed query across the lineage ids, returning the
  raw row; the caller applies the SAME curation/redaction functions it applies
  today, so policy stays single-owned.
- **Turn hand-off:** the resident actor stores `(native_revision, lineage_stamp)`
  after each turn; `_build_context` compares stamps first and reuses the actor's
  messages only on equality, else reads as today.

## Owner decisions (recommendation first)

1. **Triggers in a fork table vs an upstream column.** Recommend fork triggers
   now (sound across every writer, zero upstream lines) and an upstream door
   draft (`sessions.revision`) for the posting sitting; switch when it lands.
2. **Which content kinds get the indexed path.** Recommend `tool_input` and
   `tool_result` only (their curation is row-local: hidden filter + redaction).
   `message` keeps the full curated read unless a parity test proves its
   curation is row-local too.
3. **Cache?** Recommend none — the row's own wording: no second store.

## Slices (build order)

- **S1 — stamp + triggers + migration.** Killing mutation: drop the UPDATE
  trigger → a test running `transcript_repair`'s content update sees an
  unchanged stamp → red. Positive control: an insert bumps it.
- **S2 — `lineage_row` + tool kinds in `content.py`.** Parity test: for a
  fixture lineage (with compression ancestry and hidden rows), indexed and full
  reads return byte-equal redacted text for every tool id. Killing mutation:
  skip the hidden filter in the indexed path → parity reds.
- **S3 — turn hand-off.** Killing mutation: compare only `tip` (not the
  per-session revisions) → a test that repairs a message between two turns
  reuses stale messages → red. Measure `context_native_history_ms` before/after
  on the same chat; record both.
- **S4 — upstream door draft** for a public lineage revision.

## Blast radius

One fork module + migration, `content.py`, `run.py::_build_context`, the
resident actor's stored state. Write cost: one trigger per message write
(measure in S1 on the stream golden generator; must stay under 2% of write time).

## What it retires

Whole-lineage scans per content window, the per-turn native re-read on a warm
actor, and the "revision costs a full read" contradiction behind the 2026-10-10
ruling.
