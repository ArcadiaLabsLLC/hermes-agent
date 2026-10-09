# Warm send-prep batch integration — 2026-10-08

This batch reuses the existing canonical plugin-manager home key, adds bounded exclusive turn-context receipts, and restores four direct tool-token contract cases. Prompt, tool, provider and durability policies are unchanged. The fresh backend warm median is 259.5 ms; the 250 ms target remains unmet.

## Verification

The whole-tree fork landing gate at `3072269227`: 1,070 files, 13,843 passed, two failed, 75 skipped, zero errors; exit 1. Stage 0: 905.3 s, 8 workers, 275 bundles, two solos, three isolated reruns, 98.3% utilization. The interrupted earlier gate is not a pass.

The same failing files on detached merge-base `74a64be15e` reproduce both exact nodes:

- `test_flag_binding_boundary::test_no_handler_collapses_an_absent_flag_into_an_empty_collection`: identical `hermes_cli/bundles.py:72` offender.
- `test_upstream_footprint::test_the_upstream_footprint_never_rises_and_the_fixture_follows_it_down`: both trees have 184 files / 959 deletions / four heavy files, against fixture 176 / 883 / four. Batch increment is zero in every ratchet dimension; its two upstream edits add 13 and four lines to already-carried files. No fixture ceiling was raised.

The full gate's visibility file was red bundled and green alone. Focused ordered phases / timing / visibility bundle comparison found intermittent stdout contamination. Preserved first-pass output on BOTH baseline and batch: 84 passed, the same timing-payload and finish-reason visibility nodes fail `json.loads` with Extra data. Canonical isolated reruns pass all 86 tests. The full gate's different first visibility node was not independently reproduced; its standalone authority passed. The leak remains filed, not fixed or hidden.

Restored coverage and the complete history gate: 31 passed. Positive wire-wrapper control and generation-freeze mutation both turn the new coverage red. Combined PR CI passed history and mutation checks. Fixture tokenizer coverage does not establish production BPE values.

`main` then moved only through relay queue claims; all three owned branches were rebased, retaining those claims and identical product/test bytes. Required tooling is rerun on the rebased batch; the expensive whole-tree gate is not repeated for a queue-only incoming change.

## Integrated live receipts

Local and remote main contain `a43466214c`; PRs 4, 5 and 6 are merged. Rebase tooling: 152 passed / one inherited footprint failure / 11 skipped across nine files; final ruled docs check passes. Combined CI history and mutation checks pass.

Idle-only refresh returned `drain_complete`, zero work dropped/refused, 6 ms. No replacement auto-appeared, so the canonical service verb started the existing base-profile lane. Authenticated probe: PID 17152, boot `52a73302b4fa4866bea9e2b896ab65e8`, commit `a43466214c`, code tree `c45ffab73f5d8ab332b5806e925e05626fde18c3`. Shared skill boot: eight packages, zero refreshed/failed.

Fresh owned instance `personainst_neko_supervisor_agent_a83c6108`, root `persona_chat_personainst_neko_supervisor_agent_a83c6108_45727175a45c`, uses the existing Neko profile. Official reference socket transport called first-class `runtime.chat.message`; eight accepted requests each reached matching exit 0 and visible READY. Resident actor reused on every turn; resolver cached on six warm turns; no tools exercised. No credentials were recorded. Instance deleted through its archive alias after verification; history preserved.

| group | n | acceptance to request sent median / range, ms |
|---|---:|---|
| warm | 6 | 259.5 / 253–263 |
| after-idle | 1 | 441 / 441 |
| cold | 1 | 770 / 770 |

The exact fresh-eight first-class checker exits 0/PASS. Its 900 ms prep budget does not establish the 250 ms target. Mixed last-15 exits 1 due historical failures; preserve both verdicts. No fresh Launcher timing spans or reconnection proof were obtained. The plain reference client lacks the Launcher capability bridge, the chat history is fresh, and effective model is current configured `gpt-5.6-luna` rather than historical `gpt-6-luna`; there is no causal comparison to earlier 388/401 ms medians and no model override was applied.

Warm wall phases, median / range ms: accept to anchor 24 / 23–26; context 47 / 44–51; observability 17.5 / 17–20; agent ready 22.5 / 22–23; outer turn context 69.5 / 66–79; request build 49 / 47–50; client build 3 / 2–3; final send interval 11 / 11–12. Medians are not additive. CPU total median 210.5 (203–437), own CPU 171 (140–187), unattributed CPU 31 (15–31); these are not wall-time parts.

New exclusive warm context: total 68.5 / 66–78; MCP refresh 42.5 / 41–50; hooks 19 / 19; persistence 6 / 6–8; remaining individual parts 0–1 ms. All six complete with no unfinished interval. Turn-keyed prep and laps join directly; each unique same-log following physical window joins its stream gap by physical request ID. That physical turn binding is contextual, not an explicit foreign key.

Hooks include first-party callbacks, H4 tool settling and spill settings. `_collect_pre_llm_call_context` unconditionally loads spill settings; whether active hooks supplied context and the removable cost are not established. Lazy spill configuration is a candidate requiring result-count/cost evidence and parity controls, not a claimed 19 ms saving or a new cache. File the unresolved measurement before another change.

## Live acceptance limits

Refresh must show a new boot identity and the integrated code tree. Fresh service turns must carry resident actor reuse and matching turn/request receipts. A standalone CLI message is not warm-service proof. A reference-client service probe has no Launcher capability bridge; label that route and history gap explicitly. Preserve the original baseline and do not claim causal live savings from unmatched roots.

