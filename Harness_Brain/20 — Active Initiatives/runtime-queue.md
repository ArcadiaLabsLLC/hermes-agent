---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue





## Shipped agents stay one agent — 2026-11-19 (owner; task row in Eternia `mission-control-queue`)

- **`RT-SHIPPED-AGENTS-CODE-TRIPS-THE-NAME-CENSUS` — The shipped-agents code on main fails the two name census gates every lane runs** · group: bundled-agents-stay-one-agent · seen 2026-11-19 (lane bundled-realm, `tests/agent_runtime/test_duplicate_helper_bodies.py` and `tests/tooling/test_no_ladder_routing.py` every name is on main 2043a9e0a1; this lane adds none): W0-G3 NEW `_copy` (`bundled_agents/sort_existing.py`, `namespace_seed/seed.py`), `_entry` (`sort_existing.py`, `mission_chat_clarify.py`), `_line` (`text_summary.py`, `hermes_cli/harness_parts/persona/shipped_commands.py`), `_plain` (`bundled_agents/resolve.py`, `persona_config_sync.py`), `_source` (`agent_duplicate.py`, `running_work/rows.py`), `_stage_profile` (`agent_duplicate.py`, `persona_assignments/independent.py`); W0-G5 NEW ladder `sort_existing.py|apply_sort|ladder|action` · done when: both gates pass with the helpers renamed or folded and `apply_sort` dispatching through a table · review w1118a.40 D9: passed — a defect in this task's own shipped-agents code, so not a reds-on-main row: the task's lane renames or folds the six helpers by their one owner and gives `apply_sort` a dispatch table, never a waiver; rejected: a waiver line (the census exists to refuse one) · reviewed 2026-11-19 w1118a.40 · READY 2026-11-19


## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)


