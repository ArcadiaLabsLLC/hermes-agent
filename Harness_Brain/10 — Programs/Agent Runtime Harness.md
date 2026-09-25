---
type: program
program: agent-runtime-harness
status: active
cursor: "2026-09-21 — canon current through the multi-device doc 09 (2026-09-06); every §8.10 stage, RO-1..RO-9, RB-1..RB-9 and prep-cost Stages 6–8 LANDED; owed: one operator boot on the RB-9 build, ten live turns to verify Stage 8's numbers, the Mac half of the CP-9 read, RS Stage 3 (code-tree build-behind) builder running."
latest: "2026-09-21 — the god-file refactor plan landed (042f58edf8); H4 (serve_loop → ServeSession) is the one lane that touches this program's restart fence"
tags: [program/agent-runtime-harness, program]
---

# Agent Runtime Harness

The Hermes-native persona runtime behind Mission Control: personas → durable instances → chat roots → scene actors; realms and workspaces; the office and board; the serve process the launcher talks to; one runtime per machine, paired across devices. **Chat is the only lane** (2026-07-30).

> [!info] Cursor
> `cursor::` see frontmatter — the last landed program and what it still owes.

## Where the truth lives

`skills_cursor::` 2026-09-24 — [Client-neutral session skills](../../docs/downstream/session-skills.md)
reuse the canonical resolver and transcript evidence. Launcher Intelligence is
the first consumer; Mission Control keeps its existing catalog/assignment and
runtime ownership. [Verification limits](../../docs/downstream/session-skills-verification.md).

- **[`docs/agent-runtime-harness/00-index.md`](../../docs/agent-runtime-harness/00-index.md) — the canon. Read first.** Nine domain docs: 01 architecture · 02 data and shapes · 03 transport and wire · 04 boot and lifecycle · 05 chat turn lane · 06 office and board · 07 observability · 08 performance and debt ledger · 09 multi-device runtime. `planned/` = designed, not shipped (106 files incl. field notes); `archive/` = history.
- **The launcher half:** `EterniaLauncher/docs/mission_control/00-index.md` (eight domain docs) and `EterniaLauncher/docs/mission_control/10-multi-device-architecture.md` — read doc 10 first for the multi-device target and ledger.
- **The work queue is the launcher's** `mission-control-queue.md` (both repos). This note carries a cursor, never rows.
- Source map: [[Codebase Map]]. Rules: [[Architecture Invariants]].

## Open programs (each a plan under `planned/`, each with field notes)

| program | plan | state 2026-09-21 |
|---|---|---|
| chat-turn prep cost (pre-admit span, three skill walkers) | `chat-turn-prep-cost.md` | Stages 6–8 landed (`5bacb491c4`); Stage 8's numbers unverified — ten live turns owed; Mac CP-9 read owed; a fourth walker (`used_skills_context` per-name resolve) found by Stage 8 |
| restart drain fence (RL-20 build-behind spawned a second runtime mid-drain) | launcher `runtime-observability.md` + hermes RS-1..7 | Stages 1–2 landed (`114bfd69e7`); Stage 3 builder running |
| boot sweep identity flip (the restart killer) | `boot-sweep-…` RB-1..RB-9 | all landed (`e29b522e1`); owed: one boot on the RB-9 build; a row on bare `HERMES_HOME` as a host root |
| runtime observability RO-1..RO-9 | launcher `runtime-observability.md`, hermes O-h | all on main; killer UNNAMED; RO-1 sidecar names the next one; timeline tool `dart run tool/mission_runtime_timeline.dart` |
| local runtime ownership (rows L/R/W), remote chat parity R-C1..C8, instant pairing D1..D11 | canon 09 + launcher doc 10 | landed; owed operator proofs (held send, real pull, reap, C5 re-run both machines, D3 run #7) |
| local llama agent console | `planned/local-llama-agent-console.md` | design only |
| harness-runtime-model SKILL.md over its 16,384-byte ceiling since 2026-09-03 | — | unrowed; rewritten last from the refactor's field notes |

## Live facts an agent forgets

- The running launcher's serve uses `HERMES_HOME=<store>/profiles/base`, not `alice`. Measuring under alice measures a different runtime.
- Every hermes home defaults to `gpt-5.6-luna` on `openai-codex` since 2026-09-06 (alice: `luna-pro`). A running runtime reads config at boot — reap once to take a change.
- Diag log for chat-turn timing: `%TEMP%/eternia_launcher_diag.log` (launcher side; deleted past 2 MB on open). The hermes ledger is `<store>/mission_chat_turns/*.json`, joined on `phases.anchored_at`, never `started_at`.
- Defender exclusion for `X:/Eternia` exists (2026-09-06); `Get-MpPreference` is blind unelevated — do not read it as proof.
