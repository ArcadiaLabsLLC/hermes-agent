# Disposition pass — the ledger rows outside `tests/`, `hermes_cli/`, `tools/`, `agent/` (lane DISP-M, 2026-09-24)

Scope: the 75 `unreviewed` rows of [`upstream-footprint-ledger.md`](upstream-footprint-ledger.md) outside those four directories. Each row was read as `git diff d337b736aa HEAD -- <path>` (the fork's hunks against the manifest base) and checked against `upstream/main` @ `6b2c23ae42`. The rules are §1 rules 1 and 4 of [`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md) and its "No duplicate authority" paragraph. The ledger cells hold the per-row reason, and this note does not repeat them.

## 1. Tally

| group | rows | revert | generic | hook | carry-movable | carry-fixed |
|---|---|---|---|---|---|---|
| repo root | 15 | 0 | 4 | 3 | 4 | 4 |
| `.github/` | 8 | 0 | 6 | 0 | 2 | 0 |
| `gateway/` | 15 | 1 | 4 | 5 | 1 | 4 |
| `website/` | 15 | 2 | 5 | 1 | 7 | 0 |
| `scripts/` | 8 | 0 | 5 | 0 | 0 | 3 |
| `tui_gateway/` | 4 | 1 | 1 | 1 | 0 | 1 |
| `plugins/` | 3 | 0 | 3 | 0 | 0 | 0 |
| `apps/` | 2 | 0 | 1 | 1 | 0 | 0 |
| `evals/` | 2 | 0 | 1 | 0 | 0 | 1 |
| `contributors/`, `nix/`, `providers/` | 3 | 1 | 2 | 0 | 0 | 0 |
| **total** | **75** | **5** | **32** | **11** | **14** | **13** |

`revert` and `generic` are both disposition `upstream`, and the difference is in the reason cell. `carry-movable` counts a carry whose reason names a fork-only target for all or part of the edit.

## 2. REVERT — whole-file retirements (5 files, 22 `deleted_lines`)

Upstream has moved every one of these five files since the base. So `git checkout upstream/main -- <path>` would also pull in upstream's later hunks, which the fork has not merged yet. For the three code files, the mechanical command is the **base** form, which restores exactly upstream's bytes at the base and removes only the fork hunk. The two superseded website files converge on their own at the next upstream merge. Use the `upstream/main` form for them only together with, or after, that merge.

| path | why | deleted_lines recovered | command |
|---|---|---|---|
| `gateway/status.py` | dead edit: a duplicate `hermes_constants` import (the base imports it at line 24) plus a docstring rewrite | 3 | `git checkout d337b736aa -- gateway/status.py` |
| `tui_gateway/server.py` | dead edit: a comment-only change (a test name in a docstring) | 1 | `git checkout d337b736aa -- tui_gateway/server.py` |
| `providers/__init__.py` | dead edit: spells an import through `hermes_cli.plugins_discovery` for two names that `hermes_cli/plugins.py` still re-exports | 1 | `git checkout d337b736aa -- providers/__init__.py` |
| `website/docs/developer-guide/context-compression-and-caching.md` | superseded by upstream `79ec1f2a34` (fork copy `f0d6d10a9c`) | 4 | `git checkout upstream/main -- website/docs/developer-guide/context-compression-and-caching.md` (at/after the merge) |
| `website/static/api/model-catalog.json` | superseded by upstream `79ec1f2a34`. Upstream `38c289c014` has since dropped `gpt-6-terra`, so the fork copy is also stale | 13 | `git checkout upstream/main -- website/static/api/model-catalog.json` (at/after the merge; the file is generated) |

Expected ratchet after the five: `files` −5, `deleted_lines` −22.

Hunk-level retirements. None of these is a file revert, because the rest of each file stays:

- `.gitignore`: the fork's `.install_method` line duplicates the base's `/.install_method`.
- `hermes_state.py`: the `_resolve_default_db_path` alias is superseded by upstream `_default_db_path`. Its only readers are `tests/hermes_state/test_downstream_session_contracts.py` (2 sites) and 3 comments in `tests/test_no_frozen_hermes_home.py`. Respell those in the same commit.
- `utils.py`: `_replace_with_windows_contention_retry` is superseded by upstream `dcbe175423`. The `newline=` passthrough stays because 3 fork callers use it. This retirement recovers 2 of the file's 6 deleted lines.
- `model_tools.py`: the `get_registered_toolset_names` wrapper. Upstream's `tools/registry.py` has the method, so `agent_runtime/personas.py` can call the registry directly.

## 3. REVERT — supports something the fork retired

**None in this scope.** I probed each fork symbol these rows depend on against `tests/agent_runtime/test_tombstone_registry.py`, the `test_s*_removal.py` gates, and the live tree (`queue-status`, `background_process_agent_turns`, `_kanban_blocked_pm_hook_watcher`, `declare_async_delivery_channel`, `DiscussionLimits`, `pin_room_history`, `blocked_tool_names`, `session_usage_ledger`, `harness_core`, `HERMES_UPDATE_HISTORY_REVIEW_REQUIRED`, `HERMES_MCP_ENV_`, `never_defer`, the `.gitignore`/`.gitattributes` subjects, and the fork pytest markers). Every one is live. The only tombstone hit was `_blocked_tool_names_for_run`, which is a different function from the live `blocked_tool_names`.

## 4. Generic classes (the 32 `upstream` PR candidates, S3 unless noted)

1. **CI fork-friendliness** (6): the runner/timeout/worker conditionals in five workflows and in `tests.yml`'s shared part, plus the `contributor-check.yml` case-variants rule.
2. **Windows portability / case-insensitive FS** (5): `contributors/` case variants across `scripts/release.py`, `scripts/audit_pr_attribution.py` and the CRLF contributor file, plus `scripts/check_subprocess_stdin.py` and the `utils.py` `newline=`.
3. **Profile-home correctness** (4): the process-home fallback in `gateway/lifecycle_ledger.py` and `gateway/shutdown_watchdog.py`, the Feishu dedup path frozen at construction, and `plugins/dashboard_auth` reading config read-only.
4. **Upstream website doc drift** (5): billing, chronos, gateway-session-lifecycle, relay contract, network-isolation. In each, upstream's own code already disagrees with its page.
5. **Plain fixes** (12): media hardening, `finish_reason`, the session-order tie-break, the memory `_publish_module`, `nix` swallowing a failure, the eval-probe NameError, installers using an existing checkout, the kanban claim TTL, the tirith resolver in `cli.py`, P2 (`tui_gateway/entry.py`), and the desktop uninstall warning (S6).

## 5. Movable carries (14): the fork need not edit these upstream files

- **`website/` (7 rows).** The fork does not need to edit upstream's site at all. The one-shot MCP env overrides (2 pages), the `gateway.port` note, the kanban crash artifacts, `never_defer`, and the background-completion family (en and zh) all describe fork features. Target: fork docs under `docs/`, with upstream's pages left as shipped.
- **`.github/` (2 rows).** `ci.yaml`'s `notify-main-red` job moves to `.github/workflows/fork-ci-red-notify.yml` (on `workflow_run`). `tests.yml`'s `mutation-claims` job and history fetch move to `.github/workflows/fork-gates.yml`. The runner conditionals are the PR in §4 class 1.
- **Config defaults (2 rows).** `gateway/run_config_loaders.py` and `cli-config.yaml.example` flip `background_process_notifications` to `result`. Set that value in the fork's profile config seed instead, then REVERT both.
- **Root (3 rows, partial).**
  - `.gitattributes`: the fixture `-text` pins move to per-directory `.gitattributes` in the three fork-only fixture dirs and in `.githooks/`. The `* text=auto eol=lf` rule stays at the root.
  - `.gitignore`: the `qa-artifacts/` pair moves to `qa-artifacts/.gitignore`.
  - `pyproject.toml`: the fork markers move to `tests/_downstream/` via `pytest_configure`.

The 13 fixed carries: `AGENTS.md`, `README.md` (license), `hermes_state.py`, `uv.lock`, `gateway/run.py`, `run_notifications.py`, `run_turn.py`, `session_context.py`, the three desktop-update scripts, `evals/completion_backlog_probe.py`, and `tui_gateway/session_notifications.py`. The reasons are in the ledger cells.

## 6. Hooks (11)

- **One Group Chat host-surface PR** covers four rows: `gateway/hosted_room_discussion.py`, `hosted_room_policy_checkpoint.py`, `hosted_rooms.py` and `tui_gateway/hosted_room_driver.py`. It adds host-declared limits, history pins, the active-event budget and `request_reconciliation`, with `agent_runtime/discussions/service.py` as the consumer.
- **One tool-filter hook PR** covers three rows: `model_tools.py`, `run_agent.py` and `toolsets.py`, which carry `blocked_tool_names`, the composite `harness_core`, and `skill_search`.
- **`queue-status` via plugin `register_command`** covers three rows: `gateway/run_busy.py`, `website/.../slash-commands.md`, and `apps/.../desktop-slash-registry.json` (S6, which also needs the dump to read plugin commands).
- **A gateway watcher-registration hook** covers one row: `gateway/run_startup.py`.

## 7. Regeneration proof

After all four ledger commits, `python scripts/upstream_footprint.py --ledger` was re-run. The hand cells of these 75 rows survived: the post-run `git diff` touches no `disposition`, `reason` or `stage` cell (see this note's commit).
