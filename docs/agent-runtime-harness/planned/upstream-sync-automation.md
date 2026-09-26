# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY**.

## Frozen inputs — 2026-09-26

- F fork main: `ccbe8bbd10d55f4d2b5630e55bd13468ae8d470b`
- S cycle start: `66aa7206444d8cf8dd2e2e7be6ce6bb69dc945fa`
- U upstream main: `d0288be5b3330d2442e3907185b8e9d0958297bb`
- S/F merge base at cycle start: `6b3157532088540d22cf69036c26247079973e5f`
- F/U merge base used for three-way source checks: `067fa1a25732935d1d2b3c0f2c4c1f078a3bb05f`
- fork refresh merge: `faff04698e51aa1a4fe3953030693a21a154a950`
- source-complete tip before this handoff write: `ff0aa670b96a8f43eec4c75a018fdc62ca148267`

The fork refresh is a two-parent commit with the prior sync line first and current fork main second. It preserves the cumulative handoff and the upstream Chat-Completions fallback regression test that was not present on fork main. Fork main itself was not changed. The current handoff commit is the branch tip that contains this file; the immutable published tip is reported by the automation after the write.

The frozen upstream target is NOT yet attached as a merge parent. This branch remains preparatory reconciliation only.

## Completed this cycle

### ALREADY_RESOLVED — fork refresh superseded stale sync-side copies

Fork refresh `faff04698e51aa1a4fe3953030693a21a154a950` incorporated current fork main while preserving branch-only durable work.

After the refresh these paths are already at the frozen-upstream content and no longer need the stale queue entries from the prior handoff:
- `gateway/platforms/api_server_openai_routes.py`
- `tui_gateway/transport.py`
- `tui_gateway/ws.py`
- `agent/video_gen_provider.py`
- `agent/web_search_provider.py`
- `tests/tui_gateway/test_multi_client_fanout.py`
- `agent/auxiliary_client.py`
- `agent/billing_usage.py`
- `agent/credits_tracker.py`
- `agent/model_metadata.py`

The branch also preserves `tests/gateway/test_chat_completions_final_fallback.py`, blob `698831f512fede4c0a39731a4bcbdb7753ad2bec`, which matches the upstream regression test.

### SAFE_CLOUD_RESOLUTION — static model catalog

Commit `3511d56428e2c094be647aa24ef9378e04136f03`.

Path:
- `hermes_cli/models_catalog_static.py`

Three-way proof at F/U merge base `067fa1a...`: base and fork were both blob `c196ed9bddb3f89183cc2411bf17dd5ecab3efed`; frozen upstream is `967893efc079ef294e6f3cfe5a01168fcf5e1889`. There was no independent downstream edit to overwrite, so the exact frozen-upstream blob was adopted.

This carries the current upstream curated model catalog, including native Anthropic Claude Opus 5.5 and the Bedrock fallback ordering that keeps Sonnet 5 as the provider default.

### SAFE_CLOUD_RESOLUTION — Bedrock context/catalog fixes

Commit `896be52f8a820a09e449b918a0f1bf09361db7b9`.

Paths:
- `agent/bedrock_adapter.py`
- `tests/agent/test_bedrock_adapter.py`

Three-way proof:
- `agent/bedrock_adapter.py`: base=fork `358ee7121056ea14ad7d45467e5d8ed57caf3e76`; upstream `555fe4f58dd381d1b30823befac5576a0cea3438`.
- `tests/agent/test_bedrock_adapter.py`: base=fork `c710352a52fd80946a4642f319c0aedf7e248cbd`; upstream `36ef2d072e4ece18abebf961f719ea07badc5da6`.

The adopted upstream result includes the Claude Opus 5 Bedrock 1M context-table correction and the relationship tests that keep Bedrock static Claude windows aligned with agent model metadata. Tests were copied as source evidence but NOT run here.

### SAFE_CLOUD_RESOLUTION — busy-turn reply expectation

Commit `ff0aa670b96a8f43eec4c75a018fdc62ca148267`.

Path:
- `gateway/run_busy.py`

Three-way proof: base and fork were both blob `66ae8d9cbe6d05ccd724cb7c30ecf9051540dc71`; frozen upstream is `b7d5f8b1c7cf524402eefc99fbdea40f283adb99`. The stale handoff classified this area as runtime-sensitive because older fork routing work had diverged there; current fork main has since converged to the three-way base, so the current upstream result is a safe source adoption.

The incoming behavior folds an addressed busy-steer/redirect message into the running turn's reply expectation, preventing a bare silence marker from incorrectly suppressing the reply for a message the active turn has taken responsibility for.

