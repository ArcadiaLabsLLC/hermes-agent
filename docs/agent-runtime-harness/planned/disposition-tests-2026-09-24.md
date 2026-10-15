# Planned — dispositions for the `tests/` rows of the upstream footprint ledger (2026-09-24)

Lane DISP-T gave a disposition, a reason and a stage to all 207 `tests/` rows of
[`upstream-footprint-ledger.md`](upstream-footprint-ledger.md) that still read `unreviewed`.
The rules are §1 rules 1 and 4 and "No duplicate authority" in
[`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md).

**Inputs.** The fork hunks are `git diff d337b736aa HEAD` (the manifest base) for each path. They
were checked against `upstream/main` @ `6b2c23ae42`, fetched 2026-09-24. 173 rows take their
reason code from [`upstream-test-fix-classes-2026-09-23.md`](upstream-test-fix-classes-2026-09-23.md).
I read the other 34 rows hunk by hunk. These are files whose fork tests S5 already moved out, so
only the in-place residue is left.

**Supersession check.** For each fork hunk, I tested whether its post-image appears verbatim in
upstream's current blob and whether the lines it removed are gone from that blob. That covers all
207 rows. I also tested the fork-added lines of every row against all 928 names in
`tests/agent_runtime/test_tombstone_registry.py`. The `test_s*_removal.py` gates are migrated into
that registry, so they are covered too.

**Stage values.** `S2`, `S3`, `S4` and `S5` are plan stages. `up/<branch>` means the fix was
lifted onto that branch. `-` means carried forever. `merge` is new in this pass: the next weekly
upstream merge deletes the fork edit, either because upstream already has it or because the edit
should be reverted.

## Counts

| disposition | rows |
|---|---|
| `upstream` | 109 |
| `carry` | 93 |
| `hook` | 5 |

| reason class | rows |
|---|---|
| lifted (one or more of the 10 `up/*` branches + `up/profiles-delete-guard`), nothing left | 55 |
| carry: fork test infra (markers, `_live_system_guard`, fork-runner timeout/isolation, spell and source gates, host-OS fakes) | 48 |
| carry: depends on fork prod code | 40 |
| PR candidate (not yet lifted) | 23 |
| superseded by upstream | 18 |
| REVERT (residue, restructure, comment-only) | 7 |
| hook seam (S2: T6b `tool_describe` + `register_system_prompt_section`) | 5 |
| lifted + PR candidate for the rest | 3 |
| lifted + carry (fork test infra) | 2 |
| lifted + superseded (R8) | 2 |
| carry: conftest in-place (S3) — `tests/gateway/conftest.py`, `tests/e2e/conftest.py` | 2 |
| lifted + REVERT | 1 |
| lifted + carry (fork prod code) | 1 |

## Superseded by upstream (20 rows; the next merge deletes the fork edit)

- **Upstream deleted the file (purge lanes).** At the merge, take the deletion, or keep the file
  as fork-only, which has no footprint.
  - `19f76d7498`: `agent/test_nous_oauth_401_guidance.py`, `agent/test_pet_generate.py` (the only
    fork edit is orphan S5 banners)
  - `aedc6ccc3a`: `e2e/matrix_xsign_bootstrap/test_bootstrap.py`,
    `gateway/relay/test_contract_doc_conformance.py`
  - `21c698b7df`: `gateway/test_compression_deferred_soft_result.py`
  - `4b67380698`: `hermes_cli/test_setup_matrix_e2ee.py`
  - `524c38a98a`: `tools/test_browser_content_none_guard.py`
  - `f596ed1595`: `tools/test_local_tempdir.py`
- **Upstream now has the same fix.**
  - `21c698b7df`: `gateway/test_cron_interrupt_notification.py`
  - `1d10cef836`: `hermes_cli/test_codex_models.py`
  - `2002f03e42`: `agent/test_curator_classification.py`
- **Upstream fixed it its own way (R8).**
  - `b2ecd3518f`: `agent/test_skill_commands.py` (its lifted part stays on `up/win-shell-invocation`)
  - `4f1dcc2dad`: `hermes_cli/test_kanban_default_assignee.py`
  - `96c9cc9ac6`: `hermes_cli/test_mcp_startup.py`, `hermes_cli/test_noninteractive_git.py`
  - `8f6109e493`: `hermes_cli/test_xai_provider_labels.py`
  - `5f6b1d251f`: `tools/test_execution_flag_detection.py` (lifted part stays on `up/win-shell-invocation`)
  - `f596ed1595`: `tools/test_llm_content_none_guard.py`
- **The fork relocated upstream's own file to `tests/gateway/`, making a duplicate of upstream
  tests.** At the merge, restore upstream's path and delete the fork copy.
  - `ca16cafee4`: `hermes_cli/test_cross_profile_kill_refusal.py`
  - `67f385f2d8`: `hermes_cli/test_stderr_timestamp.py`. The fork copy is stale and is missing 29
    of upstream's lines.

Seven more carry rows depend on fork prod code whose symbol upstream has since adopted:
`connect_closing`, `plugins_discovery`, `dep_ensure`, `checkpoint_path` and `_queued_events`. Each
of those rows says a "supersession re-check owed at next merge".

## REVERT

**Supports something the fork has retired: 0 rows.** None of the 928 tombstone names appears in a
fork-added line; the only matches were substring noise. The closest case is
`hermes_cli/test_worktree_sync_base.py`. It is a comment-only note about the fork's retired
pre-push hook (`7bbf6db3b`), and it is REVERT here as comment-only.

**Residue and cosmetic edits (13 rows carry a REVERT clause):**
- whitespace left by the S5 move: `agent/test_usage_pricing.py`, `hermes_cli/test_slack_cli.py`,
  `hermes_cli/test_subcommands_batch.py`
- orphan S5 banners, comments or imports: `hermes_cli/test_dep_ensure.py`,
  `hermes_cli/test_restart_plan_reconciliation.py`, `hermes_cli/test_commands.py` (3 unused
  imports), `hermes_cli/test_bytecode_sweep.py`, `agent/test_skill_utils.py`,
  `scripts/test_run_tests_parallel.py`, `tools/test_local_env_windows_msys.py` (duplicated banner)
- `tools/test_file_staleness.py`: a cosmetic split of upstream's one test into four, with the
  same assertions
- `gateway/test_update_command.py`: the known-command hunk is a merge-drift overwrite of
  upstream's own fix
- `hermes_cli/test_worktree_sync_base.py`: comment-only

## PR candidates not yet lifted (new fix classes)

| class | files |
|---|---|
| linux-only markers (R4; needs per-test proof) | 7 |
| stale doc pointers (docstring/comment names a moved or missing test path) | 6 |
| held (R10): right fix, but the test stays red on Windows for another reason | 4 |
| win-path-spelling extension (hunks outside `up/win-path-spelling`) | 3 |
| win platform-default root pin (`_get_platform_default_hermes_home` / `sys.platform`) | 2 |
| hermetic home under a `clear=True` env | 1 |
| win-tilde-home extension (`USERPROFILE`) | 1 |
| case-insensitive filesystem | 1 |
| probe rootdir anchor (`pytest.ini`) | 1 |

## Top 10 carried files by deleted lines

| file | −/+ | reason |
|---|---|---|
| `hermes_cli/test_gateway_windows.py` | −97/+1 | fork prod `resolve_managed_python` + `_spawn_detached(script_path)`; upstream's 2 breakaway tests deleted (the fork's `tests/gateway/test_windows_gateway_spawn.py` covers them) |
| `hermes_cli/test_doctor.py` | −49/+153 | fork prod `doctor.py` (call-time `HERMES_HOME`, `agent_browser_runnable_override`) |
| `hermes_cli/test_gateway_service.py` | −35/+44 | `_live_system_guard` backend-spawn arm (ML-14) |
| `hermes_cli/test_dashboard_tui_backcompat.py` | −31/+61 | `_live_system_guard` arm; the subprocess test is now a parser test |
| `hermes_cli/test_nous_inference_url_validation.py` | −29/+92 | fork source-reading gate |
| `tools/test_local_env_blocklist.py` | −29/+54 | host-OS fake (R3) |
| `hermes_cli/test_config_read_guard.py` | −21/+61 | fork prod `persona_config_sync.py` allowlist; the walk is now drivable |
| `gateway/test_completion_delivery.py` | −21/+31 | fork `checkpoint_path` + background-agent-turns default |
| `tools/test_approval.py` | −12/+72 | fork `tools/path_identity.py` + `tirith_config.py` |
| `test_live_system_guard.py` | −11/+14 | `_live_system_guard` arm; upstream's container-exec test is inverted |

## Branch state seen on 2026-09-24

`up/win-text-encoding`, `up/monkeypatch-undo-scoped` and `up/profiles-delete-guard` exist only
as local branches. They are not on `origin`. The other `up/*` branches have been rebased since the
fix-classes note: `up/win-path-spelling` is now `5c70d5da3a`, and it sits in `upstream/main`'s
history.
