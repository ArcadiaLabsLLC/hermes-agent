# L4 outcomes (lane 1010-L4, 2026-10-10) — branch lane/1010-L4

L4.01 · RETURNED upstream PR needed: the 4 encoding nodes are GREEN under scripts/run_tests.sh (PYTHONUTF8=1; 124 passed with test_update_command/test_outbound_webhooks/test_file_read_guards/test_fts_runtime_rebuild) and red only under bare `python -m pytest` on cp1252 — the tests' own `write_text()` with no encoding; the PM file still reds under the runner: `test_update_sync_retries_a_fetch_failure_once_before_disabling` exceeds the 30 s timeout (uv retries https://127.0.0.1:9 3x in 15 s, twice) and `test_update_sync_survives_unreadable_secondary_profile` fails on Windows (`str(path)` searched inside `json.dumps` output, backslashes doubled). Drafts D1, D2.
L4.02 · RETURNED upstream PR needed: `_DUMMY_HASH = hash_password(...)` still at import of plugins/dashboard_auth/basic (0.09 s/scrypt measured; import 0.52 s); the re-importer is upstream's plugin loader, no fork caller to memo. Draft D3.
L4.03 · RETURNED upstream PR needed: still `mcp_filesystem_*` in agent/tool_guardrails.py IDEMPOTENT_TOOL_NAMES on v0.21.6 AND upstream/main (2026-10-08); the registry spells `mcp__filesystem__*`. Draft D4.
L4.04 · RETURNED upstream PR needed: hermes_cli/terminal_notify.write_tty still opens "/dev/tty" unconditionally on v0.21.6. Draft D5. (X:\dev\tty litter left for the operator.)
L4.05 · RETURNED too big: an investigation with no repro (the observer fix landed; the suspected WAL-sidecar preflight race needs a reproducer under a live native reader before any guard can be proven).
L4.06 · RETURNED upstream PR needed: the fork cuts landed (w3-perf); `pm.plugins_state.read_home_selection` still re-reads every profile config.yaml per `venv_is_current` with no memo on v0.21.6 (now via utils.fast_safe_load). Draft D6.
L4.07 · ALREADY-DONE fa2677be7b: the fork carries the fstat-vs-fstat comparison in tools/file_tools_read_tracking.py::_file_version ("Compare each clock to itself"); upstream PR #128647 CLOSED unmerged, issue #128639 still OPEN — the carry retires when upstream fixes #128639.
L4.08 · RETURNED owner decision: OWNER 2026-09-29 "wait until the fork polish is done" — is the polish done, and may the transport client door be offered upstream?
L4.09 · RETURNED operator live proof: OWNER 2026-09-29 HOLD on up/node-deps-reuse-installed-superset until a held-handle repro names the EPERM trigger (workspace union / node-npm version / npm_config_* env).
L4.10 · ALREADY-DONE fa2677be7b: same root cause as L4.07; tests/tools/test_file_read_guards.py green under scripts/run_tests.sh today (in the 124-passed run above).
L4.11 · RETURNED owner decision: still SQLite 3.45.3 here and the four `_up_red_when(sqlite<3.46)` markers stand; OWNER 2026-09-29 "skip the writable_schema path" — a VACUUM INTO draft, or wait for upstream?
L4.12 · RETURNED upstream PR needed: F821 `MagicMock` still at tests/tools/test_local_env_blocklist.py:938 on v0.21.6 (`ruff --isolated --select F821`); our PR #128657 is OPEN.
L4.13 · ALREADY-DONE v0.21.6 (3d167a8271/55d9a49c1d): `state_db_has_structural_damage` now answers False on OperationalError (the vtable raise); f7cc81dc0b retired the `_up_red` marker; tests/hermes_cli/test_doctor_structural_corruption.py green under the runner. Our #128645 can be closed as superseded.
L4.14 · RETURNED upstream PR needed: F821 `e` still at hermes_cli/cli_init_mixin.py:350 on v0.21.6; upstream PR #124237 (same rebind) still OPEN.
L4.15 · RETURNED owner decision: OWNER 2026-09-29 "low priority, later"; no upstream ask exists — file the process-wait ceiling key ask, or keep the fork's `wait_ceiling_seconds()`?
L4.16 · RETURNED owner decision: OWNER 2026-09-29 park until group-chat work resumes (the Group Chat host-surface widening PR needs scoping).
L4.17 · RETURNED upstream PR needed: all three still on v0.21.6 — `_inject_profile_env_vars()` runs at hermes_cli/config.py import (list_providers), fireworks builds its User-Agent with get_version_info() at import, `_receipt_reports_stale_runtime` asks git per start. Draft D7.
L4.18 · FIXED 22055b400f
L4.19 · FIXED 9b8879f233
L4.20 · RETURNED owner decision: the seed VALUES for the door-fit PARTIAL keys (door-fit-2026-09-27.md § CARRY-DELETE) still need the owner's picks.
L4.21 · FIXED 37367dc215 (nine verbs, not seven: sync status/pull/publish/resolve, skills show/set, agents show/set, adopt)
L4.22 · RETURNED owner decision: publish the honoured `params` of the 16 h-twins verbs in the manifest, or rule the block chat-only?
L4.23 · FIXED c3b9cef766 + d548871f4e (a loop-shaped patch in test_chat_verbs_rpc.py the sweep missed)
L4.24 · FIXED 2e93ca37a4
L4.25 · RETURNED too big: four new read twins incl. a media-style pixel payload (characters list/status/thumb/sprite) is a lane, well over 150 lines with schemas and tests.
L4.26 · RETURNED too big: six console-tier board twins (card add/move/edit/archive/restore, resolve_conflict) with tiers, params and tests.
L4.27 · ALREADY-DONE 919eb8f0da: every refusal/detail string (gateway_commands refusals.py/join.py/introduce.py) already names `plugins.entries.eternia-harness.settings.remote_gateway_listen`; only comments say `remote_gateway.listen`. LEGACY_KEYS retirement itself is a separate step (waits on the launcher writing the new path); launcher's pair_fulfiller_test.dart quote is launcher-side.
L4.28 · RETURNED owner decision: may a reused actor whose `native_revision` is unchanged hand its own messages to the turn (SessionDB stays the authority, the revision the guard)?
L4.29 · RETURNED operator live proof: one cold + one warm Windows turn read off the h-chatperf stamps.
L4.30 · RETURNED too big: publishing turn start/end as state patches is a stream-lane design change (running_work section leaves the core build), not a <150-line fix.
L4.31 · ALREADY-DONE b62278749f: the started→link-bound wait is receipted on every accepted chat turn (`chat_turn_accept_to_anchor ... link_ms=%d`, agent_runtime/turn_activity.py ACCEPT_TO_ANCHOR_RECEIPT; `accepted.link_bound` stamped in serve/lanes.py after `_bind_launcher_link`).
L4.32 · RETURNED owner decision: OWNER 2026-10-05 PARKED until the upstream settle door / the next mcp pin bump; no fork-only door (verdict 2026-10-04 still true).
L4.33 · RETURNED owner decision: OWNER 2026-10-05 PARKED; the three skip lists are upstream files at merge-base bytes — no carry.

