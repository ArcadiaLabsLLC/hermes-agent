# Operator Stop audit — 2026-10-06

The console's continuation sends omit `session_id`. Admission therefore uses
instance/persona scope before the worker resolves its operator root. Stop
previously reopened that receipt under the session scope and failed
`turn_request_conflict` before interrupting the worker. The Launcher collapsed
that refusal into a changed-conversation message.

`operator_execution.operator_execution_reservation` now proves the exact
session/turn/instance join from the canonical journal and preserves immutable
admission scope and payload fingerprints. Missing or conflicting evidence is
refused. No pointer guessing, worker replacement or provider workaround is
involved. The native cancellation owner remains upstream `InterruptScope`.

`serve_rpc.operator_conversation.status` validates the same target and reads
the execution's existing receipt and terminal journal without loading a
transcript, adding Stop intent or interrupting an owner. Launcher performs one
Stop write and bounded status reads; completion can win a late Stop, and lost
acknowledgements never prove cancellation.

## Verification

| Check | Result |
| --- | --- |
| Whole-tree fork gate before status confirmation | 891 files; 11,486 passed, 108 failed, 5 errors, 49 skipped; 733.2 seconds |
| All 31 failing files on clean pre-fix `4bd066983f` | Exact same 113 failing/error node IDs; zero branch-only failures |
| Final execution, attachment, work links, RPC manifest and authorization checks | 176 passed across 8 files, including 11 execution recovery checks |
| Provider client cancellation, interrupted API calls and stream socket abort | 8 passed |
| Post-rebase frozen-home, tombstone and upstream-footprint checks | Passed; CLI/payload contract checks also passed |
| Final native/Python–Dart integration | Both tests enabled and passed; console send omits session, loses a Stop acknowledgement, then confirms settlement through the actual Launcher Stop binding |

The whole-tree receipt precedes the narrow status-read addition. Final focused
verification covers its dispatcher, target validation, manifest and client
join. No gate limit, waiver or baseline was expanded.

Reverted killing controls: `restore_session_only_stop_lookup` caused two
native failures and `native_session_only_lookup_cross_language` caused one
integration failure; `status_read_requests_stop` failed the read-only status
test; `omit_exact_execution_confirmation` failed both the Launcher binding
test and its native integration. The Launcher diagnostic control
`collapse_execution_conflict_to_changed` failed two adapter tests.

After rebasing onto `274eb9bb6c`, the legibility-floor violations and duplicate
helper keys also reproduced on that unchanged main. Five stale live-canon
line citations reproduced there, including the additional
`05-chat-turn-lane.md` cite of `mission_chat_phases.py:62`. These residuals
remain in the fork-hygiene queue; this repair does not waive them.
The changed-line mutation inventory also refuses before listing claims:
`ctp5-deferral-decided-after-the-build-worker-starts` cannot find its source in
`stream/build.py::_full_core_batch_frames`. The identical configuration error
reproduced on unchanged `274eb9bb6c`; the manual killing controls above ran.

Stage C reported `app_not_attached`. Automated checks do not establish live
click-to-provider latency or acceptance in a rebuilt Launcher. The separate
Stop appearance delay still waits for running-work projection on the Launcher
side; see `EterniaLauncher/docs/mission_control/evidence/composer-stop-audit-2026-10-06.md`.
