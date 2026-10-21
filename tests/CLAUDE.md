# tests/ — the fork's test guide

This file is fork-owned; upstream has none. `tests/AGENTS.md` beside it is UPSTREAM's guide: it
describes upstream's runner and upstream's CI. A session in this repository does not read it or
follow it (owner ruling 2026-10-16). Every rule for running tests here is
`Harness_Brain/50 — Agent Handoffs/Running the tests.md`; read that before running anything.

## Running

- The landing gate is `scripts/run_tests_bundled.sh tests` (`--scope fork`). The fork's own bundled
  runner exists because upstream's `scripts/run_tests.sh` is slow on Windows.
- One file: `scripts/run_tests.sh <file>`. Never bare `pytest` over a directory.
- Nothing runs the whole tree (ADR 0016): a landing is `--scope fork`, a release merge `--since-merge`.
- A lane runs only the test files that import a module it touched.

## Writing

- Never edit an upstream test file (one present in `upstream/main`). A fork test is a new file,
  usually named `*_downstream.py` beside the upstream one.
- An upstream test that is red because of the fork gets a row under `tests/_downstream/id_markers/`
  (`fork_marks.py`, `posix_marks.py`, or the release's `upstream_reds_v*.py`), with a reason.
- Shared fork fixtures and seams live in `tests/_downstream/`. Every test process loads that folder,
  so an edit there is a session-chain edit; Running the tests.md says when it lands.
- Deleting a public name adds a row to `tests/agent_runtime/test_tombstone_registry.py`.
- A gate test lands with its killing mutation named and its red recorded in the commit body.
- Wait on events or `tests.waiting.wait_until`; never a wall-clock sleep.
