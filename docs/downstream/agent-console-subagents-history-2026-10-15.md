# Agent Console subagent results and history — Step 5

Owner approval: October 15, 2026. Persisted observations join the existing
owned subagent port. Hermes remains the writer, retention owner and execution
owner. This step adds no scheduler, result database, delivery acknowledgement,
worker creation, saved-tree writer or live-control authority.

## Endpoints and values

Both authenticated console families expose the same three reads:
`runtime.conversation.subagents.history/result/tree` and
`runtime.operator.conversation.subagents.history/result/tree`.
`agent_runtime/subagents/model.py` declares the operations and required
parameters; `subagents/params.py` feeds the existing RPC manifest.

| Value | Connection / source |
| --- | --- |
| Native owner | `install_id`, `session_id`, `client_scope`, `profile`; `conversations/rpc.py` → `ConversationService._owned_route` |
| Operator owner | `install_id`, `workspace_id`, `persona_id`, `persona_instance_id`, `session_id`, `client_scope`; `serve_rpc/operator_subagents.py` → `subagents/operator.py` → `operator_session_read` |
| `version`, `generation`, `observed_at` | `subagents/history.py`; identity is echoed and revalidated after reading |
| `history_ref`, `expected_generation` | Result/tree detail request; `subagents/references.py` signs owner, source kind, stored record identity and projected content. References rotate with the service; re-list after restart. They cannot authorize Steer/Stop |
| `results`, `trees`, `results_available`, `trees_available`, `truncated` | `subagents/history_store.py`; independent source availability, bounded list of at most 100 results and 100 snapshots, not a second retention policy |
| Result `goal`, `task_index`, `status`, `model`, `started_at`, `completed_at`, `source` | Native `async_delegations.task_json/result_json` or persisted `messages` with `role=tool`, `tool_name=delegate_task`; absolute batch task indexes label the original goals |
| `summary`, `error`, `exit_reason`, `failure_reason`, `truncated` | Native result entries produced by `tools/delegate_tool_child_run.py`; iteration-limit completion is qualified, never silently presented as full success |
| `input_tokens`, `output_tokens`, `api_calls`, `duration_seconds` | Native child `tokens.input/output`, API-call count and duration; absent values remain null |
| `cost_usd`, `cost_status` | Native child estimate and its status; not a new calculator; the UI warns that parent totals may include the child |
| `schema_valid`, `schema_retries`, `schema_errors` | Native output-schema result; validation failure remains visible |
| `missed_steer` | Native child completion fact; never interpreted as per-correction delivery evidence |
| `timeout_seconds`, `timed_out_after_seconds`, `timeout_phase`, `last_event_age` | Optional native timeout evidence, shown only when recorded |
| `stall_phase`, `stalled_after_quiet_seconds`, `stall_threshold_seconds`, `stall_grace_seconds` | Native async stall finalization evidence from `tools/async_delegation.py`; stalled and rejected outcomes keep their own status labels |
| `tool_trace` | Native `tool`, `input_summary`, `status`, `args_bytes`, `result_bytes`; no private messages or diagnostics |
| `processes` | Native `handed_off_processes`, `orphaned_processes`, `unread_completions`; allowlisted kind, session ID, command, note, runtime seconds, exit code and output tail. Historical facts, no process actions |
| `content_truncated` | Projection bound, separate from native iteration truncation; text 65,536 characters, trace 100 entries, schema errors 20, each process outcome 20 |
| Tree `label`, `started_at`, `finished_at`, `children`, `truncated` | Existing native `spawn-trees/<session>/<snapshot>.json` payload. Child ID, parent ID, depth, goal, model, status, delegation ID, start time, tool count and last tool are projected; `child_ref=null`, `controllable=false`, `accepting_steer=false` |

All strings cross the existing secret scrubber. Reads neither run DDL nor
consume pending completions. Synchronous result messages and async durable
rows retain their native retention. Matching delegation IDs are deduplicated;
no heuristic summary/time join manufactures equivalence between records.

## Per-seam footprint register

