---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue

- **`RT-FLAKE-DISCUSSION-GROUP-MIGRATION-UNDER-LOAD` — `tests/agent_runtime/test_discussion_group_migration.py::test_atomic_adoption_preserves_log_member_ids_defaults_and_continues_natively` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/agent_runtime/test_discussion_group_migration.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it
- **`RT-MACHINE-ROOTS-FOLD-BREAKING` — fold `machine_roots.json`'s five maps (`roots`, `config_roots`, `workspace_roots`, `slot_folders`, `project_roots`) to `roots` (config roots, the one map the launcher's `qa_mcp_server_freshness.dart` reads) + one owner-keyed slot map (`<ws>` / `project:<id>`, the keys `MachineRoots.slot_folder_bindings` already speaks), schema 5, with a migration** · group: agent-config-cleanup · `agent_runtime/machine_roots.py::write_machine_roots` · `agent_runtime/machine_roots.py::_read_registry_file` · `agent_runtime/store_epoch.py` · found 2026-11-02 by lane w1102c-rt (RT-BRAIN-PATHS-PLAIN-LIST slice 3, left): dropping the mirrored keys is BREAKING by `store_epoch.py`'s own entry `machine-roots-schema-3-named-halves` ("dropping the old keys is a later breaking entry") — an older edition reads a schema-5 file as schema 1 (no `workspace_roots`), migrates it in `workspace_slots.scoped_roots` and rewrites it with every slot fill gone; the fold is the store's FIRST breaking epoch raise (STORE_EPOCH 1 → 2, the consent flow for every namespace) · DEFERRED 2026-11-02: owner "reccomendations sound good" — fold it in the next breaking store-epoch batch, never alone




## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)

- **`TASK-AGENT-CONFIG-CLEANUP` — Agent settings: each agent's folders, data, options and abilities live in one clear place** · task: agent-config-cleanup · 10 subtasks on 2026-11-09 (10 deferred) · DEFERRED 2026-11-09: owner — every live subtask is deferred (owner sittings parked 2026-11-09); until the owner reopens it
- **`TASK-AGENT-START-UP-COST` — Agents: start up and reply faster because each turn prepares and re-reads less** · task: agent-start-up-cost · 20 subtasks on 2026-11-12 (20 deferred) · DEFERRED 2026-11-09: owner triage — every subtask is deferred; until the owner reopens it
- **`TASK-DISCUSSION-ROOMS-RELIABILITY` — Discussion tables: group rooms of agents keep running, explain refusals and work in release builds** · task: discussion-rooms-reliability · 3 subtasks on 2026-11-09 (1 blocked, 2 deferred) · BLOCKED 2026-11-09: another lane — `RT-ROOM-LEASE-LAPSES-MID-CYCLE` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-ETERNIA-LENS` — Lens: agents watch your sources and report what changed** · task: eternia-lens · 3 subtasks on 2026-11-10 (1 blocked, 1 deferred, 1 needs plan) · BLOCKED 2026-11-10: owner sitting — RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS: one Close all on the owner's Windows serve for the five w1025a orphans (steps on the row) · unblocked 2026-11-10: owner deferral triage ("rest of the triage is good") reopened `RT-ETERNIA-LENS-L2-L4`; 9 deferred idea rows archived (the Lens plan keeps them) · handoff 2026-11-10 (w1110d-lens): RT-ETERNIA-LENS-L2-L4 closed DONE ea08d34880 (L4 lens_read read live on an isolated Linux serve, fixture model, red under the lens_root mutation); RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS's hermes half read live, the owner's five orphans left as owner-sitting steps; RT-LENS-SHARE-RECIPE-TO-WORKSPACE left NEEDS PLAN with a recommendation (realm sync family) · handoff 2026-11-10: w1110a-hm closed RT-LENS-SHARED-RECIPES-OPT-IN and filed RT-LENS-SHARE-RECIPE-TO-WORKSPACE (NEEDS PLAN); the one READY row, RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS, has only the live close of the owner's five orphans on the Windows box's serve left · handoff 2026-11-10 (w1110a-org): `RT-GATEWAY-START-MANAGED-PYTHON` (a gateway that will not start) moved to Eternia's `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`; its two other-feature deferred subtasks moved 2026-11-10 to TASK-BUNDLED-VOICE and TASK-CONSOLE-TRANSCRIPT-TRUTHFUL to reopen: `RT-PIPER-FIRST-AUDIO-LATENCY` (voice speed, Eternia `TASK-BUNDLED-VOICE`) and `RT-LEAN-OPERATIVE-RULES` (agent chat prompt rules)
- **`TASK-TURN-CLEANUP` — Chat turns: replies run to the end, Stop stops only what it names, nothing sent mid-reply is lost** · task: turn-cleanup · 2 subtasks on 2026-11-12 (1 ready, 1 live check — both the client's, each now waiting only on its own client work and one live read; none open in this repository) · handoff 2026-11-12 (w1112b-hm-turn5, main lane after w1112b-hm-turn4): filed and closed this sitting, each reproduced first as whole turns on `tests/agent_runtime/held_model_turn.py` — `RT-CHAT-TURN-ROW-SAYS-WHETHER-IT-TAKES-A-STEER` 22e0c2a517 (every running `chat_turn` row of `running_work` says `steerable` true or false, from the one record the steer door accepts on) and `RT-STEER-NEXT-TURN-NAMES-THE-STEER-IT-DELIVERS` bec7fe8eec (a `steer-next-…` turn states `steer_of`, a list of steer client message ids, on its journal record, its persona-history operator row and its operator-conversation message); neither was read in the app by this lane (its brief gave the live reads to the Eternia lane): `MC-CONSOLE-WORK-TURN-FOLLOW-UP-IS-QUEUED-NOT-STEERED` (LIVE CHECK) repeats its read against a hermes that states `steerable` itself, serving 3115adf1aa or later, and `MC-CONSOLE-STEER-NEXT-TURN-LINK-IS-AN-ID-PREFIX` (READY) swaps the client's id-prefix match for `steer_of` and reads it once; two findings beside the task are rows of `TASK-TURN-CLEANUP-FOLLOWUPS` · handoff 2026-11-12 (w1112b-hm-turn4, main lane after w1112b-hm-turn3): closed this sitting, each reproduced first as a whole turn (`tests/agent_runtime/held_model_turn.py`) — `RT-STOPPED-MESSAGE-HOLD-SERVED-AGAIN-NEXT-TURN` REFUTED 6566ae26e2 (the client lane w1112b-turn5 read one request, two seconds); `RT-STOPPED-TOOL-CALL-STORED-CHAT-SAYS-FAILED` 55afd05696 (`outcome` rides the persona-history trace row and the conversation `tool_call`, one carry); `RT-NEW-TURN-WAITS-ON-ANOTHER-AGENTS-MODEL-CALL` 06a61f33a8 (the POSIX whole-run `HOME` lock became a gate: another agent's slow model call no longer holds a new turn); `RT-STOPPED-HELPER-RESULT-SAYS-NOT-PROCESSED` b6085e39ee (a stopped helper's result quotes only what it wrote); left then, both in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` — `MC-CONSOLE-STOPPED-TOOL-CALL-SAYS-FAILED` (since closed there, PASS live, 49766f25b2) and `MC-CONSOLE-WORK-TURN-FOLLOW-UP-IS-QUEUED-NOT-STEERED` (since built there, f7d42e380f); this lane read none of its four changes in the app — the same client lane reads them (a stopped step after settle / next message / reload; a plain message to agent Y while agent X holds a model call; a stopped helper's delivered result) · READY 2026-11-12 · filed 2026-11-12 on the owner's word ("i think turns might be ending early or they are structured weird"; "file all of it as a turn cleanup task") from two read-only audits of the chat turn and of running work against `upstream/main` 8e7908d9ba; the inner model-and-tools loop is upstream's unchanged (`run_agent.py` zero diff); three of its rows are the client's, in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`
- **`TASK-TURN-CLEANUP-FOLLOWUPS` — Chat turns: the loose ends found while cleaning up turns are tied off** · task: turn-cleanup-followups · 2 subtasks on 2026-11-12 (1 ready, 1 decision: `RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT` reproduced, waits on the owner's answer) · filed 2026-11-12 by w1112b-hm-turn5 (owner 2026-11-12: a follow-up is a row at once under the follow-up task of its task, never a line on the task row) — findings made beside the work of `TASK-TURN-CLEANUP` that do not make its done-when false · READY 2026-11-12 · **TAKEN 2026-11-12 w1112b-hm-latesteer on nekwo-ubuntu24 as nekwo in hm-w1109a-board**
- **`TASK-REJOIN-FRESH-REALM` — Leaving and re-joining a server: your local copy stays yours, the server's realm comes back fresh** · task: rejoin-fresh-realm · 3 subtasks on 2026-11-12 (2 ready, 1 blocked); 6 closed (`RT-REKEY-ONE-OWNED-OPERATION` 808cca7fd3, `RT-REKEY-LOCAL-COPY-GETS-NEW-AGENTS` 61910337ff, `RT-REKEY-BRAIN-AND-WORKTREES-FOLLOW` 8d722abaf4, `RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE` 0d3606365a, `RT-REKEY-ID-MAP-FOR-ETERNIA` and `RT-REKEY-NOTICE-LOCAL-COPY-HAS-OWN-AGENTS` 6db8a4213e) · filed 2026-11-12 by w1112b-hm-rejoin2 on the owner's ruling "Yes, own task" · READY 2026-11-12 · handoff 2026-11-12 (w1112b-hm-rejoin3, main lane, context spent): the re-key operation is whole on main and has NO caller — a member still sees this morning's leave and re-bind; `OWED_HANDLERS` is empty. Next, in this order: `RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START` (the triggers and busy facts; handoff on the row), `RT-REJOIN-CARD-VERB-WITHOUT-BOARD-PICKS-EITHER-COPY` (file-disjoint: a row lane can take it), then the switch-over `RT-REJOIN-PULLS-THE-SERVER-REALM-FRESH` in one landing with the two-machine walk (seven open points on its handoff). Closing `RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START` wakes the switch-over row while the card row still holds it: re-block it in the same sitting (`RT-QUEUE-CLOSE-WAKES-ROW-STILL-HELD-BY-OTHERS`). Follow-ups are rows under `TASK-REJOIN-FRESH-REALM-FOLLOWUPS` · **TAKEN 2026-11-12 w1112b-hm-rejoin4 on nekwo-ubuntu24 as nekwo in hm-w1109a-2**
- **`TASK-REJOIN-FRESH-REALM-FOLLOWUPS` — Loose ends found while building leave and re-join: queue-tool gaps, a shared task repository** · task: rejoin-fresh-realm-followups · 5 subtasks on 2026-11-12 (5 ready) · filed 2026-11-12 by w1112b-hm-rejoin3 (owner 2026-11-12: follow-ups are rows at once, under the task's follow-up task) · READY 2026-11-12

## Ownership refresh — 2026-10-08

The 2026-10-07 sol-runtime worker is idle after its completed batch; the coordinator finished reviewing the waves. Its eight unfinished claims below are released before reassignment. Release does not mark work done or discard prior branch changes, PENDING verdicts, prerequisites or capture evidence. New work must take a fresh claim. The later daily-upstream lane is a separate assignment.

Mission Control is one surface across two repos. **This file holds the rows whose fix lives in this repository**; the launcher's half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`, and a finding that needs both sides is filed on the side that must move first, with the other side named in the row. Ruling: [[0012 — The hermes half of Mission Control is queued here, split by ownership]] (amends [[0011 — One brain per repo, one Mission Control queue in the launcher]]).

Rows are one line and a pointer; claim with `**TAKEN <date> <who>**` before starting; the landing commit deletes the row; a ` · VERDICT <date>:` suffix is an owner decision, not lane work. Repo-relative paths are this repo's; another repo's file is cited with its prefix in backticks (`EterniaLauncher/…`).

**The three headings are the [[Fork Boundary Map]]'s three kinds of file**, and they decide what a lane may do:

| heading | what it means | what a lane does |
|---|---|---|
| Fork-owned | the file is absent from `upstream/main` (`agent_runtime/`, `hermes_cli/harness*`, fork-only modules and tests) | refactor freely; never conflicts on merge |
| Seams | an upstream file the fork already edits (`gateway/hosted_rooms.py`, `agent/credential_pool.py`, `hermes_cli/auth.py`, `hermes_cli/codex_models.py`, …) | ADDITIVE edits only, one import and one call at a stable point; every sync conflicts here |
| Upstream-owned | an upstream file the fork does not touch | never edited here: a caller-side memo or seam on our side, a marker, or an upstream issue/PR |

Rows below were moved verbatim from the launcher queue on 2026-09-22 (their provenance headings are kept as sub-headings). Fork-hygiene findings the launcher queue carried (CI, the suite, the mutation gate, upstream reds) went to [[fork-hygiene-queue]] in the same commit.

## Fork-owned

### Filed on arrival — 2026-11-12 (lane w1112b-hm-turn5: what Eternia lane w1112b-turn6 read live of a steered Work turn)

- **`RT-HEADER-SAYS-STANDING-BY-AFTER-A-RUNTIME-STARTED-TURN-BEGAN` — The agent header says a reply is running as soon as the agent starts one by itself** · group: turn-cleanup-followups · `agent_runtime/chat_turn_presence.py` · `hermes_cli/harness_parts/persona/chat_turn_commit/run.py` · found 2026-11-12 (Eternia lane w1112b-turn6, `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-12/TASK-TURN-CLEANUP/w1112b-turn6/README.md`) · seen live: ONE sighting, not timed — 5 s after the helper-result turn of Base started (14:25:30Z) its console header still read "Standing by" (14:25:35Z); a minute later it read "Turn running · 50 s"; the box was at load about 30 · read in code, not reproduced (w1112b-hm-turn5): every turn through the mission-chat door, whoever started it, publishes its start from `_write_ahead` (`presence.publish_started`) once the journal record persisted, with no gate on `stream` or `requested_by` — so the runtime does not skip the start of a runtime-started turn; not read: when a forged turn reaches its write-ahead after the delivery drain picks it (the 14:25:30Z clock may be the drain, not the write-ahead), how long the hub takes to build the frame at load, and what the header reads (the presence row or the state of its own send) · guess: a late frame under load, or a header that follows only turns the console sent · handoff 2026-11-12 (w1112b-hm-turn5): first step is an Eternia live read — start a helper, note the `write_ahead` instant in the turn journal `phases`, the instant the `chat_turn` row first appears in a `running_work` frame, and the instant the header changes; the layer that owns the gap owns the fix (move this row to the Eternia queue if it is the header) · done when: the three instants are read once on a quiet box and either the gap is under a second or the owning layer has a row that says why · READY 2026-11-12
- **`RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT` — A steer you typed at a task run that arrives too late runs next as your own message, not as part of the task run** · group: turn-cleanup-followups · `hermes_cli/harness_parts/persona/chat_turn_commit/leftover_steer.py` · `agent_runtime/chat_root_send_queue.py` · found 2026-11-12 (w1112b-hm-turn5, building `RT-STEER-NEXT-TURN-NAMES-THE-STEER-IT-DELIVERS`) · read in code, not reproduced: a `steer-next-…` turn is queued with a copy of the send of the turn the steer was typed at (`persistable_args`) with only message, ids, `new_session`, `clarify_token`, `retry_of`, `title` and `idempotency_key` replaced, so a steer typed at a Work turn runs as a turn whose `requested_by` is still `work:<request>` (and whose `max_seconds`, skills and origin are those of the Work turn) though the operator typed it · seen in a test: `tests/agent_runtime/test_chat_turn_row_says_steerable.py` shows a `requested_by work:` turn starts the steer watcher, so such a turn reads `steerable` true for that reason and not because an operator is watching a stream · guess: it is also unattended and budgeted as a Work turn, and anything that keys on the requester (not on the client message id) could count it toward the Work run; seen live by w1112b-turn6 only that it ran and answered · siblings: `RT-STEER-ONLY-STREAMING-TURNS` (closed 7df8385a42), `RT-STEER-NEXT-TURN-NAMES-THE-STEER-IT-DELIVERS` · handoff 2026-11-12 (w1112b-hm-turn5): reproduce on `tests/agent_runtime/held_model_turn.py` (a Work turn, one late steer, run the queued entry) and read the requester and budget of the next turn and the settle of the Work run; decide with the owner what a late operator steer at a Work turn should run as · seen in a test 2026-11-12 (w1112b-hm-rejoin4b, `tests/agent_runtime/test_late_steer_at_a_work_turn.py`, whole turns on nekwo-ubuntu24): reproduced. A Work turn queued as `PersonaTurnExecutor.start_from` queues it, held at the model, takes a steer that lands in no tool round; the queued `steer-next-…` send carries the Work turn's `requested_by work:<request>`, its `max_seconds` and its whole `send_origin` (`kind: work`, the request, its rows — `persistable_args` copies the Work entry's own origin over the fresh one). Run, it reads `steerable` true with no `work_request` on its `running_work` row, a steer late for IT is queued as a third turn of the same request, and at its end the Work executor reports the request ended a SECOND time as that turn (`work.exec_settle`, verdict failed — a chat reply has no work report); the request had already been reported ended on the Work turn's reply before the late message was read · read in code, not reproduced: the Work engine (`agent_runtime/work_store/engine.py` `on_settle`, record already settled) and the batch dispatcher (`agent_runtime/batch/dispatcher.py` `settled`, lane no longer running) drop that second report; a batch lane's late turn also inherits the lane's working folder and lent skills (the same copy); on a chat bound to an until-done run every turn's settle already feeds the run's after-turn hook (`PersonaTurnExecutor.settled`), so there a late steer is part of the run by design · options: (A) an ordinary chat message — the late turn is queued as the operator's own send (their requester, the chat's default budget, no Work origin, the agent's normal folder); the task card shows the task as it ended, the late message is answered in the chat like any message, and the task is reported ended once; (B) part of the task — the run is not reported ended until the late turn ends and that turn's reply decides the result; the board shows the task still running and tags the late turn to it; needs the run's ending to wait on the chat's queue, the late turn told to write a work report, and a bound on steers that keep arriving; (C) leave it and only stop the second report — the turn stays labelled as the task while changing nothing of it · Recommend: (A) for one-shot and batch-lane Work turns — the run has already ended and been judged when the late message is read, and (B) would make every lane's landing wait on chat; leave until-done runs as they are · handoff 2026-11-12 (w1112b-hm-rejoin4b): the test's assertions marked TODAY are the ones the ruled answer changes; for (A) the change is in `leftover_steer.queue_leftover_steer` and `_requeue_from_ledger` (what the queued send keeps of the send it was typed at) and `requeue_dead_turn_steers` reads the same `send_args` · done when: a test states what a late steer at a Work turn runs as, and the owner has agreed it · RULED 2026-11-12: owner "it should be an ordinary chat message" — option A for one-shot and wave-lane tasks (the late message runs as the operator's own chat turn, the task is reported ended once and its card shows it as it ended); until-done runs stay as they are. The question put was: you type a message at a running task and it arrives too late to change that run — should it run next as an ordinary chat message from you (A), or count as part of the task and be able to change the task's result (B)? Today it is neither: it runs with the task's settings but the task has already been marked ended · READY 2026-11-12 · **TAKEN 2026-11-12 w1112b-hm-latesteer on nekwo-ubuntu24 as nekwo in hm-w1109a-board**

