---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue





## Shipped agents stay one agent — 2026-11-19 (owner; task row in Eternia `mission-control-queue`)
- **`RT-A-PERSONA-CHAT-CAN-BE-ARCHIVED-FROM-ETERNIA` — A person archives one saved agent chat from Eternia's Chat list, and it leaves the list but stays recoverable** · group: bundled-agents-stay-one-agent · from: Eternia `MC-ACTIVE-AGENTS-LOOK-LIKE-CHATS-AND-THEIR-CHATS-LEAVE-THE-HISTORY` · owner 2026-11-21 (RULED on that Eternia row): "chat history ones should have ... menu with the first option being archive chat" · read in code (w1121-activechats, origin/main c76d8f83bd91): no serve RPC archives one persona chat — `tests/agent_runtime/serve_rpc_manifest.expected.json` lists `runtime.persona.chat.delete` (deletes the transcript) and archive verbs only for realms, workspaces and board cards; `archive_sessions` (hides from listings, recoverable) is reached only by the `hermes sessions` CLI (`hermes_cli/sessions_cmd.py`), `unarchive_recoverable_session` only by the TUI and gateway · architecture: fork-owned serve RPC beside `runtime.persona.chat.delete` (guess: `runtime.persona.chat.archive` and `.unarchive`, one session id, owner-checked like delete, over `archive_sessions` / `unarchive_recoverable_session`); the operator conversation listing already reports `state: archived` (Eternia reads it in `eternia_hermes_adapter` `conversation_summary.dart`); Eternia adds no archive of its own · done when: one RPC archives a saved persona chat by id (refused while a turn runs on it), it no longer lists by default, and an unarchive brings it back, with its manifest entry and tier · review w1118a.74: passed with a rewrite; premise confirmed in code: the serve manifest (`tests/agent_runtime/serve_rpc_manifest.expected.json`) has `runtime.persona.chat.delete` (`serve_rpc/chat_verbs.py`) and archive verbs only for realms, workspaces and board cards · correction to the architecture: neither named store call fits — `archive_sessions` (`hermes_state_sessions.py`) is a bulk filter, and `unarchive_recoverable_session` deliberately leaves a person's own archive alone (it un-archives only accidental ends), so it could never bring an archived chat back; the one primitive is `set_session_archived(session_id, bool)`, which flips the whole compression lineage · architecture: `runtime.persona.chat.archive` and `.unarchive` beside `.delete` in `chat_verbs.py` (fork-owned, console tier, the same owner check as delete), over `set_session_archived` in the store that holds the operator transcript; refused while a turn runs on the chat, and refused for a chat that is an instance's loaded chat (`default_chat_session_id`), naming it — the owner's ruling puts Archive on Chat history rows only · security: a write verb at console tier with delete's ownership check; no new input beyond a session id · edge cases documented, not worked: a chat archived on one device while another has it open · file map: `serve_rpc/chat_verbs.py`, a `chat_verbs/archive.py` beside `delete.py`, the manifest expected file + tests · same-file sweep: `RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT` (same `chat_verbs.py` and manifest file), one lane · unblocks, with Eternia `MC-CHAT-LIST-READS-AN-INSTANCES-DEFAULT-CHAT-NOT-THE-ONE-OPEN-ON-IT`, Eternia `MC-ACTIVE-AGENTS-LOOK-LIKE-CHATS-AND-THEIR-CHATS-LEAVE-THE-HISTORY` · size S · reviewed 2026-11-21 w1118a.74 · READY 2026-11-21



## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)


