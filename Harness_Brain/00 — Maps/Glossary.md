---
type: map
tags: [map, glossary]
aliases: [Terms, Vocabulary]
---

# Glossary

Fork vocabulary. Upstream terms (session, gateway platform, tool, skill, profile) keep upstream's meaning; canon [01](../../docs/agent-runtime-harness/01-system-architecture.md) is the authority for the entity model.

| term | meaning |
|---|---|
| **Harness** | The Agent Runtime Harness: `agent_runtime/` + `hermes harness …`. The Hermes-native persona runtime behind Mission Control. |
| **Persona** (template) | A declared agent identity (personality, profile binding, skills, MCP declaration). Data, not code. |
| **Instance** (placement) | A durable placement of a persona on a level; owns its chat root, office actor, steering edges. `PersonaInstanceStore`. |
| **Chat root** | The instance's conversation identity (a `HERMES_HOME`-scoped session root). One instance, many chats over time. |
| **Turn** | One operator/agent message → reply. Phases in the v3 ledger: `anchored`, `context_built`, `observability_built`, `write_ahead`, `agent_ready`, `request_assembled`, `provider_first_byte`, finalize. |
| **Pre-admit span** | `request_received → write_ahead`: context assembly + prompt observability. The chat-turn-prep-cost program's subject. |
| **Prewarm** | Building an instance's chat actor (or a snapshot) before it is asked for; the LRU is `max_hot_sessions`. |
| **Serve** | `hermes harness serve`: the long-lived process the launcher talks to. NDJSON frames on stdio + a LAN socket lane. `serve_loop` is its main loop. |
| **Method lane / argv lane** | RPC methods registered in `serve_rpc._METHODS` by manifest (the lane every write verb uses) vs. argv dispatch through `build_parser` (a fallback marked for delete). |
| **Snapshot / core** | The O(world) read model the launcher paints from; built per generation; sections (`agents_readiness`, `events`, `prompt_observability`…). |
| **Core cache** | The fingerprint-keyed persisted core so boot reads a cached core instead of building one (12 s → 0.9 s). |
| **Stream / fold** | The frame stream to the launcher and the negotiated folding of entities into batches; patch frames carry deltas. |
| **Office / actor / surface** | The spatial scene: an actor is a placed persona in a workspace surface; office verbs ride the RPC lane. |
| **Board** | The mission board (cards, columns, idempotent replay). Its lane is not yet migrated. |
| **Realm / workspace** | A realm binds a server + git-backed sync of non-source artifacts; a workspace is the operator's scope inside it. Realm sync = publish / pull / skill inbox. |
| **Install / runtime / paired device / peer** | The multi-device entities (canon 09): one runtime per machine, paired by account grant, dialable addresses, cross-install chat. |
| **Receipt** | A log line or file that PROVES a stage happened (boot timeline, `ready` frame, `[MissionChatTiming]`). Observability contract: receipts, never new envelope keys. |
| **Honesty pair** | An outcome code plus the evidence that backs it; a claim without its receipt is unverified. |
| **Tombstone** | A registry row recording a deleted symbol so it cannot silently return (`test_tombstone_registry.py`). Census: 703+ entries, loops expand literals — never grep-count. |
| **Ratchet** | A baseline list that may only shrink (frozen-home ledger, duplicate-body `_GRANDFATHERED`, size-ceiling grandfather list). Never baseline to pass. |
| **Positive control** | Before a gate or a CHANGE lands, the defect is planted on a throwaway copy and the red is pasted; a control never run is a belief. |
| **Killing mutation** | The specific edit a gate is proven to catch, recorded via `scripts/changed_line_mutation_check.py`. |
| **Field notes** | The running record a lane writes beside its plan (`planned/*-field-notes-<date>.md`); evidence, never a backlog. |
| **Validated scope** | `tests/agent_runtime tests/hermes_cli tests/hermes_state` through `scripts/run_tests.sh` — the suite the 8-worker ruling was proven on. Whole-tree is a different, unvalidated scope (~142 environmental reds). |
| **Contract dump** | A generated fixture of a cross-repo surface (`hermes_cli_contract.json`, `charsheet_payload_contract.json`); the repo that MOVED is the repo that goes red. |
| **Profile / `HERMES_HOME`** | Upstream's per-profile home; the fork resolves it at call time. `profiles/base` is the live launcher runtime's home. |
| **Store root** | `HERMES_AGENT_RUNTIME_ROOT` — the harness's own state (`X:/Eternia/.hermes/agent-runtime` here). |
| **Lane** | A worktree + one builder + one brief; lands one MOVE and one CHANGE commit. |
| **Grandfathered unit** | A file over the 800-code-line ceiling, listed with its count; the list only shrinks. 41 on 2026-09-21. |
| **Seam** | The additive anchor where fork code hooks into an upstream file (`build_downstream_parsers`, `_apply_profile_override`). |
