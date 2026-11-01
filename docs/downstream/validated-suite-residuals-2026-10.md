# Validated-suite residuals — the D3.14 classification run (2026-11-01)

Plan: `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.14
(protocol) and § D3.12. Population: the 97 failing nodes in 25 files that
`docs/downstream/native-result-policy-2026-10-10.json` lists under
`pre_existing_failures`.

## The run

Lane w1101b-perf, nekwo-ubuntu24 (Linux, 52 logical CPUs, 50 GB), tree
`66ef28daf1` (`origin/main`), `HERMES_PYTHON` = the hermes test venv, nothing else
running a suite.

`scripts/run_tests.sh -j 8` over the 24 of the 25 files still on disk:
**24 files, 315 passed, 0 failed, 4 skipped, in 70.4 s (8 workers), exit 0.**

`tests/hermes_cli/test_kanban_blocked_pm_tick.py`, the 25th, is no longer in the
tree (kanban is an unused upstream surface, ADR 0015).

## Classification

None of the 97 nodes reproduces, so no node needs a bucket (environment skip,
drift-gate burn-down or defect row): every file that held one now passes whole,
the e2e and gateway-peer files included (`test_gateway_peer_two_roots_e2e.py`
9 passed in 70 s, `test_serve_gateway_peer_lane.py` 28, `test_serve_gateway_lane.py`
28, `test_harness_core_ratchet.py` 19, `tests/tui_gateway/test_contract_catalog.py` 6).
The population has shrunk from 97 to 0; the next qualification regenerates
`pre_existing_failures` from a run, not from this note.

What the same day's whole fork gate saw instead (`scripts/run_tests_bundled.sh
--git-audit --no-cache tests`: 1,382 files, 15,554 passed, 1 failed, 135 skipped,
338.8 s, 12 workers) is a different, small set, filed as fork-hygiene rows on
arrival: one red that is red alone (`tests/agent_runtime/test_snapshot_worker.py`)
and two isolation leaks (`tests/test_temp_prefix_sweep.py`,
`tests/agent_runtime/test_serve_stream_lane_parity.py`).
