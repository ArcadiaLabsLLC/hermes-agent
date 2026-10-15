# Native worker connection ownership qualification — 8 October 2026

The Launcher app-function connection now belongs to a typed `SessionBinding` on the gateway's existing session record. The worker no longer writes or reads `agent._launcher_app_function_link`. Warm turns and agent replacement reuse the exact discovered connection and catalog. The runtime contract is [Chat Turn Lane](../agent-runtime-harness/05-chat-turn-lane.md).

Eager resume, branching and compute-host construction use a transient, context-local construction scope. Registration attaches the binding under the gateway's session lock, before I/O or publication makes the record available to a turn. Compute-host fallback migrates that same binding to its minimal record. A duplicate resume releases its abandoned catalog. Failure before registration, after transfer, or during concurrent teardown releases the exact connection without clearing another session's catalog. A failed registered record retains its closed binding and cannot silently rediscover; a failed first factory build can retry. Failed replacement preserves the still-live agent's binding. Closed emitters refuse locally. Discovery and the agent factory run outside the session lock.

## Verification

| Check | Result |
| --- | --- |
| Focused discovery, catalog, prewarm and connection lifetime checks | 87 passed across five files, 8.0 seconds |
| Real gateway eager resume, duplicate resume, branching, registration failures, early-publication race and compute-host fallback | Included in the 22 lifetime tests |
| Ruff on the touched Python files | Passed |
| Full sanctioned fork landing gate on `e74511a2a0` | 1,186 files; 14,859 passed, 86 failed, 102 skipped; 893.4 seconds, eight workers |
| Final failing assertion comparison against unchanged `6d90a42dae` | The identical 86 nodes fail; zero candidate-only or base-only nodes |
| Exit-flush process-death comparison | Same eight collected cases and first `s`, followed by process death in candidate and base, bundled and alone; unqualified |
| Tool-manifest ordered-prefix comparison | Identical isolation leak on base after the same four preceding files, then green alone |
| Documentation adjacency and changed-line mutation inventory | Passed |

Nine planted defects are checked on detached throwaway copies: reacquire a link on every bind; remove teardown cleanup; omit failed initial construction cleanup; ignore a late closed discovery result; omit normal registration transfer; omit fallback transfer; leave an abandoned construction scope open; omit cleanup after failed transferred registration; permit failed registered records to rediscover. Each produces assertion failures, and the copy is restored after each control. The CHANGE commits record the exact reds.

The full gate is **red**. Its printed `0 errors` does not qualify the exit-flush file: eight collected cases terminate after the first skipped case, with no completed file result. The baseline reproduces the same death, including an isolated rerun. The tool-manifest leak is separately recorded because its final isolated result is green. Its exact ordered prefix on the unchanged base reproduces the same failing node and green rerun; a duration-planned run which split that prefix was not sufficient proof.

The assertion comparison uses the final failure footer. The runner ledger carries a modal-sandbox red from an earlier scope which this cleanup's full run does not reach. The initial base command also ran that extra file (772 passed, 87 failed, four skipped, 375.6 seconds); its extra modal node is excluded from the current 86-node comparison. The exit-flush file was compared separately. The final JSON receipt records those distinctions.

The footprint violation also matches exactly: measured `files=184 deleted_lines=959 heavy=4`, fixture `files=176 deleted_lines=883 heavy=4`, violations `files: (176, 184)` and `deleted_lines: (883, 959)`. Neither the fixture nor a timing floor or timeout budget was loosened. The source adds narrow calls/decorators in already-carried files and replaces two lines of an existing fork factory seam; the upstream deletion/file/heavy counts do not increase.

| Final assertion failures under `tests/`, identical on base | Nodes |
| --- | ---: |
| `agent_runtime/test_gateway_media_fetch_e2e.py` | 5 |
| `agent_runtime/test_gateway_peer_cross_install_chat_e2e.py` | 3 |
| `agent_runtime/test_gateway_peer_cross_install_media_e2e.py` | 2 |
| `agent_runtime/test_gateway_peer_two_roots_e2e.py` | 9 |
| `agent_runtime/test_gateway_tls.py` | 1 |
| `agent_runtime/test_local_llama_adapter_gateway.py` | 2 |
| `agent_runtime/test_scope_use_serve_acceptance.py` | 3 |
| `agent_runtime/test_serve_gateway_chat_reply_lanes.py` | 2 |
| `agent_runtime/test_serve_gateway_lane.py` | 17 |
| `agent_runtime/test_serve_gateway_peer_lane.py` | 24 |
| `agent_runtime/test_stream_gap_receipt.py` | 1 |
| `gateway/test_complete_path_at_filter.py` | 3 |
| `scripts/test_upstream_footprint.py` | 1 |
| `tui_gateway/test_bot_relay_methods.py` | 1 |
| `tui_gateway/test_display_methods.py` | 2 |
| `tui_gateway/test_display_watch.py` | 1 |
| `tui_gateway/test_ephemeral_profile_override.py` | 3 |
| `tui_gateway/test_profiles_describe_secret_scope.py` | 1 |
| `tui_gateway/test_show_reasoning_display_gate.py` | 1 |
| `tui_gateway/test_tui_gateway_server.py` | 4 |

