---
type: queue
program: fixture
status: open
---

<!-- The work-queue row grammar: one valid row per status and per BLOCKED
reason, each `- **`<ID>` — <title>** · …` on one line. Shared contract (plan
docs/mission_control/planned/WORK_QUEUE_BOARD_2026-10-16.md D3, ADR 0025's
2026-10-18 amendment); hermes and backend port these lines to gate their own
queues. -->

- **`FX-READY` — Ready row** · surface · READY 2026-10-16
- **`FX-READY-PLAN` — Ready row with a plan** · READY 2026-10-16: plan `docs/mission_control/planned/WORK_QUEUE_BOARD_2026-10-16.md`
- **`FX-OWNER-DECISION` — Owner decision row** · BLOCKED 2026-10-16: owner decision — Ship the pill read-only? · Recommend: yes, writes wait for an ask
- **`FX-OWNER-SITTING` — Owner sitting row** · BLOCKED 2026-10-16: owner sitting (look at the board at 1280×800 on the desktop)
- **`FX-BACKEND` — Backend row** · BLOCKED 2026-10-16: backend — `PLATFORM-QUEUE-READ` the "queue read model" row
- **`FX-HERMES` — Hermes row** · BLOCKED 2026-10-16: hermes — `RT-SLOTS-SHOW` the "slots.show path" row
- **`FX-UPSTREAM` — Upstream row** · BLOCKED 2026-10-16: upstream — flutter/flutter#12345
- **`FX-ANOTHER-LANE` — Another lane row** · BLOCKED 2026-10-16: another lane — `FX-READY` lane w1016c-mc
- **`FX-DEFERRED` — Deferred row** · DEFERRED 2026-10-16: owner: "after the release" until 2026-11-01
- **`FX-NEEDS-PLAN` — Needs plan row** · NEEDS PLAN 2026-10-16: the read path and card fields
- **`FX-RULED` — Ruled row** · RULED 2026-10-16: one board per repo · READY 2026-10-16
- **`FX-TAKEN` — Taken row** · READY 2026-10-16 · **TAKEN 2026-10-16 w1016c-mc**
- **`FX-CODE-SPAN` — Code span row** · the separator `a · b` inside code · READY 2026-10-16
  - **`FX-NESTED` — Nested row** · READY 2026-10-16
- [ ] **`FX-CHECKBOX` — Checkbox row** · NEEDS PLAN 2026-10-16: whatever
- **`FX-LAUNCHER` — Launcher row** · BLOCKED 2026-10-18: launcher — `FX-TAKEN` the launcher half
- **`FX-ASSIGNEE` — Assigned row** · assignee: persona:alice · READY 2026-10-18
- **`FX-PERSONA-TAKEN` — Persona-claimed row** · READY 2026-10-18 · **TAKEN 2026-10-18 persona:pi_alice_01**
- **`WORK-A2B3C4` — Engine-minted row** · assignee: persona:pi_alice_01 · READY 2026-10-18
- **`FX-SKILLS` — Lent-skills row** · assignee: persona:alice · skills: `git-workflow`, `eternia/qa` · READY 2026-10-19
