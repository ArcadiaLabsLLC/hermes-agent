---
type: operations
tags: [operations, windows, tests]
---

# Windows console signal safety

On 2026-09-27 the operator's Codex worker exited nine times with
`STATUS_CONTROL_C_EXIT` (`0xC000013A`). Three recorded exits followed launches
of `tests/tui_gateway/test_compute_host_phase1.py` by 1.9, 7.1 and 1.7 seconds.
The exact signal sender was not captured; the unsafe calls and console-sharing
mechanism below were independently reproduced without firing a real signal.

## Mechanism and repair

- Native Windows `os.kill(pid, 0)` sends `CTRL_C_EVENT`; it is not a POSIX
  liveness query. `tui_gateway/host_supervisor.py::_pid_alive` and the import-time
  stale-lock sweep in `tests/conftest.py` now use `gateway.status._pid_exists`
  on Windows. POSIX behavior is unchanged.
- `tests/_fixtures/live_system_guard.py::_guarded_kill` refuses Windows Ctrl+C
  and Ctrl+Break events, including for own/child PIDs: subtree membership does
  not prove a separate console. Deliberate isolated signal tests retain the
  explicit bypass marker. Its self-test checks the bypass without signalling.
- `scripts/run_tests_parallel.py` starts Windows pytest workers with
  `CREATE_NO_WINDOW`. `start_new_session` does not isolate a Windows console.
  A venv launcher may create a private console; the invariant is that it does
  not include the runner, not that every worker has no console at all.

## Regression evidence

Windows Python 3.13.15; the two affected compute-host files passed (18 tests).
The new process-safety tests passed (2); the runner file passed (19 tests,
2 skipped, 1 expected failure). Ruff passed for the changed Python modules.

Each repair was independently removed, its test run, and the repair restored:

| Mutation | Recorded failure |
|---|---|
| Remove supervisor Windows branch | `test_collection_and_supervisor_query_processes_without_signalling`: live-PID assertion failed |
| Remove import-time sweep Windows branch | Same test: `AssertionError: PID query attempted signal delivery: (17696, 0)` |
| Disable Windows event refusal | `test_guard_refuses_console_events_even_for_own_pid`: `DID NOT RAISE RuntimeError` |
| Remove runner `CREATE_NO_WINDOW` | `test_windows_worker_does_not_inherit_runner_console`: runner PID `47920` present in worker console `[4336, 37672, 47920, 46064]` |

The probe intercepts `os.kill` before importing the source; the guard canary
uses a no-op delivery spy. The console test starts a hidden, separate console
and queries membership without signalling it. None requires risking the live
operator session to prove a regression.

References: [Python os.kill](https://docs.python.org/3/library/os.html#os.kill),
[Windows console events](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent).
