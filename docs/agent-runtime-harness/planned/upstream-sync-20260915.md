# Latest upstream integration, 2026-09-15

## Baselines and recovery

- Published compact fork: `0d5b7b8abccc07eb21d20d789fd0e14b68591aa4`.
- Previous upstream: `110baa095bc7135a0624557a9cc35df0f98ece0f`.
- Incoming upstream: `416a8177c25d87aa9929dfcf31f7964137d7fcdd` (642 commits).
- Pushed recovery branch: `codex/pre-upstream-416a8177-20260915`, at the compact fork.
- Integration branch: `codex/upstream-conflicts-20260915`.

This update preserves both histories with a merge. It does not repeat the history
replacement. The preceding 15-commit consolidation remains intact; its tracked
tree was `b533fff1abaa2289abc90d4664c07f421e00de19`, identical to archived
`c112a9347a4e14ce573cdbf3d154177a6f521843`. Attribution and original-to-group
mapping remain on `codex/history-replacement-20260915` at
`6d36a2b1874d97d658ffa3d735c5d04ae7e58d9e`.

## Conflict decisions

18 files conflicted. Retain upstream changes and the following fork contracts:

- Codex client timing plus upstream transport-read retries.
- Required-skill policy plus upstream already-loaded deduplication. Keep package
  ownership filtering in the shared skill resolver, used by runtime and tools.
- Managed Python and explicit target-profile home for Windows gateway startup.
- Profile bootstrap remains in the extracted module; port upstream invocation
  normalization there rather than restoring a second inline implementation.
- Call-time Hermes home and upstream cross-VM filesystem diagnostics.
- NT/device namespace and path-identity protection plus upstream full-read and
  stale-write protection. Preserve both process-completion race regressions.
- Kanban reclaimed-retry behavior and downstream crash evidence documentation.

## Reducing the next merge

Browser navigation, terminal and file-write full descriptions now follow upstream
source. Three small registration calls opt into `tools/downstream_schema.py` for
the fork's short wire descriptions. `tool_describe` reads the captured current
full description, avoiding a second manual mirror update for those tools.
Parameter schemas are unchanged; other registrations are untouched.

Keep subsequent fork work in owned modules with narrow call sites. Shared files
can still conflict at those call sites; a downstream directory cannot eliminate
integration conflicts. Do not choose either side wholesale based on filenames.
Continue daily history-preserving updates; the ahead count can grow with new
work and is not grounds for routinely rewriting published main.

## Installer reassessment

No incoming changes affect `agent_runtime/local_llama/`. Upstream's separate
supervisor changes `--no-webui` to `--no-ui` and distinguishes unknown idle
telemetry from busy/idle. Qualify the exact launch arguments of the selected
owner against each installed binary. The fork router uses neither UI flag.
Unknown telemetry must not authorize lifecycle actions. Do not adopt upstream
automatic unload in place of the fork's explicit single-model owner.

Installer endpoints remain planned, not implemented. Preserve root ownership,
receipts, revision guards, inference routing and active-turn exclusion. Producer
fixtures and served-wire proof are still required before Launcher integration.
No Launcher distribution, live service restart or runtime configuration change
is part of this update.

## Validation

All Python tests used `bash scripts/run_tests.sh` with the private
`X:/wt/hermes-upstream-audit-20260914/qa-artifacts/patched-runtime-venv`.
The operator's environment was not modified.

| Run | Result |
| --- | --- |
| 31-file merge regression, `-j 4` | 459 passed, 4 failed, 7 skipped; also doctor collection error and staleness timeout. All failures addressed below. |
| `tests/agent/test_skill_commands.py`, `tests/tools/test_t6b_brief_descriptions.py`, `tests/tools/test_downstream_schema.py`, `-j 2` | 40 passed, exit 0 |
| `tests/agent_runtime/test_serve_rpc_authorization.py`, `test_root_config_pinning.py`, `test_provider_health.py`, `-j 2` | 30 passed, exit 0 |
| `tests/hermes_cli/test_gateway_windows.py` and `tests/gateway/test_windows_gateway_spawn.py` | 8 and 2 passed |
| `tests/hermes_cli/test_gateway_spawn_fence.py`, `-j 1` | 35 passed, exit 0 |
| `tests/hermes_cli/test_doctor_journal_modes.py`, `-j 1` | 34 passed, 3 POSIX-only skips, exit 0 |
| `tests/tools/test_file_staleness.py`, `-j 1` | 12 passed, exit 0 |

The first run covers Codex runtime, skill resolution/loading, CLI bootstrap,
Windows gateway, doctor, namespace/path/read/write guards, process completion,
brief descriptions and all ten Local llama test modules. Completed-process and
file-tools timeouts passed the runner's bounded single-worker retry. The staleness
test was split into independent real-filesystem cases without increasing timeouts.
Windows expectations now match OS-native errors and intentionally portable skill
paths. Gateway spawn tests stay outside the CLI directory's unconditional fence.

`scripts/probe_local_llama_runtime.py` passed (exit 0) with the installed b10809
CUDA llama-server and qwen-3_8-27b-abliterated_i1-Q4_K_M GGUF. Its isolated home,
runtime root and random loopback port proved receipt idempotency, revision-aware
lifecycle calls, 8192-context inference, actual terminal tool roundtrip, same-model
auxiliary routing, cleared active-turn lease, unload, 4096-context reload and
owned shutdown. Receipt: `complete=true`, `runtime_closed=true`.

Raw logs are retained under
`X:/wt/hermes-upstream-audit-20260914/qa-artifacts/latest-upstream-merge-20260915/`;
real-model receipt is in the sibling `latest-upstream-real-llama-20260915/`.
Scoped Ruff checks passed. Whitespace warnings in the incoming OSV workflow and
auteur Markdown are byte-identical to upstream and were not reformatted.
This is focused Windows proof, not a full cross-platform/desktop UI suite.
Live Launcher and Hermes process start times remained unchanged.
