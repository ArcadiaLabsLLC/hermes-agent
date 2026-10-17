# test(tui_gateway): the SIGTERM exit-flush test restores SIGINT too

Draft PR body (fork-hygiene row "Qualify POSIX exit-flush test signal-state restoration", lane
r-isolation 2026-10-16). Posted by the owner in a posting sitting; the test file is upstream-owned.

## The problem

`tests/tui_gateway/test_serve_exit_flush.py::test_sigterm_flushes_populated_session_into_state_db`
saves only the previous SIGTERM handler, but `install_exit_flush_signal_handlers` replaces SIGTERM
**and** SIGINT. `_restore_signal_state` restores the saved entries and then clears
`_exit_flush_prev_handlers`, so after the test SIGINT is still `_handle_exit_flush_signal`, now
chaining to nothing, for every later test in the process.

Before/after probe (the test's own install/restore sequence in a child, native Windows, Python
3.14.5; the signal table is the same on POSIX):

```
SIGTERM before: 0 after: 0 restored
SIGINT before: default_int_handler after: _handle_exit_flush_signal LEAKED
```

## The change

Save every handler the installer replaces before installing:

```python
prev = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
signal.signal(signal.SIGTERM, _prev_handler)
```

(`_prev_handler` is still the chained SIGTERM target; `prev` holds the pre-test handlers, so
`_restore_signal_state(prev)` puts both back.) Probe after the change: both `restored`.
