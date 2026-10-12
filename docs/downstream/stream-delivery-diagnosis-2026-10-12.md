# Session commentary and turn-start diagnosis — 2026-10-12

PR #8 is merged at `b989d262e5`; its Fork gates run `38313749609` passed.
Those gates cover selected fork claims, not the whole regression suite.
The source baseline for this diagnosis is `56777bc3e5`.

## H03: confirmed delivery race, submitted upstream

The unchanged Session API file passes 39 tests alone. A bounded 30-case probe
reusing its commentary scenario produces 29 passes and one failure: the wire
contains sequence numbers 1, 2, 4, 5, 6. Commentary event 3 was stamped but never
delivered. The final answer and the separate Responses stream are intact.

Owner: `gateway/platforms/api_server.py::_SessionEventQueue` and
`APIServerAdapter._handle_session_chat_stream`. Worker callbacks schedule their
puts onto the loop; terminal events and EOS put directly. On Python 3.13, an
executor Future may finish before `asyncio.wrap_future` registers its callback.
Awaiting the already-complete wrapper does not yield. Direct terminal puts can
therefore reach EOS before the scheduled worker puts. This affects commentary,
text deltas and tool events, on both successful and failed turns.

A real `ThreadPoolExecutor` that returns only after its submitted work finishes
makes this interleaving deterministic. On current upstream `ee36aed5adc7`, the
new endpoint test reports two failures (already-finished success/failure) and
two passes (ordinary scheduling). No callback, assertion or timeout is weakened.

Candidate: [codex/session-sse-order](https://github.com/ArcadiaLabsLLC/hermes-agent/tree/codex/session-sse-order),
commits `879c2a31cd` and `addf508ad5`, then upstream refresh `2426b8dc24`
(base `b23600860f82`). All queued events and EOS use the existing
loop scheduler; sequence stamping happens on that loop. There is no second
buffer, blocking acknowledgment, lock, retry or Eternia import. The existing
live-bot direct writer and Responses writer are unchanged.

Qualification: 184 distinct tests across the Session API, API server, ordering,
keepalive, active-work drain and turn-boundary files pass without retries. The
four ordering cases also pass after fixture registration cleanup. All 12
`scripts/check --base ee36aed5adc737db49c94316ffeb97d3fb8dc099` checks pass.
The exact original red is in the fix commit body. Local proof uses Windows /
Python 3.13.15; supported Python 3.14 remains for upstream CI. After the refresh,
ten quality checks pass together; shebang file-read and lazy-deps process-start
errors clear on individual reruns. The latter reports Windows paging-file
exhaustion. Code health has zero blocking findings and zero advisories.
No full upstream suite claim.

Existing-work search found [upstream PR #89748](https://github.com/NousResearch/hermes-agent/pull/89748):
the same executor-completion race on `/v1/runs`, using a bounded blocking
acknowledgment. It does not cover the Session API endpoint reproduced here.
The operator authorized submission after this endpoint distinction was verified.
[Upstream PR #137460](https://github.com/NousResearch/hermes-agent/pull/137460)
contains the focused Session API fix, references #89748, and records the
reproduction, before/after results and local validation limits. No separate
comment or issue was posted. The candidate is **not on fork main**. Upstream
CI run `38317839373` is `action_required`: maintainer approval is needed before
the workflow runs. It is not a passing CI receipt.
The operator subsequently authorized carrying the fix into the fork.

### Fork carry qualification

`codex/session-sse-carry` carries the two source/test commits, without importing
upstream-main's unrelated commits. The only cherry-pick conflict is the older
`Dict` annotation; the reviewed implementation remains the same. The exact
upstream regression test is retained. On fork base `fd5a712977`, it reproduces
**two failures / two passes** before the carry and four passes after it.
The six API files pass **184 tests** without retry. Footprint and carry-tool
checks pass; the source patch reverse-applies against the pinned PR head.

The fork's carry checker itself translated patch bytes through Windows text
stdin and falsely reported drift. Its existing real-Git controls now use LF
and CRLF histories: the LF clean-carry assertion failed before the binary-pipe
repair, then all **57 controls pass**. This tooling repair is fork-only.

The footprint records one additional upstream file (+23/-23), pins PR #137460,
and names upstream adoption as the retirement condition. This is a prepared
carry, not a claim of upstream acceptance or a completed fork landing gate.

## H01: still open, no speculative runtime change

An instrumented copy of the original slow-turn scenario, alongside eight of
the existing H01 files with eight workers, passes: 86 tests, one existing skip,
65.0 seconds. It retains the original six-second start and 3.6-second end
bounds. This run omits the two-roots file and the original fast-turn prefix;
it is additional evidence, not a reproduction of the original entire schedule.

The scenario subscribes without fold capabilities and waits for the fallback
core carrying both the named start event and `running_work`. Current Launcher
can use `persona_chat_turn`; this test does not prove that path either way.
The next failing run needs the received-frame timeline and build/yield receipts
at the deadline. Do not raise its deadline, classify it as TLS, or retire it
because the latest run passed. Production code and the original test are unchanged.

Follow-through on `4104e06401`: the complete original ten-file selection,
including both chat-lane scenarios and the two-roots file, passes **96 tests /
one existing skip** with eight workers in 156.3 s. Only failure-message
instrumentation and INFO logging were added temporarily; assertion deadlines
are unchanged. The command-level file cap was 600 s, respecting the two-roots
file's declared allowance. The temporary instrumentation is retained outside
the checkout and removed from the source tree. H01 remains unresolved.

## H08: CLI spelling condition still exists

The original condition is recorded in
`docs/agent-runtime-harness/planned/upstream-reds-2026-10-07.md`: the relay
test compares the launcher basename case-sensitively, rejecting `hermes.EXE`.
A native Windows probe invokes the original upstream test body with the same
delivery stub and two resolver outputs: `hermes.exe` passes; `hermes.EXE`
fails at that exact assertion. Result: **one passed / one failed**.

The local XPASS therefore does not prove that the inherited condition was
fixed. Correct or reclassify the spelling assertion before retiring the broad
Windows marker. No test assertion or marker was changed, and no new upstream
PR was submitted for this finding. The temporary probe is retained outside
the checkout. This supersedes the earlier proposed unconditional retirement.

## Retained local receipts

Logs are in the shared worktree parent, not operator storage. Temporary probes
are investigation scaffolding, not new default-suite gates.

| Log | SHA-256 |
| --- | --- |
| `stream-delivery-commentary-probe.log` | `02a731a7c6e6410e688ad349f25fe5f91e629f285a53b8883351d05cdd66e36e` |
| `session-sse-upstream-red.log` | `fe35ad7e04d8cea921226d683baf6dfcba899f1dc6f55a91964275a10e7bd847` |
| `session-sse-upstream-green.log` | `b47ceb7b23270089cd74e30537ab7e12d90de680a7b096197d856e214f429a38` |
| `session-sse-upstream-adjacent-green.log` | `4a4ab52b9f2434b345530f3f22b36487db02ad3bae4527cf989440ac818061f8` |
| `stream-delivery-start-loaded-probe.log` | `d96282cb81f777c787bd7ce7307bebb7453f9d9da67237fb354e60018c78689a` |
| `triage-h01-full-prefix.log` | `38546471d5bc80028eda8c982e36e84cb6b05bfac93bf2f08df7e3fbdf82088a` |
| `triage-h08-case-control.log` | `177b298c4d920d728bf855a346dc6f3b8499f1a4cd8c0bd85e1043a5382f4b0f` |
