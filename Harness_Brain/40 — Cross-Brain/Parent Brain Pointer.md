---
type: cross-brain
target: ArcadiaLabs_Brain
relative_path: "../../../../Unreal Engine/Engine/ArcadiaLabs_Brain/"
tags: [cross-brain, parent]
---

# Parent Brain Pointer → ArcadiaLabs_Brain

Company / product parent brain. Source-of-truth for shared product decisions, cross-project roadmap, shared API contracts, cross-project handoffs, shared agent conventions.

## Vault entry

- Brain Index: `ArcadiaLabs_Brain/Brain Index.md`
- Decisions: `ArcadiaLabs_Brain/Decisions.md`
- Obsidian: `obsidian://open?vault=ArcadiaLabs_Brain`

```text
../../../../Unreal Engine/Engine/ArcadiaLabs_Brain
```

## Notes there that bind this runtime

- `Realm Sync — Server Membership & Git Artifact Sync` — the DevOps Realms cross-project contract (server membership gating + selective git-backed sync of `.hermes` / Mission Control artifacts). Hermes side: `agent_runtime/realm_sync.py`, canon 01 § realm sync.
- `Agent Gateway — Mobile Remote Control` and `Agent Gateway — Wire Spec` — phone observes/commands the desktop runtime via Keycloak + Django grants + Centrifugo relay into `harness serve` (designed 2026-07-08). Hermes side: canon 09, the gateway peers / pairing lanes.
- `Agent Kernel — Cross-Platform C++ Runtime (EAK)`, `Agent QA & Release Doctrine` — read before proposing a runtime that is not this one.

## When to read it

- A decision that affects backend + launcher + runtime (auth flow, realm contract, relay substrate).
- The shared roadmap or scope.

## When to write to it (vs. here)

Write there for cross-project contracts and rulings; write here for how the hermes fork implements or is worked. The parent index routes to hermes only through the two contract notes above — a `Harness Brain` line in its network tree is owed with the launcher's pointer (queue row).