- **`TASK-AGENT-CONFIG-CLEANUP` — Agent settings: each agent's folders, data, options and abilities live in one clear place** · task: agent-config-cleanup · 1 subtask open on 2026-11-19 (Eternia `MC-OWNER-NAMESPACES-ADOPT`; the other 9 are closed in the archives, the five hermes RT rows on 2026-11-15) · RULED 2026-11-19: owner said "same thing with this undefer it and see if its stale" (the same thing = "undefer it and have an aggent see and fix if need be") · checked 2026-11-19 (w1118a-hcfg): nothing stale was left to close — the five hermes subtasks (`RT-DELEGATION-KNOB-ENV-DEAD`, `RT-NAMESPACE-ADOPT`, `RT-ROOT-CONFIG-MISPLACEMENT-CURE`, `RT-MACHINE-ROOTS-FOLD-BREAKING`, `RT-READ-MODEL-RESIDUE-NEXT-BUMP`) were already archived CLOSED on owner words 2026-11-15; the one open subtask is real and is only the owner's own sitting on the Windows PC · BLOCKED 2026-11-19: launcher — `MC-OWNER-NAMESPACES-ADOPT` waits on the owner sitting at the Windows PC to pick the Agent data folder in Settings · was DEFERRED 2026-11-16: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` closed as churn (owner 2026-11-16 — "Close as churn"); the one subtask left, Eternia `MC-OWNER-NAMESPACES-ADOPT`, was DEFERRED by the owner (2026-11-09) · unblocked 2026-11-15: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` woken READY by w1115e-rr2 (deep sweep 2026-11-15 §D) · waits: `MC-OWNER-NAMESPACES-ADOPT`
- **`TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` — Agent engine follow-ups: the engine's own checks pass on main again after a lane broke them** · task: engine-suite-green-followups · review w1118a.40 closed bundled-realm's `FH-REALM-TESTS-HANG-ON-A-LOCAL-GIT-REMOTE` (D10: reds on main are not rows) · 3 open subtasks on 2026-11-15 (1 ready: FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY; 2 NEEDS PLAN filed by w1115c-h2 and waiting on a review batch: RT-RUNNING-TURN-START-ROW-WAITS-OUT-THE-DEMOTE-HOLD, RT-RUNNING-TURN-START-NEVER-PUBLISHED-ONCE-UNDER-LOAD; FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD closed DONE 36a1e1d45c and FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD closed DONE c157f48749 by w1115c-h2; FH-GAME-WATCH-TEST-READS-THE-MACHINES-REAL-PROCESSES and FH-BUNDLE-SERVE-PROBE-REPORT-LOST-TO-STDERR-ON-LINUX closed by other w1115c lanes; FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN closed DONE e64d77c9f6 by w1114a-h5 through fork seams) · filed 2026-11-14 by the w1114a.30 queue pass (REVIEW_W1114A_B29), for reds met on hermes main — the twin of Eternia's architecture-gate-green-followups · was DONE 2026-11-15 0495762a2e (all 1 subtasks closed) · reopened 2026-11-15 (review batches w1114a.40 and w1114a.42, REVIEW_W1114A_B39/B41): FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD moved in from the DEFERRED TASK-UPSTREAM-LOAD-FLAKES and FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN from the DEFERRED TASK-HERMES-TEST-ISOLATION · handoff 2026-11-15 (w1114a-h4): FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN reproduced and its fixture fixes written, but they edit three upstream test files (upstream footprint 224->226), so it waits on an owner ruling (DECISION); claim released · BLOCKED 2026-11-20: another lane — `FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-RUNTIME-FOLLOWUPS` — Agent runtime: what the tasks behind this queue's rows found on the way gets fixed after them** · task: runtime-followups · after w1118a-sw73-mc 2026-11-21: filed `RT-FU-A-REALM-PULL-PREVIEW-COUNTS-THE-REALM-MANIFEST-AS-AN-ARTIFACT` (seen live on account B, QA Realm, awaits a review batch); one subtask more than the counts that follow; Eternia `MC-FU-A-REALM-UPDATE-BANNER-NAMES-WHAT-A-PULL-WOULD-CHANGE` closed DONE e4b8385af63 (Eternia main 469b2934c6a), so its mention below is history · after w1118a-sw69-doors 2026-11-21: closed DONE `RT-FU-THE-FORK-PLUGINS-REACH-HERMES-CORE-ONLY-THROUGH-ITS-PUBLIC-DOORS` 8c3eaadc90 (upstream's boundary lint and the import-layers gate green on main with neither baseline raised: the fork plugins import the runtime only through published doors `agent_runtime/plugin_doors/`, serve_lane builds Telegram through `platform_registry`, the usage-fetcher set lives in the fork; plan docs/agent-runtime-harness/planned/fork-plugins-public-doors-2026-11-21.md; the merged `RT-FU-THE-USAGE-READ-FAILED-REASON-READS-A-PRIVATE-UPSTREAM-TABLE` is delivered by it and is left for the coordinator's owner close); no new rows; one subtask fewer than the counts that follow · after w1118a-hrt7 2026-11-20: closed DONE `RT-FU-A-REPLY-HERMES-STOPPED-AT-ITS-CONTINUATION-LIMIT-IS-MARKED-CUT-OFF-ON-ITS-TURN` a7eefb9362 (D2: typed `cut_off: "continuation_limit"` on the terminal frame, the turn record and the agent reply row on reload; read live on the Eternia model fixture's `[[qa:cut_off …]]` through the real chat door; Eternia's half, Eternia `MC-FU-A-REPLY-CUT-OFF-AFTER-ITS-CONTINUATIONS-SAYS-NOTHING-OF-IT`, re-vendors `tests/fixtures/reply_cut_off_v1.json`) and `RT-FU-A-QA-COPYS-QWEN-AND-COPILOT-SIGN-INS-COME-FROM-THIS-COMPUTERS-OWN-CLI-LOGINS` ed528b98c9 (D3: one per-provider `BORROWED_LOGINS` table; the Qwen seam sits on the CLI file's one reader, not the seed, RULED on the commit: the seed-only seam left the runtime rung reading and refreshing the owner's `~/.qwen`), both landed a7eefb9362; filed `RT-FU-A-QA-COPY-WITH-THE-COPILOT-PLUGIN-STILL-OFFERS-COPILOT-ACP-MODELS-ON-ITS-CLI-LOGIN` (read in code, awaits a review batch); two subtasks fewer and one more than the counts that follow · after w1118a-hrt5 2026-11-20: closed DONE `RT-FU-AN-AGENTS-TERMINAL-REALM-SYNC-REVERT-ARCHIVES-AGENTS-WITH-NO-COORDINATOR-REVIEW` 0e81629994 (D8: one removal review in `chat_coordinator`, called by office actor-remove and realm sync revert), `RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD` 4a44b2a9c7 (D9: every agent_chat door forwards `lane._instance_handle`'s one value) and `RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL` 29a5e20e09 (D10: one shipped-copy predicate for drift, publish and pull), all landed 90e53f546a and read live on Linux, account C lane namespace (own HRT5 Realm with a file:// team remote); no new rows; three subtasks fewer than the counts that follow · after w1118a-hstream 2026-11-20: closed DONE `RT-FU-ADDING-AN-AGENT-SENDS-EVERY-OPEN-ETERNIA-A-FULL-REFRESH` 3241576394 (landed b2d5996941; D2: `persona.updated` rides beside a new `persona` patch and is covered only for a client declaring `persona`; the stream golden generator runs clean and the goldens are regenerated, carrying hrt3's owed `events[]`; read live on Linux, account C: a declaring subscriber read two patch frames per add and no core; Eternia's own copy still takes one core per add until its `persona` fold and the goldens' re-vendor land, handed to the coordinator for an Eternia lane); one subtask fewer than the counts that follow · after w1118a-hrt4 2026-11-20: closed DONE `RT-FU-A-HERMES-UPDATE-MAKES-EVERY-REALM-ASK-TO-PUBLISH-ITS-BUILT-IN-SKILL` 1d0b69ad73 (landed 572ed14b60; review w1118a.63 D5 (a): a built-in skill equal to this install's shipped copy is never drift and never published, read live on Linux, account C's own realm with a file:// team remote); handed `RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS` to the Windows box (REQUIRES windows: its check passes on Linux and is pinned, 895c398cce; the Windows read is on Eternia QA-WINDOWS-CHECKS-OWED-4); filed `RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL` (seen live; since closed DONE 29a5e20e09 by w1118a-hrt5); one subtask fewer and one more than the counts that follow · after w1118a-hsec2 2026-11-20: closed DONE `RT-FU-AN-AGENTS-TERMINAL-OFFICE-REMOVE-SKIPS-THE-COORDINATOR-REVIEW` 01b3649916 (landed 9d796bbb98; an agent's terminal office actor-remove, --local-only included, goes through the one coordinator review; read live on Linux, account C), filed `RT-FU-AN-AGENTS-TERMINAL-REALM-SYNC-REVERT-ARCHIVES-AGENTS-WITH-NO-COORDINATOR-REVIEW` and `RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD` (read in code; both since closed DONE by w1118a-hrt5); one subtask fewer and two more than the counts that follow · after w1118a-hrt3 2026-11-20: closed DONE `RT-ANOTHER-REMOVAL-REACHES-ETERNIA-ONLY-WHEN-ITS-BATCH-FALLS-BACK` 63d2ed994c (D2 (a): a patch frame carries its batch's covered domain events as `events[]`, read live on Linux, account C — an agent's terminal removal rode a patch frame and Eternia's banner said who removed it; Eternia `MC-THE-ACTIVITY-LOG-SAYS-WHO-REMOVED-AN-AGENT` waited on it, since closed DONE 546219f4990) and `RT-FU-THE-DOCTOR-STILL-CALLS-AN-UNSEATED-AGENT-A-DESIGNED-ROSTER-ONLY-ROW` ba0cb6b927 (the doctor names `persona seat-unseated`, and `office actor-restore` for a deleted desk), landed 70ef963fbf; two subtasks fewer than the counts that follow · after w1118a-hsec 2026-11-20: closed DONE `RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET` 7d350bdaa9 (landed 8df9a730d4; review w1118a.62 D1 (a): every CLI coordinator door reads the asker from the terminal's session and the scope only from the store, the five argv scope flags deleted; read live on Linux, account C), filed `RT-FU-AN-AGENTS-TERMINAL-OFFICE-REMOVE-SKIPS-THE-COORDINATOR-REVIEW` (read in code; waits for a review batch); one subtask fewer and one more than the counts that follow · after w1118a-hrt2 2026-11-20: closed DONE d93b842da9 (landed f350c45d7a) Eternia's idle-instance read (`runtime.agent.idle_instances`, a shim over `staff.idle_instances`; review w1118a.53 D8 — Eternia `MC-A-NEW-CHAT-PICKS-THE-IDLE-INSTANCE-THE-RUNTIME-NAMES` was then unblocked, since closed DONE 87a0785a195), an agent's terminal removal recorded as that agent (D7 (a): the terminal carries `HERMES_SESSION_ID`; `request_actor` reads the session first, `--requested-by` never overrides it) and the shipped lead's add-instance refusal naming autonomy and `agent_runtime.coordinator_permissions.max_spawns` (RULED (b); also fixed a double-counted spawn budget), all read live on Linux, account C; filed `RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET` (seen live); three subtasks fewer and one more than the counts that follow · after w1118a-hrun 2026-11-20: closed DONE `RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE` f2f183a6db (review w1118a.58 D2: ended chat turns, requests, delegations and background terminals stay listed 30 min with outcome and finished_at, never a Stop; one policy, `running_work/ended.py`), `RT-FU-AN-AGENT-REQUESTS-OWN-TURN-NAMES-ITS-REQUEST` f2f183a6db (D3: the turn a request starts carries `parent_work_id`), `RT-FU-A-STOPPED-REQUESTS-RESULT-NAMES-NO-AGENT` def8927d28 (D5: the delivery marker names the target with no thread) and `RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF` 1d5de4ce1a (D9: the fork boot sweep closes the cut-off turn's transcript, unanswered tool calls included; upstream's repair untouched), all read live in Eternia on Linux, account C, with the Eternia half 59305679505 and 974c22f392a; filed `RT-FU-A-STOPPED-REQUESTS-TURN-STAYS-RUNNING-AFTER-STOP` (seen) and `RT-FU-AN-AGENTS-FIRST-CHAT-IS-WRITTEN-TO-THE-SHARED-STORE-NOT-ITS-OWN` (seen on disk; Eternia D6 moved here), both reviewed w1118a.59; four subtasks fewer and two more than the counts that follow · after w1118a-hwin 2026-11-20: closed DONE `RT-FU-WINDOWS-REQUEST-CHILD-ENDS-WITH-ITS-SERVES-OWN-JOB` fee580c6ca (review w1118a.57 D10: a Windows request child breaks away from the serve's job through one helper, `_subprocess_compat.popen_breaking_away`; pinned on Linux, the Windows read is on Eternia `QA-WINDOWS-CHECKS-OWED-4`) and `RT-FU-ADD-INSTANCE-CLI-REFUSALS-CONTRADICT-EACH-OTHER` 89d8b736a5 (D13: both --add-instance doors mint a missing placement id; read live), closed REFUTED `RT-FU-A-MESSAGE-QUEUED-BEHIND-A-BUSY-CHAT-RUNS-AFTER-A-SERVE-RESTART` fee580c6ca (D11: reproduced live, the queued send ran on the next serve); filed `RT-FU-DASHBOARD-GATEWAY-BUTTONS-SPAWN-THROUGH-THE-ONE-WINDOWS-BREAKAWAY-RULE` (read in code) and `RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF` (seen), both waiting for a review batch; three subtasks fewer and two more than the counts that follow · after w1118a-hfu3 (2) 2026-11-20: closed DONE `RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE` 7fc184a5f2 (review w1118a.53 D10: one check, `persona_lifecycle.is_agent_copy`, serves the template skip and the copy delete; read live in Eternia on Linux, account C: Presets 2 with a duplicate made, which Delete agent then removed); one subtask fewer than the counts that follow · after w1118a-hfu3 2026-11-19: closed DONE `RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE` 5fa36a548f (an independent copy's own profile is no profile template, judged by the persona record; read live in Eternia on Linux, account C: Presets 2 before and 2 with a copy made, Roster and Local 3; wakes Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`, closed DONE with it) and `RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING` 4260057ce0 (a drained serve joins its settle pusher, delivery drain and queued-send dispatcher, the upstream adapter shim shuts its loop's default executor down, a conftest stops the build sweep; `tests/agent_runtime/messaging/` sealed); filed `RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE` (read in code; waits for a review batch); one subtask fewer than the counts that follow · after w1118a-hgroup 2026-11-19: closed DONE `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` 168017b784 (a group chat of agents that each have their own profile answers every member's turn; read live through a real `harness serve` and in Eternia on Linux) and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (read live in Eternia's tool console: row, summary and fix); two subtasks fewer than the counts that follow · review w1118a.51 2026-11-19: passed `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` (D12, fork fixture) and `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` (D14, not an edge: the owner's board path), both READY; closed `RT-TWO-PLACEMENTS-AT-ONCE-CAN-GIVE-ONE-AGENT-THE-SAME-NUMBER` (D10) and `RT-AN-AGENTS-DONE-UNDER-A-PARKED-TASK-CLOSES-WHERE-A-LANES-CLOSE-IS-REFUSED` (D13) as edge cases and `RT-OWNERS-OLD-NEKO-MEMORY-STAYS-IN-THE-TEAM-REPO` (D11) on the ruling; three subtasks fewer than the counts that follow · after w1118a-hwork 2026-11-19: closed DONE `RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE` 92d350be97 (a close from Eternia's board, an agent's done and the engine's done now wake the rows waiting on the row and step its task, as a lane's close does; read live on Linux through a real `harness serve` on a sandbox brain: the owner's close woke the waiting subtask and turned the task READY, the agent's done of the last subtask archived the task) and filed `RT-AN-AGENTS-DONE-UNDER-A-PARKED-TASK-CLOSES-WHERE-A-LANES-CLOSE-IS-REFUSED` and `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` (read in code; edges; wait for a review batch); one subtask more than the counts that follow · after w1118a-hfu2 2026-11-19: closed DONE `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` fcdb0a5818 (a close from Eternia's board in a launcher- or backend-brain slot reads hermes's brain beside the checkout and archives the task when its last subtask closes; read live on Linux through a real `harness serve` on a sandbox launcher-brain slot: the owner's close of the last subtask archived the task, and with hermes's brain absent it stayed open) and `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` c0718e44de (a messaging-folder fixture writes runtime status with no thread); filed `RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING` (seen; waits for a review batch); one subtask fewer than the counts that follow · after w1118a-hfu 2026-11-19: closed DONE `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` f16d71a002 (a duplicate of an agent on the main profile keeps the head home's model and none of its files; read live on Linux through a real `harness serve`: the copy's one real turn reached the source's endpoint) and `RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER` 3c21e4805c (the suite runs the Telegram live check against the stand-in); filed `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` (seen; waits for a review batch); one subtask fewer than the counts that follow · review w1118a.50 filed and passed `RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE` from Eternia's sync-pull rename row (since closed DONE 7d5ba827252) (READY, D7: the workspace and realm records' pull merges against a baseline); one subtask more than the counts that follow · review w1118a.48 passed hknobs' `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (READY; D5: the second is a read the first's lane makes), hendpoint's `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` (READY, D6; since closed DONE f16d71a002) and htele's `RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER` (READY, D8; since closed DONE 3c21e4805c), filed and passed `RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE` from Eternia `MC-SUBTASK-HOLD-TO-ARCHIVE` (READY, D1b; Eternia's row since closed DONE 8810835e31f), and closed hdelete's `RT-A-COPY-DUPLICATED-BEFORE-THE-DELETE-DOOR-KEEPS-ITS-PROFILE` as an edge case (D7, on Eternia's sweep list); net unchanged against the counts that follow · after w1118a-hdelete 2026-11-19: closed DONE `RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED` a2555090c4 (`runtime.agent.delete` deletes a copy you made in one step; read live on Linux through a real `harness serve`: after a retire the directory already drops the instance but the roster keeps the copy, after the delete neither lists it; wakes Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST`) and filed `RT-A-COPY-DUPLICATED-BEFORE-THE-DELETE-DOOR-KEEPS-ITS-PROFILE` (read in code; an edge; waits for a review batch); net subtask count unchanged · after w1118a-hendpoint 2026-11-19: closed DONE `RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT` 57facbaba6 (a copy and a duplicate keep the source's model endpoint and no credential; read live on Linux: a fresh copy of Base answered its first message; wakes Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE`) and filed `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` (seen in a unit test; since closed DONE f16d71a002); no net change in subtask count · review w1118a.47 filed and passed `RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED` from Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST` (READY, D5: one door deletes an independent copy; Eternia's row waits on it); one subtask more than the counts that follow · review w1118a.46 passed hphantom's `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` (READY, D3: one list of root-only keys, one typed issue per profile copy) and bundled-facts' `RT-GROUP-CHAT-NEVER-FINISHES-ENDING-AFTER-ITS-PROCESS-STOPPED-MID-TURN` (READY, D9: premise first through a real serve restart), and filed and passed `RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT` from Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE` (READY, D2: a copy carries its source's model endpoint, never a credential); one subtask more than the counts that follow · after w1118a-hknobs 2026-11-19: closed DONE `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` 16f69d75f9 (a profile-config copy of a root-only setting is one typed issue on the agent's declaration naming the root; read live on Linux through a real `harness serve`) and REFUTED `RT-GROUP-CHAT-NEVER-FINISHES-ENDING-AFTER-ITS-PROCESS-STOPPED-MID-TURN` (a real serve restart, SIGTERM or SIGKILL, ends the room); filed `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` (seen) and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (live check), both waiting for a review batch; net subtask count unchanged · after w1118a-hphantom 2026-11-19: closed DONE `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` 6a913f1568 (a config entry declares an agent only with an identity key; a settings-only entry lists nothing, its knob still read by id; read live on Linux through a real `harness serve`) and filed `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` (read in code; waits for a review batch); net subtask count unchanged · after w1118a-hbase 2026-11-19: closed DONE `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` d28f26e14d (a placed shipped agent folds the unedited discovered persona on its profile; read live on Linux: one Base Agent plus Neko in Agents and `runtime.agent.directory`, and Base copies; wakes Eternia `MC-AGENTS-LISTS-A-PROFILE-ROW-INSTEAD-OF-THE-SHIPPED-AGENTS`) and filed `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` (seen on disk; waits for a review batch); net one subtask fewer and one more than the counts that follow · after w1118a-hscope 2026-11-19: closed DONE `RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT` 6d13964e96 (the instance verb takes `client_scope` / `--client-scope`, stamps it on all three mints and echoes it; read live on Linux through a real `harness serve`; wakes Eternia `MC-INDEPENDENT-COPY-CHAT-NOT-LINKED-TO-YOUR-ACCOUNT`, since closed DONE in Eternia 52e563fd665, w1118a-mcscope); one subtask fewer than the counts that follow · review w1118a.44 passed mccopy's `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` (READY, D4: not an edge case — a realm pull places the shipped Base beside a discovered one; the fold goes in `place_shipped`) and filed and passed `RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT` (READY, D3, security: the instance verb takes the account scope); mccopy's row was in no count, so two subtasks more than the counts that follow · after w1118a-hrealm7 2026-11-19: closed DONE `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED` 61a0d8c186 and design-fix `RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE` e357b28aba (both read live on Linux in QA Realm; the second wakes Eternia `MC-PHONE-REALM-REVERT-SAYS-RESTORED-BUT-THE-CHANGE-STAYS`, since closed DONE d07b7bca00, relayed by review w1118a.44); filed `RT-REALM-DESK-FILE-REMOVED-BY-HAND-LEAVES-A-PUBLISH-THAT-DROPS-THE-AGENT` (seen in a test; not seen live — the by-hand pull read nothing to publish), since closed by the owner; net two subtasks fewer than the counts that follow · after w1118a-hname 2026-11-19: closed DONE `RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER` 1738e2ecae (a nameless create is refused `agent_name_required`, a taken name `agent_name_taken`; read live on Linux; wakes Eternia `MC-NEW-AGENT-WITHOUT-A-NAME-IS-ASKED-FOR-ONE`, since closed DONE 159a1f050a, relayed by review w1118a.43); one subtask fewer than the counts that follow · review w1118a.41 moved `RT-PAIRED-PHONE-CAN-STEER-A-CHAT-IT-MAY-NOT-SEND-TO` to Eternia as `MC-CONSOLE-SLASH-STEER-GOES-WITHOUT-THE-ACCOUNT-SCOPE` (D7: hermes already checks both verbs; Eternia's slash steer sends no scope), closed hrealm7's `RT-REALM-DESK-FILE-REMOVED-BY-HAND-LEAVES-A-PUBLISH-THAT-DROPS-THE-AGENT` as an edge case (D9: only a hand-edited realm) and passed bundled-place's `RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER` (READY, D8: a nameless create is refused, as the design's section 4 rules); two subtasks fewer than the counts that follow · review w1118a.40 filed and passed the design-fix row `RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE` (READY, D11: every operation that adopts the team's copy settles the baseline the drift walk reads, in its own scope) and folded into it qafu18's `RT-REALM-PULL-OF-A-NET-ZERO-DESK-DELETE-LEAVES-OFFICE-LAYOUT-CHANGED` and hrealm6's `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-DRAWING` (both closed), and passed hrealm6's `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED` (READY, D17: a pull that ends a hold clears its sidecar); one subtask fewer than the counts that follow (the design row in, the two folded rows out) · after w1118a-hrealm6 2026-11-19: closed DONE `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` cae912bae4 and `RT-OFFICE-HELD-DESK-SAYS-WHAT-THE-TEAMMATE-DID` 4468dd0c4d (both read live on Linux in QA Realm; the second woke Eternia `MC-OFFICE-DESK-CONFLICT-DIALOG-SAYS-MOVED-WHEN-THE-TEAMMATE-DELETED`, since closed DONE f0918262c7, relayed by review w1118a.42); filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-DRAWING` and `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED`, both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.39 filed and passed `RT-OFFICE-HELD-DESK-SAYS-WHAT-THE-TEAMMATE-DID` (READY, D8: the office snapshot names each held desk's team side, for Eternia's conflict dialog) and regrouped bundled-runtime's `RT-SHIPPED-AGENT-SEAT-EDIT-COUNTS-AS-A-CHANGE` into `bundled-agents-stay-one-agent` (D9, a defect in that task's own work; never counted here); one subtask more than the counts that follow · review w1118a.38 passed with corrections `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` (READY, D5: taking the team's copy settles the realm's office baseline through the office pull's own settling) and closed `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` as an edge case (D6, on Eternia's sweep list); net one subtask fewer than the counts that follow · after w1118a-hrealm5 2026-11-19: closed DONE dee4e42839 `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (both read live), and design-fix `TASK-REALM-DELETE-MEETS-AN-EDIT` closed with both its subtasks; filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` and `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` (an edge), both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.36 passed with corrections hbundle's `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` (READY: one owner of the push-refused tells, `cannot lock ref` added; a repeat of archived `RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE`) and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (READY: publish writes only what the content compare says changed), and moved `RT-PHONE-REALM-CONFLICT-HAS-NO-WAY-OUT` and `RT-REALM-LOCAL-EDIT-OUTLIVES-A-TEAMMATES-DELETE` out to design-fix task `TASK-REALM-DELETE-MEETS-AN-EDIT` (one gap: no rule for a delete meeting an edit); net two subtasks more and two fewer than the counts that follow · review w1118a.31 corrected the hsurf segment below: the Eternia Home row it woke is closed, not open (DONE a8c7bead20), and so is `TASK-HOME-SHELL-FOLLOWUPS-3` (099dc3c1bd) · review w1118a.30 closed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` as an edge case (D6) and filed and closed `RT-SURFACE-NOTE-RESENT-EVERY-TURN-IN-MOA-AND-CODEX-MODES` as an edge case (D7), both on Eternia's sweep list (one root: what the model was last told is read from the transcript); net one subtask fewer than the counts that follow · after w1118a-hsurf 2026-11-19: closed DONE `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` 7787bd8a8f (a changed surface prompt rides the turn's tail; the stored prompt stays byte-identical), which wakes Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` for its live read (since closed DONE in Eternia a8c7bead20, w1118a-home4; Eternia `TASK-HOME-SHELL-FOLLOWUPS-3` closed DONE 099dc3c1bd); filed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` (an edge, waits for a review batch) · was: review w1118a.29 filed and passed `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` (ready; one subtask more than the counts that follow) · after w1118a-folderedit 2026-11-19: closed DONE `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED` fff568201e, read live in Eternia before and after on fresh lane namespaces (the folder is saved, no sync banner) · was: review w1118a.23 moved w1118a-hrealm's two realm rows (the persona-api-mode one, since closed DONE 68a504deb7, and `RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK`) out to `TASK-REALM-MEMBERS-SEE-WHAT-THE-OWNER-SHARES`; the counts that follow never held them · 5 subtasks open on 2026-11-19 after w1118a-hprov (closed DONE: the catalog's sign-in field 2e5f209c5d, which woke Eternia `MC-FU-COMPOSER-SILENT-WHEN-THE-CHATS-PROVIDER-IS-SIGNED-OUT` (since closed DONE in Eternia 9f1bb6eccd, w1118a-mcfu8); the phone readiness row cc78fac067, read first on a phone bundle; closed as churn on review w1118a.21 D6: the fresh Default office row, read on a desktop serve — the one effect found filed as `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED`, passed by review w1118a.22, since closed DONE; the other four wait on the owner) · was: review w1118a.21 filed and passed the sign-in-field and phone-readiness rows and rewrote the fresh-office row (w1118a-hphone2) · 6 subtasks open on 2026-11-19 after w1118a-hphone2 (filed `RT-FRESH-ENGINE-DEFAULT-WORKSPACE-HAS-NO-OFFICE`, waits for a review batch; the phone row the duplicate below merged onto, `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER`, closed DONE 82d80229be in `TASK-PHONE-HARNESS`) · was 5 subtasks open on 2026-11-19 after w1118a-rtfu2 (closed DONE: `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` efc2140d79, `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` 69aab89b99, `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` 4d43a3036c read live on a real model; filed `RT-PHONE-CHAT-TURN-HAS-NO-HARNESS-PARSER`, which review w1118a.19 closed as a duplicate of `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER` (merged onto that row); the other four wait on the owner: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` blocked, three deferred) · was 8 subtasks open on 2026-11-19 after w1118a-realm2 (`RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` closed DONE afb168e807, read live on two Eternia QA copies; `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` also read right in Eternia's realm sheet: two new namespaces' first pulls read In sync with nothing to publish) · was review w1118a.16 (Eternia review batch): passed `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` (both ready), closed `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` (a red on main is not a row — owner 2026-11-15) · 9 subtasks open on 2026-11-19 after w1118a-rtfu (closed DONE: `RT-READ-ONLY-TREE-REMOVAL-COPIED-THREE-TIMES` 2967e07ab1, `RT-PHONE-BUILD-STALE-SEED-BLAMES-AN-EXTRA` d197d1c389, `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` 34e21dbfe8; filed `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER`, waits for a review batch; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` waits on a real-model sitting and `RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` on an Eternia QA read, each with a handoff; `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` filed by w1118a-hphone wait for review) · was 9 subtasks open on 2026-11-19 after w1118a-hbundle3 (`RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` closed DONE d5012e054b: 18.86 -> 15.66 MiB arm64, the limit re-based by ruling, Eternia's edit) · was 11 subtasks open on 2026-11-19 after w1118a-hbundle (`RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED` closed DONE 75c5913569; `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` stays READY with a handoff — 28.80 -> 23.30 MiB landed 5febe61183, gap per part on the row; `RT-DESKTOP-BUNDLE-VERIFY-REFUSES-THE-DULWICH-REALM-SYNC` closed DONE 9962731e85 (w1118a-hbundle)) · was 11 subtasks open on 2026-11-19 after review w1118a.10 (6 ready, 1 live check, 1 blocked, 3 deferred; the review passed `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` and filed `RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED`, from Eternia `TASK-DISTRIBUTION-FOLLOWUPS`) · was 9 subtasks open on 2026-11-19 after review w1118a.8 (4 ready, 1 live check, 1 blocked, 3 deferred; `RT-PHONE-ANDROID-TLS-IGNORES-DEVICE-CERTIFICATES` closed as a documented edge case on the owner's standing call) · was, on 2026-11-17 after w1116b-rtfu: `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, `RT-CLOSE-NAMES-SIBLING-TASK-LINES-THAT-STILL-MENTION-THE-ROW` and `RT-REALM-OWNER-RECORD-LISTS-A-WORKSPACE-IT-DELETED` closed DONE; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` stays READY for its real-model live re-run only; `RT-SKILL-NAME-READ-TWO-WAYS` filed, waits for a review batch; was 5 subtasks open on 2026-11-16 after w1115e-q4 (2 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`; 1 blocked on an owner sitting; 2 deferred; closed since: `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM` DONE, `RT-LENS-RECIPE-HISTORY-AND-COUNTS-NOT-BUILT` as a documented edge, owner 2026-11-16 "sounds good" on review w1115e.19); was 7 subtasks open on 2026-11-16 after owner "Accept all" on B68 (4 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, and the two narrow realm-sync fixes `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM`; 1 blocked on an owner sitting: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH`; 2 deferred: `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR`, `RT-SCHEDULE-SYNC-AND-KNOB-2`; closed: `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS` and `RT-WORK-READS-MIX-ROWS-AND-HISTORY-FROM-TWO-COMMITS` as edges, `RT-READY-FRAME-SHELL-KEY-DOCUMENTED-NEVER-SENT` folded; each keeps its own status; its `from:` segment names the task it came from); was "7 subtasks open on 2026-11-15" · opened 2026-11-15 by w1115e-rr3 as this queue's one standing follow-ups task (owner 2026-11-15: "yea do the cleanup"; a follow-up goes here, not under a per-task `-FOLLOWUPS` task): received `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF-FOLLOWUPS` (2), `TASK-SHARED-WORK-V1-FOLLOWUPS` (1), `TASK-ONE-TURN-RECORD-FOLLOWUPS` (1), and the hermes rows of Eternia `TASK-PHONE-HARNESS-FOLLOWUPS` (1) and `TASK-CONSOLE-TOP-BAR-AND-MENU-PROPOSAL-FOLLOWUPS-2` (1) and backend `TASK-WORKSPACE-ABSORBS-PROJECTS-FOLLOWUPS-2` (1); `TASK-ETERNIA-LENS-FOLLOWUPS-2`'s 5 rows are Eternia's, now under Eternia `TASK-MISSION-CONTROL-FOLLOWUPS`; `TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` stays (its one row is a security row), each closed as merged · handoff 2026-11-20 (review w1118a.61): passed the idle-instance read for Eternia, the terminal-removal record (D7) and the shipped lead's budget refusal (all three closed DONE d93b842da9 by w1118a-hrt2); moved `RT-FU-A-PLACED-INSTALL-LISTS-A-SECOND-UNMARKED-BASE` to Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` (D8); one subtask fewer than the counts that follow · review w1118a.62: passed `RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET` (D1: all four CLI coordinator doors read the asker from the session and the scope from the store, the argv scope flags deleted), `RT-ANOTHER-REMOVAL-REACHES-ETERNIA-ONLY-WHEN-ITS-BATCH-FALLS-BACK` (D2: covered domain events ride the patch frame) and `RT-FU-THE-DOCTOR-STILL-CALLS-AN-UNSEATED-AGENT-A-DESIGNED-ROSTER-ONLY-ROW`; closed the create-method test row under the owner's reds rule and the probe agent's chat as an edge case; two subtasks fewer than the counts that follow · review w1118a.63: passed `RT-FU-AN-AGENTS-TERMINAL-OFFICE-REMOVE-SKIPS-THE-COORDINATOR-REVIEW` (security read, size S), `RT-FU-A-HERMES-UPDATE-MAKES-EVERY-REALM-ASK-TO-PUBLISH-ITS-BUILT-IN-SKILL` (D5: the build owns a built-in skill's text) and `RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS`; filed and passed `RT-FU-ADDING-AN-AGENT-SENDS-EVERY-OPEN-ETERNIA-A-FULL-REFRESH` (D2); one subtask more than the counts that follow · review w1118a.64: passed `RT-FU-AN-AGENTS-TERMINAL-REALM-SYNC-REVERT-ARCHIVES-AGENTS-WITH-NO-COORDINATOR-REVIEW` (security read, D8), `RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD` (D9) and `RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL` (D10), all READY and size S, no shared files, since closed DONE by w1118a-hrt5; the line now says Eternia `MC-THE-ACTIVITY-LOG-SAYS-WHO-REMOVED-AN-AGENT` is closed · review w1118a.65: passed `RT-FU-ADDING-AN-AGENT-CAN-STILL-SEND-A-FULL-REFRESH-FROM-A-SCOPE-RECONCILE` (D3, reproduce first), since closed DONE d6b1f62810 by w1118a-hrt6 (reproduced 2 of 4 adds; the new persona record waited for its event through a cold readiness walk; 12 of 12 adds clean after); the line now says Eternia `MC-A-NEW-CHAT-PICKS-THE-IDLE-INSTANCE-THE-RUNTIME-NAMES` is closed · review w1118a.66: passed `RT-FU-A-QA-COPYS-QWEN-AND-COPILOT-SIGN-INS-COME-FROM-THIS-COMPUTERS-OWN-CLI-LOGINS` (D3, READY: one per-provider fence), ruled the DECISION on `RT-FU-THE-SHIPPED-MISSION-LEAD-READS-NO-REPOS-RULES` (D4: the lead works on its seated instance; now BLOCKED on Eternia `MC-OUTSIDE-NEW-CHAT-OPENS-ON-AN-UNSEATED-INSTANCE`), and filed `RT-FU-A-REPLY-HERMES-STOPPED-AT-ITS-CONTINUATION-LIMIT-IS-MARKED-CUT-OFF-ON-ITS-TURN` (D2, READY: hermes marks a reply cut off at its continuation limit, for Eternia `MC-FU-A-REPLY-CUT-OFF-AFTER-ITS-CONTINUATIONS-SAYS-NOTHING-OF-IT`) · review w1118a.67: filed and passed `RT-FU-A-PROVIDERS-OWN-REFUSAL-CODE-INSIDE-ITS-ERROR-DETAILS-IS-DROPPED` (D1, READY: the provider's nested refusal code reaches Eternia, for Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO`) and `RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT` (D2, READY: an operator command in the serve is never judged as a chat's agent, for Eternia `MC-FU-A-SECOND-INDEPENDENT-COPY-IS-REFUSED-AS-AN-EXHAUSTED-SPAWN-BUDGET`); triaged out `RT-FU-A-QA-COPY-WITH-THE-COPILOT-PLUGIN-STILL-OFFERS-COPILOT-ACP-MODELS-ON-ITS-CLI-LOGIN` (D3, edge case, closed onto Eternia's edge-case list); two subtasks more and one fewer than the counts that follow · review w1118a.69: passed `RT-FU-A-SAVED-API-KEY-IS-NEVER-USED-WHILE-THE-CHOSEN-SIGN-IN-IS-EXHAUSTED` (D1: keep the chosen sign-in and say why, no silent key spend), `RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED`, `RT-FU-THE-FORK-PLUGINS-REACH-HERMES-CORE-ONLY-THROUGH-ITS-PUBLIC-DOORS` (now carrying the usage-table crossing) and `RT-FU-A-BARE-KEY-IN-A-STREAM-FRAME-OR-CHAT-LOG-LINE-IS-NOT-ASKED-OF-THE-ONE-SCRUBBER`; triaged out as edge cases, closed 2026-11-21 (w1118a-mop69): `RT-FU-A-HONOURED-ANTHROPIC-CREDENTIAL-SOURCE-SETTING-IS-LOGGED-AS-AN-IGNORED-KEY`, `RT-FU-A-DELETED-AGENT-COPY-LEAVES-THROUGH-THE-ONE-PROFILE-REMOVER`, `RT-FU-A-COPY-OF-AN-AGENT-ON-AN-OUTSIDE-MEMORY-SERVICE-KEEPS-THAT-MEMORY`; merged, closed 2026-11-21 (w1118a-mop69): `RT-FU-THE-USAGE-READ-FAILED-REASON-READS-A-PRIVATE-UPSTREAM-TABLE`, `RT-FU-THE-AGENT-PROFILE-SEED-BRIDGE-IS-RE-READ-AT-THE-NEXT-UPSTREAM-MERGE` · READY 2026-11-19 · unblocked 2026-11-19: `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` closed DONE 6a913f1568 · triage 2026-11-19 (w1118a-triH): owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — closed `RT-SKILL-NAME-READ-TWO-WAYS` as churn ("check for churn too"); `RT-SCHEDULE-SYNC-AND-KNOB-2` (owner: schedules stay local until a delete-propagation design) and `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` (waits on the deferred Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF` and a real Discord sitting) kept deferred · review w1118a.52: filed `RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE` (from Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`, READY) · handoff 2026-11-20 (w1118a-hreq): w1118a-hreq closed DONE RT-FU-A-DELETED-INSTANCES-OLD-CHAT-OPENS-ON-ANOTHER-INSTANCE 4fc62055ba (D13: a retired holder's agent read from its archive; read live in a sandbox, a retired instance's chat moved onto a second instance with its history), RT-AGENT-REQUEST-STILL-RUNNING-WHEN-ITS-SERVE-RESTARTS-IS-PICKED-UP-AGAIN and RT-WINDOWS-STOP-AFTER-ITS-SUPERVISOR-ENDED-REACHES-WHAT-A-REQUEST-LEFT 0ca1c535e9 (D12: result file, re-adoption, named kill-on-close job; read live on Linux, the Windows read is on Eternia QA-WINDOWS-CHECKS-OWED-4); filed RT-FU-WINDOWS-REQUEST-CHILD-ENDS-WITH-ITS-SERVES-OWN-JOB, RT-FU-A-RE-ADOPTED-REQUEST-HAS-NO-TIME-BUDGET-BACKSTOP, RT-FU-A-MESSAGE-QUEUED-BEHIND-A-BUSY-CHAT-RUNS-AFTER-A-SERVE-RESTART (review w1118a.57: closed RT-FU-A-RE-ADOPTED-REQUEST-HAS-NO-TIME-BUDGET-BACKSTOP as an edge case, D12; the other two and RT-FU-ADD-INSTANCE-CLI-REFUSALS-CONTRADICT-EACH-OTHER reviewed READY) · review w1118a.58 2026-11-20: filed and passed `RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE` (D2) and `RT-FU-AN-AGENT-REQUESTS-OWN-TURN-NAMES-ITS-REQUEST` (D3) from Eternia's Running now rows, which wait on them, and moved Eternia `MC-DELIVERED-RESULT-FOR-A-STOPPED-REQUEST-NAMES-NO-AGENT` here as `RT-FU-A-STOPPED-REQUESTS-RESULT-NAMES-NO-AGENT` (D5), all READY; passed hwin's `RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF` (D9, READY) and closed hwin's `RT-FU-DASHBOARD-GATEWAY-BUTTONS-SPAWN-THROUGH-THE-ONE-WINDOWS-BREAKAWAY-RULE` as churn (D10); two subtasks more than the counts above · handoff 2026-11-20 (w1118a-hagent): w1118a-hagent closed RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE and RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT (2ae02cbf29, landed b92baed712), filed the idle-instance read, the terminal-removal record and the shipped lead's budget refusal (closed DONE d93b842da9, w1118a-hrt2) · handoff 2026-11-20 (w1118a-hrtfu): closed DONE RT-FU-A-STOPPED-REQUESTS-TURN-STAYS-RUNNING-AFTER-STOP 9e2aeb4231 (the supervisor ends a killed child's turn: stopped for a Stop, interrupted past its budget), RT-FU-AN-AGENTS-FIRST-CHAT-IS-WRITTEN-TO-THE-SHARED-STORE-NOT-ITS-OWN 51e092bc1f (a never-bound instance's first turn writes where its first bind records) and RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE 8da915b449 (workspace and realm records merge field-wise against their baseline: kept, taken or held, resolve record::<family>:<id>), all read live on Linux, account C; freed Eternia's in-app read of a rename kept through a Sync (since closed DONE 7d5ba827252); three subtasks fewer than the counts that follow · handoff 2026-11-20 (w1118a-codex-win-rt): Provider detail codes landed at 9ef9e164fa. The existing provider-refusal row carries the Linux account C live read. The operator identity row still needs its fixture-serve reproduction. · handoff 2026-11-21 (w1118a-sw69-sec): after w1118a-sw69-sec 2026-11-21: closed DONE `RT-FU-A-BARE-KEY-IN-A-STREAM-FRAME-OR-CHAT-LOG-LINE-IS-NOT-ASKED-OF-THE-ONE-SCRUBBER` 46cf1e023f (landed 8f3bb90d0e: the live chat log, the chat history and board cards in the snapshot now ask the one scrubber for a bare key; the stream frame path was already masked; read live on Linux through the CLI); no new rows; one subtask fewer than the counts that follow · handoff 2026-11-21 (w1118a-sw69-keys): after w1118a-sw69-keys 2026-11-21: closed DONE RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED e29b85d1e6 (one key check at set_key and at lease; the run names api_key_control_character) and RT-FU-A-SAVED-API-KEY-IS-NEVER-USED-WHILE-THE-CHOSEN-SIGN-IN-IS-EXHAUSTED ec723f1aa7 (D1 (a): pick and run refuse chosen_credential_unusable, nothing spent from the other kind), both read live on account C's lane namespace with fake keys; Eternia's halves are MC-FU-AN-API-KEY-SAVED-WITH-A-HIDDEN-CHARACTER-FAILS-EVERY-TURN-AS-A-CONNECTION-ERROR (woken) and MC-FU-AN-APPROVED-MODEL-SWITCH-THE-RUNTIME-REFUSES-LEAVES-THE-CHAT-ON-THE-OLD-MODEL-SILENTLY; two subtasks fewer than the counts that follow · handoff 2026-11-21 (w1118a-helperlive): after w1118a-helperlive 2026-11-21: closed DONE `RT-FU-A-HELPER-GIVES-UP-ITS-ROW-AFTER-ONE-UNANSWERED-STEP` c5390d35622a (read live on a real model, Linux, account C, fresh lane namespace: a helper Base dispatched by Neko with a 'name it and stop' brief kept its TAKEN scratch row after its python3 -c read went unanswered for 5 min (block_class unanswered), read the files with read_file and uname -r instead, finished and named the blocked command; no code change) · handoff 2026-11-21 (w1118a-sw71-hm): closed DONE RT-FU-A-NEW-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-CANNOT-TAKE-ITS-FIRST-MESSAGE 1e49345594 (read live: a new chat with Neko on a fresh lane namespace took its first message, model chip qa-fixture) and RT-FU-A-DISCUSSION-ROOM-VIEW-WRITES-RECEIPTS-AND-TIMES-OUT-UNDER-LOAD d9f9737793 (landed 8bb0181168); filed RT-FU-A-GROUP-DISCUSSION-ROOM-VIEW-STILL-WRITES-ITS-TURNS-RECEIPTS (the group lane's view still writes; awaits review) · handoff 2026-11-21 (w1118a-sw71-el): filed RT-FU-A-REALM-STATUS-SAYS-WHAT-A-PULL-WOULD-CHANGE (half 2 of Eternia MC-FU-A-REALMS-UPDATE-BANNER-COUNTS-THE-WHOLE-REALM-AS-INCOMING, seen live) and RT-FU-A-TURN-SETTLE-CARRIES-THE-PROVIDERS-REFUSAL (read in code, from Eternia MC-FU-A-TURN-HERMES-REFUSED-BEFORE-SENDING-STILL-SAYS-RETRY-IN-THE-COMPOSER); both await a review batch; net two subtasks more than the counts that follow · handoff 2026-11-21 (w1118a-sw72-hm): w1118a-sw72-hm: closed DONE RT-FU-A-GROUP-DISCUSSION-ROOM-VIEW-STILL-WRITES-ITS-TURNS-RECEIPTS c622e55759 (record is the adapter contract; group room read live), RT-FU-A-REALM-STATUS-SAYS-WHAT-A-PULL-WOULD-CHANGE 41149a05a7 (incoming_artifact_counts; {} read live on QA Realm; Eternia banner half filed MC-FU-A-REALM-UPDATE-BANNER-NAMES-WHAT-A-PULL-WOULD-CHANGE) and RT-FU-A-TURN-SETTLE-CARRIES-THE-PROVIDERS-REFUSAL a9bd0ae04e (settle carries the redacted provider_refusal; Eternia half landed 5bdf8ea7421); three subtasks fewer than the counts that follow
- **`TASK-ONE-HERMES-ONE-PATH` — Every agent action runs once, inside the one running Hermes, never in a second one** · task: one-hermes-one-path · 9 subtasks · from: the 2026-11-21 Fable duplication audit (the second-Hermes / second-path flaw class) and `RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES` · RULED 2026-11-21: owner, asked whether to fold the audit's rows into one design-fix task per repo instead of the follow-ups tasks — "do those too when the reds finish" · RULED 2026-11-21 (owner, in the audit's picker; confirmed "the rest of the should of been ruled as said in the paste"): one turn engine for Mission Control and Intelligence chats inside the serve, not two engines with a separate program per profile; the fork scheduler (10-18) and Work board (ADR 0015) rulings stand · RULED 2026-11-21: owner on the snapshot build's separate process — "its just a build right thats fine it speeds it up if its on another thread" (stays a measured exception) · order: native dispatch and one turn engine first (one turn path), then stop, the model shown, sign-in, profile creation and the secret scrubber build on it · Eternia side: `TASK-MC-ONE-HERMES-ONE-PATH` (EterniaLauncher mission-control queue) · done when: every subtask is closed and each action named in them runs once in the serve process, read live · review w1118a.69: passed `RT-ONE-CREATE-VERB-MAKES-AN-AGENT-WITH-OR-WITHOUT-A-WORKSPACE` (size M; the `independent_agent` refusal lands after Eternia's door converts) and `RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES` (size L, family by family; the gateway pair is one narrow method, never a generic config write); triaged out as an edge case, closed 2026-11-21 (w1118a-mop69): `RT-FU-A-CRASH-WHILE-COPYING-AN-AGENT-LEAVES-A-PROFILE-ITS-RETRY-CAN-FINISH` · READY 2026-11-21 · handoff 2026-11-21 (w1118a-onepath-profile): profile creation done: RT-AN-AGENT-COPY-OR-NEW-AGENT-GETS-ITS-PROFILE-FROM-THE-ONE-PROFILE-CREATOR closed at ee38f8cf1b, read live on account C; follow-ups filed under runtime-followups: the copy delete through the one remover, the seed bridge re-read at the next upstream merge, a copy keeping an outside memory service · handoff 2026-11-21 (w1118a-onepath-hm): w1118a-onepath-hm: native dispatch (96569d9544, 6715be74ac, 78859b4022), the one model answer (09f51fbb5e), background jobs outliving a helper turn (f5a4c518ff) and sign-in inside the serve (780296419b) landed at 6550288611, read live on account C; closed RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES, RT-THE-MODEL-A-CHAT-SHOWS-IS-THE-MODEL-ITS-NEXT-REPLY-RUNS-ON, RT-PROVIDER-SIGN-IN-RUNS-INSIDE-THE-RUNNING-HERMES and the follow-ups RT-FU-A-LEAD-CANNOT-READ-ITS-HELPERS-MODEL-BEFORE-DISPATCHING, RT-FU-A-HELPERS-BACKGROUND-JOB-DIES-WHEN-ITS-TURN-ENDS, RT-FU-A-LEADS-READ-OF-A-HELPERS-REPLY-STILL-ASKS-FOR-A-READ-ONLY-CHECK; open: RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT and RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM (READY, each with a first-slice handoff), plus the rows other lanes hold · handoff 2026-11-21 (w1118a-onepath-typed): RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES CLOSED at 43c276fb94 (all five families typed and read live; method list in the archived row's handoffs); RT-ONE-CREATE-VERB-MAKES-AN-AGENT-WITH-OR-WITHOUT-A-WORKSPACE landed 5cbda47f86 and stays open only for the Eternia Agents-card read after MC-ONE-DOOR converts · handoff 2026-11-21 (w1118a-onepath-hm2): w1118a-onepath-hm2: fixed the red test_new_turn_not_held_by_another_agents_call (re-broken by ee38f8cf1b: create_profile gives every new agent an empty home/, so the HOME gate made agent B wait; 59bca87997). Closed RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM (c20b4ee535, 32db83d779; one stop handle per reply, one stop_turn for the chat Stop and runtime.work.cancel; read live on account C from both surfaces). Open: RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT (READY, released; slice 1 built on lane/w1118a-onepath-hm2-engine, not landed: four in-process differences named on its handoff), plus the rows other lanes hold · handoff 2026-11-21 (w1118a-onepath-hm2): w1118a-onepath-hm2: RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM closed; RT-ONE-TURN-ENGINE slice 1 landed 7030105df1 (no worker_entry child on desktop, read live on account C), the operator-chat fold (F0-F4 on the row) remains READY, claim released · handoff 2026-11-21 (w1118a-sw71-hm): closed DONE RT-AN-AGENT-WITH-NO-INSTANCE-YET-PUBLISHES-THE-MODEL-ITS-FIRST-CHAT-RUNS-ON 0504e5ee8c (landed 8bb0181168; persona rows publish effective_model/effective_provider; read live through the lane serve's snapshot); its Eternia half is MC-A-NEW-CHAT-WITH-AN-AGENT-THAT-HAS-NEVER-RUN-SHOWS-THE-MODEL-HERMES-PUBLISHES (Eternia d26756a206f); open subtasks now 2: the turn engine (TAKEN w1118a-onepath-fold) and the create verb · handoff 2026-11-21 (w1118a-sw72-hm): Eternia `MC-A-NEW-CHAT-WITH-AN-AGENT-THAT-HAS-NEVER-RUN-SHOWS-THE-MODEL-HERMES-PUBLISHES` closed DONE 164be3cdeef (landed bb40d9fecfa): the chip reads the persona row's effective_model; no-instance fallback removed

