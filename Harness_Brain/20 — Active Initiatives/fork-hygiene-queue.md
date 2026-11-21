---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue

## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)

- **`TASK-HERMES-TEST-ISOLATION` — Agent engine tests: a run never hangs, leaks onto your machine or breaks on Windows** · task: hermes-test-isolation · 2 subtasks on 2026-11-16 (2 deferred; w1115e-ts closed FH-SEAL-LEFTOVER-THREADS-AND-CHILDREN DONE 3c2769a425); was "3 subtasks on 2026-11-16 (2 deferred, 1 ready: `FH-SEAL-LEFTOVER-THREADS-AND-CHILDREN`, scoped to its four leakers by review w1115e.18)" · review w1118a.66: passed `FH-FU-THE-SLOT-SETUP-SHELL-TESTS-FAIL-ON-WINDOWS` (READY, REQUIRES windows, test-only) · DEFERRED 2026-11-16: every open subtask is deferred (FORK-LANE-HOMES-REAL-PATH; FORK-P0-VALIDATED-SUITE-FROZE closed stale 2026-11-19) · waits: `FORK-LANE-HOMES-REAL-PATH` · reopened 2026-11-15 (w1115e-h8): its DEFERRED status was stale — FH-REKEY-CENSUS-BRAIN-WORKTREE-RED-ON-WINDOWS (READY 2026-11-13) and FH-AGENT-TESTS-READ-THE-REAL-INSTALL-FACTS (READY, reviewed w1115e.5) are open under it · reopened 2026-11-12: owner — deferred-task review, batch 1: "Yes, as recommended" — five of its rows are ready, two of them Windows test failures · was dEFERRED 2026-11-10: every subtask is deferred · unblocked 2026-11-10: owner deferral triage ("rest of the triage is good") reopened `RT-WRITING-COMMAND-HOME-SKELETON`; 9 deferred rows archived · handoff 2026-11-09: w1109a-hm-iso closed FH-LIVE-GUARD-PATH-READ-AS-SPAWN (3e0292cfe4) and FH-WORK-STORE-FIXTURE-LOST-IN-ONE-PROCESS (147d9316f6, a pytest 9.1 Dir-node conftest bug fenced by regrouping args); the two READY rows left (RT-WINDOWS-BASELINE-REGRESSIONS, FH-PYTEST-HOME-BIN-LEAKS-INTO-USER-PATH) need a Windows box, their rows carry the steps · handoff 2026-11-10 (w1110a-org): recounted — `FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS` (READY, filed today) was uncounted, and `FORK-NEMO-PYD-OLD-DELETE` (delete the retired shared test venv) moved in from embedded-hermes · handoff 2026-11-10 (w1110b-hm): closed FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS (137f34928f: nothing waited, a CPU-bound closure walk that re-parsed every installed METADATA per walk; memoized, reproduced timeout at a 1/16 core share now passes); READY left: FH-GUARD-PROBE-SCAN-RED-WINDOWS (a Windows box) · handoff 2026-11-10 (w1110d-hm2): closed RT-WRITING-COMMAND-HOME-SKELETON (2a10c0de0c: the control's SOUL.md expectation was stale on a box whose git reads no checkout identity; qualified both ways); no READY subtask left — every remaining subtask is DEFERRED · handoff 2026-11-12 (w1112a-hmtests): closed FH-WORK-WRITER-TZSET-WINDOWS-RED (f36529afb51: the day zone is injectable, no tzset) and FH-GROUP-COMPUTE-QUESTION-RED-WINDOWS (cdedd83a44b: a room view no longer waits on a member dispatch in flight); FH-MAIN-RED-SPAWN-FENCE-TOOL-NOT-ARGV0, FH-MAIN-RED-SILENT-PACKAGE-PATCHES-THREE and FH-MAIN-RED-SAFE-MODE-TIMEOUT were stale, closed on 366fc0773d, 71d93d0079 and f562dfe61c; no READY subtask left, claim released · reopened 2026-11-13 (w1112b-hm5): FH-MAIN-RED-COMMAND-DISCOVERY-SERVE-GUARD (READY) moved in from TASK-UPSTREAM-LOAD-FLAKES (review batch 6 §0) · handoff 2026-11-13 (w1112b-hm6): closed FH-MAIN-RED-COMMAND-DISCOVERY-SERVE-GUARD (5e33173642: the guard admits a `serve --isolated` whose HERMES_HOME and HOME are both re-homed; the discovery test passes, its strict xfail dropped); no READY subtask left, claim released · handoff 2026-11-16 (w1115e-fh): reopened: its DEFERRED was stale — FH-CHILD-STARTUP-FINDER-AND-SPAWN-STAND-INS-RECURSE (READY, reviewed w1115e.31) is open under it; 3 subtasks (1 ready, 2 deferred) · handoff 2026-11-16 (w1115e-fh): closed FH-CHILD-STARTUP-FINDER-AND-SPAWN-STAND-INS-RECURSE DONE e85721d9f1; 2 subtasks left, both deferred · triage 2026-11-19 (w1118a-triH): owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — closed `FORK-P0-VALIDATED-SUITE-FROZE` as stale (ADR 0016 retired the whole-tree run that froze; the 2026-10-16 whole-tree gate and the 2026-10-17 every-file-alone pass ran its four files after the freeze) and `FH-WORK-ROW-SCRIPT-FOUR-REDS-ON-MAIN` as churn ("check for churn too"; a red on main is not a row); 1 subtask left, `FORK-LANE-HOMES-REAL-PATH`, kept deferred for the owner's workstation sitting; the task stays DEFERRED, waiting on it alone
- **`TASK-PREPUSH` — Agent engine checks: pre-push, CI and the full suite run fast and alike on every machine** · task: prepush · review w1118a.34: `FH-PREPUSH-TOUCHED-KILLS-THE-REAL-CLOSURE-BUNDLE-TESTS` (filed by w1118a-hbundle) triaged out as churn and DEFERRED for the owner; the task stays DEFERRED · 1 subtask open on 2026-11-16 (`FH-CI-MAIN-LARGE-RUNNER-QUEUE`, DEFERRED; w1115e-q4 closed `FH-PREPUSH-DOC-CITE-OVER-BUDGET-UNDER-LOAD` as churn, owner 2026-11-16 "sounds good" on review w1115e.19; w1115e-rr2 closed FORK-PR-RUN-TESTS-PARALLEL into FH-UPSTREAM-PRS-REBASE-V0231; earlier: w1114a-hfix2 closed `TOOL-FIVE-TESTS-UNWIND-THE-TEST-SANDBOX` and `FH-PREPUSH-DOC-CITE-REDS-UNDER-LOAD`, w1114a-hprepush closed `FH-PREPUSH-SKIPS-NAME-CENSUS-ON-PYTHON-CHANGE`; the 5 ready all need an idle Windows box) · w1118a-hfh2 closed the overrun-line subtask (9dc3831ac4: the line names a live row or this task, never a retired ID); its one open subtask, `FH-CI-MAIN-LARGE-RUNNER-QUEUE`, stays DEFERRED, the owner's · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.26 D2: set the task READY; why: a task with a reviewed READY subtask is READY by the grammar, and this changes only the task's line, not the owner's deferral of the CI row; rejected: leaving it DEFERRED, which hides a takeable subtask · was deferred 2026-11-16 while its one open subtask was the owner-deferred CI row · reviewed 2026-11-19 w1118a.26 · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — w1118a-hfh2: back to DEFERRED once its READY subtask closed; why: its only open subtask is the owner-deferred CI row, so nothing in it can start; rejected: leaving it READY, which would offer lanes a task with no takeable subtask · w1118a-hfh3 closed the pushed-lane-branch close subtask (53b51dd55d: a row op lands on main and both close guards check origin/main); its one open subtask, `FH-CI-MAIN-LARGE-RUNNER-QUEUE`, stays DEFERRED, the owner's · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.27 D2: set the task READY; why: it now holds a reviewed READY subtask, and only the task line changes; rejected: a new task for one row (a new task needs two subtasks) and leaving it DEFERRED · was deferred 2026-11-19 by w1118a-hfh2 when its overrun-line subtask closed · reviewed 2026-11-19 w1118a.27 · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — w1118a-hfh3: back to DEFERRED once its READY subtask closed, as w1118a-hfh2 did; why: its only open subtask is the owner-deferred CI row, so nothing in it can start; rejected: leaving it READY, which would offer lanes a task with no takeable subtask · waits: FH-CI-MAIN-LARGE-RUNNER-QUEUE · review w1118a.62: passed `FH-A-MUTATION-CLAIM-NAMES-A-CREATE-BACKSTOP-LINE-THAT-IS-GONE`; closed DESKTOP-QJ7DDV2's two loaded-box overrun rows under the owner's rule that a slow push check is recorded as owed, not a row; two subtasks fewer than the counts that follow · RULED 2026-11-20: owner said "sure make sure it not churn first" (asked whether to reopen this task for `FH-A-MUTATION-CLAIM-NAMES-A-CREATE-BACKSTOP-LINE-THAT-IS-GONE` alone) — coordinator churn check: not churn, it restores the recorded proof that the agent-create security backstop is tested (a correctness gain, size S); `FH-CI-MAIN-LARGE-RUNNER-QUEUE` stays the owner's deferral · was READY 2026-11-20 for that row · w1118a-hrt3 closed `FH-A-MUTATION-CLAIM-NAMES-A-CREATE-BACKSTOP-LINE-THAT-IS-GONE` DONE b8a965170a (hh13 targets `service_backstop(self.caller, method=self.METHOD)`, seen red under its mutation; landed 70ef963fbf); one subtask fewer than the counts that follow · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — w1118a-hrt3: back to DEFERRED once its READY subtask closed, as w1118a-hfh2 and w1118a-hfh3 did; why: its only open subtask is the owner-deferred CI row, so nothing in it can start; rejected: leaving it READY, which would offer lanes a task with no takeable subtask · review w1118a.63: filed and passed `FH-PREPUSH-NEVER-CHECKS-THAT-MUTATION-CLAIMS-STILL-ANCHOR` (D1, READY); closed `FH-PREPUSH-TOUCHED-OVERRAN-WITH-44-NAMED-TEST-FILES` under the owner's rule that a slow push check is recorded as owed (D4) · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.63: the task READY again, since a reviewed READY subtask makes it so (review w1118a.26 D2) · RULED 2026-11-20: owner said "go as reccomended" (keep TASK-PREPUSH open for FH-PREPUSH-NEVER-CHECKS-THAT-MUTATION-CLAIMS-STILL-ANCHOR only) · handoff 2026-11-20 (w1118a-hprep): was READY 2026-11-20 for `FH-PREPUSH-NEVER-CHECKS-THAT-MUTATION-CLAIMS-STILL-ANCHOR` (review w1118a.63 D1) · w1118a-hprep closed `FH-PREPUSH-NEVER-CHECKS-THAT-MUTATION-CLAIMS-STILL-ANCHOR` DONE 95cb5eba4f (the eight claims re-anchored and each seen KILLED by its own test; prepush runs the anchor test in the touched lane when the registry or a claimed file changes, 2.4 s there); its one open subtask, `FH-CI-MAIN-LARGE-RUNNER-QUEUE`, stays DEFERRED, the owner's · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — w1118a-hprep: back to DEFERRED once its READY subtask closed, as w1118a-hfh2, w1118a-hfh3 and w1118a-hrt3 did; why: its only open subtask is the owner-deferred CI row, so nothing in it can start; rejected: leaving it READY, which would offer lanes a task with no takeable subtask · READY 2026-11-21 · RULED 2026-11-21: owner — "yea lets do it" (asked whether to wake TASK-PREPUSH so its push-time rows can run); FH-CI-MAIN-LARGE-RUNNER-QUEUE stays DEFERRED as launch-v1 work (owner 2026-11-19) · handoff 2026-11-10: w1110c-hmprepush closed LINE-ENDINGS-MEMO-RED-WINDOWS (7b3e61beeac) and cut the Windows gates step 98 s red -> 32 s (9d87a13109c) and made heavy files shard on Windows (60cb78a0020); the 4 READY rows left are measurement work for an idle Windows box: GATES-OVER-BUDGET (start-up cost, not a gate), TOUCHED-NAMED-HEAVY-OVER-BUDGET (one 36 s room test), and the new PREPUSH-SH-TEST-SLOW-WINDOWS and DOC-CITE-OVER-BUDGET · handoff 2026-11-10 (w1110c-hm2): closed HELPER-NAME-ANSWER-TWO-OWNERS (ca01c1e694e) and DOC-CITE-OVER-BUDGET (23b58f843ce, a suffix index; idle 1.9 -> 1.5 s), refuted PREPUSH-SH-TEST-SLOW-WINDOWS (designed waits, already sharded by 60cb78a0020), cut the row guard 3.75 -> 1.63 s toward GATES-OVER-BUDGET (92d119a3f68; gates 16.2 s at load 3, still over its 10 s budget on Windows start-up), filed CENSUS-OVER-BUDGET (36.3 s at load 14); READY left: GATES-OVER-BUDGET and CENSUS-OVER-BUDGET (need an idle Windows box, load < 2), TOUCHED-NAMED-HEAVY-OVER-BUDGET (untouched: speed the 36 s twelve-member room test) · handoff 2026-11-10 (w1110c-hm3): closed TOUCHED-NAMED-HEAVY-OVER-BUDGET (5cd83a166db: twelve-member test 35-38 s -> 23-25 s at CPU ~95 %) and verified WINDOWS-EOL-COLD-ARGV cold (e40ba3032b); filed EOL-GATE-COLD-TIMEOUT; READY left need an idle Windows box: GATES-OVER-BUDGET, CENSUS-OVER-BUDGET, WORK-V1-CLAIM-GATES-WINDOWS-BUDGET, plus EOL-GATE-COLD-TIMEOUT · handoff 2026-11-10 round 2 (w1110c-hm3, box at CPU 100 %): 8 -> 5 python starts before the first test (60ae94b5331) and imports found once per tree (11e28051026, no measured win); prepush on 11e28051026 still kills gates at 22.0 s (load 101) — the rest waits on `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP` (owner decision) and idle-box readings; filed `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP`; touched step 85.3 s (load 64) and 68.5 s (load 61) here, all `tests/agent_runtime/test_discussion_runtime.py` (41-59 s alone) — belongs on w1110c-hmssh's `FH-PREPUSH-TOUCHED-OVER-BUDGET` once it lands; claim released · handoff 2026-11-10 (w1110c-hm3b): `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP` ruled fork-side and worked — the bundled runner's leftovers scan 37.5 s -> 3 s (ab80b93d269); the gates stay per-file until the bundled runner has a small-run path (~20 s of landing-gate work); claim released · handoff 2026-11-10 round 2 (w1110c-hm3b): closed `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP` (171b40979aa) — the gates run as bundles via `run_tests_bundled.sh --small`, 17.7-19.5 s vs 22.7-25.9 s per-file at CPU 80-93 %, still over the 10 s gates budget (`FH-PREPUSH-GATES-OVER-BUDGET`); claim released · handoff 2026-11-11 (w1110d-hmprepush, Linux): closed LINUX-BOX-NO-NODE-UPSTREAM-REDS, LINUX-BOX-NO-RIPGREP-SEARCH-REDS and LINUX-SOURCE-UPDATE-FILES-RED-ON-MAIN (57b6119257: host-tool reds skip by id-mark, update_finish's agent_runtime reds strict-xfail); EOL-GATE-COLD-TIMEOUT fixed for a cold memo (c929a655bd, cold fixture 7.5-9.5 s -> 3.9 s here), Windows cold run owed; the 5 READY rows left all need an idle Windows box (REQUIRES windows), with Linux readings on CENSUS (profile), GATES (Linux also overran at load 28), WORK-V1-CLAIM and TOUCHED · triage 2026-11-19 (w1118a-triH): owner said "check for churn too" — closed `FH-PREPUSH-TOUCHED-KILLS-THE-REAL-CLOSURE-BUNDLE-TESTS` and `FH-DUPLICATE-LITERAL-GATE-RED-ON-THE-GIT-PORT` as churn; `FH-CI-MAIN-LARGE-RUNNER-QUEUE` kept deferred as launch-v1 work (owner "the launch v1 tasks should remain deffered imho"); the task stays DEFERRED on it · handoff 2026-11-20 (w1118a-fulltime-hm): w1118a-fulltime-hm closed FH-DAILY-RUN-TIMES-EVERY-TEST (5abc9af657: the daily run times every test); back to DEFERRED on FH-CI-MAIN-LARGE-RUNNER-QUEUE
- **`TASK-UPSTREAM-FOOTPRINT-LEDGER` — Agent engine: carry as little as possible on top of upstream, fixing bugs where they live** · task: upstream-footprint-ledger · 2 subtasks on 2026-11-15 (2 deferred: FH-UPSTREAM-PRS-REBASE-V0231 now holds the 22 held-PR rows folded by w1115e-rr2, RT-RECHECK-AFTER-THE-PRE-LAUNCH-HERMES-UPDATE the 33 re-checks after the update) · DEFERRED 2026-11-15: every subtask is deferred — the PR rebases wait on the owner (2026-11-12 "no force-push for now"), the re-checks on the pre-launch hermes update; until one moves · waits: owner-ruling · unblocked 2026-11-15: `FORK-HERMES-GH-AUTH-STATUS` closed by the owner · handoff 2026-11-09: FH-UP-FP-FIXTURE-LAGS-MAIN filed READY by w1109a-hm-2 · handoff 2026-11-10 (hm-release): the v0.23.1 release merge (branch `merge/upstream-v0.23.1`) closed four upstream-settled rows and refuted UP-TOOL-REQUEST-MIDDLEWARE-ORIGINAL-ARGS; filed eleven READY rows (the stale sync-gate script, footprint moves the merge measured, main reds it met, the PR rebase list) and two owner decisions · handoff 2026-11-10 (w1110d-foot): footprint 241 files / 1,024 deleted lines → 234 / 905; ready left: FH-UPSTREAM-PRS-REBASE-V0231 (all 22 branches conflict on upstream/main: one rebase lane per PR) and FH-FOOTPRINT-FORK-TEST-HUNKS-OUT (three test files, each needing a door or a sibling); blocked: two owner decisions (FH-FOOTPRINT-PROVIDER-UA-LAZY, FH-HARNESS-CORE-BROWSER-AFTER-V0231) and FORK-HERMES-GH-AUTH-STATUS (upstream issue) · handoff 2026-11-10 (w1110d-foot, round 2): owner ruled both decisions (go with recommended) and both landed (UA rebind aee036c873, browser-use in harness_core d572176d5c); FH-FOOTPRINT-FORK-TEST-HUNKS-OUT done (2f4fdc47f4: drain id mark, tombstone fork copy, doctor helpers + test_doctor at upstream bytes); footprint now 224 files / 871 deleted lines; ready left: FH-UPSTREAM-PRS-REBASE-V0231 (upstream-facing PR branch rebases: held for the owner) (FH-FORK-MARKS-WINDOWS-SKIPS-SEEN closed DONE 2026-11-12 on Windows, lane w1112a-hmwork); blocked: FORK-HERMES-GH-AUTH-STATUS (upstream issue) · handoff 2026-11-11 (w1110d-uprebase): FH-UPSTREAM-PRS-REBASE-V0231 BLOCKED on an owner decision — 18 of 22 PR branches rebased onto v0.23.1 locally and green, push commands for the owner in the wave folder; #128649 and #124190 need work, #125263 split and #128841 close recommended; ready left: FH-FORK-MARKS-WINDOWS-SKIPS-SEEN (needs a Windows run) · triage 2026-11-19 (w1118a-triH): owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — both subtasks kept deferred: `FH-UPSTREAM-PRS-REBASE-V0231` holds the owner's "no force-push for now" / "pr branches should remain idle", and `RT-RECHECK-AFTER-THE-PRE-LAUNCH-HERMES-UPDATE` is launch-v1 work (owner "the launch v1 tasks should remain deffered imho"); nothing archived

