> Correction (2026-09-15): upstream has a managed local-model installer/runtime under `hermes_cli/local_runtime`. Any earlier absence claim below is superseded. See [integration checkpoint](integration-stage1.md#installer-correction). This candidate is still incomplete and untested.

# Local llama installer handoff after synchronization inventory

Status: **blocked on a validated upstream integration baseline**, not approved
for implementation. No installer or Launcher behavior was changed.

Current implemented snapshot is `34ad8ba33f2508ab10bb24a26f0377ddb62660cb`.
Fetched upstream is `110baa095bc7135a0624557a9cc35df0f98ece0f`. There is no
validated combined source yet. This is an assessment against both source trees,
not a claim to have reassessed an updated/landed implementation.

## What the upstream comparison changes

- Upstream has no `agent_runtime/local_llama/` or Harness RPC command parts.
  Preserve that downstream implementation. There is no upstream installer to
  substitute for the proposed backend contract.
- Shared `agent/agent_init.py`, `agent/auxiliary_client.py`,
  `agent/conversation_compression.py`, `run_agent.py`, `hermes_cli/auth.py`,
  `hermes_cli/config.py` and `hermes_cli/runtime_provider.py` all conflict. Their
  unchanged names do not establish compatible semantics.
- At the pinned upstream tip, `get_text_auxiliary_client(..., main_runtime=...)`
  and `AIAgent._current_main_runtime()` still exist. Preserve the downstream
  same-endpoint/model override ahead of cloud resolution and its context-local
  scope; test against upstream's expanded auxiliary interruption/cancellation
  machinery. Never infer compatibility merely from those retained signatures.
- Upstream compression still rejects auxiliary context below
  `MINIMUM_CONTEXT_LENGTH` at `agent/conversation_compression.py:1847`. The
  downstream managed-local exception must survive, restricted to the same
  verified model/context and minimum 4096. Do not broaden the exception to cloud
  providers, or inflate a local model's actual context.
- Preserve runtime construction's reserved provider identity, no-fallback rule,
  whole-turn lease and active-turn mutation exclusion through upstream turn
  refactors. Configuration must keep the root-bound manager's authority rather
  than accidentally switching to an upstream per-profile loader.
- `scripts/upstream_sync_gate.py` currently invokes bare pytest despite the
  newer instruction requiring `scripts/run_tests.sh`. Correct that gate in the
  integration work before claiming a gate verdict. Do not execute it unchanged.

## Design requirements still outstanding

Keep `../local-llama-installation-contract.md` **proposed, not fixture-frozen**.
The source comparison does not justify renaming its methods or approving its DTOs.
Before implementing, pin the actual green integration SHA and verify:

1. Existing nine-method v1 manifest, console/read authorization, owning-serve
   binding and peer refusal. Setup remains a separate additive schema.
2. Distinct `active_operation` and `requested_operation`. Historical receipt
   lookup must not hide a currently busy manager or unlock controls.
3. Original draft revisions, epoch, inventory revision, request fingerprints and
   active-turn guards. Define validation precedence for a request that becomes
   stale while the manager transitions; the baseline test exposed that race.
4. Crash journal for multi-file configuration/inventory/receipt publication;
   recovery and interrupted/cancelled operations must have durable outcomes.
5. Installation and activation remain separate; neither starts the server or
   loads weights. Activation requires server off and no active turns. Preserve
   UUID model identities and scans rather than introducing another importer.
6. Release catalog must revalidate official release/asset semantics at implement
   time and pin artifacts. This audit did not refresh llama.cpp release data.
   Download/extraction trust checks and isolated binary qualification remain
   required, with no driver installation or PATH/package-manager mutation.
7. Producer-owned method fixtures and real served-wire proof before Launcher
   integrates. Re-run the focused tests and real model probe on the COMBINED
   source; this checkpoint's passes prove only the old fork baseline.

## Available proof and gaps

394 tests passed over 17 files through the canonical wrapper, with one
retry-green manager file; see `verification.md`. Real isolated production
manager/RPC + full agent/tool loop passed, same local model/endpoint for auxiliary
compression, 8192 context, 4096 reload, owned shutdown. No cloud fallback was
present (asserted by the existing probe).

Remaining: all 187 merge conflicts and semantic seam review, integration regression
tests, upstream dependency environment, corrected sync gate, companion fixtures,
full Stage C and second physical remote-host acceptance. No installer execution
or readiness claim is warranted from this baseline alone.