## Design-fix tasks — 2026-11-15 (review batch w1115e.9, B59; filed by lane w1115e-dfile)


## Design-fix tasks — 2026-11-15 (review batch w1115e.8, B58; filed by lane w1115e-dfile)


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

### Filed on arrival — 2026-11-18 (lane w1118-slotgitinit: Eternia's slot menu "Create repository…" on a folder with no git)


### Filed on arrival — 2026-11-16 (Eternia lane w1116b-prov: the hermes half of `MC-PROVIDER-SIGNIN-FIRST-TRY-FAILS`)


### Filed on arrival — 2026-11-17 (Eternia lane w1115e-pv: the live read of `RT-FAILED-TURN-ROW-DROPS-ITS-ERROR-SURFACE`)


### Filed on arrival — 2026-11-16 (Eternia lane w1115e-pv: the hermes halves of `MC-PROVIDER-USAGE-REPORT-LEAVES-OUT-A-CONNECTED-ACCOUNT` and `MC-PROVIDER-OUT-OF-USAGE-REPLY-SAYS-NOT-PROCESSED`)



### Filed on arrival — 2026-11-16 (plan lane w1115e-dw: the slices of `docs/agent-runtime-harness/planned/phone-realm-sync-dulwich-2026-11-16.md`)


### Filed on arrival — 2026-11-16 (lane w1115e-fh3: the build slices of the accepted slot setup recipe design)


### Filed on arrival — 2026-11-15 (review batch w1115e.10, REVIEW_W1115E_B60: the hermes half of Eternia `MC-LENS-OPEN-PANEL-MISSES-A-LATER-POLL`)

### Filed on arrival — 2026-11-15 (review batch w1115e.4, REVIEW_W1115E_B54 lane H2: the hermes halves of two Eternia surface rows)


### Filed on arrival — 2026-11-15 (lane w1115c-h2: tracing `FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD`)

### Filed on arrival — 2026-11-15 (review batch w1114a.43, REVIEW_W1114A_B42)


### Filed on arrival — 2026-11-15 (review batch w1114a.42, REVIEW_W1114A_B41: the gap w1114a-h2 noted after 3025cd1128)


### Filed on arrival — 2026-11-14 (lane w1114a-hplan: the live reads of `RT-RUNNING-CHAT-TURN-CARRIES-PLAN-PROGRESS` and `RT-TODO-STATE-KEEPS-STEP-PARENT`)


### Filed on arrival — 2026-11-14 (owner in chat, an Eternia session auditing Intelligence → Connected messaging)


### Filed on arrival — 2026-11-13 (lane w1113-slotclonehome: Eternia `MC-SLOT-JOIN-ONE-PROMPT-SETUP`, the Harness half)


### Filed on arrival — 2026-11-12 (lane w1112b-hm4: review batch w1112b-5 §2, §9, §10)


### Filed on arrival — 2026-11-12 (lane w1112b-hm3: review batch w1112b-4 §3, §6)


### Filed on arrival — 2026-11-12 (lane w1112b-hm2: review batch w1112b-3 §2, §4, §5)


### Filed on arrival — 2026-11-12 (lane w1112b-hm: Eternia `COMP-D2-EXIT-PROOF`'s menu pick, relayed by w1112b-engine)

### Filed on arrival — 2026-11-12 (lane w1112b-hmremote: review batch w1112b §2, Eternia `TASK-WORKSPACE-ABSORBS-PROJECTS`)

### Filed on arrival — 2026-11-12 (Eternia lane w1112b-models: `MC-REGENERATE-MODEL`)