Newly reached failures include remote path expectations, missing `fcntl`, Windows path normalization/casing, an environment mutation, a report subprocess cap, and a removed desktop-classifier literal. These are recorded in the [fork hygiene queue](../../Harness_Brain/20%20%E2%80%94%20Active%20Initiatives/fork-hygiene-queue.md); their test files were not edited here. The shared cause of the existing peer/TLS failures remains unproven.

Two earlier whole-tree runs were interrupted after finding the eager construction handoff gap and the registration visibility race. Their partial results are not qualification. Safe raw receipts, the final node comparison and the detached mutation logs are retained in ignored `qa-artifacts/native-worker-link-2026-10-08/` in the primary checkout.

## Local certificate interception — 8 October 2026

A separate bounded diagnostic on unchanged `9982a6720a`, using the checkout's CPython 3.13.15 venv, confirms local Norton interception. It minted one disposable identity with `ensure_certificate`, served it through the real `server_ssl_context` on `127.0.0.1` and an ephemeral port, and compared the presented DER with both the certificate file and the recorded pin. Socket operations had four-second timeouts; each server thread was joined and finished. This was a diagnostic, not a rerun of the failing suite.

| Client configuration | Exact DER / fingerprint matches | Ping/pong |
| --- | --- | --- |
| Stdlib before truststore injection | No / No | Passed |
| Stdlib pinned-client helper with truststore injected | No / No | Passed |
| Platform client with truststore injected | No / No | Passed |

All three presented certificates retained `CN=hermes-loopback-diagnostic` but had issuer `CN=Norton Web/Mail Shield Self-signed Root,O=Norton Web/Mail Shield,OU=generated by Norton Antivirus for self-signed certificates`. The gateway's minted certificate is self-signed under its own diagnostic name. No server error occurred. Thus certificate replacement, rather than an inability to complete TLS, directly explains the probe's pin mismatch. [Norton's Windows documentation](https://support.norton.com/sp/en/us/home/current/solutions/v2025030513084015) describes its certificate installation for encrypted-content scanning.

This establishes interception on this machine; it does not establish that every one of the 68 gateway/peer failures has that cause. The next qualification must confirm that a narrowly scoped scanning exclusion preserves the exact gateway DER, then rerun the affected files and classify any remaining failures. Neither trusting the replacement certificate nor bypassing the pin is a repair. No antivirus setting, production certificate, runtime source, or assertion was changed. The existing fork-hygiene row remains open. Raw diagnostic results are retained locally in ignored `qa-artifacts/native-worker-link-2026-10-08/norton-loopback-probe.jsonl`.

## Existing limitation found by the real fallback test

`ComputeHost._build_server_session` calls the removed gateway helper `_sanitize_client_source` in its minimal-record fallback. Forced hydration failure raises `AttributeError` there. The ownership test supplies the gateway's existing source resolver under that name solely to isolate the binding handoff; it does not claim the unmodified fallback works end to end. The defect is filed in the [runtime queue](../../Harness_Brain/20%20%E2%80%94%20Active%20Initiatives/runtime-queue.md).

## Cost and remaining live acceptance

This cleanup adds no model tools, schemas, prompt text or per-turn discovery RPC. Identity and catalog-call assertions prove continued turns and replacement reuse the same connection. That is not a provider latency measurement. The authenticated native provider run remains unavailable as recorded in [GenUI discovery qualification](genui-discovery-qualification-2026-10-08.md); first-response selection across providers, live TTFT and cached-token behavior remain unqualified. Luau and streaming previews are outside this cleanup.

Upstream edits are narrow calls and decorators in already-carried gateway files. Their retirement doors are recorded in the [footprint ledger](../agent-runtime-harness/planned/upstream-footprint-ledger.md); no separate session registry or upstream-agent storage is introduced.
