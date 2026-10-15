---
type: open-questions
target: launcher
tags: [cross-brain, open-questions, launcher]
---

# Open Questions for Launcher

Things the runtime needs from the launcher side that are not decided or not yet run. Each: the question, what it blocks, whose call. Mirror each in the launcher's Mission Control queue so launcher agents see it natively; mark resolved with `status:: resolved` + date.

## Open

### Q1 — Which verbs does the launcher still lower to argv?

- **Status:** open.
- **Blocks:** the refactor plan's §4.2 deletions (argv fallback lanes marked for delete by [[0003 — RPC route first]]); the CLI contract fixture changes with each deletion.
- **Detail:** grep the launcher for `args_not_carried` and the method-lane manifest; rows where a method exists and the launcher no longer lowers are deletions on the hermes side, in the same wave as the launcher's re-vendor.
- **Whose call:** the operator, per row.

### Q2 — The Mac half of the CP-9 read (chat-turn prep cost)

- **Status:** open since 2026-09-08.
- **Blocks:** Stage 9 of `planned/chat-turn-prep-cost.md` (its gate reads off the re-take); Stage 8's numbers are unverified until ten live turns are taken on both machines.
- **Detail:** the Mac can pull now (hermes ≥ `5bacb491c4`); the `rt_*` timing line and `mission_runtime_timeline` are the instruments.

### Q3 — C5 re-run on both machines (remote chat parity)

- **Status:** open since 2026-09-06.
- **Blocks:** closing R-C1..C8; the Mac must be on hermes ≥ `28e502e286`.
- **Detail:** send / steer / new-chat from the Mac's console through the method lane; diag log `%TEMP%/eternia_launcher_diag.log`.

### Q4 — Operator field proofs the multi-device program still owes

- **Status:** open.
- **Blocks:** nothing on the hermes side; the launcher's doc 10 ledger rows.
- **Detail:** held send, real pull, reap; D3 run #7 (collapsed Network row, `rule present (Python)` expanded); one boot on the RB-9 build; one boot on the H4 build when it lands.

## Resolved

(none yet)
