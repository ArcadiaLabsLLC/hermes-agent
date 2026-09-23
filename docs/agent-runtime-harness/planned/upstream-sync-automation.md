# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY**. The frozen upstream target for this cycle is `eb8960fead33a8d312a91f5b2f566ad7635815e7`; it is **not** attached as a complete merge parent. The persistent branch is `automation/upstream-sync`; only the operator lands an exact locally verified candidate to `main`.

## Frozen inputs — 2026-09-23

- Fork `main` (`F`): `c219b17be3a7c724d14f1e2019ca2ee59a342348`
- Sync tip at cycle start (`S`): `2cc847e2871d9ead5ccffbdf84949778c02389be`
- Upstream `main` (`U`): `eb8960fead33a8d312a91f5b2f566ad7635815e7`
- Fork/upstream merge base observed for this frontier: `d337b736f78f3a5deb1a59f2c428aad7f01a794e`
- Fork-refresh + source-reconciliation merge created this cycle: `017a4af39142aa48bba88baaa7ac720528a30ed6`

At the end-of-cycle re-read, fork `main` was still exactly `c219b17be3a7c724d14f1e2019ca2ee59a342348`. Upstream had advanced beyond the frozen target to `004fa2e7cbbe77d7544988104941ff99da6e79c9`; that newer upstream movement is deliberately deferred to the next cycle rather than chased mid-run.

## Fork-main refresh and source reconciliation completed this cycle

`017a4af39142aa48bba88baaa7ac720528a30ed6` is a genuine two-parent history-preserving refresh. Its first parent is the prior sync line `2cc847e2871d9ead5ccffbdf84949778c02389be`; its second parent is current fork `main` `c219b17be3a7c724d14f1e2019ca2ee59a342348`. Fork `main` itself was not modified.

The merge tree is based on current fork `main` and preserves the cumulative sync handoff while resolving two source overlaps against the frozen upstream target.

### `agent/model_metadata.py`

Classification before the merge: **SAFE_CLOUD_RESOLUTION**.

Relevant blobs:
- cycle-start sync branch: `421700f6be996e54082fae09a4ec9f2e2f9df2f4`
- current fork `main`: `4d6bc477f9e856cfd9e9c7e7821f7561dfc79bcb`
- frozen upstream: `9b468e5f25b310e69073c233fb542ff0dbebcc5b`

The fork had moved the upstream-owned Codex catalog/model metadata forward while the sync line carried the earlier Mimo v2.6 reconciliation. Frozen upstream contains the current upstream combination, including the newer Codex catalog semantics and the Mimo v2.6 context-window entries, so the merge adopts the frozen-upstream blob rather than regressing either line of behavior.

Tests: **NOT RUN**.

### `agent/moonshot_schema.py`

Classification before the merge: **SAFE_CLOUD_RESOLUTION**.

Relevant blobs:
- cycle-start sync branch: `99a8f2333e2081fee69d6f8679e55027893a5e09`
- current fork `main`: `079280cfbb85fbfb52cab2d1a85294a978712365`
- frozen upstream: `99a8f2333e2081fee69d6f8679e55027893a5e09`

The sync line had already reconciled upstream's conditional-schema repair while current fork `main` did not yet contain it. The refresh therefore preserves the already-current upstream blob instead of regressing the fix. That implementation recursively repairs JSON-Schema `if` / `then` / `else` nodes and avoids incorrectly defaulting a bare conditional schema to `type: string`.

Tests: **NOT RUN**.

## Earlier reconciliation retained

Cloud-created before this cycle and still preserved in first-parent history:
- `e9d716f06feb641c40a6702a5818d58bdecd40a8` — earlier model metadata reconciliation.
- `23426949dc4d82a0f2766a741bcd01f6a8c3c428` — earlier Moonshot schema reconciliation.
- `79c4651015a77fee72d32bdff6635e02457fe684` — transcript durable timestamp markers.
- `6bc821d123077b0f8b2162a88adab72c2564a7bd` — Relay `reasoning_details` replay preservation.
- `a891c42d4978cf3fb4c7dee6a7972679e061027e` — desktop backend environment/home normalization.
- `d682b0209332df6f4ff88e03b1ef800fbfca4966` — desktop profile routing/preferences.
- `fe3a943e3c7572f547cac085b9bcfa2007d9384c` — desktop peer/session-window routing.
- `aa197f8a3b9db8183f6682d5141e852bc19ef66e` — reasoning timeout floors.
- `cfafa8d7efe9c34c558997823cdda9539ff66056` — retry reset parsing.

Pre-existing operator/local work retained — **do not attribute to automation**:
- `f90f249e4c4140d2c11afe218634a86a2985c08e`
- `023153cd2b3be4bbce2e961aad9f718f898a8eb4`
- `0b8af0622952f73f05064eba1598e9596d37c49c`

## Conflict work queue

### ALREADY_RESOLVED

- Fork-main refresh through `c219b17be3a7c724d14f1e2019ca2ee59a342348` — `017a4af39142aa48bba88baaa7ac720528a30ed6`.
- `agent/model_metadata.py` through frozen upstream `eb8960f...` — resolved in `017a4af...` with upstream blob `9b468e5...`.
- `agent/moonshot_schema.py` through frozen upstream `eb8960f...` — resolved in `017a4af...` with upstream blob `99a8f23...`.
- Earlier focused source reconciliations listed above remain preserved.

### LOCAL_GENERATOR_REQUIRED

