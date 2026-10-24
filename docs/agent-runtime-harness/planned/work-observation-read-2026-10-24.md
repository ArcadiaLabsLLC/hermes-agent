# Work observation read — 2026-10-24

Row `RT-WORK-OBSERVATION-READ` (runtime queue). Built by lane w1024t-hermes the same day.

## Problem

`runtime.work.capabilities` provisions (creates, promotes, moves the default brain) and
`runtime.work.list` / `inspect` normalize the default brain and `Writer.sync` every board (worktree add,
fetch, `reset --hard`, `clean`) before reading. A passive reader — the Projects TODO preview — must see
the same rows through the same WorkScope, board discovery and row projection without any of that.

## Decisions (ruled 2026-10-24, owner standing instruction "go with recommendations")

1. **Capability negotiation** — a flag on the existing methods, not new methods: `observe: true` on
   `capabilities`, `list`, `inspect`; `capabilities.observe` lists the operations that take it. A caller
   checks the list before passing the flag; an older runtime ignores the unknown key and acts, so a
   reader that must not mutate refuses to call when the list is absent.
2. **Same authority** — the flag rides the same `authorize_call(TIER_CONSOLE)`, install id and owner
   check; there is no second read path to authorize. Only a literal `true` observes.
3. **What is read** — hermes's EXISTING worktree of each board, as it stands. No fetch (a fetch into
   hermes-owned worktrees stays explicit, through an ordinary read). A board with no worktree yet is
   listed `readable: false` with no queues, never a silent empty board.
4. **Honest staleness** — `stale` is true unless every read worktree's HEAD equals its local tip
   (`Writer.at_tip`, two `rev-parse`s). "Not stale" means "at the last fetched tip", never "at the remote".
5. **Default-brain words** — the ordinary words, plus what the lifecycle would do next: `missing` (a full
   call would create the brain) and `move_pending` (a full call would move its rows into the repo brain).
6. **Proof** — tripwires on every mutating door (`normalize_default_brain`, `ensure_default_brain`,
   `Writer.sync` / `_ensure_worktree` / `apply`) plus a byte digest of the store root before and after,
   across capabilities, list and inspect; a positive control shows the unflagged call still creates.

## Built

`agent_runtime/work/store.py::observed`, `agent_runtime/work/service.py::_observed_brain_state`,
`agent_runtime/work_store/writer.py::Writer.at_tip`; wire in `03-transport-and-wire.md` § Work;
tests `tests/agent_runtime/test_work_observation_read.py`.