### Filed on arrival — 2026-11-12 (lane w1112b-swfu-hm: Eternia `COMP-WORK-START-FROM-A-CHAT-FOR-ANYONE`, the Harness half)


### Filed on arrival — 2026-11-12 (lane w1112b-ctt-hm2: Eternia `MC-NATIVE-ACCEPT-REPAIRS` step 4)


### Filed on arrival — 2026-11-12 (lane w1112b-hm-turn5: what Eternia lane w1112b-turn6 read live of a steered Work turn)


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


### Independent agent creation — 2026-11-18


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


### Filed on arrival — 2026-10-27 (lane w1027j-h-tri-a, planned/ triage)

- **`RT-PEER-CANCEL-LIVE-STOP-PROOF` — D1.07's peer Stop has never been proven across two real installs (durable cancel_requested, partial output kept)** · group: remote-parity-and-two-machine-proof · moved 2026-11-10 (w1110a-org): from console-smooth-and-fast.design-sweep-d1 · fork / gateway · plan `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` D1.07 (built 5a2c887621) · `tools/agent_chat_dispatch/cancel_watch.py` · DEFERRED 2026-11-09: owner triage — Proof of a built feature; no reported failure; until the owner reopens it · waits: owner-ruling

### Filed on arrival — 2026-10-27 (lane w1027f-h-rt, w1027g-h-fix)


### Filed on arrival — 2026-10-27 (lane w1027b-h-fix)


### Lens plan reconciliation — 2026-10-26 (codex-lens-status)

Reconciled against the built code and the plan, not inferred from an absent old row. Optional branches retain their decision/deferral gates. Evidence and coverage: `docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md` § Current implementation and queue coverage.


### Filed by plan — 2026-11-14 (lane w1114a-lensrows: the owner-approved Lens act/investigate design)


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


### Filed on arrival — 2026-10-21 (lane w1021j-bundle, branch `w1021j/bundle`)

- **`RT-PHONE-TLS-TRUST-UNPROVEN` — Nobody has shown that the agent engine on a phone can verify the websites and providers it connects to** · group: phone-harness · fork / `agent/ssl_verify.py::install_truststore` · read in code, not reproduced: TLS trust is pointed at the OS store through the `truststore` library, which sends every OS that is not Windows or macOS to its OpenSSL arm (read in pip's vendored copy, not the locked version), and that arm looks for OpenSSL's default paths or a short list of Linux certificate files; `certifi` is in the phone closure but nothing selects it · guess: none of those files exists on a phone, so the trust store is empty and every HTTPS call is refused · guess: the fix is to point `SSL_CERT_FILE` at certifi's bundle under the phone profile · done when: an HTTPS request to a provider succeeds and one to a host with an untrusted certificate is refused, on an Android emulator and an iOS simulator, with the phone profile · was LIVE CHECK 2026-11-19: on the Android x86_64 emulator with the phone bundle, an HTTPS request to a provider succeeds and one to self-signed.badssl.com is refused (the iOS simulator half needs a Mac) · reviewed 2026-11-15 w1115p.1 · unblocked 2026-11-17: `RT-PHONE-EMULATOR-TARGETS` closed DONE c6da3eebc358 (the x86_64 bundle and a recipe to run it on the emulator are on `RT-PHONE-PILLOW-ANDROID`; the iOS simulator half needs a Mac) · was BLOCKED 2026-11-15 on `RT-PHONE-EMULATOR-TARGETS` · handoff 2026-11-19 (w1118a-hphone): built 5374a58860: `agent_runtime/phone_tls_trust.py::ensure_phone_tls_trust` exports certifi's bundle as SSL_CERT_FILE on sys.platform android/ios (unless the host set SSL_CERT_FILE/SSL_CERT_DIR), called in `EmbeddedServe.start`; read on Linux with a simulated phone (OpenSSL defaults and truststore's file sweep emptied): before, urllib to openrouter.ai refused SSLCertVerificationError; after, urllib and resolve_httpx_verify's httpx 200, self-signed.badssl.com refused by both. left: the emulator read (lane w1118a-phoneqa holds the emulator this wave) and the iOS simulator read (needs a Mac, REQUIRES macos for that half) · handoff 2026-11-19 (w1118a-phoneE): re-read on the Android x86_64 emulator 2026-11-19 (Eternia debug APK ad11dbe861 with the embedded engine, bundled-phone 73b1c13115, which holds 5374a58860): the trust half holds — the phone engine cloned https://github.com/ArcadiaLabsLLC/eternia-qa-realm.git (dulwich over urllib3) and fetched it again on Check now, both verified connections from inside the app (realm record, clone at 65900af713, checked_at moving); the refusal half (self-signed.badssl.com refused) was not read: no route from Eternia sends the phone engine to an arbitrary host, and the iOS half still needs a Mac; stays LIVE CHECK for the refusal read; evidence EterniaLauncher/docs/stages/qa-reboot/live/2026-11-19/RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR/w1118a-phoneE/README.md · review w1118a.34: re-read after w1118a-phoneE — the trust half is seen live (two verified HTTPS connections from the phone engine: the realm clone and its re-fetch); what is left on Android is the refusal half, and no Eternia route sends the phone engine to an arbitrary host (seen by phoneE); the iOS half still needs a Mac (REQUIRES macos for that half, unchanged) · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.34 D9: read the refusal through a product route, no new code: first a custom provider in Eternia's Settings (`custom_provider_dialog.dart`) whose base URL is `https://self-signed.badssl.com/v1`, whose model read on the phone runs in the in-app engine (Eternia 0b9b1ec676, phoneG: Connections reads a provider's models from the in-app engine — read in its commit title, not traced; the lane confirms the request leaves the engine, not Eternia's Dart client, before it counts) and must fail with a certificate error; if that read is served by Dart, the fallback is the realm route — a private staging test repository's realm whose remote points at `https://self-signed.badssl.com/` (staging test repos and staging realms are allowed to lanes, owner 2026-11-14), whose Check now must fail with a certificate verification error, not a 404; either way the read names the exception text the engine logged; rejected: a QA hook that makes the phone engine fetch any URL (a shipped fetch-anything surface in the engine for one read, and it would prove the hook's HTTP client, not the paths users take) · architecture: no code; a live read on the Android x86_64 emulator with the phone bundle that holds 5374a58860; evidence beside phoneE's under `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-19/` · same-file sweep (runtime queue): `RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR` and `RT-PHONE-BUNDLE-LEAVES-OUT-THE-HARNESS-SKILLS-A-REALM-PULL-INSTALLS` share the emulator sitting — lane w1118a-hbundle takes this read after its realm reads, in the same sitting · reviewed 2026-11-19 w1118a.34 · handoff 2026-11-19 (w1118a-hbundle): w1118a-hbundle checked both of review w1118a.34 D9's routes before the read and neither sends the phone engine to an arbitrary host (read in code, Eternia 13ecf8dd42, hermes f38b8c32f5, eternia-backend main): (1) Settings' custom provider (`lib/features/account/tabs/settings/custom_provider/custom_provider_dialog.dart`) is a MEDIA search provider (`CustomMediaProviderConfig`, a URL template; its Test runs `CustomProviderTestSearch` -> `MediaSearchPage` in Dart), not a model provider, so its request never leaves the engine; and phoneG's Connections model read (Eternia 0b9b1ec676, hermes 8b53197eb0 `runtime.provider.models`) answers models.dev catalog entries by id from `agent/models_dev.py::fetch_models_dev()`, never a provider's own base URL; no Eternia screen sets a model provider base_url on the phone; (2) a server realm's remote is the backend's `clone_url_for` (`eternia-backend/realms/github.py`: always `https://github.com/<repo>.git`), which hermes adopts as `sync_manifest_ref` (`agent_runtime/realm_sync/git.py::_take_server_credential_url`), so no staging realm can point at self-signed.badssl.com without new backend code. The trust half stands, re-read this sitting: the phone engine cloned, fetched, pushed (publish `eae3ffd`, `c14a734`) and pulled github.com over HTTPS many times (RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR). Left: a route for the refusal half needs a new ruling — e.g. a model-provider custom endpoint the phone engine itself calls, or a QA-only fixture; the rejected fetch-anything hook stays rejected; iOS half still needs a Mac · review w1118a.36: hbundle's reading of both D9 routes is confirmed — the Settings custom provider is a media-search provider tested in Dart, `runtime.provider.models` reads only models.dev, and a server realm's remote is always `https://github.com/<repo>.git` (backend `clone_url_for`); no product path sends the phone engine to a host Eternia names · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.36 D5: the Android half closes on the trust read already seen (the phone engine's verified clone, fetch, push and pull of github.com) plus a hermes test of the refusal: the refusal does not depend on the device — every client the engine uses verifies with CERT_REQUIRED against the anchors it is given, and which anchors a phone has (the device-dependent part) is what the trust read proved; so `tests/agent_runtime/test_phone_tls_trust.py`'s simulated-phone child (which already refuses an untrusted private CA through urllib and httpx, no network) adds the realm sync client, `git_dulwich._BrokeredHttpClient` (dulwich over urllib3, the client the trust read used): it completes the handshake with the trusted local server (any error is git's, not the certificate's) and is refused the untrusted one with a certificate verification error, through `_wire`'s typed refusal; killing mutation: the brokered client built with `http.sslVerify` false reds the refusal assertion; rejected: a QA hook that fetches any URL (still rejected — a shipped fetch-anything surface), a new model-provider base URL screen on the phone or a backend realm remote override just for this read (new product scope for one read), self-signed.badssl.com in a test (network in a unit test; a local server proves the same), and running the test on the emulator (the device adds nothing the trust read did not) · done when (Android half, replaces the emulator refusal read): that test passes and its red is recorded; then this row goes LIVE CHECK for the iOS simulator half only, with `REQUIRES macos` · architecture: test only, `tests/agent_runtime/test_phone_tls_trust.py`; no product code · same-file sweep (runtime queue): no other open row names that test or `phone_tls_trust.py` · reviewed 2026-11-19 w1118a.36 · LIVE CHECK 2026-11-19: on an iOS simulator with the phone profile and the phone bundle that holds 5374a58860, read that the phone engine reaches a provider (or clones the QA realm) over HTTPS with a verified certificate, and that a host with an untrusted certificate is refused; the Android half is closed (see the w1118a-htls handoff) · handoff 2026-11-19 (w1118a-htls): the Android half is closed (review w1118a.36 D5): the trust half was seen live on the Android x86_64 emulator (w1118a-phoneE and w1118a-hbundle: the phone engine cloned, fetched, pushed and pulled https://github.com/ArcadiaLabsLLC/eternia-qa-realm.git through dulwich over urllib3, verified); the refusal half is a test, 8ae3448ca6: tests/agent_runtime/test_phone_tls_trust.py's simulated-phone child (no OS store, certifi = a private CA) now also clones through DulwichSyncGit (git_dulwich._BrokeredHttpClient via _wire), reaches the trusted local server (fails on git's answer, not the certificate) and is refused the untrusted one with CERTIFICATE_VERIFY_FAILED, beside urllib and httpx; no network; killing mutation _BrokeredHttpClient built with http.sslVerify false reds 'the realm client trusted a CA nothing names' (1 failed, 8 passed), restored 9 passed; left: the iOS simulator half, which needs a Mac · REQUIRES macos

### Filed on arrival — 2026-10-21 (land w1021i)


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

- **`RT-POSIX-TURNS-SERIALIZE-BEHIND` — POSIX turns still serialize behind one process lock: the fork writes `HOME` per profile turn because upstream's in-process `expanduser`/`Path.home()` readers have no context hook** · group: windows-handoffs · upstream door (run-serialization decision 3) · `agent_runtime/profile_context.py::persona_profile_context` (the `HOME` write and its pinned-readers comment) · draft the one upstream door for a context-aware home hook (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files); once it lands, delete `_PROCESS_HOME_LOCK` on the h3-runser branch and POSIX gets per-root turns like Windows · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-09: owner triage — Mac/Linux perf; waits on upstream; until the owner reopens it · waits: owner-ruling · no fork-owned caller to memo (the readers are upstream) · handoff 2026-11-12: narrowed by `RT-NEW-TURN-WAITS-ON-ANOTHER-AGENTS-MODEL-CALL` (lane w1112b-hm-turn4) — `_PROCESS_HOME_LOCK` is gone; `agent_runtime/profile_runner/workdir.py::_ProcessHomeGate` lets runs that want the same `HOME` hold it together, so on a host (no profile has a `home/`, nothing is written) turns of different chat roots run side by side on POSIX too; what is left for the upstream door is only runs whose profiles carry DIFFERENT `home/` directories, which still take turns

### Filed on arrival — 2026-10-16 (build lane h1-lineage)


### Filed on arrival — 2026-10-16 (build lane h4-seeds)

### Filed on arrival — 2026-10-16 (release merge v0.22.2, daily branch at upstream acc3cada0da)




### Filed on arrival — 2026-10-15 (launcher lane w1015i-mc)


### Filed on arrival — 2026-10-15 (orchestrator: QA bundle build under load)


### Filed on arrival — 2026-10-15 (owner sitting: first real QA bundle build)


### Filed on arrival — 2026-10-15 (owner sitting: send-prep live proof)




- **`RT-CONNECTIONS-TRACE-MISSING` — Connections: trace the missing browser sign-in `done` event for the isolated QA profile.** Owner report/review 2026-10-14: ChatGPT or Codex Subscription web sign-in completed, but the login-stream `done` event did not reach the Launcher and the pane remained pending; the selected isolated profile subsequently had a credential entry and canonical `logged_in=true`. Root cause is unproven: no historical completion frame was captured. Start at producer `hermes_cli/provider_browser_login.py::run_browser_login` (`send` of `done`), trace `agent_runtime/provider_signin.py` and the consumer `EterniaLauncher/lib/shared/provider_connections/provider_connection_state.dart::ProviderSetupController` under the same profile; capture redacted lifecycle/transport evidence and pin reliable terminal delivery. The Launcher projection reconciliation on `fix/sol-connect-20261014` is a safety net, not the root-cause fix. Preserve the QA binding; never capture credentials or account identifiers. · group: provider-api-key-and-usage-source · fork / launcher seam · found 2026-10-14 sol-connect review · code read 2026-10-15: run_browser_login sends done only after _save_codex_tokens returns, ProviderSignIns._pump folds it only while the session is ACTIVE, and the registry lives in one serve process, so a serve restart between the credential write and the next poll answers login_not_found to a pane still pending · handoff 2026-11-21 review w1118a.70: merged in `RT-FU-A-PROVIDER-SIGN-IN-INSIDE-THE-SERVE-COMPLETES-ON-THE-FIRST-TRY` — since `RT-PROVIDER-SIGN-IN-RUNS-INSIDE-THE-RUNNING-HERMES` (DONE 780296419b) every sign-in runs on a thread of the serve, so the same sitting also reads: one Codex and one Anthropic sign-in from Connections complete on the first try and the account shows signed in without a restart, and the done event reaches Eternia (this row's own read) · BLOCKED 2026-11-12: owner sitting — one provider sitting: the owner signs in to their own provider accounts on Windows and does one ChatGPT sign-in so its completion can be recorded · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, as recommended" · was dEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: one live ChatGPT/Codex browser sign-in on the isolated QA profile (Windows box), capturing the poll replies and the serve pid

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

### Filed on arrival — 2026-10-08 (owner ask: capability vs. cost-trim quietness, Neko QA-build turn)

### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)

### Filed on arrival — 2026-10-08 (GenUI comparison turn audit, Amelia turn `agent-chat-send-db7a2d34-731b-4cc8-bc0b-d00b7394f753`)

- 2026-10-08 evidence for the GenUI selection row below: with the eager pair delivered (runtime `94043a1a42`, listing `26 core/visible tools kept, 18 deferred` at 13:23:09), the first-response path still did not call `launcher_generated_list` directly — the turn loaded five skills (`launcher-generated-ui`, `harness-dev-delivery`, `harness-continuity`, `harness-runtime-model`, one not found; ~44 KB of skill text), searched, described, queried the roster, took the wrong door, then relayed to a peer and burned the rest of the 240 s on the deadlock row above. The profile-local skill is a second copy of the tool contract (it says "discover with `launcher_generated_list`" without saying it is direct); F2 of the launcher audit stands.


### Filed on arrival — 2026-10-07 (GenUI selection audit)




- **`RT-VERIFY-IMPROVE-FIRST-RESPONSE` — Verify and improve first-response selection of the Launcher generated-content tools for ordinary comparison requests; the A/B eval is built (`evals/genui_first_response_ab.py`, b05ccafe29)** · group: windows-handoffs · fork / tool selection · plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §3 · RULED 2026-10-19: owner — arms switched by QA build · RULED 2026-10-25: owner — an agent runs this sitting on this PC · live phase 2026-10-25: a launcher_qa lane runs it — two QA builds (arm A before launcher 469e500730, arm B at it), 15 turns × 2 agents × each QA provider per arm; it does not touch the owner's serve (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · BLOCKED 2026-11-15: another lane — `RT-GENUI-AB-VERIFIES-THE-AGENT-AND-PROVIDER` verify actual routing and receipt attribution before each arm is approved and sends begin · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — the A/B test exists (`evals/genui_first_response_ab.py`); it costs provider turns · was dEFERRED 2026-11-09: owner triage — Evaluation of a nice-to-have behavior; until the owner reopens it · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — the live A/B (arm A, arm B) over launcher_qa; the owner keeps ONE QA build of HEAD (11-11), so arm A on a build before launcher 469e500730 needs a plan · moved 2026-11-12 (w1112b-ctt-hm): from console-transcript-truthful.p10-agent — owner rule 2026-11-12 ("any fine tuning stuff like that and performance should go into the windows task"): an A/B of which tool a model picks first is tuning, not a defect in the chat · handoff 2026-11-12 (w1112b-ctt-hm): not run on Linux — it costs real-model turns (15 turns × 2 agents × each QA provider × 2 arms) and this wave runs the fixture model only; arm A needs a QA build before Eternia 469e500730 (a throwaway local branch at that commit, built by `launch_or_attach` from a tree checked out there) · REQUIRES windows, linux · **TAKEN 2026-11-15 codex-win-hermes-handoffs on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes-handoffs**

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

- **`RT-WORK-LIST-OWNER-SIZE-PAST-HALF` — Work's Refresh at the owner's real workspace size stays well inside its ten-second limit** · group: windows-handoffs · `runtime.work.list` · seen live 2026-11-12 on Windows (Eternia lane w1112c-winperf2, Debug `94fcaeabc3`, Harness `0b8a6aa0d3`): with QA Fixture plus the hermes and backend checkouts bound (5 brains, 831 live rows) three clean Refreshes took 5.35 / 3.29 / 3.37 s at 13-35% load, and the list step is 3.1-4.8 s of each — the same as 2026-11-10 (5.32 / 3.58 / 3.43 s), so the fetch-only-when-moved fix did not move the owner-size number · guess, unverified: the boards are still synced one after another · done when: each board's sync is timed inside `runtime.work.list`, the cause is fixed, and a Refresh at this size reads under 5 s three times in a row · consumer: Eternia `COMP-WORK-REFRESH-OWNER-SIZE-PAST-HALF` waits on it and re-times on Windows · filed 2026-11-12 by the w1112c orchestrator · REQUIRES windows · READY 2026-11-12 · handoff 2026-11-12 (w1112b-hm-turnfu): re-grouped from shared-work-v1 to shared-work-v1-followups: TASK-SHARED-WORK-V1 was archived (Eternia c8c433dfb8) with this row still open, which left it under no task and turned hermes main's queue gate red (test_every_row_is_a_task_or_a_subtask…, seen in a test at 272b0ae714); the Eternia TASK-SHARED-WORK-V1-FOLLOWUPS count goes up by one · handoff 2026-11-12 (w1112b-swfu, at the orchestrator's word): moved from shared-work-v1-followups to windows-handoffs (Eternia `TASK-WINDOWS-HANDOFFS`) — a Windows-filed speed measurement at the owner's workspace size; owner 2026-11-12: performance goes to the Windows task and never holds a feature task · handoff 2026-11-15 (codex-win-hermes): Eternia removed the duplicate destination list and landed the client fix at `cd87462285`; app Debug `cd874622859b`, 956 live rows and five brains, Harness `3997c2cc4e` over `823c73fda5`. Each of four Windows Refresh presses sent one wire list: 2.853 / 11.874 / 2.367 / 4.728 s, app composite 2.891 / 11.908 / 2.414 / 4.771 s, full reconciliation 5.237 / 14.673 / 4.662 / 8.688 s. Stable tips, zero warm note-history misses and no fetch. At CPU 6/5/5, the 11.715 s sync started the four boards within 1.21 ms after 2.675 s of pre-worker work; `backend` and `launcher` overlapped, with `git status` taking 4.513 s and 2.764 s. The serial-board guess is superseded. The exact app and per-board receipts are in `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-15/COMP-WORK-REFRESH-ASKS-HARNESS-TWICE/README.md` at `64aa3a835b`. Next source question: can lifecycle list consume a tip-pinned, owned snapshot with equivalent tracked and untracked cleanliness while preserving the writer admission, recoverable index/lock handling, and the separate checked-out user-branch guard? Today Writer._reset normalizes the dedicated worktrees and filesystem queue globbing would otherwise see abandoned untracked notes. The three-consecutive performance bound remains open. · **TAKEN 2026-11-15 codex-win-hermes on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes-perf**

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

- **`RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN` — Telegram can run on upstream's connector as a second option, off by default, so the owner can try it with a real bot before anything is switched** · group: remote-parity-and-two-machine-proof.p10-messaging · fork / messaging · filed 2026-11-14 at the owner's ask in chat ("if so then just switch it", then "i need a proper audit") · seen in a test: on branch `audit/upstream-telegram-switch` (62920f2b68) the upstream Telegram adapter, connected over HTTP to a local stand-in for the Bot API with no GatewayRunner, did what the fork's own transport does — queued turn on the persona's one root, real reply, 4,096 split, `/persona`, forum topics, approval cards — once five defects were fixed in the shim: a stranger's media fetched before refusal, replies sent silently, upstream's command menu pushed to the bot, the bot token logged at INFO, message text logged at DEBUG; note `docs/agent-runtime-harness/evidence/upstream-adapter-as-transport-2026-11-14/SWITCH_AUDIT.md` · not shown: real Telegram, and two upstream Windows tests of stuck-poll recovery fail on this box (cause not investigated) · to build: a harness setting that picks the transport per token (never both: one poller per bot), the shim and its Telegram subclass from the branch, the token from `agent_runtime/messaging/credentials.py::bot_token`, the Allow list fed from the shim's refusals with the display name it lacks today, the press handler registered through upstream's plugin handler factory so a rebuilt application keeps it · done when: with the setting on, the owner's real bot answers on a phone (it buzzes, the reply threads, a card's buttons work) for a day of ordinary use, and with it off nothing about today's Telegram changes · related: `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS`, `FORK-PARALLEL-MESSAGING-GATEWAY` · folded 2026-11-15 (w1115e-rr2, owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"): `FORK-PARALLEL-MESSAGING-GATEWAY` (its question — keep the fork's own gateway beside upstream's — was answered by the owner's ruling to reuse the upstream connectors; owner 2026-10-20 "sounds good persona system for our custom gateway is the way") and `RT-MESSAGING-PLATFORMS-TELEGRAM` (the fork Telegram transport is on main, off by default; its remainder is this row's opt-in trial; owner triage 2026-11-09 "New optional channel; off by default") are closed into this row: after the opt-in trial, retire the fork transport in `agent_runtime/messaging/` · deferred 2026-11-15: owner — "unclaim that telegram row for now" (the real-bot trial is off the owner's list; the opt-in stays shipped, off by default) · LIVE CHECK 2026-11-19: the owner's real bot on a phone for a day of ordinary use — the reply buzzes and threads, an approval card's buttons work, a stranger gets no answer · RULED 2026-11-19: owner said "undefer it and have an aggent see and fix if need be" · handoff 2026-11-14 (msg-live-note): the live check ran against real Telegram on a throwaway bot, branch audit/upstream-telegram-switch 790202d002, script scripts/live_telegram_check.py there (reported by the owner, not seen by the lane): the bot reached step 6 of 6, so connect, the threaded reply, the formatted reply, the split long reply, the approval card press and edit, and a photo all went through real Telegram; asked whether the phone buzzed, the reply threaded, the formatting rendered, line 130 arrived and the card changed, the owner answered yes; the console summary was not pasted and the stranger step is not confirmed; not covered by it: a day of ordinary use, and the two failing upstream Windows stuck-poll tests · handoff 2026-11-14 (msg-opt-in): built and on main a682b32b82 (seen in a test): the setting messaging_telegram_transport picks fork (default) or upstream in the serve lane, a changed setting stops the running connector before the other starts, the operator list is asked at the adapter's intake with the sender's name, the card press handler is registered on every application the adapter builds; 111 messaging tests pass, each new check watched red; left is only the owner's own bot: turn it on with hermes config set plugins.entries.eternia-harness.settings.messaging_telegram_transport upstream on the machine whose Harness holds the bot token, use it from a phone for a day, and switch back with fork if anything is off; the builder could not do this read — it needs the owner's bot token, phone and Telegram account · handoff 2026-11-19 (w1118a-htele): re-checked on main 17485839f2 against the local Bot API stand-in (seen): scripts/live_telegram_check.py, unchanged, driven end to end — connect, threaded notifying reply, MarkdownV2 formatted reply, 130-line reply split into 3 (none over 4,096, last ends at line 130), approval card sent/pressed/answered/edited, operator photo fetched and handed on, a stranger's photo and text refused at the adapter's intake with no getFile or download and no answer; at DEBUG neither the bot token nor any message text reached the log; all passed. Real Telegram not driven: no staging or throwaway bot token is provisioned here (the credential store reads absent). The upstream adapter is now the ONE Telegram connector (RT-MESSAGING-RETIRE-FORK-TELEGRAM, d7542acf2d); the messaging_telegram_transport setting is gone, so the owner's read is: set the bot token with runtime.messaging.credential.set, enable messaging, and use it from a phone for a day (it buzzes, the reply threads, a card's buttons work), optionally scripts/live_telegram_check.py with a throwaway bot for the stranger step
- **`RT-MACOS-LINUX-BUNDLED-DESKTOP` — macOS / Linux bundled desktop ships no OS secure store: `keyring` (Keychain / Secret Service) is not in the bundled-desktop packaging, so `auth.os_secure_store: true` refuses to start there — add it to those targets' packaging when they exist** · group: signed-installs · see: Eternia `TASK-MISSION-CONTROL-ON-MAC` · `fork` · evidence: `agent_runtime/host_store/desktop.py::admitted_keyring_backend` · filed 2026-09-28 (lane w5-hdpapi) · `keyring` is in neither pyproject.toml nor uv.lock; add it as an optional extra + networked `uv lock` + bundled-desktop.yaml darwin/linux extras in the change that first builds those targets · RULED 2026-10-16: owner — "add keyring when mac/linux builds exist, not now"; prove it at the Mac sitting · RULED 2026-11-10: owner — split: the Mac half (Keychain `keyring` extra + proving `admitted_keyring_backend` on a Mac) moves to the Mac sitting task `TASK-MISSION-CONTROL-ON-MAC` (Eternia, "…move the mac to a mac sitting task"); the Linux half (Secret Service in a Linux bundled target) stays in this task · DEFERRED 2026-10-18: `bundled-desktop.yaml` declares no darwin/linux target yet, so there is no packaging to add it to; the change that adds the first such target adds `keyring` (optional extra + networked `uv lock` + that target's extras) and proves `admitted_keyring_backend` at the Mac sitting — owner 2026-10-16 · moved 2026-11-12 (triage w1112b): from `TASK-EMBEDDED-HERMES` to `TASK-SIGNED-INSTALLS` — both halves wait on a macOS or Linux bundled-desktop target, which that task builds (Eternia `COMP-HERMES-POSIX-BUNDLE`); owner 2026-11-12 kept it deferred (deferred-task review, batch 3: "the other nine stay deferred (phones, release, Linux packaging)") and then "undefer everything in the open ready tasks being worked on so they can complete"; the 2026-11-10 split named a Mac row that was never filed, so the row keeps both halves · folded 2026-11-16 (review w1115e.18, B68; owner "Accept all"): hermes `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS` — done when also: deleting a namespace removes its `hermes-agent/<ns>` keyring entries (`namespace_admin.py` touches no host store today, and no shipped build binds the keyring yet) · RULED 2026-11-19: owner said "the launch v1 tasks should remain deffered imho" — kept deferred as launch-v1 work (packaging for the macOS / Linux bundled-desktop targets, under the deferred Eternia `TASK-SIGNED-INSTALLS`)

