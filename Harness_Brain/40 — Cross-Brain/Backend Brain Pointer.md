---
type: cross-brain
target: EterniaBackend_Brain
relative_path: "../../../../Unreal Engine/Engine/EterniaBackend/eternia-backend/EterniaBackend_Brain/"
tags: [cross-brain, sibling, backend]
---

# Backend Brain Pointer → EterniaBackend_Brain

Sibling backend child brain. Source-of-truth for Django / Django Ninja API implementation, Keycloak on the backend side, Centrifugo, deployment.

## Vault entry

- Brain Index: `eternia-backend/EterniaBackend_Brain/Brain Index.md`
- Obsidian: `obsidian://open?vault=EterniaBackend_Brain`

```text
../../../../Unreal Engine/Engine/EterniaBackend/eternia-backend/EterniaBackend_Brain
```

## What the runtime consumes from the backend

- Account-scoped device rows (the runtime sheet's devices: backend key + DELETE landed `deca2dea` / `1d0c5393`, deployed to prod 2026-09-03) — hermes side canon 09.
- Realm membership + the git artifact sync contract (parent note; backend enforces membership).
- Keycloak grants for pairing by account (code-free pairing, canon 09).

## Repo facts a hermes session forgets

- **eternia-backend deploys from `deploy`, NOT `main`.** Land `main` fast-forward; never push `deploy` without an order. Its pre-push hook works from Git Bash (~90 s) — no bypass. (`AGENTS.md` §3 there, fixed 2026-09-03.)
- Backend Postgres proof for a cross-stack change: `scripts/backend_postgres_proof.py` here; the API contract packet is written by Backend before Frontend integrates (`harness-dev-delivery` skill).

## When to write to it (vs. here)

Backend implementation and API-provider truth there; how the runtime calls it, and what it owes the runtime, here — as an open question in [[Open Questions for Launcher]] only when the launcher is the one carrying it, otherwise raise it in the backend vault directly.
