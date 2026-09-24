---
type: handoff
tags: [handoff, testing]
---

# Running the suite

What "green" means in this repo and how to get there without detaching commits or measuring the wrong scope. Full text: [`docs/downstream-development.md`](../../docs/downstream-development.md) § Testing; gates: [[Testing & Gates]].

> [!important] `scripts/run_tests.sh`, never bare `pytest`, for anything wider than one file
> Updater tests inside the validated scope run `git branch -f main origin/main`; a bare `pytest tests/hermes_cli` in the primary checkout detached 11 unpushed commits (2026-08-01). The runner isolates per file in hermetic subprocesses and finds the shared test venv (`$HERMES_TEST_VENV`, else `~/.venvs/hermes-test`).

## The commands

| what | command | cost |
|---|---|---|
| one file (debugging) | `python -m pytest -q -p no:cacheprovider <file>` | seconds |
| touched tests (an exec lane's end) | `python -m pytest -q -p no:cacheprovider <files that import what you touched>` — background, log, `; rc=$?; exit $rc`, timeout ≥ 600000 | minutes |
| **the validated suite** (a landing) | `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state` | **≥ 25 min**, 8 workers (do not raise `HERMES_TEST_WORKERS`: 12 measured slower and load-flaked) |
| the two scopes nobody else runs | `scripts/run_tests.sh tests/test_coverage_claims_resolve.py tests/scripts` | minutes |
| whole tree | `scripts/run_tests_parallel.py` default | a DIFFERENT, unvalidated scope: ~142 environmental reds on a green `main` (provider-network hangs, WSL-bash PATH shadow, `acp`/`ripgrep` holes) |

## Rules

- Explicit timeout on every call; background + log for anything over a minute; never `| tail`.
- A wait bound > 30 s needs `@pytest.mark.timeout(N)` (module-wide `pytestmark`), or pytest-timeout kills it before it reports.
- `tests/acp` cannot collect from a worktree (editable install resolves to the primary) — run it from the primary or name lanes explicitly.
- `HERMES_TEST_TMP_ROOT` → a Defender-excluded throwaway dir speeds the suite; `X:/Eternia` is already excluded on this box.
- A parallel-only failure is compared as a SET against a serial run of that file before it is believed.
- Pre-existing reds are named as such with the one-test run on `main` that proves it; never baselined ([[0010 — Stale sweep and ratchets first, never baseline]]).
- Known red on `main` (2026-09-21): `tests/test_docket_stage_claims.py::test_every_stage_that_says_it_shipped_names_a_commit_that_landed_here` (queue row).