### Filed on arrival — 2026-11-12 (lane w1112b-hm-realm2: closing the realm move rows)


### Filed on arrival — 2026-11-12 (lane w1112b-hm-leftrealm: closing `RT-LEFT-SERVER-REALM-STAYS-LISTED`)


### Filed on arrival — 2026-11-12 (lane w1112b-hm-realm: the owner's ruling on `MC-MANAGE-WS-REALM-ARCHIVE`)


### Filed on arrival — 2026-11-12 (wave w1112a: the owner's own read of Details' Tasks card)


### Filed on arrival — 2026-11-12 (Eternia lane w1112b-worklive2, live on hermes 7bb8dbd9f6: `MC-SUBAGENT-SMOKE`)


### Filed on arrival — 2026-11-12 (Eternia lane w1112b-work3, live on hermes 7bb8dbd9f6: the two shared-work live checks)


### Filed on arrival — 2026-11-12 (Eternia lane w1112b-work2: `COMP-WORK-V1-DECIDE-SCHEDULES`, `COMP-WORK-V1-DECIDE-GOAL-MODE`)



### Filed on arrival — 2026-11-10 (lane w1110c-hmboot: `RT-HARNESS-SERVE-COLD-BOOT`)


### Filed on arrival — 2026-11-09 (Eternia lane w1109a-workpill: `COMP-WORK-WAVE-STARTED-AFTER-LANES-ENDED`)


### Filed on arrival — 2026-11-09 (Eternia lane w1109a-console3: the Harness card places notices by their title)

### Filed on arrival — 2026-11-09 (lane w1109a-hm-2: live check of `RT-WORK-DEFAULT-BRAIN-HEAL-STALE-CHECKOUT`)


### Filed on arrival — 2026-11-08 (lane w1108c-hm-reds-fork: daily full-run load flakes, `FH-W1108C-WAVE-END-REDS`)

