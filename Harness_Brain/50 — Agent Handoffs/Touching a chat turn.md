---
type: handoff
program: agent-runtime-harness
tags: [handoff, program/agent-runtime-harness]
---

# Touching a chat turn

For any change on the path from a message arriving at `hermes harness persona instance … chat message` (or the `runtime.chat.*` RPC methods) to the reply leaving. Reach for this before touching `_cmd_mission_chat_message`, `_mission_chat_commit_turn`, `profile_runner`, `prompt_observability`, `mcp_admission`, `mission_chat_turns` or the prewarm.

> [!important] The turn's contract is the v3 ledger record, and it is byte-compared
> `<store>/mission_chat_turns/*.json` carries `phases` (`anchored_at`, `context_built`, `observability_built`, `write_ahead`, `agent_ready`, `request_assembled`, `provider_first_byte`, finalize) and `profile_timing`. A change that moves a mark or adds a key is a contract change; the launcher's `rt_*` timing line and `mission_runtime_timeline` read these marks. Join the log on `phases.anchored_at`, never `started_at` (the write-ahead persist stamp, 0.9–3.2 s later).

## Read order

1. [`docs/agent-runtime-harness/05-chat-turn-lane.md`](../../docs/agent-runtime-harness/05-chat-turn-lane.md) — admission and guards, the turn-phases contract, model cascade, tool posture, MCP admission, envelope grants, budgets.
2. `planned/chat-turn-prep-cost.md` §0 — the measured pre-admit span (906 ms uncontended, 2.8–3.2 s under led builds) and the three skill walkers (`skill_utils._skill_root_registry` ×4 per turn, `_installed_skill_catalog` 15 s TTL, `skills_inventory.build_shared_catalog` content-hashing every shared skill every turn) — plus the fourth walker Stage 8 found (`used_skills_context` resolving one name at a time).
3. [`07-observability.md`](../../docs/agent-runtime-harness/07-observability.md) — which receipt proves which phase.

## Hard rules

- Observability lands as log receipts, never as new envelope keys.
- The prewarm's yield and Stage 5's demote deferral read `profile_runner._ACTIVE_RUNS`, incremented at `ProfileAgentRunner.run()` — AFTER `write_ahead`. The pre-admit span is invisible to both by construction; do not "fix" a slow pre-admit by touching them.
- MCP admission = the profile declaration ([[0009 — Profile declaration is the sole MCP admission authority]]).
- `resident_actor_reused=1` is the prewarm's receipt; `builds_overlapped` and `visibility_bundle_builds` are the contention receipts. Quote them in any perf claim.
- A test that waits > 30 s declares its own `pytest.mark.timeout`.

## Where things are

- Handler: `hermes_cli/harness_parts/persona/chat_turn_message.py::_cmd_mission_chat_message` → `persona/chat_turn_commit::_mission_chat_commit_turn` (lane H3 split `persona_commands.py`; the package `__init__.py` is the map).
- Runner: `agent_runtime/profile_runner/runner.py::ProfileAgentRunner._execute_agent_run`.
- Ledger: `agent_runtime/mission_chat_turns.py`; live log `agent_runtime/chat_live_log.py`; history/curation `persona_chat_history.py`; continuity (clarify tickets, mint receipts) `persona_chat_continuity.py`.
- Tests: `tests/agent_runtime/test_mission_chat_*.py`, `test_profile_runner.py`, `test_persona_chat_history_curation.py`.
