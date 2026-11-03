---
type: queue-archive
queue: fixture-queue.md
program: fixture
month: 2026-11
---

<!-- One archived row per failure arm of the closed-row archive grammar; each
row is otherwise valid, so only its own arm can catch it. -->

- **`FX-ARCH-LIVE-STATUS` — Live status on an archived row** · DONE 2026-11-02 3f9c2a1 · READY 2026-11-02
- **`FX-ARCH-NO-OUTCOME` — Archived row with no outcome** · surface · `tool/queue/queue_grammar.dart`
- **`FX-ARCH-TWO-OUTCOMES` — Archived row with two outcomes** · DONE 2026-11-02 3f9c2a1 · REFUTED 2026-11-02 0a1b2c3
- **`FX-ARCH-CLAIM` — Archived row keeping its claim** · DONE 2026-11-02 3f9c2a1 · **TAKEN 2026-11-02 w1102a-x on box-1 as nekwo in wt-x**
- **`FX-ARCH-BAD-SHA` — Archived row with a bad sha** · DONE 2026-11-02 XYZ1234
- **`FX-ARCH-CLOSED-NO-OWNER` — Owner close without owner** · CLOSED 2026-11-02: dropped
- **`FX-ARCH-TWO-RESULTS` — Archived row with two results** · DONE 2026-11-02 3f9c2a1 · result: one · result: two