- **`RT-FLAKE-COMPARE-IMPORT-CALLER-UNDER-LOAD` — `tests/agent_runtime/test_compare_import_caller.py::test_compare_import_preserves_source_actor_across_prepare_and_finish` times out under load ("condition did not become true", `tests/agent_runtime/test_discussion_runtime.py:134` wait helper); make its wait event-driven or its budget load-proof, never a bare retry** · group: upstream-load-flakes · fork-owned · `tests/agent_runtime/test_compare_import_caller.py` · found 2026-11-08 by w1108c-hm-reds-fork: red in the w1108c daily full run on main f353a2a4ed (beside Eternia's full fake tier, load high); green alone 4× (one run, then 3 more at -j 4) and once with its three siblings at -j 24 on 95ca419262 · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it
- **`RT-FLAKE-CONSOLE-SUGGESTION-MODES-UNDER-LOAD` — `tests/agent_runtime/test_console_suggestion_modes_native.py::test_manual_rpc_observation_click_and_owner_fences` times out under load ("timed out after 5s waiting for the condition", `tests/waiting.py:45`); make its wait event-driven or its budget load-proof** · group: upstream-load-flakes · fork-owned · `tests/agent_runtime/test_console_suggestion_modes_native.py` · found 2026-11-08 by w1108c-hm-reds-fork: red in the w1108c daily full run on main f353a2a4ed (beside Eternia's full fake tier, load high); green alone 4× (one run, then 3 more at -j 4) and once with its three siblings at -j 24 on 95ca419262 · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it
- **`RT-FLAKE-DISCUSSION-RUNTIME-CLARIFICATION-UNDER-LOAD` — `tests/agent_runtime/test_discussion_runtime.py::test_clarification_resumes_same_member_session_with_fresh_turn_identity` times out under load ("condition did not become true", its own wait at line 134); make the wait event-driven or load-proof** · group: upstream-load-flakes · fork-owned · `tests/agent_runtime/test_discussion_runtime.py` · found 2026-11-08 by w1108c-hm-reds-fork: red in the w1108c daily full run on main f353a2a4ed (beside Eternia's full fake tier, load high); green alone 4× (one run, then 3 more at -j 4) and once with its three siblings at -j 24 on 95ca419262 · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it

### Filed on arrival — 2026-11-10 (launcher lane w1110a-office: `MC-PROFILE-NAME-REVERTED-ON-RELAUNCH`)


### Filed on arrival — 2026-11-08 (launcher lane w1108c-work: `COMP-WORK-ADD-TASK-HARNESS-NOT-CONFIRMED`)


### Filed on arrival — 2026-11-08 (launcher lane w1108c-mc-console: `MC-USAGE-PROBE-PROCESS-PROFILE-NOT-AGENT`)


### Filed on arrival — 2026-11-06 (lane w1106a-hm: RT-NO-MODEL-CHAT-SENDS-AND-404S)


### Filed on arrival — 2026-11-04 (launcher lane w1104a-mc-board: `MC-BOARD-DRAG-USE-WORK-MOVE`)


### Filed on arrival — 2026-11-04 (launcher lane w1104a-mc-runtime: `MC-REALMLESS-WORKSPACE-UNREACHABLE`)






### Filed on arrival — 2026-11-03 (launcher planning lane w1103a-p-work-v1: the Work board — truth, waves, the Intelligence mount, metrics)

### Filed on arrival — 2026-11-03 (lane w1103a-h1: RT-WORK-WORKSPACE-BRAIN-KEPT)


### Filed on arrival — 2026-11-02 (launcher planning lane w1101h-p-archive: closed rows archived, not deleted)


### Filed on arrival — 2026-11-02 (lane w1101g-h: work.list reads every board)


### Filed on arrival — 2026-11-02 (launcher lane w1101f-mcq: Board › Queues after Create brain, w1101d-live)


### Filed on arrival — 2026-11-01 (launcher planning lane w1101d-p-groups: queue row groups)


### Filed on arrival — 2026-11-01 (lane chat-rows: Neko calculator chat, `persona chat history` transcript audit)


### Filed on arrival — 2026-11-01 (owner: folder-slot context file toggles)


### Profile artwork — 2026-11-01 (owner approved)



### Filed on arrival — 2026-10-31 (launcher plan MC-WORKSPACE-TODO-ALL-PROJECTS, owner-approved)


### Filed on arrival — 2026-10-31 (owner sitting: the launcher's Board › Queues refused `branch_missing`)


### Filed on arrival — 2026-10-31 (lane w1031d-h)


### Filed on arrival — 2026-10-31 (launcher planning lane w1031c-plan)


### Filed on arrival — 2026-10-30 (owner: generated-tree parity with coding-harness file tools)


### Shared character assignment — 2026-10-30



### Filed on arrival — 2026-10-30 (launcher planning lane w1030p-mcaddr: `MC-ADDRESS-VALUE-LAUNCHER`)


### Filed on arrival — 2026-10-29 (lane w1029c-h-a)


### Filed on arrival — 2026-10-29 (landing w1029c-h-land)


### Filed on arrival — 2026-10-29 (landing w1029b-h-land)


### Filed on arrival — 2026-10-29 (lane w1029b-h-proj)


### Filed on arrival — 2026-10-29 (lane w1029a-h-fork)


### Filed on arrival — 2026-10-29 (lane w1029a-h-proj, the Project slot slices)


### Filed on arrival — 2026-10-29 (launcher planning lane w1029p-genui)


### Filed on arrival — 2026-10-28 (planning lane w1028p-taskbound)

### Filed on arrival — 2026-10-28 (lane w1028p-officestorm, the page-open storm plan)


### Filed on arrival — 2026-10-27 (orchestrator, from lane w1027k-h-rt)


### Filed on arrival — 2026-10-29 (lane w1029a-h-rt-b)


### Filed on arrival — 2026-10-27 (launcher lane w1027k-plan-host)


### Filed on arrival — 2026-10-27 (lane w1027k-h-local)


### Filed on arrival — 2026-10-27 (lane w1027j-h-tri-b, planned/ triage)

- **`RT-READ-MODEL-RESIDUE-NEXT-BUMP` — the retired read model's three dead config fields (`ReadModelConfig.enabled` / `serve_snapshot_from_db` / `db_filename`) still ride every snapshot through `core.runtime_config`; delete them inside whatever change next bumps `SNAPSHOT_CONTRACT_VERSION` (goldens and the launcher mirrors in lockstep), then shrink doc 02's RETIRED section — never a bump of its own** · group: agent-config-cleanup.read-model-residue-removal · fork / snapshot wire · `agent_runtime/runtime_config.py::ReadModelConfig` · plan `docs/agent-runtime-harness/planned/read-model-residue-removal.md` · DEFERRED 2026-10-27: the plan's ruling "Do not pay a bump just for this — ride the NEXT bump taken for any reason" — until a change bumps `SNAPSHOT_CONTRACT_VERSION` (54 at `agent_runtime/snapshot/context.py`); no queued row bumps it (lane w1027k-h-rt)

### Filed on arrival — 2026-10-27 (lane w1027j-h-tri-a, planned/ triage)

- **`RT-CORE-CACHE-HOME-MISMATCH-PROOF` — HC-3's live read is owed: ten serve boots on the operator's single-profile install with zero `reason=home_mismatch` and zero `fingerprint_home_lazy_capture` (the census counts the lazy receipt as its own defect family since lane w1027k-h-rt: `home_lazy_capture`, verdict `home_lazy_capture`, script exit 3)** · group: agent-start-up-cost.core-cache-home-capture-timing · fork / core cache · plan `docs/agent-runtime-harness/planned/core-cache-home-capture-timing.md` gate 1 · `agent_runtime/core_cache_census.py::census_demotes`, `scripts/core_cache_demote_census.py` · live phase w1027k: after the ten boots run `python scripts/core_cache_demote_census.py` — exit 0 or 1, never 3, and `home_mismatch` absent · DEFERRED 2026-11-09: owner triage — Measurement of an already-landed fix; until the owner reopens it · left 2026-11-05 (w1105g-hm-runtime): ten serve boots on the operator's own single-profile install, then `python scripts/core_cache_demote_census.py` (exit 0 or 1, never 3; `home_mismatch` absent) — the operator's install is the Windows box · REQUIRES windows
- **`RT-CORE-CACHE-CONVERGENCE-CENSUS` — core cache convergence on the live store: the four chat-turn sidecar families are ruled (leases and steer excluded, turns and prompt_observability kept as real inputs — lane w1027k-h-rt); left is the field half, a week of the demote census over operator boots, and IC-4 (WAL raw-content keying) only if that week still names WAL triples** · group: agent-start-up-cost.core-cache-input-closure · fork / core cache · plan `docs/agent-runtime-harness/planned/core-cache-input-closure.md` (2026-10-27 section) · `agent_runtime/core_cache/vocabulary.py::_EXCLUDED_STORE_ENTRIES`, `scripts/core_cache_demote_census.py` · live phase w1027k: a week of `python scripts/core_cache_demote_census.py` reads; file IC-4 as its own row if WAL triples remain · DEFERRED 2026-11-09: owner triage — Week-long measurement; no user-felt problem named; until the owner reopens it · left 2026-11-05 (w1105g-hm-runtime): a week of `python scripts/core_cache_demote_census.py` reads over the operator's own boots on the Windows box; file IC-4 as its own row if WAL triples remain · REQUIRES windows
- **`RT-CORRELATION-ID-CI3-ACCEPTANCE` — correlation-id: the CI-3 log-only acceptance is scripted (`scripts/correlation_id_acceptance.py`, lane w1027k-h-rt); left is its run against the operator's own build (one delete, one drag); P2's hermes half landed (w1101f-hb: `persona instance open-chat --correlation-id` stamps `persona_instance.chat_opened` and its paired row), the launcher arg is launcher row `MC-OPEN-CHAT-CORRELATION-ID-ARG`** · group: console-transcript-truthful.correlation-id-coverage · fork / transport · plan `docs/agent-runtime-harness/planned/correlation-id-coverage.md` P1/P2 · `agent_runtime/correlation_acceptance.py`, `hermes_cli/harness_parts/parser/persona.py` · P2 callers checked 2026-10-27: the launcher's `persona.instance.open_chat` argv spec carries no token (`EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_persona_capabilities.dart`) and the `--add-instance` mint (`PersonaInstanceStore.add_instance`) takes none, so the flag needs a store kwarg and a launcher arg in lockstep; live phase w1027k: the acceptance run · READY 2026-11-12 · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — the script exists; run it on a Linux or Windows QA build · was dEFERRED 2026-11-09: owner triage — Logging verification only; until the owner reopens it · left 2026-11-05 (w1105g-hm-runtime): launcher `MC-OPEN-CHAT-CORRELATION-ID-ARG` is on launcher main (checked 2026-11-05), so only the run is owed — `python scripts/correlation_id_acceptance.py` against the operator's own build after one delete and one drag on the Windows box · REQUIRES windows, linux · host 2026-11-09 (w1109a-hostsweep): owner rule — QA runs on Linux too; nothing in this check is Windows-only · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — one office delete or drag on a QA build, then scripts/correlation_id_acceptance.py over its receipts.jsonl and the serve agent.log
- **`RT-PEER-CANCEL-LIVE-STOP-PROOF` — D1.07's peer Stop has never been proven across two real installs (durable cancel_requested, partial output kept)** · group: remote-parity-and-two-machine-proof · moved 2026-11-10 (w1110a-org): from console-smooth-and-fast.design-sweep-d1 · fork / gateway · plan `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` D1.07 (built 5a2c887621) · `tools/agent_chat_dispatch/cancel_watch.py` · DEFERRED 2026-11-09: owner triage — Proof of a built feature; no reported failure; until the owner reopens it

### Filed on arrival — 2026-10-27 (lane w1027f-h-rt, w1027g-h-fix)


### Filed on arrival — 2026-10-27 (lane w1027b-h-fix)


### Lens plan reconciliation — 2026-10-26 (codex-lens-status)

Reconciled against the built code and the plan, not inferred from an absent old row. Optional branches retain their decision/deferral gates. Evidence and coverage: `docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md` § Current implementation and queue coverage.

- **`RT-LENS-ACT-ADMISSION` — Revisit the deferred act automation level** · group: eternia-lens · fork / Lens · `docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md` §2.6 and W9; agent_runtime/lens/manifest.py::AutomationLevel · DEFERRED 2026-10-26: owner-approved plan ships notify and investigate; until a separate reviewed per-monitor action-admission design and the W9 gate are approved
- **`RT-LENS-SHARE-RECIPE-TO-WORKSPACE` — Share a Lens monitor's recipe with a workspace, so each teammate sees it and can turn it on for their own PC** · group: eternia-lens · fork / Lens · ruling `OR-2026-11-09-lens-shared-recipes-opt-in` · nothing carries a Lens recipe between machines today (no sync, remote-adopt or template module imports `agent_runtime.lens`; the store is one SQLite file per runtime), so the owner's "only the recipe gets shared and you choose to enable it" needs a door built: the recipe (sources, rules, schedule — never credentials, Episodes or receipts) travels with the workspace and lands through `LensStore.create` as a DRAFT the Lens panel offers to enable; `tests/agent_runtime/lens/test_lens_shared_recipes_opt_in.py` fences it (its carrier scan must then name the new door) · NEEDS PLAN 2026-11-10: which workspace channel carries the recipe (workspace template, realm sync or the backend) and how a credential_ref is re-bound on the receiving PC · handoff 2026-11-10: filed by w1110a-hm closing RT-LENS-SHARED-RECIPES-OPT-IN; the opt-in half holds already, only the sharing door is missing · handoff 2026-11-10 (w1110d-lens): not small, so no plan written — recommend realm sync as the channel: a new `lens_recipe` family beside `level` (`agent_runtime/realm_sync/families.py`) publishing each sealed monitor's manifest only (its `credential_ref` names travel, never a secret — realm sync already refuses secret paths), a pull landing each as a DRAFT through `LensStore.create` in the receiving workspace (never sealed or enabled, so the opt-in holds), and the receiving PC re-binding a named ref through the existing `runtime.lens.credential.set` before Seal; the backend holds no Lens model and a workspace template does not move between machines; the plan needs the publish/drift/pull/revert arms and Eternia's "shared with this workspace" draft list

### Filed on arrival — 2026-10-26 (next-prompt implementation: remaining qualification)


### Filed on arrival — 2026-10-26 (launcher lane w1025b-mc)


### Filed on arrival — 2026-10-26 (lane w1025b-hlive, live sitting)


### Filed on arrival — 2026-10-25 (lane w1025a-hermes)


### Filed on arrival — 2026-10-25 (naming map verified against the owner's account namespace)


### Filed on arrival — 2026-10-25 (owner's Neko trial audit, turn `agent-chat-send-4743c92d-af53-4bbb-ab40-5438eaa74895`)


### Filed on arrival — 2026-10-24 (Projects repository TODO audit)


### Filed on arrival — 2026-10-24 (launcher lane w1024q-mc)


### Filed on arrival — 2026-10-23 (TODO / Work connection audit)


### Filed on arrival — 2026-10-22 (land w1022b)


### Filed on arrival — 2026-10-22 (land w1022a)

- **`RT-PHONE-PILLOW-ANDROID` — the phone closure needs Pillow on both targets and no Pillow release ships an Android wheel, so the Android phone bundle cannot finish (iOS has a wheel)** · group: embedded-hermes.bundled-phone-pool · fork / phone bundle · plan `docs/agent-runtime-harness/planned/bundled-phone-pool-2026-10-22.md` § Open rulings · RULED 2026-10-22: owner — a fork-built Android Pillow wheel (BeeWare mobile-forge recipe) pinned by URL and hash, psutil's Android pin shape; Pillow stays 12.3.0 · DEFERRED 2026-11-09: owner triage — Phone platform is far off; until the owner reopens it

### Filed on arrival — 2026-10-21 (lane w1021j-bundle, branch `w1021j/bundle`)

- **`RT-BUNDLED-PHONE-POOL` — the packager's pool installs the whole uv export for a phone target, so `--profile bundled-phone` never reaches verify** · group: embedded-hermes · fork / `scripts/bundle_profile_package.py::install_pool` / `export_requirements` · evidence: commit `83bf715c9d` body (omitted_distributions not dropped; psutil git pin unhashable; no phone wheels for cryptography, firecrawl-anydoc, httptools, jiter, markupsafe, pillow, watchfiles, resvg-py) · DEFERRED 2026-11-09: owner triage — Phone platform is far off; until the owner reopens it

### Filed on arrival — 2026-10-21 (land w1021i)

- **`RT-COURSE-AUTHORING-RULINGS` — course authoring stage C3 needs two owner answers: who hands the persona the course credential during a turn, and whether the course installation token may open a PR (the App has contents+metadata only)** · group: git-course · fork / course authoring · plan `docs/agent-runtime-harness/archive/realm-course-subject-authoring-2026-10-21.md` · RULED 2026-10-22: owner — the Launcher hands the course credential inline (hermes holds no player bearer); yes, add `pull_requests: write` to eternia-server-realms · DEFERRED 2026-11-09: owner triage — Owner click; course authoring works without PRs meanwhile; until the owner reopens it

### Filed on arrival — 2026-10-21 (lane w1021h-rpc, branch `w1021h/rpc`)


### Filed on arrival — 2026-10-21 (lane w1021h-cli, branch `w1021h/cli`)


### Filed on arrival — 2026-10-21 (launcher lane w1021f-qa-isolation)


### Filed on arrival — 2026-10-21 (launcher lane w1021e-mc-windows)


### Filed on arrival — 2026-10-21 (launcher landing land-w1021c)


### Filed on arrival — 2026-10-21 (launcher plan lane w1021c-plan-mc)


### Filed on arrival — 2026-10-20 (launcher landing land-w1020u review)


### Filed on arrival — 2026-10-20 (launcher lane w1020t-mc-slots)


### Filed on arrival — 2026-10-20 (launcher lane w1020r-mc-office)


### Filed on arrival — 2026-10-20 (launcher lane w1020r-mc)


### Filed on arrival — 2026-10-20 (launcher lane w1020r-dist)


### Filed on arrival — 2026-10-18 (land w6)

### Filed on arrival — 2026-10-18 (lane w6-misc, branch `w6/misc`)

### Filed on arrival — 2026-10-18 (land w5)


### Filed on arrival — 2026-10-18 (land w4)


### Filed on arrival — 2026-10-18 (lane w4-fold, branch `w4/fold`)


### Filed on arrival — 2026-10-18 (landing land-w2)

### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)


### Filed on arrival — 2026-10-16 (build lane h-bundle-speed, branch `build/h-bundle-speed`)


### Filed on arrival — 2026-10-16 (build lane h3-runser, branch `build/h3-runser`)

- **`RT-POSIX-TURNS-SERIALIZE-BEHIND` — POSIX turns still serialize behind one process lock: the fork writes `HOME` per profile turn because upstream's in-process `expanduser`/`Path.home()` readers have no context hook** · group: agent-start-up-cost · upstream door (run-serialization decision 3) · `agent_runtime/profile_context.py::persona_profile_context` (the `HOME` write and its pinned-readers comment) · draft the one upstream door for a context-aware home hook (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files); once it lands, delete `_PROCESS_HOME_LOCK` on the h3-runser branch and POSIX gets per-root turns like Windows · DEFERRED 2026-11-09: owner triage — Mac/Linux perf; waits on upstream; until the owner reopens it · no fork-owned caller to memo (the readers are upstream) · handoff 2026-11-12: narrowed by `RT-NEW-TURN-WAITS-ON-ANOTHER-AGENTS-MODEL-CALL` (lane w1112b-hm-turn4) — `_PROCESS_HOME_LOCK` is gone; `agent_runtime/profile_runner/workdir.py::_ProcessHomeGate` lets runs that want the same `HOME` hold it together, so on a host (no profile has a `home/`, nothing is written) turns of different chat roots run side by side on POSIX too; what is left for the upstream door is only runs whose profiles carry DIFFERENT `home/` directories, which still take turns

### Filed on arrival — 2026-10-16 (build lane h1-lineage)


### Filed on arrival — 2026-10-16 (build lane h4-seeds)

### Filed on arrival — 2026-10-16 (release merge v0.22.2, daily branch at upstream acc3cada0da)




### Filed on arrival — 2026-10-15 (launcher lane w1015i-mc)


### Filed on arrival — 2026-10-15 (orchestrator: QA bundle build under load)


### Filed on arrival — 2026-10-15 (owner sitting: first real QA bundle build)


### Filed on arrival — 2026-10-15 (owner sitting: send-prep live proof)




- **`RT-CONNECTIONS-TRACE-MISSING` — Connections: trace the missing browser sign-in `done` event for the isolated QA profile.** Owner report/review 2026-10-14: ChatGPT or Codex Subscription web sign-in completed, but the login-stream `done` event did not reach the Launcher and the pane remained pending; the selected isolated profile subsequently had a credential entry and canonical `logged_in=true`. Root cause is unproven: no historical completion frame was captured. Start at producer `hermes_cli/provider_browser_login.py::run_browser_login` (`send` of `done`), trace `agent_runtime/provider_signin.py` and the consumer `EterniaLauncher/lib/shared/provider_connections/provider_connection_state.dart::ProviderSetupController` under the same profile; capture redacted lifecycle/transport evidence and pin reliable terminal delivery. The Launcher projection reconciliation on `fix/sol-connect-20261014` is a safety net, not the root-cause fix. Preserve the QA binding; never capture credentials or account identifiers. · group: provider-api-key-and-usage-source · fork / launcher seam · found 2026-10-14 sol-connect review · code read 2026-10-15: run_browser_login sends done only after _save_codex_tokens returns, ProviderSignIns._pump folds it only while the session is ACTIVE, and the registry lives in one serve process, so a serve restart between the credential write and the next poll answers login_not_found to a pane still pending · BLOCKED 2026-11-12: owner sitting — one provider sitting: the owner signs in to their own provider accounts on Windows and does one ChatGPT sign-in so its completion can be recorded · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, as recommended" · was dEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: one live ChatGPT/Codex browser sign-in on the isolated QA profile (Windows box), capturing the poll replies and the serve pid

### Filed on arrival — 2026-10-15 (lane w1015h-prov)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-misc-l)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-mc-l)


### Filed on arrival — 2026-10-15 (lane w1015h-comp-l)


### Filed on arrival — 2026-10-15 (lane live-qa)


### Filed on arrival — 2026-10-15 (lane w1015h-rt-h)

### Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


### Filed on arrival — 2026-10-15 (lane w1015b-rt-h)


### Filed on arrival — 2026-10-14 (Console execution controls)





### Filed on arrival — 2026-10-12 (composer thinking meter)


### Filed on arrival — 2026-10-11 (lane h-s17, one-action-layer S17)


### Verified Console history PR #7 follow-up — 2026-10-11





### Filed on arrival — 2026-10-10 (D2.07 redesign, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)


### Filed on arrival — 2026-10-09 (owner report: "this chat I cannot delete")

### Filed on arrival — 2026-10-09 (owner report: Agent Console silent after the toolvis 1b landing)

### Filed on arrival — 2026-10-08 (launcher lane opus-qa-hygiene)

### Filed on arrival — 2026-10-08 (gateway restart after a live-checkout fast-forward)
- **`RT-GATEWAY-START-MANAGED-PYTHON` — `hermes --profile alice gateway start` raises `ManagedPythonUnavailable` ("no Hermes virtualenv found") even when run by the managed venv's own interpreter (the managed venv's `Scripts/python.exe -m hermes_cli.main`), while `hermes_cli.gateway._detect_venv_dir()` in that same interpreter returns the venv; `gateway restart` drained the gateway and then could not bring it back, so the operator is left with no gateway. Cause unproven — read the `gateway_windows.start` → `_spawn_detached` → `_launcher_settings` path for a re-exec or an env scrub before `resolve_managed_python`. Worked around with a detached `gateway run`.** · group: remote-parity-and-two-machine-proof · moved 2026-11-10 (w1110a-org): from eternia-lens · fork / gateway service (Windows) · `hermes_cli/gateway_windows.py::_launcher_settings`, `hermes_cli/gateway_downstream.py::resolve_managed_python` · evidence: 2026-10-08 ~21:55 restart, alice `gateway.log` (stopped 21:54:58, manual run up 21:58:16). Also seen: the shell's PATH `hermes` resolved to a leftover test shim under the temp dir (`rb7-identity-flip-559b6bbd/hermes/bin/hermes`) · read 2026-10-15: resolve_managed_python sees only sys.prefix, VIRTUAL_ENV and <checkout>/.venv|venv, and the launcher venv sits outside the checkout, so any interpreter whose sys.prefix is not that venv raises · RULED 2026-10-25: owner — an agent runs this sitting on this PC · LIVE 2026-10-25: resolve_managed_python() resolves the venv in the venv's own interpreter; a live start is masked by the namespace refusal (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · DEFERRED 2026-11-05: owner — "thats upstreams gateway stuff im going to build my own external gateways"; the upstream gateway is not maintained here, so this waits until a gateway of ours needs it (`RT-EXTERNAL-GATEWAY-NAMESPACE-ACCESS`)

### Filed on arrival — 2026-10-08 (owner ask: capability vs. cost-trim quietness, Neko QA-build turn)

### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)
- **`RT-SEND-PREP-H2-H6` — Send-prep H2 + H6 UNRESOLVED: skill preload (65–95 ms historically on Dev) and package stamps/preload checks did not reproduce on the fresh Neko route; re-measure on a skill-heavy persona using the existing `context_skill_preload_ms` receipts before changing either** · group: agent-start-up-cost.skill-catalog-doors · runtime / measured send-prep · `agent_runtime/skill_resolution.py`, `skills_context.py` · evidence: [Integrated receipts](../../docs/agent-runtime-harness/archive/warm-prep-integration-2026-10-08.md) · H2 reproduces on Dev (`context_skill_preload_ms` median 73; the cost sits in upstream `agent/skill_commands.py::build_preloaded_skills_prompt`/`skill_view`); H6 2–5 ms, below the bar (`docs/agent-runtime-harness/archive/warm-prep-integration-2026-10-08.md` § Attribution pass; design-sweep-d1 § D1.10) · RULED 2026-10-10 owner: WAIT on the upstream frontmatter-in-result door (no six-input memo) · DEFERRED 2026-11-09: owner triage — Small latency; waits on upstream; until the owner reopens it
- **`RT-SEND-PREP-H7-UNRESOLVED` — Send-prep H7 UNRESOLVED: request build is 47–50 ms per warm turn and is broader than the web-search lookup (separate row); split it with the existing `profile_conversation_request_*_ms` parts and name what kwargs / tool-JSON work remains, keeping the final wire-tool receipt** · group: agent-start-up-cost · runtime / measured send-prep · `agent/transports/codex.py::ResponsesApiTransport.build_kwargs`, `capture_final_request_tools` · evidence: [Integrated receipts](../../docs/agent-runtime-harness/archive/warm-prep-integration-2026-10-08.md) · split on Neko n=8: request build 48 = kwargs 41 + middleware 4 + preflight 1; kwargs is upstream `ResponsesApiTransport.build_kwargs`, its fixture-confirmed share is the web-search selection (`docs/agent-runtime-harness/archive/warm-prep-integration-2026-10-08.md` § Attribution pass; design-sweep-d1 § D1.11) · RULED 2026-10-15 owner: wait for the upstream web-search fix, no short cache · DEFERRED 2026-11-09: owner triage — Small latency measurement; waits on upstream; until the owner reopens it

### Filed on arrival — 2026-10-08 (GenUI comparison turn audit, Amelia turn `agent-chat-send-db7a2d34-731b-4cc8-bc0b-d00b7394f753`)

- **`RT-ALWAYS-HARNESS-SKILLS-PAID` — The always-on harness skills are paid per turn through `skill_view` instead of once in the cached prefix: Amelia turn `agent-chat-send-db7a2d34` (2026-10-08) read `harness-dev-delivery` (13.7 KB) and `harness-runtime-model` (18 KB, frontmatter `load_policy: required_preload`) by tool, and the relay receipt shows `required_preload_skills: []` — `required_preload_skill_ids` filters the persona's OWN assigned identifiers by surface, and nothing is assigned, so the mechanism never fires. Owner ruling owed: which skills each harness persona preloads, then assign them (persona config, not code) and compress their bodies to short operational rules per the 2026-10-08 plan; a preloaded skill `skill_view` re-reads should answer "already in your prompt" cheaply.** · group: agent-start-up-cost · fork / `agent_runtime/mission_chat_turn_context.py::_required_preload_skills`, `agent_runtime/skill_resolution.required_preload_skill_ids`, persona skill assignment · filed by lane host-guidance 2026-10-08 · RULED 2026-10-10 owner: skills load on demand by default; each persona preloads at most its top one or two · RULED 2026-10-15 owner: Launcher Dev and Backend Dev preload the delivery contract; Neko and Base preload the runtime model; everything else loads on demand · the preload half landed 6d7938ce1ab; the "preloaded skill_view re-read answers cheaply" half is upstream `tools/skills_tool.py` · DEFERRED 2026-11-09: owner triage — Our half landed; remainder is upstream cost tweak; until the owner reopens it · the fork does not own `skill_view`'s caller (the model calls the tool); preload half on main 6d7938ce1ab
- 2026-10-08 evidence for the GenUI selection row below: with the eager pair delivered (runtime `94043a1a42`, listing `26 core/visible tools kept, 18 deferred` at 13:23:09), the first-response path still did not call `launcher_generated_list` directly — the turn loaded five skills (`launcher-generated-ui`, `harness-dev-delivery`, `harness-continuity`, `harness-runtime-model`, one not found; ~44 KB of skill text), searched, described, queried the roster, took the wrong door, then relayed to a peer and burned the rest of the 240 s on the deadlock row above. The profile-local skill is a second copy of the tool contract (it says "discover with `launcher_generated_list`" without saying it is direct); F2 of the launcher audit stands.


### Filed on arrival — 2026-10-07 (GenUI selection audit)




- **`RT-VERIFY-IMPROVE-FIRST-RESPONSE` — Verify and improve first-response selection of the Launcher generated-content tools for ordinary comparison requests; the A/B eval is built (`evals/genui_first_response_ab.py`, b05ccafe29)** · group: console-transcript-truthful.p10-agent · fork / tool selection · plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §3 · RULED 2026-10-19: owner — arms switched by QA build · RULED 2026-10-25: owner — an agent runs this sitting on this PC · live phase 2026-10-25: a launcher_qa lane runs it — two QA builds (arm A before launcher 469e500730, arm B at it), 15 turns × 2 agents × each QA provider per arm; it does not touch the owner's serve (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · READY 2026-11-12 · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — the A/B test exists (`evals/genui_first_response_ab.py`); it costs provider turns · was dEFERRED 2026-11-09: owner triage — Evaluation of a nice-to-have behavior; until the owner reopens it · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — the live A/B (arm A, arm B) over launcher_qa; the owner keeps ONE QA build of HEAD (11-11), so arm A on a build before launcher 469e500730 needs a plan

### Filed on arrival — 2026-10-07 (native turn anchor carrier)


### Filed on arrival — 2026-10-07 (latency source recheck)



### Filed on arrival — 2026-10-06 (lane h-slim-prompt)


### Filed on arrival — 2026-10-06 (lane h-pool-starve)


### Filed on arrival — 2026-10-06 (lane h-send-window)


### Filed on arrival — 2026-10-06 (lane h-turn1-conn)


### Filed on arrival — 2026-10-06 (lane h-turn1-again)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-newchat-t1)


### Filed on arrival — 2026-10-06 (lane h-cache-hit)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)


### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-06 (lane h-snapshot-offproc)


### Filed on arrival — 2026-10-05 (lane h-prompt-design; h-turn1-c)

- **`RT-LEAN-OPERATIVE-RULES` — With `lean_operative_rules` on, the threading and `clarify_token` rules reach the agent only through `agent_chat_send`'s describe doc, and an eager tool is rarely described; the R4 A/B must check one teammate clarify answer goes back on its `clarify_token`, or the bullets move into `harness-mission-lead` (operator-home skill)** · group: console-transcript-truthful · fork / chat lane · evidence: lane h-prompt-surface `ba499069be` · lane: R4 A/B · RULED 2026-10-25: owner — an agent runs this sitting on this PC · LIVE 2026-10-25: flag on, Neko kept the threading rules; the clarify answer could not go on its token because the token never arrived (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md` § Batch C) · unblocked 2026-11-02: `RT-DISPATCH-DELIVERY-DROPS-CLARIFY` landed `3516b3d9e2` (a background dispatch carries the clarify_request); what is left is the live R4 A/B re-read only · READY 2026-11-12 · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — its blocker landed (3516b3d9e2); one live re-read · was dEFERRED 2026-11-09: owner triage — Live re-check of a fixed issue; until the owner reopens it · left 2026-11-05 (w1105g-hm-runtime): the R4 A/B re-read in a live sitting on the owner's Windows PC (RULED 2026-10-25): with `lean_operative_rules` on, one teammate clarify answer goes back on its `clarify_token` · REQUIRES windows, linux · host 2026-11-09 (w1109a-hostsweep): owner rule — QA runs on Linux too; nothing in this check is Windows-only · moved 2026-11-10 (owner yes on w1110a-org's finding): from eternia-lens — agent chat prompt rules belong to TASK-CONSOLE-TRANSCRIPT-TRUTHFUL · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — the live R4 re-read: flag on, one teammate clarify answer goes back on its clarify_token

### Filed on arrival — 2026-10-05 (launcher lane docs-dev, filed by the orchestrator)


### Filed on arrival — 2026-10-05 (lane h-turn1-c1-design)


### Filed on arrival — 2026-10-05 (launcher lane console-1a, filed by the orchestrator)


### Filed on arrival — 2026-10-05 (owner live turns, "turns still feel slow")












### Filed on arrival — 2026-10-05 (owner screenshot, "screenshot posts" 13:05)


### Filed on arrival — 2026-10-05 (lane hb-c)


### Filed on arrival — 2026-10-04 (launcher lane console-boundaries, filed by the orchestrator)


### Filed on arrival — 2026-10-04 (owner design: builds as first-class background work)



### Filed on arrival — 2026-10-03 (lane h-wakecap)


### Filed on arrival — 2026-10-03 (resident identity audit)


### Filed on arrival — 2026-10-03 (lane h-fence)


### Filed on arrival — 2026-10-03 (launcher lane fx-mc2, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane mc-pidx, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane w12-qa, filed by the orchestrator)


### Owner asks — 2026-10-02 (long tool calls)


### Filed on arrival — 2026-10-02 (lane w10-hr, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (owner screenshot: QA turn ended silent; filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane w10-pkg, bundled Hermes on macOS/Linux; moved here by the orchestrator)


### Filed on arrival — 2026-10-02 (lane w10-s7h, Stage 7 hermes half)


### Owner asks — 2026-10-02 (agent chat is ONE surface; filed by the launcher orchestrator)

- The launcher half of the same ruling (the Agent Console becomes the one chat widget, rendered with Intelligence's materials; `EterniaLauncher/docs/archive/companion/AGENT_CHAT_UNIFICATION_AUDIT_2026-10-02.md`) changes NO hermes method: `runtime.chat.*` and `perform_chat_turn` are the surviving chat lane; the `tui_gateway` worker is the lane that goes. Work on the worker's lifecycle beyond keeping it alive until the cutover is upstream work (the cold-start hello carry under Upstream-owned), not cutover work.

### Filed on arrival — 2026-10-02 (orchestrator, live MCP check)


### Filed on arrival — 2026-10-02 (launcher lane w5-mc, filed by the orchestrator)


### Owner asks — 2026-10-01 (instance conversations)


### Owner asks — 2026-10-01 (Eternia Lens in hermes)



### Filed on arrival — 2026-10-01 (lane w3-turn)


### Filed on arrival — 2026-10-01 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (lane hq-b)




### Filed on arrival — 2026-09-30 (moved from the launcher spatial queue, owner rulings)


### Filed on arrival — 2026-09-29 (lane h10b-triage)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

Plan and rulings: `EterniaLauncher/docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md` (stages named per row) and `ARCHITECTURE_2026-09-28.md` §4. Rule: one Python implementation, universal — enable existing Hermes code, never reimplement; bundle only what is needed.

- **`RT-MESSAGING-PLATFORMS-TELEGRAM` — Telegram for the headless persona runtime: stores and `runtime.messaging.*` verbs, the Bot API transport, the inbound bridge, approval cards and the serve lane with OS-scheduler service templates are on main (b05ccafe29), off by default and off in every bundled profile** · group: remote-parity-and-two-machine-proof.p10-messaging · fork / messaging · plan `docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md` · RULED 2026-10-19: owner — Telegram only in v1, fork-owned transport over raw httpx, one persona instance per chat, the token in the serve head home, approval cards for every bound root, the installer and a headless bundle profile wait for M7 after one live week · DEFERRED 2026-11-09: owner triage — New optional channel; off by default; until the owner reopens it
- **`RT-MACOS-LINUX-BUNDLED-DESKTOP` — macOS / Linux bundled desktop ships no OS secure store: `keyring` (Keychain / Secret Service) is not in the bundled-desktop packaging, so `auth.os_secure_store: true` refuses to start there — add it to those targets' packaging when they exist** · group: embedded-hermes · `fork` · evidence: `agent_runtime/host_store/desktop.py::admitted_keyring_backend` · filed 2026-09-28 (lane w5-hdpapi) · `keyring` is in neither pyproject.toml nor uv.lock; add it as an optional extra + networked `uv lock` + bundled-desktop.yaml darwin/linux extras in the change that first builds those targets · RULED 2026-10-16: owner — "add keyring when mac/linux builds exist, not now"; prove it at the Mac sitting · RULED 2026-11-10: owner — split: the Mac half (Keychain `keyring` extra + proving `admitted_keyring_backend` on a Mac) moves to the Mac sitting task `TASK-MISSION-CONTROL-ON-MAC` (Eternia, "…move the mac to a mac sitting task"); the Linux half (Secret Service in a Linux bundled target) stays in this task · DEFERRED 2026-10-18: `bundled-desktop.yaml` declares no darwin/linux target yet, so there is no packaging to add it to; the change that adds the first such target adds `keyring` (optional extra + networked `uv lock` + that target's extras) and proves `admitted_keyring_backend` at the Mac sitting — owner 2026-10-16

### Filed on arrival — 2026-09-29 (lane h11-mcp)


### Filed on arrival — 2026-09-29 (lane h9-bundle)


### Filed on arrival — 2026-09-30 (lane s2-plan — phone gate → zero, one row per lane; work them in the plan's order)

### Filed on arrival — 2026-09-28 (lane p2-hphone)

### Filed on arrival — 2026-09-28 (lane p1-hsplit)

### Filed on arrival — 2026-09-28 (lane w4-hd4)

### Filed on arrival — 2026-09-29 (upstream merge `merge/upstream-2026-09-29`, filed by the orchestrator)

### Filed on arrival — 2026-09-29 (lane h7-phone)

### Filed on arrival — 2026-09-29 (lane w6-hwort)
- **`RT-PIPER-FIRST-AUDIO-LATENCY` — Piper first audio is ~2 s on a sentence with a name the phonemizer dictionary lacks ("…Mira hasn't joined yet") vs 0.2–0.5 s otherwise — profile the out-of-dictionary path (the model runs per word) and cache or batch it.** · group: bundled-voice · `agent_runtime/speech_phonemize.py`; listening manifest (lane h8-voice, 2026-09-29) · code read: `OpenPhonemizer._predict` is one ORT forward per OOD word, so the likely cost is the first forward on a fresh input shape; owner 2026-09-29: profile once the voice pack is on the box, a warm-up forward at load is the likely cheap fix · RULED 2026-10-25: owner — an agent runs this sitting on this PC · LIVE 2026-10-25: no Piper pack or openphonemizer model anywhere under the hermes roots (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · DEFERRED 2026-11-09: owner triage — Noticeable but niche; needs voice pack installed; until the owner reopens it · moved 2026-11-10 (owner yes on w1110a-org's finding): from eternia-lens — voice speed belongs to TASK-BUNDLED-VOICE

### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-28 (lane w1-hclean, filed by the launcher orchestrator)


### Native conversation lifecycle audit — 2026-09-26



### Filed on arrival — 2026-09-26 (lane PF-1, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane PF-3, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (the wedged live serve, owner screenshot 15:05; filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane CI-RESTORE, filed by the orchestrator)

### Filed on arrival — 2026-09-26 (post-landing gate, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (owner ruling: ACP is not used)

### Filed on arrival — 2026-09-26 (lane L5, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane L4, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (launcher lane LLAMA-SWITCH, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (launcher lane REALM-HISTORY, filed by the orchestrator)

The launcher's realm History sheet landed at `EterniaLauncher` `4f77ddfc8`; its Remote tab renders UNSUPPORTED and restore-to-version records a refused row until H1 and H3 exist. Evidence for all four: `EterniaLauncher/docs/mission_control/subsystems/realm-history-and-publish-policy-design-sheet.md` §3.


### Filed on arrival — 2026-09-25 (program-end suite, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (lane LAYERS-DESIGN, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (lane LLAMA-ALIAS)


### Filed on arrival — 2026-09-25 (lane W3-D)



### Filed on arrival — 2026-09-25 (lane W3-C)

### Filed on arrival — 2026-09-25 (lane B4)

### Filed on arrival — 2026-09-25 (lane 2B-A)

### Filed on arrival — 2026-09-24 (lane LLAMA-H)


### Filed on arrival — 2026-09-24 (lane MOVE-A)


### Filed on arrival — 2026-09-24 (seam lane S2)

### Filed on arrival — 2026-09-24 (lanes UPREV, DISP-M)

### Filed on arrival — 2026-09-24 (seam lane S5)

### Filed on arrival — 2026-09-24 (seam lane S4)

### Owner asks — 2026-09-22, filed on arrival


### Contract questions the launcher is waiting on (filed 2026-09-20/21, routed by the 2026-09-22 verdict sheet)



### Owner design changes — 2026-09-18 (the generic-desk landing, hermes `f1268bd017`)


### Discussion Tables (hermes half) — from the 2026-09-17 reviews of `codex/discussion-tables-*`

- **`RT-DISCUSSION-TYPED-REFUSAL` — Discussion Tables (hermes half): D3 closes the typed-refusal lane by subclass, leaving three families on the raw-text boundary** · group: discussion-rooms-reliability · `hermes` · `agent_runtime/discussions/rpc.py:90-105`: `DiscussionPolicyError` (the base), the `DriverStateError` family (`gateway/hosted_room_driver.py:104-111`) and checkpoint `RuntimeError`s (`gateway/hosted_room_policy_checkpoint.py:183,291,298`) still reach `serve_rpc` as `handler_failed` with `f\"handler error: {exc}\"`. Latent — not live-reachable today. Same review @ `20b148694e`. · the policy base and `DriverStateError` family are typed in d151314bcfe; the checkpoint's three plain `RuntimeError`s are raised by upstream `gateway/hosted_room_policy_checkpoint.py`, so typing them is an upstream door (a typed subclass) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### The ghost agent — filed 2026-09-11 from the office removal-lane fix


### Runtime observability — filed 2026-09-06 from the post-rebuild field run

- **`RT-LOCAL-CHAT-PREP-COST` — The local chat prep cost is now a measured baseline** · group: agent-start-up-cost.chat-turn-prep-cost · `hermes` · `turn_context_ms` 620 / 829 / 1,233 / 4,730 with `builds_overlapped` 1 / 0 / 2 / 3 on four idle local turns (2026-09-06 15:29–15:30Z), the provider itself 0.9–1.5 s — `planned/chat-turn-prep-cost.md` (hermes canon) is re-armable as a stage against these numbers. · plan `docs/agent-runtime-harness/planned/chat-turn-prep-cost.md` (rulings CP-1..CP-9, Stages 6–10): Stage 6 landed hermes `a319021acc` (pre-rewrite) / launcher `a4b8e390c`; CP-9's PC read taken and Stage 7 landed hermes `483bcf6fab` (pre-rewrite) (write_ahead p50 844 ms; skill work 74–89 % of it, so Stage 8 is billed on live turns); no `codex/prep-cost-stage8-one-walk` branch exists — re-verify Stage 8's state before claiming; owed: CP-9's Mac half, Stage 7's ten-turn number, the launcher `ready.json` re-capture · DEFERRED 2026-11-09: owner triage — Measurement work, no user complaint; until the owner reopens it

### Snapshot build latency on Windows — filed 2026-09-08



### Harness CLI and the doctor — 2026-08-30 / 2026-09-02 hand-backs, 2026-09-12 skill sync

- **`RT-ROOT-CONFIG-MISPLACEMENT-CURE` — `root_config_misplacement` has a cure and a denominator; the 9-vs-2 comparison needs re-reading** · group: agent-config-cleanup · `hermes` · the finding half landed 2026-09-04 (w12/m5, hermes `42d54af562` (pre-rewrite)): `remediation` (present even when `ok`) and `scope` (`profiles_examined` / `root_only_key_patterns`) from the rows' own walk; doctor `schema_version` 9. A row is (profile × concrete key) and two of four patterns are per-persona, so 9 vs 2 across two machines compares inventories. What remains is operator-only: re-read the two stores against `scope` and fix the genuinely inert rows by hand — there is deliberately no automated repair, because rewriting an operator's `config.yaml` is not a write the doctor takes. · DEFERRED 2026-11-09: owner triage — Operator tidy-up; no user impact; until the owner reopens it



### Filed on arrival — 2026-09-25 (lane R4)



### Filed on arrival — 2026-09-25 (lane S2B)

### Filed on arrival — 2026-09-25 (lane S2A)

### Filed on arrival — 2026-09-25 (lane 2B-C)


### Filed on arrival — 2026-09-25 (lane B2)


### Filed on arrival — 2026-09-25 (lane B3)


### Filed on arrival — 2026-09-25 (lane B4, filed by the orchestrator)


### Filed on arrival — 2026-10-17 (lane r-perf)


### Filed on arrival — 2026-10-17 (q-version)


### Filed on arrival — 2026-10-17 (harvest of rows committed on branches, never landed)


## Seams

### Filed on arrival — 2026-11-01 (release merge lane, branch `merge/upstream-v0.22.5`)


### Filed on arrival — 2026-11-10 (lane w1110c-hmboot: `RT-HARNESS-SERVE-COLD-BOOT`)


### Filed on arrival — 2026-10-29 (lane w1029b-h-rt)


### Filed on arrival — 2026-10-21 (lane w1021h-daily, `integration/upstream-daily` `4ce03587da`)


### Filed on arrival — 2026-10-21 (lane w1021h-rpc, branch `w1021h/rpc`)


### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)

### Filed on arrival — 2026-10-16 (lane r-turnrec)




### Filed on arrival — 2026-10-15 (door PR lanes doors-a, doors-b)

- **`RT-DOORS-SHEET-C-PART-B` — Doors sheet §C part B (gh/Qwen `adopt_external_logins` bug fix) has no prepared branch; part A shipped as `feat/secret-file-store` (634f2ab083)** · group: upstream-footprint-ledger · seams · doors-a lane report 2026-10-15; sheet on `h-doors-2` §C · build a branch from upstream/main with a body in `pr-bodies` · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: build the part B branch from the then-current upstream release when upstream takes the owner's PRs again — owner 2026-10-16 deferral




- **`RT-QUALIFY-HELD-CHECKPOINT` — Qualify the held checkpoint upstream candidates against native user value and maintainer demand.** Native write extraction and reviewed consumers are complete in Console history PR #7, with separate behavior-preserving extraction `71ba58a781`. Before any submission, check open issues/discussions and overlapping PRs and apply the evidence/value bar in the footprint ledger; product neutrality alone is insufficient. Busy/wait is a separate candidate. Retention pins accompany qualified resumable restore or remain held. No upstream submission is authorized by this row. · group: upstream-footprint-ledger · seam / checkpoints · `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`, `docs/agent-runtime-harness/archive/console-history-followup-verification-2026-10-11.md` · RULED 2026-10-15 owner: no, not yet; there is no sign upstream wants them · DEFERRED 2026-10-18: hold until an upstream issue or maintainer asks for checkpoint restore — owner 2026-10-15 "no sign upstream wants them"


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)



### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)

### Filed on arrival — 2026-10-08 (native connection ownership cleanup)

### Filed on arrival — 2026-10-06 (upstream sync planning; AFTER the next release merge)


- **`RT-REQUEST-BUILT-RESOLVES-WEB` — request_built resolves every web-search provider's availability on every request (`agent/transports/codex.py::_alias_wire_tools` → `_openai_prefers_native_web_search` → `agent/web_search_registry.get_active_search_provider`: credential-pool loads, auth-file reads, nous account lookups; 85–105 ms live, ~100 ms on the fixture)** · group: agent-start-up-cost · runtime / turn latency · evidence: h-warm-phases commit 01b1a9a0f8 body · measured 2026-10-08 (`docs/agent-runtime-harness/archive/warm-send-prep-measurements-2026-10-08.md`); every fix site is upstream (`agent/transports/codex.py`, `agent/web_search_registry.py`) · RULED 2026-10-15 owner: wait for the upstream fix; no short cache (a stale cache can send the wrong search tool) · DEFERRED 2026-11-09: owner triage — Small latency; owner ruled wait on upstream; until the owner reopens it
- **`RT-NATIVE-CONVERSATION-RECOVERY` — Native conversation recovery lives inside ~15 upstream `tui_gateway/` files and is the top repeat merge conflict (`session_workdir`, `session_lifecycle`, `methods_session`, `event_replay`, `rpc_dispatch`, `server_requests`, `contracts/sessions` conflicted in the 2026-09-29 merge and/or the 2026-10-06 dry run): move the logic into fork modules, leave one-line call sites. Start only after the next release merge lands** · group: console-transcript-truthful.design-sweep-d2 · `seams / tui_gateway` · ledger `carry` rows "native conversation recovery"; `Merging upstream.md` · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.09 (two MOVE clusters + four door-PR rows) · MOVE A landed 2026-10-25 lane w1025a-hermes (observe + turn-start gates out of `compute_host.py`); MOVE B moot (D2.09 § Landed) · READY 2026-11-12 · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — its gate is met: the v0.23.1 release merge is on main (81a749eb85d); needs no upstream PR · was dEFERRED 2026-11-09: owner triage — Maintenance ease, not user-facing; upstream-gated; until the owner reopens it · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — the D2.09 move of native conversation recovery out of tui_gateway into fork modules
- **`RT-FOUR-UPSTREAM-DOOR-PRS` — Four upstream door PRs would retire 23 fork-edited upstream files (optional-module 6, SDK fallback 3, secret-file store 7+2, provider access 5): the design is on branch `h-doors` (`d3d91edc7f`, its upstream-doors plan, not on main). Owner go needed before the Opus build lanes; land the plan with the first lane; open no upstream PR without the owner's OK** · group: upstream-footprint-ledger · `seams / upstream doors` · `h-doors` · RULED 2026-10-10 owner: go: the four door-PR Opus build lanes on `h-doors`, and open the four upstream PRs · part A shipped as `feat/secret-file-store` (634f2ab083) · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: build the three remaining door branches (optional-module, SDK fallback, provider access) on `h-doors` when upstream takes the owner's PRs again — owner 2026-10-16 deferral
- **`RT-DOOR-PR-LANDS-UPSTREAM` — When a door PR lands upstream and reaches a release: delete the fork hunks it retires, file by file, per the plan's "fork deletion" section, and lower `tests/fixtures/upstream_footprint.json`** · group: upstream-footprint-ledger · `seams / upstream doors` · `upstream-doors-2026-10-06.md` · DEFERRED 2026-11-09: owner triage — Cleanup that can only happen after upstream ships; nothing breaks meanwhile; until the owner reopens it

### Filed on arrival — 2026-10-06 (lane h-prereq-window)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)


### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-05 (lane h-prompt-tools)


### Filed on arrival — 2026-10-04 (lane hb-a)


### Filed on arrival — 2026-10-03 (lane h-mcpwake)


### Filed on arrival — 2026-10-02 (instance-conversations)


### Filed on arrival — 2026-10-01 (lane w3-turn)

- **`RT-RETIRE-COMPUTE-HOST-COLD` — Retire the compute-host cold-start carry: `tui_gateway/host_supervisor.py` waits a fixed 10 s for the child's hello while the child imports `tui_gateway.server` first (5.6–6.2 s idle, 10.8–28.5 s loaded); the fork added `_HELLO_COLD_START_GRACE_SECS` (additions only). Upstream PR: a configurable hello budget, or the hello sent before the heavy import** · group: agent-start-up-cost · `upstream / tui_gateway` · ledger row `tui_gateway/host_supervisor.py` (cold-start hello grace, 2026-10-01) · RULED 2026-10-10 owner: yes: open one upstream PR for a configurable compute-host hello budget (default 10 s) · draft: local branch `up/compute-host-hello-budget` (fd282272f8e, `dashboard.compute_host_hello_timeout_secs`, red recorded) · DEFERRED 2026-11-09: owner triage — Our workaround already works; upstream PR is housekeeping; until the owner reopens it · draft `up/compute-host-hello-budget` (fd282272f8e) · fork carry `_HELLO_COLD_START_GRACE_SECS` stays

### Filed on arrival — 2026-09-29 (lane fix-cron-openai)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)


### Filed on arrival — 2026-09-29 (lane h9-bundle)


### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)

### Filed on arrival — 2026-09-26 (lane PF-1, seams; filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane AUTH-PR, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (owner ask: the fix-shaped footprint)


### Filed on arrival — 2026-09-26 (owner ask: what else moves to the plugin side without a PR)

### Filed on arrival — 2026-09-26 (orchestrator, the sync-friction read)


### Filed on arrival — 2026-09-26 (orchestrator, the footprint read)


### Filed on arrival — 2026-09-25 (lane MERGE, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (orchestrator, the `[up-fp]` raise)


### Filed on arrival — 2026-09-25 (lane 2B-B)


### Filed on arrival — 2026-09-24 (seam lane S2)


### Filed on arrival — 2026-09-24 (disposition wave, lane DISP-C)

### Filed on arrival — 2026-09-23 (seam lane S45, Stage 4/5/6 inventories)


### Standing

- **`RT-SPARK-PRO-USAGE-BUCKET` — Spark has a Pro usage bucket but Hermes's ChatGPT-account Codex route rejects it** · group: provider-api-key-and-usage-source · observed 2026-09-16: the live model catalog omitted Spark, the same account's usage response named the separate `codex_bengalfox` bucket, and a minimal `gpt-5.3-codex-spark` request returned HTTP 400 "not supported when using Codex with a ChatGPT account." The picker now shows it disabled. Investigate a supported runtime route before enabling it · `EterniaLauncher/docs/mission_control/subsystems/model-picker-account-catalog-contract-20260916.md`, `hermes_cli/codex_models.py`. · DEFERRED 2026-11-09: owner triage — Model is already safely disabled; adding it is a nice-to-have; until the owner reopens it



## Upstream-owned

### Filed on arrival — 2026-10-26 (lane w1026c-h-fork)


### Filed on arrival — 2026-10-25 (lane w1025b-h-audit)


### Filed on arrival — 2026-10-21 (lane w1021j-tooling, branch `w1021j/tooling`)


### Filed on arrival — 2026-10-18 (land w8)


### Filed on arrival — 2026-10-18 (lane r-state, branch `q/r-state`)


### Filed on arrival — 2026-10-17 (harvest)


### Filed on arrival — 2026-10-17 (lane r-perf)

- **`RT-CHECKPOINT-PM-ENSURE` — `tools/checkpoint_manager._run_git` calls `pm.client.ensure` per git call (a store-root walk each time): ~20% of `test_operator_redo` profiled** · group: agent-start-up-cost · upstream / checkpoints · [[r-perf-2026-10-17]]; also 34 s of `test_checkpoint_gitlinks.py`'s 54 s setup (lane h1-setup, `q/h1-setup`) · upstream issue or a caller-side memo · w8-slow-b 133892f92b: ~11 ms per `_run_git` child in `selected_git_env` → `pm.ensure("git")` (970 `pm.environments.store_root` / 6,402 `pm.paths.repo_root` calls for 193 children) plus a double spawn through PM's `cmd\git.exe` shim (29 ms vs 18 ms for `mingw64\bin\git.exe`) — about half of each git call on Windows · DEFERRED 2026-11-09: owner triage — Speed-up mostly felt in test runs; upstream owns the fix; until the owner reopens it


### Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)

- **`RT-SKILL-CATALOG-FRONTMATTER` — Upstream `tools/skills_tool._skill_catalog` parses every SKILL.md frontmatter itself, and the kanban environment gate costs 3 ms per tagged skill uncached plus a 1.3 s first-call import** · group: agent-start-up-cost.skill-catalog-doors · upstream / skill catalog · build-1011-B2 `9dc0b2ad19` (60/60 parses in a primed cold child) · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` approved by owner 2026-10-15 · DEFERRED 2026-11-09: owner triage — Small performance gain; upstream-owned; until the owner reopens it · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` · its only caller is upstream

### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-08 (lane opus-w1-hermes, moved from fork-hygiene)


### Filed on arrival — 2026-10-06 (lane h-suite-tail-b)

- **`RT-DASHBOARD-AUTH-SCRYPT-IMPORT` — `plugins/dashboard_auth/basic` computes a scrypt `_DUMMY_HASH` at import time (~0.2 s), paid again on every plugin re-import (80–122 scrypt calls per test file in the profiles)** · group: agent-start-up-cost · upstream-owned · evidence: lane h-suite-tail-b profiles · an upstream issue or a caller-side memo, never an edit · no caller-side memo reaches a module-level import-time computation without editing the module · re-measured 2026-10-18 (lane w2-seams): 271–313 ms per scrypt, no caller-side fork fix; issue text in `worktrees/pr-bodies/issue-dashboard-basic-auth-lazy-scrypt.md` · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · DEFERRED 2026-11-09: owner triage — Test-speed issue only; no user impact; until the owner reopens it

### Filed on arrival — 2026-10-05 (lane h-defer, name-set sweep)


### Filed on arrival — 2026-10-02 (lane w5-fh, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (instance conversations)


### Filed on arrival — 2026-10-01 (lane rw-h)


### Filed on arrival — 2026-09-29 (lane h11-code)


### Filed on arrival — 2026-09-29 (lane h10-rtseam, filed by the orchestrator)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

- **`RT-OFFER-SDK-FREE-HTTPX` — Offer the SDK-free httpx client (re-homed `turn_runner`) upstream as a transport "client" door, after the fork polish.** · group: upstream-footprint-ledger · architecture §4; ask the owner before opening the PR. · RULED 2026-10-10 owner: yes: offer the transport client door upstream · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: offer it after the fork polish closes and upstream takes the owner's PRs again — owner 2026-09-29 + 2026-10-16

### Filed on arrival — 2026-09-29 (lane fix-node-deps, filed by the orchestrator)


### Filed on arrival — 2026-09-29 (PR #125262 review follow-up, filed by the orchestrator)


### Filed on arrival — 2026-09-27 (lane PR-REPLIES, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane HELD-TESTS, filed by the orchestrator)



### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)

- **`RT-HERMES-STATE-SCHEMA-STALE` — `hermes_state_schema.py`'s stale-FTS rebuild never recovers on SQLite 3.45.3 (Windows CPython 3.12.5): `DROP TABLE IF EXISTS messages_fts` from a fresh connection raises `vtable constructor failed: messages_fts` when the FTS5 data is corrupt, so FTS stays detached for good** · group: upstream-footprint-ledger · `upstream` · reproduced on a bare FTS5 table; the four `test_fts_runtime_rebuild.py` reds are `_up_red` rows in `tests/_downstream/id_markers/upstream_reds.py` (lane TRIAGE); sibling of the `state_db_has_structural_damage` row below · PR candidate: on that raise, drop the FTS5 shadow tables under `PRAGMA writable_schema` and recreate · filed 2026-09-26 (lane TRIAGE) · RULED 2026-10-10 owner: wait for upstream; keep the `_up_red_when(sqlite<3.46)` markers; no VACUUM INTO draft · DEFERRED 2026-11-09: owner triage — Real but rare; owner already ruled to wait for upstream; until the owner reopens it

- **`RT-HOSTED-ROOMS-CANNOT-MOVE` — `gateway/hosted_room_discussion.py` (85/33) and `gateway/hosted_rooms.py` (72/4) cannot move into fork modules: their bodies call 6+ upstream privates; retire via the Group Chat host-surface widening PR, not a move** · group: upstream-footprint-ledger · seams · evidence: `docs/agent-runtime-harness/archive/footprint-drop-2026-09-27.md` Outcome · filed 2026-09-27 · fork diff +143/−37 and +72/−4; the bodies call upstream privates, so a fork module would import six-plus `_names` · RULED 2026-10-16: owner 2026-09-29 "park until group-chat work resumes"; 2026-10-10 "parked stays parked" · DEFERRED 2026-10-18: leave both as seams until group-chat work resumes, then retire them through the Group Chat host-surface widening upstream PR (a move would import six-plus upstream `_names`); re-measured vs merge-base `d923a5eb48`: +106/−44 and +21/−4 — `docs/agent-runtime-harness/archive/footprint-drop-2026-09-27.md` Outcome

- **`RT-PROCESS-STARTUP-UPSTREAM-WORK` — Every `hermes` process pays upstream start-up work no read-only verb uses: importing `hermes_cli.config` runs provider discovery (`_inject_profile_env_vars` → `providers.list_providers`, ~1.6 s, 38 plugin dirs, 27 YAML loads) and `plugins/model-providers/fireworks` calls `get_version_info()` at import (5+ `git` subprocesses for a User-Agent); `main()` then runs `_warn_pending_fleet_restart_on_startup` (`git` via `get_code_identity`, ~0.8-1.7 s). Fork-side cut so far: the land/q4 version-info cache (boot 6 → 4.2 s); the test-child start-up snapshot landed (`aa377ccc5c`). Upstream PR candidates: lazy OPTIONAL_ENV_VARS injection, a lazy User-Agent** · group: agent-start-up-cost · `upstream` · evidence: the HQ3 commit message on lane/hq-b (`perf(cli): …`, profiles 2026-10-01) · PR candidates (w3-perf 2026-10-01): (a) defer `_inject_profile_env_vars`' provider discovery — `OPTIONAL_ENV_VARS`, `CORE_DECLARED_ENV_NAMES` and the platform-manifest precedence together behind one accessor; (b) build the fireworks User-Agent on first request — drafted as local branch `up/fireworks-lazy-user-agent` (57735398159, red recorded); (c) ask git only when the fleet receipt is unfinished or stale · RULED 2026-10-15 owner: approved: open upstream PRs (a) and (b) · DEFERRED 2026-11-09: owner triage — Noticeable but not broken; depends on upstream accepting PRs; until the owner reopens it · re-measured 2026-10-18 lane h5-boot (test venv, warm bytecode, sandbox home; cProfile to the serve's `ready` frame): `hermes_cli.config` 0.70–1.04 s of which `_inject_platform_plugin_env_vars` 0.42–0.62 s (23 platform manifests parsed again, then re-parsed by the manifest scan) and `_inject_profile_env_vars` 0.16 s; `main()` startup work `_recover_update_debts_on_startup` 0.25–0.44 s and `_warn_pending_fleet_restart_on_startup` 0.24–0.40 s; `hermes_cli/main.py` module-scope command imports a read-only verb never runs — `hermes_cli.backup` (→ `hermes_state_dbfile` → `agent.context_compressor`) 0.22–0.99 s, `model_setup_flows_local` (asyncio) 0.14–0.20 s, `secrets_cli` (rich) 0.10–0.18 s, `update_cmd` 0.2 s, `kanban` 0.23 s, `pm.install` 0.07–0.10 s; upstream share of a `harness --json status` import self-time 0.91 s vs fork 0.50 s · PR candidate (d): `main.py`'s command-module imports move into their `cmd_*` handlers · issue texts (a)–(d) above; (b) drafted `up/fireworks-lazy-user-agent` (57735398159) · every caller is upstream import-time or `main()`, so no fork memo

### Filed on arrival — 2026-10-03 (lane h-twins)

### Filed on arrival — 2026-10-03 (launcher lane rpc-census, filed by the orchestrator)

### Filed on arrival — 2026-10-03 (cold first-chat diagnosis, filed by the launcher orchestrator)

### Filed on arrival — 2026-10-03 (lane h-chatperf)
- **`RT-NATIVE-HISTORY-REREAD` — Native history is re-read from SessionDB and re-filtered against the turn ledger on every turn though the resident actor holds the same lineage; now measured as `context_native_history_ms`** · group: agent-start-up-cost.sessiondb-lineage-stamp · fork / `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_build_context` · decide whether a reused actor whose `native_revision` is unchanged may hand its own messages to the turn (SessionDB stays the authority, the revision is the guard) · evidence: turn `15c73e0c` had 168 ms of `context_built` unattributed (1035 − preload 858 − hud 7 − signature 2) · RULED 2026-10-10 owner: yes: a reused actor with an unchanged `native_revision` hands its messages to the turn; SessionDB stays the authority, the revision the guard · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` approved by owner 2026-10-15; S1–S3 built on `build/h1-lineage` (the turn hand-off is S3, 52.6 → 6.4 ms on an 800-message lineage); S4, the upstream door draft, waits on the orchestrator sequencing it with Phase B wave 2 · S1–S3 landed (fc3350d3044; `build/h1-lineage` has no unlanded patch) · DEFERRED 2026-11-09: owner triage — User-visible win already shipped; leftover is upstream paperwork; until the owner reopens it · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` § S4

## Filed on arrival — 2026-10-09 (owner: a built-in way to message a persona through the running serve)

## Filed on arrival — 2026-10-09 (perf programme close-out sweep)


## Filed on arrival — 2026-10-09 (GenUI wire receipts)



## Filed on arrival — 2026-10-09 (Console history authority audit)

## Filed on arrival — 2026-10-09 (launcher transcript capability audit; the launcher halves are in `eternia_launcher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` under the same-dated heading)

## Filed on arrival — 2026-10-09 (lane h-hud-receipt)


## Filed on arrival — 2026-10-10 (lane h-settle-push)


## Filed on arrival — 2026-10-10 (lane h-busy-queue)



## Filed on arrival — 2026-10-10 (launcher lane q-turn)


## Filed on arrival — 2026-10-12 (launcher lane q-mc)




## Filed on arrival — 2026-10-15 (Claude sol-prov landing)


## Filed on arrival — 2026-10-15 (launcher QA provider check)


## Filed on arrival — 2026-10-15 (lane w1015-prov-l)


## Filed on arrival — 2026-10-15 (launcher lane console-scroll-2)


## Filed on arrival — 2026-10-15 (launcher lane w1015-misc-l)


## Filed on arrival — 2026-10-15 (owner rulings: hermes builds first for the Agent Console)


## Filed on arrival — 2026-10-15 (lane w1015b-con-x)


## Filed on arrival — 2026-10-15 (owner: provider SDKs on first setup)



## Filed on arrival — 2026-10-15 (lane e-triage: blockers with no row)


## Filed on arrival — 2026-10-15 (launcher lane w1015e-mc-l)

## Filed on arrival — 2026-10-15 (lane w1015i-packs)

## Filed on arrival — 2026-10-15 (lane w1015j-hermes)


## Filed on arrival — 2026-10-15 (backend build wave A, realms)




## Filed on arrival — 2026-10-16 (backend build wave B, realms)




### Filed on arrival — 2026-10-16 (launcher lane w1016c-mc)


### Filed at the launcher w1016 wrap-up — 2026-10-16


### Filed on arrival — 2026-10-18 (lane q-reds, branch `q/q-reds`)

### Filed on arrival — 2026-10-18 (lane q-stale, branch `q/q-stale`)
### Filed on arrival — 2026-10-18 (lane q-stale, branch `q/q-stale`)



### Filed on arrival — 2026-10-18 (lane r-product, branch `q/r-product`)

### Filed on arrival — 2026-10-18 (lane h2-sleep)
- **`RT-ROOM-LEASE-LAPSES-MID-CYCLE` — The hosted-room driver renews its room lease only between room cycles (`tui_gateway/hosted_room_driver.py::_ensure_lease` / `_renew_lease_if_needed`), so a cycle that blocks longer than the lease TTL loses the lease mid-turn and the turn never settles; and a successor serve adopts a room whose owner left a task running only once the old lease expires (up to 30 s of restart recovery, the fork's `DiscussionService` default)** · group: discussion-rooms-reliability · upstream / discussions room driver · lane h2-sleep 2026-10-18: at a 5 s test TTL a real-native room cycle ran 6.5 s and `test_real_group_compare_discuss_target_and_reopen` red; the fork now sets the TTL through `DiscussionService(lease_ttl=)` (8bcbe70242) · BLOCKED 2026-10-18: upstream — issue text: "`HostedRoomRuntime` renews a room lease only between cycles; renew from a heartbeat while an attempt executes, and let a successor with the same gateway identity adopt a lease whose `process_generation` is provably dead instead of waiting out the TTL" · v0.23.1: upstream e0d3dda02a (`tui_gateway/hosted_room_lease_keeper.py::LeaseKeeper`) renews the room lease while a turn waits and runs, which settles the mid-cycle lapse; a successor adopting a provably dead `process_generation`'s lease without waiting out the TTL is still not upstream

### Filed on arrival — 2026-10-18 (lane h3-plugins, branch `q/h3-plugins`)

### Filed on arrival — 2026-10-18 (lane h4-hotpath, branch `q/h4-hotpath`)
- **`RT-I18N-BUNDLED-PER-HOME` — `agent/i18n.py::_load_catalog` re-parses the bundled locale YAML once per `(HERMES_HOME, lang)`: 23.8% of 3,668 profiled seconds over 12 files (68% of `test_goal_dispatch`)** · group: agent-start-up-cost · upstream / i18n · [[r-perf-2026-10-17]] § h4-hotpath · DEFERRED 2026-11-09: owner triage — Performance mostly felt in tests; upstream-owned; until the owner reopens it
- **`RT-CONFIG-NOFILE-REBUILD` — `hermes_cli/config.py::_load_config_impl` caches nothing when the home has no `config.yaml`, so every read rebuilds the defaults (~2 ms; 61,049 rebuilds, 14.6% of 3,668 profiled seconds, all 23 files)** · group: agent-start-up-cost · upstream / config · [[r-perf-2026-10-17]] § h4-hotpath; per SQLite open via `hermes_state_wal.apply_wal_with_fallback`: 2.52 vs 0.37 ms/open without/with a `config.yaml`, `test_discussion_runtime` 72.5 → 41.2 s with one (re-measured 2026-10-18) · DEFERRED 2026-11-09: owner triage — Performance tweak; upstream-owned, workaround is adding a file; until the owner reopens it
- **`RT-AUX-KEY-CHAIN-LOAD-CONFIG` — `agent/auxiliary_client._resolve_api_key_provider` walks ~48 providers per auto resolution, each paying `hermes_cli/auth._model_level_key_env` → `load_config()` (a full deepcopy) plus a pool load: 34 resolutions → 1,530 `load_config`, 1,648 pool loads, 40% of `test_compression_rotation_state`** · group: agent-start-up-cost · upstream / auxiliary client · [[r-perf-2026-10-17]] § h4-hotpath · DEFERRED 2026-11-09: owner triage — Performance gain only; upstream-owned; until the owner reopens it

## Filed on arrival — 2026-10-18 (lane h5-boot)

## Filed on arrival — 2026-10-18 (land h1018)


## Filed on arrival — 2026-10-18 (owner sitting: Work on todo boards)


## Filed on arrival — 2026-10-18 (design: dispatcher and libraries)


### Filed on arrival — 2026-10-18 (lane w2-phone, branch `w2/phone`)

- **`RT-UPSTREAM-TEST-RACES-TWO` — Two upstream tests race their own harness, not the product: `tests/tools/test_browser_eval_supervisor_path.py::_make_supervisor_with_cdp_fn` starts the loop thread and returns before `run_forever`, so `evaluate_runtime`'s `loop.is_running()` check fails on a slow schedule; `tests/agent/test_run_agent.py::TestExecuteToolCalls::test_sequential_tool_calls_run_without_delay` patches `agent.tool_executor.time.sleep`, which is the `time` module's attribute, so any other live thread's nap trips `assert_not_called`** · group: upstream-load-flakes · upstream-owned (both test files) · lane w2-reds 2026-10-18: green alone x3 on main; planted controls red — a 0.2 s delay before `run_forever` gives `assert False is True`, a background `time.sleep(0.001)` thread gives "Called 151950 times" (formerly FORK-CI-FLAKY-THREE, CI run 33969282189) · upstream PR: wait on a started-Event before returning the supervisor; patch a name the executor imports, or assert on the executor's own sleep calls · DEFERRED 2026-10-18: the fix is an upstream PR, and prepared PR branches stay idle until upstream takes the owner's PRs again (`FORK-24-UPSTREAM-PR-BRANCHES`) — owner 2026-10-16

### Filed on arrival — 2026-10-18 (lane w2-realm, branch `w2/realm`)

## Filed on arrival — 2026-10-18 (land w2)

- **`RT-CONTEXT-MANIFEST-WITHIN-KIND` — /context manifest marks every non-empty candidate of one kind loaded, but the builder loads only the nearest .hermes.md / first CLAUDE.md** · group: upstream-footprint-ledger · upstream / prompt context · `agent/context_file_sources.py::list_context_file_sources` vs `agent/prompt_builder.py::_load_hermes_md`/`_load_claude_md`; the w2-agent `winner = None` carry made it visible across kinds · retire via the `context_files.load_all` PR (per-candidate loaded flags) · DEFERRED 2026-11-09: owner triage — Misleading display in a power-user command; upstream-blocked; until the owner reopens it

## Filed on arrival — 2026-10-18 (land w3)

### Filed on arrival — 2026-10-18 (lane w5-misc, branch `w5/misc`)

### Filed on arrival — 2026-10-18 (lane w5-sched, branch `w5/sched`)
- **`RT-SCHEDULE-SYNC-AND-KNOB` — `store/schedules/` is not a realm-sync family (plan §2.3 says key-wise like `workspace_slots`); the knob half LANDED (lane w6-misc: root config `agent_runtime.scheduler.max_parallel`, read each tick)** · group: remote-parity-and-two-machine-proof · fork / scheduling · `agent_runtime/work_store/schedule_store.py`, `agent_runtime/realm_sync/document_family.py`; plan `docs/agent-runtime-harness/archive/dispatcher-and-libraries-2026-10-18.md` §2.3 · RULED 2026-10-18: owner — schedules stay local to the machine that armed them for now; the realm-sync family waits for a design of delete propagation and per-fire publish · DEFERRED 2026-10-18: owner — schedules local per machine until the sync design is planned

## Filed on arrival — 2026-10-19 (launcher wave w1020)

- **`RT-WIN-CONSOLE-FLASH-CODEX-SWITCH` — A Windows console window flashes when the Agent Console switches a chat to openai-codex** · group: provider-api-key-and-usage-source · owner 2026-10-19 13:04:41Z (launcher `[MissionModelPick]` chosen=openai-codex/gpt-6-sol): the launcher spawns nothing on that path (RPC-only; its serve child is started detached, with no console), so a console child of hermes opened it. Candidate: `agent/transports/codex_app_server.py::check_codex_binary` runs `codex --version` without `windows_hide_flags()` while the Popen beside it hides; audit the openai-codex select / models / first-turn paths for subprocesses spawned without CREATE_NO_WINDOW and pin one with a Windows test · launcher `MC-PROVIDER-SWITCH-LOCKS-PICKER` waits on it (filed by launcher lane w1020-console) · BLOCKED 2026-11-12: owner sitting — one provider sitting: the owner signs in to their own provider accounts on Windows and watches one switch to Codex for a console window flash (probably fixed by 620de2c049) · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, as recommended" · was dEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: switch a chat to openai-codex on the Windows box and watch for the flash (check_codex_binary now hides its console, 620de2c049)

## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)

- **`RT-NATIVE-WORKER-UPSTREAM-BOOT` — a native worker's remaining ~5 s before its first reply is upstream engine work no caller-side memo can key safely: `tui_gateway.server` import 3.4–4.5 s (`hermes_cli.auth` 1.6 s via `local_env_policy`; `tui_gateway.contracts` 1.1 s), the first agent build 2.8–3.9 s (`run_agent` + `model_tools` + builtin discovery), `model.options` 1.4–2.5 s first call (408 `load_pool` for 279 checks, `auth.json` re-read each), and the hourly scratch prune's `reap_processes_rooted_in` over every host process** · group: agent-start-up-cost · upstream-owned / turn latency · w10-turncost profile (the fresh-scratch stamp memo landed, first turn 12.6 → 9.2 s, n=5 loaded) · DEFERRED 2026-11-09: owner triage — Felt latency but depends entirely on upstream work; until the owner reopens it
- **`RT-DELEGATION-KNOB-ENV-DEAD` — the delegation knob env fallbacks are dead: DEFAULT_CONFIG supplies `max_concurrent_children` and `child_timeout_seconds`, so `DELEGATION_MAX_CONCURRENT_CHILDREN` / `DELEGATION_CHILD_TIMEOUT_SECONDS` never apply (env 7 → getter 10)** · group: agent-config-cleanup · upstream-owned / `tools/delegate_tool_config.py::_knob` · `docs/downstream/agent-console-subagents-settings-2026-10-19.md` § Measured · DEFERRED 2026-11-09: owner triage — Settings work through config instead; minor; until the owner reopens it

## Filed on arrival — 2026-10-20 (launcher plan: edition switch and the shared namespace store, `EterniaLauncher` `9185222120`)

- **`RT-NAMESPACE-ADOPT` — `hermes namespace adopt --from-dir <dir> [<id>…] [--dry-run]`: Developer Edition only (`_developer_edition_only`), module `agent_runtime/namespace_adopt.py` excluded from the bundle closure beside `namespace_seed`; per manifest-valid namespace: refuse busy (either side) and an existing target, `os.replace` on one volume else copy+verify(count,sizes)+remove, manifest gains `adopted_from`/`adopted_at`** · group: agent-config-cleanup · fork / `hermes_cli/namespace_cmd.py`, `agent_runtime/bundle_profiles/bundled-desktop.yaml` · plan §5 · mutation: adopt a busy namespace → the busy test reds · RULED 2026-10-20: owner — move once, Developer-Edition-only, nothing ships to release; then (Q1) "default should be appdata indeed with an override to where it is now", so nothing moves · DEFERRED 2026-10-20: not needed while `ETERNIA_HERMES_NAMESPACES_DIR` keeps an existing store in place (launcher `MC-OWNER-NAMESPACES-ADOPT`); re-enter if a developer must physically move a store

## Filed on arrival — 2026-10-22 (launcher session, owner report from a Neko Mission Lead turn)

- **`RT-SAFETY-BLOCK-LIVE-READ` — read one self-repo-blocked turn on the owner's serve and record whether the model stopped on the FINAL text (the code says the runtime does not end the turn)** · group: console-transcript-truthful.safety-block-recovery · `docs/agent-runtime-harness/planned/safety-block-recovery-2026-10-25.md` §2.1 · `tools/terminal_tool_guards.py::_blocked_json` · filed by lane w1025b-h-misc 2026-10-25 · LIVE 2026-10-26: not measured — the turn ran on the qa Lens Episode chat, which holds `read_only` admission (`toolsets_dropped` terminal), so no terminal call was made (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md` § 2026-10-26); the read needs one turn on a qa chat that is not a Lens Episode chat · READY 2026-11-12 · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — Windows only: the guard runs only there (`self_repo_guard.py`, `os.name == "nt"`) · was dEFERRED 2026-11-09: owner triage — A measurement, not a fix; until the owner reopens it · left 2026-11-05 (w1105g-hm-runtime): one self-repo-blocked terminal turn on a qa chat that is NOT a Lens Episode chat, on the owner's serve, reading whether the model stopped on the FINAL text; no serve was started: the box was under a no-detached-serve hold after the 2026-11-05 desktop-session kill, and the owner's serve and home are off limits · RULED 2026-11-06: owner — "6 reccomendations are good": run the turn on the QA serve (a qa chat that is not a Lens Episode chat, QA home with openai-codex), not the owner's serve · released 2026-11-06 w1106a-live-c: not runnable on Linux — `tools/self_repo_guard.py::guard_active` is `os.name == "nt"`, so nothing is blocked on POSIX and a self-repo turn here would really rewrite the hermes checkout the QA serve runs from (the machine install); left: run the read on a Windows QA serve (ruling 2026-11-06 allows a QA serve) · left 2026-11-08 (w1108a-hm): still not runnable on Linux (`tools/self_repo_guard.py::guard_active` is `os.name == "nt"`) and no committed log holds the read; left: on a Windows QA serve (QA home, openai-codex), one self-repo-blocked terminal turn on a qa chat that is NOT a Lens Episode chat, then read its transcript for whether the model stopped on the FINAL text · REQUIRES windows, linux · host 2026-11-09 (w1109a-hostsweep): owner rule — QA runs on Linux too; nothing in this check is Windows-only
- **`RT-SAFETY-BLOCK-ALLOW-ONCE` — an operator allow-once for a FINAL self-repo block through upstream's approval queue (`submit_pending` / `resolve_gateway_approval`, the dangerous-command card), recorded with who allowed it; the guard consulting the queue is an upstream change, so an upstream PR first** · group: console-transcript-truthful.safety-block-recovery · `docs/agent-runtime-harness/planned/safety-block-recovery-2026-10-25.md` §2.4 · `tools/approval.py::submit_pending` · `tools/self_repo_guard.py::_block_message` · filed by lane w1025b-h-misc 2026-10-25 · DEFERRED 2026-11-09: owner triage — New convenience feature; upstream must move first; until the owner reopens it

## Filed on arrival — 2026-10-22 (land w1022d)


## Filed on arrival — 2026-10-23 (launcher lane w1023l-mc)


## Filed on arrival — 2026-10-24 (launcher session, owner report: yellow readiness text on every agent)

## Filed on arrival — 2026-10-25 (lane w1024t-hermes2)

## Filed on arrival — 2026-10-25 (launcher lane w1025a-comp)

## Filed on arrival — 2026-10-26 (launcher session: first Linux install of the Developer Edition)


## Follow-up suggestions — planned completion and qualification

- **`RT-NEXT-PROMPT-PROVIDER-EVAL` — Complete remaining suggestion provider and native placement qualification** · group: console-top-bar-and-menu-proposal.console-next-prompt-completion · `docs/agent-runtime-harness/planned/console-next-prompt-completion-2026-10-27.md` · DEFERRED 2026-11-09: owner triage — Optional feature that ships off; evaluation can wait; until the owner reopens it · Corrected 36-call corpus and Windows Developer/local live provider-to-composer Use/Tab/chord/dismiss/off passed; ownership blocker resolved through existing creation/send metadata with exact validation retained; remaining human acceptance/edit burden, cost, native visible latency/primary-turn overhead, bundled/paired-remote/two-window/multi-persona matrix, stock next_prompt versus console_next_prompt override/reset and single-producer coexistence; preserve personas, inherited routing and default-off; pair Launcher `MC-NEXT-PROMPT-QUALIFY`; evidence `docs/downstream/console-next-prompt-evaluation-2026-10-27.md` · Launcher inline presentation implemented; focused native Tab/Use/chord/dismiss/off evidence added 2026-10-28, with unchanged ownership/personas/auxiliary routing and zero new attempts after an off-state reply; keep the remaining matrix open, including an observed auxiliary-call-in-flight disable; no Harness implementation or duplicate provider corpus for this presentation change · left 2026-11-05 (w1105g-hm-runtime): the remaining matrix is live and human — acceptance/edit burden, cost, native visible latency, bundled/paired-remote/two-window/multi-persona, stock next_prompt vs console_next_prompt override/reset — on the Windows Developer/local build the earlier passes used · REQUIRES windows, linux · host 2026-11-09 (w1109a-hostsweep): owner rule — QA runs on Linux too; nothing in this check is Windows-only

## Filed on arrival — 2026-10-27 (hermes lane w1027a-h-rt)


## Filed on arrival — 2026-10-27 (launcher lane w1027b-mc)


## Filed on arrival — 2026-10-27 (launcher lane w1027e-plan-mc)


## Filed on arrival — 2026-10-27 (launcher lane w1027e-plan-comp)


## Filed on arrival — 2026-10-27 (launcher lane w1027g-lens)


## Filed on arrival — 2026-10-27 (orchestrator, after lane w1027g-h-head)


## Filed on arrival — 2026-10-27 (launcher lane w1027i-plan-ai)


## Filed on arrival — 2026-10-27 (planned/ triage lane w1027j-h-tri-c)


## Filed on arrival — 2026-10-27 (owner: dynamic harness lifetime, mutual supervision)



## Windows baseline qualification — 2026-10-27



## Filed on arrival — 2026-10-28 (orchestrator: owner "i don't have a default realm anymore")


## Filed on arrival — 2026-10-28 (orchestrator: owner direction on slots, projects and workspaces)


## Projects integration — 2026-10-28


## Filed on arrival — 2026-10-28 (orchestrator: owner on chat sharing and the learning loop)


## Filed on arrival — 2026-10-29 (planning lane w1029p-projects: the Project record, slots re-keyed to `<project>/<slot>`, shared chats)


## Filed on arrival — 2026-10-30 (launcher lane w1029f-proj: shared chats)

## Filed on arrival — 2026-10-30 (launcher lane w1030a-dist: relaunch after a game)



## Filed on arrival — 2026-10-30 (character migration validation)



## Character completion qualification findings — 2026-10-31


## Filed on arrival — 2026-10-31 (lane w1031j-h-rt)


## Filed on arrival — 2026-11-01 (owner: one context file per folder slot)


## Filed on arrival — 2026-11-01 (owner: Anthropic usage is not measured like ChatGPT)

- **`RT-USAGE-ANTHROPIC-UNITS-SCOPE` — `_fetch_anthropic_account_usage` reads `/api/oauth/usage` with `_usage_windows(..., fraction=True)`, which multiplies any value ≤ 1 by 100, so if utilization already arrives as a percent a 0.5 % window shows 50 % and 1 % shows full (the fixture in `tests/agent/test_account_usage_pool_fetch.py` encodes fractions, the same unverified belief); the extra-usage credit goes out as a free-text details line, not a typed balance; and `_serialize_usage_window` drops each window's `scope`, so the client cannot tell an Opus-only cap from the account cap** · group: provider-api-key-and-usage-source · `agent/account_usage.py::_fetch_anthropic_account_usage` · `hermes_cli/harness_parts/usage/serialize.py::_serialize_usage_window` · 2026-11-02: launcher `MC-USAGE-ANTHROPIC-RESEARCH` landed `7019b2c2fb` and found the `/api/oauth/usage` units on no Anthropic page, so the units wait on one recorded payload; the `scope` half needs no units and is split out as `RT-USAGE-WINDOW-SCOPE-SERIALIZE` · DEFERRED 2026-11-09: owner — waits on deferred `MC-USAGE-ANTHROPIC-OAUTH-UNITS` (owner sittings parked 2026-11-09: "the whole tasks of them should be deffered if they aren't blocking work"); was BLOCKED 2026-11-02: launcher — `MC-USAGE-ANTHROPIC-OAUTH-UNITS` one recorded `/api/oauth/usage` payload beside Settings › Usage settles fraction vs percent and cents vs dollars · note 2026-11-12 (deferred-task review): the scope half is already done (`serialize.py`); what is left is the units and the typed balance, which wait on launcher `MC-USAGE-ANTHROPIC-OAUTH-UNITS`

## Filed on arrival — 2026-11-01 (lane w1101b-perf, the first idle-box run)


## Filed on arrival — 2026-11-02 (launcher lane w1101h-teardown)





## Optional suggestion post-call work — 2026-11-03




## Filed on arrival — 2026-11-04 (owner via Eternia: the workspace absorbs Projects; plan w1104-wsmerge)

- **`RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM` — once the owner's first gateway answers: stop the alice upstream gateway, remove its logon task, delete the shared bot token from the eight profile `.env` files (no code)** · group: remote-parity-and-two-machine-proof.external-gateway-access · `docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md` §2 D4, §5 · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: after the owner's first gateway is live
- **`RT-WS-RECALL-RENAME-S3-PUBLISH` — publish `recall_shared_workspaces` in the persona-instance projection (flip S2's spelling map), only once every realm member's edition reads it (S1); the sync has no edition floor, so the gate is a release ruling or an edition-floor field on the projection head first** · group: workspace-absorbs-projects · `docs/agent-runtime-harness/planned/recall-field-rename-mixed-editions-2026-11-06.md` §2 S3 · filed by lane w1105i-hm 2026-11-06 · DEFERRED 2026-11-09: owner triage — A rename with no user gain; just needs a release decision later; until the owner reopens it


- **`RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS` — Lens keeps each workspace's monitors apart, and old test monitors stop showing in your panel** · group: eternia-lens · detail: Lens keeps ONE store per runtime at the head home (`lens_root()` → `<head home>/lens`), so every agent, workspace and test that ran in a namespace shares one fold; the owner's panel (2026-11-08) shows five OPEN Episodes from wave w1025a's QA monitors (`w1025a_l1`, `_l3`, `_l3b`, `_proof`, `_w107`, 2026-10-25) in their real namespace while reporting 0 monitors; (1) a monitor and its Episodes and receipts carry the workspace they belong to, and `runtime.lens.*` reads filter by it (with an all-workspaces read), (2) an Episode whose monitor is gone is ORPHANED — reported as such and closable in one call, never left open forever, (3) the five monitors were NOT a QA leak: they came from lane w1025a-hlive's owner-ruled live sitting on the owner's own serve, which paused and retired them with their Episodes still `active` (no path to close) · `agent_runtime/lens/store.py:190` · `agent_runtime/lens/episode.py` · `agent_runtime/lens/snapshot_fold.py` · `agent_runtime/lens/retention.py` · found 2026-11-08 by the owner in Eternia; the panel half is `eternia_launcher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` row `MC-LENS-PANEL-REDESIGN-PER-WORKSPACE` · read 2026-11-08 (why Dismiss does nothing): the owner pressed Dismiss on all five; `harness snapshot` now shows each with `decision: dismiss` but `state: active`, still in `open_episodes` — by design an ACTIVE Episode "stays while it breaches, whatever was decided" (`agent_runtime/lens/store_decisions.py` header) and becomes `closed_recovered` only when its monitor next observes it not firing (`agent_runtime/lens/episode.py:196`); these monitors no longer exist, so no observation ever comes and a dismissed orphan stays open forever — the orphan close in (2) must cover a dismissed ACTIVE Episode whose monitor is gone, and Eternia must not show Dismiss as if it closed something it cannot · data contract (for Eternia's Lens plan, `MC-LENS-PANEL-REDESIGN-PER-WORKSPACE`): `runtime.lens.list` / `episodes` / `receipts` / `fold` take an optional `workspace_id`; absent = every workspace (the old answer), given = only that workspace's monitors and their Episodes and receipts; every monitor, Episode and receipt row carries `workspace_id` (null for a monitor written before the column), every Episode row carries `orphan` (null | `monitor_gone` | `monitor_retired` | `monitor_paused`); `runtime.lens.episodes.close_orphans {workspace_id?}` -> `{closed}` resolves every orphan; retire resolves its monitor's open Episodes; Dismiss of an orphan resolves it; a create without `workspace_id` belongs to the active workspace · BLOCKED 2026-11-10: owner sitting — only the owner's own data is left: the five `w1025a_*` Episodes on the owner's Windows serve; steps: (1) run a hermes at or after `ec52d376af` there and relaunch Eternia, (2) Mission Control › Lens › All workspaces: the five sit in one orphan group (`orphan: monitor_retired` — their monitors were retired before a retire closed its Episodes, and the old Dismiss could not settle an ACTIVE Episode), (3) press that group's Close all and confirm (`runtime.lens.episodes.close_orphans {}`), (4) read the header at 0 open and `hermes harness snapshot` with no `w1025a_*` in `open_episodes`, then close this row with that read · handoff 2026-11-10 (w1110d-lens): the hermes half read live on an isolated Linux serve (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md` § 2026-11-10): `workspace_id` on every row and filtering `episodes` / `list`, retire resolving its open Episode at once, a paused monitor's Episode `orphan: monitor_paused`, `close_orphans` scoped by workspace and unscoped; Eternia's panel half was read live by w1109a-board5/board6 and MC-LENS-PILL-CLOSE-LIVE-READ

## w1108b hand-off to the Linux box — 2026-11-08


## Filed on arrival — 2026-11-08 (lane w1108b-hfh)


## Filed on arrival — 2026-11-08 (Eternia lane w1108d-mclive)


## Filed on arrival — 2026-11-09 (Eternia lane queue-grammar-at-write)


## Filed on arrival — 2026-11-09 (Eternia lane w1109a-console-live)

## Filed on arrival — 2026-11-09 (Eternia lane w1109a-console2)

## Filed on arrival — 2026-11-09 (Eternia lane w1109a-lens3)

- **`RT-FLAKE-UPDATE-EXISTING-MAIN-SWITCH-HANDOFF` — The update command's hand-off after switching to an existing main passes even on a busy box** · group: upstream-load-flakes · `tests/hermes_cli/test_update_existing_branch_baseline.py::test_command_hands_off_after_existing_main_switch` · found 2026-11-10 by w1110d-hm2: red once in a prepush `touched` run at load 31 beside an unrelated change; not reproduced alone · DEFERRED 2026-11-10: a load-only red joins the deferred upstream-load-flakes batch; reproduce on a quiet box first

## Filed on arrival — 2026-11-10 (Eternia lane w1110c-hmsync)

## Filed on arrival — 2026-11-10 (lane w1110c-hm3)

- **`RT-ROOM-TURN-CONNECTION-CHURN` — Discussion rooms would move between members faster if a turn did not open the room database about seventy times** · group: agent-start-up-cost · `agent_runtime/discussions/service.py::DiscussionService.prepare`, `gateway/hosted_room_policy_checkpoint.py`, `tui_gateway/hosted_room_driver.py` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2: after 5cd83a166db a twelve-member room still takes ~0.8 s per member turn with an instant model, CPU-bound on SQLite connection opens (~4,100 per two-round test; every op opens and closes its own connection); `prepare` runs twice per turn (the terminal publish, then the next cycle), each reading the room three times and the policy checkpoint twice; most opens are in upstream hosted-room modules (a door, never an edit); Windows also pays `tests/home_io_guard.py`'s realpath per mkdir · DEFERRED 2026-11-10: joins the owner-deferred speed task TASK-AGENT-START-UP-COST

## Filed on arrival — 2026-11-11 (launcher plan w1111e-manage-ws)

- **`RT-GROUP-MEMBER-FIRST-TURN-COLD-START` — A group member with turn isolation on asks its model sooner after you message the room** · group: agent-start-up-cost · measured 2026-11-12 by w1112a-hmtests on DESKTOP-QJ7DDV2 (moderate load, eight runs of `tests/agent_runtime/test_discussion_group_compute.py` with temporary monotonic stamps): submit → claim 0.05 s, → member worker `main` 0.6-1 s, → worker ready 1.3-2.3 s more, → `open_member` done 2-3.7 s more, → compute host `main` 1-1.4 s more, → `send` returns 1.5-2 s more, → first model request 6.2-9.6 s more; 15-17 s on a quiet box, 27 s on a busier one; the last leg (compute host to first request) is the largest · REQUIRES windows · DEFERRED 2026-11-12: its task is deferred until the owner reopens it
- **`RT-REJOIN-PULLS-THE-SERVER-REALM-FRESH` — Re-joining a server gives you its realm fresh, and keeps your local copy beside it** · group: rejoin-fresh-realm · `agent_runtime/realm_leave.py`, `agent_runtime/realm_membership.py`, `agent_runtime/realm_sync/revocation.py`, `docs/agent-runtime-harness/03-transport-and-wire.md` · filed 2026-11-12 by w1112b-hm-rejoin on the owner's direction · RULED 2026-11-12: owner, on what a re-join does with a realm that turned local — "what do you mean if its moved out then there is nothing to publish" and "it would be less buggy if it kept your local realm and then re-pulled the fresh one from the community server"; on where the ids change — "it should be rekeyd as soon as you leave and checked for a rekey again once joined back". So: a leave re-keys the realm and whatever of its contents would collide with the server's ids as part of becoming local; a re-join checks again for any id that still collides, re-keys those local items aside, then pulls the server realm fresh; nothing done while local is published by a re-join · supersedes the re-bind-and-merge of `RT-LEFT-SERVER-REALM-STAYS-LISTED` (ed84b2c01a, 7660bf4b30: same realm id bound again, team baselines set aside and restored) and the re-join branch of `RT-REJOIN-KEEPS-WORKSPACES-MOVED-WHILE-LOCAL` (30bf4d08c7); the leave itself, the wide reason set, archive rules and the ordinary-move fixes of 30bf4d08c7 stand · RULED 2026-11-12: owner, shown the survey and asked "Build the fresh-pull re-join as its own task, with the two recommendations?" — "Yes, own task". Accepted: (1) the leave makes the realm local at once and records the re-key as owed in a journal; the one owned re-key function runs the first moment nothing is running in that realm, at the latest at the next serve start; a re-join finishes any owed or half-done re-key before its fresh pull and answers a retryable "realm busy" while a turn is live; (2) the agents and their chats return with the fresh server realm under the team's ids (chats never leave the machine); the local copy keeps workspaces, boards and cards, office layout, levels, brain and Work history under new ids and gets new agents of the same personas at its desks, with empty chats · plan `docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md` §5, §7, §9 slice 6: the switch-over, ONE landing — the leave owes the re-key, the re-join adopts fresh with the collision re-check and `realm_busy`, the re-bind and `keep_team_baselines` / `restore_team_baselines` go, the wire doc, the two-machine walk · READY 2026-11-12 · unblocked 2026-11-12: `RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START` closed DONE 57849a6b4d · handoff 2026-11-12: slice 1 of six is on main and has no caller (lane w1112b-hm-rejoin2); a member still sees the re-bind of ed84b2c01a / 30bf4d08c7. The two-machine walk of plan §9 slice 6 has not been run; no real `hermes harness` child has driven the re-key yet (there is no verb) — the walk models are lane hm-realm2's `.lane_logs/r2/row{2,3,4}.py` · handoff 2026-11-12: survey only, nothing built (lane w1112b-hm-rejoin; findings in the wave holding file, lines `w1112b-hm-rejoin SURVEY 1/6`–`6/6`). Workspace ids are global on an install (`paths.workspace_path`; the generic pull overwrites and re-homes a colliding workspace, `realm_sync/pull.py` `_overwrite_generic_families`), so a realm-only re-key is refuted. The re-key must be ONE journaled function reaching ~10 realm-keyed and 30+ workspace-keyed places (census in the holding file: store records, `office/`, `boards/board_default_<ws>`, `levels/`, `workspace_slots/`, `work/<ws>/` with its absolute brain path and git worktrees, chat fold/exports/db, schedules, `machine_roots.json`, discussion tables in `state.db`, lens, baselines, pointers); closest model `project_migration.migrate_namespace` (boot-time, idempotent by deleting old shapes last). Still to remove once built: `keep_team_baselines` / `restore_team_baselines` and the re-bind in `realm_membership.adopt_realms`, and the re-join wording in `docs/agent-runtime-harness/03-transport-and-wire.md`. Eternia must honour a workspace old-id→new-id map and owns the level bytes · handoff 2026-11-12 (lane w1112b-hm-rejoin3, context spent before this row): what the re-key does today and the switch-over must use — `owe_rekey(realm_id, reason=…)` at the leave (the map is the realm AS IT IS AT THAT MOMENT: workspaces, boards, the agents then seated, board-minted cards), `rekey_realm(old id)` (steps agents, content, rename, git, outside, ledgers; resumable), `realm_rekey_agents.restore_parked_agents(old id)` before the fresh pull, `realm_rekey_journal.rekeyed_from`. Not built, each to settle here: (1) the fresh pull meets restored team agents with NO persona-instance baseline (the baselines moved to the new realm id) — check `apply_persona_instance_pull` classifies local-present + remote-present + no-baseline as converged or adopts, never a conflict sidecar; (2) install-wide catalogues are not re-keyed (maps, prefabs, persona definitions, skills): the team's copy of the same id meets the local one — say what a member sees; (3) this machine's folder slots, env fills and Lens watches moved with the local copy, so the fresh realm's workspaces arrive with no folder bound, as for a first-time joiner — say so in the wire doc or copy the bindings; (4) a promoted brain keeps the team's remote (`RT-LEFT-REALM-BRAIN-STILL-PUSHES-TO-THE-TEAM`); (5) the collision re-check can call `owe_rekey` + `rekey_realm` only per REALM today — a one-workspace map (plan §7) needs `owe_rekey` to take a workspace subset; (6) `realm_busy` is not built (it rides `RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START`'s busy facts); (7) no real `hermes harness` child has driven any of it — every test is in-process over real stores, real git and a real bare team repository · **TAKEN 2026-11-12 w1112b-hm-rejoin4 on nekwo-ubuntu24 as nekwo in hm-w1109a-2**
- **`RT-LOCAL-REALM-PUBLISH-SAYS-REMOTE-UNREACHABLE` — Publishing a realm that has no server says it worked instead of reporting an unreachable remote** · group: rejoin-fresh-realm-followups · `agent_runtime/realm_sync/publish.py` (the push after the commit), `agent_runtime/realm_sync/git.py` (`_sync_repo_path`: the `local` repository) · seen in a test: `tests/agent_runtime/test_realm_rekey_census.py` — `publish_realm_sync` on a realm that turned local commits to `realm_sync/local`, then raises `sync_remote_unreachable` ("committed locally but could not push upstream") because the repository has no `origin`; the census seed and the outside-the-store test both swallow it · already so before the re-key (the seed of 808cca7fd3 catches it) · filed 2026-11-12 by w1112b-hm-rejoin3 · READY 2026-11-12 · done when: a publish of a server-less realm whose sync repository has no remote returns its committed result, or the code shows no client can ask for it
- **`RT-QUEUE-ROW-HANDOFF-HAS-NO-COMMAND` — A lane can add a handoff note or a second blocker to a row with one command instead of a hand edit** · group: rejoin-fresh-realm-followups · `scripts/work_row.py` · seen live: lane w1112b-hm-rejoin2 left five rows with handoffs by hand edit plus a grammar run (~3 min, its INEFF line in the wave holding file); lane w1112b-hm-rejoin3 filed these rows the same way · filed 2026-11-12 by w1112b-hm-rejoin3 · READY 2026-11-12 · done when: `work_row.py handoff <ID> --note "…"` appends a dated handoff segment, commits and pushes like the other ops, and the grammar test passes on the result
- **`RT-PREPUSH-MISSES-STALE-RPC-MANIFEST-AND-CLI-DUMP` — A change to a runtime request's accepted fields is told before it lands that its two recorded contracts need regenerating** · group: rejoin-fresh-realm-followups · `scripts/prepush.sh`, `tests/agent_runtime/_serve_rpc_manifest.py`, `scripts/dump_cli_contract.py` · seen live 2026-11-12 (lane w1112b-hm-rejoin4b, 9966cb8023): adding `board_id` to five `runtime.board.*` verbs and `--board` to their argv twins left `tests/agent_runtime/serve_rpc_manifest.expected.json` stale; `scripts/prepush.sh` was green on that commit (its touched step runs only test files the branch changed or the pusher names) and the stale file was found by a grep, then fixed in 712663095a before the push; the CLI dump was caught only because the lane ran `scripts/dump_cli_contract.py --check` by hand · read in code, not reproduced: the six tests that read the manifest expectation and `tests/hermes_cli/test_cli_contract_dump.py` are not in `prepush.sh --list-gates` · guess: both checks are cheap enough for the gates step when `agent_runtime/serve_rpc/` or `hermes_cli/harness_parts/parser/` differs from the merge-base · not in done-when of `RT-REJOIN-CARD-VERB-WITHOUT-BOARD-PICKS-EITHER-COPY` · filed 2026-11-12 by w1112b-hm-rejoin4b · READY 2026-11-12 · done when: a branch that changes a serve-RPC method's honoured params or an argparse flag without regenerating the manifest expectation or the CLI contract dump reds `scripts/prepush.sh`, naming the regenerate command
- **`RT-QUEUE-ROW-OP-PUSHES-BEFORE-THE-LANES-CHECKS` — A lane can record a row change without it reaching main before the lane's own checks have run** · group: rejoin-fresh-realm-followups · `scripts/work_row.py` (`commit_and_push`) · seen live 2026-11-12 (lane w1112b-hm-speed, its INEFF line in the wave holding file): `work_row.py close` committed and pushed to `main` by itself, before the lane's pre-push checks and gates could run; they were green after the fact · read in code, not reproduced: every operation pushes `HEAD` to the target unless `--no-commit` is given, which leaves the edit uncommitted, so there is no way to commit a row change and hold the push; a `HEAD` that carries other unpushed commits takes them to `main` with the row change · related: `RT-QUEUE-ROW-HANDOFF-HAS-NO-COMMAND` (same script) · already there at c7109865a0 · filed 2026-11-12 by w1112b-hm-qtools · READY 2026-11-12 · done when: `work_row.py <op> … --no-push` commits the row change by pathspec and pushes nothing, the default still pushes, and `tests/tooling/test_work_row_script.py` holds both
- **`RT-QUEUE-ROW-APPEND-LANDS-AT-THE-BOTTOM-OF-THE-NOTE` — A new row filed with the row command lands beside its task's other rows, not under whatever heading is last** · group: rejoin-fresh-realm-followups · `scripts/work_row.py` (`edited_text`, `_note_and_text`) · seen live 2026-11-12 (lane w1112b-hm-turn5, its INEFF line in the wave holding file): three filings with `work_row.py append`, a task row among them, each landed at the end of the note under an old dated heading and was moved by hand, about 2 minutes each · read in code, not reproduced: `append` adds the line to the end of the note's text, and with no `--note` takes the first queue note found · related: `RT-QUEUE-ROW-HANDOFF-HAS-NO-COMMAND` (same script) · already there at c7109865a0 · filed 2026-11-12 by w1112b-hm-qtools · READY 2026-11-12 · done when: `append` puts a subtask after the last live row of its group in the note that holds them and a task row after the last row under that note's Tasks heading, `--under "<heading>"` names a heading instead, a row with nowhere better still lands at the end, and `tests/tooling/test_work_row_script.py` holds each
- **`RT-PREPUSH-RUNS-A-NAMED-FIXTURE-AS-A-TEST` — Naming a fixture or a helper file to the pre-push check no longer fails it with "no tests ran"** · group: rejoin-fresh-realm-followups · `scripts/prepush.sh` · seen live 2026-11-12 (lane w1112b-hm-rejoin3, its INEFF line in the wave holding file): three pre-push rounds, about 8 minutes, lost to argument lists built with `git grep -l <symbol>` — the list held `.json` fixtures and conftest plugins, which the touched step ran as tests and reddened "no tests ran" · read in code, not reproduced: every path argument that exists joins the touched step, whatever its name · filed here, not under the pre-push task, because that task is claimed on another machine this wave · already there at c7109865a0 · filed 2026-11-12 by w1112b-hm-qtools · READY 2026-11-12 · done when: an argument that is a file not named `test_*.py` is skipped with one line naming it, a test file or a directory still runs, and `tests/scripts/test_prepush_sh.py` holds both
- **`RT-LEFT-REALM-BRAIN-STILL-PUSHES-TO-THE-TEAM` — After you leave a server, Work done in your local copy is not sent to the team's shared task repository** · group: rejoin-fresh-realm-followups · `agent_runtime/work_store/default_brain.py` (`promote_default_brain`, the binding's `remote_url`, slot `brain`), `agent_runtime/realm_leave.py` · read in code, not reproduced: a workspace brain that was promoted has the team's private `eternia-work-<slug>` repository as its git remote and a declared `brain` slot; `make_realm_local` drops the realm's server and sync address but does not touch the brain's remote, so a Work write in the local copy still pushes there — this was already so after ed84b2c01a, before the re-key · guess: the re-key should detach the remote for the local copy (keep the history, drop `origin`, clear `remote_url`) and the fresh realm adopts the declared brain as a second machine does · filed 2026-11-12 by w1112b-hm-rejoin3 · READY 2026-11-12 · done when: a left realm's promoted brain is shown to push nowhere (a two-repo test through `make_realm_local`), or the code is shown to refuse the push already