H4 tool-writer and H11 prewarm ownership remain with sol-runtime. Broader search-provider lookup remains measured but unchanged. Historical evidence: [initial measurements](warm-send-prep-measurements-2026-10-08.md), [attribution proof](warm-turn-context-attribution-2026-10-08.md), [token coverage](warm-prep-token-coverage-2026-10-08.md).

## Attribution pass — 2026-10-08 (opus-w1-sendprep)

Read-only sources: the durable `phases` / `profile_timing` of the eight `warm-prep-*` turns on root `persona_chat_personainst_neko_supervisor_agent_a83c6108_45727175a45c` (six warm, one after-idle, one first), the same turns' `turn_context_receipt` and `send_prep_receipt` log lines in the Neko profile's `agent.log`, and every Dev-persona turn record since 2026-10-06 carrying `context_skill_preload_ms` (n ≈ 48, 11 roots; skill-heavy, history up to ~30 rows). `hermes harness observe turn-timing --check --last 20 --json --since 2d`: warm n=9, `send_prep_total` 228–472 ms. Phase marks are cumulative from `request_received`; `context_built` (45–51) therefore includes accept→anchor (23–26), and the context span proper is 21–25 ms.

| row | warm median / range (n) | owner (file::symbol) | verdict |
|---|---|---|---|
| `context_built` sub-stamps | Neko: history 2 (0–5, grows ~0.6 ms per turn of history), HUD 5 (4–7), signature 2, preload 3 (3–8); sum 11–14 of a 21–25 span (n=8). Dev: history 17–29, preload 73 (38–273). Unstamped inside the span: a SECOND full lineage read + `safe_native_history` + JSON + SHA for `native_revision_before` | `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_RunPhases._build_context` → `agent_runtime/persona_chat_session.py::_persona_chat_native_revision` → `persona_chat_continuity/wire.py::native_history_revision` | CONFIRMED redundant: the revision re-resolved the tip, re-read the ancestor-inclusive lineage just read, and re-ran `safe_native_history` over a list identical to the fed one whenever the journal's abandoned filter drops nothing. FIXED in `1ecc5ed668` (revision hashed from the read; the fed safe list reused when nothing was dropped). Residual ~7–9 ms unstamped on Neko (journal abandoned-id read, relay marker, runtime registry, session model config, builder glue), no single part shown > 5 ms |
| `observability_built` | 17 (17–20) Neko, of which `observability_skill_rows_ms` 15 (14–17); Dev skill rows ~100 | `agent_runtime/prompt_observability.py` (skill rows) | attributed by the existing stamp; skill-row cost scales with the persona's skill set — carried under H2/H6 |
| `agent_ready` (write_ahead→agent_ready) | 22.5 (22–23), n=6 | `chat_turn_commit/run.py::_write_ahead` + `_cross_provider_boundary` (durable write-ahead, START publish, live-log mirror, `executing` transition) then `agent_runtime/profile_runner/runner.py::_admit_mcp_servers` | UNRESOLVED-as-removable: `mcp_admission_ms` 10–11 on every warm turn of a reused actor (the same admitted set registered and torn down per run) + ~11 ms of durable writes the lane may not move. A per-actor admission memo is structural, not a narrow fix |
| hooks span | 19 (19–19), n=6 | `agent/turn_context.py::_collect_pre_llm_call_context` (upstream) → eternia-harness `settle_turn_tools` → `agent_runtime/tool_blocks.py::reprune_turn_agent` → `chat_lane_defer.reapply_chat_lane_defer` | REJECTED (lazy spill config): `tools/hook_output_spill.get_spill_config` measured 1.0 ms warm (median of 30, Neko home, read-only); the move is a non-additive upstream edit for ≤ 1 ms. The span is dominated by the H4 tool settle — all eight turns log a second `tool_search activated (tier 1)` line after the turn-start line and before the receipt, where hooks is the only part over 6 ms — owned by sol-runtime |
| web-search lookup | inside `kwargs` 41 (39–42) Neko, 45–162 Dev | `agent/transports/codex.py::_alias_wire_tools` → `_openai_prefers_native_web_search` → `agent/web_search_registry.get_active_search_provider` (all upstream) | UNRESOLVED-live / CONFIRMED-fixture (codex-warm-prep: 18.3 ms after home-key reuse). Fix needs an upstream door or the held per-process memo PR row; no fork-side edit is additive |
| H2 + H6 skill preload / package checks | Neko 3 (3–8); Dev 73 median (38–273), n ≈ 48 since 10-06 | `agent_runtime/mission_chat_turn_context.py::_resolve_skill_preload` → `agent/skill_commands.py::build_preloaded_skills_prompt` → upstream `skill_view` | CONFIRMED live on the skill-heavy persona (H2 reproduces on Dev, not on Neko). The measured redundancies (two frontmatter parses per load, usage write) sit in upstream `skill_view` / a durable write; no fork-owned narrow fix. H6 signature 2–5 ms stays below the bar |
| H7 request build | 48 (46–50) Neko = kwargs 41 + middleware 4 (3–6) + preflight 1; lead-in, redecorate, observe-tools, hook 0 | `agent/transports/codex.py::ResponsesApiTransport.build_kwargs` (upstream), `persona_turn_binding.capture_final_request_tools` | SPLIT: kwargs is ~85% of the span on every warm turn; within kwargs the web-search selection is the one fixture-confirmed share, the rest (tool JSON / input assembly) is upstream and unsplit by receipts |

Fix (fixture savings only, no live claim): on a real `SessionDB`, history read + fed safe pass + revision, A/B/A/B medians of 25 — 16 rows 3.8/2.3/6.0/2.8 ms, 80 rows 28/15/33/18 ms, 240 rows 93/35/73/42 ms. A matched live before/after receipt is owed (`context_built` minus `context_native_history_ms` on a Dev chat of ≥ 20 rows).
