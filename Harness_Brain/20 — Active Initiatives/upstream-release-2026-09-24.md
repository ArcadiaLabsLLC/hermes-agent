---
type: evidence
program: upstream-sync
status: merged-on-lane-branch-with-known-reds
tags: [program/upstream-sync, evidence]
---

# Weekly upstream merge — 2026-09-24 (lane MERGE)

Upstream range: `d337b736aa..f24a1d7f92` — 1,663 commits. Pre-merge main `37ca422c25`.
Merge `075fb4eba4` on `seam/upstream-merge-2026-09-24`, history-preserving (no squash, no rebase),
then `origin/main` `b93ce5e66c` (lanes S2 + SUITE2, landed meanwhile) merged in as `5b5a68bb69`;
the new merge base is `f24a1d7f92`. Worktree `X:/wt/h-merge`, logs in its `.lane-logs/`.

## Conflicts: 73 files, resolved by the [[Upstream Sync]] rules

The merge commit's message lists every file with one line on how it was resolved. The shape:
upstream's "purge low-value tests" lanes (py03…py18) deleted many upstream tests the fork had
edited in place — 6 modify/delete files taken as deletions, ~30 content conflicts taken as theirs.
Fork-original tests survived: two purged files' fork tests re-homed to fork-owned files
(`tests/gateway/relay/test_contract_doc_session_key_columns.py`,
`tests/tools/test_browser_content_reads_none_guarded.py`), the rest kept in place.
Hardest three: `hermes_cli/main.py` (upstream changed the profile override the fork had moved to
`hermes_cli/_profile_bootstrap.py`; upstream's `_s6_supervised_gateway_run` ported into the seam,
the fork's `_desktop_ssh_backend` now delegates to upstream's `_startup_fast` authority);
`tools/tool_search.py` (upstream's hosted-connector failure payload over the fork's legacy
query/name shapes and in-session describe set); `uv.lock` (upstream's lock re-locked over the
merged `pyproject.toml`: only `coverage` and `pytest-timeout` added).

**What a clean resolution still broke** (all found by the touched-test run, fixed in-lane):
imports and one helper dropped from six fork-edited test files (`3ea8d47e10`); a production
NameError — upstream's new `heartbeat` never reached the fork's `_terminal_tool_run` behind the
envelope wrapper (`77cd9c6a6f`); five fork test edits dropped by "theirs" hunks (`cd6e67dea1`).
ruff did not see any of them: F821 is ignored under `tests/**`, `tools/**`, `agent/**`, `gateway/**`.

## Supersession pass

28 ledger rows said "superseded by upstream": 22 retired (file now equals upstream or is gone),
including the gpt-6 prod rows and the generated `model-catalog.json`; 6 kept with a row —
`agent/usage_pricing.py` (pricing half adopted; `record_api_call_usage` is fork-only),
`hermes_state.py` (mixin carry), two lifted PR carries (`up/win-shell-invocation`), and the two
`tests/gateway/` relocations (the tests/hermes_cli gateway fence blocks their spawns at upstream's
path — tried, 2 red, reverted in `177e685cf6`). The seven "re-check at next merge" carries:
2 dropped (`test_watch_patterns.py`, `test_notify_on_complete.py`), 4 kept (upstream's version
red: kanban_boards, entry_point_discovery, browser_homebrew_paths; e2e conftest unexercised),
1 not re-tried (`test_process_registry.py`, lifted PR hunk).

## Open PRs

All eleven in the [[Upstream Sync]] table are OPEN upstream (`gh pr view`, 2026-09-24) and none is
in `upstream/main`'s log; no carry was dropped.

**Conflict count expected next merge** (lane CARRY, after the merge): the trial at 37ca422c25 vs f24a1d7f92 had 57 conflicting test files, 33 of them still fork-edited on `origin/main`; 15 remain (8 rule-4 carries that replace upstream behaviour, 7 `upstream`/`hook` rows owed to PRs), so at this week's churn expect about 66 - 18 = 48 or fewer. Trial against today's `upstream/main` (`git merge-tree --write-tree HEAD upstream/main | grep -c ^CONFLICT`): 1 before and after (`tools/process_registry.py`, not a test).

Ruled 2026-09-24: a strict-xfailed upstream test naming the fork symbol beside the sibling's opposite assertion IS the recorded parallel, not duplicate authority.

## Ratchet

Before `[up-fp] files=408 deleted_lines=2612 heavy=11` at base `d337b736aa`;
after `[up-fp] files=373 deleted_lines=2404 heavy=10` at base `f24a1d7f92` (`a8aebea5fa`, then
re-measured over S2 in `5b5a68bb69`; S2 alone had taken the old-base line to 404/2602/10). Nothing rose. 509 of the deleted lines are the two relocations.

## Gates and reds

ruff (repo config): 1 error, pre-existing on `37ca422c25` (`hermes_cli/cli_init_mixin.py:347`,
upstream code). CLI contract fresh (202 paths); payload contract fresh; mutation `--list` exit 0;
doc-cite adjacency green after one re-anchor (`d50000a389`); `tests/scripts/test_upstream_footprint.py` green.
Touched tests: 76 files, one run, then the repaired files re-run. Every remaining red was re-run
on `37ca422c25` (`X:/wt/h-merge-base`) and is red there too: gui_command 4, config 2,
noninteractive_git 1, background_process_notifications 2, kanban_db 1, doctor 1, computer_use 1,
local_env_blocklist 2, tui_gateway_server 2, gateway port/stop 2 (+1 timeout), and
`test_prompt_builder.py` does not collect on Windows (`os.geteuid`, upstream). `tests/scripts`:
install autostash 1 and `test_run_tests_parallel.py` pre-existing; `test_install_diverged_rescue_ref.py`
is upstream-new and Windows-red (install.sh defers to the PowerShell installer).
After the S2 merge: `tests/test_no_source_grep_assertions.py` debt register had 50 stale lines
(purged tests) — deleted, 71 → 21; its two other reds, `test_system_prompt.py` kanban 2,
`test_t6b_brief_descriptions.py` 1 and stage42 1 are red on `origin/main` too. Owner ruling 2026-09-24: fork gates apply to fork-authored lines only and the fork keeps no
registers of upstream tests — the pinned-upstream register (`tests/upstream_source_assertions.json`,
66 entries at `110baa095b`, ~60 of them stale after the purge) is deleted and the source-grep gate
scoped by `is_fork_authored`; the coverage-claims gate got the same scope (7 upstream-authored
citations) and its 11 fork citations were re-anchored (2) or recorded as deleted (9). Both gates green.
Formerly merge-caused and not fixed (now fixed, see above): `tests/test_coverage_claims_resolve.py` — 18 citations to tests
upstream purged (0 at base), fixed in `12f45e8d1a`. Classification is against a baseline run, not the
242-ID bundle (not in the repo). No validated-suite run (ruling: once per program).

The shared test venv gained `snowballstemmer==3.1.1` and `firecrawl-anydoc==0.2.4`
(upstream core deps it lacked); its other pin drift is pre-existing.
