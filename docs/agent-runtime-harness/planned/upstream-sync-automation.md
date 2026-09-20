# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY — safe upstream preparation continues incrementally; current upstream `52d203d041f9e4baad4a78013abeccd8f13a86e3` is NOT yet attached as a complete merge parent.**

This is the durable handoff for `automation/upstream-sync`. Cloud runs and local agents continue from this branch. Only the operator lands an exact, locally verified candidate to `main`.

## Frozen inputs for the 2026-09-20 cycle

- Fork: `ArcadiaLabsLLC/hermes-agent`
- Fork `main` (`F`): `f1268bd017d54e3102fe7f98c7e87b001adec747`
- Sync tip at cycle start (`S`): `e69fd2b7a8df2bcfecddd1e91e5372ca26faafdf`
- Official upstream: `NousResearch/hermes-agent`
- Upstream `main` (`U`): `52d203d041f9e4baad4a78013abeccd8f13a86e3`
- Previous reviewed upstream target: `17b5df02f2a729d8f46fbbf78cfc1f5a8cf0f121`
- Upstream baseline already represented by the accepted fork lineage before the incremental preparation stack: `c62bd9f2078a946108f1c9d9b24bf118963277ef`

At cycle start `S` already contained current fork `main`; no fork refresh merge was needed. Upstream advanced substantially beyond the previous target, so review continues in bounded slices rather than treating one GitHub compare file list as exhaustive.

## Source reconciliation completed THIS cycle

These commits were created by the 2026-09-20 cloud cycle after freezing `S` above.

### 1. OpenAI named-model reasoning timeout floors — resolved

Commit: `aa197f8a3b9db8183f6682d5141e852bc19ef66e`

Changed path:
- `agent/reasoning_timeouts.py`

Evidence:
- sync-start / fork blob: `ae0a405ca4f71bbc166e1afbb6bf5d1774444d0f`
- previous upstream target blob: the same `ae0a405ca4f71bbc166e1afbb6bf5d1774444d0f`
- current upstream blob: `4b03c9b2c89ec563dc70ee8bc7098dcad66d8603`

The current-upstream file was therefore adopted verbatim: there were no downstream edits on this path to overwrite. The change adds the `gpt-5.6` and `gpt-6` named reasoning families to the existing 600-second stale-timeout floor while retaining the existing anchored slug matching. Current upstream also carries focused tests for these model families; those later test-file changes are coupled to additional stream-timeout work and were not copied wholesale in this commit.

Tests were **NOT RUN** in this GitHub-only environment.

### 2. Quota reset parsing / display helper — resolved

Commit: `cfafa8d7efe9c34c558997823cdda9539ff66056`

Changed path:
- `agent/retry_utils.py`

Evidence:
- sync-start / fork blob: `ab28ee37a948a85946c1150b58c5bd03575989ee`
- previous upstream target blob: the same `ab28ee37a948a85946c1150b58c5bd03575989ee`
- current upstream blob: `0cec62957d479bc09013bc659b4c30028e894bfe`

The current-upstream file was adopted verbatim. It extends the shared reset grammar with the stringified `resets_in_seconds` body field and adds `format_reset_window`; both are additive and introduce no new module dependency. Later upstream gateway call sites can consume the helper when their coupled source is reconciled.

Tests were **NOT RUN**.

## Safe reconciliation retained from prior cycles

### Cloud-created on 2026-09-19

- `a891c42d4978cf3fb4c7dee6a7972679e061027e` — `apps/desktop/electron/backend-env.ts` + test.
- `d682b0209332df6f4ff88e03b1ef800fbfca4966` — `apps/desktop/electron/desktop-profile.ts` + test.
- `fe3a943e3c7572f547cac085b9bcfa2007d9384c` — `apps/desktop/electron/session-windows.ts` + test.
- fork-main refresh was preserved by merge commit `ebd572b7cdcddf5b1128c383cf5290ff02bab344`.

### Pre-existing operator/local work — do NOT attribute to automation

- `f90f249e4c4140d2c11afe218634a86a2985c08e` — portal cookies/session/live fixture.
- `023153cd2b3be4bbce2e961aad9f718f898a8eb4` — `agent/opencode_affinity.py` and `agent/reasoning_effort.py` wording alignment.
- `0b8af0622952f73f05064eba1598e9596d37c49c` — prior cumulative handoff update.

## Conflict work queue

### ALREADY_RESOLVED

