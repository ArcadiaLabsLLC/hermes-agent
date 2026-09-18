# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY — cloud progress preserved; current upstream is not yet represented by a complete merge.**

This is the durable handoff for `automation/upstream-sync`. The branch is cumulative: cloud runs
and local agents continue from its existing history rather than restarting. Only the operator
lands an accepted, locally tested candidate to `main`.

## Frozen inputs for this cycle

- Fork: `ArcadiaLabsLLC/hermes-agent`
- Fork `main` (`F`): `68b24d4254c56550688707e805ec5755c1823f10`
- Previous sync tip (`S`): `cdac5ee5d1cd5bf680718cd4077bb3f65b33608a`
- Official upstream: `NousResearch/hermes-agent`
- Upstream `main` (`U`): `98f758ae7e8db83c2bb9214c3b35adf41df15f03`
- Previous upstream observation: `9796235822b89e08597a402dad045b5b4464e474`
- Last upstream commit already represented in accepted fork history: `416a8177c25d87aa9929dfcf31f7964137d7fcdd`

Ancestry checks show both the previous upstream observation and the last accepted upstream tip remain
ancestors of current upstream. No upstream history rewrite was detected. The persistent sync branch
had diverged from fork `main` only through this handoff file; this cycle refreshes the branch from
current fork `main` while preserving the handoff lineage. **No newer upstream commit is attached as
a merge parent yet.** The external run result names the immutable published branch tip/tree; this
file cannot contain its own enclosing commit SHA without circularity.

## Progress completed in cloud

### Fork-main refresh

Fork `main` advanced by six commits since the previous handoff. Its new work is the account-verified
Codex/provider model-picker contract and associated docs/tests/fixtures. The sync branch now preserves
that fork work plus the prior handoff history; it was not reset, rebased, squashed or force-updated.

### New fork model-picker work versus current upstream

The relevant ownership check is favorable and narrows future conflict work:

- `hermes_cli/codex_models.py`: current upstream is byte-identical to the last accepted upstream
  version (`a652f10541727064c41c0a3705cf997b7125567c`). Fork `main` adds the account-scoped verified
  picker/cache on top. There is no competing upstream edit to this file in the current target.
- `hermes_cli/provider_catalog.py`: current upstream is byte-identical to the last accepted upstream
  version (`8f381e6a0582ffb383b4c9eb77a046ea29ddbdf0`). The fork's provider-login/consumer contract remains
  a downstream extension, and the new model-picker policy is integrated at that downstream seam.
- `hermes_cli/model_picker_policy.py` is downstream-only at the current upstream target.
- `scripts/dump_cli_contract.py` is downstream-only at the current upstream target.
- Current upstream does have `hermes_cli/auth_model_picker.py`, but it owns the interactive OAuth/login
  picker. It is not a proven semantic replacement for the downstream provider-login policy/wire
  projection. Do not delete the downstream contract merely because both contain “model picker” logic.

These findings mean the six new fork commits should be preserved as downstream work rather than
replayed as conflicts against similarly named upstream picker code.

### `pyproject.toml` conflict decision is now precise

The fork's dependency/test additions remain intentional:

- `dev` contains `coverage==7.16.0` and `pytest-timeout==2.4.0`;
- `[tool.uv.exclude-newer-package]` carries the matching exemptions.

Current upstream still lacks those fork-only dev dependency rows. The only post-baseline upstream
`pyproject.toml` semantic change found in path history is from upstream commit
`94ced1a2b263ac4192872af1416e7ac523bd301f`: it adds the pytest marker
`real_post_swap_handoff: opt out of the autouse stub that runs the update post-swap tail in-process`.

Therefore the intended source reconciliation is unambiguous: **keep the fork dependency/test rows and
add the upstream `real_post_swap_handoff` marker.** This is a resolved source decision; it does not
resolve the generated lockfile.

## Generated blocker: `uv.lock`

This blocker remains real and was revalidated against the current tips:

- fork `uv.lock` blob: `c9e2c9a657ca6a69b4a77d49b85b6233a3bb6745`
- upstream `uv.lock` blob: `6d381729736fb8b318236863844a51781be19e23`
- fork `pyproject.toml` blob: `529fbed5c565749f71f33be1e2eae7f154f522cc`
- upstream `pyproject.toml` blob: `34c382a6e47fadeb37814a85ad9f527e6bf3320a`

Neither lock can be selected wholesale because the final source must combine upstream changes with
fork-only dependency inputs. Regenerate `uv.lock` from the final merged `pyproject.toml` using the
repository's canonical `uv lock` workflow in a real checkout. Do not fabricate lock content.

## Upstream review still in progress

Upstream advanced substantially beyond the previous observation while the fork also moved. The
ancestry is normal, but the source delta is broad and includes areas with historical downstream
contracts (`agent/`, `hermes_cli/`, Desktop and other runtime paths). A single GitHub compare is not
sufficient evidence because changed-file output can be capped. The current upstream target is **not
claimed integrated** until bounded/tree-complete review and reconciliation finish.

Continue the cloud-side review in bounded ranges, prioritizing intersections with known downstream
modifications and contracts. Resolve deterministic text/semantic overlaps in cloud when their full
content is available; otherwise record the exact path/decision here for the local agent.

## Local-agent continuation

Work only on `automation/upstream-sync`; leave `main` untouched.

1. Read root/nested `AGENTS.md`, `docs/downstream-development.md`, this handoff, and the latest
   upstream-sync/local-llama notes before editing.
2. From a neutral cwd, create an isolated worktree for this branch per the downstream safety rules;
   do not switch/reset a running primary checkout.
3. Re-fetch/re-pin official upstream. If it moved beyond
   `98f758ae7e8db83c2bb9214c3b35adf41df15f03`, either deliberately include the newer tip after
   review or clearly defer it; never silently mix targets.
4. Continue the bounded three-way review from last accepted upstream
   `416a8177c25d87aa9929dfcf31f7964137d7fcdd` to the pinned upstream target. Preserve current
   upstream behavior plus the documented Arcadia/Eternia contracts.
5. Reconcile `pyproject.toml` as decided above: retain the fork's coverage/pytest-timeout dependency
   and uv-exemption rows, plus add upstream's `real_post_swap_handoff` pytest marker.
6. After the final merged source inputs are known, run the canonical `uv lock` regeneration and
   verify the lock corresponds to that exact tree.
7. Run focused verification via `scripts/run_tests.sh` (never bare pytest). Because the fork-main
   work changes the CLI/provider contract fixtures, also run `python scripts/dump_cli_contract.py --check`
   and inspect any diff before regenerating a contract fixture.
8. Re-run focused tests for every reconciled runtime contract. Local llama remains owned by
   `agent_runtime/local_llama/manager` with explicit lifecycle/RPC ownership, root/grant isolation,
   receipts, revision/active-turn guards and no automatic start/unload substitution.
9. If Hermes CLI/RPC/payload contracts require consumer changes, record the likely Launcher follow-up
   here, but do not modify Launcher in this branch.
10. Commit completed reconciliation and update this handoff. Change State to `SOURCE_CANDIDATE` only
    when the pinned upstream target is actually in ancestry and no known source/generated defect remains.

## Verification state

Cloud checks in this cycle are Git/history/source review only. No shell, `uv`, generator, Python test,
JS test, GPU/runtime probe or Launcher test was executed. Tests present in fork `main` are existing
repository evidence, not newly executed proof for the sync branch.

## Conflict hierarchy to preserve

1. Prefer current upstream implementation for upstream-owned behavior.
2. Preserve downstream intent, not obsolete downstream lines.
3. Keep unique fork behavior in existing fork-owned modules/adapters/seams with narrow shared-file hooks.
4. Preserve profile/root isolation, authorization, persistence/recovery, lifecycle, path/read/write and
   completion/crash-race protections unless semantic equivalence is proven.
5. Preserve one downstream Local llama lifecycle/RPC owner; reuse upstream primitives without adopting
   an independent automatic supervisor as authority.
6. Use each touched overlap to reduce future merge surface without unrelated refactors.

## Acceptance boundary

`automation/upstream-sync` is a staging line. `HANDOFF_ONLY` is not a merge candidate. A later
`SOURCE_CANDIDATE` is still accepted only after the operator tests that exact immutable SHA locally.
Preserve the real upstream merge ancestry when landing; do not squash/cherry-pick away the integration
history.

---

# 2026-09-17 sync preparation — pinned target `cdceca42e1`

State: **ANALYSIS_ONLY.** No merge was landed, nothing was pushed to `main`. This section records a real, executed conflict preview against a pinned upstream target and the ledger needed to plan the integration. Work branch: `automation/upstream-sync-next`, cut from `origin/automation/upstream-sync`.

## Pinned inputs

| role | SHA | note |
| --- | --- | --- |
| last accepted upstream (`B`, merge base) | `416a8177c25d87aa9929dfcf31f7964137d7fcdd` | ancestor of both sides, verified |
| fork `main` (`F`) | `68b24d4254c56550688707e805ec5755c1823f10` | 25 commits on `B` |
| sync branch tip before this section | `e45270a989` | already contains `F`; `git merge --no-edit origin/main` answered *Already up to date* |
| **pinned upstream target (`U`)** | **`cdceca42e107f0e51ab9ff50e1cc881ad76b577e`** | 2026-09-17 16:49:57 -0400, *test(gateway): cover watchdog fallback for empty agent holder and raising snapshot*; **1,222** commits past `B` |
| published compact fork (fold tip) | `0d5b7b8abccc07eb21d20d789fd0e14b68591aa4` | fold guard anchor |

