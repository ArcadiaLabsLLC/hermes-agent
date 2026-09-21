# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY**. The upstream target reviewed in this cycle is `ea0c2b820bd30bace020a3791d8aef0b44002e0d`; it is **not** attached as a complete merge parent. The persistent branch remains `automation/upstream-sync`; only the operator lands an exact locally verified candidate to `main`.

## Frozen inputs — 2026-09-21

- Fork `main` (`F`): `f1268bd017d54e3102fe7f98c7e87b001adec747`
- Sync tip at cycle start (`S`): `2de6c76b848c9e22636590dfcb3052030de99bb5`
- Upstream `main` (`U`): `ea0c2b820bd30bace020a3791d8aef0b44002e0d`
- Previous reviewed upstream: `52d203d041f9e4baad4a78013abeccd8f13a86e3`
- Source-reconciliation tip before this handoff update: `6bc821d123077b0f8b2162a88adab72c2564a7bd`

Fork `main` did not move relative to the prior cycle, so no fork-refresh merge was required. Upstream advanced by 911 commits from the previous reviewed target; the GitHub compare is large and must not be treated as exhaustive coverage.

## Source reconciliation completed this cycle

### `79c4651015a77fee72d32bdff6635e02457fe684`

`sync: reconcile transcript timestamp markers with upstream ea0c2b8`

Changed:
- `agent/transcript_repair.py`

Why this was safe cloud-side: the sync-start blob and previous-upstream blob were both `a1bed300f302ec3ae3c525d260eba72ff8dc222b`, proving no downstream edit existed on this path. Current upstream is `f245088abcc96df1c3564534643b8341256345d1`, adopted verbatim. The change makes `sync_flushed_message_markers()` copy a numeric durable `timestamp` back onto the live message dict after commit, alongside the row id and canonical content.

Tests: **NOT RUN**.

### `6bc821d123077b0f8b2162a88adab72c2564a7bd`

`sync: preserve relay reasoning details from upstream ea0c2b8`

Changed:
- `agent/chat_completion_helpers_relay.py`

Why this was safe cloud-side: the sync-start blob and previous-upstream blob were both `ef5923c8193f41aa07d01f486c80680078ab58eb`, again proving no downstream edit on the path. Current upstream is `f853045822775fca5ec2b561609d9e953f6986d4`, adopted verbatim. `RelayChatAccumulator` now accumulates streamed `reasoning_details` records and includes them in the reconstructed final message so opaque signed/encrypted provider replay records survive the relay path in order.

Current upstream has focused reasoning-details tests, but that test stack did not exist at the previous reviewed target and was not copied piecemeal. Tests: **NOT RUN**.

## Earlier safe reconciliation retained

Cloud-created before this cycle:
- `a891c42d4978cf3fb4c7dee6a7972679e061027e` — desktop backend environment/home normalization pair.
- `d682b0209332df6f4ff88e03b1ef800fbfca4966` — desktop profile routing/preferences pair.
- `fe3a943e3c7572f547cac085b9bcfa2007d9384c` — desktop peer/session-window routing pair.
- `aa197f8a3b9db8183f6682d5141e852bc19ef66e` — reasoning timeout floors.
- `cfafa8d7efe9c34c558997823cdda9539ff66056` — retry reset parsing.
- `ebd572b7cdcddf5b1128c383cf5290ff02bab344` — history-preserving fork-main refresh.

Pre-existing operator/local work — **do not attribute to automation**:
- `f90f249e4c4140d2c11afe218634a86a2985c08e`
- `023153cd2b3be4bbce2e961aad9f718f898a8eb4`
- `0b8af0622952f73f05064eba1598e9596d37c49c`

## Conflict work queue

### ALREADY_RESOLVED

- Fork-main refresh through `f1268bd017d54e3102fe7f98c7e87b001adec747`.
- Prior desktop/reasoning/retry reconciliation stack above.
- `agent/transcript_repair.py` through upstream `ea0c2b8...` — `79c4651...`.
- `agent/chat_completion_helpers_relay.py` through upstream `ea0c2b8...` — `6bc821d...`.

### LOCAL_GENERATOR_REQUIRED

- `uv.lock`: current upstream is blob `41b83576c4546dfd3e0a3c6328b14456f90917a3`, while the sync branch retains downstream blob `c9e2c9a657ca6a69b4a77d49b85b6233a3bb6745`. Upstream also changed `pyproject.toml` from the previous reviewed upstream blob to current blob `f487128d79e7aacac2c48f3efc6a2e91be1c7d23`, while the fork retains downstream blob `d98df81c6315e164401edaf0710860d05fc8a64e`. Reconcile the dependency-input source deliberately, preserving intentional fork-only inputs, then regenerate `uv.lock` with the repository's canonical `uv lock` workflow. Do not select either lock wholesale or fabricate it cloud-side.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- `gateway/run_busy.py` `/stop` behavior centered on upstream `0fb56906fc70a5987aec4e3c773d5229369cd60e`. The upstream fix is understood, but the fork file carries downstream session/profile/key-shape behavior. Integrate the focused behavior in a real checkout and run the upstream `/stop` tests plus affected downstream Gateway tests with `scripts/run_tests.sh` before calling the combined behavior resolved.

### OPERATOR_DECISION_REQUIRED

- None newly identified in this cycle.

### Coupled source requiring bounded review before classification

These are not safe wholesale blob choices because the sync branch already differs from the previous upstream baseline or the caller depends on sibling owner changes. Review the complete owner slice before classifying a concrete edit:
- `agent/auxiliary_wire.py` + current chat-completions transport sanitization owner changes.
- `agent/rate_limit_credits.py` + `agent/credits_tracker.py`.
- `agent/billing_usage.py` + `agent/account_usage.py`.
- downstream-diverged agent owners such as `agent/error_classifier.py`, `agent/usage_pricing.py`, `agent/turn_finalizer.py`, `agent/turn_iteration_prep.py`, and `agent/micro_compaction.py`.

The next cloud cycle must keep looking for exact `SAFE_CLOUD_RESOLUTION` slices inside the 911-commit frontier rather than stopping on the local-only rows above.

## Verification status

Executed this cycle:
- froze F/S/U and verified fork `main` is unchanged;
- read root, downstream and Agent instructions relevant to the touched files;
- compared previous-upstream and sync-start blob identities before adopting each current-upstream source file;
- published two focused source commits on `automation/upstream-sync` only;
- re-read the branch ref and both published source blobs after publication;
- rechecked dependency-input and lock blob identities against current upstream.

Not run:
- `scripts/run_tests.sh` / Python tests;
- Vitest/Electron tests;
- generators, including `uv lock`;
- runtime/network/GPU/service probes.

## Local-agent continuation

Continue only on `automation/upstream-sync`; do not reset, rebase, force-push, or modify `main`. Highest-value local work remains the `gateway/run_busy.py` `/stop` combined-behavior reconciliation/tests and the dependency-input + `uv.lock` regeneration once that source merge is decided. Commit completion to this same branch and update this handoff; later cloud cycles must preserve it.

## Acceptance boundary

This remains `HANDOFF_ONLY`. Upstream `ea0c2b820bd30bace020a3791d8aef0b44002e0d` is not claimed as fully integrated. The two commits above are preparatory source reconciliations only. After all source overlaps and generated artifacts are complete, construct genuine history-preserving upstream merge ancestry, test the exact immutable candidate locally, and let the operator decide acceptance.
