# Fast-gate landing — the whole-tree gate's reds (2026-10-11)

The fast-gate batch (FG1 incl. FG2, FG3) ran `scripts/run_tests_bundled.sh tests` once in its
landing worktree: 6,469 files, the cache's first fill (6,389 greens written), exit 1 with 20
failing files. Each red was re-run on the batch's merge base `828fdb3c0e` (batch 2 on main) to
split ours from pre-existing.

| file | on the batch | on base `828fdb3c0e` | verdict |
|---|---|---|---|
| `tests/hermes_state/test_session_db_read_conn_pool.py` | 1 red: the duplicate-handle report names `fresh_db_census.counted_init` | green | **ours** (FG1 census wrapped `SessionDB.__init__`); fixed `5f0e244ec1` |
| 5 tui_gateway files, 10 ids | XPASS(strict) | XPASS(strict) | **batch 2's**: the Thread shield made the v0.21.6 upstream reds pass; ids removed `5f0e244ec1` |
| `tests/hermes_cli/test_gateway_migrate_multiplex.py` | timeout (300 s whole-tree, then 120 s known-red cap) | green, 174 s solo | pre-existing slowness; the known-red cap traps it (row filed) |
| `tests/scripts/install/test_install_ps1_native_calls.py` | 30 s per-test timeout | green, 27.9 s | timing edge (class row) |
| `tests/test_no_shadowed_test_definitions.py` | 30 s per-test timeout | timeout, then green on retry (31 s / 29 s) | timing edge (class row) |
| `tests/scripts/install/test_install_clone_throttle_fallback.py` | timeout under load; green as known red | green | timing edge (class row) |
| `tests/hermes_cli/test_web_server.py` | `test_concurrent_first_load_reads_all_succeed_on_fresh_store`: a 500 at index 7 under load | green | load flake (class row) |
| `test_update_ci_routing`, `test_desktop_build_lock`, `test_run_agent`, `test_icon_flavors`, `test_run_tests_parallel`, `test_known_file_write_baseline`, `verify/test_environment_and_runner`, `test_tui_gateway_server`, `test_serve_exit_flush` | timeout / no result | the same, quiet `-j 2` | pre-existing (class row; four already rowed) |

Base runs: `run_tests.sh` on all 20 at `-j 2`, then `run_tests_bundled.sh` on the three that
differed. After the fix the census, pool and five tui files and `test_upstream_reds_rows_resolve`
run green on the batch. Killing mutation for the census fix: restore the `__init__` wrapper →
`tests/test_fresh_db_census.py` red on its creation-site pin.

## After the landing (2026-10-11)

- Q5 amended by the owner: a file whose last red was a TIMEOUT runs at the flat timeout (`SoloPolicy.cap`);
  the 120 s trap row is closed by that change.
- Two detached `hermes_cli.main update --yes --gateway --branch main --keep-stash` processes from the
  test-environment venv were found alive at 13:00, started 00:16 and 01:51 during this gate, parents gone.
  Killed; the primary's stash list and tree were unchanged. Rowed in fork-hygiene (2026-10-11 heading).
- The six worker-count runs (§4) cannot start the bundled runner directly from a Python-launched Git
  Bash: that shell has no activation, so `run_tests.sh` re-execs under `run-in-hermes-env` and hits the
  FG1-filed `$__BUNDLED_DIR` re-exec bug (rc 2, no tests). Wrapping the command in
  `scripts/run-in-hermes-env` works.

## Worker count (§4), 2026-10-11 — closed: 8 stays

The 291-file `scripts/worker_protocol_sample.txt` from the primary, `--no-cache --file-retries 0`, through
`scripts/run-in-hermes-env` (receipts `.pytest_cache/hermes_worker_protocol.jsonl`):

| workers | wall | failed | CPU mean / p90 | memory peak |
|---|---|---|---|---|
| 8 | 1,529 s | 0 | 86.6% / 99% | 67.3% |
| 12 | 1,302 s | 2 | 91.4% / 100% | 75.5% |
| 16 | 3,302 s | 2 | 79.8% / 100% | 84.2% |

The owner stopped the repeats (runs 4–6) and kept 8: 16 is a loss, and 12's 15% came with two new reds at
the CPU threshold. The two sampler rows (receipts outside `RunLedger.summary`; the sample needs the
primary) are closed with the measurement. Run 4 reproduced the leaked `hermes update`
(`test_desktop_update_windows_marker.py::test_script_killed_right_after_spawning_the_update_leaves_a_live_marker`).
