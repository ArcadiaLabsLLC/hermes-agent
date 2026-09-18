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

## Acceptance state after this section

State stays **ANALYSIS_ONLY / HANDOFF_ONLY**. `automation/upstream-sync-next` carries this ledger and nothing else; it contains no upstream merge parent, and `main` is untouched. The branch passes the fold guard. Promote to `SOURCE_CANDIDATE` only when `cdceca42e1` (or a deliberately re-pinned later tip) is actually in ancestry and the auth policy decision in theme 7 has been ruled on.
