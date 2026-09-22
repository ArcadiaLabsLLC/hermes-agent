---
type: cross-brain
target: Launcher_Brain
relative_path: "../../../../Unreal Engine/Engine/Launcher/EterniaLauncher/Launcher_Brain/"
tags: [cross-brain, sibling, launcher]
---

# Launcher Brain Pointer → Launcher_Brain

Sibling launcher/frontend child brain. Source-of-truth for the Mission Control SURFACE (office scene, chat panel, board, read model), the Flutter launcher, Stage C QA, and **the launcher half of the Mission Control work queue** (the hermes half is [[runtime-queue]]).

## Vault entry

- Brain Index: `EterniaLauncher/Launcher_Brain/Brain Index.md`
- Obsidian: `obsidian://open?vault=Launcher_Brain`

```text
../../../../Unreal Engine/Engine/Launcher/EterniaLauncher/Launcher_Brain
```

(from this vault's root: `../../../Unreal Engine/Engine/Launcher/EterniaLauncher/Launcher_Brain`; the launcher repo itself is `X:/Unreal Engine/Engine/Launcher/EterniaLauncher` — NOT a sibling of hermes-agent.)

## When to read it

- Before any Mission Control work: `10 — Programs/Mission Control.md`, then `docs/mission_control/00-index.md` and `10-multi-device-architecture.md`.
- To file or claim work on the SURFACE: `20 — Active Initiatives/mission-control-queue.md`. Runtime work whose fix is in this repository is [[runtime-queue]] here.
- For the refactor method: `docs/mission_control/planned/mission-control-refactor-program.md`, `wave4/EXEC_CARD.md`, `docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`, `docs/tooling/AGENT_WALL_TIME_2026-09-18.md`.
- For the launcher's heavy-command discipline (slot wrapper, bundled tier): its `CLAUDE.md` § Commands.

## When to write to it (vs. here)

| Write **here** (Harness_Brain) | Write **there** (Launcher_Brain) |
|---|---|
| fork boundary, upstream sync, the repo's gates and suite | anything about the launcher's code or its tests |
| runtime program cursors, hermes-side handoffs, Mission Control rows whose fix is in hermes ([[runtime-queue]]) | Mission Control rows whose fix is in the launcher |
| ADRs about how the hermes repo is worked | ADRs about the surface, the vault network, work tracking (ADR 0025 is theirs; we adopt it) |
| open questions FOR the launcher ([[Open Questions for Launcher]]) | the launcher's open questions for backend/parent |

## Owed

The launcher's `40 — Cross-Brain/` has no pointer back to this vault yet (row in [[fork-hygiene-queue]]).