## Design-fix tasks — 2026-11-15 (review batch w1115e.9, B59; filed by lane w1115e-dfile)


## Design-fix tasks — 2026-11-15 (review batch w1115e.8, B58; filed by lane w1115e-dfile)


## Owner request — 2026-11-08 (hermes prepush: a tight cap, an overrun report, fast)
- **`FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-EMBEDDED-PHONE-SESSION-FILE` — A push that touches provider sign-in waits a minute on one phone test file, past the touched step's budget** · group: prepush · from: lane w1118a-onepath-hm landing 6550288611 · seen 2026-11-21 (`scripts/prepush.sh`, Linux box, load 2.58): step `touched` 62.1 s against budget 60 s (deadline 120 s), its whole wall `tests/agent_runtime/test_embedded_phone_session.py` alone (4 tests, 61.4 s, 1 worker); the step stayed green · guessed: the file boots an embedded serve per test; not profiled · done when: the file runs inside the touched budget on this box, or the touched step splits it across workers · review w1118a.70: passed with a rewrite; read in code — the file is `pytest.mark.e2e_child` and boots an `EmbeddedServe` (plus a local provider `ThreadingHTTPServer`) in each of its 4 tests, ~15 s each, so one worker carries the touched step's whole 60 s budget (`scripts/prepush.sh` `touched` budget 60, deadline 120); the overrun ledger names a fork-hygiene row for each overrun, which this is; the step stayed green, so it is a speed row, not a red · first step: profile one test (setup vs call, where the serve's boot and teardown `serve.wait(60)` spend) before any change · architecture: test-side only — share one embedded serve across the file's tests through a module fixture where each test's state allows, or let the touched step split the file; never raise the touched budget (owner 2026-11-13) · file map: `tests/agent_runtime/test_embedded_phone_session.py`, `scripts/prepush.sh` only if the split is the answer · overlap: none open on this file (swept); `FH-PREPUSH-GATES-KILLED-AT-HANG-GUARD-UNDER-LOAD-48` is the gates step, not this one · size S · reviewed 2026-11-21 w1118a.70 · review w1118a.71: clustered under `FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET` (the design fix: a fresh tree has no `test_durations.json`, so the touched step never shards this file on its first push); this row runs after it and closes if the shard fallback brings the file under budget, else keeps its test-side fix · reviewed 2026-11-21 w1118a.71 · READY 2026-11-21 · handoff 2026-11-21 (w1118a-sw75-hm): w1118a-sw75-hm: seen again 2026-11-21 landing RT-FU-A-PHONE-SIGNED-IN-TO-ONE-PROVIDER-GIVES-ITS-AGENTS-NO-MODEL: touched 78.5 s against the 60 s budget at load 7.10, of which tests/agent_runtime/test_embedded_phone_session.py alone took 77.9 s (the next slowest 24.7 s); work 8 files.
- **`FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-ROSTER-BYPASS-CONTRACT-FILE` — A push that touches the agent create or place doors waits past the touched step's budget on one roster contract test file** · group: prepush · from: lane w1118a-sw74-hm landing (RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT) · seen 2026-11-21 twice (`scripts/prepush.sh`, Linux box, load 24.4 then 28.6): step `touched` 64.4 s then 65.3 s against budget 60 s (deadline 120 s); `tests/agent_runtime/test_persona_roster_bypass_contract.py` (5 tests) was sharded into 4 from its 31 s record, timed out as a shard and passed on the 1-worker retry in 30.6 s, so the retry alone carried the step past budget; the step stayed green the second time · guessed: the file walks the `agent_runtime` and `hermes_cli` trees (AST) per test, about 30 s whatever the shard count, so sharding it adds a timeout and a retry; not profiled · done when: the file runs inside the touched budget on this box (one walk shared across its tests, or kept unsharded), pinned by its own timing · file map: `tests/agent_runtime/test_persona_roster_bypass_contract.py`, the touched step's shard rule in `scripts/prepush.sh` / the bundler only if that is the answer · overlap: `FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET` (shard fallback) and `FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-EMBEDDED-PHONE-SESSION-FILE` are other files of the same step · size S · filed 2026-11-21 by lane w1118a-sw74-hm (awaits a review batch) · review w1118a.75: merged into `FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET` (the touched step's shard-decision design row); premise corrected in code: the tree walk is once per process (`tests/agent_runtime/_tree_index.py`, session cache), and only `test_every_persona_carrying_call_site_is_declared` walks, so the file's ~30 s is ONE test, which node-id shards cannot split; `scripts/prepush.sh` shards on the file's duration (`_last_seconds`) as if it divided across tests — the same flaw as that row (the shard decision answers from the wrong fact), so its fix carries this file. `TASK-PREPUSH` stays DEFERRED as the owner left it. The coordinator closes it · READY 2026-11-21


## Filed on arrival — 2026-11-20 (lane rt-never-ran-field)


## Filed on arrival — 2026-11-20 (lane rt-chat-rebind)


## Filed on arrival — 2026-11-19 (lane bundled-facts)


## Filed on arrival — 2026-11-19 (lane bundled-realm)


## Filed on arrival — 2026-11-16 (lane w1115e-fh3: what the hermes test seal reported)


## Filed on arrival — 2026-11-15 (lane w1115e-rr2)


## Filed on arrival — 2026-11-15 (lane w1115r-h3)

## Filed on arrival — 2026-11-15 (lane w1115r-h2)

## Filed on arrival — 2026-11-15 (lane w1115k-hlens: the end-of-lane run of the Lens recipe rows)


## Filed on arrival — 2026-11-13 (lane w1113-slotclonehome)


## Filed on arrival — 2026-11-12 (lane w1112b-hm3: review batch w1112b-4 §6)


## Filed on arrival — 2026-11-12 (lane w1112b-hm-speed: running the tests beside `RT-HARNESS-PARSER-PLUGIN-LOAD-TWICE`)


## Filed on arrival — 2026-11-12 (lane w1112a-hmscan)


## Filed on arrival — 2026-11-12 (lane w1112a-hmwork)


## Filed on arrival — 2026-11-10 (lane w1110c-hm3)


## Filed on arrival — 2026-11-09 (lane w1109a-hm-2)


## Filed on arrival — 2026-11-09 (lane w1109a-hm-iso)


## Filed on arrival — 2026-11-09 (stale-headers lane)


## Filed on arrival — 2026-11-08 (lane w1108c-hm-reds-upstream)


## Filed on arrival — 2026-11-08 (lane w1108a-hm-reds)


## Filed on arrival — 2026-11-08 (lane w1108a-land-hm)


## Filed on arrival — 2026-11-06 (lane w1106b-hm)


## Filed on arrival — 2026-11-06 (lane w1106a-hm)


## Filed on arrival — 2026-11-05 (lane w1105h-hm)


## Filed on arrival — 2026-11-02 (appearance acceptance)


## Filed on arrival — 2026-11-02 (landing w1101e, hermes)


## Filed on arrival — 2026-11-01 (profile artwork qualification)


## Filed on arrival — 2026-10-30 (owner: push checks hang)


## Filed on arrival — 2026-10-29 (land w1029a-h)


## Filed on arrival — 2026-10-29 (lane w1029a-h-fork)


## Filed on arrival — 2026-10-27 (lane w1027k-plan-misc, launcher)


## Filed on arrival — 2026-10-27 (lane w1027j-h-tri-b, planned/ triage)


## Filed on arrival — 2026-10-27 (lane w1027i-h-fork)


## Filed on arrival — 2026-10-27 (lane w1027h-h-reds)


## Filed on arrival — 2026-10-27 (lane w1027a-h-fork)


## Filed on arrival — 2026-10-26 (lane w1026c-h-rt-b)


## Filed on arrival — 2026-10-26 (lane w1026c-h-fork)


## Filed on arrival — 2026-10-26 (lane poller-requeue)


## Filed on arrival — 2026-10-26 (next-prompt implementation)






















## Filed on arrival — 2026-10-25 (lane w1025a-hermes)


## Filed on arrival — 2026-10-22 (release merge rel-v0224)


## Filed on arrival — 2026-10-22 (land w1022d)


## Filed on arrival — 2026-10-22 (land w1022a)


## Filed on arrival — 2026-10-21 (lane w1021h-tooling, branch `w1021h/tooling`)

- **`FH-CI-MAIN-LARGE-RUNNER-QUEUE` — hermes CI on `main` never finishes: upstream's jobs ask for runner labels ArcadiaLabsLLC lacks; run 39494050964 (`79d3fa5754`) queued since 2026-10-20 holds `ci-refs/heads/main`, every later push pending → cancelled; 0 green in the last 200 runs** · group: prepush · fork CI · evidence `306a622a64` (branch `w1021h/tooling`) · RULED 2026-10-22: owner — no larger runners; a fork seam maps upstream's large-runner labels to standard runners through a repository variable whose default is upstream's label · RULED 2026-10-25: owner — zero upstream footprint: one fork-owned workflow on `ubuntu-latest` / `windows-latest` running `scripts/run_tests.sh` over the validated lanes on `main` pushes, then the owner disables upstream's `ci.yaml` for the fork in the repository's Actions settings (one click, after the fork workflow lands); supersedes the 2026-10-22 per-label seam · BUILT 2026-10-25 lane w1025a-hermes: `.github/workflows/fork-gates.yml` job `validated-suite` (ubuntu-latest + windows-latest, the validated scope then `tests/tooling tests/scripts`, push to `main`), pinned by `tests/ci/test_fork_suite_on_standard_runners.py` · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: in GitHub, ArcadiaLabsLLC/hermes-agent → Actions → "CI" (`ci.yaml`) → Disable workflow, and cancel queued run 39494050964 if it still holds `ci-refs/heads/main`; then read the first `Fork gates` run on `main` for the two `Validated suite` jobs · waits: owner-ruling · RULED 2026-11-19: owner said "the launch v1 tasks should remain deffered imho" — kept deferred as launch-v1 work (CI enablement); read 2026-11-19 with `gh`: run 39494050964 has completed (failure), so it no longer holds `ci-refs/heads/main`, and no Actions run of any workflow has started on ArcadiaLabsLLC/hermes-agent since 2026-11-06 — what is left is the owner's Actions step (disable upstream `CI`, read the first `Fork gates` run) when CI is switched on for launch
- **`FH-PREPUSH-GATES-KILLED-AT-HANG-GUARD-UNDER-LOAD-48` — A push check skipped its queue gates because the box was busy, so a push went out with them owed** · group: prepush · seen 2026-11-20 by lane w1120b-skills (`scripts/prepush.sh`, head 0cdf90092570, Windows box): step `gates` work 11 (at its ceiling 11), wall 20.7 s against budget 10 s, killed at its 20 s hang guard, load 48.00 with other lanes running; exit 0 with "OWED … gates" · guessed: load, not the gates, set the wall; not re-run on a quiet box · done when: the gates step finishes under its deadline on this box at the load other lanes make, or its deadline is raised on an idle-box measurement · READY 2026-11-20 · handoff 2026-11-20 (w1120b-approvals): seen again 2026-11-21 (head 1cf5edc9bb63, two runs, Windows box): gates killed at its 20 s guard (22.8 s / 23.2 s, load 16.5 / 38.0), census killed at its 60 s guard (64.8 s / 62.1 s, budget 30 s, load 22.9 / 54.0), touched (9 files) 97.6 s against budget 60 s at load 13.3, killed at 120 s at load 80.7; all OWED, no red

## Filed on arrival — 2026-10-20 (launcher orchestrator w1020r)


## Filed on arrival — 2026-10-18 (land w4)


## Filed on arrival — 2026-10-16 (landing land-h5, reds proven on `origin/main` `b11585e6424` by `scripts/run_tests.sh` alone)


## Filed on arrival — 2026-10-16 (build lane h-bundle-speed, reds proven on `origin/main` `aba5fec098c`)


## Filed on arrival — 2026-10-16 (build lane h3-runser)


## Filed on arrival — 2026-10-15 (audit lane a1015-hfh)


## Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


## Filed on arrival — 2026-10-15 (lane w1015h-rt-h)


## Filed on arrival — 2026-10-15 (landing land-w1015j-h, reds proven on `origin/main` `88414c8d13e`)


## Filed on arrival — 2026-10-15 (landing land-w1015e, pre-existing reds proven on `origin/main` `ef2a4492272`)


## Filed on arrival — 2026-10-15 (lane w1015b-fh-a)


## Filed on arrival — 2026-10-13 (upstream merge v0.21.7)


## Filed on arrival — 2026-10-09 (final gates)


## Filed on arrival — 2026-10-08 (lane opus-w1-hermes)


## Filed on arrival — 2026-10-08 GenUI qualification


## Filed on arrival — 2026-10-06 (lane console-generated-content)



The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — the hermes half is [[runtime-queue]], the launcher half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-10-06 (lane h-prereq-window)


## Filed on arrival — 2026-10-05 (owner ask: a usable suite)


## Filed on arrival — 2026-10-05 (lane h-turn1-title)


## Filed on arrival — 2026-10-05 (lane h-turnws, the workstation freeze)

## Filed on arrival — 2026-10-05 (lane h-turnws)


## Filed on arrival — 2026-10-04 (lane hb-a)


## Filed on arrival — 2026-10-03 (resident identity verification)


## Filed on arrival — 2026-10-02 (lane h-rows)


## Filed on arrival — 2026-10-02 (instance foundation)


## Filed on arrival — 2026-10-02 (lane w13-hm, filed by the orchestrator)


## Filed on arrival — 2026-10-02 (lane w10-s7h)


## Filed on arrival — 2026-10-02 (lane w5-fh)


## Filed on arrival — 2026-09-30 (GenUI invocation)


## Filed on arrival — 2026-10-01 (lane w3-turn)


## Filed on arrival — 2026-10-01 (lane w3-perf)


## Release validation — 2026-09-23


**Provider-boundary qualification, October 1:** the existing TLS setup stall and duplicate-name/routing-ladder gate failures were reproduced, not waived; [evidence](../../docs/downstream/provider-access-boundary-2026-10-01.md#qualification). Native provider, plugin and execution checks pass; this does not certify a whole-repository green run.




**Additional evidence for the claimed validated-suite residuals:** 68 gateway/TLS failures reproduce on clean primary with Python 3.13.15; this does not supersede the separate Python 3.12 green receipt. [Comparison](../../docs/downstream/chat-first-group-qualification-2026-09-29.md#baseline-comparison). Filed 2026-09-29 chat-first-groups.








### Filed on arrival — 2026-10-15 (owner screenshot during land-w1015h)


### Filed on arrival — 2026-09-29 (h11-mcp landing)


### Filed on arrival — 2026-09-29 (lane h10-fhrest)


### Filed on arrival — 2026-09-29 (lane h7-phone)


### Filed on arrival — 2026-09-28 (lane w5-hstt)

### Filed on arrival — 2026-09-29 (lane h10b-triage — the three-directory triage, one row per class)


### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-27 (Windows console signal safety)


### Filed on arrival — 2026-09-26 (native Hermes qualification)


  EVIDENCE 2026-10-06 console-generated-content: the 895-file fork gate's exact
  115 failure/error nodes in 33 files reproduce on unchanged `5c0f130723`;
  the 35 unique helper/legibility/citation violation lines also match.
  [Receipt and remaining native acceptance](../../docs/downstream/console-generated-content-2026-10-06.md).

### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)





## Filed on arrival — 2026-09-30 (Stage 2 G4 landing, filed by the orchestrator)




## Filed on arrival — 2026-09-30 (launcher engine-build diagnosis, filed by the launcher orchestrator)


## Filed on arrival — 2026-09-29 (footprint attribution, filed by the orchestrator)


## Filed on arrival — 2026-09-29 (lane h10-fhrel, filed by the orchestrator)


## Filed on the move — 2026-09-22 (fork rows the launcher queue had carried since 2026-09-02)

Moved verbatim from `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`; they are about the repository as a fork, not about the surface. Upstream-owned ones are tagged so: never patched here, a marker or an upstream issue.


- The unrun-gate class on hermes `main`: nothing on any push lane runs the full suites, so reds accumulate silently. Two instances measured and FIXED 2026-08-30 (hermes `00fa94dd75` (pre-rewrite)): `tests/scripts/test_run_tests_script.py` (pins now follow `$RUNNER_PATH` and the import-pytest venv probe) and `tests/hermes_cli/test_error_exit_code_producers.py` (`runtime_unavailable` left `_KEPT_UNSPENDABLE` — the gateway lane mints it at five sites). The CLASS is NARROWED 2026-09-02: hermes' push gate now exists (`fc2e16349e` (pre-rewrite) — Lane B runs the validated 4-dir lane on `main` pushes), so what stays open is only the dirs outside that lane, e.g. `tests/scripts`, home of the first instance. Evidence: the misc-batch landing report (hermes `5fa9000b2`), both fixes `00fa94dd75` (pre-rewrite); hermes `AGENTS.md` §Testing. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16
- Hermes's focused suites cannot be trusted under multi-agent load: the named instance is RETIRED by suite-perf Stage 6 — `test_realm_sync.py` now drives `run_harness_in_process` (`tests/agent_runtime/_harness_cli`) and carries no `timeout` at all (verified 2026-09-01). The CLASS survives: an in-test subprocess cap `--timeout` cannot raise is invisible to the runner. Original filing: it timed out at load average ~400 on a command the diff never touched; fifteen failures across two suites on 2026-08-30 were all this class. Either the in-test cap becomes environment-scalable or the wave serializes pytest across agents. Evidence: the misc-batch landing report. **RULED 2026-09-04 evening (operator, recommended answer adopted):** Option 1. There is no scaling helper anywhere today — a repo-wide grep for `HERMES_TEST_SUBPROCESS_TIMEOUT` / `timeout_scale` finds only an unrelated audio test — while 474 test files carry a `timeout=`, so the class is broad and nothing currently absorbs load. Option 2 needs exactly the cross-agent orchestrator the shared-index row above says does not exist, and serializing test runs is a direct tax on the multi-agent workflow this house runs by default. Next: hermes: add the scaled-timeout helper plus its env knob, convert the subprocess caps in the test tree to use it, and add a gate refusing a bare numeric subprocess `timeout=` in `tests/`. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16

## Filed on arrival — 2026-09-24 (lane CARRY2A)



## Filed on arrival — 2026-09-24 (lanes UPPR2, REDS)


### Filed on arrival — 2026-09-29 (lane h12-upnew)


## Filed on arrival — 2026-09-24 (disposition wave)


## Filed on arrival — 2026-09-23 (seam Stage 0 lanes)


## Filed on arrival — 2026-09-21 (upstream sync assessment)


## Filed on arrival — 2026-09-21 (god-file refactor plan)


## Filed on arrival — 2026-09-21 (brain)


## Filed on arrival — 2026-09-24 (lane CARRY2B)


## Filed on arrival — 2026-09-24 (lane REDS2)


## Filed on arrival — 2026-09-24 (lane CARRY3)


## Filed on arrival — 2026-09-24 (lane TESTS)


## Filed on arrival — 2026-09-24 (lane REDS3)


## Filed on arrival — 2026-09-24 (lane CLOSE)


## Filed on arrival — 2026-09-24 (program-end gate on `c7652475cd`)


## Filed on arrival — 2026-09-24 (lane LEDGER-DOCS)



## Filed on arrival — 2026-09-24 (lane DOORS-A)


## Filed on arrival — 2026-09-24 (lane W0)


## Filed on arrival — 2026-09-24 (lane MERGE)


## Filed on arrival — 2026-09-24 (lane H1)
## Filed on arrival — 2026-09-25 (lane R4)


## Filed on arrival — 2026-09-25 (lane S2B)


## Filed on arrival — 2026-09-25 (lane S2A)


## Filed on arrival — 2026-09-25 (lane 2B-A)


## Filed on arrival — 2026-09-25 (lane Q-DEAD-A)

## Filed on arrival — 2026-09-25 (lane B2)


## Filed on arrival — 2026-09-25 (lane Q-GATES)

## Filed on arrival — 2026-09-25 (lane B3)


## Filed on arrival — 2026-09-30 (lane h13-test)


## Filed on arrival — 2026-09-26 (lane TRIAGE)


## Filed on arrival — 2026-09-26 (lane ACP-DROP, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (program-end suite on `7df3bee189`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (batch gates on `6bae3f2484`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LAYERS-DESIGN, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LLAMA-ALIAS, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane W3-A)

## Filed on arrival — 2026-09-25 (round-2 gate pass)


## Filed on arrival — 2026-09-25 (lane W3-C)


## Filed on arrival — 2026-09-27 (lane MERGE-0927)

## Filed on arrival — 2026-09-30 (lane h12-upfix)



## Filed on arrival — 2026-10-04 (lane h-qaeff)


## Filed on arrival — 2026-10-05 (lane upstream-PR review replies)


## Filed on arrival — 2026-10-06 (turn-latency session)

- **`FORK-LANE-HOMES-REAL-PATH` — Test and lane homes still land their `bin` on the operator's real user `Path` after the 2026-10-03 PATH fence: 14 of 30 leaked entries were created 2026-10-05 (`stage2-serve-*`, `stage4-gateway-*`, `rb7-identity-flip-*`, `ro9-boot-sweep-*`, `rs7-restart-fence-*`, `p-l-longrun-*`, a lane's `scratchpad/live`); the first one shadowed `hermes` and the operator's `hermes harness observe` died on a deleted interpreter** · group: hermes-test-isolation.design-sweep-d3 · fork hygiene / test isolation · evidence: `[Environment]::GetEnvironmentVariable('Path','User')` read 2026-10-06 00:35, dated by each dir's CreationTime; writers are `hermes_cli/_launchers.py` (user-Path merge) and `windows_env.py`, fence `hermes_cli/_registry_write_fence.py` · lane: find the writer the fence misses (a subprocess outside `install_path_fence`, or a root the fence counts as owned), make the gate a positive test, then a one-time cleanup verb the operator runs · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.15; stages 1–2 built (`805f8293c9` `4045fa25c8` `811fc986e7`) · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: on the workstation: stage 0 (Process Monitor on a launcher real-serve sandbox run) and `scripts/prune_user_path.ps1 -Apply` after reading its list; stage 3's -SkipUserPath upstream PR waits with the idle PR branches · waits: owner-ruling

## Filed on arrival — 2026-10-06 (lane h-turn1-conn)


## Filed on arrival — 2026-10-07 (owner: upstream integration jobs)


## Filed on arrival — 2026-10-06 (upstream PR triage)


## Filed on arrival — 2026-10-06 (landing w16)


## Filed on arrival — 2026-10-07 (upstream PR lanes up-drafts / up-door-*)


## Filed on arrival — 2026-10-07 (landing prep/hermes-waves-reviewed)


## Found fixing main's reds — 2026-10-07 (lanes h-red-cli/-runtime/-gates/-inherited)


## Filed by isolated lifecycle fixture — 2026-10-07


## Filed on arrival — 2026-10-08 final GenUI gate


Process-dock product-half recurrence, 2026-10-08 GenUI qualification: `tests/gateway/test_abandoned_turn_process_cleanup.py` times out in `test_timed_out_turn_reaps_only_its_own_job_on_a_shared_container_key`, at `tools/process_registry.py::_release_finished_handles` → `stream.close()`. The candidate full gate and isolated run hang; untouched `7ea1c17366` first passes all 15 tests, then an isolated repeat hangs at the identical site. This is additional evidence for the existing process-dock/upstream-PR row above. No timeout, environment fence or production cleanup code was changed.

## Filed on arrival — 2026-10-08 (release merge v0.21.6)


## Filed on arrival — 2026-10-09 (lane opus-fix-toolsets-refusal)


## Filed on arrival — 2026-10-09 (perf programme close-out sweep)


## Filed on arrival — 2026-10-09 (landing lane land-h-toolvis; red on detached origin/main 440cba12ce, after the upstream v0.21.6 merge)


## Filed on arrival — 2026-10-10 (release merge v0.21.6 reds, branch `fix/v0216-fork-reds`)


## Filed on arrival — 2026-10-10 (chat content integrity)


## Filed on arrival — 2026-10-10 (chat-content boundary qualification)




## Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)



## Filed on arrival — 2026-10-11 (Console history final qualification)







## Filed on arrival — 2026-10-13 shutdown-test repair

- **`FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY` — Bundled Hermes ships an OpenTelemetry API version without a known denial-of-service flaw** · group: engine-suite-green-followups · seen 2026-11-15 (w1115c-h1, same Linux stage and verify as above): `bundle_vuln_scan.py` reports `opentelemetry-api==1.45.1` GHSA-mf5v-w3w3-f6cg / CVE-2026-126360, fixed in 1.45.2, unwaived, so D4 gates fail; not checked whether the release lane already waives or bumps it elsewhere · architecture (B44): hermes owns the pins and the lock; a lock-only bump is impossible because upstream's `[otlp]` extra pins `opentelemetry-sdk==1.45.1` and `opentelemetry-exporter-otlp-proto-http==1.45.1` (`pyproject.toml:480-481`) and sdk 1.45.2 requires `opentelemetry-api==1.45.2`; a `[tool.uv]` constraint conflicts with those pins, so no fork route avoids them — footprint is upstream `pyproject.toml` +2/−2 plus a regenerated `uv.lock`, both already carried files, ledgered first as drop-when-upstream-bumps; no waiver, no Eternia change beyond the next bundled pin · done when: the bundle vuln scan reports 0 unwaived and the bundle verify stays green · NEW 2026-11-15 · BLOCKED 2026-11-15: upstream — owner held the fork bump; the pre-launch hermes update is expected to carry opentelemetry 1.45.2 · reviewed 2026-11-15 w1115c.1 · RULED 2026-11-15: owner — "yes" (to: update the packages — two version numbers plus a re-lock, ledger first, drop when upstream bumps) · handoff 2026-11-15 (w1115c-otel): pins moved to 1.45.2 and uv lock re-resolved (only the 11 opentelemetry packages move) on branch lane/w1115c-otel at 3d355a7fef, ledger rows updated; HELD unlanded because tests/scripts/test_upstream_footprint.py goes red: deleted_lines rises 874 to 911 (+2 pyproject.toml, +35 uv.lock), a fixture raise the lane may not make without a ruling that names the footprint raise (orchestrator asked) · handoff 2026-11-15 (w1115c-otel): owner 2026-11-15: "hold the fix" / "we will likely update hermes before launch" — the 1.45.2 bump (3d355a7fef on lane/w1115c-otel, not landed) is held; the footprint ceiling stays 874; the pre-launch hermes update is expected to carry opentelemetry 1.45.2 · handoff 2026-11-19 (w1118a-coord): w1118a-hotel 2026-11-19: upstream fixed it in 3b2610d01e (pyproject +2/-2, uv.lock; in v0.23.3 / rc.1-v0.23.3); a cherry-pick applies cleanly but upstream_footprint reads deleted_lines 915 vs ceiling 879 (the footprint base 3b42157858 is 8970 commits before the fix), so taking it now means raising a shrink-only ratchet, which the owner's rule forbids — RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended": recommended = the fix arrives with the next hermes upstream update (merge to v0.23.3+) at zero footprint; still BLOCKED on upstream for that reason



## Filed on arrival — 2026-10-15 (land-w1015b)


## Filed on arrival — 2026-10-15 (owner: "testing commands should be optimised")


## Filed on arrival — 2026-10-15 (lane w1015h-fh-h)


## Filed on arrival — 2026-10-15 (upstream PR sync lanes up-sync-1015-*)


## Filed on arrival — 2026-10-15 (owner: the footprint ratchet only goes up)

### Filed on arrival — 2026-10-16 (Phase B lanes pb-*, release gate triage rel-0222-reds)







## Filed on arrival — 2026-10-15 (lane w1015j-hermes)


## Filed on arrival — 2026-10-16 (h2-redact)


## Filed on arrival — 2026-10-16 (land-h234)



## Filed on arrival — 2026-10-16 (lane h5-deadcode)


## Filed on arrival — 2026-10-17 (footprint audit)


## Filed on arrival — 2026-10-17 (lane r-plugins)


## Filed on arrival — 2026-10-18 land/q6




## Filed on arrival — 2026-10-18 (lane r-quiet)

## Filed on arrival — 2026-10-18 (lane q-gates)

## Filed on arrival — 2026-10-18 (lane q-stale)

## Filed on arrival — 2026-10-18 (lane r-turn)

## Filed on arrival — 2026-10-18 (lane h1-setup)

## Filed on arrival — 2026-10-18 (lane h2-sleep)

## Filed on arrival — 2026-10-18 (lane h3-plugins)

## Filed on arrival — 2026-10-18 (lane h6-collect)

## Filed on arrival — 2026-10-18 (land h1018)

## Filed on arrival — 2026-10-18 (lane w2-reds)

## Filed on arrival — 2026-10-18 (lane w2-speed-b)

## Filed on arrival — 2026-10-18 (landing land-w2)

## Filed on arrival — 2026-10-18 (landing land-ww2)

## Filed on arrival — 2026-10-18 (landing land-w3)

## Filed on arrival — 2026-10-18 (land w6)

## Filed on arrival — 2026-10-18 (session r-perf close-out)


## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)


## Filed on arrival — 2026-10-19 (ns + rt-model landing ab8578f8f5: reds on main after land w10)


## Filed on arrival — 2026-10-19 (lane rt-ns-seed)


## Filed on arrival — 2026-10-20 (parent session)

## Filed on arrival — 2026-10-25 (lane w1024t-hermes2)



## Filed on arrival — 2026-10-26 (next-prompt landing baseline)

## Filed on arrival — 2026-10-27 (owner: triage every plan in planned/)



## Filed on arrival — 2026-10-28 (lane w1028a-h-persona)


## Windows baseline qualification — 2026-10-27


## Filed on arrival — 2026-10-28 (lane w1028a-h-rt)



## Filed on arrival — 2026-10-28 (lane w1028a-h-triage)


## Filed on arrival — 2026-10-29 (orchestrator, found running the CLAUDE.md-reading tests)



## Filed on arrival — 2026-10-30 (character migration validation)




## Character completion qualification findings — 2026-10-31


## Filed on arrival — 2026-11-01 (owner ruling, launcher ADR 0038 amendment)

## Filed on arrival — 2026-11-01 (release merge lane, branch `merge/upstream-v0.22.5`)


## Profile artwork qualification findings — 2026-11-01


## Filed on arrival — 2026-11-02 (landing w1101f)

## Filed on arrival — 2026-11-03 (lane w1103a-h1)


## Windows cold EOL census — 2026-11-03


## Baseline gates observed during suggestion modes — 2026-11-03



## Filed on arrival — 2026-11-04 (landing hm-land-w1104a)



## Filed on arrival — 2026-11-08 (lane w1108b-hfh)


## Filed on arrival — 2026-11-09 (lane queue-tasks-s2)


## Filed on arrival — 2026-11-10 (lane hm-rel-fix-a, v0.23.1 release gate)


## Filed on arrival — 2026-11-10 (lane hm-release, branch `merge/upstream-v0.23.1`)

- **`FH-UPSTREAM-PRS-REBASE-V0231` — Our open upstream fixes apply to the current upstream release again** · group: upstream-footprint-ledger · NousResearch/hermes-agent PRs · triage 2026-11-10 against v0.23.1: 62 open, 0 merged, 0 overtaken; 39 still apply (32 clean, 7 by 3-way); 22 conflict — simple rebases #121640 #124191 #124194 #125259 #125260 #125262 #125265 #128649 #128653 #128840 #129414 #131903 #131904 #132423, moderate #123978 #123979 #124190 #124210 #128648 #128654, non-trivial #125263 (drop the dead browser/service_manager hunks in #121640 #125262 #131903); #128841 unclear (upstream b9e983665c bounds grace re-probes for built lists; re-run the PR's repro) · folded 2026-11-15 (w1115e-rr2, owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"): the 22 held-PR rows are closed into this one, each line in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` § Held upstream PRs — one record (2026-11-15): FH-AUTH-TRANSPORT-PRS feat/auth-on-verification + feat/plugin-cli-commands unopened; FH-DEFER-PR-128649-SHARED-TLS #128649 open, needs rework (certifi rotation); FH-DEFER-PR-REGISTRY-SNAPSHOT-RESTORE body drafted, not posted; FH-DEFER-PR-SELF-REPO-GUARD-VARS no branch, seam on main; FH-FOOTPRINT-WOVEN-CHECKPOINT-RPC two door asks, one lane each; FORK-18-CARRIED-PR-PAIRS #119069 #121642 #125259 #125261 #125263 #125264 #128648 #128652 differ in logic; FORK-24-UPSTREAM-PR-BRANCHES 24 idle branches, bodies in worktrees/pr-bodies/; FORK-FULL-RE-AUDIT-FOUND nine fixes, no branch; FH-SEAMS-PLAN-STAGE-3-AND-7 P1–P5 unopened; FH-DEFER-PR-J2A-HOSTED-ROOM-LIMITS / J2-B0-OMISSION-RESERVE / J2B-HOSTED-ROOM-PINS unopened, code on main; FH-RECORDED-PARALLELS-PAR-2-6 seven held branches; RT-DOOR-PR-LANDS-UPSTREAM the delete-the-hunks rule; RT-DOORS-SHEET-C-PART-B no branch; RT-FOUR-UPSTREAM-DOOR-PRS three door branches unbuilt on h-doors; RT-OFFER-SDK-FREE-HTTPX unopened; RT-QUALIFY-HELD-CHECKPOINT held, no submission authorized; RT-RECOVERY-DOOR-PRS four doors unopened; RT-HOSTED-ROOMS-CANNOT-MOVE widening PR unopened; RT-RETIRE-COMPUTE-HOST-COLD up/compute-host-hello-budget fd282272f8e unopened; FORK-PR-RUN-TESTS-PARALLEL runner series unopened, #125263 body to fix. Owner deferrals carried unchanged: 2026-10-16 "pr branches should remain idle", 2026-10-24 "defer prs but make sure the code needed is on our main", 2026-10-15 "no sign upstream wants them", 2026-10-10 "parked stays parked" · DEFERRED 2026-11-12: owner — no force-push for now ("all as reccomended is good"; at the upstream PR limit since 2026-11-10); until the owner reopens it · waits: owner-ruling · was waiting since 2026-11-11 on the owner's word to force-push the 18 ready rebased PR branches (one commit each on v0.23.1; the lane's force-push was refused by the permission system, owner ruling 2026-11-11: no pushes, no new PRs, no comments) · Recommend: review and run `/home/nekwo/Eternia/worktrees/_w1110d/uprebase_v0231_push_commands.sh` on nekwo-ubuntu24 (--force-with-lease pinned to each PR's old head; local branches rebase-v0231/<pr> in the hermes repo); close #128841 as overtaken; after the push, a lane fixes #128649 and #124190 and splits #125263 (below) · handoff 2026-11-10 (w1110d-foot): dry-run rebase of all 22 conflict branches onto upstream/main 0325fc7c60 (1,093 commits past v0.23.1): every one conflicts — up/doc-accuracy (service_manager.py), up/skills-extra-dirs (prompt_builder, skill_utils, skills_tool), up/local-runtime-knobs (local_runtime bootstrap/presets), fix/readonly-config-reads (config.py, dashboard_auth/_shared, vision_tools, test_image_generation), fix/doctor-call-time-home (doctor_config, doctor_state), fix/win-path-identity (approval_detection, browser_tool_lifecycle), fix/updater-fork-history (desktop-update posix.sh, windows.ps1), up/tls-shared-platform-context (ssl_verify + test), feat/plugin-session-info-tool-names (system_prompt), fix/bytecode-sweep-lock (main_web_build), widen/processes (process_registry), widen/misc (profiles), feat/model-skill-search-tool (toolsets + two website refs), widen/per-call-usage-record (codex_runtime), widen/register-toolset (plugins, registry, toolsets), up/store-home-override (hermes_constants), up/persisted-row-hooks (6 agent/ files), feat/plugin-cli-commands (main, plugins, plugins_manifest), refactor/oauth-flow-catalog (web_server_oauth), fix/test-runner (run_tests_parallel), fix/tool-registry-probe-cache (registry), refactor/tui-gateway-methods-pdf (methods_prompt, server); nothing pushed. Likely fix: one rebase lane per PR (or 3-4 PRs per lane by shared file), each re-running the PR's own tests on upstream/main before a force-push; #129412/#129413/#129414 are no longer carried by the fork (psutil stand-in, launch_relaunch, pdf.attach upstream bytes) — owner call whether to keep offering them upstream · handoff 2026-11-11 (w1110d-uprebase): rebased LOCAL ONLY onto v0.23.1 3b42157858 as one squashed commit per PR (the net PR diff; the branches' upstream-main merges dropped; each commit body lists the original commits and every resolution), each PR's touched tests plus neighbours run on ~/.venvs/hermes-release-v0231, ruff clean on touched files; nothing pushed. READY (18): #121640 (dead service_manager hunk dropped) #124191 #124194 #125259 #125260 #125262 (dead browser_tool_lifecycle hunk dropped; 2 reds not its own: test_tts_mistral key_missing is red on bare v0.23.1 in the same file set, order pollution; test_repeated_launcher_words_scan_in_linear_time 2.05 s vs its 2 s budget under box load, 1.2-1.7 s alone like v0.23.1) #125265 (test_desktop_update_shim_profile_cleanup red on bare v0.23.1 here; handoff_protocol timing test passes alone) #128653 #128840 (v0.23.1's _prune_dropped_directories now runs inside the locked sweep) #129414 (fork no longer carries it: owner call to keep offering) #131903 (dead browser_tool_lifecycle hunks + test dropped; v0.23.1's new callers in process_registry_ownership and browser_launcher renamed) #131904 (re-derived as renames on v0.23.1, incl. new callers session_group_controls and windows_ssh_runtime) #132423 (skill_search first sentence shortened to fit v0.23.1's 80-char catalog check) #123978 #123979 (mixin moved to plugins_context.py) #124210 (its stdio-MCP HERMES_HOME part is upstream now, dropped) #128648 (parent= moved to plugins_context.py) #128654 (copilot-acp row dropped like upstream). NEEDS WORK (2): #128649 — under truststore it hands every caller one platform context, which skips v0.23.1's certifi-rotation repair: 4 v0.23.1 tests red, incl. the end-to-end test_rotated_process_keeps_trusting_the_bundle_it_was_configured_with (a private CA in the certifi bundle is no longer trusted); fix: build the shared context from the live certifi bundle (or keep True when a bundle is configured) and adapt the rotation tests; #124190 — tests green (one order-dependent red, test_a_split_unit_labels_its_failed_task_with_that_tasks_goal, passes alone), but v0.23.1's worker-delegation writer (gateway/session_worker_delegation.py) inserts async_delegations rows through the session DB in the profile's state.db, so with a background_work override those rows sit outside the ledger the sweep and replay read. ASSESSED (2): #125263 — applies with one conflict (-j default; trial branch rebase-v0231/125263), but red on v0.23.1's test_fork_server_reports_failures_and_kills_stragglers (asserts the old 'Ns exceeded; process tree SIGKILL'd' wording the PR rewrites), and its min(cpu_count, 8) worker cap runs against v0.23.1's fork-server runner (4ca478075f, 904418490c): recommend splitting it — keep the bounded isolation retry and the cygpath runner path with upstream's timeout wording, drop the cap or re-justify it with a measurement on the fork-server runner; #128841 — its repro (tests/tools/test_registry_grace_reprobe.py) is still red on v0.23.1 for direct _check_fn_cached lookups (3 probes where it wants 2), but upstream b9e983665c bounds the hot path it was for (tools[] builds and tool_call via check_fn_verdict_window, a grace-served list reused 5 s, same constant); what is left are per-pass memoized status reads (hermes tools, dashboard): recommend closing #128841 as overtaken

## Filed on arrival — 2026-11-10 (lane w1110d-foot)


## Filed on arrival — 2026-11-12 (lane w1112b-hm-realm2)


## Filed on arrival — 2026-11-12 (lane w1112b-hm-settle)



## Filed by review batch w1114a.9 — 2026-11-14 (qashell's NEEDS line)

## Filed on arrival — 2026-11-15 (wave w1115k landing)


## Filed on arrival — 2026-11-17 (lane w1116b-rtfu)


## Filed on arrival — 2026-11-18 (side session w1118-slotstatus)


## Filed on arrival — 2026-11-20 (Eternia lane w1120a-unseated)


## Filed on arrival — 2026-11-20 (review w1118a.63: what hermes lane w1118a-hrt3 reported)


## Filed on arrival — 2026-11-20 (lane w1120a-slotrules: a red the prepush met)
- **`FH-FU-THE-SLOT-SETUP-SHELL-TESTS-FAIL-ON-WINDOWS` — Four slot set-up script tests fail on Windows, so every Windows prepush that touches slots reads red** · group: hermes-test-isolation · from: `MC-A-FOLDER-SLOT-CHOOSES-WHICH-RULES-FILE-ITS-AGENT-READS` (EterniaLauncher, lane w1120a-slotrules) · seen 2026-11-20 on DESKTOP-QJ7DDV2 (Windows): `tests/agent_runtime/test_workspace_slot_clone.py` 4 failed (`test_run_needs_the_script_the_person_was_shown`, `test_nothing_runs_on_its_own`, `test_run_step_refusals_are_typed`, `test_the_shell_door_runs_powershell_on_windows`); one reads `script_shell(Path("/r/linux.sh"), windows=False)` as `['bash', '\r\linux.sh']`; `--confirm-red` verdict pre-existing (red on origin/main) · guess: the tests build POSIX paths with `Path` and compare strings, so Windows renders backslashes · done when: the file is green on Windows and Linux · REQUIRES windows · review w1118a.66: passed; one of the four read in code and confirmed — `tests/agent_runtime/test_workspace_slot_clone.py::test_the_shell_door_runs_powershell_on_windows` builds `Path("/r/linux.sh")` and compares the string `"/r/linux.sh"`, which a Windows `Path` writes with backslashes; the other three are not read, the guess stands for them · the fix is test-only (`PurePosixPath`, or comparing paths rather than strings); the product's `agent_runtime/host_tools.py::script_shell` is right on its own host · the Windows host requirement stays: the reds are seen only on Windows and a Windows run confirms the fix · no decision; not churn: it reds every Windows prepush that touches slots · file map: `tests/agent_runtime/test_workspace_slot_clone.py` · no other open row in the file (swept) · size XS · reviewed 2026-11-20 w1118a.66 · READY 2026-11-20
- **`FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET` — Landing a change to the conversation engine passes the touched-tests step inside its budget** · group: prepush · from: `RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT` (lane w1118a-onepath-hm2) · seen 2026-11-21 (Linux box, prepush at head 7030105df1, load 11.53, work 18): `touched slow: 74.1s against budget 60s (deadline 120s)`; the file alone `tests/agent_runtime/test_native_large_recovery.py` took 72.82 s, green · read in code: each parametrized case boots a real in-process conversation worker and a large recovery; the compute case starts a compute host · guess: the file is near the budget on its own, so any landing that touches it overruns; split the inline and compute cases into two files (as the stop table was split) or move the compute case to the bench tier · review w1118a.71: passed with a rewrite, as the design-fix row for both touched-step overruns; read in code — `scripts/prepush.sh` already shards a touched file whose last run was 20 s or more (`_last_seconds`, up to 4 node-id shards), but it reads only the tree's own untracked `test_durations.json`, so a fresh lane tree (or a file it never ran) runs the file whole on one worker; the record for this file appears only in the tree that overran (`test_native_large_recovery.py` 72.8 s), and the same gap explains `FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-EMBEDDED-PHONE-SESSION-FILE` (4 tests, 61 s, one worker) · design flaw: the shard decision has no answer on a tree's first push · architecture: prepush only — when the tree has no record for a touched file, the shard decision falls back to a shared record (the runner's last full-run durations, or a slow marker such as `slow_native` / `e2e_child` meaning one shard per test), never a raised budget (owner 2026-11-13); splitting this file stays the fallback only if one case alone overruns, which the lane profiles first (the 5 MiB payload per case is the cost) · done when: on a fresh lane tree with no `test_durations.json`, touching this file runs its two cases side by side inside the 60 s budget on this box, pinned by the prepush script's own test with no record present (red with the fallback dropped) · file map: `scripts/prepush.sh`, `tests/scripts/test_prepush_sh.py` · order: before the phone-session row, which then closes if the fallback brings it under budget · size S · review w1118a.75: absorbs `FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-ROSTER-BYPASS-CONTRACT-FILE`: its done-when also covers a touched file whose recorded time is one test's (`tests/agent_runtime/test_persona_roster_bypass_contract.py`, one ~30 s walk), which runs whole instead of sharding into a timeout and a retry · reviewed 2026-11-21 w1118a.71 · READY 2026-11-21
- **`FH-INHERITED-E2E-TESTS-NEED-NO-SPECIAL-TIME-LIMIT` — The inherited real-gateway e2e tests run fast enough to need no special time limit** · group: prepush · from: `owner 2026-11-21` ("a don't forget to track upstream code", option (a): land the measured limits, file the speed-up separately; lane w1118a-hlimits) · seen 2026-11-21 (daily full run, hermes origin/main, -j 24): 57 upstream test files killed at the fork's 30 s per-test default with no result and 64 more killed once then green on retry; the retry phase outran the 5400 s step cap · read in code: each test boots one or more `python -m gateway.run` daemons (~5 s quiet, 10+ s under suite load), often twice across a restart, or spawns managed workers; slowest test per file 10-152 s at -j 24 · held for now by 99 measured per-file limits, `tests/_downstream/id_markers/fork_marks.py::_MEASURED_E2E_WALLS` (3x the wall, floor 90 s; 526c3c3eae), pinned to each file's upstream blob by `tests/tooling/test_measured_e2e_limits_track_upstream.py` · guess: one gateway daemon shared by every test in a file (a module-scoped fixture beside the per-test one, reset between tests) and a faster gateway boot (lazy imports, no plugin scan or state.db migration on a test home) would bring each test under 30 s; the fix lives in fork-owned fixtures or seams (these are upstream files, edited additively or not at all) · done when: every file leaves `_MEASURED_E2E_WALLS` because its slowest test runs under 30 s at -j 24 on this box, the table is empty and its gate deleted with it · review w1118a.76: passed; owner-ruled option (a) 2026-11-21 (land the measured limits, file the speed-up); a speed row, so a fork-hygiene speed lane takes it, never a feature lane; `TASK-PREPUSH` stays DEFERRED (not touched) · architecture: test-side and fork-owned only — a module-scoped gateway fixture beside the per-test one, reset between tests, and a lighter gateway boot for a test home, both in fork seams (`tests/_downstream/`, fork conftest hooks); upstream test files are not edited (additive only, owner's upstream-footprint rule); `_MEASURED_E2E_WALLS` is shrink-only — a file leaves it when it runs under 30 s, the table never grows or loosens · security: a shared gateway must not carry one test's tokens, pairing state or home into the next (reset proves it); test-only otherwise · split: by file family (gateway restart, managed workers, platform adapters) so several lanes can take slices without touching the same fixture · edge cases documented, not worked: a test whose restart is the thing under test keeps its own daemon · same-file sweep: `fork_marks.py` and `_MEASURED_E2E_WALLS` are cited by no other open row; the prepush touched-step rows touch `scripts/prepush.sh`, not these · size L · reviewed 2026-11-21 w1118a.76 · READY 2026-11-21
- **`FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-REGISTERED-EVENTS-EMITTER-FILE` — A push that touches the operator chat turn waits two minutes on one event-emitter test file, so the touched-tests step is cut off and owed** · group: prepush · from: `RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT` (lane w1118a-enginefold landing 939f70e5c8) · seen 2026-11-21: `scripts/prepush.sh` touched step killed at its 120 s hang guard (budget 60 s, work 45, load 16.79); `tests/agent_runtime/test_s55_registered_events_have_emitters.py` alone ran 117 s, 5 tests (`_lane_logs/prepush_overruns.jsonl` line 2026-11-21T19:48:32Z) · guess: that file parses the whole fork source per test, so any change to the turn path pays it · done when: the touched step finishes a push that touches `agent_runtime/operator_turn_policy.py` inside its budget on an idle box, or the file leaves the touched set with the reason · review w1118a.77: passed with a rewrite; premise corrected in code: the tree is parsed once per process, not per test (`_production_trees_cached`, `lru_cache`, l.182, through the shared `source_cache`; pinned by `test_the_shared_walk_is_paid_at_import_and_not_by_whichever_test_runs_first`), and the file holds 13 tests; its whole-file record is 103.9 s (`test_durations.json` in the enginefold tree), so the cost is one whole-tree walk that no node-id shard divides: every shard pays it again · design flaw (cluster): a whole-tree source gate rides the touched step as if it were a unit test file; the same as `FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-ROSTER-BYPASS-CONTRACT-FILE` (merged into `FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET` by review .75); that row's run-whole rule does not save this file, which overruns even whole · architecture: reuse the seam `scripts/prepush.sh` already has for this kind: the name census gates run in their own step with their walks pooled over workers (`PREPUSH_CENSUS_GATES`, `scripts/census_pool.py`); route this `pytest.mark.gate` file there, or pool its walk the same way; never a raised budget (owner 2026-11-13); first step: profile the import walk against the two builders on an idle box · security: test tooling only · file map: `scripts/prepush.sh`, `tests/scripts/test_prepush_sh.py`, `tests/agent_runtime/test_s55_registered_events_have_emitters.py` only if the walk itself changes · same-file sweep: the other `scripts/prepush.sh` rows (`FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET`, `FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-EMBEDDED-PHONE-SESSION-FILE`, `FH-PREPUSH-GATES-KILLED-AT-HANG-GUARD-UNDER-LOAD-48`, `FH-INHERITED-E2E-TESTS-NEED-NO-SPECIAL-TIME-LIMIT`) go to the same lane, after the native row; `TASK-PREPUSH`'s status is the coordinator's and is not touched · size S · reviewed 2026-11-21 w1118a.77 · READY 2026-11-21