- Fork-main refresh through `f1268bd...` — preserved in sync ancestry by `ebd572b...`.
- Desktop backend environment/home normalization — `a891c42...`.
- Desktop profile routing/preferences — `d682b020...`.
- Desktop peer/session-window routing — `fe3a943...`.
- OpenAI named reasoning timeout floors — `aa197f8...` (this cycle).
- Quota reset parsing / reset-window helper — `cfafa8d...` (this cycle).
- Dependency input/lock status for the currently reviewed frontier: current upstream `U` still has `pyproject.toml` blob `34c382a6e47fadeb37814a85ad9f527e6bf3320a` and `uv.lock` blob `6d381729736fb8b318236863844a51781be19e23`, the same upstream pair previously reviewed. The fork intentionally retains its coherent downstream pair (`pyproject.toml` `d98df81c6315e164401edaf0710860d05fc8a64e`, `uv.lock` `c9e2c9a657ca6a69b4a77d49b85b6233a3bb6745`). No NEW lock regeneration blocker was introduced by the upstream movement reviewed this cycle.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- `gateway/run_busy.py` `/stop` semantics, centered on upstream `0fb56906fc70a5987aec4e3c773d5229369cd60e`. The upstream patch fixes a real same-thread partial-stop bug, shares one running-agent scan, and canonicalizes WhatsApp DM identity. The fork's `run_busy.py` is not baseline-identical and carries downstream session/profile/key-shape behavior. The upstream source decision is understood, but the exact combined behavior across downstream key shapes is not yet safe to publish from a wholesale blob choice. A local continuation should apply the focused upstream behavior to the fork version and run the two upstream `/stop` test files plus affected downstream gateway tests through `scripts/run_tests.sh` before treating the combined source as resolved.

### Coupled source — do not cherry-pick one file in isolation

These were inspected and are not currently classified as standalone `SAFE_CLOUD_RESOLUTION` items because their current-upstream edits rely on sibling changes that have not yet been reconciled:

- `agent/auxiliary_wire.py`: upstream now forwards the resolved SDK client's `base_url` into `ChatCompletionsTransport.convert_messages`; the behavior belongs with the corresponding current transport-side sanitization changes.
- `agent/rate_limit_credits.py`: upstream depleted-credit notice handling now calls `rewarm_pricing_before_depleted_notice`, which is owned by the changed `agent/credits_tracker.py` stack.
- `agent/billing_usage.py`: upstream redirects portal account fetching through `agent.account_usage._fetch_portal_account`; adopt only with that account-usage owner stack.

Future cloud runs should review these owner stacks together. Once a complete coupled set is source-deterministic, classify it `SAFE_CLOUD_RESOLUTION` and commit it in the same run.

## Unreviewed frontier

These are not yet classified because the complete owning slice has not been inspected. They are the next bounded work, not excuses to stop:

1. current upstream changes after `17b5df...` across the agent timeout/retry/account-usage owners;
2. remaining Desktop main-process/gateway boot/team-change lifecycle and call sites consuming the already reconciled desktop helpers;
3. broad provider/model-policy and OpenCode-removal changes under `agent/` and `hermes_cli/`;
4. the remaining current upstream delta through `52d203d...`.

A future cloud run must continue finding and committing deterministic source slices; do not stop merely because the complete upstream merge is still large.

## Generated artifacts

No new generator blocker was found in the two paths reconciled this cycle. The old `pyproject.toml` / `uv.lock` concern was revalidated against current upstream and remains unchanged as described in the queue above.

Revalidate both dependency blobs again if a later upstream tip changes either one.

## Verification status

EXECUTED (Git/source checks only):

- froze `F`, `S`, and current `U` above;
- verified sync-start `S` already contains current fork `main`;
- read root, downstream, Gateway, and Agent instructions relevant to the inspected owners;
- proved `agent/reasoning_timeouts.py` and `agent/retry_utils.py` were each byte-identical between the sync start and the previous upstream target before adopting the current-upstream blob;
- inspected upstream `0fb56906...` and the fork/current-upstream `/stop` helper shapes;
- inspected coupling for `agent/auxiliary_wire.py`, `agent/rate_limit_credits.py`, and `agent/billing_usage.py` rather than cherry-picking their callers blindly;
- revalidated current upstream and fork dependency-input/lock blob identities;
- published the two focused source reconciliation commits above with non-forced branch advancement after re-reading the live sync ref.

NOT RUN:

- Python tests (`scripts/run_tests.sh`);
- JavaScript/Vitest/Electron tests;
- CLI/payload generators;
- runtime/network/GPU/service probes.

Source-complete-but-untested preparation is allowed in `HANDOFF_ONLY`; none of the above test status is claimed green.

## Local-agent continuation

Continue on `automation/upstream-sync`; do not reset/rebase/force-push or modify `main`.

Highest-value local lane now:

1. reconcile upstream `0fb56906...` `/stop` behavior into the current fork `gateway/run_busy.py` without discarding downstream key/profile behavior;
2. bring over its focused tests/docs as appropriate;
3. run the affected Gateway tests via `scripts/run_tests.sh` and record exact commands/results/SHA here;
4. then continue with the coupled account-usage / credits / transport owner slices above.

If a local agent commits completion to this same branch, the next cloud run must preserve and build on it.

## Acceptance boundary

This remains `HANDOFF_ONLY`. Current upstream `52d203d041f9e4baad4a78013abeccd8f13a86e3` is **NOT** in branch ancestry. The source commits above are safe preparatory reconciliation against that pinned target, not a claim that current upstream is fully merged.

Do not merge to `main`. When all required source overlaps and generated artifacts are complete, construct the genuine history-preserving upstream merge, test the exact immutable candidate SHA locally, and let the operator decide acceptance.
