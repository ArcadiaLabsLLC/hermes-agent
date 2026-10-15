# Native handler anchor contract — 2026-10-07

Frozen base `40ebb8da6428b4349131ef2676434a6229ceffa0` joins claim/main `f1d285e4faf09aec1e6b973e307c439201248d0c` and reviewed runtime `8f235b8e320324f928d752b1eda9197013a0234f`. No advancing-main integration during proof.

`TurnPhaseMarks.snapshot()` already contains `anchored_at`, the ISO microsecond handler-entry wall stamp. Earlier packet wording referring to `dump()` and saying snapshot lacked it was incorrect. Before this repair the public timing projection omitted the stamp; no second wall clock input was needed.

| Native carrier | Exact field | Identity |
| --- | --- | --- |
| v2 start frame | `turn.start.anchored_at` | `turn_id`, `client_message_id` |
| terminal envelope | `chat.final.timing.anchored_at` | turn/client plus resolved instance/root |
| `runtime.operator.conversation.status` result | `timing.anchored_at` | validated operator attachment and admitted `turn_request_id`; journal client, sanitized turn and root must match |

One sanitizer accepts only bounded timezone-qualified ISO strings, copies the handler stamp without clock conversion, and omits invalid/absent stamps. Existing numeric keys retain ordering; anchor is appended. Queued admission acknowledgement has no anchor. Old records remain absent. Replay keeps the original journal stamp; another request/root/installation cannot borrow it. Handler anchor excludes queue delay; emitter TTFT starts later and cannot replace it. Legacy emitter callers with no marks omit anchor.

The status path remains a read of the exact admission/journal, without transcript/provider loading. Terminal settlement uses the existing snapshot-to-timing path. No upstream file edits or extra anchor clock.

`tests/fixtures/native_handler_anchor.json` is a bounded public packet projected from an actual real-handler run with deterministic provider transport, actual SQLite/journal, accepted serve lane and native operator RPC, not handwritten stand-in envelopes. The full capture is `outputs/native-handler-anchor-wire.json` in the coordinator workspace. Running status is observed from inside provider execution; terminal status follows handler completion; same request replay queues no new job.

Focused acceptance: named anchor file, existing timing block and operator recovery files, plus three exact phase anchor/persistence nodes. Killing controls substitute a later emitter stamp, remove journal/admission identity guards, and allow a naive ISO stamp; all must fail before restored green. No full suite or main landing. Launcher C020 may consume only these tested carriers; resident/writer R011 follow-on remains pending.

Acceptance receipt: 70 focused cases green; after three new malformed/absent emitter cases, restored anchor file 25 green. Five touched Python files Ruff green. Clock substitution: 1 red; identity/admission fence removal: 3 red (turn, root, missing admission), 2 passing negative controls; naive timezone acceptance: 1 red, 10 passing negative controls. Source restored byte-for-byte after each mutation. Queue removes only this producer claim; standing-stream evidence/owner and R011 remain pending.