## Drafts (never posted)

### D1 · test: write the Windows-safe update/webhook fixtures as UTF-8
Title: `test(gateway,agent): write fixture files with encoding="utf-8" so the suite passes on a cp1252 Windows console`
`tests/gateway/test_update_command.py::TestSendUpdateNotification` writes `.update_output.txt` containing `→`/`✓` with `Path.write_text(...)` and no encoding, and `tests/agent/test_outbound_webhooks.py::TestDelivery::test_events_enqueued_at_exit_still_delivered` generates a script the same way; on Windows without UTF-8 mode the locale codec is cp1252 and the write raises UnicodeEncodeError (the generated script is rejected by Python). Pass `encoding="utf-8"` at each `write_text`.
Repro (Windows, PYTHONUTF8 unset): `python -m pytest tests/gateway/test_update_command.py::TestSendUpdateNotification tests/agent/test_outbound_webhooks.py::TestDelivery::test_events_enqueued_at_exit_still_delivered` → 4 failed, `'charmap' codec can't encode character '\u2192'`.

### D2 · test(pm): two Windows reds in test_plugin_survival_contract.py
Title: `test(pm): bound the fetch-retry test's uv retries and compare Windows paths as JSON in the unreadable-profile test`
`test_update_sync_retries_a_fetch_failure_once_before_disabling` points uv at `https://127.0.0.1:9/...`; on Windows a refused connect is retried by uv 3x over ~15 s, and the contract retries the fetch once, so the test passes 30 s and pytest-timeout kills the session (the file aborts; every later node goes unreported). Set `UV_HTTP_RETRIES=0` in the test's environment (or declare `@pytest.mark.timeout(90)`). `test_update_sync_survives_unreadable_secondary_profile` asserts `str(broken.parent) in json.dumps(warnings)`; on Windows `json.dumps` doubles each backslash, so the substring never matches — compare against `json.dumps(str(broken.parent))[1:-1]` or search the parsed warnings.
Repro (Windows): `scripts/run_tests.sh tests/pm/test_plugin_survival_contract.py` → Timeout in `_run_streaming`; the second node alone → `assert 'C:\\...\\profiles\\work' in '[{"at": ...`.

