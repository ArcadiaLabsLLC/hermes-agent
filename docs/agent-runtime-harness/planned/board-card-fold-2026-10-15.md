# A `board_card` fold, produced inside `board_lock` (design)

Status: PLAN — written 2026-10-15; owner approval owed. Row: runtime-queue,
"board_card fold: the `runtime.board.*` twins ack but publish no fold; a fold
needs its producer inside `board_lock` (board-surface-rpc-lane.md rule 3)".

## Build status (lane h4-seeds, 2026-10-16)

BLOCKED at S0: the measurement is a live end-to-end timing (ack, full core
received, Launcher repaint) on a running serve and Launcher, which a build lane
does not start; it needs the owner's machine. S1–S4 are gated on its number, so
nothing was built.

## In plain English

Board writes now have fast RPC twins (build-1011-C4), but after each write the
Launcher still gets a whole fresh snapshot ("full core") because no small
"this one card changed" patch is published. The office solved the same problem
with a patch emitted while its store lock is held, so patches can never arrive
out of order. This plan does the same for board cards — **if** a measurement
says the full-core refresh is slow enough to matter. The earlier plan for the
board said so explicitly: measure before building.

## Evidence (tree at `origin/main` 428e2b0dd09)

- RPC twins, no fold: `agent_runtime/serve_rpc/board.py` (six `@method`s,
  module docstring "No fold here (rule 3)").
- Rules: `docs/agent-runtime-harness/planned/board-surface-rpc-lane.md` § "Gate,
  if this is picked up" — (1) measure first; (2) office shape is the template;
  (3) a board fold needs a paired producer inside the store lock, with an
  accounted-refresh escape for writes it cannot express.
- Template: `agent_runtime/office_store/patches.py::_emit_surface_patch`
  (inside `office_lock`, before the paired domain event; best-effort — a
  missing patch is a missing promotion, never a lost write) and
  `agent_runtime/state_patches/office.py`.
- Lock: `agent_runtime/locks.py::board_lock` (l.161).
- Coverage: `agent_runtime/patch_coverage.py` l.33 / l.706 — board writes are
  uncovered, so any batch with one demotes to a full core.
- Projection: `agent_runtime/snapshot/boards.py::board_card_row` (l.48) — the
  row a patch would carry; `board_summary_row` (l.92) holds derived counts.
- Launcher consumer pattern: `EterniaLauncher/lib/features/mission_control/data/wire/mission_fold_declaration.dart`
  (`office_surface` entity + `office_surface_fold` capability token).

## Target shape

- **Producer:** `agent_runtime/state_patches/board.py::emit_board_card_patch`,
  called from each `BoardStore` write path **inside `board_lock`** and before
  the paired `board.card.*` event; payload = `board_card_row(card)` plus the
  card's board id and post-write revision; archive emits a tombstone row.
- **Coverage:** `patch_coverage.py` treats `board.card.*` as covered only when
  paired with its patch in the same batch; `resolve_conflict` and any write
  that changes board summary counts in a way the client cannot derive emits an
  accounted refresh (full core), never a silent patch.
- **Negotiation:** capability token `board_card_fold`; clients without it keep
  full cores (same as `office_surface_fold`).
- **Launcher:** a `board_card` fold that subset-merges cards by id, gated on
  revision (older revision ignored), and recomputes the summary counts locally.

## Owner decisions (recommendation first)

1. **Build it at all?** Recommend **measure first** (S0): if a board write's
   full-core refresh is under the office's gesture tolerance, close the row as
   "correct as-is" with the number. Board writes are operator-paced.
2. **Summary counts.** Recommend the client recomputes per-board counts from
   folded cards; if the snapshot ever truncates cards, those batches demote
   (the office actor-patch truncation guard is the precedent).
3. **Pairing.** Recommend one paired hermes+launcher landing (hermes producer
   behind the token is inert until the launcher declares it, so hermes may land
   first, but the proof needs both).

## Slices (build order)

- **S0 — measure.** Time a card move end to end over the RPC twin (ack →
  full core received → repaint) on a realistic board; record in this doc.
  Stop here if under tolerance.
- **S1 — producer inside the lock.** Killing mutation: emit the patch after
  releasing `board_lock` → an interleaving test (two writers, forced order)
  observes a lower revision at a higher event-log offset → red.
- **S2 — coverage + token.** Killing mutation: mark `board.card.move` covered
  without its patch → the coverage test for an unpaired event reds.
  Positive control: a client without the token still receives a full core.
- **S3 — launcher fold** (`EterniaLauncher/lib/features/mission_control/data/`).
  Killing mutation: accept an older revision → the out-of-order fold test reds.
- **S4 — live proof:** move a card in the Launcher; the transport receipts show
  a patch, not a full core.

## Blast radius

Hermes: `board_store` write paths, `state_patches/`, `patch_coverage.py`, the
manifest's capability list. Launcher: fold declaration, read-model patch
application, board view model. No change to the RPC verbs or their acks.

## What it retires

The board's full-core demote on every write (if S0 says it matters), and the
last write surface in the office/board pair with no fold.
