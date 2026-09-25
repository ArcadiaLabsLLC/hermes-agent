---
type: map
tags: [map, fork, upstream]
aliases: [Fork Boundary, Upstream Boundary]
---

# Fork Boundary Map

What is ours, what is upstream's, and where the two touch. This is the map every upstream sync, every refactor lane and every "can I edit this file?" question reads first. Numbers are from 2026-09-21 (`main` @ `042f58edf8`, `upstream/main` @ `ea0c2b820b`); re-take them with `scripts/refactor_census.py` and the two `git ls-tree` listings it documents.

## The three kinds of file

| kind | how to tell | count (2026-09-21) | rule |
|---|---|---|---|
| **Fork-only** | absent from `git ls-tree -r upstream/main` | 1,439 files (962 `.py`) | Ours entirely. Refactor freely; never conflicts on merge. |
| **Upstream, fork-edited** | present in both trees, differs from the last merge base | 449 files (246 are tests) — +18,300 / −2,300 lines | Every merge conflict comes from here. Edits must be ADDITIVE (see below). |
| **Upstream, untouched** | present in both, identical to merge base | the rest of ~3,600 upstream files | Never edit. Upstream a fix instead. |

## Where the fork lives (the fork-only tree)

- `agent_runtime/` (183 files) — the whole Agent Runtime Harness: stores, serve RPC + socket, snapshot, stream, chat turn, office, board, realm sync, gateway peers, multi-device. **Not in upstream at all.**
- `hermes_cli/harness.py` + `hermes_cli/harness_parts/` — the `hermes harness …` command tree (the runtime's CLI and its `serve` loop).
- `hermes_cli/_downstream_cli.py`, `_profile_bootstrap.py`, `_boot_clock.py`, `_bytecode_sweep.py`, `harness_support.py`, `path_setup.py`, `windows_env.py`, `venv_integrity.py`, `runtime_environment.py`, `config_read_scope.py`, `flag_binding.py`, `gateway_home_receipt.py`, `install_method.py`, `model_picker_policy.py`, `charsheet_payload_contract.py`, `auth_noninteractive.py`, `tirith_config.py`, `update_history.py`, `kanban_blocked_pm.py`, `kanban_crash_evidence.py` — fork modules living in upstream's `hermes_cli/` package (fork-only files, but the DIRECTORY is upstream's: no new module there without a reason, per the refactor plan's grain rule).
- `tools/agent_chat_tool.py`, `agent_chat_dispatch.py`, `agent_chat_remote.py`, `board_tool.py`, `downstream_schema.py`, `path_identity.py`, `process_notify_store.py`, `tool_full_descriptions.py`, `toolset_manifest.py`, `toolset_scan.py`.
- `agent/charsheet/` (10) + `agent/pet/…` — the character sheet pipeline.
- `apps/desktop/src/app/skills/` and 32 desktop files; `mobile_core/` (45); `plugins/model-providers/` (2).
- `scripts/` (23 fork scripts: contract dumps, mutation check, doc-cite adjacency, unattended suite, fixture generators, `upstream_sync_gate.py`, `refactor_census.py`).
- `tests/agent_runtime/` (474), `tests/hermes_cli/` (94 fork-only), `tests/fixtures/` (51), `tests/scripts/`, `tests/agent/`, `tests/tools/`.
- `docs/agent-runtime-harness/` (267), `docs/downstream-development.md`, `docs/downstream/`, `docs/architecture/mcp-expansion*`, `agent_runtime/docs/`, `.githooks/post-merge`, `CLAUDE.md`, this vault.

## Where the fork touches upstream (the seams)

The fork reaches into upstream files at a few anchors. The good shape is **one import and one call at a stable point**; the bad shape is replacing or deleting upstream lines, which conflicts on every upstream edit to that block forever.

| upstream file | seam | shape today |
|---|---|---|
| `hermes_cli/main.py` | `_boot_clock.mark_main_import_started()`; `_profile_bootstrap` imports + `_apply_profile_override()` at entry; `build_downstream_parsers(subparsers)` in `_build_cli_parser`; `process_registry.restore_durable_completions()` in `_prepare_agent_startup`; `"harness"` in the console-command list | mostly additive, BUT a 200-line upstream block was replaced by the `_profile_bootstrap` imports — the permanent-conflict shape |
| `hermes_constants.py` | +286 lines: profile-aware home resolution (`get_hermes_home` at call time, `display_hermes_home`) | heavy; conflicts every sync |
| `hermes_cli/profiles.py` | +301 | heavy |
| `tools/registry.py`, `tools/skills_tool.py`, `agent/prompt_builder.py`, `agent/skill_utils.py` | skill/toolset admission hooks, prompt sections | medium |
| `scripts/run_tests_parallel.py`, `scripts/run_tests.sh` | the fork's hermetic runner (8 workers, per-file subprocesses) | heavy, conflicts every sync |
| `tests/hermes_cli/conftest.py` (+1,266), `tests/conftest.py` (+569), `tests/tools/conftest.py` (+406), `tests/agent/conftest.py` | hermetic-home fixtures, env-gap fence | the single largest conflict surface |
| `pyproject.toml` / `uv.lock` | `coverage==7.16.0`, `pytest-timeout==2.4.0` in `dev` + `[tool.uv.exclude-newer-package]` exemptions; repo-wide `--timeout=30` | keep the fork's pair on every merge, plus any NEW upstream rows |

22 upstream files carry more than 200 fork lines; 118 carry five or fewer. The heavy tail is the whole conflict problem — see [[Upstream Sync]] and [[0006 — Upstream sync is a real merge, per-file reconciliation retired]].

## The fence

- Refactor lanes never touch an upstream file: gate W0-G2 of [`downstream-god-file-refactor.md`](../../docs/agent-runtime-harness/planned/downstream-god-file-refactor.md) reds a `refactor(` commit whose diff intersects the upstream manifest.
- New modules go under fork-owned directories (`agent_runtime/`, `hermes_cli/harness_parts/`, `agent/charsheet/`, `tools/agent_chat/`, `scripts/mutation_check/`, `apps/desktop/src/app/skills/`), never at the top level of `hermes_cli/` or `tools/`.
- A duplicate whose second copy is in an upstream file is folded on the fork side only; the upstream copy is baselined `upstream_copy_left`.
- The history was RECONSTRUCTED on 2026-09-15 (`ed9ac406be`, "same-tree reconstruction", pinned upstream `110baa095b`); pre-history commits live on `codex/pre-history-replacement-20260915`. `git log --follow` on a fork file stops there. See [[0005 — Fork history reconstruction 2026-09-15]].
