# Hermes upstream-sync automation handoff

State: **HANDOFF_ONLY**. The frozen upstream target for this cycle is `e7552113274e990805f625ab91a8fe186a43df6a`; it is **not** attached as a complete merge parent. The persistent branch is `automation/upstream-sync`; only the operator lands an exact locally verified candidate to `main`.

## Frozen inputs — 2026-09-24

- Fork `main` (`F`): `b93ce5e66c3e405c0ea3fb30ef43458a601f5243`
- Sync tip at cycle start (`S`): `63bd6ffe2ee7107f2a7816ae81eff9159bb7cc67`
- Upstream `main` (`U`): `e7552113274e990805f625ab91a8fe186a43df6a`
- Fork-refresh merge created this cycle: `5a6a71e6de90cad34f4e35b7dd01f9b7548a7dba`
- Source-reconciliation tip before this handoff update: `45cd0641d58ee301c176291a8135cb4345e72f3d`

Fork `main` was re-read after source reconciliation and remained exactly `b93ce5e66c3e405c0ea3fb30ef43458a601f5243`. Upstream moved after the cycle freeze; the final live upstream ref observed before this handoff update was `deb4bd2c085757b3a5329d3a684d0ce395cc9a05`. That newer movement is deferred to the next cycle rather than chased mid-run.

## Fork-main refresh completed this cycle

`5a6a71e6de90cad34f4e35b7dd01f9b7548a7dba` is a genuine two-parent history-preserving refresh. First parent: prior sync line `63bd6ffe2ee7107f2a7816ae81eff9159bb7cc67`. Second parent: current fork `main` `b93ce5e66c3e405c0ea3fb30ef43458a601f5243`. Fork `main` itself was not modified.

The refresh tree is based on current fork `main`, preserves this cumulative handoff, and deliberately preserves the already-reconciled upstream `agent/moonshot_schema.py` blob `99a8f2333e2081fee69d6f8679e55027893a5e09` rather than regressing to fork-main's older blob. Current fork `agent/model_metadata.py` was retained because fork main had independently advanced that file after the previous sync cycle; it was not overwritten with the older sync blob.

Tests: **NOT RUN**.

## Source reconciliation completed this cycle

Four new upstream overlaps were proven safe from blob history: for each path, current fork `main` still matched the previous reviewed upstream baseline exactly, while frozen upstream changed the file. Therefore the frozen-upstream blob could be adopted without overwriting Arcadia-specific edits.

### `agent/command_token_source.py`

Classification: **SAFE_CLOUD_RESOLUTION → ALREADY_RESOLVED**.

Commit: `f8b710260958c9c43147be7118e3a49dfc272f40` — `sync: reconcile command token profile env with upstream e755211`.

Previous fork/upstream-baseline blob: `38ace243248b93e6195011264d979416ff88c850`. Frozen-upstream blob adopted: `08c6d0476306cbcd7ac255048e00d416caf37fa3`.

The upstream source now mints `key_cmd` credentials with `served_profile_child_env(inherit_credentials=True)`, so a served profile's command helper executes in that profile's own secrets/HERMES_HOME environment instead of inheriting the multiplexer's launch environment.

Tests: **NOT RUN**.

### `agent/error_classifier.py`

Classification: **SAFE_CLOUD_RESOLUTION → ALREADY_RESOLVED**.

Commit: `853fea07d608734c1b44188171cd53596f9ab210` — `sync: reconcile error classification with upstream e755211`.

Previous fork/upstream-baseline blob: `530ea1ebe5d1452b208746275e2c453b146cfdb1`. Frozen-upstream blob adopted: `d471e781b4681bd0757ac01753711100e4d60966`.

This is the exact frozen-upstream classifier blob. No downstream edit existed in this file relative to the prior reviewed upstream baseline, so no fork behavior was selected away.

Tests: **NOT RUN**.

### `agent/video_gen_provider.py`