- Dependency-input + lock pair remains a real generated frontier. After the fork refresh the current sync tree has `pyproject.toml` blob `79f11516b005000da7971ccab3de3d0830f3f035` and `uv.lock` blob `937c66b01054a5ab2eb38275e69057143e78dcfd`.
- Frozen-upstream `pyproject.toml` was source-read at `eb8960f...` and is semantically different from the current fork input: the fork retains downstream development/test inputs including `coverage==7.16.0` and `pytest-timeout==2.4.0` plus its downstream `hindsight` extra, while the frozen upstream source does not carry those fork-only additions.
- The exact frozen-upstream contents-metadata read for `pyproject.toml` / `uv.lock` hit a transient GitHub connector 429 during this bounded cycle, so this handoff does **not** invent a new frozen-upstream blob SHA. That does not remove the generator requirement: the dependency inputs are confirmed divergent, therefore the final combined `pyproject.toml` must be deliberately reconciled first and `uv.lock` regenerated with the repository's canonical `uv lock` workflow in a real checkout. Never choose either lock wholesale or fabricate generated bytes cloud-side.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- Hosted provider context-window cap stack from upstream commit `24f03c41c16323a28b53223ef5a00fc6bc9e15da`: upstream changes `agent/agent_loop.py`, `agent/turn_overflow.py`, and `tests/agent/test_turn_overflow.py`. The current fork's `agent/turn_overflow.py` still matches that upstream commit's parent blob `41292cf0d675f8e16ea6cd3858f2ce943bf2e9af`, but the fork no longer has the upstream `agent/agent_loop.py` owner at that path. A verbatim three-file port would therefore be incomplete. The effective-context-window handoff must be mapped to the fork's current extracted orchestration owner and then exercised through the focused overflow/provider-cap tests before this stack can be claimed integrated.
- `gateway/run_busy.py` `/stop` semantics remain a carry-forward runtime-sensitive overlap: upstream's same-thread partial-stop/canonical identifier work intersects fork session/profile/key-shape behavior. Do not wholesale-select one side; combine against the current fork owner and exercise the gateway stop cases in a real checkout.
- The previously identified auxiliary/billing/credits owner stack remains coupled (`agent/auxiliary_wire.py`, `agent/rate_limit_credits.py`, `agent/billing_usage.py` and their sibling transport/accounting owners). Do not treat an individual file as independently safe until the current call/ownership closure is re-censused and the focused behavior is executable.

### OPERATOR_DECISION_REQUIRED

- None newly proven in this bounded cycle.

## Remaining review frontier

Frozen upstream `eb8960f...` is not fully represented by source ancestry or by a complete reconciled tree. Continue three-way review path by path on later cloud cycles. A generated lock blocker is not permission to stop unrelated source work: any newly proven `SAFE_CLOUD_RESOLUTION` item must still be committed. The live upstream tip `004fa2e...` was observed after the freeze and is deferred for the next cycle.

## Verification status

Executed/source-reviewed this cycle:
- read current fork root, downstream-development, Agent, upstream-sync, Local llama, and downstream-schema instructions/contracts relevant to this task;
- froze F/S/U and checked ancestry/merge-base relationships rather than relying on dates alone;
- re-read the live sync ref before publication and found no concurrent branch movement;
- refreshed the sync branch from current fork `main` with a genuine two-parent merge preserving first-parent sync history;
- compared the retained model/schema blobs across starting sync, current fork, and frozen upstream before selecting the merge-tree contents;
- re-read the published sync ref and verified it points at `017a4af39142aa48bba88baaa7ac720528a30ed6`;
- source-reviewed upstream hosted-context-window commit `24f03c41...` and rejected a partial verbatim port after confirming the fork lacks upstream's `agent/agent_loop.py` owner path;
- re-read fork `main` at cycle end and confirmed it remained `c219b17...`;
- re-read upstream `main` at cycle end and observed newer live tip `004fa2e7cbbe77d7544988104941ff99da6e79c9`, which is deferred rather than chased.

Not run:
- `scripts/run_tests.sh` / Python tests;
- Vitest/Electron tests;
- `uv lock` or any generator;
- CLI contract generator/check;
- runtime/network/GPU/service probes.

## Local-agent continuation

Continue only on `automation/upstream-sync`; do not reset, rebase, force-push, or modify `main`.

1. Reconcile the final combined `pyproject.toml` source, preserving intentional fork-only dev/test and downstream inputs while taking applicable upstream dependency changes; then regenerate `uv.lock` canonically.
2. Map upstream hosted-context-window cap behavior from the removed upstream `agent/agent_loop.py` owner into the fork's current orchestration seam, and run the focused overflow/provider-cap tests.
3. Revisit the gateway `/stop` and coupled auxiliary/billing/credits frontiers against the now-refreshed fork tree.
4. Run affected Python coverage through `scripts/run_tests.sh`; run relevant JS/Electron coverage for desktop changes already on the branch; run `scripts/dump_cli_contract.py --check` if the eventual combined candidate touches a CLI contract surface.
5. Commit local completion to this same branch and update this handoff. Later cloud cycles must preserve that work.

## Consumer / acceptance boundary

No new Hermes CLI/RPC/payload contract was changed by this cycle's two source resolutions (`agent/model_metadata.py`, `agent/moonshot_schema.py`), so this cycle identifies no new Launcher-specific consumer action. Broader branch history may still carry existing consumer-alignment requirements; do not read or modify Launcher here.

This remains `HANDOFF_ONLY`. Frozen upstream `eb8960fead33a8d312a91f5b2f566ad7635815e7` is not claimed as fully integrated, and live upstream `004fa2e7cbbe77d7544988104941ff99da6e79c9` is explicitly deferred. After all source overlaps and generated artifacts are complete, construct genuine history-preserving upstream merge ancestry, test the exact immutable candidate locally, and let the operator decide acceptance.
