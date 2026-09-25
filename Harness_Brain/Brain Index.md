---
type: moc
aliases: [Index, Home, Brain, Harness Brain]
tags: [moc]
---

# Harness_Brain Index

Child brain of the **Hermes Agent fork** (`ArcadiaLabsLLC/hermes-agent`, fork of `NousResearch/hermes-agent`) for **Arcadia Labs / Eternia**. Thin navigation, decisions, and handoff layer on top of [`docs/agent-runtime-harness/00-index.md`](../docs/agent-runtime-harness/00-index.md) (the runtime canon) and [`docs/downstream-development.md`](../docs/downstream-development.md) (the fork's working contract).

> [!tip] Read me first on hermes work
> Then jump out to the canon for architecture, wire, boot, chat-turn and observability truth — this brain never duplicates it. Upstream's own guide is [`AGENTS.md`](../AGENTS.md); the fork's session rules are [`CLAUDE.md`](../CLAUDE.md).

## Brain network

```text
X:/
├── Unreal Engine/Engine/
│   ├── ArcadiaLabs_Brain/                    parent: product + cross-project
│   ├── EterniaBackend/eternia-backend/
│   │   └── EterniaBackend_Brain/             sibling: Django/API
│   └── Launcher/EterniaLauncher/
│       └── Launcher_Brain/                   sibling: the Mission Control SURFACE + its queue
└── Eternia/hermes-agent/
    └── Harness_Brain/                        ← you are here: the runtime + the fork
```

- Sibling (launcher): [[Launcher Brain Pointer]] — the launcher half of Mission Control's queue lives THERE; the hermes half is [[runtime-queue]] here.
- Parent: [[Parent Brain Pointer]]
- Sibling (backend): [[Backend Brain Pointer]]

## Routing

| Need | Look |
|---|---|
| "Is this file ours or upstream's?" | [[Fork Boundary Map]] |
| "Where does X live in the fork?" | [[Codebase Map]] |
| "What's a hard rule?" | [[Architecture Invariants]] |
| "Term I don't know?" | [[Glossary]] |
| Per-program cursor + entry | `10 — Programs/` — [[Agent Runtime Harness]] · [[Mission Control]] · [[Upstream Sync]] · [[Downstream Refactor]] · [[Charsheet]] |
| **"What is LEFT?"** | [[TODO]] → the queues. Mission Control's hermes half is [[runtime-queue]] (split fork-owned / seams / upstream-owned); its launcher half is the launcher's `mission-control-queue.md`; fork-hygiene rows are [[fork-hygiene-queue]]. |
| What's mid-flight | [[Initiatives Index]] |
| Why we chose X | [[Decisions Index]] |
| Cross-brain coordination | [[Launcher Brain Pointer]] · [[Parent Brain Pointer]] · [[Backend Brain Pointer]] · [[Open Questions for Launcher]] |
| Pre-task primer | [[Handoffs Index]] |
| Run / test / gates / gotchas | [[Build & Run]] · [[Testing & Gates]] · [[Known Pitfalls]] |
| Starting a new note | [[Templates/README\|Templates]] |

## Programs

[[Agent Runtime Harness]] · [[Mission Control]] · [[Upstream Sync]] · [[Downstream Refactor]] · [[Charsheet]]

## Source-of-truth routing

- `docs/agent-runtime-harness/` owns runtime architecture, data shapes, wire, boot, chat turn, office/board, observability, performance ledger, multi-device. Nine domain docs; `planned/` = designed, not shipped; `archive/` = history, not truth. Always cite there, never restate.
- `docs/downstream-development.md` owns the fork's working contract: profile-safe code, the test runner and its validated scope, the contract dumps, the unattended report, worktree discipline.
- `AGENTS.md` is upstream's development guide (the fork appends one pointer line to `docs/downstream-development.md` and `CLAUDE.md`). `CLAUDE.md` is fork-owned and carries session rules (subagent briefs, repo facts).
- **This brain** owns: navigation, the fork boundary as a MAP, decision rationale (ADRs), cross-brain coordination, in-flight snapshots, handoff primers, operational gotchas.
- **The entry point for "what is left?" is [[TODO]]** — pointers only. Mission Control's queue is split by repository: the hermes half is [[runtime-queue]], the launcher half is the launcher's `mission-control-queue.md` (rule: [[0012 — The hermes half of Mission Control is queued here, split by ownership]], amending [[0011 — One brain per repo, one Mission Control queue in the launcher]]).
- Session memory (`~/.claude/projects/X--Eternia-hermes-agent/memory/`) is per-machine, per-operator scratch. Anything durable graduates from there into this brain or the canon.

## Maintenance

After each meaningful landing:
1. Touch the relevant program note's `cursor::` field.
2. File findings into the queue on arrival (never batch into a wrap-up); an ADR when a ruling was load-bearing.
3. Keep notes ≤ ~80 lines — link out to `docs/` for detail.