### D3 · perf(dashboard-auth): compute the constant-time dummy hash on first use
Title: `perf(dashboard_auth/basic): derive _DUMMY_HASH lazily instead of at import`
`plugins/dashboard_auth/basic/__init__.py` runs one scrypt (n=2**14, ~0.09 s measured on Windows) at import to build `_DUMMY_HASH`, which every plugin (re-)import pays — 80–122 scrypt calls per test file in profiles. Move it behind a `functools.cache`d `_dummy_hash()` read at the one verify site; the timing-equalisation property is unchanged (the first unknown-user login pays it once).
Repro: `python -X importtime -c "import plugins.dashboard_auth.basic"` or time the import (0.52 s here) vs. the same with the line removed.

### D4 · fix(guardrails): spell the filesystem MCP idempotent names the way the registry does
Title: `fix(tool_guardrails): derive the filesystem MCP idempotent names with mcp_prefixed_tool_name`
`agent/tool_guardrails.py::IDEMPOTENT_TOOL_NAMES` lists eight `mcp_filesystem_*` names (single underscore), but since #33533 the registry registers `mcp__filesystem__*` (`tools/mcp_tool_schema.py::MCP_TOOL_NAME_PREFIX`), and `ToolCallGuardrail` compares the raw registered name, so the no-progress guard never treats a filesystem read as idempotent. Build the eight with `mcp_prefixed_tool_name("filesystem", name)`.
Repro: `python -c "from agent.tool_guardrails import IDEMPOTENT_TOOL_NAMES as I; from tools.mcp_tool_schema import mcp_prefixed_tool_name as p; print(p('filesystem','read_file') in I)"` → False.

### D5 · fix(cli): never open /dev/tty on Windows
Title: `fix(terminal_notify): skip the /dev/tty attempt on Windows`
`hermes_cli/terminal_notify.write_tty` opens `"/dev/tty"` first; on Windows that path resolves under the current drive's root, so where a `\dev` folder exists (e.g. test litter) the BEL/OSC sequence is written into a FILE `X:\dev\tty` instead of the terminal. Gate the attempt on `os.name != "nt"` and go straight to the stdout fallback.
Repro (Windows): `mkdir X:\dev`, cd to X:, `python -c "from hermes_cli.terminal_notify import write_tty; write_tty('\x07')"` → `X:\dev\tty` now exists and holds the byte.

### D6 · perf(pm): one plugin-selection verdict per process
Title: `perf(pm): memo read_home_selection by config.yaml stat so venv_is_current stops re-parsing every profile`
`pm.plugins_state.read_home_selection` parses each profile's `config.yaml` on every `venv_is_current` call, which a self-managed launch makes twice (`prepare_launch` + `check_runtime`); with 12 profiles that was 3.0 s of a 23 s `hermes` start (cProfile, 2026-10-01). Key a memo on `(path, st_mtime_ns, st_size)`; an unreadable selection still raises.
Repro: `python -X importtime`/cProfile of `hermes --version` on a home with many profiles; count `read_home_selection` calls.

### D7 · perf(cli): stop paying provider discovery, git and a User-Agent build at every start
Title: `perf(cli): lazy OPTIONAL_ENV_VARS injection, lazy fireworks User-Agent, git only for an unfinished fleet receipt`
Every `hermes` process pays: `hermes_cli/config.py::_inject_profile_env_vars()` at import (`providers.list_providers()`, ~1.6 s, 38 plugin dirs); `plugins/model-providers/fireworks` building `User-Agent` from `get_version_info()` at import (git subprocesses, ~2.1 s profiled); and `update_cmd_fleet._receipt_reports_stale_runtime` → `get_code_identity(refresh=True)` (git, 0.8–1.7 s) on start. Defer the injection behind a module `__getattr__`, build the header on first request, and consult git only when the receipt is unfinished or its fleet matrix stale.
Repro: `python -X importtime -c "import hermes_cli.config"`; cProfile `hermes --version`.
