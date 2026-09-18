# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY — safe source reconciliation is landing incrementally; upstream `01382698fc32ec7740b6a204d9b7a6abeac74d33` is not yet attached as a complete merge parent.**

This is the durable handoff for `automation/upstream-sync`. Cloud runs and local agents continue from this branch; only the operator lands a tested candidate to `main`.

## Current frozen state

- Fork: `ArcadiaLabsLLC/hermes-agent`
- Fork `main` (`F`): `297d218297cbd3eb1d26069160ade08c12dd4f48`
- Sync tip at start of this cycle (`S`): `297d218297cbd3eb1d26069160ade08c12dd4f48`
- Official upstream: `NousResearch/hermes-agent`
- Upstream `main` (`U`): `01382698fc32ec7740b6a204d9b7a6abeac74d33`
- Upstream commit already represented by the current fork merge: `c62bd9f2078a946108f1c9d9b24bf118963277ef`
- Source-reconciliation tip before this handoff update: `023153cd2b3be4bbce2e961aad9f718f898a8eb4`

The prior handoff metadata is superseded by real repository history: fork `main` and the sync branch were advanced by operator/local work to `297d218...`, a genuine merge commit whose second parent is upstream `c62bd9f...`. The earlier `uv.lock` blocker therefore is not the current integration frontier. The new upstream delta from `c62bd9f...` to `0138269...` does not change `pyproject.toml` or `uv.lock`, so no new lock regeneration is presently required for this 17-commit delta. This statement is source-delta evidence only; no lock/test command was executed here.

## Source reconciliation completed this cycle

### 1. Desktop portal-session/auth window — resolved

Commit: `f90f249e4c4140d2c11afe218634a86a2985c08e`

Changed paths:
- `apps/desktop/electron/portal-cookies.ts`
- `apps/desktop/electron/portal-cookies.test.ts`
- `apps/desktop/electron/portal-session.ts`
- `apps/desktop/electron/portal-session-live-fixture/main.ts`

Resolution method: all four fork blobs were byte-identical to the already-integrated upstream baseline `c62bd9f...`, while current upstream changed them together. The branch therefore adopts the current-upstream blobs verbatim, preserving upstream's coherent portal-window fix stack without overwriting any downstream edits on those paths.

Behavior carried forward includes the portal-session window driver changes around new-access-cookie settlement, forced renewal, cookie type sharing, and the live Electron fixture that exercises the associated race/renewal behavior. Tests are present but were NOT RUN in this GitHub-only environment.

### 2. OpenCode provider-removal wording — resolved

Commit: `023153cd2b3be4bbce2e961aad9f718f898a8eb4`

Changed paths:
- `agent/opencode_affinity.py`
- `agent/reasoning_effort.py`

Resolution method: both fork blobs were byte-identical to upstream baseline `c62bd9f...`; current upstream only removes stale `opencode-free` wording after the provider's removal. Current-upstream blobs were adopted verbatim. No runtime behavior was changed by these two files in this commit.

## Conflict work queue

- `ALREADY_RESOLVED` — operator/local integration through upstream `c62bd9f2078a946108f1c9d9b24bf118963277ef` is present in fork history via merge commit `297d218297cbd3eb1d26069160ade08c12dd4f48`.
- `ALREADY_RESOLVED` — desktop portal-session/auth-window four-file stack, source commit `f90f249e4c4140d2c11afe218634a86a2985c08e`.
- `ALREADY_RESOLVED` — `agent/opencode_affinity.py` and `agent/reasoning_effort.py` provider-removal wording, source commit `023153cd2b3be4bbce2e961aad9f718f898a8eb4`.

### Next cloud-side review queue

These are the next material overlaps to classify by full three-way source review; do not select ours/theirs wholesale:

1. `gateway/run_busy.py` plus `/stop` tests/docs. Current fork is not byte-identical to upstream baseline, while upstream `0fb56906...` changes same-chat/thread stop semantics, WhatsApp canonicalization, and the shared scan. Preserve downstream gateway/profile/session behavior while bringing in the upstream bug fix.
2. OpenCode-free provider removal across `hermes_cli/*`, `agent/auxiliary_client.py`, `agent/models_dev.py`, plugin deletion, compatibility manifests, tests, and docs. This intersects downstream provider/model-picker policy; verify each owner before removing fork behavior.
3. Remaining desktop Cloud-gateway/auth lifecycle changes (`use-gateway-boot`, gateway store, team-change handling) after the portal-session stack. Prefer upstream where current fork still equals the `c62bd9f...` baseline; three-way reconcile only where downstream changed the same path.

A future cloud run should start with these overlaps and commit every source result that becomes deterministically safe. Do not wait for local testing merely because testing would be desirable; only defer when the correct source content itself depends on execution or operator intent.

## Verification status

Executed source/Git checks only:
- verified `F == S == 297d218297cbd3eb1d26069160ade08c12dd4f48` at freeze time;
- verified `297d218...` is a two-parent merge carrying upstream `c62bd9f...`;
- compared upstream `c62bd9f...` to `0138269...` (17 commits);
- verified baseline/current/latest blob identity for each of the six reconciled paths before adopting upstream blobs;
- compared fork `297d218...` to source tip `023153c...`: exactly six source paths changed across two commits.

NOT RUN:
- JavaScript/Vitest/Electron tests;
- `scripts/run_tests.sh`;
- CLI/payload contract generators;
- runtime/network/GPU/service probes.

A local agent should use an isolated worktree from a neutral cwd, preserve this branch history, and use the repository-documented test commands for each changed area. Python tests must go through `scripts/run_tests.sh`, never bare pytest. For the desktop portal stack, run the applicable repository JS/Vitest/Electron test scripts after reading `apps/desktop/AGENTS.md` and package scripts. Record exact commands/results and tested SHA here when done.

## Acceptance boundary

This remains `HANDOFF_ONLY`: `01382698fc32ec7740b6a204d9b7a6abeac74d33` is not yet in branch ancestry. The six source paths above are preparatory reconciliations against that pinned target, not a claim that the whole upstream delta is merged. Do not merge to `main` yet. Once all remaining overlaps are reconciled, create the genuine history-preserving upstream merge, then locally verify the exact immutable candidate SHA before operator acceptance.
