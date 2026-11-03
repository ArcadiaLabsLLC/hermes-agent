---
type: queue-archive
queue: fixture-queue.md
program: fixture
month: 2026-11
---

<!-- The closed-row archive grammar (plan
docs/mission_control/planned/QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02.md D2/D3):
one valid archived row per outcome shape and record, each the live line with
its status replaced by ONE outcome segment and its claim mark removed. Shared
contract: hermes and backend copy these lines byte-identically to gate their
own archives. -->

Closed rows of `fixture-queue.md` for 2026-11; appended by the close commits, never edited.

- **`FX-ARCH-DONE` — Done row** · surface · DONE 2026-11-02 3f9c2a1
- **`FX-ARCH-DONE-LONG-SHA` — Done row with a full sha** · DONE 2026-11-02 3f9c2a1b7d4e5f60718293a4b5c6d7e8f9012345
- **`FX-ARCH-DONE-HERE` — Done in the close commit row** · DONE 2026-11-02 here
- **`FX-ARCH-REFUTED` — Refuted row** · REFUTED 2026-11-02 0a1b2c3
- **`FX-ARCH-CLOSED` — Owner-closed row** · CLOSED 2026-11-02: owner — "drop it, the dock covers it"
- **`FX-ARCH-RESULT` — Row with a result** · DONE 2026-11-02 3f9c2a1 · result: red recorded: dropping `|here` made the DONE-here row BAD OUTCOME
- **`FX-ARCH-REVIEW` — Reviewed row** · DONE 2026-11-02 3f9c2a1 · review: owner looked 2026-11-03
- **`FX-ARCH-RULED` — Ruled row kept whole** · group: queue-row-archive · `tool/queue/queue_grammar.dart` · RULED 2026-11-01: one archive per queue · REQUIRES linux · DONE 2026-11-02 3f9c2a1