Classification: **SAFE_CLOUD_RESOLUTION → ALREADY_RESOLVED**.

Commit: `ff7dba6d1178084109eba2085b09f3c1580383e7` — `sync: reconcile video generation provider with upstream e755211`.

Previous fork/upstream-baseline blob: `4b1644ba1b3d92535c83e5db32dd4e6173c93569`. Frozen-upstream blob adopted: `56b3bd8e6c00adbd0ceda915098cf693a4fb7bfd`.

Tests: **NOT RUN**.

### `agent/web_search_provider.py`

Classification: **SAFE_CLOUD_RESOLUTION → ALREADY_RESOLVED**.

Commit: `45cd0641d58ee301c176291a8135cb4345e72f3d` — `sync: reconcile web search provider with upstream e755211`.

Previous fork/upstream-baseline blob: `4c5e393241d440cd189948fb64c9198da0119768`. Frozen-upstream blob adopted: `947b95cc044a66c0f51f2fa083e118a21ee8781d`.

Tests: **NOT RUN**.

## Earlier reconciliation retained

Cloud-created before this cycle and preserved in first-parent history:
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

- Fork-main refresh through `b93ce5e66c3e405c0ea3fb30ef43458a601f5243` — `5a6a71e6de90cad34f4e35b7dd01f9b7548a7dba`.
- `agent/moonshot_schema.py` — prior upstream conditional-schema repair preserved through the fork refresh.
- `agent/command_token_source.py` — `f8b710260958c9c43147be7118e3a49dfc272f40`.
- `agent/error_classifier.py` — `853fea07d608734c1b44188171cd53596f9ab210`.
- `agent/video_gen_provider.py` — `ff7dba6d1178084109eba2085b09f3c1580383e7`.
- `agent/web_search_provider.py` — `45cd0641d58ee301c176291a8135cb4345e72f3d`.
- Earlier focused reconciliations listed above remain preserved.

### LOCAL_GENERATOR_REQUIRED

- Dependency-input + lock pair remains a real generated frontier. Current sync has `pyproject.toml` blob `79f11516b005000da7971ccab3de3d0830f3f035` and `uv.lock` blob `937c66b01054a5ab2eb38275e69057143e78dcfd`.
- Frozen upstream `e755211...` has `pyproject.toml` blob `1a98d5528c88ddc3d4e32439d3e8322487ce31bc` and `uv.lock` blob `852ac06d0e91c52da50448d9e7bf0251df00b704`.
- Both dependency input and generated lock differ. Reconcile the final combined `pyproject.toml` deliberately, preserving intentional fork-only development/test/downstream inputs, then regenerate `uv.lock` using the repository's canonical `uv lock` workflow in a real checkout. Never select either lock wholesale or fabricate generated bytes cloud-side.

### LOCAL_TEST_OR_RUNTIME_REQUIRED

- Hosted provider context-window cap stack from upstream commit `24f03c41c16323a28b53223ef5a00fc6bc9e15da`: upstream changes `agent/agent_loop.py`, `agent/turn_overflow.py`, and `tests/agent/test_turn_overflow.py`. The fork no longer has upstream's `agent/agent_loop.py` owner at that path. Map the effective-context-window handoff to the fork's current extracted orchestration owner, then exercise focused overflow/provider-cap tests.
- `gateway/run_busy.py` `/stop` semantics remain a carry-forward runtime-sensitive overlap: upstream's same-thread partial-stop/canonical-identifier work intersects fork session/profile/key-shape behavior. Combine against the current fork owner and exercise gateway stop cases rather than wholesale-selecting a side.
- The previously identified auxiliary/billing/credits owner stack remains coupled (`agent/auxiliary_wire.py`, `agent/rate_limit_credits.py`, `agent/billing_usage.py` plus sibling transport/accounting owners). Do not treat an individual file as independently safe until current call/ownership closure is re-censused and focused behavior is executable.
- `agent/stream_delivery.py` is not a direct-copy candidate: current fork and the prior reviewed upstream baseline already differed before frozen upstream changed it again. Preserve fork stream-delivery semantics while reviewing the new upstream delta, then run focused stream tests.

