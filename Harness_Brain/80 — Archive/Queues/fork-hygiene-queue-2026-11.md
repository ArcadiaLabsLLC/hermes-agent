---
type: queue-archive
queue: fork-hygiene-queue.md
program: fork-hygiene
month: 2026-11
---

Closed rows of `fork-hygiene-queue.md` for 2026-11; appended by the close commits, never edited.

- **`FH-WORK-STATUS-LADDER-BASELINE` — Replace the two new Work-status routing ladders with the existing dispatch vocabulary** · `agent_runtime/work/store.py::move` · `agent_runtime/work_store/grammar.py::_close_line` · test_no_ladder_routing reports identical 2 NEW / 0 GREW / 0 STALE on suggestion candidate and unchanged main e689847b48: vocab BLOCKED and CLOSED; suggestion paths add no ladder · DONE 2026-11-04 8de0500cdc
- **`FH-RUFF-BASELINE-20261103` — Clear the fourteen existing fork-line Ruff findings exposed by the current lint census** · `scripts/check` · `agent_runtime/provider_retry_wait.py` · `tests/agent_runtime/test_brain_remote.py` · census on main e689847b48 sources: RUF022/RUF046 in provider_retry_wait; PLR0402/PIE807/UP017/RUF059/RUF100 in board_card_patches, brain_paths, brain_remote, home_env_freshness, provider_retry_wait, skill_freshness, slot_context_cache_prefix, subagent_operator_ownership, turn_attendance and work_store/batch_support; suggestion files are clean after removing one new unused noqa · DONE 2026-11-04 fa9d25b37d