### Filed on arrival — 2026-09-29 (lane h11-mcp)


### Filed on arrival — 2026-09-29 (lane h9-bundle)


### Filed on arrival — 2026-09-30 (lane s2-plan — phone gate → zero, one row per lane; work them in the plan's order)

### Filed on arrival — 2026-09-28 (lane p2-hphone)

### Filed on arrival — 2026-09-28 (lane p1-hsplit)

### Filed on arrival — 2026-09-28 (lane w4-hd4)

### Filed on arrival — 2026-09-29 (upstream merge `merge/upstream-2026-09-29`, filed by the orchestrator)

### Filed on arrival — 2026-09-29 (lane h7-phone)

### Filed on arrival — 2026-09-29 (lane w6-hwort)
- **`RT-PIPER-FIRST-AUDIO-LATENCY` — Piper first audio is ~2 s on a sentence with a name the phonemizer dictionary lacks ("…Mira hasn't joined yet") vs 0.2–0.5 s otherwise — profile the out-of-dictionary path (the model runs per word) and cache or batch it.** · group: bundled-voice · `agent_runtime/speech_phonemize.py`; listening manifest (lane h8-voice, 2026-09-29) · code read: `OpenPhonemizer._predict` is one ORT forward per OOD word, so the likely cost is the first forward on a fresh input shape; owner 2026-09-29: profile once the voice pack is on the box, a warm-up forward at load is the likely cheap fix · RULED 2026-10-25: owner — an agent runs this sitting on this PC · LIVE 2026-10-25: no Piper pack or openphonemizer model anywhere under the hermes roots (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · DEFERRED 2026-11-09: owner triage — Noticeable but niche; needs voice pack installed; until the owner reopens it · waits: owner-ruling · moved 2026-11-10 (owner yes on w1110a-org's finding): from eternia-lens — voice speed belongs to TASK-BUNDLED-VOICE

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


### The ghost agent — filed 2026-09-11 from the office removal-lane fix


### Runtime observability — filed 2026-09-06 from the post-rebuild field run


### Snapshot build latency on Windows — filed 2026-09-08



### Harness CLI and the doctor — 2026-08-30 / 2026-09-02 hand-backs, 2026-09-12 skill sync




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

### Filed on arrival — 2026-11-15 (lane codex-win-hermes)


### Filed on arrival — 2026-11-01 (release merge lane, branch `merge/upstream-v0.22.5`)


### Filed on arrival — 2026-11-10 (lane w1110c-hmboot: `RT-HARNESS-SERVE-COLD-BOOT`)


### Filed on arrival — 2026-10-29 (lane w1029b-h-rt)


### Filed on arrival — 2026-10-21 (lane w1021h-daily, `integration/upstream-daily` `4ce03587da`)


### Filed on arrival — 2026-10-21 (lane w1021h-rpc, branch `w1021h/rpc`)


### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)

### Filed on arrival — 2026-10-16 (lane r-turnrec)




### Filed on arrival — 2026-10-15 (door PR lanes doors-a, doors-b)







### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)



### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)

### Filed on arrival — 2026-10-08 (native connection ownership cleanup)

### Filed on arrival — 2026-10-06 (upstream sync planning; AFTER the next release merge)



### Filed on arrival — 2026-10-06 (lane h-prereq-window)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)


### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-05 (lane h-prompt-tools)


### Filed on arrival — 2026-10-04 (lane hb-a)


### Filed on arrival — 2026-10-03 (lane h-mcpwake)


### Filed on arrival — 2026-10-02 (instance-conversations)


### Filed on arrival — 2026-10-01 (lane w3-turn)


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




## Upstream-owned

### Filed on arrival — 2026-11-15 (lane w1115e-rr2: the deep sweep's row-reduction pass)

- **`RT-RECHECK-AFTER-THE-PRE-LAUNCH-HERMES-UPDATE` — After the pre-launch Hermes update, 33 old findings in upstream code are checked once more and only the ones still true come back** · group: upstream-footprint-ledger · upstream-owned code the fork cannot edit (§ Upstream-owned) · filed 2026-11-15 by w1115e-rr2 from the deep sweep 2026-11-15 §H-B3 (owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure") · read in git, not re-run: the update (merge-base 3b42157858 to `upstream/main`) rewrites the files these rows cite — `hermes_cli/gateway.py` +30/−123, `hermes_cli/gateway_windows.py` +96/−27, `hermes_cli/config.py` +64/−235, `agent/ssl_verify.py` +74, `tools/delegate_tool_config.py` +41, `agent/prompt_builder.py` +60/−25, `tui_gateway/host_supervisor.py` +41/−15, `hermes_state.py` +31/−21, `gateway/hosted_room_policy_checkpoint.py` +30 · architecture: no fork edit and no upstream edit — a re-check only; each survivor is filed as its own row by the layer it lands in (a fork seam per the fork-route-first rule, or an upstream issue); each row's full text is in `Harness_Brain/80 — Archive/Queues/` (runtime-queue-2026-11.md, fork-hygiene-queue-2026-11.md) · checklist (each row closed into this one, its owner quote kept): `RT-REQUEST-BUILT-RESOLVES-WEB`: re-time the per-request web-search provider lookup in `agent/transports/codex.py::_alias_wire_tools` (owner triage 2026-11-09 "Small latency; owner ruled wait on upstream"); `RT-SEND-PREP-H7-UNRESOLVED`: re-split the 47–50 ms warm request build in `ResponsesApiTransport.build_kwargs` ("Small latency measurement; waits on upstream"); `RT-SEND-PREP-H2-H6`: re-measure skill preload and package stamps on a skill-heavy persona; it did not reproduce on the fresh route ("Small latency; waits on upstream"); `RT-SKILL-CATALOG-FRONTMATTER`: re-time `tools/skills_tool._skill_catalog` frontmatter parsing and the kanban gate's 1.3 s first import ("Small performance gain; upstream-owned"); `RT-DASHBOARD-AUTH-SCRYPT-IMPORT`: check `plugins/dashboard_auth/basic` still computes its scrypt dummy hash (~0.2 s) at import ("Test-speed issue only; no user impact"); `RT-PROCESS-STARTUP-UPSTREAM-WORK`: re-time the provider discovery (~1.6 s) that importing `hermes_cli.config` runs for read-only verbs ("Noticeable but not broken; depends on upstream accepting PRs"); `RT-I18N-BUNDLED-PER-HOME`: check `agent/i18n.py::_load_catalog` still re-reads the bundled translations per profile ("Performance mostly felt in tests; upstream-owned"); `RT-CONFIG-NOFILE-REBUILD`: re-time a profile with no `config.yaml` through `hermes_cli/config.py::_load_config_impl` (config.py +64/−235 in the update; 72.5 s vs 41.2 s test file) ("Performance tweak; upstream-owned, workaround is adding a file"); `RT-AUX-KEY-CHAIN-LOAD-CONFIG`: count `load_config()` calls per `agent/auxiliary_client._resolve_api_key_provider` auto resolution (~48 providers) ("Performance gain only; upstream-owned"); `RT-NATIVE-WORKER-UPSTREAM-BOOT`: re-time a native worker's ~5 s to first reply: `tui_gateway.server` import, first agent build, first `model.options` ("Felt latency but depends entirely on upstream work"); `RT-CHECKPOINT-PM-ENSURE`: check `tools/checkpoint_manager._run_git` still calls `pm.client.ensure` on every git call (~11 ms each) ("Speed-up mostly felt in test runs; upstream owns the fix"); `RT-DELEGATION-KNOB-ENV-DEAD`: check `DELEGATION_MAX_CONCURRENT_CHILDREN` / `DELEGATION_CHILD_TIMEOUT_SECONDS` still lose to DEFAULT_CONFIG in `tools/delegate_tool_config.py::_knob` (+41 in the update) ("Settings work through config instead; minor"); `RT-CONTEXT-MANIFEST-WITHIN-KIND`: check `/context` still marks every candidate of a kind loaded while `agent/prompt_builder.py` (+60/−25) loads only the nearest ("Misleading display in a power-user command; upstream-blocked"); `RT-HERMES-STATE-SCHEMA-STALE`: check Windows chat search recovers by itself after its search index is damaged (`hermes_state.py` +31/−21) ("Real but rare; owner already ruled to wait for upstream"); `RT-SPARK-PRO-USAGE-BUCKET`: check `gpt-5.3-codex-spark` on the ChatGPT-account Codex route; `hermes_cli/codex_models.py` already lists it ("Model is already safely disabled; adding it is a nice-to-have"); `FORK-WINDOWS-SIGNAL-SAFETY-CARRY`: check whether upstream now ships an equal Windows Ctrl+C safety fix; if it does, drop the carry ("Reminder only; nothing to do until upstream changes"); `RT-GATEWAY-START-MANAGED-PYTHON`: check `hermes --profile <name> gateway start` from the managed venv (`hermes_cli/gateway.py` +30/−123) (owner 2026-11-05 "thats upstreams gateway stuff im going to build my own external gateways"); `FH-FLAKE-API-ADMISSION-OFF-LOOP-UNDER-LOAD`: re-run `tests/gateway/test_api_admission_off_loop.py` (owner triage 2026-11-09 "Test-only timing flake; the product itself is not shown broken"); `FH-FLAKE-SESSION-AUTHORITY-OWNER-KILL-UNDER-LOAD`: re-run `tests/gateway/test_session_authority.py` (same triage); `FH-FLAKE-BROWSE-SCHEMA-DRIFT-CONCURRENT-UNDER-LOAD`: re-run `tests/hermes_cli/test_browse_schema_drift.py` (same triage); `FH-FLAKE-SCHEDULER-PROVIDER-RECOVERY-THREAD`: re-run `tests/cron/test_scheduler_provider.py` (same triage); `FH-FLAKE-API-PENDING-DAEMON-DEADLINE`: re-run `tests/gateway/test_api_pending_daemon.py` (same triage); `FH-FLAKE-EXECUTE-CODE-GATE-LOOP-TICK`: re-run `tests/gateway/test_local_turn_origin_execute_code_gate.py` (same triage); `FH-FLAKE-LOCAL-SESSION-APPROVAL-CHILD`: re-run `tests/gateway/test_local_session.py` (same triage); `FH-FLAKE-SHARED-BUSY-RECEIVE-DEADLINE`: re-run `tests/gateway/test_shared_busy_receive_loop.py`, an upstream file the fork edits (same triage); `FH-FLAKE-WEBHOOK-AUTHORITY-CHILD`: re-run `tests/gateway/test_webhook_authority.py`, an upstream file the fork edits (same triage); `FH-FLAKE-SESSION-CONFIG-PROJECTION-PROVIDERS`: re-run `tests/gateway/test_session_config_projection.py` ("Only seen under heavy test load; no user report"); `FH-FLAKE-CONNECTOR-OPERATION-RPC-NO-REPLY`: re-run `tests/tui_gateway/test_connector_operation_rpc.py` (same triage); `FH-FLAKE-PM-STREAMING-DEADLINE-UNDER-LOAD`: re-run `tests/pm/test_environment_build.py` (same triage); `RT-FLAKE-UPDATE-EXISTING-MAIN-SWITCH-HANDOFF`: re-run `tests/hermes_cli/test_update_existing_branch_baseline.py`, on a quiet box first (deferred 2026-11-10 into the load-flakes batch); `RT-UPSTREAM-TEST-RACES-TWO`: re-run `tests/tools/test_browser_eval_supervisor_path.py` and `tests/agent/test_run_agent.py::TestExecuteToolCalls` (owner 2026-10-16 "pr branches should remain idle"); `FH-UPSTREAM-TESTS-STRIP-SYSTEMROOT`: re-run `tests/hermes_cli/test_update_restore_authority.py` and `tests/hermes_cli/test_runtime_maintenance_exclusion.py` on Windows ("Upstream test bug; product unaffected"); `FORK-QUALIFY-NATIVE-WINDOWS-MSYS`: re-check MSYS foreground-child cleanup on native Windows ("Rare leftover processes; upstream-owned; needs report first") · done when: the update has landed; the 16 test files are re-run at -j 24 on a busy box, the 11 latencies re-measured once (as Eternia `TASK-WINDOWS-HANDOFFS` rows), the 6 behaviours re-read; only what still fails is filed, and this row closes · reviewed 2026-11-15 w1115e.10 · handoff 2026-11-21 (review w1118a.69): carries one more re-read, from `RT-FU-THE-AGENT-PROFILE-SEED-BRIDGE-IS-RE-READ-AT-THE-NEXT-UPSTREAM-MERGE` — when the update brings upstream's `create_profile(seed_model=False)` (upstream 0c35c98c1a), re-read `agent_runtime/agent_profile_create.py::_create_seeded` (it points the context home at a throwaway seed home because the fork's `create_profile` seeds the head home's model block, an inline key possible): keep the seed route or move to `seed_model=False` with the carried model block still migrated, `tests/agent_runtime/test_agent_copy_keeps_its_model_endpoint.py` green · DEFERRED 2026-11-15: waiting on the pre-launch hermes update; until it lands · RULED 2026-11-19: owner said "the launch v1 tasks should remain deffered imho" — kept deferred as launch-v1 work (it runs at the pre-launch hermes update; the owner allows the full suite only on upstream release updates)

### Filed on arrival — 2026-10-26 (lane w1026c-h-fork)


### Filed on arrival — 2026-10-25 (lane w1025b-h-audit)


### Filed on arrival — 2026-10-21 (lane w1021j-tooling, branch `w1021j/tooling`)


### Filed on arrival — 2026-10-18 (land w8)


### Filed on arrival — 2026-10-18 (lane r-state, branch `q/r-state`)


### Filed on arrival — 2026-10-17 (harvest)


### Filed on arrival — 2026-10-17 (lane r-perf)



### Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-08 (lane opus-w1-hermes, moved from fork-hygiene)


### Filed on arrival — 2026-10-06 (lane h-suite-tail-b)


### Filed on arrival — 2026-10-05 (lane h-defer, name-set sweep)


### Filed on arrival — 2026-10-02 (lane w5-fh, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (instance conversations)


### Filed on arrival — 2026-10-01 (lane rw-h)


### Filed on arrival — 2026-09-29 (lane h11-code)


### Filed on arrival — 2026-09-29 (lane h10-rtseam, filed by the orchestrator)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)


### Filed on arrival — 2026-09-29 (lane fix-node-deps, filed by the orchestrator)


### Filed on arrival — 2026-09-29 (PR #125262 review follow-up, filed by the orchestrator)


### Filed on arrival — 2026-09-27 (lane PR-REPLIES, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane HELD-TESTS, filed by the orchestrator)



### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)




### Filed on arrival — 2026-10-03 (lane h-twins)

### Filed on arrival — 2026-10-03 (launcher lane rpc-census, filed by the orchestrator)

### Filed on arrival — 2026-10-03 (cold first-chat diagnosis, filed by the launcher orchestrator)

### Filed on arrival — 2026-10-03 (lane h-chatperf)

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

### Filed on arrival — 2026-10-18 (lane h3-plugins, branch `q/h3-plugins`)

### Filed on arrival — 2026-10-18 (lane h4-hotpath, branch `q/h4-hotpath`)

## Filed on arrival — 2026-10-18 (lane h5-boot)

## Filed on arrival — 2026-10-18 (land h1018)


## Filed on arrival — 2026-10-18 (owner sitting: Work on todo boards)


## Filed on arrival — 2026-10-18 (design: dispatcher and libraries)


### Filed on arrival — 2026-10-18 (lane w2-phone, branch `w2/phone`)


### Filed on arrival — 2026-10-18 (lane w2-realm, branch `w2/realm`)

## Filed on arrival — 2026-10-18 (land w2)


## Filed on arrival — 2026-10-18 (land w3)

### Filed on arrival — 2026-10-18 (lane w5-misc, branch `w5/misc`)

### Filed on arrival — 2026-10-18 (lane w5-sched, branch `w5/sched`)

## Filed on arrival — 2026-10-19 (launcher wave w1020)

- **`RT-WIN-CONSOLE-FLASH-CODEX-SWITCH` — A Windows console window flashes when the Agent Console switches a chat to openai-codex** · group: provider-api-key-and-usage-source · owner 2026-10-19 13:04:41Z (launcher `[MissionModelPick]` chosen=openai-codex/gpt-6-sol): the launcher spawns nothing on that path (RPC-only; its serve child is started detached, with no console), so a console child of hermes opened it. Candidate: `agent/transports/codex_app_server.py::check_codex_binary` runs `codex --version` without `windows_hide_flags()` while the Popen beside it hides; audit the openai-codex select / models / first-turn paths for subprocesses spawned without CREATE_NO_WINDOW and pin one with a Windows test · launcher `MC-PROVIDER-SWITCH-LOCKS-PICKER` waits on it (filed by launcher lane w1020-console) · BLOCKED 2026-11-12: owner sitting — one provider sitting: the owner signs in to their own provider accounts on Windows and watches one switch to Codex for a console window flash (probably fixed by 620de2c049) · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, as recommended" · was dEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: switch a chat to openai-codex on the Windows box and watch for the flash (check_codex_binary now hides its console, 620de2c049)

## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)


## Filed on arrival — 2026-10-20 (launcher plan: edition switch and the shared namespace store, `EterniaLauncher` `9185222120`)


## Filed on arrival — 2026-10-22 (launcher session, owner report from a Neko Mission Lead turn)


## Filed on arrival — 2026-10-22 (land w1022d)


## Filed on arrival — 2026-10-23 (launcher lane w1023l-mc)


## Filed on arrival — 2026-10-24 (launcher session, owner report: yellow readiness text on every agent)

## Filed on arrival — 2026-10-25 (lane w1024t-hermes2)

## Filed on arrival — 2026-10-25 (launcher lane w1025a-comp)

## Filed on arrival — 2026-10-26 (launcher session: first Linux install of the Developer Edition)


## Follow-up suggestions — planned completion and qualification


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


## Filed on arrival — 2026-11-01 (lane w1101b-perf, the first idle-box run)


## Filed on arrival — 2026-11-02 (launcher lane w1101h-teardown)





## Optional suggestion post-call work — 2026-11-03




## Filed on arrival — 2026-11-04 (owner via Eternia: the workspace absorbs Projects; plan w1104-wsmerge)

- **`RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM` — once the owner's first gateway answers: stop the alice upstream gateway, remove its logon task, delete the shared bot token from the eight profile `.env` files (no code)** · group: remote-parity-and-two-machine-proof.external-gateway-access · `docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md` §2 D4, §5 · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: after the owner's first gateway is live · waits: owner-ruling



## w1108b hand-off to the Linux box — 2026-11-08


## Filed on arrival — 2026-11-08 (lane w1108b-hfh)


## Filed on arrival — 2026-11-08 (Eternia lane w1108d-mclive)


## Filed on arrival — 2026-11-09 (Eternia lane queue-grammar-at-write)


## Filed on arrival — 2026-11-09 (Eternia lane w1109a-console-live)

## Filed on arrival — 2026-11-09 (Eternia lane w1109a-console2)

## Filed on arrival — 2026-11-09 (Eternia lane w1109a-lens3)


## Filed on arrival — 2026-11-10 (Eternia lane w1110c-hmsync)

## Filed on arrival — 2026-11-10 (lane w1110c-hm3)

- **`RT-ROOM-TURN-CONNECTION-CHURN` — Discussion rooms would move between members faster if a turn did not open the room database about seventy times** · group: windows-handoffs · `agent_runtime/discussions/service.py::DiscussionService.prepare`, `gateway/hosted_room_policy_checkpoint.py`, `tui_gateway/hosted_room_driver.py` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2: after 5cd83a166db a twelve-member room still takes ~0.8 s per member turn with an instant model, CPU-bound on SQLite connection opens (~4,100 per two-round test; every op opens and closes its own connection); `prepare` runs twice per turn (the terminal publish, then the next cycle), each reading the room three times and the policy checkpoint twice; most opens are in upstream hosted-room modules (a door, never an edit); Windows also pays `tests/home_io_guard.py`'s realpath per mkdir · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · READY 2026-11-19 · RULED 2026-11-19: owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — undeferred: its deferral was joining the owner-deferred speed task TASK-AGENT-START-UP-COST, which Eternia `TASK-WINDOWS-HANDOFFS` (READY) replaced; read in code 2026-11-19: `agent_runtime/discussions/definition_store.py` still opens a connection per op and `DiscussionService.prepare` is unchanged, so a room still waits ~0.8 s per member turn — a separate perf lane, never a feature lane · review w1118a.48: undeferral checked (its speed task was replaced by Eternia `TASK-WINDOWS-HANDOFFS`, READY); a separate perf lane per the owner's 2026-11-12 rule, never a feature lane · reviewed 2026-11-19 w1118a.48

## Filed on arrival — 2026-11-11 (launcher plan w1111e-manage-ws)

- **`RT-GROUP-MEMBER-FIRST-TURN-COLD-START` — A group member with turn isolation on asks its model sooner after you message the room** · group: windows-handoffs · measured 2026-11-12 by w1112a-hmtests on DESKTOP-QJ7DDV2 (moderate load, eight runs of `tests/agent_runtime/test_discussion_group_compute.py` with temporary monotonic stamps): submit → claim 0.05 s, → member worker `main` 0.6-1 s, → worker ready 1.3-2.3 s more, → `open_member` done 2-3.7 s more, → compute host `main` 1-1.4 s more, → `send` returns 1.5-2 s more, → first model request 6.2-9.6 s more; 15-17 s on a quiet box, 27 s on a busier one; the last leg (compute host to first request) is the largest · REQUIRES windows · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · READY 2026-11-19 · RULED 2026-11-19: owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — undeferred: its deferral was its old speed task, which Eternia `TASK-WINDOWS-HANDOFFS` (READY) replaced; 15-27 s from your message to a member's first model request is felt by every group-chat user — a separate perf lane on the Windows box · review w1118a.48: undeferral checked (its speed task was replaced by Eternia `TASK-WINDOWS-HANDOFFS`, READY); a separate perf lane per the owner's 2026-11-12 rule, never a feature lane · reviewed 2026-11-19 w1118a.48

## Filed on arrival — 2026-11-12 (safe local runtime restart)

- **`RT-WINDOWS-UPDATE-RESTART-DEFAULT-IDENTITY` — Updating Hermes restores the host gateway under its default identity** · group: windows-handoffs · seen 2026-11-13 by hermes-creation: canonical updates from 51014a80 through 1825fa6445 and 4d29a8936c pause the zero-turn default multiplexer but automatic Windows restart repeatedly selects sticky active profile amelia and refuses a separate poller; explicit hermes -p default gateway restart restores all eight original profiles and Telegram · cause: gateway_windows._launcher_settings uses gateway._profile_arg which returns an empty selector for the default root; detached boot follows active_profile; the later update fleet also labelled the root multiplexer amelia, classification cause not yet traced · done when: canonical Windows update preserves the root gateway identity and restores its original served profiles with one poller through existing lifecycle authority · READY 2026-11-19 · REQUIRES windows · handoff 2026-11-15 (codex-win-hermes): The update watcher, not the supervised launcher renderer, chose the wrong home: its Windows overlay was based on the updating CLI, and its unpinned selectorless root followed active_profile. Five Windows regressions red on 1e7d9652a5 and green on topic 8179f588ed. An isolated native Windows pause/resume restored the default and all eight profiles; the replacement default PID was the only new Telegram poller against a loopback fixture, and the fleet labelled it default. The topic waits on the footprint ruling (three base lines moved into else) and a landing; a full source/dependency swap was not exercised. · handoff 2026-11-19 (w1118a-coord): RULED 2026-11-19: owner answered the decision 'May the restart fix move three upstream watcher lines into the fallback branch, raising deleted_lines from 874 to 877?' with "yes" — build the recommended fix (candidate on wave/codex-win-hermes at 83869ce5d3); REQUIRES windows · **TAKEN 2026-11-15 codex-win-hermes on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes**

## Filed on arrival — 2026-11-13 (lane w1112b-hm5: review batch w1112b-6 §2)


## Filed on arrival — 2026-11-13 (Eternia orchestrator: GitHub-quota read)


## Filed on arrival — 2026-11-13 (Eternia orchestrator: git-host architecture read)



## Filed by Eternia review batch w1114a.2 — 2026-11-14

- **`RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` — When GitHub refuses a realm's push because the owner disconnected the repository, the member is told to ask for a reconnect within a minute, instead of retrying a dead token for up to 44 minutes** · group: runtime-followups · from: `TASK-WORKSPACE-ABSORBS-PROJECTS` · `agent_runtime/realm_sync/` · read in code 2026-11-14 (`eternia-backend` `603184bc`, `REALM-GIT-BINDING-DEATH-UNSEEN-WHILE-TOKEN-CACHED`): the backend now takes `POST /api/realms/{id}/sync/auth-rejected` (local `/api/me/realms/{ref}/sync/auth-rejected`) with the credential's `api_token`, answering 204 (re-broker) or 409 `realms.git_host_binding_lost`; hermes calls it nowhere · the Eternia half is already mapped (read in code: Eternia `realm_sync_credential_failure.dart` maps `realms.git_host_binding_lost` to reconnect), so it is this row's own live read, not a separate row · done when: a push or fetch refused 401/403 by github.com reports once, a 204 re-brokers, a 409 reaches the snapshot as `git_host_binding_lost`, pinned by tests; and the builder reads Mission Control showing reconnect, not retry, in a QA copy · NEW 2026-11-14 · reviewed 2026-11-14 w1114a.2 · the read, once unblocked: built ef70922059 (report on 401/403/404 from publish, pull, status; 204 re-broker, 409 host-state mark; 13 tests on a local refusing HTTP host) — read Mission Control showing reconnect after GitHub refuses a server realm's push · handoff 2026-11-14: not read live — making github.com refuse a staging realm's token means uninstalling the staging GitHub App or dropping a repo from its installation, a GitHub account settings change no lane may make unasked; the hermes→snapshot half is pinned by test (sync.revoked reason git_host_binding_lost, host_state true), the Eternia render of that mark is existing code (mission_snapshot_realms.dart) · handoff 2026-11-14 (w1114a-realmlive): probe approved by the owner and staging rolled to backend 4c38b903, but no tool on the Linux box can take a repo out of the staging App's installation (gh's OAuth token is refused 403 on installation repositories, the built-in browser is signed out of GitHub, the Chrome extension is not connected), so GitHub's refusal was never provoked; what is left: the owner unticks ArcadiaLabsLLC/eternia-probe-org-create-2026-11 in the eternia-server-realms-staging installation, a lane binds QA Realm to the probe (staging manage.py shell: realms.subject_git_host _upsert of the realm subject with installation 181291722, then connect_realm_github as the server owner), Pulls as account B and reads the sheet, then the owner re-ticks it and the lane unbinds (disconnect_realm_github) · READY 2026-11-21 · waits: owner-ruling · reviewed 2026-11-16 w1115e.18 · handoff 2026-11-21 (orchestrator): 2026-11-21 orchestrator, the owner asked for a read that needs no GitHub settings change ("can't you test that another way it can on its own"): a GitHub App installation token can revoke itself (DELETE https://api.github.com/installation/token with that token), so the lane makes github.com refuse the realm's cached token for real with no installation edit — bind QA Realm to the probe as the row says, Pull once so hermes holds a token, revoke that token, Pull again: GitHub answers 401, hermes reports auth-rejected, and with the binding intact the backend answers 204 and re-brokers (the 204 leg read live); for the 409 leg the lane first reads in eternia-backend how auth-rejected decides git_host_binding_lost, and if that decision reads the staging binding row (not a live GitHub installation call), breaks the binding on staging only (manage.py shell, the probe realm's subject binding) before the revoked Pull, reads Mission Control showing reconnect, then restores it; if the backend asks GitHub live, only the installation untick reaches 409 and the row says so; never print a token
- **`RT-SCHEDULE-SYNC-AND-KNOB-2` — Agent schedules stay in step between your two machines, like the rest of your agent setup** · group: runtime-followups · from: `TASK-REALM-SYNC-FAMILY-DESCRIPTOR` · reopened 2026-11-16 (review w1115e.18, B68): `RT-SCHEDULE-SYNC-AND-KNOB` was DEFERRED by the owner and folded into the READY `RT-SYNC-FAMILY-DESCRIPTOR`, which undeferred it silently; it returns to DEFERRED here under a new ID (the old one is archived) · architecture: `agent_runtime/work_store/schedule_store.py`, `agent_runtime/realm_sync/document_family.py`; plan `docs/agent-runtime-harness/archive/dispatcher-and-libraries-2026-10-18.md` §2.3; the knob half landed (root config `agent_runtime.scheduler.max_parallel`) · RULED 2026-10-18: owner — schedules stay local to the machine that armed them for now; the realm-sync family waits for a design of delete propagation and per-fire publish · RULED 2026-11-16: owner — "Accept all" (on review w1115e.18, B68) · DEFERRED 2026-11-16: owner — schedules stay local for now (ruled 2026-10-18); waits for a design of delete propagation and per-fire publish · waits: owner-ruling · reviewed 2026-11-16 w1115e.18

## Filed by Eternia review batch w1114a.3 — 2026-11-14

## Filed on arrival — 2026-11-14 (lane w1114a-hanthropic)

## Filed on arrival — 2026-11-14 (lane w1114a-hlens-rules)


## Filed on arrival — 2026-11-14 (lane w1114a-hlens-budget)

- **`RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` — Message your agents from Discord, through upstream's ready-made connector** · group: runtime-followups · from: `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF` · fork / messaging · the build the owner's ruling on `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS` opened: a `Platform` member in `agent_runtime/messaging/models.py`, the token in `credentials.py`, a factory in `serve_lane.py` over the shim, Discord's own answer to each SWITCH_AUDIT finding (the sender gate: `RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM`; read in code, not run: after connect the adapter bulk-syncs upstream's slash commands with `tree.sync`, which its `sync_policy` `off` skips; whether discord.py logs the token or message text was not checked), approval cards as Discord components, and its Eternia page · bundle fit measured 2026-11-14 (w1114a-hmsgadapt): no adapter library enters the bundled-desktop or bundled-phone closure (both ship only the anthropic, mcp and fal extras, and switch off `agent_runtime.messaging`); on a full Harness the locked `discord.py[voice]` adds 14.7 MB installed over the base install, aiohttp's stack included · not shown: a real Discord message, which is the owner's sitting · RULED 2026-11-14: owner — "go with your recommendation after an architecture investigation for this session" (orchestrator, REVIEW_W1114A_B27: the NEXT-APPS ruling chose how, not when; Discord waits with its DEFERRED parent) · NEW 2026-11-14 · DEFERRED 2026-11-14: waits with the DEFERRED parent Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`; the gate it needed, `RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM`, is being built by w1114a-hmsggate · waits: launcher `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`

## Filed on arrival — 2026-11-14 (lane w1114a-hcensus)

## Filed on arrival — 2026-11-15 (lane w1115e-h3)
- **`RT-GENUI-AB-VERIFIES-THE-AGENT-AND-PROVIDER` — The comparison evaluation counts each answer under the agent and provider that actually produced it** · group: windows-handoffs · `evals/genui_first_response_ab.py` (`drive`, `collect`, `PromptResult.provider_key`) · `EterniaLauncher/lib/app/app_functions/app_function_agent_chat.dart` · source-audited 2026-11-15 by codex-win-hermes-handoffs on the exact two Eternia arm commits (`8ee367c821`, `469e500730`): new chat uses the selected agent and ignores the emitted agent/provider args, while scores prefer the planned provider label over the observed context receipt; no provider calls sent. · done when: dry-run each historical Console contract via the existing selected-agent and model-picker doors, pin their readbacks to the fresh chat, and prove a wrong agent/provider/model or absent receipt stays unverified before it can enter a passing cell. · NEW 2026-11-15 · reviewed 2026-11-15 codex-win-handoffs · LIVE CHECK 2026-11-15: open each pinned historical Debug executable in a lane-scoped nonbillable fixture, verify its build stamp and Console agent/session/model readbacks through the v2 preflight · handoff 2026-11-15 (codex-win-hermes-handoffs): v2 eval driver and Windows offline coverage are in `567aff25ec`, `04a3dee9bc` and `90cc579f4e`. Both exact historic console sources expose the required doors. Next read: drive the two historical Debug executables with an isolated model fixture, verify their compiled Stage C build and zero-send Console readbacks, then keep the real A/B behind its separate per-arm approvals. Evidence `docs/agent-runtime-harness/evidence/windows-handoffs-2026-11-15/genui-readiness.md`. · REQUIRES windows, linux · **TAKEN 2026-11-15 codex-win-hermes-handoffs on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes-handoffs**
- **`RT-WARM-AGENT-TURN-SKIPS-THE-HISTORY-REREAD` — A chat turn on an agent that is already warm starts without re-reading and re-filtering its whole history** · group: windows-handoffs · task in Eternia: `TASK-WINDOWS-HANDOFFS` · moved 2026-11-15 (w1115e-rr6, B60) from `TASK-RUNTIME-FOLLOWUPS`: unmeasured speed work goes to the perf list, never a feature lane (owner 2026-11-12); its S4 still needs an upstream ledger row and the owner's words · from: `TASK-ONE-TURN-RECORD` · carried from `RT-NATIVE-HISTORY-REREAD` (folded into `RT-TURN-RECORD-AT-ADMISSION`, which closed without it, 8ce7470b6b) · read in code, not measured this wave: lineage-stamp S1–S3 landed (fc3350d3044, a resident actor hands its history over when the stamp matches), but `chat_turn_commit/run.py::_build_context` still reads `abandoned_mission_chat_message_ids` and `mission_chat_turn_records` and re-filters the history on every turn, resident or not; S4 of `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` (a public lineage revision) edits upstream `hermes_state*.py` and needs the owner's words and a ledger entry · architecture: layer fork lanes (`run.py::_build_context`) plus upstream state for S4; seam `agent_runtime/session_lineage_stamp.py` and `persona_chat_runtime_registry().resident_native_history`; files `hermes_cli/harness_parts/persona/chat_turn_commit/run.py`, `agent_runtime/session_lineage_stamp.py`, `agent_runtime/mission_chat_turns/reads.py` · reviewed 2026-11-15 w1115e.10 · NEEDS PLAN 2026-11-15: a measured plan for the perf lane; S4 waits on the owner's words for an upstream edit

## Filed on arrival — 2026-11-16 (lane w1115e-fh5)

## Filed on arrival — 2026-11-16 (lane w1115e-rs: the owner's report of a realm member's sync)

## Filed on arrival — 2026-11-17 (lane w1116b-rtfu)


## Filed on arrival — 2026-11-18 (side session from Eternia's realm push alert, `EterniaLauncher` `360d3de929`)


## Filed on arrival — 2026-11-19 (review w1118a.29, from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE`)

## Filed on arrival — 2026-11-19 (lane w1118a-hsurf)

## Filed on arrival — 2026-11-19 (lane bundled-runtime)


## Filed on arrival — 2026-11-19 (lane bundled-pushlist)


## Filed on arrival — 2026-11-19 (lane bundled-menus)


## Filed on arrival — 2026-11-19 (lane bundled-facts)

## Filed on arrival — 2026-11-19 (review w1118a.52, from Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`)


## Filed on arrival — 2026-11-19 (review w1118a.46, from Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE`)


## Filed on arrival — 2026-11-19 (review w1118a.47, from Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST`)


## Filed on arrival — 2026-11-19 (review w1118a.48, from Eternia `MC-SUBTASK-HOLD-TO-ARCHIVE`)


## Filed on arrival — 2026-11-19 (review w1118a.50, from Eternia `MC-SYNC-PULL-UNDOES-A-LOCAL-RENAME-MADE-SINCE-THE-LAST-PUBLISH`)


## Filed on arrival — 2026-11-20 (lane w1119-busystop: the owner's stop order that bounced off a busy lane)


## Filed on arrival — 2026-11-20 (lane w1118a-hagent: the runtime's idle-instance rule, which Eternia still copies)


## Filed on arrival — 2026-11-20 (lane w1120a-helperclaim)

- **`RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS` — A command your agent's terminal gave up on stops, rather than finishing its work after the agent was told it timed out** · group: runtime-followups · from: launcher `QA-FU-A-HELPER-CLAIMS-IN-THE-SHARED-CHECKOUT-AND-STOPS-ON-ITS-OWN-CLAIM` (w1120a-helperclaim) · seen 2026-11-20 read-only in the owner's install on Windows: session `persona_chat_personainst_dev_agent_8b319ebf_144d0dee5352` ran `dart tool/queue/task.dart --claim … --as dev` with `timeout: 30`; the terminal answered exit 124 "[Command timed out after 30s]" at 18:13:26Z, and the claim commit `b3316bc20a` it was making landed on the EterniaLauncher primary's `main` at 18:13:32Z, six seconds later; the agent's retry was then refused on that claim · cause not read: `tools/environments/local.py` `_kill_process` routes Windows to `_kill_process_windows` (a tree kill); whether `dart` (a shim launching `dart.exe`) or its `git` child escaped it is a guess · done when: a foreground command killed for its timeout on Windows leaves no descendant running (checked with a child that writes a file after the timeout), or the timeout answer says the command may still be running · review w1118a.63: passed; seen in the owner's install (the claim commit landed 6 s after the timeout answer), the cause not read · Eternia's `QA-FU-A-QUEUE-CLAIM-TAKES-A-MINUTE-ON-WINDOWS` is the speed half and went to the Windows handoffs; this row is the half that loses work · architecture: `tools/environments/local.py` is an upstream file already in the fork's footprint ledger; fork-owned seams first — if the tree kill cannot reach a `dart` shim's children, the fork-side answer (the timeout reply says the command may still be running) is the one owner of what the agent is told · the done when's check (a child that writes a file after the timeout) runs on Linux too, so the lane runs it there first and the Windows read is REQUIRES windows · reviewed 2026-11-20 w1118a.63 · REQUIRES windows · READY 2026-11-20 · handoff 2026-11-20 (w1118a-hrt4): Linux half done and pinned: the done-when check runs on Linux and passes (a child, a grandchild, a setsid child and a backgrounded subshell of a command timed out after 2 s, none wrote its file after the 124 answer); `tests/tools/test_local_timeout_leaves_no_descendant.py` (895c398cce, landed 572ed14b60) is that check through the real local backend, red when `LocalEnvironment._kill_process` kills only the shell. Windows not read (this host has none): run that test on the Windows box (it is on Eternia QA-WINDOWS-CHECKS-OWED-4). If it is red there, the candidate read in code (not reproduced) is `_kill_process_windows` falling back to `proc.kill()`, the shell alone, when `terminate_pid`'s start-time guard refuses; else the tree kill not reaching a dart shim's children (guess). Nothing fork-side changed: with no survivor seen, a timeout reply saying the command may still be running would be untrue on Linux

## Filed on arrival — 2026-11-20 (Eternia lane mc-running-now: the hermes halves of `MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT`)


## Filed on arrival — 2026-11-20 (review w1118a.58: the hermes halves of Eternia's Running now and stopped-request rows)

- **`RT-FU-A-PLACED-INSTALL-LISTS-A-SECOND-UNMARKED-BASE` — A new chat in an install with the shipped agents placed offers a second plain "Base" beside the shipped "Base Agent"** · group: bundled-agents-stay-one-agent · from: Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` · seen live 2026-11-20 by w1120a-rtship (Eternia on Windows, account A, lane namespace with `place_shipped_agents`, hermes worktree at 5532ccaa34): Intelligence → New conversation listed "Base Agent" (Eternia mark), "Neko Mission Lead" (Eternia mark) and "Base" (no mark, a "…" menu instead of a chevron); `sort-shipped` answered `none` for both agents (no `fold`) and the agent store held only the two shipped references (`base`, `neko_supervisor`) · cause: guess — a row the directory builds from the `base` profile or a config-roster persona outside `AgentStore`, which the fold (`fold_discovered`) does not see; sibling: archived `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` · done when: a lane namespace with the shipped agents placed lists one Base in the New conversation picker · moved 2026-11-20 (review w1118a.61 D8): a second Base in the picker makes Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT`'s title ("agents that ship with Eternia appear once") false, so it is a defect in that task's own work, not a follow-up; regrouped from `runtime-followups` (the task row is TAKEN by DESKTOP-QJ7DDV2; no claim touched) · review w1118a.61: passed; seen on Windows only, so the lane reproduces it on Linux first and reads which source the third row comes from (the `base` profile or a config-roster persona) before changing anything · architecture: hermes' directory build and `fold_discovered` are the one owner of "these rows are one shipped agent"; Eternia adds no filter of its own · reviewed 2026-11-20 w1118a.61 · READY 2026-11-20

## Filed on arrival — 2026-11-20 (Eternia lane w1120a-unseated: agents a lead added that stood on no office level)


## Filed on arrival — 2026-11-20 (review w1118a.63: what hermes lane w1118a-hrt3 reported)


## Filed on arrival — 2026-11-20 (lane w1118a-hrt4: the live read of the built-in skill rule)


## Filed on arrival — 2026-11-20 (lane w1120a-slotrules: the shipped lead's prompt)
- **`RT-FU-THE-SHIPPED-MISSION-LEAD-READS-NO-REPOS-RULES` — The shipped Neko Mission Lead reads no repository's rules, because it sits in no workspace and so can have no folder checked** · group: runtime-followups · from: `MC-A-FOLDER-SLOT-CHOOSES-WHICH-RULES-FILE-ITS-AGENT-READS` (EterniaLauncher, lane w1120a-slotrules) · fork / `agent_runtime/persona_slots.py::set_instance_slots` (refuses `instance_has_no_workspace`) and `load_slot_context` (None without a workspace) · seen 2026-11-20 in the owner's namespace, read only: `personainst_neko_supervisor` has `workspace_id: null` and no slots; its turns in session `persona_chat_personainst_neko_supervisor_9f755a6523a9` (`agent-chat-send-b95368d0…` and `dispatch-delivery-dispatch-1c2022aca6b7`) carried SOUL.md, the operator-channel rules and profile memory only — `skip_context_files: true`, `workspace_agents_injected: false`, no `workspace_context_receipt` — while Neko Mission Lead Beta (`ws_testv4_afb811`, `eternialauncher` checked) carries `## eternialauncher — CLAUDE.md` with the `close_row.dart` rule · the shipped lead is the one whose brief said "delete the row" (EterniaLauncher `QA-FU-A-LEAD-AGENT-BRIEFS-HELPERS-AGAINST-THE-REPOS-OWN-RULES`) · done when: the shipped lead, given a repo folder the way the owner rules, has that repo's rules file in its prompt (shown from its context record); read live · review w1118a.66: passed; read in code — `agent_runtime/persona_slots.py::set_instance_slots` refuses `instance_has_no_workspace` and `load_slot_context` answers None for an instance with no workspace, so the seen prompt (no rules file for `personainst_neko_supervisor`, `workspace_id: null`) follows from the code · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.66 D4, answering the row's DECISION: (a) the shipped lead does repo work on its instance in a workspace, as Beta does, and that instance's folder slots carry the rules file — the owner already ruled that a new chat with an agent runs on its instance in the default workspace from Home and the current one inside Mission Control, "never on an unseated one" (Eternia `MC-OUTSIDE-NEW-CHAT-OPENS-ON-AN-UNSEATED-INSTANCE`, TAKEN on DESKTOP-QJ7DDV2 by w1120a-doorws), so a lead chat on the canonical channel with no workspace is the case that row removes; (b) the row's own recommendation, the unseated lead reading the active workspace's slots — a second slot path keyed on a UI notion hermes does not hold, kept alive for an instance the owner's ruling stops chats from landing on; recommended and taken: (a), changing the row's recommendation · what is left here: no hermes code is expected; once that Eternia row lands, a lane reads the lead's context record on a chat it opens and closes this row with that read, or writes what still drops the rules file · architecture: the slot owner and `load_slot_context` unchanged; the instance a chat runs on is the runtime's idle pick and placement, asked by Eternia's one New chat action · file map: none until the read; then `agent_runtime/persona_slots.py` only if a seated lead still loads nothing · reviewed 2026-11-20 w1118a.66 · READY 2026-11-21
- **`RT-FU-A-PROVIDERS-OWN-REFUSAL-CODE-INSIDE-ITS-ERROR-DETAILS-IS-DROPPED` — A provider's own reason for a refusal reaches Eternia, so a sign-in the provider does not allow is not told to sign in again** · group: runtime-followups · from: Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO` (review w1118a.67 D1) · seen live 2026-11-20 by Eternia lane w1118a-mcsonnet (Linux, account C, machine QA pool, hermes a973163fcc): Anthropic answered a Claude Sonnet 5.5 turn HTTP 403 `{"type":"error","error":{"type":"permission_error","message":"OAuth authentication is currently not allowed for this organization.","details":{"error_code":"oauth_not_allowed_for_organization"}}}` and the refusal block reached Eternia as `reason: permission_error`, `failure_reason: auth`, so Eternia told the person to sign in again · read in code: `agent/agent_runtime_helpers.py::extract_api_error_context` (upstream) keeps `error.code`, else `error.type`, as `reason` and never reads `error.details.error_code`; `agent/error_classifier.py::_status_403` falls to its auth default; `agent/provider_failure.py::provider_failure_block` (fork-only) copies `reason` from that context · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.67 D1: (a) hermes passes the provider's own most specific code — a nested `details.error_code` when the provider sends one — as the block's `reason`, and Eternia's one code table maps it; the classifier's kind and the pool's benching are unchanged (the credential cannot serve this organization either way); (b) a new `FailoverReason` in `agent/error_classifier.py` — an upstream edit for a fact the provider already names; (c) leave hermes and let Eternia read the message words — prose, which both sides refuse to classify; recommended and taken: (a) · architecture: fork seams first — `agent/provider_failure.py` is fork-only, but it is handed the context, not the body; the lane tries a fork-owned read of the nested code (e.g. what `attach_provider_failure` is handed at its one call in `agent/turn_api_error.py`) before any upstream line, and writes what it tried if `extract_api_error_context` must change · file map: `agent/provider_failure.py`, `agent/turn_api_error.py` (one seam line, if needed), `agent_runtime/provider_retry_wait.py` only if the retry-wait block must read the same, their tests · done when: a 403 with that body yields a refusal block whose `reason` is `oauth_not_allowed_for_organization`, pinned by a test on the body; a body with no nested code keeps today's `reason` · size XS · filed 2026-11-20 by review w1118a.67 · reviewed 2026-11-20 w1118a.67 · LIVE CHECK 2026-11-20: verify the provider refusal reason in the Linux account C copy · handoff 2026-11-20 (w1118a-codex-win-rt): Landed 9ef9e164fa. Recorded 403 now reports oauth_not_allowed_for_organization and still classifies as auth. Removing the turn detail-code read restored permission_error and failed the regression. 19 focused checks and prepush passed on Windows. Linux account C live read remains.
- **`RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT` — Your own presses in Eternia act as you, even after an agent's chat turn ran in the same runtime** · group: runtime-followups · from: Eternia `MC-FU-A-SECOND-INDEPENDENT-COPY-IS-REFUSED-AS-AN-EXHAUSTED-SPAWN-BUDGET` (review w1118a.67 D2) · seen live once 2026-11-20 by Eternia lane w1118a-mcsonnet (Linux, account C, hermes a973163fcc): Mission Control's Create independent copy of Base made a copy on its first press; a second press about 4 minutes later, after two chat turns had run in the same serve, was refused `spawn_scope_exhausted` · read in code, not reproduced: `agent_runtime/coordinator_permissions.py::review_coordinator_budget` answers every operator actor with `operator_bypass`, so the refusal means the press was judged as an agent; since 7d350bdaa9 (2026-11-20 14:31, inside a973163fcc) `persona instance create` takes its asker from `hermes_cli/harness_parts/persona/chat_coordinator.py::_coordinator_actor_id` → `lifecycle_commands.terminal_request_actor()` → `gateway.session_context.get_session_env("HERMES_SESSION_ID")`, which reads a bound session var or else the process environment, and `agent/agent_init.py` can set `os.environ["HERMES_SESSION_ID"]` for a turn · guess: a turn's session left in the serve's process state (environment or context var) makes the next command Eternia sends through the serve (`hermes_cli/harness_parts/serve/handle_message.py::_dispatch_argv_request`) look like that chat's agent, Base Agent copy, whose budget is 0; the retire and steer doors read the same asker · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.67 D2: (a) a command the serve runs for Eternia is the operator's: the serve's dispatch binds the session vars empty for each request it runs (`get_session_env` lets a bound empty value win over the environment), so only an agent's own terminal, whose subprocess carries its turn's `HERMES_SESSION_ID`, is judged as that agent; (b) Eternia passes `--requested-by operator` — by design an argv name never overrides the session; (c) stop `agent_init` writing the process environment — upstream, and other readers rely on it; recommended and taken: (a), the lane confirming first which of the two the serve leaks · architecture: fork seams only (the serve dispatch and `chat_coordinator`); `request_actor` stays the one owner of "who asked" · file map: `hermes_cli/harness_parts/serve/handle_message.py`, `hermes_cli/harness_parts/persona/chat_coordinator.py` only if the read must move, their tests (a turn run in the serve, then an operator create: operator) · done when: after a chat turn in the same serve, an operator `persona instance create`, retire and steer each act as the operator, pinned by a test that reds when the session leaks; an agent's terminal call is still judged as that agent · size S · filed 2026-11-20 by review w1118a.67 · reviewed 2026-11-20 w1118a.67 · READY 2026-11-20
- **`RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT` — A chat with an agent behaves the same wherever you open it: the same approvals, model choice, Stop, goal handling and background jobs in Mission Control's chat as in an Intelligence conversation** · group: one-hermes-one-path · from: architecture audit w1121a-archaudit, the class of `RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES` (two paths for one job) · read in code, not reproduced (2026-11-21): the serve hosts TWO turn engines. (A) the operator chat: `agent_runtime/mission_chat_door.py::run_mission_chat_turn` → `chat_turn_commit/` → `persona_runtime.py` → `profile_runner/runner.py` (line 411 builds `AIAgent` itself; a fork-built host with its own prewarm and send queue `chat_root_send_queue.py`). (B) Intelligence's independent conversations and profile-group discussions: `conversations/service.py::ConversationService` → `conversations/worker.py::start_worker`, one child `python -m agent_runtime.conversations.worker_entry` per served profile running upstream's `tui_gateway` engine with its own SessionDB, config, model catalog and credentials, spoken to over stdin/stdout (`native_peer.py`); the in-process twin `in_process_peer.py::start_in_process_worker` is chosen only when `conversations.subprocess_worker` is false (default true, false only in `bundle_profiles/bundled-phone.yaml`). Canon states the split as intended: `docs/agent-runtime-harness/05-chat-turn-lane.md` "Independent native conversations", `04-boot-and-lifecycle.md` "Native conversation workers" · read in code, not reproduced: each concern is answered twice — approvals (A: per-chat mode and notifier in `session_controls.py::session_approval_scope` / `_notify_root`, feeding the relay and the messaging cards; B: `tui_gateway/session_registry.py` `register_gateway_notify` plus `conversations/worker_permissions.py::turn_permission`), model (A: `persona_chat_session.py::_resolve_turn_model_selection`; B: `conversations/session_facts.py` and `model_preferences.py`), goal continuation (A: `work_store/goal_turns.py::after_turn`; B: `tui_gateway/prompt_turn.py`; upstream gateway: `gateway/run_goals.py` — three loops around one `GoalManager.evaluate_after_turn`), background-job completion (A: the serve's `dispatch_delivery` drain over the serve's process registry; B: `tui_gateway/session_notifications.py` inside the worker) · symptoms already paid, one side at a time: approval work landed on A only (d52fb4f795e6, e861255ed822, 1cf5edc9bb63) while B got its own permission fix (d81085f6d20b); `RT-NATIVE-WORKER-UPSTREAM-BOOT` (about 5 s before a native worker's first reply, a second engine import); `RT-NATIVE-CONVERSATION-RECOVERY` (the top repeat merge conflict); `RT-PHONE-DISCUSSION-SERVICE-NOT-BOUND-IN-THE-APP` · guess: an approval mode, speed control or off-desktop approval card set on a chat does not apply to the same agent's Intelligence conversation, and a goal that hits max iterations ends differently on each · architecture: one owner of "run a turn for this agent on this chat" inside the serve process — per the fork rule to adopt upstream's implementation, the upstream `tui_gateway` session engine run in-process (the phone already does this) with the persona and instance facts (model cascade, per-chat approval mode, steer, queue, live frames) supplied to it as policy, and `profile_runner`'s own `AIAgent` host, the per-profile worker processes and the duplicate goal loop retired; `RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES` then has one entry to call instead of choosing between two · weakness escalation per EterniaLauncher `docs/agent_context/WEAKNESS_ESCALATION.md` · done when: a turn started from Mission Control's chat and one started from an Intelligence conversation for the same agent run through the same function in the serve process, no `worker_entry` child is started on desktop, and one approval path, one model answer, one goal loop and one completion drain serve both; read live in both surfaces · RULED 2026-11-21: owner picked "One engine (Recommended)" — the operator chat and Intelligence conversations run on one turn engine inside the serve, the upstream engine in-process as on the phone, planned after the dispatch row · READY 2026-11-21 · unblocked 2026-11-21: `RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES` closed DONE 78859b4022 · handoff 2026-11-21 (w1118a-onepath-hm): w1118a-onepath-hm (woken by the dispatch close, not started): crash and hang isolation is answered once on RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES (in-process with cooperative limits; the decision applies here); suggested first slice toward "no worker_entry child on desktop": select agent_runtime/conversations/in_process_peer.py::start_in_process_worker on every profile (the phone path) and retire conversations.subprocess_worker, worker.py::start_worker's spawn and worker_entry.py; snapshot.subprocess_worker currently defaults to the conversations switch (ruling R8) and must default to a process on its own (owner 2026-11-21: the snapshot build stays a separate process); then fold the operator chat's profile_runner host onto the same engine per the RULED segment · handoff 2026-11-21 (w1118a-onepath-hm2): w1118a-onepath-hm2: slice 1 built, NOT landed. Branch lane/w1118a-onepath-hm2-engine (ba3b215854): select_worker_factory and ConversationService's default factory are the in-process worker on every profile, conversations.subprocess_worker retired, snapshot.subprocess_worker defaults on by itself (phone says off), canon 04/05 updated; mutations red. Merged with the stop work on lane/w1118a-onepath-hm2 (f798c583cb), where the real-worker tests are converted to canonical profile homes (the in-process worker serves a profile by name; a tmp_path home is refused conversation_owner_changed) and the subprocess modes dropped. Seen red there, each a real in-process difference to settle before landing: (1) test_native_conversation_compute_roundtrip / test_native_large_recovery[compute-child]: no tui_gateway.compute_host child appears with dashboard.turn_isolation in process — decide whether compute isolation is supported in process or dropped; worker_entry.stop_compute_host has no in-process twin, so a retired peer would leave a compute host running; (2) test_native_large_recovery[inline]: the conversation epoch is unchanged across a service close and reopen in one process (in_process_identity's generation), so a reopened route cannot tell a new execution from the old one; (3) test_subagent_spawning_native: the spawn pause (tools.delegate_tool_registry is_spawn_paused) is process-wide in process, so pausing one profile's worker pauses every agent in the serve; (4) test_discussion_runtime twelve same-profile instances hit sqlite 'database is locked' (seen once under load 30+; guess: contention now that every instance shares one process). Not read live: the Intelligence surface that reaches ConversationService is the discussion room (runtime.discussion.*), its QA path not yet found. Next: settle (1)-(4), land slice 1, live-read a discussion room on account C with no worker_entry child, then retire worker.start_worker/worker_entry.py and fold profile_runner's AIAgent host onto the engine per the RULED segment · handoff 2026-11-21 (w1118a-onepath-hm2): w1118a-onepath-hm2: slice 1 LANDED on main 7030105df1 (slice 9f588da9ba; earlier ba3b215854, f798c583cb): every profile serves conversations through the in-process tui_gateway worker; worker_entry.py, worker.start_worker and their tests retired; snapshot build stays its own process (snapshot.subprocess_worker on by default, phone off). The four in-process differences settled: (1) the last in-process worker to close stops the compute host (in_process_peer.stop_compute_host); (2) the replay epoch carries the serving worker generation (recovery_history._epoch / serving_worker); (3) spawn pause per profile via the eternia-harness pre_tool_call seam (spawning.spawn_pause_refusal), upstream global flag only with no bound profile; (4) "database is locked" is the room view writing receipts, not the engine: filed RT-FU-A-DISCUSSION-ROOM-VIEW-WRITES-RECEIPTS-AND-TIMES-OUT-UNDER-LOAD. Mutations red: epoch, stop never, stop on every close, global pause, serve env composer. Live read 2026-11-21 account C, QA copy on this tree: Intelligence group conversation (Base Agent + Neko Mission Lead, QA path intelligence.agents.conversations.open/.draft.agent/.group/.agent.<id>/.create, then set_text intelligence.agents.conversation.composer + .send) ran rounds with both members replying, and Mission Control chat for Base Agent replied in the same serve; ps showed no worker_entry child. Overrun filed FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET. NOT done: the fold. Operator chat still runs profile_runner's own AIAgent host (runner._default_agent_factory, execute.py 1091 lines, chat_root_send_queue) beside the tui_gateway engine, so done-when (same function, one approval path, one model answer, one goal loop, one completion drain) is unmet. Suggested order, each its own reviewable slice: F0 a plan under docs/agent-runtime-harness/planned/ mapping execute.py duties (budget, progress frames, tool payloads, redaction, model-input observability, tool blocks, chat-lane defer, MCP lane) onto tui_gateway session policy; F1 operator chat turn submitted to the in-process tui_gateway session for the persona's canonical home (prompt.submit) with model cascade from persona_chat_session supplied as session facts and per-chat approval mode feeding register_gateway_notify; F2 one goal loop: work_store/goal_turns.after_turn retired onto tui_gateway/prompt_turn's GoalManager path; F3 one completion drain: dispatch_delivery vs tui_gateway/session_notifications; F4 retire profile_runner's AIAgent host and the duplicate send queue. Claim released. · handoff 2026-11-21 (w1118a-onepath-fold): w1118a-onepath-fold: F0 plan landed, docs/agent-runtime-harness/planned/operator-chat-on-the-gateway-engine-2026-11-21.md — every execute.py duty mapped onto the in-process tui_gateway session through the two existing fork seams (worker_app_functions.create_agent at construction, bind/reset around each turn), so F1-F4 need no upstream edit; F1 next · handoff 2026-11-21 (w1118a-onepath-fold): w1118a-onepath-fold: F1 NOT built. Reading the gateway for F1 found three constraints, now in the plan's 'Read while starting F1' (read in code, not reproduced): (1) the operator transcript lives in the HEAD store (chat_turn_commit/run.py session_db), so the operator's gateway session must open on the serve's launch scope, not the persona's profile, and InProcessPeer needs a launch-scope mode; (2) prompt.submit writes the submitted text as a user row the agent adopts (_adopt_submit_user_row), so the operator's composed message, relay marker, MEDIA lines and replay (reuse_current_user_message) must move onto that row — RULED per the wave decision rule: resume the gateway session on the chat's native tip and adopt upstream's row; (3) chat_goal.arm keys GoalManager on the chat ROOT, and on a never-compressed chat root == gateway session key, so F1 alone runs two goal loops on one goal: F1 and F2 land together. Next: InProcessPeer launch-scope mode; operator construction via worker_app_functions.create_agent (source eternia_operator, AgentRunExecution.construct_agent); per-turn door wrapping agent.run_conversation with AgentRunExecution's phases (acquire replaced by the session's agent); chat-goal continuation onto prompt_turn's loop; switch the operator chat over with the ~104 test files migrated; then F3, F4 · handoff 2026-11-21 (w1118a-onepath-fold): F1-F3 LANDED c26be762ba (branch lane/w1118a-onepath-fold): a Mission Control chat turn runs on its own in-process gateway session (source eternia_operator, resumed on the chat tip in the store that holds it); the turn is an empty-text prompt.submit and the gateway's turn thread runs AgentRunExecution through a door on run_conversation (one transcript, agent writes the user row); the gateway judges a chat goal once and the settle reads its decision (EngineJudgedGoal); the engine's poller delivers completions for an open chat, the operator lane wakes a chat with no open session (queue + notification_park). Two additive upstream hunks ledgered (tui_gateway/agent_factory.py operator_agent seam, tui_gateway/prompt_turn.py first_contact_owned). Found and fixed: the gateway's import swapped sys.stdout for stderr in the serve (every reply line after the first in-process session became a stderr frame). Live read 2026-11-21 drive.dart account C session onepathfold: Base replied on the engine (tui prompt accepted chars=0 / turn finished complete), approval card shown and Allow once finished the turn (keyboard: QA-FU-A-CHATS-OWN-APPROVAL-CARD-HAS-NO-QA-CONTROL), Stop ended a held turn in 7 s (Reply stopped), a goal armed in the store ran 3 turns with 3 judges, 2 continuations and 2 engine follow-ups that ran nothing, then paused at max_turns; discussion room Base+Neko both replied; ps: the serve and its snapshot worker only. F4 HELD (owner decision, plan section Built on the branch, item 7): chat_root_send_queue/runner is the durable admission ahead of an engine whose queue is in memory, so retiring it means a boot replay over the journal, the same durable queue under another name; execute.py and _default_agent_factory run inside the engine's turn through the door and moving them into bind/reset changes no engine (RECOMMENDED keep). The transcript choice (empty submit, not the adopted gateway row) is RECOMMENDED, awaiting the owner. · **TAKEN 2026-11-21 w1118a-onepath-fold on nekwo-ubuntu24 as nekwo in w1118a-hmG**
- **`RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS` — A helper a lead sends work to is not stopped by an approval nobody saw in its first minute** · group: runtime-followups · from: the owner's Neko live test, pass 5 of Eternia `MC-FU-THE-CONSOLE-TOP-BAR-PICTURE-TEST-IS-RED-ON-MAIN` · seen 2026-11-21 (owner namespace, read only): the helper (profile `launcher-dev`, `approvals: mode: manual, timeout: 60`) had its one probe command held by the risky-command check, nobody answered in 60 s, it expired, the pass ended with nothing run; the same ended pass 1; the lead (Neko) runs `smart` and would have passed it · the owner asked for auto approval ("auto aproval right there is arow for it?"), which exists per chat (Ask / Smart / Off) but nothing sets it for a dispatched helper, and a manual 60 s wait suits a person watching, not a helper the owner never opens · related: `RT-FU-A-HELPER-GIVES-UP-ITS-ROW-AFTER-ONE-UNANSWERED-STEP` (carries on after an unanswered step), Eternia `MC-A-HELPERS-APPROVAL-NEVER-REACHES-THE-LEADS-CHAT` (closed: the card shows in the lead's chat) · done when: a helper dispatched by a smart lead runs a risky-looking read-only probe without a card, a manual lead's helper waits on the card in the lead's chat past 60 s and runs once approved, pinned by tests and read live through a real dispatch · DECISION 2026-11-21: what governs a dispatched helper's approvals — (1) the dispatching lead's mode (a smart lead's helper runs smart; a manual lead's card waits in the lead's chat until answered, no 60 s expiry); (2) shipped and new profiles default to smart; (3) leave it per profile and only stretch the timeout for dispatched turns · Recommend: (1), the helper acts for the lead, and the card already shows in the lead's chat; hardline and deny rules still apply


## Filed on arrival — 2026-11-21 (lane w1118a-sw71-hm: what the discussion-view fix left)


## Filed on arrival — 2026-11-21 (Eternia lane w1118a-sw71-el: the realm banner and the composer refusal line)


## Filed on arrival — 2026-11-21 (lane w1118a-onepath-el2: the hermes half of Eternia MC-ONE-DOOR-PLACES-AN-AGENT-FROM-EVERY-SURFACE)
- **`RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT` — Placing or copying an agent has one door in the runtime, so a second seat or a copy behaves the same whoever asks** · group: one-hermes-one-path · from: Eternia `MC-ONE-DOOR-PLACES-AN-AGENT-FROM-EVERY-SURFACE` (its architecture: hermes retires `runtime.persona.instance.create` and the `--add-instance` argv doors as placing doors, a hermes row filed when that row is built) · read in code 2026-11-21 (lane w1118a-onepath-el2): Eternia 89bb9c84fdd has no caller of `runtime.persona.instance.create` or of the `add_instance` / `independent_agent` keys any more (every surface creates through `runtime.agent.create` and places through `runtime.agent.place`), but the runtime still answers both on `runtime.persona.instance.create` (`agent_runtime/serve_rpc/chat_verbs.py`) and on the `harness persona instance create --add-instance / --independent-agent` argv; `RT-ONE-CREATE-VERB-MAKES-AN-AGENT-WITH-OR-WITHOUT-A-WORKSPACE` deferred the `independent_agent` refusal until Eternia converted · architecture: `runtime.persona.instance.create` refuses `add_instance` and `independent_agent`, naming `runtime.agent.place` / `runtime.agent.create` (or the verb retires if no other caller is found), and the argv flags retire with it; no new verb · done when: a create on `runtime.persona.instance.create` with either key is refused naming the door to use, and Eternia's office drop, Place, chat Add instance and Agents-card create/copy still work, read live · filed 2026-11-21 by lane w1118a-onepath-el2 (awaits a review batch) · review w1118a.74: passed with a rewrite; premise confirmed in code: Eternia main has no sender of `runtime.persona.instance.create` or of `add_instance` / `independent_agent` (only comments in `mission_open_chat_lowering.dart`); hermes still answers both on `chat_verbs/instance_create.py` (twin params `serve_rpc/twin_params.py:58`) · found while testing: there are THREE placing doors outside `agent_create/perform.py`, not two — `PersonaInstanceStore().add_instance` is also called by the open-chat argv `--add-instance` (`hermes_cli/harness_parts/persona/chat_open.py:166`) besides `lifecycle_commands.py:306`, and `--independent-agent` reaches `create_independent_agent` through `lifecycle_commands.py::_create_independent_instance` · architecture: `agent_create/perform.py` is the one owner of making and placing an agent; `runtime.persona.instance.create` refuses `add_instance` / `independent_agent` naming `runtime.agent.place` / `runtime.agent.create` (or retires if nothing else calls it), and the three argv doors lower to that service or retire; no new verb · security: fewer doors that can mint an instance past the create's reservation and name lock · file map: `chat_verbs/instance_create.py`, `serve_rpc/twin_params.py`, `hermes_cli/harness_parts/persona/chat_open.py`, `lifecycle_commands.py`, `parser/persona.py` + tests · same-file sweep: `RT-A-PERSONA-CHAT-CAN-BE-ARCHIVED-FROM-ETERNIA` (`chat_verbs.py`, the manifest) and `RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT` (`lifecycle_commands.py`, the same `persona instance create`), one lane · size S · reviewed 2026-11-21 w1118a.74 · READY 2026-11-21

## Filed on arrival — 2026-11-21 (Eternia lane w1118a-sw73-mc: the realm banner's kinds, read live)

- **`RT-FU-A-REALM-PULL-PREVIEW-COUNTS-THE-REALM-MANIFEST-AS-AN-ARTIFACT` — A realm's update banner names only the shared things a pull changes, not the realm's own bookkeeping file** · group: runtime-followups · from: Eternia `MC-FU-A-REALM-UPDATE-BANNER-NAMES-WHAT-A-PULL-WOULD-CHANGE` (lane w1118a-sw73-mc, which prints hermes's `incoming_artifact_counts` in the banner) · seen live 2026-11-21 (Linux Xvfb, account B, QA Realm, lane namespace `stagec-smoke-2-lane-8e32104a2a`, hermes 00a1d4b41e from a worktree): with the lane's clone reset locally behind a commit range whose net realm change was one workspace file and `manifest.json`, the banner read "1 artifact, 1 workspace" · read in code: `agent_runtime/realm_sync/status.py::_incoming_artifact_counts` classifies every changed realm path with `families._kind_for_sync_path`, whose fallback is `SyncFamily.ARTIFACT`; the realm's own `manifest.json` matches no family, and every publish rewrites it, so nearly every pull will name "1 artifact" beside the real kinds · guess: the manifest (and any other realm bookkeeping path) should be left out of the incoming counts, as `artifact_counts` presumably does for the whole-realm stock; not checked · done when: a realm behind by a publish that changed one workspace answers `{workspace: 1}` with no `artifact` entry, pinned by a test that goes red with the manifest counted · file map: `agent_runtime/realm_sync/status.py` (+ `families.py` if the exclusion belongs in the path table) + `tests/agent_runtime/test_realm_status_incoming_counts.py` · size XS · filed 2026-11-21 by lane w1118a-sw73-mc (awaits a review batch) · review w1118a.74: passed with a rewrite; premise confirmed in code: `status.py::_incoming_artifact_counts` classifies every changed realm path with `families._kind_for_sync_path`, whose fallback is `SyncFamily.ARTIFACT`, and `manifest.json` matches no family; the row's guess is answered: four other readers already leave the file out, each with its own inline `!= "manifest.json"` (`realm_sync/history.py:125`, `persona_artifacts.py:502`, `publish.py:220` and `:701`) · architecture: one fact, one place — `families.py` (the path table) owns "realm bookkeeping, not an artifact" as one predicate; `_incoming_artifact_counts` and the four inline checks read it; no change to what the other four count · security: counts only, the remote's paths still never leave the function · done when: as written · file map: `realm_sync/families.py`, `status.py`, `history.py`, `persona_artifacts.py`, `publish.py` + `tests/agent_runtime/test_realm_status_incoming_counts.py` · same-file sweep: no other open runtime row on these files · size XS · reviewed 2026-11-21 w1118a.74 · READY 2026-11-21 · **TAKEN 2026-11-21 w1118a-sw74-hm on nekwo-ubuntu24 as nekwo in rev70-hm**
