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
