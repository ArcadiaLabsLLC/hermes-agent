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

## Slice outcomes

Recorded under the plan's status section as each slice lands.