## Work queue

### LOCAL_GENERATOR_REQUIRED

1. Dependency source / lock consistency:
   - current sync `pyproject.toml`: `ea7c2c7cd2a193d11ae96fdda8dbe697d3d60ff5`
   - frozen upstream/base `pyproject.toml`: `3380055aa40d8c7c6ed783b85a07d8060a70188b`
   - current sync `uv.lock`: `953221d85bd0dc70e5ff2c929e5c7245f5f4d235`
   - frozen upstream `uv.lock`: `953221d85bd0dc70e5ff2c929e5c7245f5f4d235`

   The old handoff's “both sides changed the lock” description is obsolete. The lock now equals upstream, while the fork retains a different dependency source. That does NOT prove the pair is coherent. Review the fork-only dependency intent, then run the repository's current canonical PM lock workflow (`hermes pm lock`) in a real checkout. Do not invent lock contents.

2. Session-create contract generation:
   - current `tui_gateway/contracts/sessions.py`: `d2c1809cbda986fe859cca09e142c3b4069e14cd`
   - upstream: `be298aebf745bbc10c83ab5c11681bd90a78c6bb`
   - current generated TS: `a8faf4b7366b773712c3a3fae71d0eaba119ab6f`
   - upstream generated TS: `a91142764b1011feb3e30ce981cd58f7de50d0cf`
   - current OpenRPC: `6f2e149390150b95f1cfa2614c456434a4120c1f`
   - upstream OpenRPC: `f922bcb5552e41f4c76f279f85ddc4f90f6c6e4d`

   Upstream adds `cwd_explicit` to `session.create` and regenerates both artifacts. The source change is understandable, but publishing only the Python model would knowingly leave generated contracts stale. Reconcile the source in a real checkout and run `scripts/gen_gateway_contracts.py`, then verify the generated consumers.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- Upstream Fast-routing stack `fd602278c7097574143fc9ad64bb8ce6f0441ab9` spans `tui_gateway/server.py`, its session-scope tests, and the TUI status rendering. Review against current fork owner layout and run focused Python + TUI tests before selecting a result.
- Upstream customCSS owner cleanup `179124cdff5da31c4b300ba3c28ac211f5fb36be` moves live ownership into `tui_gateway/change_watcher.py` and removes a duplicated watcher block from the server facade. The correct source owner is clear upstream, but current fork has substantial TUI-gateway work; audit the owner layout and run focused skin/change-watcher tests before modifying this stack.

These are the specifically examined execution-sensitive stacks. The remaining upstream delta is not blanket-classified as local-only; continue three-way B/F/U blob scans next cycle and promote any clean upstream-only path to SAFE_CLOUD_RESOLUTION.

### OPERATOR_DECISION_REQUIRED

None newly proven.

## Verification

Actually performed:
- read current root and applicable area instructions plus downstream-development and prior handoff/contracts;
- froze F/S/U and inspected ancestry / merge bases;
- incorporated newer fork main with a non-forced two-parent merge while preserving branch-only work;
- compared base/fork/upstream blobs for each source slice before adopting it;
- re-read the live sync ref before every branch write;
- published only non-forced ref updates;
- re-read fork, sync and upstream refs after the source work.

NOT run:
- `scripts/run_tests.sh`
- focused agent/gateway/TUI Python tests
- TUI/JS/Vitest/Electron tests
- `hermes pm lock`
- `scripts/gen_gateway_contracts.py`
- runtime/network/GPU/service probes

No test, generator, or runtime result is claimed from this cloud-only cycle.

## Consumer follow-up

No new Hermes CLI/RPC/payload consumer requirement is introduced by the three source reconciliations completed here. The pending `session.create.cwd_explicit` contract work is a wire-contract change, but it has NOT been integrated in this branch yet; any downstream consumer acceptance should wait for its generated-contract/local verification.

## Acceptance blockers / local continuation

1. Resolve and regenerate the dependency/lock pair with the current PM workflow.
2. Reconcile `session.create.cwd_explicit`, regenerate the shared gateway contracts, and run producer/consumer contract checks.
3. Run focused agent + gateway tests covering the model/Bedrock/busy-turn changes carried here.
4. Continue three-way review of the remaining frozen upstream delta; do not stop merely because generator work exists.
5. Only after the complete source tree is internally consistent may `d0288be5b3330d2442e3907185b8e9d0958297bb` be attached as real upstream merge ancestry and the state promoted toward SOURCE_CANDIDATE.