**Upstream moved during this session.** The `git fetch upstream main` that opened this cycle advanced `upstream/main` from `cdceca42e1` to `0a8d4caef4` (*Merge pull request #114261 … feat/catalog-mnemosyne-rekey*, 2026-09-17 16:54:07 -0700). Every number in this section is measured against the **pinned** `cdceca42e1` and nothing else; `0a8d4caef4` is recorded here only so the next cycle does not mistake it for a rewrite. Ancestry `B -> U` is linear; no upstream history rewrite was detected.

## Fold guard

`git merge-base --is-ancestor 0d5b7b8abc <ref>`, upstream refs exempt:

| ref | result |
| --- | --- |
| `origin/main` (68b24d4254) | **PASS** |
| `origin/automation/upstream-sync` (e45270a989) | **PASS** |
| `automation/upstream-sync-next` HEAD (e45270a989) | **PASS** |
| upstream `cdceca42e1` | does not contain the fold — **expected**, it is the other side |

No pre-fold commit is reachable from anything this cycle builds on. `416a8177c2` is an ancestor of both `cdceca42e1` and `origin/main`.

## Overlap ledger

```
git diff --name-only 416a8177c2 cdceca42e1 | sort        ->  1,802 files (upstream side)
git diff --name-only 416a8177c2 origin/main | sort       ->  1,756 files (fork side)
comm -12 of the two                                      ->    158 files (the overlap)
```

Ownership is the **last `fork: *` commit to touch the file** in `416a8177c2..origin/main` (`git log --format=%s 416a8177c2..origin/main -- <file> | grep -m1 '^fork:'`); a file no `fork: *` commit touched is `post-fold`.

| fold theme | files | of which conflict today |
| --- | ---: | ---: |
| `fork: core tool seams` | 37 | 5 |
| `fork: build test platform` | 34 | 5 |
| `fork: transport` | 22 | 1 |
| `fork: conversation` | 14 | 2 |
| `fork: skills tools mcp` | 13 | 3 |
| `fork: auth config provider` | 13 | 4 |
| `fork: office board graph` | 8 | 1 |
| `fork: persona lifecycle` | 6 | 5 |
| `fork: runtime storage` | 4 | 0 |
| `fork: documentation` | 4 | 0 |
| `fork: realm sync` | 2 | 0 |
| `post-fold` | 1 | 0 |
| **total** | **158** | **26** |

### Full per-theme file lists

<details>
<summary><code>fork: core tool seams</code> — 37 files</summary>

- `agent/agent_init.py`
- `agent/conversation_loop.py`
- `agent/image_routing.py`
- `agent/session_persistence.py`  **[CONFLICTS]**
- `run_agent.py`
- `tests/agent/test_anthropic_adapter.py`
- `tests/agent/test_image_routing.py`
- `tests/tools/test_approval.py`  **[CONFLICTS]**
- `tests/tools/test_browser_console.py`
- `tests/tools/test_checkpoint_manager.py`
- `tests/tools/test_code_execution.py`
- `tests/tools/test_computer_use.py`
- `tests/tools/test_image_generation.py`
- `tests/tools/test_local_env_blocklist.py`
- `tests/tools/test_modal_sandbox_fixes.py`
- `tests/tools/test_process_registry.py`
- `tests/tools/test_terminal_tool_requirements.py`
- `tests/tools/test_vision_native_fast_path.py`
- `tools/approval_detection.py`  **[CONFLICTS]**
- `tools/browser_tool.py`
- `tools/browser_tool_lifecycle.py`
- `tools/checkpoint_manager.py`
- `tools/clarify_tool.py`
- `tools/code_execution_env.py`
- `tools/code_execution_tool.py`
- `tools/environments/local.py`
- `tools/file_operations.py`
- `tools/file_tools.py`
- `tools/file_tools_write_guards.py`
- `tools/image_generation_tool.py`
- `tools/lazy_deps.py`
- `tools/process_registry.py`  **[CONFLICTS]**
- `tools/process_registry_notifications.py`
- `tools/registry.py`  **[CONFLICTS]**
- `tools/terminal_tool.py`
- `tools/vision_tools.py`
- `tools/web_tools.py`

</details>

<details>
<summary><code>fork: build test platform</code> — 34 files</summary>

- `.github/workflows/js-tests.yml`
- `.gitignore`
- `cli.py`
- `hermes_cli/doctor_platform.py`  **[CONFLICTS]**
- `hermes_cli/doctor_state.py`
- `hermes_cli/main.py`  **[CONFLICTS]**
- `hermes_cli/main_desktop.py`
- `hermes_cli/main_web_build.py`
- `hermes_cli/service_manager.py`
- `hermes_cli/update_cmd.py`
- `hermes_cli/update_cmd_git.py`
- `hermes_cli/update_cmd_windows.py`
- `hermes_cli/update_inventory.py`
- `hermes_cli/worktree_ops.py`
- `hermes_constants.py`
- `pyproject.toml`
- `scripts/desktop-update/windows.ps1`
- `scripts/install.ps1`
- `scripts/install.sh`
- `tests/agent/conftest.py`
- `tests/conftest.py`
- `tests/hermes_cli/conftest.py`  **[CONFLICTS]**
- `tests/hermes_cli/test_active_sessions.py`
- `tests/hermes_cli/test_cmd_update.py`
- `tests/hermes_cli/test_gui_command.py`
- `tests/hermes_cli/test_managed_uv.py`  **[CONFLICTS]**
- `tests/hermes_cli/test_relay_shared_metrics.py`
- `tests/hermes_cli/test_update_autostash.py`
- `tests/hermes_cli/test_update_concurrent_quarantine.py`
- `tests/hermes_cli/test_update_fleet_restart_pending.py`
- `tests/hermes_cli/test_update_stale_dashboard.py`
- `tests/test_hermes_constants.py`
- `utils.py`
- `uv.lock`  **[CONFLICTS]**

</details>

<details>
<summary><code>fork: transport</code> — 22 files</summary>

- `gateway/lifecycle_ledger.py`
- `gateway/platforms/base.py`
- `gateway/run.py`
- `gateway/run_busy.py`
- `gateway/run_notifications.py`
- `gateway/run_startup.py`
- `gateway/run_turn.py`
- `gateway/status.py`
- `hermes_cli/gateway.py`
- `hermes_cli/gateway_windows.py`
- `hermes_cli/web_server.py`
- `tests/gateway/test_api_server_active_work_drain.py`
- `tests/gateway/test_background_process_notifications.py`
- `tests/gateway/test_cron_interrupt_notification.py`
- `tests/gateway/test_status_command.py`
- `tests/gateway/test_update_command.py`
- `tests/hermes_cli/test_gateway.py`
- `tests/hermes_cli/test_gateway_service.py`
- `tests/tui_gateway/test_tui_gateway_server.py`
- `tui_gateway/entry.py`
- `tui_gateway/server.py`
- `tui_gateway/session_notifications.py`  **[CONFLICTS]**

</details>

<details>
<summary><code>fork: conversation</code> — 14 files</summary>

- `agent/auxiliary_client.py`
- `agent/chat_completion_helpers.py`  **[CONFLICTS]**
- `agent/conversation_compression.py`  **[CONFLICTS]**
- `agent/prompt_builder.py`
- `agent/system_prompt.py`
- `agent/turn_api_call.py`
- `agent/turn_context.py`
- `agent/turn_finalizer.py`
- `agent/turn_response_check.py`
- `agent/turn_response_intake.py`
- `agent/turn_usage.py`
- `tests/agent/test_compression_feasibility.py`
- `tests/agent/test_prompt_builder.py`
- `tests/agent/test_system_prompt.py`

</details>

<details>
<summary><code>fork: skills tools mcp</code> — 13 files</summary>

- `agent/skill_commands.py`
- `agent/skill_utils.py`  **[CONFLICTS]**
- `hermes_cli/plugins.py`
- `hermes_cli/plugins_discovery.py`
- `plugins/memory/__init__.py`
- `plugins/platforms/feishu/adapter.py`
- `tests/hermes_cli/test_mcp_startup.py`
- `tests/tools/test_skills_guard.py`
- `tests/tools/test_skills_hub.py`
- `tests/tools/test_skills_tool.py`  **[CONFLICTS]**
- `tools/mcp_tool_config.py`
- `tools/mcp_tool_transport.py`
- `tools/skills_tool.py`  **[CONFLICTS]**

</details>

<details>
<summary><code>fork: auth config provider</code> — 13 files</summary>

- `agent/codex_runtime.py`
- `agent/credential_pool.py`  **[CONFLICTS]**
- `cli-config.yaml.example`
- `hermes_cli/auth.py`  **[CONFLICTS]**
- `hermes_cli/auth_codex.py`
- `hermes_cli/auth_commands.py`
- `hermes_cli/auth_nous.py`
- `hermes_cli/config.py`
- `hermes_cli/config_defaults.py`
- `hermes_cli/runtime_provider.py`  **[CONFLICTS]**
- `tests/agent/test_provider_fallback.py`
- `tests/hermes_cli/test_auth_profile_fallback.py`  **[CONFLICTS]**
- `tests/hermes_cli/test_config.py`

</details>

<details>
<summary><code>fork: office board graph</code> — 8 files</summary>

- `hermes_cli/kanban.py`
- `hermes_cli/kanban_db.py`
- `hermes_cli/kanban_db_dispatch.py`
- `hermes_cli/kanban_ops.py`
- `hermes_cli/kanban_parser.py`
- `tests/hermes_cli/test_kanban_db.py`
- `tests/hermes_cli/test_kanban_per_profile_cap.py`
- `website/docs/user-guide/features/kanban.md`  **[CONFLICTS]**

</details>

<details>
<summary><code>fork: persona lifecycle</code> — 6 files</summary>

- `hermes_cli/profile_cmd.py`  **[CONFLICTS]**
- `hermes_cli/profiles.py`  **[CONFLICTS]**
- `hermes_cli/subcommands/profile.py`
- `hermes_cli/web_routers/profiles.py`  **[CONFLICTS]**
- `tests/hermes_cli/test_apply_profile_override.py`  **[CONFLICTS]**
- `tests/hermes_cli/test_profiles.py`  **[CONFLICTS]**

</details>

<details>
<summary><code>fork: runtime storage</code> — 4 files</summary>

- `hermes_state.py`
- `hermes_state_messages.py`
- `hermes_state_sessions.py`
- `tests/hermes_state/test_session_db_read_conn_pool.py`

</details>

<details>
<summary><code>fork: documentation</code> — 4 files</summary>

- `website/docs/reference/mcp-config-reference.md`
- `website/docs/reference/slash-commands.md`
- `website/docs/user-guide/docker.md`
- `website/docs/user-guide/messaging/index.md`

</details>

<details>
<summary><code>fork: realm sync</code> — 2 files</summary>

- `tests/tools/test_async_delegation.py`
- `tools/async_delegation.py`

</details>

<details>
<summary><code>post-fold</code> — 1 files</summary>

- `tests/hermes_cli/test_doctor_journal_modes.py`

</details>

## Conflict preview — executed, then aborted

System git here is **2.31.1**: `git merge-tree --write-tree` does not exist and exits 128, which is indistinguishable from "conflicts" if only the return code is read. The preview below is therefore a real merge in the worktree:

```
git merge --no-commit --no-ff cdceca42e1   # rc=1, 'Automatic merge failed'
git diff --name-only --diff-filter=U       # 26 files
git merge --abort                          # rc=0
git status --porcelain                     # empty; no MERGE_HEAD
```

**26 conflicting files: 25 content, 1 modify/delete, 0 add/add.** Kind is read from the index stages (`git ls-files -u`): 1+2+3 = content, 1+2 or 1+3 = modify/delete, 2+3 = add/add. Hunks = count of `<<<<<<<` markers.

| file | kind | hunks | fold theme | recurs from 09-15 |
| --- | --- | ---: | --- | --- |
| `agent/chat_completion_helpers.py` | content | 1 | `fork: conversation` | no |
| `agent/conversation_compression.py` | content | 1 | `fork: conversation` | no |
| `agent/credential_pool.py` | content | 3 | `fork: auth config provider` | no |
| `agent/session_persistence.py` | content | 1 | `fork: core tool seams` | no |
| `agent/skill_utils.py` | content | 1 | `fork: skills tools mcp` | no |
| `hermes_cli/auth.py` | content | 1 | `fork: auth config provider` | no |
| `hermes_cli/doctor_platform.py` | content | 1 | `fork: build test platform` | **yes** |
| `hermes_cli/main.py` | content | 2 | `fork: build test platform` | **yes** |
| `hermes_cli/profile_cmd.py` | content | 1 | `fork: persona lifecycle` | no |
| `hermes_cli/profiles.py` | content | 1 | `fork: persona lifecycle` | no |
| `hermes_cli/runtime_provider.py` | content | 2 | `fork: auth config provider` | no |
| `hermes_cli/web_routers/profiles.py` | content | 2 | `fork: persona lifecycle` | no |
| `tests/hermes_cli/conftest.py` | content | 1 | `fork: build test platform` | no |
| `tests/hermes_cli/test_apply_profile_override.py` | content | 1 | `fork: persona lifecycle` | no |
| `tests/hermes_cli/test_auth_profile_fallback.py` | modify/delete | n/a | `fork: auth config provider` | no |
| `tests/hermes_cli/test_managed_uv.py` | content | 1 | `fork: build test platform` | no |
| `tests/hermes_cli/test_profiles.py` | content | 1 | `fork: persona lifecycle` | no |
| `tests/tools/test_approval.py` | content | 1 | `fork: core tool seams` | no |
| `tests/tools/test_skills_tool.py` | content | 1 | `fork: skills tools mcp` | no |
| `tools/approval_detection.py` | content | 1 | `fork: core tool seams` | no |
| `tools/process_registry.py` | content | 1 | `fork: core tool seams` | **yes** |
| `tools/registry.py` | content | 2 | `fork: core tool seams` | no |
| `tools/skills_tool.py` | content | 1 | `fork: skills tools mcp` | **yes** |
| `tui_gateway/session_notifications.py` | content | 1 | `fork: transport` | no |
| `uv.lock` | content | 2 | `fork: build test platform` | no |
| `website/docs/user-guide/features/kanban.md` | content | 1 | `fork: office board graph` | **yes** |

### The one modify/delete, and why it is the headline

`tests/hermes_cli/test_auth_profile_fallback.py` — **deleted upstream, modified in HEAD**; git left the fork's version in the tree. This is not a stale-test cleanup, it is a **deliberate upstream reversal of the behaviour the fork test asserts**. Upstream `93889b770d` (*fix(auth): named profiles no longer inherit the root profile's auth.json*, #111724, 2026-09-16) deletes that file and adds `tests/hermes_cli/test_auth_profile_isolation.py` asserting the opposite, while stripping 256 lines from `agent/credential_pool.py`, 172 from `hermes_cli/auth.py` and 538 from `hermes_cli/auth_oauth_grants.py`. The fork's file, last touched by `fork: auth config provider` (`26fc8d68bb`), documents the fallback as a fix for the #18594 follow-up: *profile workers couldn't see providers authenticated only at the global root*.

That is exactly the Eternia shape — many persona-instance profiles under one root, authenticated once. **This is an operator policy decision, not a merge mechanic**, and it explains the whole four-file `fork: auth config provider` conflict cluster (`agent/credential_pool.py`, `hermes_cli/auth.py`, `hermes_cli/runtime_provider.py`, and this test). Do not resolve it by taking a side per file. Either the fork keeps an explicit, owned fallback seam on top of upstream's isolation (and the test is rewritten to say so), or the fork adopts isolation and every profile is authenticated independently. `hermes_cli/profile_credential_audit.py` is new upstream and may be the seam to build on.

### What upstream did to the other conflicting files

Upstream commit counts in `416a8177c2..cdceca42e1`, newest subject first, for the files that carry real behaviour:

| file | upstream commits | newest upstream subject |
| --- | ---: | --- |
| `website/docs/user-guide/features/kanban.md` | 14 | fix(kanban): goal_mode workers keep the live tool feed in their worker log |
| `hermes_cli/profiles.py` | 14 | fix(cli): inherit the launch profile's custom provider gateway with its model |
| `hermes_cli/main.py` | 11 | fix(sessions): one-shot runs get a distinct `oneshot` source that pickers hide |
| `agent/chat_completion_helpers.py` | 11 | feat(notifications): opt-in suppression of user-channel warning notifications |
| `agent/conversation_compression.py` | 7 | feat(notifications): opt-in suppression of user-channel warning notifications |
| `tui_gateway/session_notifications.py` | 6 | feat(notifications): opt-in suppression of user-channel warning notifications |
| `hermes_cli/runtime_provider.py` | 6 | fix(auth): dead OAuth logins are reported once and leave rotation |
| `tests/hermes_cli/test_managed_uv.py` | 5 | fix(update): let the Windows repoint run; refuse a minor-line jump |
| `tools/registry.py` | 4 | fix(tools): core-tool drop warns only after the probe had admitted it |
| `hermes_cli/profile_cmd.py` | 3 | fix(profiles): purge a deleted profile's session/routing identity on delete |
| `tools/skills_tool.py` | 3 | fix: collapse same-root duplicate skills only when provably the same skill |
| `tools/approval_detection.py` | 2 | fix(approval): deobfuscate every command word in one detection variant (#113535) |
| `tools/process_registry.py` | 2 | fix(process): grace host PID tree teardown |
| `hermes_cli/doctor_platform.py` | 2 | fix(doctor): name the processes holding a WAL database that journal_mode=delete never converted |
| `hermes_cli/web_routers/profiles.py` | 2 | fix(profiles): report a settle-pending delete as a typed partial success |
| `agent/skill_utils.py` | 1 | fix: validate the skill name before opening its lock; key lock files on a digest |
| `agent/session_persistence.py` | 1 | feat(notifications): opt-in suppression of user-channel warning notifications |

Three upstream themes account for most of the non-auth conflicts: the **opt-in warning-notification suppression** feature (four files at once — `agent/session_persistence.py`, `agent/conversation_compression.py`, `agent/chat_completion_helpers.py`, `tui_gateway/session_notifications.py`), the **profile identity/tombstone/delete** work (`hermes_cli/profiles.py`, `profile_cmd.py`, `web_routers/profiles.py`), and **same-root duplicate skill resolution** (`tools/skills_tool.py`, `agent/skill_utils.py`). Each is a coherent upstream change landing across a fork seam, which is the shape the conflict hierarchy already prescribes: take upstream's implementation, re-attach the fork seam.

## Recurrence versus the 2026-09-15 merge

The 09-15 note records "18 files conflicted" without naming them. The set was recovered by replaying that merge in a throwaway detached worktree at the fold tip (`git merge --no-commit --no-ff 416a8177c2` on `0d5b7b8abc`), which reproduces **exactly 18** — the note's count, confirmed rather than assumed. The worktree was aborted and removed.

**5 of the 18 recur** (28% of 09-15; 19% of today's 26):

- `hermes_cli/doctor_platform.py` — `fork: build test platform`
- `hermes_cli/main.py` — `fork: build test platform`
- `tools/process_registry.py` — `fork: core tool seams`
- `tools/skills_tool.py` — `fork: skills tools mcp`
- `website/docs/user-guide/features/kanban.md` — `fork: office board graph`

**13 of the 18 did not recur** — the 09-15 resolutions held, and the `tools/downstream_schema.py` opt-in described in that note visibly did its job: `tools/browser_tool.py`, `tools/terminal_tool.py` and `tools/file_tools.py` were three of the 18 and are clean today.

- `AGENTS.md`
- `agent/codex_runtime.py`
- `agent/prompt_builder.py`
- `agent/skill_commands.py`
- `hermes_cli/gateway_windows.py`
- `tests/hermes_cli/test_gateway_windows.py`
- `tests/hermes_cli/test_local_quickstart.py`
- `tests/tools/test_oneshot_completion_linger.py`
- `tools/AGENTS.md`
- `tools/browser_tool.py`
- `tools/file_tools.py`
- `tools/file_tools_write_guards.py`
- `tools/terminal_tool.py`

**21 are new**, dominated by the auth-isolation reversal and the notification-suppression feature:

- `agent/chat_completion_helpers.py` — `fork: conversation`
- `agent/conversation_compression.py` — `fork: conversation`
- `agent/credential_pool.py` — `fork: auth config provider`
- `agent/session_persistence.py` — `fork: core tool seams`
- `agent/skill_utils.py` — `fork: skills tools mcp`
- `hermes_cli/auth.py` — `fork: auth config provider`
- `hermes_cli/profile_cmd.py` — `fork: persona lifecycle`
- `hermes_cli/profiles.py` — `fork: persona lifecycle`
- `hermes_cli/runtime_provider.py` — `fork: auth config provider`
- `hermes_cli/web_routers/profiles.py` — `fork: persona lifecycle`
- `tests/hermes_cli/conftest.py` — `fork: build test platform`
- `tests/hermes_cli/test_apply_profile_override.py` — `fork: persona lifecycle`
- `tests/hermes_cli/test_auth_profile_fallback.py` — `fork: auth config provider`
- `tests/hermes_cli/test_managed_uv.py` — `fork: build test platform`
- `tests/hermes_cli/test_profiles.py` — `fork: persona lifecycle`
- `tests/tools/test_approval.py` — `fork: core tool seams`
- `tests/tools/test_skills_tool.py` — `fork: skills tools mcp`
- `tools/approval_detection.py` — `fork: core tool seams`
- `tools/registry.py` — `fork: core tool seams`
- `tui_gateway/session_notifications.py` — `fork: transport`
- `uv.lock` — `fork: build test platform`

The five recurring files are the standing high-friction seams. `hermes_cli/main.py`, `hermes_cli/doctor_platform.py`, `tools/process_registry.py`, `tools/skills_tool.py` and `website/docs/user-guide/features/kanban.md` have now conflicted in two consecutive integrations. Per the conflict hierarchy's rule 6, these are the files where the resolution should also **reduce the next merge surface** — narrow the fork's call sites, not re-resolve the same hunks a third time.

## `pyproject.toml` — the decision holds, and git now reaches it unaided

**`pyproject.toml` is not in the conflicting set.** The preview merge auto-merged it, and the auto-merged result is byte-for-byte the decision this handoff recorded:

- fork rows kept: `coverage==7.16.0` and `pytest-timeout==2.4.0` in `dev` (line 207), `coverage = false` and `pytest-timeout = false` under `[tool.uv.exclude-newer-package]` (line 480f);
- upstream's marker present: `real_post_swap_handoff: opt out of the autouse stub that runs the update post-swap tail in-process` (line 614);
- zero conflict markers in the merged file.

Blob identities confirm the earlier analysis is still live rather than merely re-asserted: upstream's `pyproject.toml` at `cdceca42e1` is `34c382a6e47fadeb37814a85ad9f527e6bf3320a` — **the same blob this handoff recorded at upstream `98f758ae7e`**, so upstream has not touched the file since. Fork blob `529fbed5c565749f71f33be1e2eae7f154f522cc`, base blob `4ddeea131d7f37af5416fdbb9463380ef5f88add`.

The full upstream-vs-fork delta is wider than the two dependency rows and every other line is fork-owned and must survive: `agent_runtime`/`agent_runtime.*` in `packages.include`; `--timeout=30 --timeout-method=thread` in `addopts`; ruff `F821` in `select` with its per-path ignores; and the fork-only markers `real_venv_pip` and `real_agent_browser_probe`. The auto-merge preserves all of them. **Verdict: no hand resolution needed for this file — but verify the four items above in the real merge rather than trusting this note, because a later upstream `pyproject.toml` edit would change the outcome.**

## `uv.lock` — still a generated blocker, now an actual conflict

`uv.lock` **does** conflict (content, 2 hunks). Blobs are unchanged from this handoff's earlier record — fork `c9e2c9a657ca6a69b4a77d49b85b6233a3bb6745`, upstream `6d381729736fb8b318236863844a51781be19e23` — confirming upstream has not relocked since `98f758ae7e` either. Neither side may be selected wholesale, and the two conflict hunks must **not** be hand-resolved. Resolve `pyproject.toml` first (it needs no work, above), then regenerate the lock from that exact merged source with the repository's canonical `uv lock` workflow in a real checkout, and verify the lock corresponds to that tree. Do not fabricate lock content.

## Recommended per-theme merge order

One merge commit is still the goal — preserving real upstream ancestry, per the acceptance boundary. The order below is the order to **resolve the conflicted paths in**, chosen so that each group is a single coherent decision and the one policy decision is not made accidentally while resolving something else.

| # | theme | files | why here |
| --- | --- | ---: | --- |
| 1 | `fork: office board graph` + docs | 1 | `website/docs/user-guide/features/kanban.md` — prose only, 14 upstream commits, no runtime risk. Resolve first to clear noise and to see the shape of upstream's kanban changes before touching kanban-adjacent code. |
| 2 | `fork: core tool seams` | 5 | `tools/registry.py`, `tools/process_registry.py`, `tools/approval_detection.py`, `agent/session_persistence.py`, `tests/tools/test_approval.py`. Upstream changes are small, well-described bug fixes; the fork owns narrow seams. Take upstream, re-attach the seam. Two of these are 09-15 recurrences — narrow the call sites here. |
| 3 | `fork: skills tools mcp` | 3 | `tools/skills_tool.py`, `agent/skill_utils.py`, `tests/tools/test_skills_tool.py` — one upstream story (same-root duplicate resolution + digest-keyed skill locks) against the fork's package-ownership filtering in the shared resolver, which the 09-15 note says to keep. |
| 4 | `fork: conversation` + `fork: transport` | 3 | `agent/chat_completion_helpers.py`, `agent/conversation_compression.py`, `tui_gateway/session_notifications.py`. Resolve together: all three are the same upstream notification-suppression feature plus Codex effort/watchdog work. Splitting them across sessions is how a half-wired feature lands. |
| 5 | `fork: build test platform` | 5 (minus lock) | `hermes_cli/main.py`, `hermes_cli/doctor_platform.py`, `tests/hermes_cli/conftest.py`, `tests/hermes_cli/test_managed_uv.py`. Test-harness and CLI-entry surface; `main.py` and `doctor_platform.py` are both 09-15 recurrences. |
| 6 | `fork: persona lifecycle` | 5 | `hermes_cli/profiles.py`, `profile_cmd.py`, `web_routers/profiles.py`, `tests/hermes_cli/test_profiles.py`, `test_apply_profile_override.py`. 14 upstream commits on `profiles.py` alone (tombstones, rename identity migration, delete purge). The 09-15 ruling stands: profile bootstrap stays in the extracted module; port upstream's invocation normalization **there**, never restore a second inline implementation. |
| 7 | `fork: auth config provider` | 4 | **The policy decision.** `agent/credential_pool.py` (3 hunks), `hermes_cli/auth.py`, `hermes_cli/runtime_provider.py`, and the modify/delete `tests/hermes_cli/test_auth_profile_fallback.py`. Last on purpose: it needs an operator ruling on root-auth fallback vs upstream isolation, and nothing else should be blocked waiting for it. |
| 8 | `uv.lock` | 1 | Generated. Only after 1–7 and `pyproject.toml` are final. `uv lock`, never hand-edited. |

Verification after resolution, per this handoff's continuation list and `docs/downstream-development.md`: `scripts/run_tests.sh` only (never bare pytest), the validated four-directory scope `tests/agent_runtime tests/hermes_cli tests/cli tests/state`, plus `python scripts/dump_cli_contract.py --check` and `python scripts/dump_payload_contract.py --check` — the fork's model-picker work already moves the CLI contract, and themes 6–7 touch the profile CLI directly. Budget at least 25 minutes for the suite scope. Nothing in this section was tested; it is Git/source analysis only. No shell test, `uv` run, generator or runtime probe was executed for it.

## Theme 7 ruling — RULED 2026-09-17 (operator): adopt upstream isolation, keep the fork's explicit store binding

Upstream `93889b770d` (2026-09-16, "named profiles no longer inherit the root profile's auth.json") is a
policy reversal, not a code conflict, and the operator ruled on it rather than leaving it to a per-file
merge. Background the ruling rests on: the fork isolates persona profiles' environments (its own
`HERMES_HOME` per profile, which upstream did not do at the time), so it needed a way for those profiles
to reach credentials held at the head — and it built its own, explicit one, alongside the general
(head/root) profile it also runs. That mechanism is **`HERMES_AUTH_HOME`**, fork-only (zero hits on
upstream `main`): `agent_runtime/profile_context.py` pins every persona profile's *active auth store* to
the head's, mirrored into both the ContextVar (`set_hermes_auth_home_override`) and the spawn env. That
is store **selection**, not the inheritance **fallback** upstream deleted.

Ruling:

1. **Runtime default = upstream's.** Profiles are islands. Take upstream's side of
   `agent/credential_pool.py`, `hermes_cli/auth.py`, `hermes_cli/auth_oauth_grants.py`,
   `agent/anthropic_credentials.py` and the related modules; accept the deletion of
   `tests/hermes_cli/test_auth_profile_fallback.py` (the modify/delete resolves as **delete**) and adopt
   upstream's `tests/hermes_cli/test_auth_profile_isolation.py`. No implicit root fallback, no root
   write-through, no borrowed-row bookkeeping survive in the fork. The auth cluster returns to
   upstream-owned code the fork stops re-patching every sync.
2. **Sharing survives only through the fork's one seam.** A persona profile shares credentials because
   Mission Control bound its active auth store to the head via `HERMES_AUTH_HOME` — explicit,
   one-directional, chosen by the operator's runtime. Token rotation lands in the head store because
   it *is* the active store, so single-use refresh chains (Codex/ChatGPT) never fork and no
   write-through logic is needed. Upstream's ruling ("never handed another profile's auth") is honoured:
   nobody inherits.
3. **Re-seat the two fork extensions that still lean on the deleted fallback:**
   `agent_runtime/auth_extensions.py` (the Codex "global-root singleton fallback", ~lines 134–191 at
   `68b24d4254`) and the comment in `tools/managed_tool_gateway.py:45`. With the head store active the
   singleton is simply *in* the store; the fallback branch is removed, not ported.
4. **Fork-owned surface after the merge:** `get_hermes_auth_home()` / `set_hermes_auth_home_override()`
   in `hermes_constants.py`, plus the single call site where the auth store path is resolved. Narrow
   call site in a shared file, owned module for the behaviour — the shape the 2026-09-15 note asked for.
5. **Positive control, red-first, on this branch before `SOURCE_CANDIDATE`:** a persona profile with an
   *empty* auth store of its own, bound under `persona_profile_context`, resolves the head's Codex
   provider with upstream's fallback code gone; the same profile *outside* the context does not.
   Name the killing mutation (drop the `HERMES_AUTH_HOME` pin in `profile_context.py`) and record the red.

Named risk: upstream's original fallback (`33bf5f62`) existed for kanban/cron workers under named
profiles **outside** any persona context. Any such worker that authenticates only at the head will start
refusing with "set a provider for profile X" after this sync. Upstream's `hermes update` audit
(`hermes_cli/profile_credential_audit.py`) prints exactly that list on the first update, so the failure
is announced, not silent; the operator accepts it.

## Acceptance state after this section

State stays **ANALYSIS_ONLY / HANDOFF_ONLY**. `automation/upstream-sync-next` carries this ledger and the
theme-7 ruling and nothing else; it contains no upstream merge parent, and `main` is untouched. The
branch passes the fold guard. The auth policy decision in theme 7 is now **ruled** (above). Promote to
`SOURCE_CANDIDATE` only when `cdceca42e1` (or a deliberately re-pinned later tip) is actually in ancestry
and the theme-7 positive control has been recorded red-then-green.

---

# 2026-09-17 merge execution — `cdceca42e1` merged, one history-preserving merge commit

State: **SOURCE_CANDIDATE** (promoted 2026-09-18 after the owner rulings; this section records the
merge as executed, and the ruling outcomes are in the 2026-09-18 section at the end). The pinned
upstream target `cdceca42e1` IS in ancestry. The theme-7 positive control IS recorded red-then-green. Nothing was pushed
to `main`. The exact remaining list is in **Still red, with the diagnosis** below; the three
promotion conditions and their status are restated at the end of this section.

## Preconditions, measured

| check | result |
| --- | --- |
| fold guard on branch base (`dc172f0864`) | `git merge-base --is-ancestor 0d5b7b8abc HEAD` → **PASS** |
| fork `main` contained before the upstream merge | `git merge --no-edit origin/main` → clean merge `94a5db103d` (fork main `0bd06e91d1`) |
| fold guard after that merge | **PASS** |
| pinned target | `cdceca42e1` exactly. `upstream/main` has since moved to `e83b1d51f1`; deliberately NOT re-pinned. |

## Conflicting set versus the handoff's 26

`git merge --no-ff --no-commit cdceca42e1` → rc=1; `git diff --name-only --diff-filter=U` → **26
files, identical to the handoff's list, file for file.** The two fork commits that landed on `main`
the same day — `ce557b3fb2` (*fix(mcp): stdio MCP child receives the bound profile's HERMES_HOME*)
and `0bd06e91d1` (*fix(discussions): map room-store and room-policy refusals to the typed lane*, the
Discussion Tables landing) — introduced **no new conflict**: both touch fork-owned trees
(`agent_runtime/`, `tests/agent_runtime/`) that upstream does not have.

## Per-file ledger

`upstream` = upstream's implementation taken as-is. `fork-seam re-attached` = upstream's
implementation with the fork's narrow call site put back on top. `both` = the two sides are additive
and neither is a replacement for the other.

| # | file | decision | why |
| ---: | --- | --- | --- |
| 1 | `website/docs/user-guide/features/kanban.md` | both | The `crashed` payload row. Both sides are live in the merged code (`kanban_db_dispatch.py:982` writes `worker_output`; `:1074` writes `classification`/`evidence_path`), so one row documents both — checked in the source, not inferred from the diff. |
| 2 | `tools/registry.py` | fork-seam re-attached | Upstream's core-drop WARNING gate (`_check_fn_ever_good`, #112649) taken whole, including its demotion of the ordinary verdict to INFO. The fork's 3-tuple cache entry (explicit expiry, read by `get_cached_check_fn_result`) and `_check_fn_epoch` survive: upstream's 2-tuple writes are re-spelled with the expiry. |
| 3 | `tools/process_registry.py` | fork-seam re-attached | Upstream's only change to the conflicted function is its new `-> bool` contract ("True when this call persisted the session"), consumed by its new `kill_process` re-write path. The fork's notify-request delivery body is kept and given that contract: `return False` on a duplicate move, `return True` on every path that persisted. The fork's `_completion_event_payload` was verified field-for-field against upstream's inline dict — nothing of upstream's payload is dropped. |
| 4 | `tools/approval_detection.py` | upstream | Comment only. Upstream's wording carries the measured reason (GIL/Gateway starvation); the fork's near-duplicate comment two lines up was removed rather than left to disagree. |
| 5 | `agent/session_persistence.py` | fork-seam re-attached | Upstream's `_mute_notification_reply` display marking taken whole; the fork's `msg_idx` argument to `_db_flush_row` re-attached. |
| 6 | `tests/tools/test_approval.py` | both | Import line; both modules are used. |
| 7 | `tools/skills_tool.py` | fork-seam re-attached | Upstream's same-root duplicate collapse (#112179) taken whole. The fork's `as_posix()` spelling of the refusal message is kept, and applied to upstream's new duplicate list too, which otherwise printed `str()` on the same paths. |
| 8 | `agent/skill_utils.py` | both | `EXCLUDED_SKILL_DIRS`: upstream's `.locks` plus the fork's `.realm_inbox` / `.provenance`. |
| 9 | `tests/tools/test_skills_tool.py` | both | Two additive test blocks at EOF (fork's `TestSkillSearch`; upstream's `TestSameRootDuplicationResolves` + `TestTrustWarningSymlinkAware`). |
| 10 | `agent/chat_completion_helpers.py` | fork-seam re-attached | Upstream's `_consume_ephemeral_max_output` taken; the fork's `transport` binding, `header_cache_scope_id` and the cache-routing observability tail after the call all survive — upstream returned directly, which would have deleted that tail. |
| 11 | `agent/conversation_compression.py` | fork-seam re-attached | Upstream's `_compression_child_source` taken; it subsumes the fork's `agent.platform or env` read and adds the parent-row source (#112550). The fork's `child_model_config(agent)` is kept over upstream's bare `_session_init_model_config` — it is a strict superset of it. |
| 12 | `tui_gateway/session_notifications.py` | fork-seam re-attached | Upstream's `render_notification` wrapper taken; the fork's `_tui_background_agent_turns_enabled()` gate re-attached after the emit loop. |
| 13 | `hermes_cli/main.py` | fork-seam re-attached | The 09-15 ruling holds: profile bootstrap stays in `hermes_cli/_profile_bootstrap.py` and `main.py` keeps its import-only form. Upstream's two behaviour changes inside the conflicted region were PORTED into that module, not restored inline — rows 13a/13b. Everything upstream added outside it (`_warn_if_unsupervised_pid1`, `_install_rebuilt_desktop_app`, `CLI_FAMILY_SOURCES`, `HERMES_SESSION_SOURCE_EXPLICIT`) auto-merged and was verified present. |
| 13a | `hermes_cli/_profile_bootstrap.py` | upstream ported | `_resolve_sudo_user_profile_env`: `candidate.is_dir()` → `named_profile_is_live(candidate)`. |
| 13b | `hermes_cli/_profile_bootstrap.py` | upstream ported | `apply_profile_override`: upstream's `HERMES_UPDATE_POST_SWAP` early return. The fork's resolution receipt stays `default` on that path — `gateway_home_receipt.py`'s four rungs are a closed set this port deliberately does not widen. |
| 14 | `hermes_cli/doctor_platform.py` | fork-seam re-attached | Upstream's `resolve_journal_mode` and its docstring taken. Upstream's `from hermes_cli.doctor import HERMES_HOME` is NOT taken: a module-level frozen home is the exact bug class `docs/downstream-development.md` rule 3 bans. Call-time `get_hermes_home()` kept, with the reason stated at the site. |
| 15 | `tests/hermes_cli/conftest.py` | both | Two additive autouse fixtures. |
| 16 | `tests/hermes_cli/test_managed_uv.py` | upstream | Upstream `290bdc3c76` RETIRED `_windows_runtime_self_lock` with a live windows-latest receipt; the helper is gone from `managed_uv.py`, so `TestWindowsRuntimeSelfLock` was deleted with it. The fork's `TestExplicitPosixInstaller` (no upstream counterpart; `_install_uv_posix` still exists) was kept. |
| 17 | `hermes_cli/profiles.py` | both | Upstream's `ProfileIdentitySettlementPending` class added; the fork's `force_unverified_writers` keyword kept on `delete_profile`. |
| 18 | `hermes_cli/profile_cmd.py` | both | `except ProfileDeleteBlocked` (fork, first so it wins) then upstream's widened `(ValueError, FileNotFoundError, RuntimeError)`. |
| 19 | `hermes_cli/web_routers/profiles.py` | both | Both typed answers survive: the fork's 409 refusal and upstream's `settlement_pending` partial success. The handler body had already auto-merged; only the two docstrings and the `ProfileDeleteBlocked` import conflicted. |
| 20 | `tests/hermes_cli/test_apply_profile_override.py` | upstream | Upstream's `config.yaml` identity markers adopted (required by `named_profile_is_live`); the fork's explicit `encoding="utf-8"` kept on the `active_profile` write. |
| 21 | `tests/hermes_cli/test_profiles.py` | both | Two additive test blocks. |
| 22 | `agent/credential_pool.py` | fork-seam re-attached | **Not a theme-7 file in substance.** The fork's entire delta here is the pool-ROTATION extension (`agent_runtime/pool_rotation.py`), not the auth fallback, so "take upstream's side" does not reach it. Both mixins are on the class (`PoolRotationMixin` first in the MRO; no member of the three collides) and `_select_unlocked` carries both keywords. |
| 23 | `hermes_cli/auth.py` | upstream + re-seat | See theme 7 below. |
| 24 | `hermes_cli/runtime_provider.py` | fork-seam re-attached | Upstream's `_raise_for_credentialless_bare_custom` taken, raised outside the rotation scope where it belongs; the fork's `pool_rotation_scope` wrapper and `_select_pool_entry` seam kept, with upstream's new `model=` threaded THROUGH the seam so the model-cooldown filter is not lost on the non-persisting read path. |
| 25 | `tests/hermes_cli/test_auth_profile_fallback.py` | upstream (DELETE) | The modify/delete resolved as delete, per the ruling. |
| 26 | `uv.lock` | regenerated | Neither side taken. `uv lock` (uv 0.11.14) from the final merged `pyproject.toml`. |

`pyproject.toml` (theme 8) auto-merged, as the handoff predicted, and all four recorded items were
verified **in the real merge** rather than trusted from the note: `coverage==7.16.0` and
`pytest-timeout==2.4.0` in `dev` (line 207), their two `[tool.uv.exclude-newer-package]` rows
(481–482), upstream's `real_post_swap_handoff` marker (614), and the fork-owned `agent_runtime`
packages, `--timeout=30 --timeout-method=thread`, ruff `F821`, `real_venv_pip` and
`real_agent_browser_probe` all intact. Zero conflict markers.

## Theme 7 — the ruling, applied

**What the ruling turned out to require that the note did not say.** `HERMES_AUTH_HOME` had exactly
one consumer on the credential path, and it was `_global_auth_file_path` — the read-only FALLBACK
upstream deleted. `_auth_file_path()`, the ACTIVE store, read `get_hermes_home()` and had never
consulted the pin. So deleting the fallback and stopping there would have deleted the sharing
mechanism the ruling explicitly preserves. Ruling point 4 names the repair: *"plus the single call
site where the auth store path is resolved"*. That re-seat is done here.

| change | file | what |
| --- | --- | --- |
| fallback deleted | `hermes_cli/auth.py` | `_global_auth_file_path()` and `_load_global_auth_store()` removed with their mtime cache, as upstream `93889b770d` did. |
| pin re-seated | `hermes_cli/auth.py:468` | `_auth_file_path()` resolves `get_hermes_auth_home()` first, `get_hermes_home()` otherwise. Unbound, byte-for-byte upstream's path. Bound, the head store IS the active store — so a single-use refresh chain lands in the one store and needs no write-through. The pytest seat belt is unchanged. |
| import | `hermes_cli/auth.py:33` | `get_hermes_auth_home` added to the `hermes_constants` import. |
| Codex singleton fallback removed | `agent_runtime/auth_extensions.py:133` | `_read_global_codex_tokens_if_usable()` deleted (ruling point 3). |
| readiness mirror | `agent_runtime/auth_extensions.py` | `codex_auth_store_credentials_present()` returns `False` after the singleton read instead of consulting the deleted fallback; the `_pool_codex_access_token` non-mirroring rationale is kept and re-worded. |
| resolver rung removed | `hermes_cli/auth_codex.py:456` | The `source="global-auth-store"` rung deleted; the reason is stated at the site. |
| picker rung removed | `hermes_cli/model_picker_policy.py:31` | Precedence is now singleton → pool. |
| re-export | `hermes_cli/auth.py` (tail) | `_read_global_codex_tokens_if_usable` dropped from the downstream re-export block. |
| test repointed | `tests/agent_runtime/test_profile_context.py:176` | The context-local/env-mode agreement test now probes `_auth_file_path`. Its guarantee did not move; the call site did. |
| stale monkeypatch | `tests/hermes_cli/test_model_picker_policy.py` | Patch of the deleted symbol removed. |
| doc references | `agent_runtime/profile_context.py:315`, `agent_runtime/profile_readiness.py:137,331`, `hermes_cli/auth_noninteractive.py:82`, `tests/test_hermetic_env_blanking.py:92` | Repointed. `auth_noninteractive`'s note was materially WRONG after the re-seat — it said the pin "governs the read-side fallback only" — and now says the pin selects the active store for reads AND writes. |
| modify/delete | `tests/hermes_cli/test_auth_profile_fallback.py` | DELETE; upstream's `tests/hermes_cli/test_auth_profile_isolation.py` adopted. |

**Ruling item discharged by upstream, not by a fork edit:** `tools/managed_tool_gateway.py:45`. The
fork comment the ruling names (profile-then-global-root fallback, `share_auth`,
`manage_connections` vanishing) was itself replaced by upstream's post-isolation wording in this
merge — the merged file reads *"Reads the profile's own `auth.json` through
`get_provider_auth_state` like every other credential reader"*, which is correct under the new
model. No edit to upstream-owned code was needed.

**Left alone, filed instead:** `auth_json_path()` in that same file is a second resolver of the auth
store path, still spelling `get_hermes_home() / "auth.json"`, which would disagree with
`_auth_file_path()` under a binding. It has **zero callers** anywhere in the tree and is
upstream-owned, so it was not edited. It is a queue row, not a merge decision.

## Accepted risk, restated

Upstream's original fallback existed for kanban/cron workers under named profiles **outside** any
persona context. Such a worker authenticated only at the head will now refuse with "set a provider
for profile X". Upstream's `hermes_cli/profile_credential_audit.py` prints that list on the first
`hermes update`, so the failure is announced, not silent. The operator accepted this.

## Verification — executed once at tip `8be2431138`, then triaged against the pre-merge tip

```
bash scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/cli tests/state -j 8 --file-timeout 180
=== Summary: 1719 files, 20968 tests passed, 268 failed, 378 skipped (100% complete) in 6756.0s (8 workers) ===
=== 85 files with test failures (268 tests failed) ===          exit 1
```

`-j 8` is the ruled full-suite lane (`docs/downstream-development.md`, hermes-suite-perf R3), not
the `-j 4` the task text suggested; at 4 workers the same scope was on track for ~4.5 hours and was
restarted rather than finished, because the restart also gave one clean pass over a tree that
already carried the first round of fixes. **`tests/cli` and `tests/state` are completely green** —
every failure is in `tests/agent_runtime` (13 files) or `tests/hermes_cli` (76 files).

Three files never ran at all (collection/import error, or timeout before collection) and are
counted as neither pass nor fail: `tests/hermes_cli/test_dashboard_system_gateway_elevation.py`,
`tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` (exit 124), `tests/hermes_cli/test_gateway.py`.

### The split, and how it was taken

A raw failure count says nothing about a merge. Every failing file was re-run at the **pre-merge
tip** `94a5db103d` — fork `main` plus this branch, without the upstream merge — in a throwaway
detached worktree:

```
89 failing files at 94a5db103d   ->  70 files / 250 tests fail there too
```

so **250 of the 268 are pre-existing on fork `main` and have nothing to do with upstream.** The
17 candidate files were then re-run at BOTH tips under the same worker count and load, because the
first pass compared a 112-minute loaded run against a 9-minute light one and that difference alone
produced two false positives (`test_goal_workspace_realm_stage42` and `test_harness_tool_inventory`
are load-sensitive: they failed under `-j 4`, passed under `-j 8`, and fail at the pre-merge tip
too). Matched-load result: **16 files / 20 tests genuinely merge-caused.**

Guard on the method itself: `main` and `origin/main` were `0bd06e91d1` before and after the
baseline run, and all worktree registrations survived — recorded because that baseline set includes
`test_worktree.py` and the updater tests that run `git branch -f main origin/main`.

### The 20, and what happened to them

| root cause | tests | outcome |
| --- | ---: | --- |
| fork fixtures froze a signature upstream extended | 9 | **fixed** (`fb4e6206f6`, `8be2431138`) |
| fork profile fixtures had no identity marker | (of the 9) | **fixed** — see below |
| upstream's two new `monkeypatch.undo()` sites vs a fork safety gate | 1 | **fixed**, gate kept |
| upstream message/behaviour the fork test must adopt | 3 | **fixed** |
| an upstream test that cannot pass on Windows (regex-unsafe path) | 1 | **fixed**, worth sending upstream |
| POSIX-only code/tests reaching a Windows host | 8 | **open — environmental** |
| behaviour changes needing a decision, not a guess | 3 | **open — diagnosed below** |
| the CLI contract fixture | 1 | **open by choice** |

Four of the nine signature failures were the SAME defect shape, which is the finding rather than
the four instances: a stub that re-declares a signature it does not own cannot fail as "the thing I
stubbed changed" — it fails as a `TypeError` raised from inside somebody else's call stack. One of
them was worse: `test_readiness_credential_store_quiescent`'s spy raised into a readiness probe that
CATCHES exceptions, so the counter stayed 0 and the gate reported *"vacuous gate: the readiness pass
did not take exactly one non-persisting pool selection"* — a true sentence pointing at nothing. The
instrument was vacuous, not the pass. All four now forward `**kwargs`.

The identity-marker fix had a second-order lesson worth keeping: the first attempt wrote
`config.yaml` as the marker, which broke `test_toolset_declaration`'s "a missing config file
resolves the lane default" — that test DELETES `config.yaml`, so the marker and the subject were
the same file and deleting it un-existed the profile. The marker is now `profile.yaml`.

### Still red, with the diagnosis

**POSIX-only on a Windows host (8 tests, 5 files) — not fixable by this merge.** Upstream code or
tests reach an import that does not exist here: `fcntl` (`test_orphan_desktop_serve_reap`, 3),
`pwd` (`test_gateway_migrate_multiplex`, 2 of its 3), `signal.SIGKILL`
(`test_update_serve_generation_recovery`, 1), a Linux desktop entry (`test_linux_desktop_entry`, 1
of its 24 — the other 23 are pre-existing), and a WSL `/mnt/...` mount walk
(`test_node_runtime_npm_resolution`, 1). `AGENTS.md` prescribes the repair: an OS marker
(`linux_only` / `macos_only`), never a faked `sys.platform`. That is a clean ~5-file follow-up on
upstream-owned tests and is deliberately not bundled into a merge commit.

**Three that need a ruling, not a patch.** Each passes at the pre-merge tip and fails serially (so
not load flakes):

- `test_worktree_selfheal::TestMaintainPackHealth::test_repacks_at_threshold` — "pack count must
  strictly decrease (made=12, after=12)". Upstream replaced the full `repack -a -d` with a
  **bounded incremental geometric repack** (`repack -d --geometric=2 --write-midx`) behind a
  one-slot-per-clone-per-6h lock (`_claim_repack_slot`). Geometric repacking does not guarantee a
  strict decrease, so the fork's assertion encodes a contract upstream deliberately dropped. What
  the new guarantee *is* — decrease, or just "a multi-pack-index now exists" — is a decision;
  inventing a replacement assertion here would encode a belief rather than a measured behaviour.
- `test_kanban_worktree_teardown::test_cleanup_proceeds_when_cwd_was_deleted` — `WinError 32`:
  Windows refuses to delete a directory that is a live process's CWD, which POSIX permits. The test
  is POSIX-shaped in its premise, not just its imports.
- `test_web_server_git::test_gh_auth_refresh_waits_out_a_probe_started_before_it` —
  `{'authenticated': False} != {'authenticated': True}`; a concurrency pin on the `gh` auth probe,
  in a file the merge changed (`hermes_cli/web_routers/git.py`, `web_server.py`).

**`test_cli_contract_dump` is red on purpose.** See the contract section below.

### Contract checks

- `python scripts/dump_payload_contract.py --check` — **clean**, exit 0
  ("4 kinds, 152 keys, sha256 622681856d6c12e8").
- `python scripts/dump_cli_contract.py --check` — **DRIFTED**, exit 1, and **deliberately not
  regenerated**. The drift is **purely additive**: two new subcommands, `profile migrate-identity`
  and `profile purge-identity`, from upstream `a41552fad4`. Zero removals — checked line by line,
  because a removed command or flag is a launcher operator button that now exits 2, and that is the
  dangerous half. Nothing the Launcher calls disappeared.

  It is left red because `tests/fixtures/hermes_cli_contract.json` is a FORK-only file (it does not
  exist upstream) whose whole purpose is that the repo that MOVED goes red, and because the Launcher
  vendors its own copy: regenerating here without re-syncing
  `tool/hermes_cli_contract/` in the same wave would leave the launcher's copy lying, which is the
  exact failure the gate exists to prevent. Regenerate + re-vendor + record the sync in that
  README as one wave.

## Acceptance state after the merge execution

**`HANDOFF_ONLY`.** The three promotion conditions, measured:

| condition | status |
| --- | --- |
| pinned SHA `cdceca42e1` in ancestry | **YES** — `git merge-base --is-ancestor cdceca42e1 HEAD` passes; merge commit `30d89c05e1` carries it as a real second parent |
| fold guard | **PASS** — `git merge-base --is-ancestor 0d5b7b8abc HEAD` |
| theme-7 positive control recorded red-first | **YES** — `c941959441`, killing mutation applied, red output pasted into the commit message, reverted, green |
| verification green | **NO** — 12 merge-caused tests remain red (8 POSIX-on-Windows, 3 needing a ruling, 1 the deliberately un-regenerated CLI contract) |

Promote to `SOURCE_CANDIDATE` only after the four open items are closed or explicitly accepted:

1. OS-mark the five POSIX-only files (`AGENTS.md`: a marker, never a faked `sys.platform`).
2. Rule on the pack-health contract after upstream's geometric-repack change.
3. Decide the two remaining POSIX-premise/concurrency tests
   (`test_cleanup_proceeds_when_cwd_was_deleted`, `test_gh_auth_refresh_waits_out_a_probe_started_before_it`).
4. Regenerate `tests/fixtures/hermes_cli_contract.json` and re-vendor the Launcher's
   `tool/hermes_cli_contract/` in the SAME wave, recording the sha256 in that README.

Owed to the Launcher, and not done in this branch by rule: the CLI contract gained
`profile migrate-identity` and `profile purge-identity`. Additive only — no launcher operator
button was removed — so nothing breaks today, but the vendored copy is stale until item 4 runs.

---

# 2026-09-18 — owner rulings applied, Linux leg run, state promoted

State: **SOURCE_CANDIDATE.** Read the caveat before treating that as "all green": two tests are
red on Windows and both are accounted for — one is red BY RULING (the CLI contract, ruling 5) and
one is an upstream defect the merge imported rather than caused, proven green on Linux and proven
not-a-resolution by blob identity. Every red that this merge actually caused is closed.

Fork `main` was fast-forwarded to `229b1d43a4` by the parent while this work continued; the commits
below sit ahead of it on the branch and `main` is an ancestor of the branch tip. No divergence.

## Per-ruling outcome

### Ruling 1 — pack health: adopt upstream's contract

Done (`642bcba309`, corrected by `e71265fc2e`). The old assertion — "pack count must strictly
decrease" — was the contract of `repack -a -d`; upstream replaced it with an incremental
`repack -d --geometric=2 --write-midx` behind a once-per-clone-per-6h slot. The tests now pin
liveness first (the slot lock exists, so the pass reached the repack), then "never GROWS", then the
multi-pack-index where the flag exists, plus a second test for the slot no-op with a positive
control that the FIRST pass does repack.

**The measurement moved the answer, and found a real defect.** On git 2.31.1 (this workstation):

```
$ git repack -d --geometric=2 --write-midx --quiet
error: unknown option `geometric=2'
rc=129
```

`--geometric` / `--write-midx` landed in git 2.32. `_run_bounded_repack` sends both streams to
DEVNULL and never reads the return code, so on any host with git < 2.32 pack maintenance claims its
6-hour slot, runs a command that fails in milliseconds, reports nothing, and suppresses retries for
six hours. Filed as a queue row; not repaired here (upstream-owned, and the fix is a behaviour
decision, not a merge resolution).

Killing mutation (`_claim_repack_slot` → `return True`) applied, red recorded verbatim in
`642bcba309`, reverted, green. It also reddened the pre-existing
`TestRepackStampede::test_one_repack_per_clone_per_interval` — the right neighbour to have caught it.

**A correction worth keeping.** The first version of the capability probe grepped
`git repack -h` for `"--geometric"`. Git 2.53 prints it as `-g, --[no-]geometric`, so the probe
answered False on a git that runs the command perfectly — the multi-pack-index assertion would have
been skipped on Windows (genuinely unsupported) AND on Linux (supported, spelled differently), i.e.
never run anywhere while reading as covered. The probe now RUNS the command in a throwaway repo and
keys on its return code. Verified live: `False` on git 2.31.1, `True` on git 2.53.0.

### Ruling 2 — kanban worktree teardown: mark POSIX-only

Done (`3de9a499d3`). `test_cleanup_proceeds_when_cwd_was_deleted` is marked `linux_only`. Its
premise is POSIX, not an import: POSIX lets a process delete the directory it is standing in,
Windows answers `WinError 32`. Not fixed — queue row handed over verbatim, as instructed.

### Ruling 3 — gh auth probe: DIAGNOSE first

**Neither branch of the ruling applies, and the evidence is conclusive.**

It is not a mis-resolution, because there was no resolution: both files are byte-identical to
upstream.

| file | merged blob | upstream `cdceca42e1` blob |
| --- | --- | --- |
| `hermes_cli/web_routers/git.py` | `64ae36cf59e2d328b530175bc53ee155305de6b6` | identical |
| `tests/hermes_cli/test_web_server_git.py` | `5449733654a73a5c81bbeee7d50cca858fc7d8fb` | identical |

`git.py` was never in the 26 conflicted files, and the test is upstream's own — absent from fork
`main` at `94a5db103d`, present at `cdceca42e1`. It arrived with the merge together with the
implementation it covers. The merged code DOES carry the wait
(`if not refresh or started >= asked: break`); nothing was lost.

**Root cause: the guard compares two clock reads with `>=` on a clock that cannot resolve the
interval between them.** Measured on this workstation:

```
monotonic resolution: 0.015625     (15.625 ms)
identical back-to-back reads: 10000/10000
```

So the stale probe's `started` and the refresh's `asked` are the SAME float, `started >= asked` is
true by equality, the loop breaks, and the refresh adopts the stale (logged-out) answer — then
caches it for the full 5-minute TTL. Deterministic here: 3/3 runs.

On Linux the same test PASSES (below). But the race is real there too, not merely absent:

```
monotonic resolution: 1e-09
identical back-to-back reads: 1009/10000
```

~10% of back-to-back read pairs are still equal on Linux, so this is a genuine upstream bug that
Windows makes deterministic rather than a Windows-only artifact. Not patched here:
`hermes_cli/web_routers/git.py` is upstream-owned and the standing rule is never to edit upstream
logic to suit the fork. Queue row filed for the upstream report; the one-character fix upstream
would want is `>` rather than `>=`, or a monotonic counter instead of a timestamp.

### Ruling 4 — OS markers for the POSIX-only tests

Done (`3de9a499d3`), marker-only, 30 test defs across 6 files: `fcntl` (3), `pwd` (3),
`signal.SIGKILL` (1), XDG desktop entry (21 defs / 24 node ids), WSL `/mnt` mount walk (1), plus
ruling 2's cwd-deletion premise (1).

Scope note: only `linux_only` / `macos_only` / `windows_only` exist and conftest makes carrying two
a hard collection error, so a POSIX-generic test can only be spelled `linux_only` — which also drops
it from the macOS lane. The in-tree alternative `skipif(sys.platform == "win32")` keeps macOS but is
invisible to `scripts/ci/list_os_marked_tests.py`, which finds lane members by grepping marker
NAMES; the repo has 75 of those. A `posix_only` marker would spell this honestly and is a one-line
addition to `_OS_MARKS` plus pyproject — deliberately NOT taken, because the marker vocabulary is a
repo-wide contract rather than a merge decision.

21 of the 24 desktop-entry node ids were pre-existing failures on fork `main`, not merge-caused;
marked with the rest because the marker is correct for all of them and 21 permanently-red tests are
the noise that hides the next real one.

### Ruling 5 — CLI contract

Left red, as ruled. Additive only (`profile migrate-identity`, `profile purge-identity` from
upstream `a41552fad4`), zero removals. Parent regenerates and re-vendors the launcher copy in one
wave after landing.

### Ruling 6 — pre-existing and never-ran

Accepted for landing. Queue row handed over verbatim.

## Linux leg

A Linux-side clone of the branch tip in the WSL filesystem (`~/hermes-linux`, NOT `/mnt/x` — the
`/mnt` walk is itself one of the failure causes), `uv`-provisioned CPython 3.11.15 against
`uv.lock`, git 2.53.0, 16 cores.

```
bash scripts/run_tests.sh <27 files> -j 8 --file-timeout 180
=== Summary: 27 files, 490 tests passed, 1 failed, 5 skipped (100% complete) in 92.5s (8 workers) ===
rc=1
```

**The single Linux failure is `test_cli_contract_dump` — the one deliberately left red.**
Everything else passes, including every newly-marked test, which is what makes the markers a finding
rather than an excuse:

| file | Linux | note |
| --- | --- | --- |
| `test_linux_desktop_entry.py` | 49 passed | all 21 marked defs RAN (Windows: 22 passed / 24 skipped) |
| `test_orphan_desktop_serve_reap.py` | 13 passed | `fcntl` available |
| `test_gateway_migrate_multiplex.py` | 31 passed | `pwd` available |
| `test_update_serve_generation_recovery.py` | 60 passed | `signal.SIGKILL` available |
| `test_node_runtime_npm_resolution.py` | 2 passed | the `/mnt` walk is a native mount here |
| `test_kanban_worktree_teardown.py` | 14 passed | deleting a live CWD is legal on POSIX |
| `test_worktree_selfheal.py` | 9 passed | midx assertion LIVE here (probe returns True on git 2.53) |
| `test_web_server_git.py` | 8 passed | **ruling 3 confirmed** — the gh-auth race does not fire on a ns clock |
| `test_dashboard_system_gateway_elevation.py` | 6 passed | one of the three that never ran on Windows |
| `test_gateway.py` | 44 passed | never ran on Windows |
| `test_gateway_peer_two_roots_e2e.py` | 9 passed | never ran on Windows (exit 124 there) |
| `test_persona_head_auth_store.py` | 2 passed | the theme-7 positive control holds on Linux too |

All three files that never ran on Windows run and pass on Linux, so they were Windows collection /
timeout problems, not broken tests.

## Windows verification re-run

```
bash scripts/run_tests.sh <22 files> -j 8 --file-timeout 180
=== Summary: 22 files, 382 tests passed, 2 failed, 44 skipped (100% complete) in 149.0s (8 workers) ===
rc=1   (captured unpiped)
```

Both failures are the accounted-for pair: `test_cli_contract_dump` (ruling 5, deliberate) and
`test_gh_auth_refresh_waits_out_a_probe_started_before_it` (ruling 3, upstream defect, green on
Linux). Of the 20 originally merge-caused tests, **18 are closed**, 1 is deliberate, 1 is an
imported upstream defect.

## Acceptance state

| condition | status |
| --- | --- |
| pinned SHA `cdceca42e1` in ancestry | **YES** |
| fold guard `0d5b7b8abc` | **PASS** on the final tip |
| theme-7 positive control red-first | **YES** (`c941959441`), and green on Linux |
| every merge-CAUSED red closed | **YES** — the 2 remaining are ruled-deliberate and upstream-imported |

Owed after landing, none of it blocking: regenerate the CLI contract + re-vendor the launcher copy
in one wave; the four queue rows below.
