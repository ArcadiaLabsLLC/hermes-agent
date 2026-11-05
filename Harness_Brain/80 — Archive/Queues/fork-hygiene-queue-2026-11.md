---
type: queue-archive
queue: fork-hygiene-queue.md
program: fork-hygiene
month: 2026-11
---

Closed rows of `fork-hygiene-queue.md` for 2026-11; appended by the close commits, never edited.

- **`FH-WORK-STATUS-LADDER-BASELINE` — Replace the two new Work-status routing ladders with the existing dispatch vocabulary** · `agent_runtime/work/store.py::move` · `agent_runtime/work_store/grammar.py::_close_line` · test_no_ladder_routing reports identical 2 NEW / 0 GREW / 0 STALE on suggestion candidate and unchanged main e689847b48: vocab BLOCKED and CLOSED; suggestion paths add no ladder · DONE 2026-11-04 8de0500cdc
- **`FH-RUFF-BASELINE-20261103` — Clear the fourteen existing fork-line Ruff findings exposed by the current lint census** · `scripts/check` · `agent_runtime/provider_retry_wait.py` · `tests/agent_runtime/test_brain_remote.py` · census on main e689847b48 sources: RUF022/RUF046 in provider_retry_wait; PLR0402/PIE807/UP017/RUF059/RUF100 in board_card_patches, brain_paths, brain_remote, home_env_freshness, provider_retry_wait, skill_freshness, slot_context_cache_prefix, subagent_operator_ownership, turn_attendance and work_store/batch_support; suggestion files are clean after removing one new unused noqa · DONE 2026-11-04 fa9d25b37d
- **`FH-STREAM-CONTRACT-FIXTURE-COLLECT-TIMEOUT` — `tests/agent_runtime/test_stream_contract_fixture.py` times out before collection under `scripts/run_tests.sh` (its bounded 1-worker retry too, 44 s) at load ~70–100 on the Linux box: collection reads the tree through `tests/agent_runtime/_tree_index.py::text` for every file (`stream_frames` grep); alone with a 600 s bound it passes 25 in 19.8 s — make the walk one indexed read (or a memo like the line-endings gate's) so a loaded box is not a red** · `tests/agent_runtime/test_stream_contract_fixture.py` · `tests/agent_runtime/_tree_index.py::text` · found 2026-11-03 by lane w1103a-h1 running the core cache importers · REFUTED 2026-11-04 244bc949e7 · result: the file imports no _tree_index and walks no tree at collection: collect-only 25 tests in 0.54 s (wall 1.6 s) at load 23; scripts/run_tests.sh runs it green in 12.1 s at load 22; the 44 s timeout was box load (70-100), not a collection walk
