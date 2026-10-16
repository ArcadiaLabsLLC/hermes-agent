# Run-serialization retirement — S1 census (field notes, 2026-10-16)

Plan: [run-serialization-retirement-2026-10-15.md](run-serialization-retirement-2026-10-15.md).
Lane h3-runser, tree at `origin/main` `343319c5d37`. This note is the S1 census the
plan asks for: every reader on the turn path that keeps `persona_profile_context`'s
`os.environ` writes and `_agent_workdir`'s `os.chdir` alive. Each row below names
the slice that retires it.

## The writes (what serialization protects)

| Write | Site | Value |
|---|---|---|
| `HERMES_HOME` | `profile_context.persona_profile_context` | persona profile home |
| `HOME` | same | `<profile>/home` when it exists |
| `HERMES_AUTH_HOME` | same | the head auth home (constant across personas in one serve) |
| `HERMES_AGENT_RUNTIME_ROOT` | same (both arms) | the head-resolved store root (constant in practice) |
| process cwd + `TERMINAL_CWD` | `profile_runner.workdir._agent_workdir` | the turn's workdir |

## Readers, by channel

**In-process `HERMES_HOME`.** The pinned reader `plugins/memory/openviking` no longer
exists in the tree (no `openviking` anywhere under `plugins/`). Every turn-path reader
goes through `get_hermes_home()` (ContextVar first). Raw `os.environ["HERMES_HOME"]`
reads remaining on a turn: `tools/self_repo_guard.py::_block_message` (wording of a
refusal message only, upstream) and `tools/mcp_tool_config.py::_inject_child_hermes_home`
(fallback only when `get_hermes_home` fails to import). Neither needs the write.

**In-process `HERMES_AUTH_HOME`.** Already a ContextVar
(`profile_home._HERMES_AUTH_HOME_OVERRIDE`), read through `get_hermes_auth_home()`.

**In-process `HERMES_AGENT_RUNTIME_ROOT`.** Three fork readers key on the RAW env var:
`terminal_envelope/receipts.py::_audit_root` and `audit_root_source`, and
`terminal_policy.py::_harness_safety_block` (activation on presence). Store reads go
through `paths.store_root()` → `resolution.resolve_runtime()`, which already honours a
context-scoped resolution (`resolution.runtime_resolution_scope`) before `os.environ`.
→ S3.

**In-process `HOME`.** POSIX `expanduser`/`Path.home()` only; 51 such calls in
`agent_runtime/` alone, plus upstream. Measured on this box (Windows, Python 3.12):
with `HOME` set to a fake path, `ntpath.expanduser("~")` still answers
`USERPROFILE` — so on native Windows the `HOME` write is unobservable in-process. → S5
keeps it on POSIX only, behind a narrow lock, until the upstream door.

**Spawns.** Every upstream spawn on the turn path builds its env through
`tools/environments/local.py` (`_sanitize_subprocess_env`, `hermes_subprocess_env`,
`build_subprocess_env`, `served_profile_child_env`), and every one of those calls
`_apply_profile_home`, which already bridges the ContextVar `HERMES_HOME` and computes
the child `HOME` from it (`hermes_constants.get_subprocess_home`; on a host in `auto`
mode it REPAIRS a profile-home `HOME` back to the real home, so the fork's `HOME`
write never reached factory-built children anyway). Not bridged: `HERMES_AUTH_HOME`
and `HERMES_AGENT_RUNTIME_ROOT` — today they reach children only through the process
env write (measured: all three factories pass both names through). → S2 bridges them
from the run context inside `_apply_profile_home` (one fork call; local.py is already
on the footprint list).
MCP stdio children (`mcp_tool_config._build_safe_env`) pass `HOME` raw from
`os.environ` and deliberately never `HERMES_AUTH_HOME`; the runtime root is not a safe
key, so MCP children never received it. Without the `HOME` write they get the
process `HOME`, which is upstream's own host policy ("hosts keep real HOME").
Fork spawn sites under `agent_runtime/` (`git_cmd`, `dirty_state`, `external_skill_links`,
`local_llama_adapter/setup`, `store_file_io_windows`, `provider_signin_child`,
`workspace_slots_probe`, `route_command`) need no Hermes home in their env; the ones
reachable from a turn (`repo_context` git reads, `dirty_state`) are git status reads.

