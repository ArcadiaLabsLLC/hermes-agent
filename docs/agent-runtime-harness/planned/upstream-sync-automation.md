# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY — fork main is refreshed and safe upstream preparation is landing incrementally; current upstream `17b5df02f2a729d8f46fbbf78cfc1f5a8cf0f121` is NOT yet attached as a complete merge parent.**

This is the durable handoff for `automation/upstream-sync`. Cloud runs and local agents continue from this branch. Only the operator lands an exact, locally verified candidate to `main`.

## Frozen inputs for the 2026-09-19 cycle

- Fork: `ArcadiaLabsLLC/hermes-agent`
- Fork `main` (`F`): `f1268bd017d54e3102fe7f98c7e87b001adec747`
- Sync tip at cycle start (`S`): `0b8af0622952f73f05064eba1598e9596d37c49c`
- Official upstream: `NousResearch/hermes-agent`
- Upstream `main` (`U`): `17b5df02f2a729d8f46fbbf78cfc1f5a8cf0f121`
- Last upstream commit already represented by the accepted fork lineage before this cycle: `c62bd9f2078a946108f1c9d9b24bf118963277ef`

The old handoff target `01382698fc32ec7740b6a204d9b7a6abeac74d33` is superseded. Current upstream is much farther ahead of `c62bd9f...`; the broad compare reports 1152 commits. That delta is too large to treat one compare response as complete file coverage, so future runs must continue bounded/tree-complete enumeration instead of assuming the first file list is exhaustive.

## Fork-main refresh completed this cycle

Fork `main` advanced independently after the previous sync tip with the generic-desk/office change `f1268bd...`. The sync line also had three branch-only commits after their merge base `297d218...` (two prior manual/local source reconciliations plus the prior handoff). Their changed paths are disjoint from the new fork-main commit.

Prepared merge commit:
- `ebd572b7cdcddf5b1128c383cf5290ff02bab344`
- first parent: prior sync `0b8af0622952f73f05064eba1598e9596d37c49c`
- second parent: fork main `f1268bd017d54e3102fe7f98c7e87b001adec747`

This preserves the persistent sync lineage and the new fork-main office work without replay/reset/rebase.

## Source reconciliation completed THIS cycle

These commits were created during the 2026-09-19 cloud cycle. They are distinct from the prior operator/local commits `f90f249...`, `023153cd...`, and `0b8af062...`.

### 1. Desktop backend environment/home normalization — resolved

Commit: `a891c42d4978cf3fb4c7dee6a7972679e061027e`

Changed paths:
- `apps/desktop/electron/backend-env.ts`
- `apps/desktop/electron/backend-env.test.ts`

Evidence: both fork files at frozen `F` were byte-identical to upstream baseline `c62bd9f...`; current upstream changed both. The current-upstream blobs were adopted verbatim. This carries the upstream `normalizeHermesHomeRoot` policy (literal `~` expansion and profile-home → global Hermes-root normalization) together with its focused tests, without overwriting downstream edits because none existed on these paths after the baseline.

Tests were NOT RUN in this GitHub-only environment.

### 2. Desktop profile routing/preferences — resolved

Commit: `d682b0209332df6f4ff88e03b1ef800fbfca4966`

Changed paths:
- `apps/desktop/electron/desktop-profile.ts`
- `apps/desktop/electron/desktop-profile.test.ts`

Evidence: both frozen-fork blobs were byte-identical to baseline `c62bd9f...`; current upstream changed both. Current-upstream blobs were adopted verbatim. Required sibling modules (`profile-delete-routing.ts`, `profile-rename-routing.ts`, `window-connection-route.ts`) already exist in the frozen fork, so this does not introduce unresolved imports.

Tests were NOT RUN.

### 3. Desktop peer/session-window routing — resolved

Commit: `fe3a943e3c7572f547cac085b9bcfa2007d9384c`

Changed paths:
- `apps/desktop/electron/session-windows.ts`
- `apps/desktop/electron/session-windows.test.ts`

Evidence: both frozen-fork blobs were byte-identical to baseline `c62bd9f...`; current upstream changed both. Current-upstream blobs were adopted verbatim. The updated source consumes `DesktopWindowLaunch`, which is supplied by the immediately preceding desktop-profile reconciliation.

Tests were NOT RUN.

## Prior safe reconciliation retained (pre-existing before this cycle)

These were operator/local work and MUST NOT be attributed to the 2026-09-19 automation cycle:

- `f90f249e4c4140d2c11afe218634a86a2985c08e`: portal cookies/session/live fixture (`apps/desktop/electron/portal-cookies.ts`, `portal-cookies.test.ts`, `portal-session.ts`, `portal-session-live-fixture/main.ts`).
- `023153cd2b3be4bbce2e961aad9f718f898a8eb4`: `agent/opencode_affinity.py` and `agent/reasoning_effort.py` wording alignment.
- `0b8af0622952f73f05064eba1598e9596d37c49c`: prior cumulative handoff update.

