---
type: map
tags: [map, codebase]
aliases: [Where does X live]
---

# Codebase Map

"Where does X live?" for the fork-only tree. Upstream's layout (agent loop, gateway platforms, tools, CLI) is `AGENTS.md` § Project Structure — not restated here. Ownership is per [[Fork Boundary Map]].

## The runtime — `agent_runtime/`

| concern | modules | canon doc |
|---|---|---|
| entities + config | `config.py` (runtime config, authority), `store.py` (`RealmStore`, `WorkspaceStore`), `persona_assignments.py` (`PersonaInstanceStore`), `persona_profile_binding.py`, `agent_create.py`, `agent_retire.py` | [01](../../docs/agent-runtime-harness/01-system-architecture.md) |
| data + shapes | `snapshot.py` (the core), `core_cache.py` (fingerprint cache), `state_patches/`, `events.py`, `serde.py` (one authority for wire coercion + atomic JSON), `paths.py` | [02](../../docs/agent-runtime-harness/02-runtime-data-and-shapes.md) |
| transport | `serve_rpc.py` (`_METHODS` registry, `method()` decorator, tiers), `serve_socket.py` (server / client / `SocketOwnerLock`), `stream.py` (frames, folds, Stage-5 demote deferral), `serve_registry.py`, `gateway_peers.py`, `gateway_identity.py`, `gateway_tls.py`, `gateway_announce.py` | [03](../../docs/agent-runtime-harness/03-transport-and-wire.md), [09](../../docs/agent-runtime-harness/09-multi-device-runtime.md) |
| boot | `boot_timeline.py`, `build_stamp.py`, `persona_prewarm.py`, `persona_chat_actor_prewarm.py`, `machine_roots.py`, `harness_doctor.py` | [04](../../docs/agent-runtime-harness/04-boot-and-lifecycle.md) |
| chat turn | `mission_chat_turns.py` (v3 ledger), `chat_turn.py`, `chat_turn_reservations.py`, `profile_runner.py` (`ProfileAgentRunner`), `mcp_admission.py`, `terminal_envelope.py`, `prompt_observability.py`, `runtime_hud.py`, `persona_chat_history.py`, `persona_chat_continuity.py`, `persona_open_chat.py`, `mission_chat_steer.py`, `chat_live_log.py`, `operator_channels.py`, `running_work.py`, `dispatch_store.py`, `dispatch_delivery.py` | [05](../../docs/agent-runtime-harness/05-chat-turn-lane.md) |
| office + board | `office_store.py`, `office_layout_policy.py`, `board_store.py`, `level_sync.py`, `flow_graph_sync.py` | [06](../../docs/agent-runtime-harness/06-office-and-board.md) |
| observability | `prompt_observability.py`, `parity.py`, `tool_turn_history.py`, `progress.py` | [07](../../docs/agent-runtime-harness/07-observability.md) |
| sync | `realm_sync.py` (publish / pull / skill inbox / git), `persona_instance_sync.py`, `persona_config_sync.py`, `skills_inventory.py`, `skill_promotion.py` | [01](../../docs/agent-runtime-harness/01-system-architecture.md) § realm sync |
| sub-packages | `discussions/` (definition/attempt/run stores, native), `local_llama_adapter/` (the launcher's `runtime.local_llama.*` verbs over upstream `hermes_cli/local_runtime` — receipts, turn lease, log cursor, knobs; `planned/local-llama-agent-console.md`), `blueprints/`, `docs/` (five fork notes incl. `upstream_sync_workflow.md`) | |

## The CLI — `hermes_cli/harness.py` + `harness_parts/`

`hermes harness <family> <verb>`. `build_parser` in `harness.py` wires every family; handlers live in `harness_parts/` — real modules since lane H1 (`runtime_commands`, `board`, `office`, `level`, `flow_commands`, `checkpoint_commands`) plus the `harness_parts/persona/` package (lane H3: seventeen modules, one verb family each; its `__init__.py` is the map), see [[Touching the harness CLI]] and `harness_parts/serve.py` (a real module: `serve_loop`, the process main loop) and `harness_parts/gateway_commands.py`. Registered into upstream's parser by `hermes_cli/_downstream_cli.py::build_downstream_parsers`. Profile selection before any import reads the filesystem: `hermes_cli/_profile_bootstrap.py`.

## Tools the agents call — `tools/`

`agent_chat_tool.py` (send / threads / dispatch to a placed agent), `agent_chat_dispatch.py`, `agent_chat_remote.py` (cross-install), `board_tool.py`, `toolset_manifest.py` + `toolset_scan.py` + `downstream_schema.py` (the fork's tool inventory and schema gate — `scripts/emit_harness_tool_inventory.py`).

## Character sheets — `agent/charsheet/`

`pipeline.py` (run, validate, mirrored-art detection), `draft.py` (`CharacterDraft`: directions, rows, states, thumbs, compose), `palette.py`, `revisions.py`, `fake_draftsman.py`. The payload contract with the launcher: `hermes_cli/charsheet_payload_contract.py`, `scripts/dump_payload_contract.py`, `tests/fixtures/charsheet_payload_contract.json`. Program note: [[Charsheet]].

## Skills — `docs/agent-runtime-harness/harness-skills/`

Four canonical skills, installed into every profile by `install_harness_skills_at_boot` (serve boot) and the `.githooks/post-merge` hook: `harness-runtime-model` (the mental model + operating manual; over its 16,384-byte ceiling since 2026-09-03), `harness-dev-delivery`, `harness-qa-verdict`, `harness-charsheet-authoring`. Tests read the installed source; `scripts/verify_harness_skill_install.py` checks the install.

## Tests, fixtures, gates — `tests/`, `scripts/`

See [[Testing & Gates]]. Fixture contracts: `tests/fixtures/hermes_cli_contract.json` (argparse surface), `charsheet_payload_contract.json`, the stream/response fixtures generated by `scripts/generate_agent_runtime_*_fixtures.py`.

## Docs

`docs/agent-runtime-harness/00-index.md` → nine domain docs → `planned/` (106 files: plans + their field notes) → `archive/` (shipped plans, pre-consolidation history). `docs/downstream-development.md` = the fork contract. `docs/agent-handoffs/`, `docs/downstream/` (updater history), `docs/architecture/mcp-expansion*` are small fork additions.

## The live store (this workstation)

`X:/Eternia/.hermes/` — `config.yaml`, `profiles/` (`base` is the launcher runtime's home; `alice`, `neko`, `qa`, `launcher-qa`, `launcher-qa-direct`, `launcher-dev`, `backend-dev`, `gpt-launcher`, `unbounded`, `aliceimagecron`), `agent-runtime/` (the store root: instances, chats, office, board, realms, `mission_chat_turns/`, `serve_instances/`). Every profile is its own `HERMES_HOME`; resolve it at CALL time ([[Architecture Invariants]] rule 1).