### OPERATOR_DECISION_REQUIRED

- None newly proven in this bounded cycle.

## Remaining review frontier

Frozen upstream `e755211...` is not fully represented by source ancestry or by a complete reconciled tree. Continue three-way review path by path. The generated lock blocker is not permission to stop unrelated source work: any newly proven `SAFE_CLOUD_RESOLUTION` item must still be committed. Live upstream `deb4bd2c085757b3a5329d3a684d0ce395cc9a05` was observed after the freeze and is deferred to the next cycle.

Current fork `agent/model_metadata.py` was advanced independently after the previous sync cycle, while frozen upstream also moved the file; it was intentionally left on the fork version during this refresh rather than overwritten without a fresh three-way audit. Treat that file as a next-cycle review frontier, not as already resolved through `e755211...`.

## Verification status

Executed/source-reviewed this cycle:
- read current fork root, downstream-development, nested Agent instructions, and the cumulative upstream-sync handoff;
- froze F/S/U and checked ancestry/merge-base relationships rather than relying on dates alone;
- re-read the live sync ref before every branch publication and found no concurrent movement;
- refreshed the sync branch from current fork `main` with a genuine two-parent merge preserving first-parent sync history;
- compared prior-upstream/current-fork/current-upstream blobs for four newly reconciled files and only adopted upstream where fork equaled the prior upstream baseline;
- published four focused source-reconciliation commits;
- re-read fork `main` and confirmed it remained `b93ce5e66c3e405c0ea3fb30ef43458a601f5243`;
- re-read upstream `main` and observed newer live tip `deb4bd2c085757b3a5329d3a684d0ce395cc9a05`, deferred rather than chased;
- revalidated the dependency/lock blocker by exact blob IDs.

Not run:
- `scripts/run_tests.sh` / Python tests;
- Vitest/Electron tests;
- `uv lock` or any generator;
- CLI contract generator/check;
- runtime/network/GPU/service probes.

## Local-agent continuation

Continue only on `automation/upstream-sync`; do not reset, rebase, force-push, or modify `main`.

1. Reconcile the final combined `pyproject.toml`, preserving intentional fork-only dev/test and downstream inputs while taking applicable upstream dependency changes; regenerate `uv.lock` canonically.
2. Map upstream hosted-context-window cap behavior from the removed upstream `agent/agent_loop.py` owner into the fork's current orchestration seam, and run focused overflow/provider-cap tests.
3. Revisit gateway `/stop`, `agent/stream_delivery.py`, and the coupled auxiliary/billing/credits frontiers against the refreshed fork tree.
4. Re-audit `agent/model_metadata.py` against current fork and the next frozen upstream before selecting a side; current fork was intentionally preserved this cycle.
5. Run affected Python coverage through `scripts/run_tests.sh`; run relevant JS/Electron coverage for desktop changes already on the branch; run `scripts/dump_cli_contract.py --check` if the eventual combined candidate touches a CLI contract surface.
6. Commit local completion to this same branch and update this handoff. Later cloud cycles must preserve that work.

## Consumer / acceptance boundary

This cycle changes internal provider token/environment handling, error classification, and media/search provider internals. No new Hermes CLI/RPC/payload contract was identified from these four source reconciliations, so no new Launcher-specific consumer action is recorded. Broader branch history may still carry existing consumer-alignment requirements; do not read or modify Launcher here.

This remains `HANDOFF_ONLY`. Frozen upstream `e7552113274e990805f625ab91a8fe186a43df6a` is not claimed as fully integrated, and live upstream `deb4bd2c085757b3a5329d3a684d0ce395cc9a05` is explicitly deferred. After all source overlaps and generated artifacts are complete, construct genuine history-preserving upstream merge ancestry, test the exact immutable candidate locally, and let the operator decide acceptance.
