# Chat-turn prep cost — running record of the 2026-09-07 re-arm (hermes half)

Field notes for [`chat-turn-prep-cost.md`](chat-turn-prep-cost.md) Stages 6–10. This file is written by whoever builds a stage, in the repo the stage stands in (the launcher half of Stage 6 — the `rt_write_ahead_ms` clause and the fixture mirrors — writes its own notes beside `EterniaLauncher/docs/mission_control/planned/runtime-observability.md`). The skill, if one is written, is written LAST from these notes.

## 0. The read that re-armed the plan (Fable, 2026-09-07, read-only)

What was read and how, so the next reader can re-take every number in the plan's §0 without this session:

- **Ledger:** `<store>/mission_chat_turns/persona_chat_personainst_neko_supervisor_agent_f6844ba8_*.json` — the three 07:48–07:49Z turns (root `…894297972f70`) and the 2026-09-06 turns (roots `…115b37660a88`, `…3d6466fce9a8`, `…a9f7d06394ef`, `…cd75c54589eb`, `…6707159dd4c8`). Table script: a plain loop over each record's `phases` and `profile_timing`; the join key for the log is `phases.anchored_at`, NOT `started_at` (§0 preamble of the plan — `started_at` is 0.9–3.2 s later, it is the write-ahead persist stamp).
- **Log:** the neko profile's `logs/agent.log`, pid 28184 (build `42a07c5dfa`, register row `serve_instances/28184.json`, `hermes_home` = the store root's `profiles/base`), lines 03:48:45–03:49:45 local. The prewarm line, the eight `snapshot_build_core` lines with their `sections_top`, the six `snapshot_agents_readiness walk_ms=` lines, the three `snapshot_build_deferred` lines, the three `API call #1 … ttfb=` lines, and the `never_converged … diff=chat_turn_reservations/…` warning.
- **Launcher:** `[MissionChatTiming]` for this morning is unrecoverable — the diag log is deleted on open past 2 MB (`EterniaLauncher/lib/core/telemetry/diag_log_file.dart`) and today's file opened at 13:15:44Z; the receipts file (`diagnostics/mission_transport/receipts.jsonl` under application support) carries no chat-timing kind. The 2026-09-06 lines quoted in `runtime-observability.md` §0.4 were joined instead (plan §0.4).
- **Sandbox profile:** a robocopy of the live root minus `cache`, `lsp`, `logs`, `audio_cache`, `image_cache`, `*_archive`, `migration_backups`, `curator`, `sandboxes`, `events.jsonl` and `*.lock` (2.8 GB; 78 MB of locked files skipped); `HERMES_HOME` → `<copy>/profiles/base`, `HERMES_AGENT_RUNTIME_ROOT` → `<copy>/agent-runtime`, `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA` → `<copy>/userhome`; interpreter = the serve's own (the register row's chain). The script imports `hermes_cli.harness`, then calls, in the handler's order: `load_agent_runtime_config`, `_persona_by_id`, `_default_persona_session_db`, `PersonaInstanceStore().ensure_for_personas(ensure_persisted_personas(cfg))`, `store.get(instance)`, `apply_instance_model_overrides`, `_resolve_chat_model_override(requested_override=None)`, `_chat_effective_model_payload`, `_persona_chat_existing_turn`, `mission_chat_turn_record`, `_persona_chat_native_tip`, `_persona_chat_native_history`, `mission_chat_turn_records(session_id=)`, `_persona_chat_native_revision`, `_session_model_config`, `permission_options_for_chat`, `chat_lane_bundle_key_material`, `chat_lane_bundle`, `build_mission_chat_turn_context(agents_file=None, surface_prompt="")`, `mission_chat_prompt_observability(skill_resolver=None)`, `runtime_context_envelope`, `instance_store.update`; each wrapped in `time.perf_counter`, the two builders under `cProfile` on the cold pass and on the TTL-expired pass. Passes: cold → warm immediately → warm immediately (run 1); cold → warm immediately → warm after 17 s (run 2). The numbers in plan §0.3 are run 1's cold and immediate-warm columns and run 2's 17 s column; run 2's cold column read 595 / 339 / 619 for the bundle / context / observability (OS file cache warm from run 1), which is why the plan quotes run 1 for "cold".
- **Not run:** no serve started, no chat turn sent, nothing written under the live root; the write the script performs (queued-skill consume, model-override persist, instance update, the sandbox SessionDB open) landed in the copy.

## 1. Open at re-arm time — what the plan could not measure and says so

- The Mac's ledger (its `write_ahead`, sub-spans, build cadence) — Stage 6 is what makes it a one-grep read.
- Which bundle key component moves on a quiet live turn (`visibility_bundle_builds`=1 on all 15 turns since 08-29) — Stage 6 item 3.
- The GIL share of the prewarm's 5,750 ms (its client closes and probes are I/O-bound; its tool-defs build and `tool_search` activation are not) — Stage 6's `prewarm_overlapped`.
- Defender / disk / filesystem `stat` cost differences between the machines — not evidenced, not claimed.

## 2. Stage 6

(builder writes here)

## 3. Stage 7

## 4. Stage 8

## 5. Stage 9

## 6. Stage 10
