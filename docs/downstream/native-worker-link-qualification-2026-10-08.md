# Native worker connection ownership qualification — 8 October 2026

The Launcher app-function connection now belongs to a typed `SessionBinding` on the gateway's existing session record. The worker no longer writes or reads `agent._launcher_app_function_link`. Warm turns and agent replacement reuse the exact discovered connection and catalog. The runtime contract is [Chat Turn Lane](../agent-runtime-harness/05-chat-turn-lane.md).

Eager resume, branching and compute-host construction use a transient, context-local construction scope until registration transfers the binding. A duplicate resume releases its abandoned catalog. Failure before registration, after transfer, or during concurrent teardown releases the exact connection without clearing another session's catalog. Failed replacement preserves the still-live agent's binding. Closed emitters refuse locally. Discovery and the agent factory run outside the session lock.

## Verification

| Check | Result |
| --- | --- |
| Focused discovery, catalog, prewarm and connection lifetime checks | 86 passed across five files, 7.7 seconds |
| Real gateway eager resume, duplicate resume, branching, registration failures and compute-host fallback | Included in the 21 lifetime tests |
| Ruff on the touched Python files | Passed |
| Full sanctioned fork landing gate | Pending final candidate run; the earlier interrupted run is incomplete |

Eight planted defects are checked on detached throwaway copies: reacquire a link on every bind; remove teardown cleanup; omit failed initial construction cleanup; ignore a late closed discovery result; omit normal registration transfer; omit fallback transfer; leave an abandoned construction scope open; omit cleanup after failed transferred registration. Each must produce assertion failures, and the copy is restored after each control. The CHANGE commits record the exact reds.

The earlier whole-tree gate was interrupted after finding the eager construction handoff gap. Its partial results are not a qualification. The final gate and unchanged-base node/violation comparison will replace the pending row before landing.

## Existing limitation found by the real fallback test

`ComputeHost._build_server_session` calls the removed gateway helper `_sanitize_client_source` in its minimal-record fallback. Forced hydration failure raises `AttributeError` there. The ownership test supplies the gateway's existing source resolver under that name solely to isolate the binding handoff; it does not claim the unmodified fallback works end to end. The defect is filed in the [runtime queue](../../Harness_Brain/20%20%E2%80%94%20Active%20Initiatives/runtime-queue.md).

## Cost and remaining live acceptance

This cleanup adds no model tools, schemas, prompt text or per-turn discovery RPC. Identity and catalog-call assertions prove continued turns and replacement reuse the same connection. That is not a provider latency measurement. The authenticated native provider run remains unavailable as recorded in [GenUI discovery qualification](genui-discovery-qualification-2026-10-08.md); first-response selection across providers, live TTFT and cached-token behavior remain unqualified. Luau and streaming previews are outside this cleanup.

Upstream edits are narrow calls and decorators in already-carried gateway files. Their retirement doors are recorded in the [footprint ledger](../agent-runtime-harness/planned/upstream-footprint-ledger.md); no separate session registry or upstream-agent storage is introduced.
