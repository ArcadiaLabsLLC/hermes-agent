# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY**. The reviewed upstream target for this cycle is `52d203d041f9e4baad4a78013abeccd8f13a86e3`; it is **not** yet attached as a complete merge parent. A newer upstream tip, `639823919ced15640924e905bacab3858c5afd19`, was observed after the cycle was frozen and is deliberately deferred to the next run rather than chased mid-cycle.

Persistent branch: `automation/upstream-sync`. Only the operator lands an exact, locally verified candidate to `main`.

## Frozen inputs — 2026-09-20

- Fork `main` (`F`): `f1268bd017d54e3102fe7f98c7e87b001adec747`
- Sync tip at cycle start (`S`): `e69fd2b7a8df2bcfecddd1e91e5372ca26faafdf`
- Reviewed upstream (`U`): `52d203d041f9e4baad4a78013abeccd8f13a86e3`
- Previous reviewed upstream: `17b5df02f2a729d8f46fbbf78cfc1f5a8cf0f121`
- Later upstream observed and deferred: `639823919ced15640924e905bacab3858c5afd19`

`S` already contained current fork `main`; no fork-refresh merge was needed this cycle.

## Source reconciliation completed this cycle

### `aa197f8a3b9db8183f6682d5141e852bc19ef66e`

`sync: reconcile reasoning timeout floors with upstream 52d203d`

Changed:
- `agent/reasoning_timeouts.py`

Evidence: fork/sync-start and previous-upstream blobs were both `ae0a405ca4f71bbc166e1afbb6bf5d1774444d0f`; current reviewed upstream is `4b03c9b2c89ec563dc70ee8bc7098dcad66d8603`. Current upstream was adopted verbatim because there were no downstream edits on this path. This adds the anchored `gpt-5.6` and `gpt-6` named reasoning families to the 600-second stale-timeout floor.

Tests: **NOT RUN**.

### `cfafa8d7efe9c34c558997823cdda9539ff66056`

`sync: reconcile retry reset parsing with upstream 52d203d`

Changed:
- `agent/retry_utils.py`

Evidence: fork/sync-start and previous-upstream blobs were both `ab28ee37a948a85946c1150b58c5bd03575989ee`; current reviewed upstream is `0cec62957d479bc09013bc659b4c30028e894bfe`. Current upstream was adopted verbatim. It adds parsing of stringified `resets_in_seconds` quota fields plus `format_reset_window` without introducing a new module dependency.

Tests: **NOT RUN**.

## Earlier safe reconciliation retained

Cloud-created 2026-09-19:
- `a891c42d4978cf3fb4c7dee6a7972679e061027e` — desktop backend environment/home normalization pair.
- `d682b0209332df6f4ff88e03b1ef800fbfca4966` — desktop profile routing/preferences pair.
- `fe3a943e3c7572f547cac085b9bcfa2007d9384c` — desktop peer/session-window routing pair.
- `ebd572b7cdcddf5b1128c383cf5290ff02bab344` — history-preserving fork-main refresh.

Pre-existing operator/local work — **do not attribute to automation**:
- `f90f249e4c4140d2c11afe218634a86a2985c08e` — portal cookies/session/live fixture.
- `023153cd2b3be4bbce2e961aad9f718f898a8eb4` — OpenCode/reasoning wording alignment.
- `0b8af0622952f73f05064eba1598e9596d37c49c` — earlier handoff update.

## Conflict work queue

### ALREADY_RESOLVED

- Fork-main refresh through `f1268bd...`.
- Prior desktop reconciliation stack above.
- `agent/reasoning_timeouts.py` through reviewed upstream `52d203d...` — `aa197f8...`.
- `agent/retry_utils.py` through reviewed upstream `52d203d...` — `cfafa8d...`.
- Dependency-input status for this reviewed frontier: upstream `pyproject.toml` remains blob `34c382a6e47fadeb37814a85ad9f527e6bf3320a` and upstream `uv.lock` remains `6d381729736fb8b318236863844a51781be19e23`; the fork intentionally retains its coherent downstream pair (`d98df81c6315e164401edaf0710860d05fc8a64e` / `c9e2c9a657ca6a69b4a77d49b85b6233a3bb6745`). No new lock regeneration blocker was introduced by the reviewed upstream movement.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- `gateway/run_busy.py` `/stop` behavior centered on upstream `0fb56906fc70a5987aec4e3c773d5229369cd60e`. The upstream fix is understood: one shared same-chat scan, act on the chat-tier superset rather than prematurely stopping after thread siblings, preserve the thread-sibling reason when appropriate, and canonicalize WhatsApp DM identity. The fork file has downstream session/profile/key-shape changes, so wholesale upstream-file adoption is unsafe. Local continuation should integrate the focused behavior into the fork version and run the two upstream `/stop` test files plus affected downstream Gateway tests through `scripts/run_tests.sh` before calling the combined behavior resolved.

### COUPLED SOURCE — REVIEW AS OWNER STACKS

Do not cherry-pick these callers alone:
- `agent/auxiliary_wire.py` now forwards client `base_url` into ChatCompletions message conversion; reconcile with the current transport sanitization owner changes.
- `agent/rate_limit_credits.py` now calls `rewarm_pricing_before_depleted_notice`; reconcile with the changed `agent/credits_tracker.py` owner stack.
- `agent/billing_usage.py` now delegates portal fetching to `agent.account_usage._fetch_portal_account`; reconcile with that account-usage stack.

Once a complete coupled set is source-deterministic, classify it `SAFE_CLOUD_RESOLUTION` and commit it in that same run.

## Next bounded frontier

1. Re-freeze upstream at the next run, starting from deferred `639823919ced15640924e905bacab3858c5afd19` or whatever immutable tip is current then.
2. Continue current agent timeout/retry/account-usage owner slices.
3. Continue Desktop main-process/gateway boot/team-change call sites consuming already reconciled helpers.
4. Continue provider/model-policy and OpenCode-removal changes under `agent/` and `hermes_cli/`.
5. Continue bounded enumeration of the remaining upstream delta; do not trust one compare result as complete coverage.

## Verification status

Executed this cycle:
- froze F/S/U;
- verified S already contained current fork main;
- read applicable root/downstream/Agent/Gateway instructions;
- proved the two reconciled files were byte-identical between sync start and the previous upstream target before adopting current-upstream blobs;
- inspected the upstream `/stop` fix and current fork/upstream helper shapes;
- inspected coupling for auxiliary-wire, credits, and billing-usage changes;
- revalidated upstream/fork dependency-input and lock blob identities;
- advanced the sync branch non-forced after re-reading the live ref;
- re-read the published source files and confirmed their blobs match the reviewed upstream blobs.

Not run:
- `scripts/run_tests.sh` / Python tests;
- Vitest/Electron tests;
- generators;
- runtime/network/GPU/service probes.

## Local-agent continuation

Continue on `automation/upstream-sync`; do not reset, rebase, force-push, or modify `main`. Highest-value local work is the `gateway/run_busy.py` `/stop` reconciliation and its focused Gateway tests. Commit any completion to this same branch and update this handoff; future cloud runs must preserve it.

## Acceptance boundary

This is still `HANDOFF_ONLY`. Neither reviewed upstream `52d203d041f9e4baad4a78013abeccd8f13a86e3` nor later observed `639823919ced15640924e905bacab3858c5afd19` is claimed as fully integrated. These are preparatory reconciliation commits only.

Do not merge to `main`. After all source overlaps and generated artifacts are complete, construct the genuine history-preserving upstream merge, test the exact immutable candidate SHA locally, and let the operator decide acceptance.