| Seam | Connection and disposition | Replacement / proof |
| --- | --- | --- |
| Service borrow mode | `ConversationService.subagents` validates `_owned_route`, then `conversations/subagent_history.py` reads stores without `Bindings.borrow`; live operations retain the existing-only worker borrow | Keep harness route ownership until an equivalent public owned route exists; a worker factory that fails on any acquisition proves history does not start execution |
| Worker-entry registration | `worker_subagents.py` uses `LIVE_OPERATIONS`; existing worker/compute registrations remain six live verbs. The three history reads terminate in the service | No new worker or compute RPC, registration or upstream-file hunk; native/compute/in-process round trips must still work |
| Operator RPC family | Existing console-tier family delegates through `operator_session_read` and profile binding to the same history reader | Retain exact install/workspace/persona/instance/session/client validation; device/unknown callers remain refused |
| Completion/transcript read | `subagents/history_store.py` reads native SQLite with `mode=ro`. Transcript DB is the validated conversation DB. Native async DB uses the existing `get_hermes_background_work_home` under the route's profile context; operator async DB is the authoritative session head | Replace SQL projection with an equivalent public owned result-list API when available; never add another writer. Split head/profile test proves writer/reader agreement |
| Lineage | Public `SessionDB.get_compression_lineage`; delegated child sessions require the native `_delegate_from` marker recursively | Replace only with a native scoped delegation-history API. Shared `parent_session_id` alone never includes branch/reset conversations |
| Saved trees | Enumerate only owned lineage directories under the captured profile home; verify payload `session_id`, reject redirected roots/files, bound reads; never use caller paths or cross-session index entries | Replace with an equally scoped native read API. Snapshots saved only under an unrelated UI session ID cannot be attributed and are omitted |
| Historical references | Existing signer gains a separate content-bound observation method; no server observation cache | Replace with native owner-bound immutable history references; changed content, kind or owner refuses |
| Launcher presentation | Same borrowed port and provider lifetime, distinct typed history references, existing branch renderer | One observation controller; saved trees cannot invoke command methods; hidden/disposed responses cannot repopulate a view |

All changed production files are fork-owned. No upstream-file diff, private
upstream dependency allowance, footprint ceiling or exception set is added.
The register is linked from the canonical footprint ledger. Existing live
execution seams and their replacement conditions remain in the
[Step 4 register](agent-console-subagents-controls-2026-10-15.md).

## Qualification

Focused tests use real SessionDB writes, native result construction and async
dispatch persistence, plus both harness owners. Launcher adapter fixtures are
captured from those reads. Tests cover wrong owners, branch exclusion, nested
delegations, split stores, symlinks, stale content, independent source failure,
null quantities, schema/iteration qualifications and read-only saved branches.

The final focused store/ownership/import-layer/footprint run passes **54 tests**.
After tightening capability discovery to advertise history only on the public
owner routes, its four-file follow-up passes **22 tests**, including all six
real Steer/Stop + persisted-history round trips across native worker, isolated
compute and in-process execution. Each closes its host, reopens the service,
and reads history with a worker factory that fails if invoked. Changed
production modules pass ruff; footprint/private-import allowances are unchanged.

Applied killing mutation: remove projected content from
`References.historical`'s signature. The changed-result test fails with
`DID NOT RAISE SubagentError`. Restoring the signature returns the suite to green.

The complete fork landing run selected **1,079 files**, with **12,237 tests
passed, one failed, one setup error and 28 skipped** in 653.3 seconds. The PM
slow-exit fixture requires Python 3.14 and this workstation's explicit runner
is 3.13.15; unchanged base `28b444fc75` reproduces the same setup error. The
machine-wide orphan-scan positive control also failed in that full run; its
eight tests then pass on both unchanged base and this candidate. Both files
already have active entries in the fork-hygiene queue. No clean whole-suite
result or relaxed requirement is claimed.

Live UI QA remains deferred by owner agreement until after Step 6; Step 7 owns
that complete smoke. Steps 6 and 7 require their separate approvals.
