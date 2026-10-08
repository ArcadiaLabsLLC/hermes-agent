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
