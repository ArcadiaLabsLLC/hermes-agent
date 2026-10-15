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

Qualification: the original Windows / Python 3.13.15 reproduction and
checks are retained below. The current upstream PR head `2426b8dc24` is now
qualified on Windows / Python 3.14.7: **184 tests** across all six API files
pass in one run without retries, and all **12 quality checks pass together**
against pinned base `b23600860f82`, with zero health findings. The original
red is recorded in the fix commit body. No full upstream suite claim.

Existing-work search found [upstream PR #89748](https://github.com/NousResearch/hermes-agent/pull/89748):
the same executor-completion race on `/v1/runs`, using a bounded blocking
acknowledgment. It does not cover the Session API endpoint reproduced here.
The operator authorized submission after this endpoint distinction was verified.
[Upstream PR #137460](https://github.com/NousResearch/hermes-agent/pull/137460)
contains the focused Session API fix, references #89748, and records the
reproduction, before/after results and local validation limits. No separate
comment or issue was posted. The fork carry is qualified below. Upstream
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
and names upstream adoption as the retirement condition. Fork source commit
`ce3609b4a8` carries the fix; `30f3aa4aa9` and `a359a8f8bc` qualify the
binary carry-checker pipe and its host-independent controls.

The landing gate on `a359a8f8bc`, after merging fork main `c81d716323`,
passes **13,269 tests in 1,088 files**, zero failures/errors, 60 skips,
**zero reruns, straggler retries or abnormal bundle diagnostics**. Nothing
was skipped by the green cache. The receipt records 76 bundles, 13 solos
and two known-red files run once; elapsed time 541.6 s (terminal). Selection
covers 1,029 fork files and 59 reached inherited files; the standing six
upstream exclusions and three idle-box files remain excluded. This is the
fork landing gate, not the entire upstream suite. The command was
`scripts/run_tests_bundled.sh --since c81d7163230705cb2a1d664e9074d0f12a605ec4 --file-retries 0 tests`.

Python 3.14.7 comes from a lane-owned environment built by the existing PM
owner, with `python -m pm.build_env --source . --out <fresh-env>
--python <supported-python> --cache <lane-cache> --group dev --group test
--extra all`; `HERMES_PYTHON` selects that interpreter in the test wrappers.
No shared interpreter was mutated. Reverting only the API source restores
the same two ordering failures on 3.14; restoring it passes all four.
The untouched H04 slow-exit file also passes in this environment. The first
minimal environment lacked the API dependency `aiohttp`; its collection
error is an environment setup receipt, not a killing control.

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

On 2026-10-13, the same ten-file selection on Python 3.14.7 passes **96 tests /
one existing skip**, without retries, in 195.5 s. The cause still does not
reproduce. The existing test recorder now retains its reader exception and
the last 32 received frame summaries when its wait fails. It keeps the same
transport, subscriptions, assertions and deadlines; no runtime path changes.
Forcing only the start-wait allowance to zero exercises that reporting path:
one expected failure includes the received hydrate/ack timeline. Restoring
the allowance passes both file tests. This verifies diagnostics, not a
killing mutation for the unresolved runtime intermittent.

### Reproduced turn-presence delay and scoped repair — 2026-10-13

A separate controlled probe adds the real `conversation_request_assembled` /
`conversation_provider_returned` markers around the scripted provider dwell.
With the current client fold declaration, both an explicitly bound snapshot
worker and the supported in-process mode miss the unchanged six-second
running-row bound. Both marker-free controls pass. The mixed batch demotes
before publishing; its core waits behind the provider window. This corrects
the D2.06 DROP verdict for the existing turn-presence queue row. It does not
establish the cause of the older marker-free H01 intermittent.

The repair extends the existing `running_work_frame` publication in
`StreamSession.flush` to start and end transitions. It reads once per batch,
before the heavier projection, and leaves the event watermark and snapshot
yield rule unchanged. There is no new frame type, read model or client path.
Two journal-backed regression cases fail on the old implementation (one and
two starts in a batch produce `delta` before `running_work`). The repaired
current-client probe passes all four cases; 32 focused tests pass without
retry across presence, turn sections and the original gateway measurement.
Existing end, unreadable-store,
quiet-batch and declaring-client checks retain their safety assertions.

## H08: CLI spelling condition still exists

The original condition is recorded in
`docs/agent-runtime-harness/planned/upstream-reds-2026-10-07.md`: the relay
test compares the launcher basename case-sensitively, rejecting `hermes.EXE`.
A native Windows probe invokes the original upstream test body with the same
delivery stub and two resolver outputs: `hermes.exe` passes; `hermes.EXE`
fails at that exact assertion. Result: **one passed / one failed**.

The local XPASS did not prove that the inherited condition was fixed. The
repair now supplies the CLI resolver result and checks that the handler uses
that exact path, with `hermes`, `hermes.exe` and `hermes.EXE` beneath a directory
containing spaces. Native launcher selection retains its existing tests.
[Upstream PR #137478](https://github.com/NousResearch/hermes-agent/pull/137478),
commit `458dd40910`, changes only this test (+6/-3). Before the assertion repair,
the uppercase case fails and the other two pass. On Windows Python 3.14.7 the
three repaired cases pass; delivery plus launcher-selection files report
31 passed and one unrelated reported-turn timeout. That timeout reproduces
alone with the unchanged upstream test file in the same environment. All 12
upstream quality checks pass; zero health findings. No production change.

The fork candidate carries the exact patch and removes only this test's broad
Windows marker. The unrelated timeout marker stays. H08 joins H11 in
`codex/triage-followthrough`: both touch the shared test-fixture chain, so their
whole-tree qualification belongs to the release batch. The completed batch
qualification is recorded below; the upstream PR remains open, not accepted.

On the paired fork candidate `256c151c76`, supported Python 3.14.7
qualification passes 56 tests across relay delivery, footprint, environment
registry and fixture-boundary files (three existing skips and one existing
xfail). The original
H11 20-file bundle passes 204 tests, ten skips and two existing xfails,
with no reruns. These are scoped results: removing a marker under
`tests/_downstream/` joins H11 in the owed session-chain release batch.

## H12: shared sleep override removed; broader qualification remains open

The retained 20-file neighborhood on `34d27ed88d` reproduces a process death:
pytest's 30-second timeout stops the first Codex Responses test during agent
initialization/plugin discovery. A terminal cleanup thread is simultaneously
running configuration work. This is the maximal surrounding selection, not
the exact original bundle boundary: the old planning cache was not retained.
The runner misattributes setup death to the previous completed file; its
retained output identifies the active Codex test. That tooling defect is filed.

The native Codex test fixture replaces process-wide `time.sleep`, so every
background thread loses its pacing. The agent conftest already owns zero-delay
retry backoff. Native candidate `057b9339c0` removes the redundant override and
adds a behavioral sleep control, with no production changes. Reinstating the
old fixture makes the control fail (a 10 ms request takes approximately
0.0006 ms). Removing it passes all 70 native file tests on Windows Python
3.14.7, without retry; all 12 upstream checks pass against `63d0b9412002`.
The fork removes the downstream test's import of that same deleted fixture;
both files now use the existing agent conftest.

The native branch `upstream/codex-retry-isolation` contains one commit on pure
upstream history. GitHub refused PR creation for the authenticated account on
2026-10-13; no PR number or acceptance is claimed. Preserve the prepared body
and branch for submission when that permission is available.

The broader candidate neighborhood also exposes live OpenRouter metadata reads
in neighboring pruning/rotation tests. Those HTTPS reads time out before the
Codex file; rotation did so before this repair too. This is separately filed
test-isolation evidence, not proof that the sleep repair regressed the
runtime, and not a clean neighborhood qualification: its final exit is 1,
with 206 passes and one timed-out pruning file after three bundle deaths.
The repaired Codex file passes 70 tests and its downstream consumer passes 12
when reached. On Python 3.14.7, the same neighborhood ends with 212 passes,
but an earlier metadata-read timeout still requires re-bundling. The unchanged
pruning file passes all six tests alone on the baseline; that intermittent
network dependency remains open. The original process-death
incident cannot be attributed exclusively to this override from the old log.

## Combined candidate qualification — 2026-10-13

Final candidate `911275e641` passes the fork integration gate on Python 3.14.7:
**12,717 passed, 56 skipped, zero failures/errors**, 1,032 files in 546.7 s.
The receipt has no bundle diagnostics, retries, re-bundles or cache skips.
Both H01 file tests, all 70 native Codex tests and all 12 downstream Codex
tests pass on their first attempt. The citation gate reports no new failures
and no stale waivers (21 existing waivers).

The intermediate presence candidate `0f525bd2b3` failed the stream bookkeeping
test because it removed the existing optional-event guard. `911275e641`
restores that guard; all 13 coalescing/presence tests pass, followed by the
clean full fork gate above. The failed receipt is retained below.

This gate uses `--since 3c2ba45c4bf82fced3440cf59a05c66b898825c1`: every fork
file plus the three inherited files reached by the later edits. No shared
fixture changed after that base. It supplements, rather than replaces,
the H08/H11 whole-tree qualification on the isolated Windows Actions runner:
[run 38352941865](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38352941865),
pinned to `3c2ba45c4b` against `958e574c2e`. The temporary proof workflow is
on its own branch and is not part of the implementation.

That four-worker run reached the command's 110-minute cap after reporting
3,853 of 6,486 files: 41,043 passes, 768 skips and 238 expected failures,
with no failed/error result reported in that partial log. The recorded modes
are 3,842 bundled files and 11 solos. This is incomplete qualification, not
a whole-tree pass; the interrupted run produced no final ledger. The original
log is retained in the run's `shared-fixture-qualification` artifact and its
digest is below. Source and interpreter are the pinned values above.

[Run 38364979651](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38364979651)
repeats the same selection on the same source with a 220-minute command
budget, sized from the measured four-worker throughput. Individual test
deadlines, assertions, exclusions and the existing runner are unchanged.
The proof-only workflow also disables inherited shell `errexit` around the
pipeline so a timeout records its exit code before artifact upload.
That run exited 124 at its 220-minute command cap. It reported all 6,486
selected files, but recovery was still running: 58 files' latest reported
result failed and no final ledger was emitted. Thirteen of those files show
the real-store/subprocess guard refusing a call, nine show strict expected
failures that now pass, and nineteen have timeout banners. These categories
are observations, not causal attribution or proof of baseline failure.
The artifact retains the exact source, interpreter and exit code, plus the
original log (digest below). This was hosted Windows, not the operator's PC;
the result cannot be attributed to the operator's antivirus configuration.

[Run 38426498916](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38426498916)
compares the exact 58-file selection through `scripts/run_tests.sh` on both
pinned revisions, with the same PM setup and two workers. Individual test
deadlines and assertions are unchanged. It records the runner-image version
and preserves both outcomes, including failed jobs.

The direct comparison completed on identical `win25-vs2026` image
`20260925.250.1` and Python 3.14.7. The baseline has 46 final failing files;
the candidate has 48. Every one of the candidate's 154 failing/error node IDs
also occurs among the baseline's 155. The one baseline-only assertion is
`TestWidenedPruner.test_squash_merged_tree_is_reaped`. The update-routing gate
has the identical violation list on both: `hermes_cli/interpreter_abi.py`
is imported by `hermes_cli/venv_sync.py` but missing from `e2e_upgrade` routing.

The candidate-only failing files are timeout-shaped, with no new assertion:
`test_install_ps1_native_calls.py` dies while waiting for `_stage` in
`test_rerun_parks_local_work_and_pins_only_branch_commits`, and
`test_kanban_descendant_scope.py` dies while waiting for a descendant in
`test_terminal_descendants_cannot_mutate_even_after_task_is_removed`.
The kanban file also times out in the baseline's first attempt, then passes
its serial retry. The installer file passes the direct baseline attempt.
Neither test's deadline was widened; assess the original-group comparison
before concluding the timeout difference is unrelated to this repair.

[Run 38427670480](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38427670480)
also compares the original collection context for the 106 files whose latest
mode was recovery. Calling the existing `assign_bundles` on the original
6,486-file selection reconstructs 1,632 cold groups and eleven solos. The
selected 86 groups contain 344 files; re-planning that subset reproduces every
original group exactly. Both jobs use `scripts/run_tests_bundled.sh`, the
original four-worker count, no result cache and no changed test deadlines.
This comparison supplements the original run; it is not a new full-tree pass.

The candidate completes all 344 files in 1,863.6 s: 4,184 passed, 61 failed,
95 errors and 188 skipped. Its ledger retains 70 original diagnostics,
including 21 abnormal exits; recovery does not make this a clean first attempt.
All eight final timeout files also time out on the direct baseline comparison.
The two direct-comparison timeout differences pass this candidate run; the
installer still needs a serial retry.

The grouped baseline exceeded both configured limits and was cancelled. It
produced no baseline artifact, and GitHub returned no job log after cancellation.
No baseline result is inferred from that stall. The continuation,
[run 38439426620](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38439426620),
checks the 36 unmatched cases on the same pinned baseline and runner image.
Three bounded selections preserve their 15 original four-file groups, verified
through the existing planner. The command writes directly to a log file; no
test deadline, assertion, exclusion or runner implementation changes.

Together, the completed comparisons reproduce **all 159 final failure/error
IDs** and **189 of 191 original diagnostic IDs** from the candidate. The
remaining two are first-attempt timing failures that pass isolated recovery:
`TestRunConversation.test_redirect_from_input_thread_cancels_live_model_request`
misses its two-second entry event while plugins initialize, and
`TestClarifyEagerReseed.test_double_clarify_boundary_reseed_chain` checks the
second seed after a fixed 50 ms drain. Neither assertion reproduced on the
baseline; the run-agent group's baseline first attempt instead times out in
the preceding rotation test and then passes after re-bundling.

These remain unresolved findings, not claimed fixes or proven baseline
reproductions. Between `958e574c2e` and `3c2ba45c4b`, all production files,
both test files and their fixture owners are byte-identical. A collection
diagnostic through the canonical runner confirms the new backup fixture is
absent from both cases and present in the backup control. That diagnostic
executes no test bodies; its collection-only exit is not a passing test receipt.
The temporary inspection plugin was removed. Their queue row retains the
receipts and calls for completion-based synchronization and reliable cleanup.

The batch therefore lands the qualified H08/H11 repairs, the H12 fixture carry
and the bounded H01 presence fix; it does not retire the wider Windows
timing/isolation findings or certify a clean whole suite. The final fork gate
above remains 12,717 passed without retry. After merging current-main evidence,
the nine tooling files pass 163 tests, with eleven existing skips; citation
checks have no new failures or stale waivers. No production bytes changed
after that integration gate. The proof workflow and selection files remain
on the temporary branch and are excluded from the implementation.

## Retained local receipts

Logs are in the shared worktree parent, not operator storage. Temporary probes
are investigation scaffolding, not new default-suite gates.

| Log | SHA-256 |
| --- | --- |
| run `38439426620`, part 1 `gate.log` | `d66f4b8821b2322273c7f26154df372fde4481de81e2ff8519a225a7e385f47b` |
| run `38439426620`, part 2 `gate.log` | `1b742920aa7ecdafe96f8fb73f69503b769c6311677234ee4dde49f2d33f4de4` |
| run `38439426620`, part 3 `gate.log` | `800935baf32fb96e0305862e45f7843193380730c3dc45ecd2e544f3ea57cb6a` |
| run `38427670480`, candidate `gate.log` | `0f1b7c1e04fc7d9d7b7f804ae5afd98b608186776aec572ace05a1bc76e6cfae` |
| `triage-fixture-exposure.jsonl` | `42bd97d5eea58c2ac864ede993c3146c388e2b4eb044245b19b4c891f30d3f6f` |
| run `38426498916`, baseline `gate.log` | `98691f0823c21f8be50e5b42be3d64ee4bffbb6410b488fe982e7d4cf54a08d4` |
| run `38426498916`, candidate `gate.log` | `efa0f145854428a90a4900635e4ea577e4b35248803d43e876ecae6614356c43` |
| hosted run `38364979651`, `gate.log` | `ea93dd491f400e8c2caf1c43871fe3cebfd0a2eee48c8d4db4c456a38b6f618d` |
| hosted run `38352941865`, `gate.log` | `85f31c6d01fb900370c7c1c3cf2345b5368ba2068b42995aa0d503f42c02ee6e` |
| `triage-final-integration-gate.log` | `1741861b0185e3195ccdc1069f89514542b97f655c5088981262e08fd31d55fe` |
| `triage-final-integration-doc-cites.log` | `e9d0b6b8ebdbc18bff57d8a4fe2985f15951993898edc40df38f2d5e2607faf4` |
| `triage-presence-integration-gate.log` | `ca9ab961b29d45b1737edaff97e980735ef371cc295f7c457ea8cf4eaf42525b` |
| `triage-h01-presence-guard-green.log` | `5010c3feb4be8e37d7cbe0b77a66c53c8e3f4f3a9f3b06e696a32c81b7554c47` |
| `triage-h01-start-overlay-final.log` | `77ae456ee54277bb2e3435b82a62bb24180c2296821c907c4cdeaa909c2df91b` |
| `triage-h01-start-overlay-red.log` | `eedf95b96c744544b4ea0fc66434379a67f5b944e9b14070db964c981951a895` |
| `triage-h01-current-client-bound-probe.log` | `da9affb89a216e96bdd00dc280807e9ca02c51649ff8095491773d3e18b7d4ee` |
| `triage-h01-current-client-repaired-probe.log` | `9fb25faa79a329c1cfcdf3153d72819b225e2fef78dc53da6ade8e5910e06266` |
| `triage-integration-gate.log` | `3d4e2d3f9fb2747afb42acc3eb3ef3c7c391ff1baf8ab36dbfb355ae158a89f8` |
| `triage-integration-doc-cites.log` | `e9d0b6b8ebdbc18bff57d8a4fe2985f15951993898edc40df38f2d5e2607faf4` |
| `triage-h12-supported-neighborhood.log` | `ba03a3860aa9b5449d31e19c5928bec60cf44f5bdc4d128e8eb86ccbb1e03b0a` |
| `triage-h12-catalog-baseline313.log` | `b7f883f3a07992501436892b9f9b020654582f33e1a5b85ff49c249aaf00ec1a` |
| `triage-h01-diagnostic314-20261013.log` | `894a9271cfdb2454235209524d9abb814c9c68ab36073990363b50c6d3fad811` |
| `triage-h01-diagnostic-control.log` | `7683a7ca11302fd40fa82c01abbdeb9641a62d37ab18517c2453c1d3b733bf2a` |
| `triage-h01-diagnostic-green.log` | `2c826fa3eb5f5ddb3f344381411beebe7cdb5d013dee38ebf0757724322d89d9` |
| `triage-h12-neighborhood313-20261013.log` | `f555653c2b87fe35bbb81c3d4878c54ea690abe873a6256ebb243d3d1ce9cdc1` |
| `triage-h12-final-mutation-red.log` | `21e1ee68809b908c8757f13e32706d9c468d4809ea84a296123783b96287b58e` |
| `triage-h12-final-native-green.log` | `f260f18180829f795fc6f20c6398c08ad711aee0d496ada682f22876a82d080d` |
| `triage-h12-final-check.log` | `32a77fa7cad034e20fbaa2e53c01256d70f6bc13744bc58da775ee4c5c554b78` |
| `triage-h12-final-neighborhood-green.log` | `f6606ac5b5148b108c2b0c316a77e4cfeb34131e5d76429c795f51615fbdda35` |
| `stream-delivery-commentary-probe.log` | `02a731a7c6e6410e688ad349f25fe5f91e629f285a53b8883351d05cdd66e36e` |
| `session-sse-upstream-red.log` | `fe35ad7e04d8cea921226d683baf6dfcba899f1dc6f55a91964275a10e7bd847` |
| `session-sse-upstream-green.log` | `b47ceb7b23270089cd74e30537ab7e12d90de680a7b096197d856e214f429a38` |
| `session-sse-upstream-adjacent-green.log` | `4a4ab52b9f2434b345530f3f22b36487db02ad3bae4527cf989440ac818061f8` |
| `stream-delivery-start-loaded-probe.log` | `d96282cb81f777c787bd7ce7307bebb7453f9d9da67237fb354e60018c78689a` |
| `triage-h01-full-prefix.log` | `38546471d5bc80028eda8c982e36e84cb6b05bfac93bf2f08df7e3fbdf82088a` |
| `triage-h08-case-control.log` | `177b298c4d920d728bf855a346dc6f3b8499f1a4cd8c0bd85e1043a5382f4b0f` |
| `session-sse-fork-red314.log` | `19c239feacf98492458890ade8ba4657cf509a2b7dcdc0c3d3452fdb70a9a03c` |
| `session-sse-supported-green314.log` | `03dcffedc3a8febce267129391a8b1e426c5bda50ce07847a418f369453eeeae` |
| `session-sse-fork-landing314.log` | `fad7f86c2dd06d30f098379ab4e5cefd6145d932dc07ad66c04eaf961ddaa82a` |
| `session-sse-upstream-green314.log` | `072821570bff8444434acbee087872400ff6bc48702662839e2401f5f0593f54` |
| `session-sse-upstream-check314.log` | `2052f2b2b0462c1528f29878f6769c946565c3bf20fc40be27133916e7f36357` |
| `carry-check-lf-red.log` | `cdd463b624eb6d89fcb6a0c9c42656152180d9a70c5eaf6ccb41031db790e020` |
| `relay-cli-upstream-red.log` | `cd89be74ed4a843072feedf43e0f3312c364c09ebb3001dd57b3fe862ee76add` |
| `relay-cli-upstream-green314.log` | `1b73917bcdaf6ea3f7552331168323fe2669dd18636604c732a9c681a80f6ee8` |
| `relay-cli-upstream-baseline314.log` | `269b56bea6841a1abccb85f417d8d8ae66f4dce170dc5861874d67696bc82036` |
| `relay-cli-upstream-check314.log` | `78a5be93d5f219b036a95392e01ca5b83020328542f8ccdb6dd50392f823cd3d` |
| `triage-batch-focused314.log` | `ed8edf795f65620df9bb2715f0bfe9d212f9ba276e80f9bb403c094528144a46` |
| `triage-h11-batch-green314.log` | `76240889e0ece4b9331dd0b6fcc80a62e8b982cefee6e9ec1ba6fb4de878703e` |
