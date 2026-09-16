# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY — local completion required; no new upstream merge is represented by this branch yet.**

This file is the durable handoff for the persistent branch `automation/upstream-sync`.
The cloud task updates it whenever it can make safe progress or discovers a new blocker.
A local coding agent may continue from this branch, complete work requiring a real checkout
or toolchain, commit the result to the same branch, and leave `main` untouched for operator
testing and acceptance.

## Frozen state for this handoff

- Fork: `ArcadiaLabsLLC/hermes-agent`
- Fork main: `0a86b7e1374a3b7860cd37b8d89776ddc9255ea1`
- Official upstream: `NousResearch/hermes-agent`
- Current upstream observed: `9796235822b89e08597a402dad045b5b4464e474`
- Last upstream commit already represented in accepted fork history: `416a8177c25d87aa9929dfcf31f7964137d7fcdd`
- Earlier cloud audit target: `784d5c3f9c2cb77698d8a9d2e72b1d106a38ea88`
- Upstream advanced 22 commits from that earlier audit target to the current observed tip.

The cloud audit deliberately did **not** attach either newer upstream target as a merge parent,
because the resulting source tree could not be proven complete without regenerating a
conflicting generated dependency lockfile.

## Cloud capability test completed

The cloud-side GitHub path has now successfully demonstrated all of the following without
modifying `main`:

- pinned branch/file/history reads;
- Git tree-object creation;
- Git commit-object creation without publishing it;
- creation of the persistent `automation/upstream-sync` branch at a handoff-only commit;
- reading the handoff back from the published branch;
- updating this handoff file on that branch.

This proves the cloud task can maintain durable branch state and can assemble Git objects.
It does **not** prove that it has a shell, can execute repository generators/tests, or can
safely publish an upstream merge whose generated artifacts are unresolved.

## What the cloud audit completed

- Read the fork-wide downstream instructions and recent upstream-sync decisions.
- Verified that fork `main` stayed untouched.
- Audited the upstream delta in bounded pieces rather than trusting a single potentially
  truncated GitHub compare response.
- Confirmed both fork and upstream independently changed dependency-resolution inputs/state.
- Re-checked current upstream after the blocked audit and observed 22 additional commits.
- Preserved all source integration as pending rather than falsely recording newer upstream
  ancestry before the merged tree is complete.

## Primary blocker: `uv.lock`

`uv.lock` changed independently on fork and upstream. The fork also changed
`pyproject.toml`: its `dev` extra adds `coverage==7.16.0` and
`pytest-timeout==2.4.0`, and `[tool.uv.exclude-newer-package]` adds exemptions for
those packages. Current upstream does not contain those fork-only dev dependency changes.
Upstream independently regenerated its lock for newer dependency-resolution state.

Therefore neither side's `uv.lock` can be selected wholesale with confidence. The correct
lock must be regenerated from the final merged `pyproject.toml` in a real checkout using the
repository's canonical uv workflow. Do not fabricate lock content or publish an upstream
merge while leaving the lock knowingly inconsistent.

## Local-agent continuation

Work only on `automation/upstream-sync`; do not modify or force-push `main`.

1. Read `AGENTS.md`, `docs/downstream-development.md`, applicable nested `AGENTS.md` files,
   and the latest upstream-sync notes before editing.
2. From a neutral cwd, create an isolated worktree for this branch according to the repo's
   current worktree safety rules. Do not switch/reset a running primary checkout.
3. Fetch the official upstream and re-check its `main`. If it has advanced beyond
   `9796235822b89e08597a402dad045b5b4464e474`, either intentionally include the newer pinned
   tip and record it here, or keep this target pinned and clearly defer newer commits.
4. Merge the pinned upstream commit into this branch with real merge ancestry. Resolve
   conflicts by behavior: prefer current upstream implementation for upstream-owned behavior;
   preserve unique Arcadia/Eternia contracts through existing fork-owned seams; remove truly
   redundant fork code; keep shared-file hooks narrow.
5. Pay special attention to Local llama ownership, call-time profile/home resolution,
   Windows/profile startup, runtime/storage contracts, path/read/write protections, and
   downstream wire-schema adaptations documented by the fork.
6. After the final merged `pyproject.toml` is known, regenerate `uv.lock` with the canonical
   repository uv workflow. Verify the lock corresponds to that exact source tree.
7. Run focused checks first, using `scripts/run_tests.sh` and the downstream hermetic-runner
   rules. Run generator/contract checks required by files actually changed. Record exact
   commands, results, and the tested commit SHA here.
8. If CLI/RPC/payload contracts changed, record likely Launcher follow-up here, but do not
   modify Launcher from this branch.
9. Commit completed reconciliation and update this handoff in the same branch. Change this
   file's State to `SOURCE_CANDIDATE` only when the claimed upstream target is actually present
   in Git ancestry and the source tree has no known unresolved integration defect.
10. Do not merge to `main`; the operator will pull/test the exact candidate SHA and decide
   acceptance.

## Conflict hierarchy to preserve

1. Understand upstream and downstream behavior before choosing lines.
2. Prefer the new upstream implementation for upstream-owned behavior.
3. Preserve downstream intent, not obsolete downstream code.
4. Keep unique fork behavior in existing fork-owned modules/adapters/seams where practical.
5. Minimize modifications to upstream-owned files and delete redundant downstream machinery.
6. Preserve security, authorization, profile/root, lifecycle, persistence and recovery
   contracts unless semantic equivalence is demonstrated.
7. Use each real overlap as an opportunity to make the next upstream merge smaller, without
   starting unrelated refactors.

## Cloud-task continuation rules

Future scheduled runs must inspect this file and actual Git ancestry before acting. They should
make every safe GitHub-only improvement they can. If a real-checkout operation is still needed,
they should **update this handoff on the persistent branch instead of returning only an ephemeral
chat report**.

A handoff-only commit is allowed when source integration cannot safely be published. It may
record analysis, exact blocker details, safe preparatory work, and local-agent instructions.
It must keep `State: HANDOFF_ONLY`, must not attach an upstream merge parent whose tree is known
incomplete, and must not claim the newer upstream SHA is integrated.

Do not create a daily handoff commit when nothing material changed. Update it when fork `main`,
upstream `main`, blocker details, safe completed work, or required local steps materially change.

If a local agent later commits the completed merge, future cloud runs must treat those human
commits as authoritative branch history, inspect what was completed, refresh fork `main` first
when necessary, then continue with newer upstream commits. Never reset or discard local-agent
work merely because the scheduled task did not create it.

## Acceptance boundary

The branch is a staging/integration line only. Any commit mentioned here is **not accepted into
`main`** until the operator tests that exact immutable SHA locally and explicitly lands it.