- **`TASK-AGENT-CONFIG-CLEANUP` — Agent settings: each agent's folders, data, options and abilities live in one clear place** · task: agent-config-cleanup · 1 subtask open on 2026-11-19 (Eternia `MC-OWNER-NAMESPACES-ADOPT`; the other 9 are closed in the archives, the five hermes RT rows on 2026-11-15) · RULED 2026-11-19: owner said "same thing with this undefer it and see if its stale" (the same thing = "undefer it and have an aggent see and fix if need be") · checked 2026-11-19 (w1118a-hcfg): nothing stale was left to close — the five hermes subtasks (`RT-DELEGATION-KNOB-ENV-DEAD`, `RT-NAMESPACE-ADOPT`, `RT-ROOT-CONFIG-MISPLACEMENT-CURE`, `RT-MACHINE-ROOTS-FOLD-BREAKING`, `RT-READ-MODEL-RESIDUE-NEXT-BUMP`) were already archived CLOSED on owner words 2026-11-15; the one open subtask is real and is only the owner's own sitting on the Windows PC · BLOCKED 2026-11-19: launcher — `MC-OWNER-NAMESPACES-ADOPT` waits on the owner sitting at the Windows PC to pick the Agent data folder in Settings · was DEFERRED 2026-11-16: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` closed as churn (owner 2026-11-16 — "Close as churn"); the one subtask left, Eternia `MC-OWNER-NAMESPACES-ADOPT`, was DEFERRED by the owner (2026-11-09) · unblocked 2026-11-15: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` woken READY by w1115e-rr2 (deep sweep 2026-11-15 §D) · waits: `MC-OWNER-NAMESPACES-ADOPT`
- **`TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` — Agent engine follow-ups: the engine's own checks pass on main again after a lane broke them** · task: engine-suite-green-followups · review w1118a.40 closed bundled-realm's `FH-REALM-TESTS-HANG-ON-A-LOCAL-GIT-REMOTE` (D10: reds on main are not rows) · 3 open subtasks on 2026-11-15 (1 ready: FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY; 2 NEEDS PLAN filed by w1115c-h2 and waiting on a review batch: RT-RUNNING-TURN-START-ROW-WAITS-OUT-THE-DEMOTE-HOLD, RT-RUNNING-TURN-START-NEVER-PUBLISHED-ONCE-UNDER-LOAD; FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD closed DONE 36a1e1d45c and FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD closed DONE c157f48749 by w1115c-h2; FH-GAME-WATCH-TEST-READS-THE-MACHINES-REAL-PROCESSES and FH-BUNDLE-SERVE-PROBE-REPORT-LOST-TO-STDERR-ON-LINUX closed by other w1115c lanes; FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN closed DONE e64d77c9f6 by w1114a-h5 through fork seams) · filed 2026-11-14 by the w1114a.30 queue pass (REVIEW_W1114A_B29), for reds met on hermes main — the twin of Eternia's architecture-gate-green-followups · was DONE 2026-11-15 0495762a2e (all 1 subtasks closed) · reopened 2026-11-15 (review batches w1114a.40 and w1114a.42, REVIEW_W1114A_B39/B41): FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD moved in from the DEFERRED TASK-UPSTREAM-LOAD-FLAKES and FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN from the DEFERRED TASK-HERMES-TEST-ISOLATION · handoff 2026-11-15 (w1114a-h4): FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN reproduced and its fixture fixes written, but they edit three upstream test files (upstream footprint 224->226), so it waits on an owner ruling (DECISION); claim released · BLOCKED 2026-11-19: another lane — `FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-RUNTIME-FOLLOWUPS` — Agent runtime: what the tasks behind this queue's rows found on the way gets fixed after them** · task: runtime-followups · after w1118a-hfu3 (2) 2026-11-20: closed DONE `RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE` 7fc184a5f2 (review w1118a.53 D10: one check, `persona_lifecycle.is_agent_copy`, serves the template skip and the copy delete; read live in Eternia on Linux, account C: Presets 2 with a duplicate made, which Delete agent then removed); one subtask fewer than the counts that follow · after w1118a-hfu3 2026-11-19: closed DONE `RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE` 5fa36a548f (an independent copy's own profile is no profile template, judged by the persona record; read live in Eternia on Linux, account C: Presets 2 before and 2 with a copy made, Roster and Local 3; wakes Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`, closed DONE with it) and `RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING` 4260057ce0 (a drained serve joins its settle pusher, delivery drain and queued-send dispatcher, the upstream adapter shim shuts its loop's default executor down, a conftest stops the build sweep; `tests/agent_runtime/messaging/` sealed); filed `RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE` (read in code; waits for a review batch); one subtask fewer than the counts that follow · after w1118a-hgroup 2026-11-19: closed DONE `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` 168017b784 (a group chat of agents that each have their own profile answers every member's turn; read live through a real `harness serve` and in Eternia on Linux) and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (read live in Eternia's tool console: row, summary and fix); two subtasks fewer than the counts that follow · review w1118a.51 2026-11-19: passed `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` (D12, fork fixture) and `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` (D14, not an edge: the owner's board path), both READY; closed `RT-TWO-PLACEMENTS-AT-ONCE-CAN-GIVE-ONE-AGENT-THE-SAME-NUMBER` (D10) and `RT-AN-AGENTS-DONE-UNDER-A-PARKED-TASK-CLOSES-WHERE-A-LANES-CLOSE-IS-REFUSED` (D13) as edge cases and `RT-OWNERS-OLD-NEKO-MEMORY-STAYS-IN-THE-TEAM-REPO` (D11) on the ruling; three subtasks fewer than the counts that follow · after w1118a-hwork 2026-11-19: closed DONE `RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE` 92d350be97 (a close from Eternia's board, an agent's done and the engine's done now wake the rows waiting on the row and step its task, as a lane's close does; read live on Linux through a real `harness serve` on a sandbox brain: the owner's close woke the waiting subtask and turned the task READY, the agent's done of the last subtask archived the task) and filed `RT-AN-AGENTS-DONE-UNDER-A-PARKED-TASK-CLOSES-WHERE-A-LANES-CLOSE-IS-REFUSED` and `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` (read in code; edges; wait for a review batch); one subtask more than the counts that follow · after w1118a-hfu2 2026-11-19: closed DONE `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` fcdb0a5818 (a close from Eternia's board in a launcher- or backend-brain slot reads hermes's brain beside the checkout and archives the task when its last subtask closes; read live on Linux through a real `harness serve` on a sandbox launcher-brain slot: the owner's close of the last subtask archived the task, and with hermes's brain absent it stayed open) and `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` c0718e44de (a messaging-folder fixture writes runtime status with no thread); filed `RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING` (seen; waits for a review batch); one subtask fewer than the counts that follow · after w1118a-hfu 2026-11-19: closed DONE `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` f16d71a002 (a duplicate of an agent on the main profile keeps the head home's model and none of its files; read live on Linux through a real `harness serve`: the copy's one real turn reached the source's endpoint) and `RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER` 3c21e4805c (the suite runs the Telegram live check against the stand-in); filed `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` (seen; waits for a review batch); one subtask fewer than the counts that follow · review w1118a.50 filed and passed `RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE` from Eternia `MC-SYNC-PULL-UNDOES-A-LOCAL-RENAME-MADE-SINCE-THE-LAST-PUBLISH` (READY, D7: the workspace and realm records' pull merges against a baseline); one subtask more than the counts that follow · review w1118a.48 passed hknobs' `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (READY; D5: the second is a read the first's lane makes), hendpoint's `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` (READY, D6; since closed DONE f16d71a002) and htele's `RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER` (READY, D8; since closed DONE 3c21e4805c), filed and passed `RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE` from Eternia `MC-SUBTASK-HOLD-TO-ARCHIVE` (READY, D1b; Eternia's row since closed DONE 8810835e31f), and closed hdelete's `RT-A-COPY-DUPLICATED-BEFORE-THE-DELETE-DOOR-KEEPS-ITS-PROFILE` as an edge case (D7, on Eternia's sweep list); net unchanged against the counts that follow · after w1118a-hdelete 2026-11-19: closed DONE `RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED` a2555090c4 (`runtime.agent.delete` deletes a copy you made in one step; read live on Linux through a real `harness serve`: after a retire the directory already drops the instance but the roster keeps the copy, after the delete neither lists it; wakes Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST`) and filed `RT-A-COPY-DUPLICATED-BEFORE-THE-DELETE-DOOR-KEEPS-ITS-PROFILE` (read in code; an edge; waits for a review batch); net subtask count unchanged · after w1118a-hendpoint 2026-11-19: closed DONE `RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT` 57facbaba6 (a copy and a duplicate keep the source's model endpoint and no credential; read live on Linux: a fresh copy of Base answered its first message; wakes Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE`) and filed `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` (seen in a unit test; since closed DONE f16d71a002); no net change in subtask count · review w1118a.47 filed and passed `RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED` from Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST` (READY, D5: one door deletes an independent copy; Eternia's row waits on it); one subtask more than the counts that follow · review w1118a.46 passed hphantom's `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` (READY, D3: one list of root-only keys, one typed issue per profile copy) and bundled-facts' `RT-GROUP-CHAT-NEVER-FINISHES-ENDING-AFTER-ITS-PROCESS-STOPPED-MID-TURN` (READY, D9: premise first through a real serve restart), and filed and passed `RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT` from Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE` (READY, D2: a copy carries its source's model endpoint, never a credential); one subtask more than the counts that follow · after w1118a-hknobs 2026-11-19: closed DONE `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` 16f69d75f9 (a profile-config copy of a root-only setting is one typed issue on the agent's declaration naming the root; read live on Linux through a real `harness serve`) and REFUTED `RT-GROUP-CHAT-NEVER-FINISHES-ENDING-AFTER-ITS-PROCESS-STOPPED-MID-TURN` (a real serve restart, SIGTERM or SIGKILL, ends the room); filed `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` (seen) and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (live check), both waiting for a review batch; net subtask count unchanged · after w1118a-hphantom 2026-11-19: closed DONE `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` 6a913f1568 (a config entry declares an agent only with an identity key; a settings-only entry lists nothing, its knob still read by id; read live on Linux through a real `harness serve`) and filed `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` (read in code; waits for a review batch); net subtask count unchanged · after w1118a-hbase 2026-11-19: closed DONE `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` d28f26e14d (a placed shipped agent folds the unedited discovered persona on its profile; read live on Linux: one Base Agent plus Neko in Agents and `runtime.agent.directory`, and Base copies; wakes Eternia `MC-AGENTS-LISTS-A-PROFILE-ROW-INSTEAD-OF-THE-SHIPPED-AGENTS`) and filed `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` (seen on disk; waits for a review batch); net one subtask fewer and one more than the counts that follow · after w1118a-hscope 2026-11-19: closed DONE `RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT` 6d13964e96 (the instance verb takes `client_scope` / `--client-scope`, stamps it on all three mints and echoes it; read live on Linux through a real `harness serve`; wakes Eternia `MC-INDEPENDENT-COPY-CHAT-NOT-LINKED-TO-YOUR-ACCOUNT`, since closed DONE in Eternia 52e563fd665, w1118a-mcscope); one subtask fewer than the counts that follow · review w1118a.44 passed mccopy's `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` (READY, D4: not an edge case — a realm pull places the shipped Base beside a discovered one; the fold goes in `place_shipped`) and filed and passed `RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT` (READY, D3, security: the instance verb takes the account scope); mccopy's row was in no count, so two subtasks more than the counts that follow · after w1118a-hrealm7 2026-11-19: closed DONE `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED` 61a0d8c186 and design-fix `RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE` e357b28aba (both read live on Linux in QA Realm; the second wakes Eternia `MC-PHONE-REALM-REVERT-SAYS-RESTORED-BUT-THE-CHANGE-STAYS`, since closed DONE d07b7bca00, relayed by review w1118a.44); filed `RT-REALM-DESK-FILE-REMOVED-BY-HAND-LEAVES-A-PUBLISH-THAT-DROPS-THE-AGENT` (seen in a test; not seen live — the by-hand pull read nothing to publish), since closed by the owner; net two subtasks fewer than the counts that follow · after w1118a-hname 2026-11-19: closed DONE `RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER` 1738e2ecae (a nameless create is refused `agent_name_required`, a taken name `agent_name_taken`; read live on Linux; wakes Eternia `MC-NEW-AGENT-WITHOUT-A-NAME-IS-ASKED-FOR-ONE`, since closed DONE 159a1f050a, relayed by review w1118a.43); one subtask fewer than the counts that follow · review w1118a.41 moved `RT-PAIRED-PHONE-CAN-STEER-A-CHAT-IT-MAY-NOT-SEND-TO` to Eternia as `MC-CONSOLE-SLASH-STEER-GOES-WITHOUT-THE-ACCOUNT-SCOPE` (D7: hermes already checks both verbs; Eternia's slash steer sends no scope), closed hrealm7's `RT-REALM-DESK-FILE-REMOVED-BY-HAND-LEAVES-A-PUBLISH-THAT-DROPS-THE-AGENT` as an edge case (D9: only a hand-edited realm) and passed bundled-place's `RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER` (READY, D8: a nameless create is refused, as the design's section 4 rules); two subtasks fewer than the counts that follow · review w1118a.40 filed and passed the design-fix row `RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE` (READY, D11: every operation that adopts the team's copy settles the baseline the drift walk reads, in its own scope) and folded into it qafu18's `RT-REALM-PULL-OF-A-NET-ZERO-DESK-DELETE-LEAVES-OFFICE-LAYOUT-CHANGED` and hrealm6's `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-DRAWING` (both closed), and passed hrealm6's `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED` (READY, D17: a pull that ends a hold clears its sidecar); one subtask fewer than the counts that follow (the design row in, the two folded rows out) · after w1118a-hrealm6 2026-11-19: closed DONE `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` cae912bae4 and `RT-OFFICE-HELD-DESK-SAYS-WHAT-THE-TEAMMATE-DID` 4468dd0c4d (both read live on Linux in QA Realm; the second woke Eternia `MC-OFFICE-DESK-CONFLICT-DIALOG-SAYS-MOVED-WHEN-THE-TEAMMATE-DELETED`, since closed DONE f0918262c7, relayed by review w1118a.42); filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-DRAWING` and `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED`, both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.39 filed and passed `RT-OFFICE-HELD-DESK-SAYS-WHAT-THE-TEAMMATE-DID` (READY, D8: the office snapshot names each held desk's team side, for Eternia's conflict dialog) and regrouped bundled-runtime's `RT-SHIPPED-AGENT-SEAT-EDIT-COUNTS-AS-A-CHANGE` into `bundled-agents-stay-one-agent` (D9, a defect in that task's own work; never counted here); one subtask more than the counts that follow · review w1118a.38 passed with corrections `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` (READY, D5: taking the team's copy settles the realm's office baseline through the office pull's own settling) and closed `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` as an edge case (D6, on Eternia's sweep list); net one subtask fewer than the counts that follow · after w1118a-hrealm5 2026-11-19: closed DONE dee4e42839 `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (both read live), and design-fix `TASK-REALM-DELETE-MEETS-AN-EDIT` closed with both its subtasks; filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` and `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` (an edge), both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.36 passed with corrections hbundle's `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` (READY: one owner of the push-refused tells, `cannot lock ref` added; a repeat of archived `RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE`) and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (READY: publish writes only what the content compare says changed), and moved `RT-PHONE-REALM-CONFLICT-HAS-NO-WAY-OUT` and `RT-REALM-LOCAL-EDIT-OUTLIVES-A-TEAMMATES-DELETE` out to design-fix task `TASK-REALM-DELETE-MEETS-AN-EDIT` (one gap: no rule for a delete meeting an edit); net two subtasks more and two fewer than the counts that follow · review w1118a.31 corrected the hsurf segment below: the Eternia Home row it woke is closed, not open (DONE a8c7bead20), and so is `TASK-HOME-SHELL-FOLLOWUPS-3` (099dc3c1bd) · review w1118a.30 closed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` as an edge case (D6) and filed and closed `RT-SURFACE-NOTE-RESENT-EVERY-TURN-IN-MOA-AND-CODEX-MODES` as an edge case (D7), both on Eternia's sweep list (one root: what the model was last told is read from the transcript); net one subtask fewer than the counts that follow · after w1118a-hsurf 2026-11-19: closed DONE `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` 7787bd8a8f (a changed surface prompt rides the turn's tail; the stored prompt stays byte-identical), which wakes Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` for its live read (since closed DONE in Eternia a8c7bead20, w1118a-home4; Eternia `TASK-HOME-SHELL-FOLLOWUPS-3` closed DONE 099dc3c1bd); filed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` (an edge, waits for a review batch) · was: review w1118a.29 filed and passed `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` (ready; one subtask more than the counts that follow) · after w1118a-folderedit 2026-11-19: closed DONE `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED` fff568201e, read live in Eternia before and after on fresh lane namespaces (the folder is saved, no sync banner) · was: review w1118a.23 moved w1118a-hrealm's two realm rows (the persona-api-mode one, since closed DONE 68a504deb7, and `RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK`) out to `TASK-REALM-MEMBERS-SEE-WHAT-THE-OWNER-SHARES`; the counts that follow never held them · 5 subtasks open on 2026-11-19 after w1118a-hprov (closed DONE: the catalog's sign-in field 2e5f209c5d, which woke Eternia `MC-FU-COMPOSER-SILENT-WHEN-THE-CHATS-PROVIDER-IS-SIGNED-OUT` (since closed DONE in Eternia 9f1bb6eccd, w1118a-mcfu8); the phone readiness row cc78fac067, read first on a phone bundle; closed as churn on review w1118a.21 D6: the fresh Default office row, read on a desktop serve — the one effect found filed as `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED`, passed by review w1118a.22, since closed DONE; the other four wait on the owner) · was: review w1118a.21 filed and passed the sign-in-field and phone-readiness rows and rewrote the fresh-office row (w1118a-hphone2) · 6 subtasks open on 2026-11-19 after w1118a-hphone2 (filed `RT-FRESH-ENGINE-DEFAULT-WORKSPACE-HAS-NO-OFFICE`, waits for a review batch; the phone row the duplicate below merged onto, `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER`, closed DONE 82d80229be in `TASK-PHONE-HARNESS`) · was 5 subtasks open on 2026-11-19 after w1118a-rtfu2 (closed DONE: `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` efc2140d79, `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` 69aab89b99, `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` 4d43a3036c read live on a real model; filed `RT-PHONE-CHAT-TURN-HAS-NO-HARNESS-PARSER`, which review w1118a.19 closed as a duplicate of `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER` (merged onto that row); the other four wait on the owner: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` blocked, three deferred) · was 8 subtasks open on 2026-11-19 after w1118a-realm2 (`RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` closed DONE afb168e807, read live on two Eternia QA copies; `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` also read right in Eternia's realm sheet: two new namespaces' first pulls read In sync with nothing to publish) · was review w1118a.16 (Eternia review batch): passed `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` (both ready), closed `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` (a red on main is not a row — owner 2026-11-15) · 9 subtasks open on 2026-11-19 after w1118a-rtfu (closed DONE: `RT-READ-ONLY-TREE-REMOVAL-COPIED-THREE-TIMES` 2967e07ab1, `RT-PHONE-BUILD-STALE-SEED-BLAMES-AN-EXTRA` d197d1c389, `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` 34e21dbfe8; filed `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER`, waits for a review batch; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` waits on a real-model sitting and `RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` on an Eternia QA read, each with a handoff; `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` filed by w1118a-hphone wait for review) · was 9 subtasks open on 2026-11-19 after w1118a-hbundle3 (`RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` closed DONE d5012e054b: 18.86 -> 15.66 MiB arm64, the limit re-based by ruling, Eternia's edit) · was 11 subtasks open on 2026-11-19 after w1118a-hbundle (`RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED` closed DONE 75c5913569; `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` stays READY with a handoff — 28.80 -> 23.30 MiB landed 5febe61183, gap per part on the row; `RT-DESKTOP-BUNDLE-VERIFY-REFUSES-THE-DULWICH-REALM-SYNC` closed DONE 9962731e85 (w1118a-hbundle)) · was 11 subtasks open on 2026-11-19 after review w1118a.10 (6 ready, 1 live check, 1 blocked, 3 deferred; the review passed `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` and filed `RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED`, from Eternia `TASK-DISTRIBUTION-FOLLOWUPS`) · was 9 subtasks open on 2026-11-19 after review w1118a.8 (4 ready, 1 live check, 1 blocked, 3 deferred; `RT-PHONE-ANDROID-TLS-IGNORES-DEVICE-CERTIFICATES` closed as a documented edge case on the owner's standing call) · was, on 2026-11-17 after w1116b-rtfu: `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, `RT-CLOSE-NAMES-SIBLING-TASK-LINES-THAT-STILL-MENTION-THE-ROW` and `RT-REALM-OWNER-RECORD-LISTS-A-WORKSPACE-IT-DELETED` closed DONE; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` stays READY for its real-model live re-run only; `RT-SKILL-NAME-READ-TWO-WAYS` filed, waits for a review batch; was 5 subtasks open on 2026-11-16 after w1115e-q4 (2 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`; 1 blocked on an owner sitting; 2 deferred; closed since: `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM` DONE, `RT-LENS-RECIPE-HISTORY-AND-COUNTS-NOT-BUILT` as a documented edge, owner 2026-11-16 "sounds good" on review w1115e.19); was 7 subtasks open on 2026-11-16 after owner "Accept all" on B68 (4 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, and the two narrow realm-sync fixes `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM`; 1 blocked on an owner sitting: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH`; 2 deferred: `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR`, `RT-SCHEDULE-SYNC-AND-KNOB-2`; closed: `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS` and `RT-WORK-READS-MIX-ROWS-AND-HISTORY-FROM-TWO-COMMITS` as edges, `RT-READY-FRAME-SHELL-KEY-DOCUMENTED-NEVER-SENT` folded; each keeps its own status; its `from:` segment names the task it came from); was "7 subtasks open on 2026-11-15" · opened 2026-11-15 by w1115e-rr3 as this queue's one standing follow-ups task (owner 2026-11-15: "yea do the cleanup"; a follow-up goes here, not under a per-task `-FOLLOWUPS` task): received `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF-FOLLOWUPS` (2), `TASK-SHARED-WORK-V1-FOLLOWUPS` (1), `TASK-ONE-TURN-RECORD-FOLLOWUPS` (1), and the hermes rows of Eternia `TASK-PHONE-HARNESS-FOLLOWUPS` (1) and `TASK-CONSOLE-TOP-BAR-AND-MENU-PROPOSAL-FOLLOWUPS-2` (1) and backend `TASK-WORKSPACE-ABSORBS-PROJECTS-FOLLOWUPS-2` (1); `TASK-ETERNIA-LENS-FOLLOWUPS-2`'s 5 rows are Eternia's, now under Eternia `TASK-MISSION-CONTROL-FOLLOWUPS`; `TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` stays (its one row is a security row), each closed as merged · READY 2026-11-19 · unblocked 2026-11-19: `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` closed DONE 6a913f1568 · triage 2026-11-19 (w1118a-triH): owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — closed `RT-SKILL-NAME-READ-TWO-WAYS` as churn ("check for churn too"); `RT-SCHEDULE-SYNC-AND-KNOB-2` (owner: schedules stay local until a delete-propagation design) and `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` (waits on the deferred Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF` and a real Discord sitting) kept deferred · review w1118a.52: filed `RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE` (from Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`, READY)
- **`RT-A-SAVED-CHAT-CAN-MOVE-TO-ANOTHER-INSTANCE-OF-ITS-AGENT` — Reopening an old chat while its agent is busy opens it on another idle instance of that agent instead of being refused** · group: bundled-agents-stay-one-agent · from: Eternia `MC-CHAT-LIST-GROUPS-CHATS-UNDER-THEIR-AGENT-INSTANCE` · read in code 2026-11-19 by Eternia lane bundled-chatlist, not reproduced: `agent_runtime/persona_assignments/` `assert_bindable` refuses binding a chat created on one instance to another instance, so Eternia's chat panel still asks before reopening a saved chat whose instance is replying · owner 2026-11-19 (Eternia chat): "Reuse idle, else new" — opening an old chat reuses an idle instance of its agent (replacing that instance's loaded chat) and places a new one only when every instance is busy; an instance can open old chats from other instances of the same persona · architecture: one rebind owner in the runtime; a chat stays one conversation (its history moves with it), never copied · done when: a saved chat whose instance is replying re-binds to an idle instance of the same agent (or a newly placed one) and keeps its history; a chat of a different agent is still refused; read live on a throwaway root · reviewed 2026-11-20 owner ("claim all of these rows … and do em here") · READY 2026-11-19 · **TAKEN 2026-11-20 rt-chat-rebind on DESKTOP-QJ7DDV2 as nekwo in hermes-agent**
- **`RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE` — An agent leading a wave can add another instance of an agent with one proper tool, instead of scripting the command line** · group: runtime-followups · from: Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` · seen 2026-11-19 (owner's namespace, a wave run by Neko Mission Lead Beta; owner's screenshot of Agent Console › Details › Activity): to get two more Launcher Dev instances in testv4 Neko ran a terminal tool call `for n in 2 3; do h=$(openssl rand -hex 4); hermes harness persona instance create --persona dev --add-instance --placem…`, choosing placement ids by hand and naming them "Launcher Dev Agent 2" / "3" itself (instances `personainst_dev_agent_68b8bedc`, `_f88f7aff`), bypassing the runtime's `· 2` numbering (`numbered_instance_name`) and leaving no record of which agent asked · owner 2026-11-19: "yes agreed it needs a first class row" · architecture: one agent-facing tool over the existing `runtime.agent.place` path (and the "reuse an idle instance, else place one" rule the Eternia resolver applies — one owner, not a second rule), taking agent and workspace, never a name or placement id; the runtime names the instance and records the asking agent instance (ties to `RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT`); permission-gated like other office writes · done when: a lead agent asked to staff a wave adds instances through the tool, they read `<agent> · 2` and carry who asked, an idle instance is reused before a new one is placed, and no shell command is needed; read live on a throwaway root · read in code (review w1118a.53): the pieces the row names exist — `numbered_instance_name` (`agent_runtime/agent_create/request.py:125`) names `<agent> · 2`, `runtime.agent.place` runs through `agent_runtime/agent_create/perform.py` and `serve_rpc/agent.py`, and the create path already carries `requested_by` (`agent_create/phases.py:147`, a verb name today, not the asking instance); agent tools live under `tools/` (the agent-chat tool is the nearest sibling) · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.53 D8, analysis: (a) one agent tool over `runtime.agent.place`, taking the agent and the workspace only; the runtime reuses an idle instance before placing one (the rule moves to the runtime if Eternia's resolver holds it today, and Eternia then reads the runtime's answer — one owner), names it, and records the asking instance as `requested_by`; office writes' permission gate applies; (b) teach agents the CLI line; recommended and taken: (a) — the owner asked for a first-class tool, and the CLI bypasses numbering and the record; rejected (b) · same seam: `RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT` (the actor on the record) — one lane takes both, this row first · architecture: fork — `tools/` (the new tool), `agent_runtime/agent_create/`, `agent_runtime/serve_rpc/agent.py`; no upstream edit · REQUIRES linux · reviewed 2026-11-19 w1118a.53 · READY 2026-11-19 · **TAKEN 2026-11-19 w1118a-hagent on nekwo-ubuntu24 as nekwo in w1118a-hagent-hm**
- **`RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT` — When an agent is removed from a workspace, its record and the activity log say who removed it (you, or which agent) instead of leaving it a mystery** · group: runtime-followups · from: Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` · seen 2026-11-19 (Eternia orchestrator, owner's namespace, during a wave run by Neko Mission Lead Beta): the owner removed Base Agent from the testv4 level; the retire receipt `persona_instances_archive/<stamp>_retire/receipts/personainst_base_agent_a24948df.json` reads `reason` "placement removed from Mission Office" and `requested_by` null, the `persona_instance.retired` event names no actor, and `office.actor.removed` says only `instance_reaped` — so it read as possibly the agent's doing until the owner confirmed it was theirs · owner 2026-11-19: "maybe log should say user removed x agent shoudn't be a mystery" · architecture: the retire and office-removal verbs record the actor the request came from (the signed-in person through Eternia, or the agent instance whose tool call asked) on the receipt and both events; Eternia sends nothing it does not already know (check whether its office removal passes an actor and file the Eternia half as an Eternia mission-control-queue row if not) · done when: removing an agent from the level in Eternia records the person, an agent's own removal records that agent instance, and the activity line reads "<who> removed <agent> from <workspace>"; read live on a throwaway root · read in code (review w1118a.53): the retire receipt already has a `requested_by` field (`agent_runtime/agent_retire.py:234`, `:321`) and `runtime.agent.delete` fills it with its verb name (`agent_copy_delete.py:220`), while the office removal's reap passes the bare reason `instance_reaped` and no actor (`agent_runtime/office_store/archive.py:199`, `persona_assignments/retire.py:191`) — which fits the null the owner saw · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.53 D9, analysis: (a) every retire and removal verb takes an actor — the signed-in person when the request comes through Eternia's authenticated call, or the agent instance whose tool call asked — and writes it to the receipt and both events, the activity line reading "<who> removed <agent> from <workspace>"; a call with no actor records `unknown`, never null; (b) infer the actor from the call path; recommended and taken: (a); rejected (b), which guesses · the Eternia half: if Eternia's office removal sends no actor, the lane files it at once as an Eternia mission-control-queue row (the row already says so) · same lane as `RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE` · architecture: fork — `agent_runtime/agent_retire.py`, `office_store/archive.py`, `persona_assignments/retire.py`, the event emitters · REQUIRES linux · reviewed 2026-11-19 w1118a.53 · READY 2026-11-19 · **TAKEN 2026-11-19 w1118a-hagent on nekwo-ubuntu24 as nekwo in w1118a-hagent-hm**
- **`TASK-FRESH-INSTALL-NEKO` — A new install opens with Neko Mission Lead ready to talk, instead of an empty agent list** · task: fresh-install-neko · 3 subtasks on 2026-11-18 (2 ready here, 1 in Eternia's `mission-control-queue.md`: `MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME`) · RULED 2026-11-18: owner — "new installs default agent should be neko mission lead"; "base is still the base for the protocol layer though don't change that aspect of base" · READY 2026-11-18 · **TAKEN 2026-11-18 w1118-neko on DESKTOP-QJ7DDV2 as nekwo in w1118-neko**

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

- **`RT-RECHECK-AFTER-THE-PRE-LAUNCH-HERMES-UPDATE` — After the pre-launch Hermes update, 33 old findings in upstream code are checked once more and only the ones still true come back** · group: upstream-footprint-ledger · upstream-owned code the fork cannot edit (§ Upstream-owned) · filed 2026-11-15 by w1115e-rr2 from the deep sweep 2026-11-15 §H-B3 (owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure") · read in git, not re-run: the update (merge-base 3b42157858 to `upstream/main`) rewrites the files these rows cite — `hermes_cli/gateway.py` +30/−123, `hermes_cli/gateway_windows.py` +96/−27, `hermes_cli/config.py` +64/−235, `agent/ssl_verify.py` +74, `tools/delegate_tool_config.py` +41, `agent/prompt_builder.py` +60/−25, `tui_gateway/host_supervisor.py` +41/−15, `hermes_state.py` +31/−21, `gateway/hosted_room_policy_checkpoint.py` +30 · architecture: no fork edit and no upstream edit — a re-check only; each survivor is filed as its own row by the layer it lands in (a fork seam per the fork-route-first rule, or an upstream issue); each row's full text is in `Harness_Brain/80 — Archive/Queues/` (runtime-queue-2026-11.md, fork-hygiene-queue-2026-11.md) · checklist (each row closed into this one, its owner quote kept): `RT-REQUEST-BUILT-RESOLVES-WEB`: re-time the per-request web-search provider lookup in `agent/transports/codex.py::_alias_wire_tools` (owner triage 2026-11-09 "Small latency; owner ruled wait on upstream"); `RT-SEND-PREP-H7-UNRESOLVED`: re-split the 47–50 ms warm request build in `ResponsesApiTransport.build_kwargs` ("Small latency measurement; waits on upstream"); `RT-SEND-PREP-H2-H6`: re-measure skill preload and package stamps on a skill-heavy persona; it did not reproduce on the fresh route ("Small latency; waits on upstream"); `RT-SKILL-CATALOG-FRONTMATTER`: re-time `tools/skills_tool._skill_catalog` frontmatter parsing and the kanban gate's 1.3 s first import ("Small performance gain; upstream-owned"); `RT-DASHBOARD-AUTH-SCRYPT-IMPORT`: check `plugins/dashboard_auth/basic` still computes its scrypt dummy hash (~0.2 s) at import ("Test-speed issue only; no user impact"); `RT-PROCESS-STARTUP-UPSTREAM-WORK`: re-time the provider discovery (~1.6 s) that importing `hermes_cli.config` runs for read-only verbs ("Noticeable but not broken; depends on upstream accepting PRs"); `RT-I18N-BUNDLED-PER-HOME`: check `agent/i18n.py::_load_catalog` still re-reads the bundled translations per profile ("Performance mostly felt in tests; upstream-owned"); `RT-CONFIG-NOFILE-REBUILD`: re-time a profile with no `config.yaml` through `hermes_cli/config.py::_load_config_impl` (config.py +64/−235 in the update; 72.5 s vs 41.2 s test file) ("Performance tweak; upstream-owned, workaround is adding a file"); `RT-AUX-KEY-CHAIN-LOAD-CONFIG`: count `load_config()` calls per `agent/auxiliary_client._resolve_api_key_provider` auto resolution (~48 providers) ("Performance gain only; upstream-owned"); `RT-NATIVE-WORKER-UPSTREAM-BOOT`: re-time a native worker's ~5 s to first reply: `tui_gateway.server` import, first agent build, first `model.options` ("Felt latency but depends entirely on upstream work"); `RT-CHECKPOINT-PM-ENSURE`: check `tools/checkpoint_manager._run_git` still calls `pm.client.ensure` on every git call (~11 ms each) ("Speed-up mostly felt in test runs; upstream owns the fix"); `RT-DELEGATION-KNOB-ENV-DEAD`: check `DELEGATION_MAX_CONCURRENT_CHILDREN` / `DELEGATION_CHILD_TIMEOUT_SECONDS` still lose to DEFAULT_CONFIG in `tools/delegate_tool_config.py::_knob` (+41 in the update) ("Settings work through config instead; minor"); `RT-CONTEXT-MANIFEST-WITHIN-KIND`: check `/context` still marks every candidate of a kind loaded while `agent/prompt_builder.py` (+60/−25) loads only the nearest ("Misleading display in a power-user command; upstream-blocked"); `RT-HERMES-STATE-SCHEMA-STALE`: check Windows chat search recovers by itself after its search index is damaged (`hermes_state.py` +31/−21) ("Real but rare; owner already ruled to wait for upstream"); `RT-SPARK-PRO-USAGE-BUCKET`: check `gpt-5.3-codex-spark` on the ChatGPT-account Codex route; `hermes_cli/codex_models.py` already lists it ("Model is already safely disabled; adding it is a nice-to-have"); `FORK-WINDOWS-SIGNAL-SAFETY-CARRY`: check whether upstream now ships an equal Windows Ctrl+C safety fix; if it does, drop the carry ("Reminder only; nothing to do until upstream changes"); `RT-GATEWAY-START-MANAGED-PYTHON`: check `hermes --profile <name> gateway start` from the managed venv (`hermes_cli/gateway.py` +30/−123) (owner 2026-11-05 "thats upstreams gateway stuff im going to build my own external gateways"); `FH-FLAKE-API-ADMISSION-OFF-LOOP-UNDER-LOAD`: re-run `tests/gateway/test_api_admission_off_loop.py` (owner triage 2026-11-09 "Test-only timing flake; the product itself is not shown broken"); `FH-FLAKE-SESSION-AUTHORITY-OWNER-KILL-UNDER-LOAD`: re-run `tests/gateway/test_session_authority.py` (same triage); `FH-FLAKE-BROWSE-SCHEMA-DRIFT-CONCURRENT-UNDER-LOAD`: re-run `tests/hermes_cli/test_browse_schema_drift.py` (same triage); `FH-FLAKE-SCHEDULER-PROVIDER-RECOVERY-THREAD`: re-run `tests/cron/test_scheduler_provider.py` (same triage); `FH-FLAKE-API-PENDING-DAEMON-DEADLINE`: re-run `tests/gateway/test_api_pending_daemon.py` (same triage); `FH-FLAKE-EXECUTE-CODE-GATE-LOOP-TICK`: re-run `tests/gateway/test_local_turn_origin_execute_code_gate.py` (same triage); `FH-FLAKE-LOCAL-SESSION-APPROVAL-CHILD`: re-run `tests/gateway/test_local_session.py` (same triage); `FH-FLAKE-SHARED-BUSY-RECEIVE-DEADLINE`: re-run `tests/gateway/test_shared_busy_receive_loop.py`, an upstream file the fork edits (same triage); `FH-FLAKE-WEBHOOK-AUTHORITY-CHILD`: re-run `tests/gateway/test_webhook_authority.py`, an upstream file the fork edits (same triage); `FH-FLAKE-SESSION-CONFIG-PROJECTION-PROVIDERS`: re-run `tests/gateway/test_session_config_projection.py` ("Only seen under heavy test load; no user report"); `FH-FLAKE-CONNECTOR-OPERATION-RPC-NO-REPLY`: re-run `tests/tui_gateway/test_connector_operation_rpc.py` (same triage); `FH-FLAKE-PM-STREAMING-DEADLINE-UNDER-LOAD`: re-run `tests/pm/test_environment_build.py` (same triage); `RT-FLAKE-UPDATE-EXISTING-MAIN-SWITCH-HANDOFF`: re-run `tests/hermes_cli/test_update_existing_branch_baseline.py`, on a quiet box first (deferred 2026-11-10 into the load-flakes batch); `RT-UPSTREAM-TEST-RACES-TWO`: re-run `tests/tools/test_browser_eval_supervisor_path.py` and `tests/agent/test_run_agent.py::TestExecuteToolCalls` (owner 2026-10-16 "pr branches should remain idle"); `FH-UPSTREAM-TESTS-STRIP-SYSTEMROOT`: re-run `tests/hermes_cli/test_update_restore_authority.py` and `tests/hermes_cli/test_runtime_maintenance_exclusion.py` on Windows ("Upstream test bug; product unaffected"); `FORK-QUALIFY-NATIVE-WINDOWS-MSYS`: re-check MSYS foreground-child cleanup on native Windows ("Rare leftover processes; upstream-owned; needs report first") · done when: the update has landed; the 16 test files are re-run at -j 24 on a busy box, the 11 latencies re-measured once (as Eternia `TASK-WINDOWS-HANDOFFS` rows), the 6 behaviours re-read; only what still fails is filed, and this row closes · reviewed 2026-11-15 w1115e.10 · DEFERRED 2026-11-15: waiting on the pre-launch hermes update; until it lands · RULED 2026-11-19: owner said "the launch v1 tasks should remain deffered imho" — kept deferred as launch-v1 work (it runs at the pre-launch hermes update; the owner allows the full suite only on upstream release updates)

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

- **`RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` — When GitHub refuses a realm's push because the owner disconnected the repository, the member is told to ask for a reconnect within a minute, instead of retrying a dead token for up to 44 minutes** · group: runtime-followups · from: `TASK-WORKSPACE-ABSORBS-PROJECTS` · `agent_runtime/realm_sync/` · read in code 2026-11-14 (`eternia-backend` `603184bc`, `REALM-GIT-BINDING-DEATH-UNSEEN-WHILE-TOKEN-CACHED`): the backend now takes `POST /api/realms/{id}/sync/auth-rejected` (local `/api/me/realms/{ref}/sync/auth-rejected`) with the credential's `api_token`, answering 204 (re-broker) or 409 `realms.git_host_binding_lost`; hermes calls it nowhere · the Eternia half is already mapped (read in code: Eternia `realm_sync_credential_failure.dart` maps `realms.git_host_binding_lost` to reconnect), so it is this row's own live read, not a separate row · done when: a push or fetch refused 401/403 by github.com reports once, a 204 re-brokers, a 409 reaches the snapshot as `git_host_binding_lost`, pinned by tests; and the builder reads Mission Control showing reconnect, not retry, in a QA copy · NEW 2026-11-14 · reviewed 2026-11-14 w1114a.2 · the read, once unblocked: built ef70922059 (report on 401/403/404 from publish, pull, status; 204 re-broker, 409 host-state mark; 13 tests on a local refusing HTTP host) — read Mission Control showing reconnect after GitHub refuses a server realm's push · handoff 2026-11-14: not read live — making github.com refuse a staging realm's token means uninstalling the staging GitHub App or dropping a repo from its installation, a GitHub account settings change no lane may make unasked; the hermes→snapshot half is pinned by test (sync.revoked reason git_host_binding_lost, host_state true), the Eternia render of that mark is existing code (mission_snapshot_realms.dart) · handoff 2026-11-14 (w1114a-realmlive): probe approved by the owner and staging rolled to backend 4c38b903, but no tool on the Linux box can take a repo out of the staging App's installation (gh's OAuth token is refused 403 on installation repositories, the built-in browser is signed out of GitHub, the Chrome extension is not connected), so GitHub's refusal was never provoked; what is left: the owner unticks ArcadiaLabsLLC/eternia-probe-org-create-2026-11 in the eternia-server-realms-staging installation, a lane binds QA Realm to the probe (staging manage.py shell: realms.subject_git_host _upsert of the realm subject with installation 181291722, then connect_realm_github as the server owner), Pulls as account B and reads the sheet, then the owner re-ticks it and the lane unbinds (disconnect_realm_github) · BLOCKED 2026-11-16: owner sitting — untick the probe repository in the eternia-server-realms-staging installation for one read, then re-tick (steps on the row) · waits: owner-ruling · reviewed 2026-11-16 w1115e.18
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

- **`RT-BUNDLED-NEKO-USER-INJECTOR` — An agent's SOUL or profile text can say `{user}` and the agent reads the signed-in Eternia account's name there, so no shipped agent hardcodes a person** · group: fresh-install-neko · reported 2026-11-18 by the owner: "one thing i want to add is the `user` injector from the eternia profile"; clarified 2026-11-18: "in the soul or profile md data we can put {user} and it will take the eternia account profiles name instead of hardcoding Tony or a name" · read in code 2026-11-18: no placeholder exists today, and the runtime holds no account display name (the namespace is keyed by account id only) · RULED 2026-11-18: owner (quotes above) · do: where the runtime reads an agent's SOUL, SOUL overlay and system prompt into a turn, replace the exact token `{user}` with the account's display name, and with "the user" when none is known; the name comes from Eternia through the contract in `EterniaLauncher` row `MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME` (file `account_profile.json` at the namespace root, `{"display_name": "<name>"}`, written by Eternia); the upstream `SOUL.md` load goes through a fork seam, never an upstream edit; then the bundled Neko SOUL from `RT-FRESH-INSTALL-SEEDS-NEKO` says `{user}` where it now says "the person you work with" / "they" · architecture: one fork-owned resolver of the account name (namespace file, then the fallback) read by every prompt-text reader; no reader re-reads the file itself · done when: a persona whose SOUL says "Protect {user}'s attention" gets the account's name in its turn prompt, "the user" with no file, and a literal `{users}` or `{ user }` is left alone · READY 2026-11-18 · handoff 2026-11-18 (orchestrator): left for the Linux box (owner 2026-11-18 'Leave for Linux'); start after RT-FRESH-INSTALL-SEEDS-NEKO lands, it ships the bundled Neko SOUL this row edits; pairs with EterniaLauncher MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME, which owns the account_profile.json writer · handoff 2026-11-18 (orchestrator): also owed from RT-FRESH-INSTALL-SEEDS-NEKO (landed 2f502b2544ba, seen live in the CLI only): read Eternia on a fresh namespace through launcher_qa and see Neko Mission Lead selected by default; do it in this row's live read

## Filed on arrival — 2026-11-19 (review w1118a.29, from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE`)

## Filed on arrival — 2026-11-19 (lane w1118a-hsurf)

## Filed on arrival — 2026-11-19 (lane bundled-runtime)

- **`RT-SHIPPED-AGENT-SEAT-EDIT-COUNTS-AS-A-CHANGE` — Giving one seat of Neko or Base its own skills shows as a change to the agent and is reset by the next update** · group: bundled-agents-stay-one-agent · from: Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` · read in code, not reproduced (lane bundled-runtime, 2026-11-19): `agent_runtime/bundled_agents/resolve.py::is_locally_changed` reads only the persona record, while a seat's `PersonaInstance.skill_overrides`, `character_assignment` and `display_name` (`agent_runtime/models.py`) can make one seat of a shipped agent behave differently under the shipped name — design § 3 (Eternia `Launcher_Brain/20 — Active Initiatives/bundled-agents-stay-one-agent-design.md`) counts those as changing the agent; owner answer 2 keeps model and reasoning effort seat settings · regrouped by review w1118a.39 from `runtime-followups`: `is_locally_changed` is this task's own work (`RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD`, closed today), and the design's § 3 already counts a seat's skills, character and name as the agent's definition, so this is a defect in its own work · read in code, confirmed (review w1118a.39): `is_locally_changed(persona)` (`agent_runtime/bundled_agents/resolve.py`) takes only the persona and compares its definition and SOUL with the shipped one; nothing reads a seat · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.39 D9: one owner — `resolve.py` answers "changed" for a seat too: the seat's `skill_overrides`, `character_assignment` and `display_name` count, read beside the persona's definition, and the directory and instance detail report it per seat through `directory_fields`; the update that resets a changed shipped agent clears those three seat fields and leaves `model`, provider, `reasoning_effort`, folder slots, desk and chats alone (owner answer 2); writes are never refused (owner answer 6 amends § 4: warn and reset); rejected: refusing seat writes (§ 4 as amended) and a second "changed" check in the instance code (two owners) · architecture: fork-owned `agent_runtime/bundled_agents/resolve.py` and its callers only; no upstream hermes file · cross-reference: Eternia `MC-BUNDLED-AGENTS-CHANGE-NEEDS-A-NEW-NAME` (TAKEN by bundled-copy) warns on `locally_changed`, so a seat edit warns once this lands · tests: a seat with its own skills reads changed while its model alone does not (red with the seat fields dropped), and an update clears the skills and keeps the model · done when: a seat of a shipped agent with its own skills reads `locally_changed: true` in `runtime.agent.directory`, and an update resets its definition overrides and leaves its model alone · filed 2026-11-19 by bundled-runtime · reviewed 2026-11-19 w1118a.39 · READY 2026-11-19

## Filed on arrival — 2026-11-19 (lane bundled-pushlist)


## Filed on arrival — 2026-11-19 (lane bundled-menus)


## Filed on arrival — 2026-11-19 (lane bundled-facts)

## Filed on arrival — 2026-11-19 (review w1118a.52, from Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`)


## Filed on arrival — 2026-11-19 (review w1118a.46, from Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE`)


## Filed on arrival — 2026-11-19 (review w1118a.47, from Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST`)


## Filed on arrival — 2026-11-19 (review w1118a.48, from Eternia `MC-SUBTASK-HOLD-TO-ARCHIVE`)


## Filed on arrival — 2026-11-19 (review w1118a.50, from Eternia `MC-SYNC-PULL-UNDOES-A-LOCAL-RENAME-MADE-SINCE-THE-LAST-PUBLISH`)

- **`RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE` — Syncing keeps a workspace or realm change you made here since the last publish, instead of putting the team's older copy back** · group: runtime-followups · from: Eternia `MC-SYNC-PULL-UNDOES-A-LOCAL-RENAME-MADE-SINCE-THE-LAST-PUBLISH` (review w1118a.50) · seen in Eternia 2026-11-19 (sync-alert-clears, Windows, QA Realm): a workspace renamed here after its publish read the team's older name again after Sync's pull, and nothing was published · read in code (review w1118a.50): `agent_runtime/realm_sync/families.py` gives the WORKSPACE and REALM record families `owner=GENERIC_PULL`, and `pull.py::_overwrite_generic_families` writes the pulled bytes over the local file whenever they differ, with no baseline; boards, office, levels, maps, prefabs, persona and instance config and flow graphs each merge against a baseline and keep or hold a local change · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.50 D7: one design fix for both record families: their pull merges field-wise against the last-published baseline, as the persona-config pull does — a field changed only here is kept and published next, a field changed only by the team is taken, a field both changed is held with the same sidecar and status the other families use; the workspace re-home and moved-out rules (`_workspaces_moved_out`, the rehome) keep working; rejected: a rename-only patch (every field of both records has the same overwrite) and Eternia publishing before it pulls · done when: a rename made here after the last publish survives a pull and is published, a teammate's rename of an unchanged workspace is taken, both renaming holds, each red-tested; read live in QA Realm on Linux, and Eternia `MC-SYNC-PULL-UNDOES-A-LOCAL-RENAME-MADE-SINCE-THE-LAST-PUBLISH` reads it in the app · architecture: runtime realm sync — `agent_runtime/realm_sync/families.py`, `pull.py`, a workspace/realm applier beside the other families' · REQUIRES linux · filed 2026-11-19 by w1118a-rev48 · reviewed 2026-11-19 w1118a.50 · READY 2026-11-19
- **`RT-SCRUB-THE-OWNERS-OLD-NEKO-MEMORY-FROM-THE-TEAM-REPO-HISTORY` — The owner's old Neko memory is gone from the team repo's history, not only from its files** · group: runtime-followups · from: `RT-OWNERS-OLD-NEKO-MEMORY-STAYS-IN-THE-TEAM-REPO` · RULED 2026-11-19: owner said "yes scrub it for good measure" · seen 2026-11-19 (read-only `git log` of the owner's realm clone): `store/profile_files/neko/SOUL.md` and `memories/MEMORY.md` were published 2026-09-25, 10-06 and 10-25, before Neko shipped · how: first the owner's next real publish drops them from the tree; then rewrite the team repo's history to drop those two paths (git filter-repo on a fresh mirror clone, every branch), and force-push the rewritten history to the team repo — the ONE force-push the owner allowed, for this repo only; every member's clone then needs a fresh clone or a hard reset to the new history (say so to the owner before the push, with the member list) · done when: no commit in the team repo's history holds either path, every member's Eternia reads In sync afterwards, and a member on an older build does not publish the files back (if it does, file a row) · review w1118a.52, the plan checked against code: (1) the repo cannot be named from code — it is data: the owner's realm's git binding (`eternia-backend/realms/models.py` `GitHostBinding.repo_owner`/`repo_name`, used as `owner/name` in `realms/git_host.py:171`), which is also the `origin` of the owner's realm clone; the lane reads both read-only (the remote URL with any credential stripped, never printed with one), they must agree, and it is never the QA Realm (`ArcadiaLabsLLC/eternia-qa-realm`) — if they differ, stop; (2) seen on this box: `git filter-repo` is not installed (not a git command, no Python module), and installing it is a download; recommended and taken: git's own `filter-branch --index-filter 'git rm -q --cached --ignore-unmatch -- store/profile_files/neko/SOUL.md store/profile_files/neko/memories/MEMORY.md' --prune-empty -- --all` on a fresh `git clone --mirror` (the lane first lists every path that ever held those two files with `git log --all --name-only` and scrubs each spelling), then `refs/original/` dropped, the reflog expired and `gc --prune=now`; verify `git log --all -- <paths>` is empty and no blob of those files is reachable; filter-repo only with the owner's yes to the download; (3) the ONE force-push: `git push --force` of the rewritten branches (and any tag that changed) to that repo only, never `--mirror` (it would delete refs the mirror lacks), after a read-only check of the branch protection; (4) read in code, the trap: a member clone still on the old history meets the rewritten tip as diverged, and `agent_runtime/realm_sync/git.py:432` merges the upstream commit into it, so that member's next publish pushes every old commit, the files included, back — every member's Eternia (the owner's too) is closed from before the push until its clone is re-made; (5) the re-clone: the lane reads how a realm clone is made again (`agent_runtime/realm_sync/adoption.py`) and writes the exact steps for a member; guess: close Eternia, move the realm clone folder aside (not deleted), reopen, and the grant set-up clones the new history; (6) the owner's next real publish is not needed first — the rewrite removes the files from every commit, the tip included · what the owner is told before the push, in one message: the repo's full name; the member list (from the realm's members, which no code holds — the owner's realm members view or the backend admin); that every member closes Eternia before the push and re-clones after, or their next sync puts the files back; that a member's unpublished changes in that clone are lost on re-clone, so each publishes first; that every commit id changes, so old commit links break; that GitHub can still serve the old commits by id (cached views, any fork, pull-request refs) until GitHub Support purges them, so a full purge also needs a support request and any fork removed; and that a clone made before the scrub still holds the files and no scrub reaches it · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.52 D12, analysis: (a) a lane prepares and verifies the rewritten mirror on this box, sends the owner the message above, and pushes only on the owner's go after it, then reads In sync on its own copy and checks the done-when; (b) push at once on the owner's earlier yes; recommended and taken: (a) — the row itself says to tell the owner first, and members who are not told re-publish the files; rejected (b) · lane: a hermes lane on Linux with the owner's GitHub credentials on this box (never a brokered token printed); it stops BLOCKED (owner sitting) at the push step with the message, if the owner has not answered · reviewed 2026-11-19 w1118a.52 · BLOCKED 2026-11-20: owner sitting — the go on the repo name nekwo/testtest and the realm's member list (NEKO_SCRUB_PLAN.md), then the one force-with-lease push of main · handoff 2026-11-20 (w1118a-hscrub): prepared and verified, nothing pushed; plan for the owner's go in the coordinator's wave folder, NEKO_SCRUB_PLAN.md (_w1118a); seen: the repo is nekwo/testtest (the realm record's sync_manifest_ref and the owner's clone origin agree; the backend GitHostBinding row was not read, no read-only path); it is PUBLIC, one branch main, no tags, no PRs, no forks, not protected; filter-branch on a fresh mirror dropped all 5 spellings (store/profile_files/neko/SOUL.md, store/profile_files/neko/memories/MEMORY.md, profiles/neko/personas/neko_supervisor/{memories/MEMORY.md,soul_overlay/SOUL.md}, profiles/base/personas/neko_supervisor/soul_overlay/SOUL.md), main bdc2f6a7e7 -> 56024ab0fd, 52 commits kept, log of the paths empty, the private blobs unreachable, every commit differs only by those paths, tip trees identical; read in code: a member must move aside BOTH realm_sync/_clones/<realm> and the old shared realm_sync/<server> clone, or _carry_shared_clone copies the old history back; waits: the owner's go on the repo name and the member list (the backend holds it), then the force-with-lease push in the plan · **TAKEN 2026-11-19 w1118a-hscrub on nekwo-ubuntu24 as nekwo in /home/nekwo/Eternia/worktrees/w1116-wg-hm** · waits: owner-ruling
- **`RT-A-REALMS-TEAM-REPO-CAN-BE-PUBLIC` — A realm whose team repo is public shows every member's published files, agents' memories included, to anyone on the internet, and nothing tells the owner** · group: runtime-followups · from: `RT-SCRUB-THE-OWNERS-OLD-NEKO-MEMORY-FROM-THE-TEAM-REPO-HISTORY` (lane w1118a-hscrub) · seen 2026-11-20 (GitHub API, read-only): the owner's realm `cf6d244d-…` syncs with `nekwo/testtest`, which reads `private: false`, and its history held the owner's Neko memory · read in code, not reproduced: the backend creates a new realm repo with a `private` flag (`eternia-backend/realms/github.py:1105`, `realms/routes.py:469`), but nothing was found that checks the visibility of an existing repo a realm is bound to, or that warns when a publish goes to a public repo · guess: Eternia and hermes never show the team repo's visibility · layer: guess, the backend binding read model (the visibility fact) with the Eternia realm sync surface showing it, hermes only if the publish verb should refuse · done when: an owner whose realm syncs with a public repo is told so before a publish, and the owner has ruled whether a publish to a public repo is refused or only warned · read in code (review w1118a.54): hermes realm sync holds no visibility fact (nothing under `agent_runtime/realm_sync/` reads one) and publishes with the brokered credential only; the backend is the one place that reaches GitHub as the App and already reads `GET /repos/{owner}/{repo}` (`eternia-backend/realms/github.py:591`), whose body holds `private`, but its binding read model `GitHostOut` (`eternia-backend/realms/schemas.py:168`) carries none, so Eternia's sync sheet cannot show it · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.54 D5, analysis of layer and kind: (a) warn: the backend reads the visibility once (backend `REALM-REPO-SAYS-WHETHER-IT-IS-PUBLIC`), Eternia's sync sheet shows it and asks once before a manual or automatic publish to a public working repo (`MC-REALM-SYNC-WARNS-WHEN-THE-TEAM-REPO-IS-PUBLIC`), hermes unchanged; (b) refuse in hermes' publish verb, which would need the fact carried into the credential and a second reader of it; (c) refuse in the backend credential broker; recommended and taken: (a) — a public repo is a choice the backend's create step offers and the realm publishing repository's site needs, so a refusal blocks a legitimate setup and needs an override anyway; the fact keeps one reader (owner rule 2026-11-19, no duplicate implementations); every member, not only the owner, is asked, since it is each member's own memory that goes out; rejected (b) and (c) · the owner's own repo: `nekwo/testtest` is public now; the scrub plan already says so (`RT-SCRUB-THE-OWNERS-OLD-NEKO-MEMORY-FROM-THE-TEAM-REPO-HISTORY`, TAKEN by w1118a-hscrub, not edited here); making it private is the owner's choice, raised by the coordinator with that plan · no hermes code: this row closes with launcher `MC-REALM-SYNC-WARNS-WHEN-THE-TEAM-REPO-IS-PUBLIC` · reviewed 2026-11-20 w1118a.54 · BLOCKED 2026-11-20: launcher — `MC-REALM-SYNC-WARNS-WHEN-THE-TEAM-REPO-IS-PUBLIC`: the warning is Eternia's over the backend's fact; no hermes change

## Filed on arrival — 2026-11-20 (lane w1119-busystop: the owner's stop order that bounced off a busy lane)


## Filed on arrival — 2026-11-20 (Eternia lane mc-running-now: the hermes halves of `MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT`)

- **`RT-RUNNING-WORK-ROWS-SAY-WHO-ASKED-WHERE-AND-WHICH-STEPS` — Running now's open card can show who asked an agent for the work, its workspace and folder, and its steps with how long each took** · group: runtime-followups · from: Eternia `MC-RUNNING-NOW-SHOWS-EACH-AGENT-AND-BUILD-AS-A-THIN-ROW` · seen 2026-11-20 by lane mc-running-now building the owner-approved card: a `running_work` row carries no asker, workspace or working folder, and its `plan` is only `done`/`total`/`current_step` — so the card's Asked by, Workspace, Working in and Show folder tiles, and the Steps list (a tick per done step, a duration each, Show all N), are left out rather than guessed; a build's full log has no path to open (Open full log) · read in code: `agent_runtime/running_work/lanes_chat.py` `ChatTurnLane.turn_row` / `DispatchLane.running_row`, `rows.py::work_row` · likely fix: additive row keys (`asked_by` instance, `workspace_id`, `cwd`, `plan.items[]` with state and seconds, a build's `log_path`) through `extra=`, then the Eternia card reads them · done when: a live agent turn's row carries them and the card shows them · review w1118a.55, premise read in code, confirmed: `rows.py::work_row` takes a lane's additive keys through `extra=` and refuses one that would replace a shared key; `lanes_chat.py`'s turn and dispatch rows carry no asker, workspace or folder, and the plan only counts; whether the plan store keeps a time per step is NOT read — the lane reads it first and invents no duration (a step with no recorded time shows none) · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.55 D12, analysis: (a) hermes adds the keys through `extra=` on the rows that own them (`asked_by` as the asking instance, `workspace_id`, `cwd`, `plan.items[]` with state and the seconds the store has, a build's `log_path`), pinned by a projection test, and closes on that; the card's read stays with the Eternia Running now card work (`MC-RUNNING-NOW-SHOWS-EACH-AGENT-AND-BUILD-AS-A-THIN-ROW`, TAKEN on DESKTOP-QJ7DDV2, not edited here), which is told when this lands; (b) one row spanning both repos to a live read; recommended and taken: (a) — a task's rows in another repository go to a separate agent · security: the new keys ride the row's existing account scope, so a row hidden from a caller hides them too; a `cwd` or `log_path` is a path on the install that ran the work — a paired phone may show it, only that install may open it · files: `agent_runtime/running_work/lanes_chat.py`, `lanes_process.py` (the build log), `tests/agent_runtime/test_running_work.py` · reviewed 2026-11-20 w1118a.55 · READY 2026-11-20
- **`RT-STOP-REACHES-WHAT-AN-AGENT-REQUEST-STARTED-AFTER-ITS-PROCESS-ENDS` — Stopping an agent request also ends the test runs and builds it started, even when the agent's own process has already exited** · group: runtime-followups · from: Eternia `MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT` · seen 2026-11-19 by the Eternia orchestrator on Windows: dispatch child pid 32524 had exited while its child (bash → flutter test → MSVC build in a lane worktree) was still alive and had to be ended by pid · read in code, not reproduced: `tools/agent_chat_dispatch/child.py::_kill_child` → `ProcessRegistry._terminate_host_pid` is `taskkill /T /F` on Windows, which walks only a LIVE parent's tree, and `local.py::_run_dispatch_guarded` settles the row when the child exits with no look at what it left running, so survivors are invisible to Running now and nothing can stop them · likely fix (guess): spawn the dispatch child in its own Windows Job Object (POSIX: its own process group) in `local_child.spawn_child`, and have Stop, the budget kill and the settle end the job, not the pid · done when: a dispatch whose child exits leaving a grandchild running has that grandchild ended on Stop (or listed as still running), pinned by a test that spawns a surviving grandchild · review w1118a.55, premise read in code and widened: POSIX has the same gap — `tools/process_registry_termination.py::_terminate_host_pid` refuses a dead pid at its start-time check and returns on `NoSuchProcess`, so a grandchild re-parented after its parent exited is reached on no platform; the surviving-grandchild test therefore runs on Linux, and nothing here needs Windows but the Job Object half · fork route: `tools/agent_chat_dispatch/` is fork-owned (not in `tests/fixtures/upstream_manifest.txt`); `tools/process_registry_termination.py` is upstream and stays untouched · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.55 D10, analysis: (a) `local_child.spawn_child` starts the child in its own process group / session on POSIX (with the repo's `detached-spawn: ok` annotation, as `agent/lsp/client.py` does) and in a Job Object on Windows, and a fork-side group end in `child.py` serves Stop and the budget kill, ending the group even when its leader has exited; the identity guard stays on the leader's recorded start time; on the settle, survivors the process registry lists as the request's own background processes are left (they show in Running now and stop from there), any other survivor is ended with the group; (b) widen upstream `_terminate_host_pid` to walk orphans; (c) only list survivors; recommended and taken: (a) — (b) is an upstream edit the fork route avoids, (c) leaves the seen leak · files: `tools/agent_chat_dispatch/local_child.py`, `child.py`, `local.py` (the settle), a test that spawns a surviving grandchild · edge triaged out: a grandchild that leaves the group on purpose (`setsid` of its own) is not chased · reviewed 2026-11-20 w1118a.55 · READY 2026-11-20 · **TAKEN 2026-11-20 w1118a-hstop on nekwo-ubuntu24 as nekwo in w1118a-homefu-hm**
- **`RT-AGENT-REQUEST-WHOSE-PROCESS-ENDED-STAYS-LISTED-FOR-MORE-THAN-A-SWEEP` — An agent request whose process has ended leaves Running now within a minute on its own, without anyone pressing Stop** · group: runtime-followups · from: Eternia `MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT` · seen 2026-11-19 by the owner: three Launcher Dev requests stayed "unconfirmed" (pid unverified, dead per the orchestrator) for longer than the 60s orphan sweep (`dispatch_delivery/drain.py::sweep_orphaned_dispatches`, `ORPHAN_SWEEP_INTERVAL_SECONDS`) · not reproduced 2026-11-20 by lane mc-running-now: no `mission_chat_dispatches` table in any namespace `state.db` on this Windows box, so the rows were read elsewhere · guess, three candidates read in code: the supervising process still holds the id in `dispatch_store/supervision.py::_supervised` (the sweep skips it), the serve's delivery drain was not running (the sweep runs only inside it), or the store the sweep read was not the one the projection read · Stop on such a row now settles it at once (mc-running-now) · done when: the cause is seen on a live box and a row whose owner is provably gone leaves the frame within one sweep with no Stop · review w1118a.55, a fourth candidate read in code, and the likeliest given "pid unverified": Running now says unconfirmed for `PID_NO_BASELINE` / `PID_START_TIME_UNREADABLE` (`agent_runtime/running_work/vocabulary.py`), and `dispatch_store/delivery.py::owner_provably_gone` answers False for a LIVE pid with no baseline or an unreadable start time, by design; a dead pid is settled — so a row stays only when its pid number is alive again (recycled, fast on Windows) and its identity cannot be proved (another session's process, access denied); and Stop does not clear it either: `local.py::_request_cancel_elsewhere` falls to `cancel_requested`, whose mark no supervisor is left to honour · RULED 2026-11-20: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.55 D11, analysis: (a) the lane pins each of the four candidates with a store test on Linux (faked pid and start-time probes), fixes those that hold, and for the recycled-and-unprovable case settles `unknown` a Stop's cancel mark that no supervisor honoured within its poll window — the operator asked and no process answered; (b) settle any unprovable row at sweep time; (c) keep it forever and say so; recommended and taken: (a) — (b) buries a live build on a psutil hiccup, the trap `vocabulary.py` warns of, (c) is the seen defect · done-when re-read: the cause pinned by a test is enough to close; the Windows re-read of a recycled pid goes on the owed Windows checks at landing · files: `agent_runtime/dispatch_store/delivery.py`, `tools/agent_chat_dispatch/local.py`, tests beside `tests/agent_runtime/test_running_work.py` · one lane with `RT-STOP-REACHES-WHAT-AN-AGENT-REQUEST-STARTED-AFTER-ITS-PROCESS-ENDS` (both edit `local.py`'s stop and settle paths) · reviewed 2026-11-20 w1118a.55 · READY 2026-11-20 · **TAKEN 2026-11-20 w1118a-hstop on nekwo-ubuntu24 as nekwo in w1118a-homefu-hm**