**cwd.** Upstream already carries the working directory per context for its own
multiplexed gateway: every `TERMINAL_*` read goes through `tools.terminal_scope.terminal_env`
(a bound scope wins over `os.environ`), and `agent.runtime_cwd.resolve_agent_cwd()`
reads the session cwd ContextVar, then that scope. Fork reader with raw env + process
cwd: `agent_runtime/flutter_build_guard.py::_terminal_base_dir`. Upstream `os.getcwd()`
readers reached only when no `TERMINAL_CWD` is configured, or cosmetic:
`agent/display.py` (path display), `agent/tool_dispatch_helpers._canonical_path`
(overlap detection), `tools/async_delegation.py` (recovery hint),
`tools/file_operations_search.py` (darwin only), `tools/send_message_senders.py`,
`agent/shell_hooks.py`. → S4 binds a terminal scope with the workdir; these go in the
upstream door list.

## Other holders of the lock's meaning (S5 must keep them true)

- `operator_checkpoints.py` / `operator_undo.py` take `_WORKDIR_LOCK` non-blocking to
  mean "no run in flight"; they also read `agent_runs_in_flight()`.
- `mcp_admission/resident.py`: "`_WORKDIR_LOCK` serialises runs, so one slot per scope
  is enough". A per-root lock lets two roots that admitted the same MCP scope run at
  once; one `BudgetSlot` then carries the wrong run's budget.
- `persona_chat_actor_prewarm.py` stands down on `agent_runs_in_flight()`; unchanged.
- `tools/agent_chat/send.py`, `tools/agent_chat_dispatch/`: reason about the lock to
  choose a child process for agent-to-agent sends; still correct (conservative).

## Slice outcomes (lane h3-runser, branch `build/h3-runser`)

| slice | commit | outcome |
|---|---|---|
| S1 census | `197d6a5bf3b` | this note |
| S2 spawns from context | `c95ab355f17` | `agent_runtime/run_context.py`; one fork call in `local.py::_apply_profile_home` bridges the run's root + auth home into every factory-built child |
| S3 envelope + root | `7bf55ca1118` | safety block, audit-root ladder and `paths.store_root()` read the run's bound root (`runtime_root_signal`, `runtime_resolution_scope`) |
| S4 no `os.chdir` | `76ee9cec743` | workdir bound as `TERMINAL_CWD` in the run's terminal scope; `flutter_build_guard` reads the scope |
| S5 per-root lock | `d1324ca9dd1` | `root_run_lock(root)` for the run; `_WORKDIR_LOCK` is the workspace writers' turnstile; `export_env=False`; POSIX `HOME` under `_PROCESS_HOME_LOCK`; MCP `BudgetSlot` one binding per run |

Every CHANGE commit carries its killing mutation and the recorded red.

## S5 live two-root proof (2026-10-16)

Setup, all lane-owned and torn down after: a temporary `HERMES_HOME` and runtime
root, two profiles `alpha` / `beta` each bound by a config-declared persona with its
own `repo_scope` workdir, a scripted OpenAI-compatible model server on loopback, and
`harness serve --ndjson --service` started from the lane worktree with the test venv
(ended with `serve connect --drain`). Approval mode `manual`, timeout 90 s. Root A's
model asks for `rm -rf ./runser_alpha_scratch` (needs operator approval, never
answered); five seconds after that tool call, root B's model asks for a terminal
command printing the basenames of its `HERMES_HOME`, runtime root, auth home and
cwd. The same driver ran against `origin/main` `343319c5d37` as the control.

| run | A tool call → A exit | B send → B exit | B's first model call |
|---|---|---|---|
| control (`origin/main`) | 752.9 → 850.6 (approval timed out) | 759.5 → 856.7 (97 s) | 852.4 — **after A ended** |
| branch, run 1 | 439.7 → 537.0 (timed out) | 447.0 → 474.3 (27 s) | 471.2 — during A's wait |
| branch, run 2 | 962.6 → 1057.7 (timed out) | 969.4 → 1000.2 (31 s) | 995.0 — during A's wait |

(Seconds, last digits of the epoch stamps in the lane's timeline files.)

No crossing: root B's child printed `home_tail=beta root_tail=root auth_tail=home
cwd_tail=work_beta` on the branch run that overlapped A's wait — byte-identical to
the control, where nothing overlapped. Each root's transcript
(`harness persona chat history`) holds only its own operator rows (0 foreign rows
in either). The temp root's `config.yaml` under the platform default home was read
by the root anchor but not written (mtime unchanged); skills installed into the temp
home only.

Setup facts worth keeping: a serve on a fresh root needs `HERMES_HEAD_HOME` (the
launcher sets it) or every persona turn fails `chat_session_db_unavailable` — the
process-home override has no authoritative head without it.

## Residue (rows filed)

- POSIX still serializes every run behind `_PROCESS_HOME_LOCK` until the upstream
  door for in-process `HOME` / `expanduser` readers lands (plan decision 3).
- `persona_profile_context(export_env=True)` has no production caller left.
- `planned/serve-cwd-per-run-paths.md` describes the chdir regime this retired.