## Conflict work queue

- `ALREADY_RESOLVED` — fork-main refresh through `f1268bd...`, represented by merge commit `ebd572b...` in the prospective sync lineage.
- `ALREADY_RESOLVED` — desktop backend environment/home normalization pair, commit `a891c42...`.
- `ALREADY_RESOLVED` — desktop profile routing/preferences pair, commit `d682b020...`.
- `ALREADY_RESOLVED` — desktop peer/session-window routing pair, commit `fe3a943e...`.
- `ALREADY_RESOLVED` — downstream `pyproject.toml` + `uv.lock` state for this frontier: current upstream `U` has the same `pyproject.toml` blob and `uv.lock` blob as baseline `c62bd9f...`; the fork's divergent pair carries its fork-only dev/test dependencies. No NEW upstream lock conflict was introduced by `c62bd9f... -> U`, so no lock regeneration is required merely for the upstream movement reviewed here.

### Next source-review frontier (not yet classified; bounded work remains)

These are real overlaps that still require full three-way source review before assigning one of the queue classifications above:

1. `gateway/run_busy.py` plus its `/stop` tests/docs. Upstream commit `0fb56906fc70a5987aec4e3c773d5229369cd60e` fixes same-thread partial stop, consolidates the chat scan, and canonicalizes WhatsApp DM identity. The frozen fork changed `gateway/run_busy.py` after baseline, so wholesale upstream adoption is NOT safe. Preserve downstream gateway/profile/session behavior while reconciling the upstream fix.
2. Remaining desktop main-process/call-site changes that consume the newly reconciled helpers (`apps/desktop/electron/main.ts`, gateway boot/team-change lifecycle, window routing). Several frozen-fork files still equal the baseline and may become `SAFE_CLOUD_RESOLUTION` after their coupled dependencies are checked; do not select them wholesale until the dependency set is complete.
3. Broad OpenCode/provider removal and provider/model-policy changes under `agent/` and `hermes_cli/`. This intersects downstream provider/model-picker policy and requires owner-by-owner review.
4. The rest of the `c62bd9f... -> 17b5df0...` upstream delta. The compare spans 1152 commits; continue in bounded slices because a single GitHub compare can omit changed files.

A future cloud run must resume here and keep committing deterministic `SAFE_CLOUD_RESOLUTION` items rather than stopping because the full merge is large.

## Generated artifacts

No new generator blocker was discovered in the paths reconciled this cycle.

Revalidation of the old dependency concern:
- baseline `c62bd9f...` `pyproject.toml` blob: `34c382a6e47fadeb37814a85ad9f527e6bf3320a`
- current upstream `U` `pyproject.toml`: same blob
- baseline `uv.lock`: `6d381729736fb8b318236863844a51781be19e23`
- current upstream `U` `uv.lock`: same blob
- fork `F` intentionally has its downstream dependency pair (`pyproject.toml` `d98df81...`, `uv.lock` `c9e2c9a...`).

Therefore the previous lockfile issue is not an upstream-frontier blocker today. Revalidate again if later upstream commits alter either input.

## Workflow/publication safety checked

The fork's main CI orchestrator has `push.branches: [main]`; the deploy-site workflow also restricts push deployment to `main` and its privileged Vercel job runs only for release/manual dispatch. This candidate-branch publication does not enable or manually dispatch deployment/release automation. Other ordinary checks, if any, are not evidence of test success.

## Verification status

EXECUTED (Git/source checks only):
- froze F/S/U above;
- proved S and F diverged from merge base `297d218...` and that F's one new commit touches a disjoint path set from S's seven branch-only paths;
- assembled a genuine two-parent fork-refresh merge object preserving S first-parent history;
- for each of the six source files reconciled this cycle, verified frozen fork == baseline blob and current upstream != baseline before adopting current-upstream content;
- checked relevant root, downstream, Desktop, and Gateway instructions;
- revalidated current upstream dependency-input/lock blobs against the baseline;
- inspected candidate-branch CI/deploy trigger posture.

NOT RUN:
- JavaScript/Vitest/Electron tests;
- `scripts/run_tests.sh`;
- CLI/payload generators;
- runtime/network/GPU/service probes.

Local testing is still required for any eventual `SOURCE_CANDIDATE`. Use repository-documented commands; Python tests must go through `scripts/run_tests.sh`, never bare pytest.

## Acceptance boundary

This remains `HANDOFF_ONLY`. Current upstream `17b5df02f2a729d8f46fbbf78cfc1f5a8cf0f121` is NOT in branch ancestry. The commits above are safe preparatory reconciliation against that pinned target, not a claim that all 1152 upstream commits are merged.

Do not merge to `main`. Once all required upstream overlaps/artifacts are reconciled, construct the genuine history-preserving upstream merge, locally test the exact immutable candidate SHA, then let the operator decide acceptance.
