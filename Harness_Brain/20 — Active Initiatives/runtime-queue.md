---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue





## Filed on arrival — 2026-11-24 (Eternia architecture study lane w1123r-loadarch: the hermes halves of task `TASK-AGENT-VIEWS-ASK-HERMES-ONLY-FOR-WHAT-THEY-SHOW`; waits for a review batch)

- **`RT-FU-A-QUESTION-YOU-MOVED-PAST-LEAVES-THE-AGENT-LIST-WHEN-YOU-MOVE-ON` — When you start working in another chat with an agent, the old chat stops showing "waiting for your answer" in the chat list right away, not at the next full refresh** · group: runtime-followups · from: `TASK-AGENT-VIEWS-ASK-HERMES-ONLY-FOR-WHAT-THEY-SHOW` (lane w1124b-hermespush) · read in code 2026-11-24: the agent list's chat rows now carry `clarify_token` (`persona_chat_frame_history`, `RT-FU-THE-AGENT-LIST-SAYS-WHICH-CHATS-WAIT-FOR-YOUR-ANSWER`), set and cleared on the asking chat's own overlay (its turns, and a dismissal's `clarify_dismissed` notice); a question is also "moved past" (`clarify_waiting.clarify_question_moved_past`) when a turn somebody sent starts in the agent's other, now current, chat — that turn's overlay re-reads only ITS root, so the old chat's row keeps its token until the next full core (guessed from the code, not seen live) · likely fix: the turn-start overlay of a root names, as a second root of the batch, any other chat of the same instance whose open ticket the start moves past (read off the clarify index, which is per session) · done when: a fixture where chat A asked, then a turn starts in chat B of the same agent, ships A's row with `clarify_token: null` in that batch's frames, pinned by a test · READY 2026-11-24

## Shipped agents stay one agent — 2026-11-19 (owner; task row in Eternia `mission-control-queue`)



## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)


- **`TASK-AGENT-CONFIG-CLEANUP` — Agent settings: each agent's folders, data, options and abilities live in one clear place** · task: agent-config-cleanup · 1 subtask open on 2026-11-19 (Eternia `MC-OWNER-NAMESPACES-ADOPT`; the other 9 are closed in the archives, the five hermes RT rows on 2026-11-15) · RULED 2026-11-19: owner said "same thing with this undefer it and see if its stale" (the same thing = "undefer it and have an aggent see and fix if need be") · checked 2026-11-19 (w1118a-hcfg): nothing stale was left to close — the five hermes subtasks (`RT-DELEGATION-KNOB-ENV-DEAD`, `RT-NAMESPACE-ADOPT`, `RT-ROOT-CONFIG-MISPLACEMENT-CURE`, `RT-MACHINE-ROOTS-FOLD-BREAKING`, `RT-READ-MODEL-RESIDUE-NEXT-BUMP`) were already archived CLOSED on owner words 2026-11-15; the one open subtask is real and is only the owner's own sitting on the Windows PC · BLOCKED 2026-11-19: launcher — `MC-OWNER-NAMESPACES-ADOPT` waits on the owner sitting at the Windows PC to pick the Agent data folder in Settings · was DEFERRED 2026-11-16: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` closed as churn (owner 2026-11-16 — "Close as churn"); the one subtask left, Eternia `MC-OWNER-NAMESPACES-ADOPT`, was DEFERRED by the owner (2026-11-09) · unblocked 2026-11-15: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` woken READY by w1115e-rr2 (deep sweep 2026-11-15 §D) · waits: `MC-OWNER-NAMESPACES-ADOPT`
- **`TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` — Agent engine follow-ups: the engine's own checks pass on main again after a lane broke them** · task: engine-suite-green-followups · review w1118a.40 closed bundled-realm's `FH-REALM-TESTS-HANG-ON-A-LOCAL-GIT-REMOTE` (D10: reds on main are not rows) · 3 open subtasks on 2026-11-15 (1 ready: FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY; 2 NEEDS PLAN filed by w1115c-h2 and waiting on a review batch: RT-RUNNING-TURN-START-ROW-WAITS-OUT-THE-DEMOTE-HOLD, RT-RUNNING-TURN-START-NEVER-PUBLISHED-ONCE-UNDER-LOAD; FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD closed DONE 36a1e1d45c and FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD closed DONE c157f48749 by w1115c-h2; FH-GAME-WATCH-TEST-READS-THE-MACHINES-REAL-PROCESSES and FH-BUNDLE-SERVE-PROBE-REPORT-LOST-TO-STDERR-ON-LINUX closed by other w1115c lanes; FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN closed DONE e64d77c9f6 by w1114a-h5 through fork seams) · filed 2026-11-14 by the w1114a.30 queue pass (REVIEW_W1114A_B29), for reds met on hermes main — the twin of Eternia's architecture-gate-green-followups · was DONE 2026-11-15 0495762a2e (all 1 subtasks closed) · reopened 2026-11-15 (review batches w1114a.40 and w1114a.42, REVIEW_W1114A_B39/B41): FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD moved in from the DEFERRED TASK-UPSTREAM-LOAD-FLAKES and FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN from the DEFERRED TASK-HERMES-TEST-ISOLATION · handoff 2026-11-15 (w1114a-h4): FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN reproduced and its fixture fixes written, but they edit three upstream test files (upstream footprint 224->226), so it waits on an owner ruling (DECISION); claim released · BLOCKED 2026-11-20: another lane — `FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-RUNTIME-FOLLOWUPS` — Agent runtime: what the tasks behind this queue's rows found on the way gets fixed after them** · after lane w1122d-hmauthz 2026-11-24: `RT-FU-AN-EXTERNAL-CHANNELS-UNPROVEN-MACHINE-SAYS-WHY-IT-IS-UNPROVEN` closed DONE 370ec836ea (a channel's routing key says `machine:unproven:outside_spec`, any other machine-less caller `machine:unproven:not_proven`), so its mentions below are history, one subtask fewer; `RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS` premise re-checked (hermes half green; look-grant part moot since account-only pairing) and set BLOCKED on launcher `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA` for its live read · after review w1122d.31 2026-11-24: passed `RT-FU-AN-EXTERNAL-CHANNELS-UNPROVEN-MACHINE-SAYS-WHY-IT-IS-UNPROVEN` (READY XS: the routing key's machine segment says `outside_spec` for a channel and `not_proven` for a caller that should have proved one; a channel works as now), counts unchanged · after lane w1122d-hmonecall 2026-11-24: `RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST` (a subtask of Eternia's `TASK-PAIRING-THROUGH-YOUR-ACCOUNT-ONLY`, not of this task) closed DONE 8f7285815d, so its mentions below are history; filed `RT-FU-AN-EXTERNAL-CHANNELS-UNPROVEN-MACHINE-SAYS-WHY-IT-IS-UNPROVEN` (READY, owner ruling on arrival, needs review), one subtask more · after lane w1122d-hmmachine 2026-11-24: `RT-ACCOUNT-ONLY-A-CONNECTION-FROM-ANOTHER-MACHINE-THAN-THE-ONE-YOUR-DEVICE-PAIRED-WITH-IS-DROPPED-FIRST` (a subtask of Eternia's `TASK-PAIRING-THROUGH-YOUR-ACCOUNT-ONLY`, not of this task) closed DONE f3dacaa347, so its mention below is history; its close woke `RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST` (READY) · after lane w1122d-hmroute 2026-11-24: `RT-FU-A-PHONE-AND-THE-LOCAL-APP-ON-THE-SAME-CONNECTION-NUMBER-GET-EACH-OTHERS-ANSWERS` closed DONE 30653d6ea9 (+e6334a98fa; every per-connection map keys on `RpcCaller.route_owner()`, a device and the local app on one connection number each get only their own answers), so its mentions below are history; the close woke `RT-ACCOUNT-ONLY-A-CONNECTION-FROM-ANOTHER-MACHINE-THAN-THE-ONE-YOUR-DEVICE-PAIRED-WITH-IS-DROPPED-FIRST` (READY); one subtask fewer · after review w1122d.27 2026-11-23: passed `RT-FU-A-PHONE-AND-THE-LOCAL-APP-ON-THE-SAME-CONNECTION-NUMBER-GET-EACH-OTHERS-ANSWERS` (filed READY by lane w1122d-hmdiag at f408dc03ea, which left this line unchanged), one subtask more · after lane w1122d-hmdiag 2026-11-23: `RT-FU-A-PAIRED-DEVICE-CAN-READ-THIS-COMPUTERS-THREAD-STACKS-AND-ITS-CONNECTION-LIST` closed DONE c1e1da80ec (+ef3c43eb70, +e0f9b237fe; a device or peer is refused `stacks` and `connections` at the dispatcher door, and a device's `version` carries no connections block), so its mentions below are history; filed `RT-FU-A-PHONE-AND-THE-LOCAL-APP-ON-THE-SAME-CONNECTION-NUMBER-GET-EACH-OTHERS-ANSWERS` (READY, awaiting review); count unchanged · after review w1122d.26 2026-11-23: passed `RT-FU-A-PAIRED-DEVICE-CAN-READ-THIS-COMPUTERS-THREAD-STACKS-AND-ITS-CONNECTION-LIST` (filed READY by lane w1122d-hmaccess at 2c0c2c9056, which left this line unchanged), one subtask more · after coordinator-w1122d 2026-11-23: closed `RT-FU-CHAT-AND-FILE-LISTS-STOP-WORKING-OUT-READ-AND-EDIT-FLAGS-FOR-A-VIEW-ONLY-LEVEL-THAT-IS-GONE` as churn on the owner's words ("3 yes alot of this sounds like churn"), one subtask fewer · after lane w1122d-hmnoread 2026-11-23: `RT-FU-HERMES-PAIRS-A-DEVICE-ONLY-AT-FULL-CONTROL-WITH-NO-VIEW-ONLY-LEVEL` closed DONE 606f2b83c0 (+71322c206d; every paired device has full control, the view-only level and the path projection are gone) and `RT-FU-A-VIEW-ONLY-DEVICE-IS-SENT-WHERE-THIS-COMPUTER-KEEPS-ITS-CHARACTERS` closed REFUTED as superseded by it, so their mentions below are history; filed `RT-FU-CHAT-AND-FILE-LISTS-STOP-WORKING-OUT-READ-AND-EDIT-FLAGS-FOR-A-VIEW-ONLY-LEVEL-THAT-IS-GONE` (READY, awaiting review); one subtask fewer · after review w1122d.18 2026-11-23: filed and passed `RT-FU-HERMES-PAIRS-A-DEVICE-ONLY-AT-FULL-CONTROL-WITH-NO-VIEW-ONLY-LEVEL` (BLOCKED on launcher `QA-FU-A-LANES-PAIRING-MINT-MAKES-ONLY-FULL-CONTROL-CODES`; the owner-asked check found no user of the view-only pairing level outside QA copies and tests), and set `RT-FU-A-VIEW-ONLY-DEVICE-IS-SENT-WHERE-THIS-COMPUTER-KEEPS-ITS-CHARACTERS` BLOCKED on it, superseded (its lane closes it REFUTED), one subtask more · after lane w1122d-hmacctonly 2026-11-23: Eternia-task row `RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN` closed DONE 7b71fd8a84 (a phone's engine answers a paired computer only at the account level), so its mentions below are history; filed `RT-FU-A-VIEW-ONLY-DEVICE-IS-SENT-WHERE-THIS-COMPUTER-KEEPS-ITS-CHARACTERS` (READY, awaiting review; found by the re-pointed read-tier path census), one subtask more · after lane w1122d-hmprobe 2026-11-23: `RT-FU-THE-PHONE-ENGINE-BUILD-CHECKS-THAT-THE-PHONES-OWN-ENTRY-STARTS-INSTEAD-OF-THE-DESKTOP-COMMAND-LINE` closed DONE 6d8db21923 (a bundled-phone build verifies with the serve import probe on: the probe starts the profile's own entry from packaging.roots), so its mention below is history, one subtask fewer · after review w1122d.16 2026-11-23 (Eternia): filed and passed `RT-FU-THE-PHONE-ENGINE-BUILD-CHECKS-THAT-THE-PHONES-OWN-ENTRY-STARTS-INSTEAD-OF-THE-DESKTOP-COMMAND-LINE` (READY), one subtask more · after review w1122d.15 2026-11-23: closed `RT-FU-A-PHONE-PAIRED-AGAIN-BY-QR-OR-PASTED-CODE-REPLACES-ITS-EARLIER-PAIRING-ON-THE-COMPUTER` on the owner's words (account pairing only), so its mentions below are history, one subtask fewer; the look and chat levels' removal is `RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN` under Eternia `TASK-PAIRING-THROUGH-YOUR-ACCOUNT-ONLY` · after review w1122d.14 2026-11-23: filed and passed `RT-FU-A-PHONE-PAIRED-AGAIN-BY-QR-OR-PASTED-CODE-REPLACES-ITS-EARLIER-PAIRING-ON-THE-COMPUTER` (READY M, the owner's 2026-11-23 parity ruling: a QR or pasted-code re-pair retires the earlier pairing on proof of its old credential; its Eternia half is Eternia `MC-FU-A-PHONE-PAIRED-AGAIN-BY-QR-OR-PASTED-CODE-PROVES-ITS-EARLIER-PAIRING-SO-THE-COMPUTER-ENDS-IT`, BLOCKED on it), one subtask more · after lane w1122d-hmhealth 2026-11-23: `RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST` closed DONE ee2e283d60 (a Look or Run chats computer's health-check and agent-list replies carry no absolute local path; the census's `_FILED` is empty), so its mentions below are history; one subtask fewer · after lane w1122d-hmredact 2026-11-23: `RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-ITS-AGENTS-CONTEXT-FILES` closed DONE 754baf9892 (a Look or Run chats computer's prompt-details reply carries no absolute local path; census over every computer-reach verb), so its mentions below are history; it wakes Eternia `MC-FU-A-COMPUTER-USING-A-PHONES-AGENT-SHOWS-THE-PHONES-FULL-FILE-PATH-IN-EVIDENCE-AND-PROVENANCE`; filed `RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST` (the census's finding), subtask count unchanged · after review w1122d.12 2026-11-23 (Eternia): filed and passed `RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-ITS-AGENTS-CONTEXT-FILES` (READY S, the hermes half of Eternia `MC-FU-A-COMPUTER-USING-A-PHONES-AGENT-SHOWS-THE-PHONES-FULL-FILE-PATH-IN-EVIDENCE-AND-PROVENANCE`), one subtask more · after coordinator relay 2026-11-22 (Eternia lane w1122d-delkeys): Eternia `MC-FU-DELETING-A-SAVED-CHAT-NAMES-THIS-ACCOUNT-SO-IT-NEVER-DELETES-ANOTHER-ACCOUNTS-CHAT` closed DONE (Eternia 9b79577d844, read live against 9981dbd360: own chat deleted, another account's chat refused 'This conversation belongs to another account.'), so its mentions below are history · after coordinator relay 2026-11-22 (Eternia lane w1122d-phonechat's emulator read): `RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE` closed DONE 9c21ff1c61 and `RT-FU-A-PHONE-AGENTS-FIND-AND-REPLACE-EDIT-SHOWS-NO-VIEW-DIFF` closed DONE e6b5f24fd1, so their mentions below are history; two subtasks fewer · after lane w1122d-hmdelete 2026-11-22: `RT-FU-DELETING-A-SAVED-CHAT-CHECKS-WHICH-ACCOUNT-IT-BELONGS-TO-AS-ARCHIVING-DOES` closed DONE 9981dbd360 (`runtime.persona.chat.delete` refuses another account's chat `conversation_owner_changed` in archive's order; an unscoped call keeps its authority), so its mentions below are history; it wakes Eternia `MC-FU-DELETING-A-SAVED-CHAT-NAMES-THIS-ACCOUNT-SO-IT-NEVER-DELETES-ANOTHER-ACCOUNTS-CHAT`; one subtask fewer · after lane w1122d-hmgone 2026-11-22: `RT-FU-A-REMOVED-INSTANCES-SAVED-CHAT-MOVES-ONTO-A-LIVE-INSTANCE-OF-ITS-AGENT` closed DONE d5575d537e (a removed instance's saved chat in its own profile moves onto a live instance of its agent; read live on Linux), so its mentions below are history; filed `RT-FU-DELETING-A-SAVED-CHAT-CHECKS-WHICH-ACCOUNT-IT-BELONGS-TO-AS-ARCHIVING-DOES` and `RT-FU-A-CHAT-MOVED-ONTO-A-NEW-INSTANCE-STILL-SHOWS-IN-CHAT-HISTORY-BESIDE-ITS-ACTIVE-AGENT-ROW` (both need review); one subtask closed, two filed · after lane w1122d-hmworkdir 2026-11-22: `RT-FU-A-CHAT-TURNS-RECORD-KEEPS-WHERE-THE-TURN-RAN` closed DONE 6d0026472c (a chat turn's disk record keeps its workdir receipt under `mission_chat_workdir`, never on the terminal frame or a history row), so its mentions below are history; Eternia `QA-FU-A-LANE-CANNOT-READ-A-TURNS-WORKDIR-RECEIPT` woken by hand for its live read; one subtask fewer · after lane w1122d-hmport 2026-11-22: `RT-FU-TURNING-REACHABLE-BACK-ON-KEEPS-THE-PORT-THE-COMPUTER-LISTENS-ON` closed DONE ac404176db (a disabled listener's greeting names the stored port) and `RT-FU-A-PAIRING-CODE-IS-REFUSED-WHEN-THE-RUNNING-SERVES-PAIRING-DOOR-FAILED-TO-OPEN` closed DONE a340e59b50 (pair, peers pair and introduce refuse `gateway_not_listening` while the running serve's bind failed), so their mentions below are history; Eternia `MC-FU-A-PAIRING-CODE-IS-OFFERED-FOR-A-PAIRING-DOOR-THAT-NEVER-OPENED` is woken by hand; two subtasks fewer · after review w1122d.8 2026-11-22: passed `RT-FU-TURNING-REACHABLE-BACK-ON-KEEPS-THE-PORT-THE-COMPUTER-LISTENS-ON` as filed; filed and passed `RT-FU-A-PAIRING-CODE-IS-REFUSED-WHEN-THE-RUNNING-SERVES-PAIRING-DOOR-FAILED-TO-OPEN` (READY S, the hermes half of Eternia `MC-FU-A-PAIRING-CODE-IS-OFFERED-FOR-A-PAIRING-DOOR-THAT-NEVER-OPENED`) and `RT-FU-A-CHAT-TURNS-RECORD-KEEPS-WHERE-THE-TURN-RAN` (READY XS, the fix behind Eternia `QA-FU-A-LANE-CANNOT-READ-A-TURNS-WORKDIR-RECEIPT`); two subtasks more · after Eternia lane w1122d-gwport 2026-11-22: filed `RT-FU-TURNING-REACHABLE-BACK-ON-KEEPS-THE-PORT-THE-COMPUTER-LISTENS-ON` (READY XS, awaits a review batch), one subtask more · after lane w1122d-hmsave 2026-11-22: `RT-FU-A-CONTEXT-FILE-OPENED-FROM-ANOTHER-DEVICE-IS-SAVED-BACK-THROUGH-THIS-ENGINE-BY-HANDLE` closed DONE 3207136fef (`runtime.media.context_file.write`, console tier, no computer reach: SOUL.md or AGENTS.md saved by the handle it was read at, the new handle answered), so its mentions below are history; it wakes Eternia `MC-FU-A-CONTEXT-FILE-OPENED-FROM-ANOTHER-DEVICES-ENGINE-CAN-BE-EDITED-AND-SAVED-BACK-THROUGH-IT`; one subtask fewer · after lane w1122d-hmpath 2026-11-22: `RT-FU-A-LOOK-DEVICE-IS-SENT-THE-PATH-OF-AN-AGENTS-SETTINGS-FILE` closed DONE 4aaa99b7ad (the agent detail verb names no absolute local path to a view-only device or a Look / Run-chats computer; the console keeps them), so its mentions below are history; one subtask fewer · after lane w1122d-hmsafe 2026-11-22: `RT-FU-ANOTHER-DEVICE-SEES-A-SHORT-LIST-OF-SAFE-AGENT-SETTINGS-NEVER-THE-CONFIG-FILE` closed DONE aadf168665 (the agent detail verb carries a `settings` block, model, provider and toolsets, at read tier and Look), so its mentions below are history; it wakes Eternia `MC-FU-ANOTHER-DEVICES-AGENT-SHOWS-ITS-MODEL-PROVIDER-AND-TOOLSETS-WHERE-ITS-SETTINGS-FILE-WAS-LISTED`; filed `RT-FU-A-LOOK-DEVICE-IS-SENT-THE-PATH-OF-AN-AGENTS-SETTINGS-FILE` (READY S, awaits review); one subtask fewer, one more · after lane w1122d-hmpins 2026-11-22: `RT-FU-A-NEW-TOP-LEVEL-SERVE-MANIFEST-KEY-EDITS-ONE-EXPECTATION-NOT-SIX-TESTS` closed DONE cccf3f8073 (the six key-set pins read the expectation file), so its mentions below are history (one subtask fewer); `RT-FU-A-PHONE-AGENTS-FIND-AND-REPLACE-EDIT-SHOWS-NO-VIEW-DIFF` built e6b5f24fd1, LIVE CHECK on the next emulator sitting, so its READY mentions below are history · after review w1122d.4 2026-11-22 (second part): filed and passed `RT-FU-A-PHONE-AGENTS-FIND-AND-REPLACE-EDIT-SHOWS-NO-VIEW-DIFF` (READY S, from lane w1122d-emu's emulator sitting: a phone agent's replace-mode patch answers no diff); to proposed lane H4 w1122d-hmpins in `hm-liveuse`, after `RT-FU-A-NEW-TOP-LEVEL-SERVE-MANIFEST-KEY-EDITS-ONE-EXPECTATION-NOT-SIX-TESTS`; one subtask more than the counts that follow · after review w1122d.4 2026-11-22: passed `RT-FU-A-NEW-TOP-LEVEL-SERVE-MANIFEST-KEY-EDITS-ONE-EXPECTATION-NOT-SIX-TESTS` (READY XS: the six key-set pins read the expectation file's keys; proposed lane H4 w1122d-hmpins in `hm-liveuse`); counts unchanged · after lane w1122d-hmreach 2026-11-22: `RT-FU-A-LOOK-COMPUTER-LISTS-THE-PHONES-EXISTING-CHATS` built 64e7914196 and `RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE` built 9c21ff1c61, both LIVE CHECK on the next emulator sitting (sub-wave C, L7); the stated-reach design fix closed DONE f156e08997 (wakes Eternia `MC-FU-EVERY-CALL-A-COMPUTER-MAKES-TO-A-PHONES-AGENTS-IS-ONE-THE-PHONE-SAYS-IT-ANSWERS`, whose serve rpc manifest mirror is now stale); filed `RT-FU-A-NEW-TOP-LEVEL-SERVE-MANIFEST-KEY-EDITS-ONE-EXPECTATION-NOT-SIX-TESTS` (READY S, awaits review); one subtask fewer, one more · after review w1122d.3 2026-11-22: passed `RT-FU-A-RETIRED-HOLDERS-CHAT-IN-ITS-OWN-PROFILE-STAYS-IN-THE-CHAT-LISTS` (READY S: one fan-out helper in `chat_heads.py` opens retired holders' heads for both chat readers; files disjoint from H1, so its own lane, proposed H3 w1122d-hmretired in `qacopy-hm`); counts unchanged · after review w1122d.2 2026-11-22 (part 2): passed `RT-FU-A-CONTEXT-FILE-OPENED-FROM-ANOTHER-DEVICE-IS-SAVED-BACK-THROUGH-THIS-ENGINE-BY-HANDLE` for when it wakes (stays BLOCKED; the handle is the read digest, writes SOUL.md and AGENTS.md only); counts unchanged · after review w1122d.2 2026-11-22 (part 1): passed `RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE` (READY, security, now M: a Run chats computer can also send with no scope and resolve the owner's turns; the grant row owns the computer's scope, bound at dispatch), lane H1 after the reach refactor; counts unchanged · after review w1122d.1 2026-11-22: passed `RT-FU-A-LOOK-COMPUTER-LISTS-THE-PHONES-EXISTING-CHATS` (READY S, first slice of the design fix, lane H1), the stated-reach design fix (closed DONE f156e08997 by w1122d-hmreach) (READY M, lane H1) and `RT-FU-ANOTHER-DEVICE-SEES-A-SHORT-LIST-OF-SAFE-AGENT-SETTINGS-NEVER-THE-CONFIG-FILE` (READY S, lane H2); filed `RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE` (READY, security, awaits review w1122d.2) and `RT-FU-A-CONTEXT-FILE-OPENED-FROM-ANOTHER-DEVICE-IS-SAVED-BACK-THROUGH-THIS-ENGINE-BY-HANDLE` (BLOCKED on `RT-FU-A-DEVICE-DRIVING-THIS-ENGINE-OPENS-THE-DIFFS-AND-CONTEXT-FILES-ITS-AGENT-WROTE`'s live read); two subtasks more than the counts that follow · after review w1122b.5 2026-11-22: passed `RT-FU-A-COMPUTER-USING-A-PHONES-AGENTS-IS-HANDED-THE-PICTURES-IN-THE-CHATS-IT-MAY-READ` (READY S: chat pictures only, on the look list) and `RT-FU-A-COMPUTER-GIVEN-RUN-CHATS-OPENS-THE-CHAT-IT-STARTED-AND-STARTS-ONE-BY-AGENT` (READY S: on the chat list only, the attach read requiring the computer's own scope), and filed and passed `RT-FU-A-PHONE-CHANGING-A-COMPUTERS-LEVEL-KEEPS-ITS-CREDENTIAL-AND-ITS-ACCEPT` (READY S, from Eternia `MC-FU-A-COMPUTER-LOSES-THE-PHONES-AGENTS-UNTIL-IT-ACCEPTS-AGAIN-AFTER-A-LEVEL-CHANGE`; one subtask more); the three are one hermes lane, in that order · after lane w1122b-hmsplit 2026-11-22: `RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS` built c6332a4d2f (reads `runtime.agent.files.virtual` in the look allowlist, writes the new `runtime.agent.files.virtual.write` in no computer allowlist), LIVE CHECK (waits on Eternia `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA`'s reverse-route read), so its READY mentions below are history · after lane w1122b-emu2 2026-11-22: closed `RT-FU-A-PHONES-REVOKE-TELLS-THE-COMPUTER-SO-IT-DROPS-ITS-ACCEPT` DONE 41d43752a4 (read live on the emulator: the phone's Off dropped the computer's accept), so its mentions below are history (one subtask fewer) · after lane w1122b-hmfour 2026-11-22 (rows 2-4): `RT-FU-A-PHONES-REVOKE-TELLS-THE-COMPUTER-SO-IT-DROPS-ITS-ACCEPT` built 41d43752a4 and `RT-FU-A-DEVICE-DRIVING-THIS-ENGINE-OPENS-THE-DIFFS-AND-CONTEXT-FILES-ITS-AGENT-WROTE` built f5d28a5ab3, both LIVE CHECK (each waits on its Eternia row's live read), so their READY mentions below are history; `RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN` (group phone-harness) built cd23f961b9, LIVE CHECK; filed `RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS` (READY S, awaits a review batch; one subtask more) · after lane w1122b-hmfour 2026-11-22: `RT-FU-A-SAVED-FAILED-TURNS-HISTORY-READ-DROPS-THE-STORED-PROVIDER-CODE` closed DONE fd0389c226 (Eternia mirror re-synced; Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO` woken for its saved-row live read), so every mention of it below is history (one subtask fewer) · after review w1122b.3 2026-11-22: passed `RT-FU-A-SAVED-FAILED-TURNS-HISTORY-READ-DROPS-THE-STORED-PROVIDER-CODE` (READY, XS), `RT-FU-A-PHONES-REVOKE-TELLS-THE-COMPUTER-SO-IT-DROPS-ITS-ACCEPT` (READY, S; the offline retry triaged out) and `RT-FU-A-DEVICE-DRIVING-THIS-ENGINE-OPENS-THE-DIFFS-AND-CONTEXT-FILES-ITS-AGENT-WROTE` (READY, M; `config.yaml` held back until the owner answers); the last two (filed by w1122b-emu and w1122b-agentfiles) were never counted here: two subtasks more than the counts that follow; the two mentions of Eternia's Qwen sign-in name row (closed DONE c675c5d0cd0) now name it in words; `RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN` (passed, phone-harness) is not counted here · after lane w1122b-refusal2 2026-11-22: `RT-FU-A-SEAT-MOVED-TO-A-COPY-IS-ANNOUNCED-UNDER-THE-COPY-AT-ONCE` closed DONE 43903e8528 (read live: the seat is listed under the copy right after Make my own copy), so every mention of it below is history (one subtask fewer); filed `RT-FU-A-SAVED-FAILED-TURNS-HISTORY-READ-DROPS-THE-STORED-PROVIDER-CODE` (READY, awaits a review batch; the history read drops the `provider_code` ee150f7b7e stores; Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO` waits on it; one subtask more) · after lane w1122b-hmseat 2026-11-22: closed `RT-FU-A-FAILED-TURNS-SAVED-ERROR-CARD-DROPS-THE-PROVIDERS-OWN-REFUSAL-CODE` DONE ee150f7b7e (a saved failed turn's `error_surface` carries `provider_code`; Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO` woken), so every mention of it below is history and open is now 7 subtasks; the uncounted `RT-FU-A-SEAT-MOVED-TO-A-COPY-IS-ANNOUNCED-UNDER-THE-COPY-AT-ONCE` is built (43903e8528) and now LIVE CHECK · after review w1122b.2 2026-11-22: passed `RT-FU-A-FAILED-TURNS-SAVED-ERROR-CARD-DROPS-THE-PROVIDERS-OWN-REFUSAL-CODE` (READY, filed by w1122b-refusal; Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO` waits on it), one subtask more; `RT-FU-AN-AGENT-PLACED-NOWHERE-TELLS-ETERNIA-IT-SHIPS-WITH-ETERNIA-OR-WHAT-IT-IS-BASED-ON` (filed by w1122b-agentsD, passed by review w1122b.1) closed DONE b0394fbb6b (w1122b-hmorigin) and was never counted here; the copy rows `RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE` and `RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED` (DONE eb70a3779c), the second-copy row `RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT` (DONE 220ed9afac) and the refusal-code row `RT-FU-A-PROVIDERS-OWN-REFUSAL-CODE-INSIDE-ITS-ERROR-DETAILS-IS-DROPPED` (DONE 9ef9e164fa) are closed, so every mention of them below, the "Open subtasks now 9" list included, is history; `RT-FU-A-SEAT-MOVED-TO-A-COPY-IS-ANNOUNCED-UNDER-THE-COPY-AT-ONCE` and `RT-FU-A-CHAT-MOVED-ONTO-AN-INSTANCE-LEAVES-NO-EMPTY-CHAT-BEHIND` serve Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` and are not counted here; open now, 8 subtasks: `RT-FU-A-FAILED-TURNS-SAVED-ERROR-CARD-DROPS-THE-PROVIDERS-OWN-REFUSAL-CODE` (READY), `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` (READY, owner GitHub step), `RT-FU-A-PLACED-AGENTS-LENS-TRIGGER-AND-HARNESS-QUERY-ARE-READ-LIVE-IN-ETERNIA` (LIVE CHECK), `RT-FU-A-PHONE-SERVE-STARTS-NO-WORK-GIT-OR-MESSAGING-STEP-ITS-PROFILE-SWITCHES-OFF` (LIVE CHECK, handed off by w1122b-emu after its emulator read), `RT-FU-RIPGREPS-MATCHER-LOADS-ON-A-PHYSICAL-ANDROID-PHONE` (owner sitting), and DEFERRED `RT-FU-AN-ANDROID-PHONE-WHOSE-MATCHER-DOES-NOT-LOAD-STILL-SEARCHES-WITH-THE-REGEX-PACKAGE`, `RT-SCHEDULE-SYNC-AND-KNOB-2` and `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` · handoff 2026-11-22 (w1122b-rulings): owner said "yes go as reccomended" to w1122b owner list item 5, option (a) — moved to Eternia `TASK-MISSION-CONTROL-ON-MAC`, statuses kept: `RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE` and its waiter `RT-PHONE-FILE-TOOLS-TAKE-THE-SAME-ARGUMENTS-AS-ON-DESKTOP-WITH-RIPGREPS-ENGINE-IN-PROCESS`; two subtasks fewer than the counts on this line · after review w1118a.92 2026-11-22: passed the device read `RT-FU-A-PHONE-SERVE-STARTS-NO-WORK-GIT-OR-MESSAGING-STEP-ITS-PROFILE-SWITCHES-OFF` and the QA-copy read `RT-FU-A-PLACED-AGENTS-LENS-TRIGGER-AND-HARNESS-QUERY-ARE-READ-LIVE-IN-ETERNIA` (both LIVE CHECK); filed `RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE` (READY, S, moved from Eternia) · after lane w1118a-helperappr 2026-11-22: closed `RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS` DONE 626b56a694 (archived; landed 9589e9ab15: a dispatched helper's approvals follow its root lead's policy, no expiry on a person-wait, read live on Linux) and filed Eternia `QA-FU-THE-MODEL-FIXTURE-RUNS-A-DIRECTIVE-QUOTED-IN-A-HELPERS-DELIVERED-REPLY` (seen live); one subtask fewer than the counts that follow · after lane w1118a-gates 2026-11-22: closed the class row `RT-FU-A-PHONE-RUNS-A-FEATURE-ONLY-WHEN-ITS-PROFILE-SWITCHES-IT-ON` DONE 21e02913fa (archived; every feature gate over a switched-off module asks `module_presence.runs_here`) and filed `RT-FU-A-PHONE-SERVE-STARTS-NO-WORK-GIT-OR-MESSAGING-STEP-ITS-PROFILE-SWITCHES-OFF` (LIVE CHECK, the device read, awaiting review); no change to the counts that follow · after lane w1118a-phfiles 2026-11-22: closed `RT-FU-THE-PHONE-GATE-JUDGES-THE-CODE-BEHIND-A-PHONE-AGENTS-FILE-TOOLS` DONE 3bfe7ac796 and `RT-FU-A-PHONE-NEVER-ASKS-THE-GIT-PROGRAM-TO-CHECK-A-PROJECT-BRAINS-REMOTE` DONE 8b2479b1c3 (both archived; the first woke `RT-FU-A-REGEX-SEARCH-ON-THE-ANDROID-EMULATOR-RUNS-THE-SHIPPED-MATCHER` to READY), and filed the class row `RT-FU-A-PHONE-RUNS-A-FEATURE-ONLY-WHEN-ITS-PROFILE-SWITCHES-IT-ON` (READY, awaiting review); no change to the counts that follow · after lane w1118a-regex 2026-11-21: closed `RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID` DONE 8bfedd71b4 (archived) and filed `RT-FU-A-REGEX-SEARCH-ON-THE-ANDROID-EMULATOR-RUNS-THE-SHIPPED-MATCHER` (BLOCKED on `RT-FU-THE-PHONE-GATE-JUDGES-THE-CODE-BEHIND-A-PHONE-AGENTS-FILE-TOOLS`) and `RT-FU-AN-ANDROID-PHONE-WHOSE-MATCHER-DOES-NOT-LOAD-STILL-SEARCHES-WITH-THE-REGEX-PACKAGE` (NEEDS PLAN), both awaiting review; no change to the counts that follow · after review w1118a.88 2026-11-21: filed and passed the hermes half of Eternia `MC-FU-A-RETIRED-AGENTS-SAVED-CHAT-REOPENS-FROM-THE-AI-CHAT-HISTORY`, closed DONE c6450855be 2026-11-21 by w1118a-pairs (archived); no change to the counts that follow · task: runtime-followups · after review w1118a.87 2026-11-21: passed the regex plan's three build rows (the Android one, closed DONE 8bfedd71b4 2026-11-21 by w1118a-regex, archived; `RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE`, filed by w1118a-rgplan, not yet counted here; the third, the native matcher, closed DONE 8e59cd8580 2026-11-21 by w1118a-rgA, archived, and filed `RT-FU-THE-PHONE-GATE-JUDGES-THE-CODE-BEHIND-A-PHONE-AGENTS-FILE-TOOLS`, not yet counted here); three subtasks more than the counts that follow · after review w1118a.86 2026-11-21: passed and split `RT-PHONE-FILE-TOOLS-TAKE-THE-SAME-ARGUMENTS-AS-ON-DESKTOP-WITH-RIPGREPS-ENGINE-IN-PROCESS` (filed by w1118a-coord on the owner's ruling, not yet counted here) into `RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT` (READY, M, ships first) and itself (NEEDS PLAN, L: the in-process regex engine); two subtasks more than the counts that follow · after review w1118a.85 2026-11-21: passed `RT-FU-A-HIDDEN-COPY-IS-IN-LIVE-USE-WHEN-IT-HOLDS-A-LIVE-CHAT-NOT-BY-A-14-DAY-WINDOW` (filed by w1118a-coord on the owner's ruling, not yet counted here; done-when corrected: the cleanup tests the chat pointer apart from the move ledger's saved chats); one subtask more than the counts that follow · after review w1118a.84 2026-11-21: passed `RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED`, `RT-FU-A-CHAT-OPENED-ON-AN-AGENTS-BARE-NAME-NO-LONGER-MAKES-A-HELD-ROW` and `RT-FU-THE-LAST-READERS-THAT-GUESS-AN-AGENTS-HIDDEN-COPY-NAME-ASK-FOR-ITS-PLACED-INSTANCE` (filed by w1118a-mint, not yet counted here; they start after w1118a-mint's two TAKEN rows land), passed `RT-FU-A-BUNDLED-INSTALLS-SWITCHES-READ-OUTSIDE-THE-READ-SEAM-HOLD-TOO` narrowed to its one live guess (already counted by w1118a-overlay), filed `RT-FU-A-VIEW-ONLY-DEVICE-CANNOT-READ-AN-AGENTS-PROJECT-FILES` (READY XS, security: a view-only device reads an agent's project files); four subtasks more than the counts that follow · after review w1118a.83 2026-11-21: passed `RT-FU-A-BUNDLED-AGENT-CANNOT-START-A-LOCAL-MCP-SERVER-BY-WRITING-ANOTHER-PROFILES-CONFIG` (READY, urgent, filed by w1118a-bundle and not yet counted here: confirmed in code; fork seam the eternia-harness `pre_tool_call` hook); `RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG` stays DECISION with its question re-asked plainly; `RT-FU-A-BUNDLED-AGENT-PROFILE-TURNS-ON-LOCAL-MCP-SERVERS-ONLY-WITH-AN-APPROVAL` closed DONE da76b6b947 meanwhile; one subtask more than the counts that follow · after review w1118a.82 2026-11-21: passed `RT-FU-A-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-RUNS-WHEN-IT-IS-THE-FIRST-TURN-AFTER-HERMES-STARTS` (READY, now XS: its fix landed in 901df41f03 under the pydantic row; a Linux live read is left) and `RT-FU-A-CHAT-WHOSE-FIRST-TURNS-FAILED-SENDS-THE-AGENTS-FULL-PROMPT-AFTERWARDS` (READY; its own root, not folded); passed as DECISIONs, questions kept, `RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG` and `RT-FU-A-BUNDLED-AGENT-PROFILE-TURNS-ON-LOCAL-MCP-SERVERS-ONLY-WITH-AN-APPROVAL` (filed by w1118a-switch, not yet counted here); two subtasks more than the counts that follow · after review w1118a.80 2026-11-21: passed `RT-FU-A-SWITCHED-OFF-PROVIDER-STAYS-OUT-OF-THE-PROVIDER-LISTS-SIGN-INS` (READY, already counted by w1118a-e1), `RT-FU-A-PHONE-AGENT-WITH-ITS-OWN-PROFILE-SENDS-WITHOUT-PYDANTIC` (filed by w1121-hpc and not yet counted here; since closed DONE 901df41f03, read live on the owner's phone) and the corrected design on `RT-FU-A-SAVED-PROFILE-CONVERSATION-OUTSIDE-A-GROUP-IS-KEPT-BUT-NEVER-BECOMES-AN-AGENTS-CHAT` (BLOCKED on the Windows census); filed `RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE` (READY, awaits a review batch: the root flaw under the pydantic row); two subtasks more than the counts that follow · after review w1118a.79 2026-11-21: `RT-FU-A-SAVED-PROFILE-CONVERSATION-OUTSIDE-A-GROUP-IS-KEPT-BUT-NEVER-BECOMES-AN-AGENTS-CHAT` and `RT-FU-AN-AGENT-ROOMS-LAUNCHER-REQUESTS-HAVE-NO-TEST` (filed by w1118a-retireconv, not yet counted here) passed and stay READY (their source, `RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT`, closed DONE e0b7134111); two subtasks more than the counts that follow · after w1121-hdm 2026-11-21: filed and closed DONE `RT-FU-A-PHONE-SIGNED-IN-BEFORE-AN-UPGRADE-GETS-A-DEFAULT-MODEL-TOO` bd26283c77 (the upgrade edge of `RT-FU-A-PHONE-SIGNED-IN-TO-ONE-PROVIDER-GIVES-ITS-AGENTS-NO-MODEL`: serve start reconciles the default model of an install already signed in to exactly one provider), so its mention here is history; no new rows; counts unchanged · after w1118a-sw74-c 2026-11-21: filed `RT-FU-A-PHONE-SIGNED-IN-TO-ONE-PROVIDER-GIVES-ITS-AGENTS-NO-MODEL` (from Eternia `MC-PHONE-NEW-CHAT-STARTS-WITH-NO-MODEL`, which closed REFUTED onto it, so that mention is history; read in code, awaits a review batch); one subtask more than the counts that follow · after w1118a-sw73-mc 2026-11-21: filed `RT-FU-A-REALM-PULL-PREVIEW-COUNTS-THE-REALM-MANIFEST-AS-AN-ARTIFACT` (closed DONE ef51796310 by w1118a-sw74-hm 2026-11-21, so its mention here is history); Eternia `MC-FU-A-REALM-UPDATE-BANNER-NAMES-WHAT-A-PULL-WOULD-CHANGE` closed DONE e4b8385af63 (Eternia main 469b2934c6a), so its mention below is history · after w1118a-sw69-doors 2026-11-21: closed DONE `RT-FU-THE-FORK-PLUGINS-REACH-HERMES-CORE-ONLY-THROUGH-ITS-PUBLIC-DOORS` 8c3eaadc90 (upstream's boundary lint and the import-layers gate green on main with neither baseline raised: the fork plugins import the runtime only through published doors `agent_runtime/plugin_doors/`, serve_lane builds Telegram through `platform_registry`, the usage-fetcher set lives in the fork; plan docs/agent-runtime-harness/planned/fork-plugins-public-doors-2026-11-21.md; the merged `RT-FU-THE-USAGE-READ-FAILED-REASON-READS-A-PRIVATE-UPSTREAM-TABLE` is delivered by it and is left for the coordinator's owner close); no new rows; one subtask fewer than the counts that follow · after w1118a-hrt7 2026-11-20: closed DONE `RT-FU-A-REPLY-HERMES-STOPPED-AT-ITS-CONTINUATION-LIMIT-IS-MARKED-CUT-OFF-ON-ITS-TURN` a7eefb9362 (D2: typed `cut_off: "continuation_limit"` on the terminal frame, the turn record and the agent reply row on reload; read live on the Eternia model fixture's `[[qa:cut_off …]]` through the real chat door; Eternia's half, Eternia `MC-FU-A-REPLY-CUT-OFF-AFTER-ITS-CONTINUATIONS-SAYS-NOTHING-OF-IT`, re-vendors `tests/fixtures/reply_cut_off_v1.json`) and `RT-FU-A-QA-COPYS-QWEN-AND-COPILOT-SIGN-INS-COME-FROM-THIS-COMPUTERS-OWN-CLI-LOGINS` ed528b98c9 (D3: one per-provider `BORROWED_LOGINS` table; the Qwen seam sits on the CLI file's one reader, not the seed, RULED on the commit: the seed-only seam left the runtime rung reading and refreshing the owner's `~/.qwen`), both landed a7eefb9362; filed `RT-FU-A-QA-COPY-WITH-THE-COPILOT-PLUGIN-STILL-OFFERS-COPILOT-ACP-MODELS-ON-ITS-CLI-LOGIN` (read in code, awaits a review batch); two subtasks fewer and one more than the counts that follow · after w1118a-hrt5 2026-11-20: closed DONE `RT-FU-AN-AGENTS-TERMINAL-REALM-SYNC-REVERT-ARCHIVES-AGENTS-WITH-NO-COORDINATOR-REVIEW` 0e81629994 (D8: one removal review in `chat_coordinator`, called by office actor-remove and realm sync revert), `RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD` 4a44b2a9c7 (D9: every agent_chat door forwards `lane._instance_handle`'s one value) and `RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL` 29a5e20e09 (D10: one shipped-copy predicate for drift, publish and pull), all landed 90e53f546a and read live on Linux, account C lane namespace (own HRT5 Realm with a file:// team remote); no new rows; three subtasks fewer than the counts that follow · after w1118a-hstream 2026-11-20: closed DONE `RT-FU-ADDING-AN-AGENT-SENDS-EVERY-OPEN-ETERNIA-A-FULL-REFRESH` 3241576394 (landed b2d5996941; D2: `persona.updated` rides beside a new `persona` patch and is covered only for a client declaring `persona`; the stream golden generator runs clean and the goldens are regenerated, carrying hrt3's owed `events[]`; read live on Linux, account C: a declaring subscriber read two patch frames per add and no core; Eternia's own copy still takes one core per add until its `persona` fold and the goldens' re-vendor land, handed to the coordinator for an Eternia lane); one subtask fewer than the counts that follow · after w1118a-hrt4 2026-11-20: closed DONE `RT-FU-A-HERMES-UPDATE-MAKES-EVERY-REALM-ASK-TO-PUBLISH-ITS-BUILT-IN-SKILL` 1d0b69ad73 (landed 572ed14b60; review w1118a.63 D5 (a): a built-in skill equal to this install's shipped copy is never drift and never published, read live on Linux, account C's own realm with a file:// team remote); handed `RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS` to the Windows box (REQUIRES windows: its check passes on Linux and is pinned, 895c398cce; the Windows read is on Eternia QA-WINDOWS-LIVE-READS-OWED-1); filed `RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL` (seen live; since closed DONE 29a5e20e09 by w1118a-hrt5); one subtask fewer and one more than the counts that follow · after w1118a-hsec2 2026-11-20: closed DONE `RT-FU-AN-AGENTS-TERMINAL-OFFICE-REMOVE-SKIPS-THE-COORDINATOR-REVIEW` 01b3649916 (landed 9d796bbb98; an agent's terminal office actor-remove, --local-only included, goes through the one coordinator review; read live on Linux, account C), filed `RT-FU-AN-AGENTS-TERMINAL-REALM-SYNC-REVERT-ARCHIVES-AGENTS-WITH-NO-COORDINATOR-REVIEW` and `RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD` (read in code; both since closed DONE by w1118a-hrt5); one subtask fewer and two more than the counts that follow · after w1118a-hrt3 2026-11-20: closed DONE `RT-ANOTHER-REMOVAL-REACHES-ETERNIA-ONLY-WHEN-ITS-BATCH-FALLS-BACK` 63d2ed994c (D2 (a): a patch frame carries its batch's covered domain events as `events[]`, read live on Linux, account C — an agent's terminal removal rode a patch frame and Eternia's banner said who removed it; Eternia `MC-THE-ACTIVITY-LOG-SAYS-WHO-REMOVED-AN-AGENT` waited on it, since closed DONE 546219f4990) and `RT-FU-THE-DOCTOR-STILL-CALLS-AN-UNSEATED-AGENT-A-DESIGNED-ROSTER-ONLY-ROW` ba0cb6b927 (the doctor names `persona seat-unseated`, and `office actor-restore` for a deleted desk), landed 70ef963fbf; two subtasks fewer than the counts that follow · after w1118a-hsec 2026-11-20: closed DONE `RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET` 7d350bdaa9 (landed 8df9a730d4; review w1118a.62 D1 (a): every CLI coordinator door reads the asker from the terminal's session and the scope only from the store, the five argv scope flags deleted; read live on Linux, account C), filed `RT-FU-AN-AGENTS-TERMINAL-OFFICE-REMOVE-SKIPS-THE-COORDINATOR-REVIEW` (read in code; waits for a review batch); one subtask fewer and one more than the counts that follow · after w1118a-hrt2 2026-11-20: closed DONE d93b842da9 (landed f350c45d7a) Eternia's idle-instance read (`runtime.agent.idle_instances`, a shim over `staff.idle_instances`; review w1118a.53 D8 — Eternia `MC-A-NEW-CHAT-PICKS-THE-IDLE-INSTANCE-THE-RUNTIME-NAMES` was then unblocked, since closed DONE 87a0785a195), an agent's terminal removal recorded as that agent (D7 (a): the terminal carries `HERMES_SESSION_ID`; `request_actor` reads the session first, `--requested-by` never overrides it) and the shipped lead's add-instance refusal naming autonomy and `agent_runtime.coordinator_permissions.max_spawns` (RULED (b); also fixed a double-counted spawn budget), all read live on Linux, account C; filed `RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET` (seen live); three subtasks fewer and one more than the counts that follow · after w1118a-hrun 2026-11-20: closed DONE `RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE` f2f183a6db (review w1118a.58 D2: ended chat turns, requests, delegations and background terminals stay listed 30 min with outcome and finished_at, never a Stop; one policy, `running_work/ended.py`), `RT-FU-AN-AGENT-REQUESTS-OWN-TURN-NAMES-ITS-REQUEST` f2f183a6db (D3: the turn a request starts carries `parent_work_id`), `RT-FU-A-STOPPED-REQUESTS-RESULT-NAMES-NO-AGENT` def8927d28 (D5: the delivery marker names the target with no thread) and `RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF` 1d5de4ce1a (D9: the fork boot sweep closes the cut-off turn's transcript, unanswered tool calls included; upstream's repair untouched), all read live in Eternia on Linux, account C, with the Eternia half 59305679505 and 974c22f392a; filed `RT-FU-A-STOPPED-REQUESTS-TURN-STAYS-RUNNING-AFTER-STOP` (seen) and `RT-FU-AN-AGENTS-FIRST-CHAT-IS-WRITTEN-TO-THE-SHARED-STORE-NOT-ITS-OWN` (seen on disk; Eternia D6 moved here), both reviewed w1118a.59; four subtasks fewer and two more than the counts that follow · after w1118a-hwin 2026-11-20: closed DONE `RT-FU-WINDOWS-REQUEST-CHILD-ENDS-WITH-ITS-SERVES-OWN-JOB` fee580c6ca (review w1118a.57 D10: a Windows request child breaks away from the serve's job through one helper, `_subprocess_compat.popen_breaking_away`; pinned on Linux, the Windows read is on Eternia `QA-WINDOWS-LIVE-READS-OWED-1`) and `RT-FU-ADD-INSTANCE-CLI-REFUSALS-CONTRADICT-EACH-OTHER` 89d8b736a5 (D13: both --add-instance doors mint a missing placement id; read live), closed REFUTED `RT-FU-A-MESSAGE-QUEUED-BEHIND-A-BUSY-CHAT-RUNS-AFTER-A-SERVE-RESTART` fee580c6ca (D11: reproduced live, the queued send ran on the next serve); filed `RT-FU-DASHBOARD-GATEWAY-BUTTONS-SPAWN-THROUGH-THE-ONE-WINDOWS-BREAKAWAY-RULE` (read in code) and `RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF` (seen), both waiting for a review batch; three subtasks fewer and two more than the counts that follow · after w1118a-hfu3 (2) 2026-11-20: closed DONE `RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE` 7fc184a5f2 (review w1118a.53 D10: one check, `persona_lifecycle.is_agent_copy`, serves the template skip and the copy delete; read live in Eternia on Linux, account C: Presets 2 with a duplicate made, which Delete agent then removed); one subtask fewer than the counts that follow · after w1118a-hfu3 2026-11-19: closed DONE `RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE` 5fa36a548f (an independent copy's own profile is no profile template, judged by the persona record; read live in Eternia on Linux, account C: Presets 2 before and 2 with a copy made, Roster and Local 3; wakes Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`, closed DONE with it) and `RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING` 4260057ce0 (a drained serve joins its settle pusher, delivery drain and queued-send dispatcher, the upstream adapter shim shuts its loop's default executor down, a conftest stops the build sweep; `tests/agent_runtime/messaging/` sealed); filed `RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE` (read in code; waits for a review batch); one subtask fewer than the counts that follow · after w1118a-hgroup 2026-11-19: closed DONE `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` 168017b784 (a group chat of agents that each have their own profile answers every member's turn; read live through a real `harness serve` and in Eternia on Linux) and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (read live in Eternia's tool console: row, summary and fix); two subtasks fewer than the counts that follow · review w1118a.51 2026-11-19: passed `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` (D12, fork fixture) and `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` (D14, not an edge: the owner's board path), both READY; closed `RT-TWO-PLACEMENTS-AT-ONCE-CAN-GIVE-ONE-AGENT-THE-SAME-NUMBER` (D10) and `RT-AN-AGENTS-DONE-UNDER-A-PARKED-TASK-CLOSES-WHERE-A-LANES-CLOSE-IS-REFUSED` (D13) as edge cases and `RT-OWNERS-OLD-NEKO-MEMORY-STAYS-IN-THE-TEAM-REPO` (D11) on the ruling; three subtasks fewer than the counts that follow · after w1118a-hwork 2026-11-19: closed DONE `RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE` 92d350be97 (a close from Eternia's board, an agent's done and the engine's done now wake the rows waiting on the row and step its task, as a lane's close does; read live on Linux through a real `harness serve` on a sandbox brain: the owner's close woke the waiting subtask and turned the task READY, the agent's done of the last subtask archived the task) and filed `RT-AN-AGENTS-DONE-UNDER-A-PARKED-TASK-CLOSES-WHERE-A-LANES-CLOSE-IS-REFUSED` and `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` (read in code; edges; wait for a review batch); one subtask more than the counts that follow · after w1118a-hfu2 2026-11-19: closed DONE `RT-A-BOARD-CLOSE-IN-THE-LAUNCHER-OR-BACKEND-BRAIN-NEVER-ARCHIVES-ITS-TASK` fcdb0a5818 (a close from Eternia's board in a launcher- or backend-brain slot reads hermes's brain beside the checkout and archives the task when its last subtask closes; read live on Linux through a real `harness serve` on a sandbox launcher-brain slot: the owner's close of the last subtask archived the task, and with hermes's brain absent it stayed open) and `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` c0718e44de (a messaging-folder fixture writes runtime status with no thread); filed `RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING` (seen; waits for a review batch); one subtask fewer than the counts that follow · after w1118a-hfu 2026-11-19: closed DONE `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` f16d71a002 (a duplicate of an agent on the main profile keeps the head home's model and none of its files; read live on Linux through a real `harness serve`: the copy's one real turn reached the source's endpoint) and `RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER` 3c21e4805c (the suite runs the Telegram live check against the stand-in); filed `RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING` (seen; waits for a review batch); one subtask fewer than the counts that follow · review w1118a.50 filed and passed `RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE` from Eternia's sync-pull rename row (since closed DONE 7d5ba827252) (READY, D7: the workspace and realm records' pull merges against a baseline); one subtask more than the counts that follow · review w1118a.48 passed hknobs' `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (READY; D5: the second is a read the first's lane makes), hendpoint's `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` (READY, D6; since closed DONE f16d71a002) and htele's `RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER` (READY, D8; since closed DONE 3c21e4805c), filed and passed `RT-A-ROW-CLOSED-FROM-THE-BOARD-LEAVES-ITS-TASK-AND-WAITING-ROWS-AS-THEY-WERE` from Eternia `MC-SUBTASK-HOLD-TO-ARCHIVE` (READY, D1b; Eternia's row since closed DONE 8810835e31f), and closed hdelete's `RT-A-COPY-DUPLICATED-BEFORE-THE-DELETE-DOOR-KEEPS-ITS-PROFILE` as an edge case (D7, on Eternia's sweep list); net unchanged against the counts that follow · after w1118a-hdelete 2026-11-19: closed DONE `RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED` a2555090c4 (`runtime.agent.delete` deletes a copy you made in one step; read live on Linux through a real `harness serve`: after a retire the directory already drops the instance but the roster keeps the copy, after the delete neither lists it; wakes Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST`) and filed `RT-A-COPY-DUPLICATED-BEFORE-THE-DELETE-DOOR-KEEPS-ITS-PROFILE` (read in code; an edge; waits for a review batch); net subtask count unchanged · after w1118a-hendpoint 2026-11-19: closed DONE `RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT` 57facbaba6 (a copy and a duplicate keep the source's model endpoint and no credential; read live on Linux: a fresh copy of Base answered its first message; wakes Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE`) and filed `RT-DUPLICATING-AN-AGENT-WITH-NO-PROFILE-GIVES-A-COPY-WITH-NO-MODEL` (seen in a unit test; since closed DONE f16d71a002); no net change in subtask count · review w1118a.47 filed and passed `RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED` from Eternia `MC-RETIRED-COPY-STAYS-IN-THE-AGENT-LIST` (READY, D5: one door deletes an independent copy; Eternia's row waits on it); one subtask more than the counts that follow · review w1118a.46 passed hphantom's `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` (READY, D3: one list of root-only keys, one typed issue per profile copy) and bundled-facts' `RT-GROUP-CHAT-NEVER-FINISHES-ENDING-AFTER-ITS-PROCESS-STOPPED-MID-TURN` (READY, D9: premise first through a real serve restart), and filed and passed `RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT` from Eternia `MC-NEW-COPY-CANNOT-ANSWER-ITS-FIRST-MESSAGE` (READY, D2: a copy carries its source's model endpoint, never a credential); one subtask more than the counts that follow · after w1118a-hknobs 2026-11-19: closed DONE `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` 16f69d75f9 (a profile-config copy of a root-only setting is one typed issue on the agent's declaration naming the root; read live on Linux through a real `harness serve`) and REFUTED `RT-GROUP-CHAT-NEVER-FINISHES-ENDING-AFTER-ITS-PROCESS-STOPPED-MID-TURN` (a real serve restart, SIGTERM or SIGKILL, ends the room); filed `RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN` (seen) and `RT-ETERNIA-SHOWS-A-SETTING-WRITTEN-IN-THE-WRONG-CONFIG-FILE` (live check), both waiting for a review batch; net subtask count unchanged · after w1118a-hphantom 2026-11-19: closed DONE `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` 6a913f1568 (a config entry declares an agent only with an identity key; a settings-only entry lists nothing, its knob still read by id; read live on Linux through a real `harness serve`) and filed `RT-A-CHAT-LANE-SETTING-IN-A-PROFILE-CONFIG-DOES-NOTHING-AND-SAYS-NOTHING` (read in code; waits for a review batch); net subtask count unchanged · after w1118a-hbase 2026-11-19: closed DONE `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` d28f26e14d (a placed shipped agent folds the unedited discovered persona on its profile; read live on Linux: one Base Agent plus Neko in Agents and `runtime.agent.directory`, and Base copies; wakes Eternia `MC-AGENTS-LISTS-A-PROFILE-ROW-INSTEAD-OF-THE-SHIPPED-AGENTS`) and filed `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` (seen on disk; waits for a review batch); net one subtask fewer and one more than the counts that follow · after w1118a-hscope 2026-11-19: closed DONE `RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT` 6d13964e96 (the instance verb takes `client_scope` / `--client-scope`, stamps it on all three mints and echoes it; read live on Linux through a real `harness serve`; wakes Eternia `MC-INDEPENDENT-COPY-CHAT-NOT-LINKED-TO-YOUR-ACCOUNT`, since closed DONE in Eternia 52e563fd665, w1118a-mcscope); one subtask fewer than the counts that follow · review w1118a.44 passed mccopy's `RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE` (READY, D4: not an edge case — a realm pull places the shipped Base beside a discovered one; the fold goes in `place_shipped`) and filed and passed `RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT` (READY, D3, security: the instance verb takes the account scope); mccopy's row was in no count, so two subtasks more than the counts that follow · after w1118a-hrealm7 2026-11-19: closed DONE `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED` 61a0d8c186 and design-fix `RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE` e357b28aba (both read live on Linux in QA Realm; the second wakes Eternia `MC-PHONE-REALM-REVERT-SAYS-RESTORED-BUT-THE-CHANGE-STAYS`, since closed DONE d07b7bca00, relayed by review w1118a.44); filed `RT-REALM-DESK-FILE-REMOVED-BY-HAND-LEAVES-A-PUBLISH-THAT-DROPS-THE-AGENT` (seen in a test; not seen live — the by-hand pull read nothing to publish), since closed by the owner; net two subtasks fewer than the counts that follow · after w1118a-hname 2026-11-19: closed DONE `RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER` 1738e2ecae (a nameless create is refused `agent_name_required`, a taken name `agent_name_taken`; read live on Linux; wakes Eternia `MC-NEW-AGENT-WITHOUT-A-NAME-IS-ASKED-FOR-ONE`, since closed DONE 159a1f050a, relayed by review w1118a.43); one subtask fewer than the counts that follow · review w1118a.41 moved `RT-PAIRED-PHONE-CAN-STEER-A-CHAT-IT-MAY-NOT-SEND-TO` to Eternia as `MC-CONSOLE-SLASH-STEER-GOES-WITHOUT-THE-ACCOUNT-SCOPE` (D7: hermes already checks both verbs; Eternia's slash steer sends no scope), closed hrealm7's `RT-REALM-DESK-FILE-REMOVED-BY-HAND-LEAVES-A-PUBLISH-THAT-DROPS-THE-AGENT` as an edge case (D9: only a hand-edited realm) and passed bundled-place's `RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER` (READY, D8: a nameless create is refused, as the design's section 4 rules); two subtasks fewer than the counts that follow · review w1118a.40 filed and passed the design-fix row `RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE` (READY, D11: every operation that adopts the team's copy settles the baseline the drift walk reads, in its own scope) and folded into it qafu18's `RT-REALM-PULL-OF-A-NET-ZERO-DESK-DELETE-LEAVES-OFFICE-LAYOUT-CHANGED` and hrealm6's `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-DRAWING` (both closed), and passed hrealm6's `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED` (READY, D17: a pull that ends a hold clears its sidecar); one subtask fewer than the counts that follow (the design row in, the two folded rows out) · after w1118a-hrealm6 2026-11-19: closed DONE `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` cae912bae4 and `RT-OFFICE-HELD-DESK-SAYS-WHAT-THE-TEAMMATE-DID` 4468dd0c4d (both read live on Linux in QA Realm; the second woke Eternia `MC-OFFICE-DESK-CONFLICT-DIALOG-SAYS-MOVED-WHEN-THE-TEAMMATE-DELETED`, since closed DONE f0918262c7, relayed by review w1118a.42); filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-DRAWING` and `RT-REALM-HELD-DESK-THE-TEAM-PUT-BACK-STILL-SAYS-DELETED`, both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.39 filed and passed `RT-OFFICE-HELD-DESK-SAYS-WHAT-THE-TEAMMATE-DID` (READY, D8: the office snapshot names each held desk's team side, for Eternia's conflict dialog) and regrouped bundled-runtime's `RT-SHIPPED-AGENT-SEAT-EDIT-COUNTS-AS-A-CHANGE` into `bundled-agents-stay-one-agent` (D9, a defect in that task's own work; never counted here); one subtask more than the counts that follow · review w1118a.38 passed with corrections `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` (READY, D5: taking the team's copy settles the realm's office baseline through the office pull's own settling) and closed `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` as an edge case (D6, on Eternia's sweep list); net one subtask fewer than the counts that follow · after w1118a-hrealm5 2026-11-19: closed DONE dee4e42839 `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (both read live), and design-fix `TASK-REALM-DELETE-MEETS-AN-EDIT` closed with both its subtasks; filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` and `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` (an edge), both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.36 passed with corrections hbundle's `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` (READY: one owner of the push-refused tells, `cannot lock ref` added; a repeat of archived `RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE`) and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (READY: publish writes only what the content compare says changed), and moved `RT-PHONE-REALM-CONFLICT-HAS-NO-WAY-OUT` and `RT-REALM-LOCAL-EDIT-OUTLIVES-A-TEAMMATES-DELETE` out to design-fix task `TASK-REALM-DELETE-MEETS-AN-EDIT` (one gap: no rule for a delete meeting an edit); net two subtasks more and two fewer than the counts that follow · review w1118a.31 corrected the hsurf segment below: the Eternia Home row it woke is closed, not open (DONE a8c7bead20), and so is `TASK-HOME-SHELL-FOLLOWUPS-3` (099dc3c1bd) · review w1118a.30 closed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` as an edge case (D6) and filed and closed `RT-SURFACE-NOTE-RESENT-EVERY-TURN-IN-MOA-AND-CODEX-MODES` as an edge case (D7), both on Eternia's sweep list (one root: what the model was last told is read from the transcript); net one subtask fewer than the counts that follow · after w1118a-hsurf 2026-11-19: closed DONE `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` 7787bd8a8f (a changed surface prompt rides the turn's tail; the stored prompt stays byte-identical), which wakes Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` for its live read (since closed DONE in Eternia a8c7bead20, w1118a-home4; Eternia `TASK-HOME-SHELL-FOLLOWUPS-3` closed DONE 099dc3c1bd); filed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` (an edge, waits for a review batch) · was: review w1118a.29 filed and passed `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` (ready; one subtask more than the counts that follow) · after w1118a-folderedit 2026-11-19: closed DONE `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED` fff568201e, read live in Eternia before and after on fresh lane namespaces (the folder is saved, no sync banner) · was: review w1118a.23 moved w1118a-hrealm's two realm rows (the persona-api-mode one, since closed DONE 68a504deb7, and `RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK`) out to `TASK-REALM-MEMBERS-SEE-WHAT-THE-OWNER-SHARES`; the counts that follow never held them · 5 subtasks open on 2026-11-19 after w1118a-hprov (closed DONE: the catalog's sign-in field 2e5f209c5d, which woke Eternia `MC-FU-COMPOSER-SILENT-WHEN-THE-CHATS-PROVIDER-IS-SIGNED-OUT` (since closed DONE in Eternia 9f1bb6eccd, w1118a-mcfu8); the phone readiness row cc78fac067, read first on a phone bundle; closed as churn on review w1118a.21 D6: the fresh Default office row, read on a desktop serve — the one effect found filed as `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED`, passed by review w1118a.22, since closed DONE; the other four wait on the owner) · was: review w1118a.21 filed and passed the sign-in-field and phone-readiness rows and rewrote the fresh-office row (w1118a-hphone2) · 6 subtasks open on 2026-11-19 after w1118a-hphone2 (filed `RT-FRESH-ENGINE-DEFAULT-WORKSPACE-HAS-NO-OFFICE`, waits for a review batch; the phone row the duplicate below merged onto, `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER`, closed DONE 82d80229be in `TASK-PHONE-HARNESS`) · was 5 subtasks open on 2026-11-19 after w1118a-rtfu2 (closed DONE: `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` efc2140d79, `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` 69aab89b99, `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` 4d43a3036c read live on a real model; filed `RT-PHONE-CHAT-TURN-HAS-NO-HARNESS-PARSER`, which review w1118a.19 closed as a duplicate of `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER` (merged onto that row); the other four wait on the owner: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` blocked, three deferred) · was 8 subtasks open on 2026-11-19 after w1118a-realm2 (`RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` closed DONE afb168e807, read live on two Eternia QA copies; `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` also read right in Eternia's realm sheet: two new namespaces' first pulls read In sync with nothing to publish) · was review w1118a.16 (Eternia review batch): passed `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` (both ready), closed `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` (a red on main is not a row — owner 2026-11-15) · 9 subtasks open on 2026-11-19 after w1118a-rtfu (closed DONE: `RT-READ-ONLY-TREE-REMOVAL-COPIED-THREE-TIMES` 2967e07ab1, `RT-PHONE-BUILD-STALE-SEED-BLAMES-AN-EXTRA` d197d1c389, `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` 34e21dbfe8; filed `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER`, waits for a review batch; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` waits on a real-model sitting and `RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` on an Eternia QA read, each with a handoff; `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` filed by w1118a-hphone wait for review) · was 9 subtasks open on 2026-11-19 after w1118a-hbundle3 (`RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` closed DONE d5012e054b: 18.86 -> 15.66 MiB arm64, the limit re-based by ruling, Eternia's edit) · was 11 subtasks open on 2026-11-19 after w1118a-hbundle (`RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED` closed DONE 75c5913569; `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` stays READY with a handoff — 28.80 -> 23.30 MiB landed 5febe61183, gap per part on the row; `RT-DESKTOP-BUNDLE-VERIFY-REFUSES-THE-DULWICH-REALM-SYNC` closed DONE 9962731e85 (w1118a-hbundle)) · was 11 subtasks open on 2026-11-19 after review w1118a.10 (6 ready, 1 live check, 1 blocked, 3 deferred; the review passed `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` and filed `RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED`, from Eternia `TASK-DISTRIBUTION-FOLLOWUPS`) · was 9 subtasks open on 2026-11-19 after review w1118a.8 (4 ready, 1 live check, 1 blocked, 3 deferred; `RT-PHONE-ANDROID-TLS-IGNORES-DEVICE-CERTIFICATES` closed as a documented edge case on the owner's standing call) · was, on 2026-11-17 after w1116b-rtfu: `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, `RT-CLOSE-NAMES-SIBLING-TASK-LINES-THAT-STILL-MENTION-THE-ROW` and `RT-REALM-OWNER-RECORD-LISTS-A-WORKSPACE-IT-DELETED` closed DONE; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` stays READY for its real-model live re-run only; `RT-SKILL-NAME-READ-TWO-WAYS` filed, waits for a review batch; was 5 subtasks open on 2026-11-16 after w1115e-q4 (2 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`; 1 blocked on an owner sitting; 2 deferred; closed since: `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM` DONE, `RT-LENS-RECIPE-HISTORY-AND-COUNTS-NOT-BUILT` as a documented edge, owner 2026-11-16 "sounds good" on review w1115e.19); was 7 subtasks open on 2026-11-16 after owner "Accept all" on B68 (4 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, and the two narrow realm-sync fixes `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM`; 1 blocked on an owner sitting: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH`; 2 deferred: `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR`, `RT-SCHEDULE-SYNC-AND-KNOB-2`; closed: `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS` and `RT-WORK-READS-MIX-ROWS-AND-HISTORY-FROM-TWO-COMMITS` as edges, `RT-READY-FRAME-SHELL-KEY-DOCUMENTED-NEVER-SENT` folded; each keeps its own status; its `from:` segment names the task it came from); was "7 subtasks open on 2026-11-15" · opened 2026-11-15 by w1115e-rr3 as this queue's one standing follow-ups task (owner 2026-11-15: "yea do the cleanup"; a follow-up goes here, not under a per-task `-FOLLOWUPS` task): received `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF-FOLLOWUPS` (2), `TASK-SHARED-WORK-V1-FOLLOWUPS` (1), `TASK-ONE-TURN-RECORD-FOLLOWUPS` (1), and the hermes rows of Eternia `TASK-PHONE-HARNESS-FOLLOWUPS` (1) and `TASK-CONSOLE-TOP-BAR-AND-MENU-PROPOSAL-FOLLOWUPS-2` (1) and backend `TASK-WORKSPACE-ABSORBS-PROJECTS-FOLLOWUPS-2` (1); `TASK-ETERNIA-LENS-FOLLOWUPS-2`'s 5 rows are Eternia's, now under Eternia `TASK-MISSION-CONTROL-FOLLOWUPS`; `TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` stays (its one row is a security row), each closed as merged · handoff 2026-11-20 (review w1118a.61): passed the idle-instance read for Eternia, the terminal-removal record (D7) and the shipped lead's budget refusal (all three closed DONE d93b842da9 by w1118a-hrt2); moved `RT-FU-A-PLACED-INSTALL-LISTS-A-SECOND-UNMARKED-BASE` to Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT` (D8); one subtask fewer than the counts that follow · review w1118a.62: passed `RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET` (D1: all four CLI coordinator doors read the asker from the session and the scope from the store, the argv scope flags deleted), `RT-ANOTHER-REMOVAL-REACHES-ETERNIA-ONLY-WHEN-ITS-BATCH-FALLS-BACK` (D2: covered domain events ride the patch frame) and `RT-FU-THE-DOCTOR-STILL-CALLS-AN-UNSEATED-AGENT-A-DESIGNED-ROSTER-ONLY-ROW`; closed the create-method test row under the owner's reds rule and the probe agent's chat as an edge case; two subtasks fewer than the counts that follow · review w1118a.63: passed `RT-FU-AN-AGENTS-TERMINAL-OFFICE-REMOVE-SKIPS-THE-COORDINATOR-REVIEW` (security read, size S), `RT-FU-A-HERMES-UPDATE-MAKES-EVERY-REALM-ASK-TO-PUBLISH-ITS-BUILT-IN-SKILL` (D5: the build owns a built-in skill's text) and `RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS`; filed and passed `RT-FU-ADDING-AN-AGENT-SENDS-EVERY-OPEN-ETERNIA-A-FULL-REFRESH` (D2); one subtask more than the counts that follow · review w1118a.64: passed `RT-FU-AN-AGENTS-TERMINAL-REALM-SYNC-REVERT-ARCHIVES-AGENTS-WITH-NO-COORDINATOR-REVIEW` (security read, D8), `RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD` (D9) and `RT-FU-A-BUILT-IN-SKILL-THE-TEAM-CARRIES-AT-ANOTHER-HERMES-VERSION-IS-HELD-ON-PULL` (D10), all READY and size S, no shared files, since closed DONE by w1118a-hrt5; the line now says Eternia `MC-THE-ACTIVITY-LOG-SAYS-WHO-REMOVED-AN-AGENT` is closed · review w1118a.65: passed `RT-FU-ADDING-AN-AGENT-CAN-STILL-SEND-A-FULL-REFRESH-FROM-A-SCOPE-RECONCILE` (D3, reproduce first), since closed DONE d6b1f62810 by w1118a-hrt6 (reproduced 2 of 4 adds; the new persona record waited for its event through a cold readiness walk; 12 of 12 adds clean after); the line now says Eternia `MC-A-NEW-CHAT-PICKS-THE-IDLE-INSTANCE-THE-RUNTIME-NAMES` is closed · review w1118a.66: passed `RT-FU-A-QA-COPYS-QWEN-AND-COPILOT-SIGN-INS-COME-FROM-THIS-COMPUTERS-OWN-CLI-LOGINS` (D3, READY: one per-provider fence), ruled the DECISION on `RT-FU-THE-SHIPPED-MISSION-LEAD-READS-NO-REPOS-RULES` (D4: the lead works on its seated instance; now BLOCKED on Eternia `MC-OUTSIDE-NEW-CHAT-OPENS-ON-AN-UNSEATED-INSTANCE`), and filed `RT-FU-A-REPLY-HERMES-STOPPED-AT-ITS-CONTINUATION-LIMIT-IS-MARKED-CUT-OFF-ON-ITS-TURN` (D2, READY: hermes marks a reply cut off at its continuation limit, for Eternia `MC-FU-A-REPLY-CUT-OFF-AFTER-ITS-CONTINUATIONS-SAYS-NOTHING-OF-IT`) · review w1118a.67: filed and passed `RT-FU-A-PROVIDERS-OWN-REFUSAL-CODE-INSIDE-ITS-ERROR-DETAILS-IS-DROPPED` (D1, READY: the provider's nested refusal code reaches Eternia, for Eternia `MC-FU-A-PROVIDER-THAT-FORBIDS-THIS-SIGN-IN-IS-SHOWN-AS-A-SIGN-IN-TO-REDO`) and `RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT` (D2, READY: an operator command in the serve is never judged as a chat's agent, for Eternia `MC-FU-A-SECOND-INDEPENDENT-COPY-IS-REFUSED-AS-AN-EXHAUSTED-SPAWN-BUDGET`); triaged out `RT-FU-A-QA-COPY-WITH-THE-COPILOT-PLUGIN-STILL-OFFERS-COPILOT-ACP-MODELS-ON-ITS-CLI-LOGIN` (D3, edge case, closed onto Eternia's edge-case list); two subtasks more and one fewer than the counts that follow · review w1118a.69: passed `RT-FU-A-SAVED-API-KEY-IS-NEVER-USED-WHILE-THE-CHOSEN-SIGN-IN-IS-EXHAUSTED` (D1: keep the chosen sign-in and say why, no silent key spend), `RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED`, `RT-FU-THE-FORK-PLUGINS-REACH-HERMES-CORE-ONLY-THROUGH-ITS-PUBLIC-DOORS` (now carrying the usage-table crossing) and `RT-FU-A-BARE-KEY-IN-A-STREAM-FRAME-OR-CHAT-LOG-LINE-IS-NOT-ASKED-OF-THE-ONE-SCRUBBER`; triaged out as edge cases, closed 2026-11-21 (w1118a-mop69): `RT-FU-A-HONOURED-ANTHROPIC-CREDENTIAL-SOURCE-SETTING-IS-LOGGED-AS-AN-IGNORED-KEY`, `RT-FU-A-DELETED-AGENT-COPY-LEAVES-THROUGH-THE-ONE-PROFILE-REMOVER`, `RT-FU-A-COPY-OF-AN-AGENT-ON-AN-OUTSIDE-MEMORY-SERVICE-KEEPS-THAT-MEMORY`; merged, closed 2026-11-21 (w1118a-mop69): `RT-FU-THE-USAGE-READ-FAILED-REASON-READS-A-PRIVATE-UPSTREAM-TABLE`, `RT-FU-THE-AGENT-PROFILE-SEED-BRIDGE-IS-RE-READ-AT-THE-NEXT-UPSTREAM-MERGE` · handoff 2026-11-22 (wave-start sweep w1122b-sweep): closed `RT-FU-A-SAVED-PROFILE-CONVERSATION-OUTSIDE-A-GROUP-IS-KEPT-BUT-NEVER-BECOMES-AN-AGENTS-CHAT` on the owner's 2026-11-22 word ("no need to support any previous version today its a waste of time"), moved `RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS` to Eternia `TASK-WINDOWS-HANDOFFS` (its Linux half is done; only the Windows read is left), and noted `RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE` as one change with `RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED`; the earlier mentions of the first two above are history; two subtasks fewer than the counts on this line · READY 2026-11-19 · unblocked 2026-11-19: `RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT` closed DONE 6a913f1568 · triage 2026-11-19 (w1118a-triH): owner said "do all the deffered too actually see if it should be archived, its stale and should be archived or we should undefer it" — closed `RT-SKILL-NAME-READ-TWO-WAYS` as churn ("check for churn too"); `RT-SCHEDULE-SYNC-AND-KNOB-2` (owner: schedules stay local until a delete-propagation design) and `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` (waits on the deferred Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF` and a real Discord sitting) kept deferred · review w1118a.52: filed `RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE` (from Eternia `MC-A-COPY-IS-COUNTED-UNDER-PRESETS`, READY) · handoff 2026-11-20 (w1118a-hreq): w1118a-hreq closed DONE RT-FU-A-DELETED-INSTANCES-OLD-CHAT-OPENS-ON-ANOTHER-INSTANCE 4fc62055ba (D13: a retired holder's agent read from its archive; read live in a sandbox, a retired instance's chat moved onto a second instance with its history), RT-AGENT-REQUEST-STILL-RUNNING-WHEN-ITS-SERVE-RESTARTS-IS-PICKED-UP-AGAIN and RT-WINDOWS-STOP-AFTER-ITS-SUPERVISOR-ENDED-REACHES-WHAT-A-REQUEST-LEFT 0ca1c535e9 (D12: result file, re-adoption, named kill-on-close job; read live on Linux, the Windows read is on Eternia QA-WINDOWS-LIVE-READS-OWED-1); filed RT-FU-WINDOWS-REQUEST-CHILD-ENDS-WITH-ITS-SERVES-OWN-JOB, RT-FU-A-RE-ADOPTED-REQUEST-HAS-NO-TIME-BUDGET-BACKSTOP, RT-FU-A-MESSAGE-QUEUED-BEHIND-A-BUSY-CHAT-RUNS-AFTER-A-SERVE-RESTART (review w1118a.57: closed RT-FU-A-RE-ADOPTED-REQUEST-HAS-NO-TIME-BUDGET-BACKSTOP as an edge case, D12; the other two and RT-FU-ADD-INSTANCE-CLI-REFUSALS-CONTRADICT-EACH-OTHER reviewed READY) · review w1118a.58 2026-11-20: filed and passed `RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE` (D2) and `RT-FU-AN-AGENT-REQUESTS-OWN-TURN-NAMES-ITS-REQUEST` (D3) from Eternia's Running now rows, which wait on them, and moved Eternia `MC-DELIVERED-RESULT-FOR-A-STOPPED-REQUEST-NAMES-NO-AGENT` here as `RT-FU-A-STOPPED-REQUESTS-RESULT-NAMES-NO-AGENT` (D5), all READY; passed hwin's `RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF` (D9, READY) and closed hwin's `RT-FU-DASHBOARD-GATEWAY-BUTTONS-SPAWN-THROUGH-THE-ONE-WINDOWS-BREAKAWAY-RULE` as churn (D10); two subtasks more than the counts above · handoff 2026-11-20 (w1118a-hagent): w1118a-hagent closed RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE and RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT (2ae02cbf29, landed b92baed712), filed the idle-instance read, the terminal-removal record and the shipped lead's budget refusal (closed DONE d93b842da9, w1118a-hrt2) · handoff 2026-11-20 (w1118a-hrtfu): closed DONE RT-FU-A-STOPPED-REQUESTS-TURN-STAYS-RUNNING-AFTER-STOP 9e2aeb4231 (the supervisor ends a killed child's turn: stopped for a Stop, interrupted past its budget), RT-FU-AN-AGENTS-FIRST-CHAT-IS-WRITTEN-TO-THE-SHARED-STORE-NOT-ITS-OWN 51e092bc1f (a never-bound instance's first turn writes where its first bind records) and RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE 8da915b449 (workspace and realm records merge field-wise against their baseline: kept, taken or held, resolve record::<family>:<id>), all read live on Linux, account C; freed Eternia's in-app read of a rename kept through a Sync (since closed DONE 7d5ba827252); three subtasks fewer than the counts that follow · handoff 2026-11-20 (w1118a-codex-win-rt): Provider detail codes landed at 9ef9e164fa. The existing provider-refusal row carries the Linux account C live read. The operator identity row still needs its fixture-serve reproduction. · handoff 2026-11-21 (w1118a-sw69-sec): after w1118a-sw69-sec 2026-11-21: closed DONE `RT-FU-A-BARE-KEY-IN-A-STREAM-FRAME-OR-CHAT-LOG-LINE-IS-NOT-ASKED-OF-THE-ONE-SCRUBBER` 46cf1e023f (landed 8f3bb90d0e: the live chat log, the chat history and board cards in the snapshot now ask the one scrubber for a bare key; the stream frame path was already masked; read live on Linux through the CLI); no new rows; one subtask fewer than the counts that follow · handoff 2026-11-21 (w1118a-sw69-keys): after w1118a-sw69-keys 2026-11-21: closed DONE RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED e29b85d1e6 (one key check at set_key and at lease; the run names api_key_control_character) and RT-FU-A-SAVED-API-KEY-IS-NEVER-USED-WHILE-THE-CHOSEN-SIGN-IN-IS-EXHAUSTED ec723f1aa7 (D1 (a): pick and run refuse chosen_credential_unusable, nothing spent from the other kind), both read live on account C's lane namespace with fake keys; Eternia's halves are MC-FU-AN-API-KEY-SAVED-WITH-A-HIDDEN-CHARACTER-FAILS-EVERY-TURN-AS-A-CONNECTION-ERROR (woken) and MC-FU-AN-APPROVED-MODEL-SWITCH-THE-RUNTIME-REFUSES-LEAVES-THE-CHAT-ON-THE-OLD-MODEL-SILENTLY; two subtasks fewer than the counts that follow · handoff 2026-11-21 (w1118a-helperlive): after w1118a-helperlive 2026-11-21: closed DONE `RT-FU-A-HELPER-GIVES-UP-ITS-ROW-AFTER-ONE-UNANSWERED-STEP` c5390d35622a (read live on a real model, Linux, account C, fresh lane namespace: a helper Base dispatched by Neko with a 'name it and stop' brief kept its TAKEN scratch row after its python3 -c read went unanswered for 5 min (block_class unanswered), read the files with read_file and uname -r instead, finished and named the blocked command; no code change) · handoff 2026-11-21 (w1118a-sw71-hm): closed DONE RT-FU-A-NEW-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-CANNOT-TAKE-ITS-FIRST-MESSAGE 1e49345594 (read live: a new chat with Neko on a fresh lane namespace took its first message, model chip qa-fixture) and RT-FU-A-DISCUSSION-ROOM-VIEW-WRITES-RECEIPTS-AND-TIMES-OUT-UNDER-LOAD d9f9737793 (landed 8bb0181168); filed RT-FU-A-GROUP-DISCUSSION-ROOM-VIEW-STILL-WRITES-ITS-TURNS-RECEIPTS (the group lane's view still writes; awaits review) · handoff 2026-11-21 (w1118a-sw71-el): filed RT-FU-A-REALM-STATUS-SAYS-WHAT-A-PULL-WOULD-CHANGE (half 2 of Eternia MC-FU-A-REALMS-UPDATE-BANNER-COUNTS-THE-WHOLE-REALM-AS-INCOMING, seen live) and RT-FU-A-TURN-SETTLE-CARRIES-THE-PROVIDERS-REFUSAL (read in code, from Eternia MC-FU-A-TURN-HERMES-REFUSED-BEFORE-SENDING-STILL-SAYS-RETRY-IN-THE-COMPOSER); both await a review batch; net two subtasks more than the counts that follow · handoff 2026-11-21 (w1118a-sw72-hm): w1118a-sw72-hm: closed DONE RT-FU-A-GROUP-DISCUSSION-ROOM-VIEW-STILL-WRITES-ITS-TURNS-RECEIPTS c622e55759 (record is the adapter contract; group room read live), RT-FU-A-REALM-STATUS-SAYS-WHAT-A-PULL-WOULD-CHANGE 41149a05a7 (incoming_artifact_counts; {} read live on QA Realm; Eternia banner half filed MC-FU-A-REALM-UPDATE-BANNER-NAMES-WHAT-A-PULL-WOULD-CHANGE) and RT-FU-A-TURN-SETTLE-CARRIES-THE-PROVIDERS-REFUSAL a9bd0ae04e (settle carries the redacted provider_refusal; Eternia half landed 5bdf8ea7421); three subtasks fewer than the counts that follow · handoff 2026-11-21 (w1118a-sw74-hm): filed FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-ROSTER-BYPASS-CONTRACT-FILE (fork-hygiene, prepush overrun at this lane's landing acda3c4325); RT-FU-A-REALM-PULL-PREVIEW-COUNTS-THE-REALM-MANIFEST-AS-AN-ARTIFACT closed DONE ef51796310, read live on account B / QA Realm · handoff 2026-11-21 (w1118a-hdoorseam): after w1118a-hdoorseam 2026-11-21: the owner asked for the fork-plugin doors to be published through a fork-only seam so hermes_cli/plugin_validate_private_imports.py returns to upstream bytes; NOT POSSIBLE, nothing changed in code (69d9ebbb87). Tried, in order: (1) a hook or config upstream reads: none, its verdict reads only plugin_api.json, pyproject's package list and the baseline (upstream/main's rewrite too); moving the plugins out of plugins/ is the rejected Stage 7 move; (2) an allowlist upstream loads: plugin_api.json is upstream's file and renders its docs page, the baseline is off limits; (3) a fork wrapper: upstream's test_boundary_lint still reds on the 3 door keys, and a runtime rebind of _public_api is a private upstream import and a core override; (4) the fork's own census: needs (1) or a skip of (3). Loopholes (a door inside upstream's published providers/pm package, a shadow path, TYPE_CHECKING) hide the coupling and were rejected. [up-fp] stays files=228 deleted_lines=878 heavy=1; the plan's section 'A fork-only seam for the publication' and the ledger row record it · handoff 2026-11-21 (w1118a-sw75-hm): w1118a-sw75-hm: closed DONE RT-FU-A-QA-COPY-REWRITES-THE-OWNERS-CHECKOUT-LAUNCHERS (de75e241e7) and RT-FU-A-PHONE-SIGNED-IN-TO-ONE-PROVIDER-GIVES-ITS-AGENTS-NO-MODEL (6508ff7b1a); RT-FU-A-HELPERS-FIXTURE-TURN-AND-A-QUEUED-FOLLOW-UP-ARE-REFUSED-AS-PROVIDER-UNAVAILABLE closed DONE f7b79bea5e under TASK-ONE-HERMES-ONE-PATH. Any mention of them on this line is stale. · handoff 2026-11-21 (review w1118a.77): `RT-A-CHATS-STANDING-GOAL-IS-ITS-OWN-THING-AND-UNTIL-DONE-IS-ONE-USER-OF-IT` passed with a rewrite (upstream's goal engine is the one engine) and waits BLOCKED on the TAKEN `RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT` · handoff 2026-11-21 (w1118a-prepush): FH-PREPUSH-TOUCHED-OVER-BUDGET-ON-THE-ROSTER-BYPASS-CONTRACT-FILE (filed by w1118a-sw74-hm above) is closed REFUTED, merged into FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET (review w1118a.75), which closed DONE 1f174ff9ff: from the shared timing record the roster file (one ~34 s test) runs whole instead of sharding · handoff 2026-11-21 (w1118a-retireconv): w1118a-retireconv: RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT closed DONE e0b7134111, which woke RT-A-CHATS-STANDING-GOAL-IS-ITS-OWN-THING-AND-UNTIL-DONE-IS-ONE-USER-OF-IT to READY · handoff 2026-11-21 (w1118a-e1): after w1118a-e1 2026-11-21: filed `RT-FU-A-SWITCHED-OFF-PROVIDER-STAYS-OUT-OF-THE-PROVIDER-LISTS-SIGN-INS` (from Eternia's Qwen sign-in name row, which waited on it and is since closed DONE c675c5d0cd0; read in code and live, awaits a review batch); one subtask more than the counts that follow · handoff 2026-11-21 (w1118a-goal): after w1118a-goal 2026-11-21: closed DONE `RT-A-CHATS-STANDING-GOAL-IS-ITS-OWN-THING-AND-UNTIL-DONE-IS-ONE-USER-OF-IT` ed85d1c827 (one chat-goal loop, agent_runtime/chat_goal_loop.py; Until done is one user of it), so its mention here is history; woke Eternia `MC-A-SLASH-GOAL-SETS-A-STANDING-GOAL-IN-ANY-CHAT`; no new rows; one subtask fewer than the counts that follow · handoff 2026-11-21 (w1118a-rooms): closed DONE `RT-FU-AN-AGENT-ROOMS-LAUNCHER-REQUESTS-HAVE-NO-TEST` 963c03e620 (test-only: an agent room's queued app-function request rides the admitting Eternia connection with the room/task identity, red under the most-recent-declarer mutation), so its mentions here and on `TASK-ONE-HERMES-ONE-PATH` are history; `RT-FU-A-SAVED-PROFILE-CONVERSATION-OUTSIDE-A-GROUP-IS-KEPT-BUT-NEVER-BECOMES-AN-AGENTS-CHAT` set BLOCKED on the Windows census (`scripts/legacy_route_census.py` 23696e608e; this box pending=0) with its premise corrected: a route keeps no account scope on disk, so the reviewed start-up pass cannot be built and the recommended design adopts on the owner's connection; no new rows; one subtask fewer than the counts that follow · handoff 2026-11-21 (w1118a-connxs): after w1118a-connxs 2026-11-21: closed DONE `RT-FU-A-SWITCHED-OFF-PROVIDER-STAYS-OUT-OF-THE-PROVIDER-LISTS-SIGN-INS` f2113c1410 (a switched-off provider's login is skipped before its probe; read live on a Linux QA copy with the switch in the probed profile's config), so its mentions below are history; the switch in the serve root's config alone did not take on a QA copy (the seam `RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE` names); Eternia's Qwen sign-in name row owed the phone read (since closed DONE c675c5d0cd0); no new rows; one subtask fewer than the counts that follow · handoff 2026-11-21 (w1118a-lead): closed DONE `RT-FU-THE-SHIPPED-MISSION-LEAD-READS-NO-REPOS-RULES` f3b16d9e9f (read live on account C's lane namespace: the shipped lead placed in ws_default by a Home chat, the eternialauncher folder checked on it through Folder slots, its new chat's prompt carried '## eternialauncher — CLAUDE.md'; no code), so its mention on this line is history; filed `RT-FU-A-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-RUNS-WHEN-IT-IS-THE-FIRST-TURN-AFTER-HERMES-STARTS` and `RT-FU-A-CHAT-WHOSE-FIRST-TURNS-FAILED-SENDS-THE-AGENTS-FULL-PROMPT-AFTERWARDS` (both seen live, await a review batch); one subtask fewer and two more than the counts that follow · handoff 2026-11-21 (w1118a-switch): after w1118a-switch 2026-11-21: closed DONE `RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE` 54e22e8441 (landed 61c2456786; its mention above is history; the phone read of a second-profile turn is owed), filed `RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG` and `RT-FU-A-BUNDLED-AGENT-PROFILE-TURNS-ON-LOCAL-MCP-SERVERS-ONLY-WITH-AN-APPROVAL` (both DECISION, passed by review w1118a.82); one subtask fewer and two more than the counts that follow · handoff 2026-11-21 (w1118a-goal): after w1118a-goal 2026-11-21 (2): Eternia `MC-A-SLASH-GOAL-SETS-A-STANDING-GOAL-IN-ANY-CHAT` closed DONE 664ed0107d5, read live with this queue's chat-goal loop (a plain chat continued once per judge; an Until done run stopped on /goal pause and clear), so its mention here is history; no new rows; counts unchanged · handoff 2026-11-21 (w1118a-stub): after w1118a-stub 2026-11-21: closed DONE RT-FU-A-CHAT-WHOSE-FIRST-TURNS-FAILED-SENDS-THE-AGENTS-FULL-PROMPT-AFTERWARDS 015c0a2a20 (so its mentions here are history; its Linux live read is owed and recorded on the closed row); no new rows; counts: one fewer open subtask · handoff 2026-11-21 (w1118a-reach): closed DONE `RT-FU-A-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-RUNS-WHEN-IT-IS-THE-FIRST-TURN-AFTER-HERMES-STARTS` on 901df41f03 with its Linux live read (first turn after serve start a Neko turn on a just-placed instance, fixture reply, second Neko turn too, no 4007); live read owed by `RT-FU-A-CHAT-WHOSE-FIRST-TURNS-FAILED-SENDS-THE-AGENTS-FULL-PROMPT-AFTERWARDS` (closed DONE 015c0a2a20) done 2026-11-21 on hermes 171d81f0ba, account C, model_fixture, fresh namespace e9a1b14b42: a fresh Neko chat's first turn was stopped (interrupted_during_api_call), the next send replied, its context record ctx_2aad608572f1c4b4 carries system_chars 22140 (not 48), and the chat's stored system_prompt in profiles/neko/state.db is NULL, not the mint stub; nothing filed; the mentions of both rows before this segment are history · handoff 2026-11-21 (w1118a-bundle): RT-FU-A-BUNDLED-AGENT-PROFILE-TURNS-ON-LOCAL-MCP-SERVERS-ONLY-WITH-AN-APPROVAL closed DONE da76b6b947 (follow upstream, no approval record); RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG back to DECISION for the owner (option 1 writes the bundled switches into the namespace config.yaml the Developer Edition shares; recommends a narrowed option 2); new subtask RT-FU-A-BUNDLED-AGENT-CANNOT-START-A-LOCAL-MCP-SERVER-BY-WRITING-ANOTHER-PROFILES-CONFIG (READY, needs review); net counts: one subtask closed, one added · handoff 2026-11-21 (w1118a-cfgguard): after w1118a-cfgguard 2026-11-21: closed RT-FU-A-BUNDLED-AGENT-CANNOT-START-A-LOCAL-MCP-SERVER-BY-WRITING-ANOTHER-PROFILES-CONFIG DONE 1884f38db9 (bundled installs refuse write_file/patch to the root's and every profile's config.yaml, and to plugins/eternia-* copies under a home, via the eternia-harness pre_tool_call veto), so its mention here is history; no new rows; counts unchanged · handoff 2026-11-21 (w1118a-overlay): closed DONE `RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG` ec37f4bbbd (owner ruling: the bundled edition holds the shipped profile's install-only switches in memory on every read, nothing written, local_runtime.enabled, delegation.worktree_isolation and auth.os_secure_store held out; read live on a bundled-stamped serve on a temp home), so its mentions in this line are history; filed `RT-FU-A-BUNDLED-INSTALLS-SWITCHES-READ-OUTSIDE-THE-READ-SEAM-HOLD-TOO` (read in code, awaits a review batch); one subtask fewer and one more than the counts that follow · handoff 2026-11-21 (w1118a-hsmall): w1118a-hsmall closed two subtasks: RT-FU-A-VIEW-ONLY-DEVICE-CANNOT-READ-AN-AGENTS-PROJECT-FILES DONE 78e8ee104c (the three agent-files verbs are console tier; Eternia mirror f072ae9d460), and RT-FU-A-BUNDLED-INSTALLS-SWITCHES-READ-OUTSIDE-THE-READ-SEAM-HOLD-TOO REFUTED 8f867fcfe7 (agent.environment_probe already goes through the seam; pinned by a test). The project-folder search row that was waiting on the tier row can start; two subtasks fewer than the counts on this line · handoff 2026-11-21 (w1118a-liveuse): after w1118a-liveuse 2026-11-21: closed DONE `RT-FU-A-HIDDEN-COPY-IS-IN-LIVE-USE-WHEN-IT-HOLDS-A-LIVE-CHAT-NOT-BY-A-14-DAY-WINDOW` 271ec6216a (the review w1118a.85 mention of it is history; the cleanup keeps a copy whose chat pointer names a live chat as live_chat and retires a pointerless copy holding only ledger chats; no date window); no new rows; counts unchanged · handoff 2026-11-21 (w1118a-args): w1118a-args 2026-11-21: closed RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT DONE e001fab6da (phone file tools take every desktop argument; read through handle_function_call with a phone-shaped registry); the regex parent RT-PHONE-FILE-TOOLS-TAKE-THE-SAME-ARGUMENTS-AS-ON-DESKTOP-WITH-RIPGREPS-ENGINE-IN-PROCESS can now build on the search_files handler · after w1118a-emu3 2026-11-22: closed `RT-FU-A-REGEX-SEARCH-ON-THE-ANDROID-EMULATOR-RUNS-THE-SHIPPED-MATCHER` DONE 3bfe7ac796 (read live on the x86_64 emulator) and filed `RT-FU-RIPGREPS-MATCHER-LOADS-ON-A-PHYSICAL-ANDROID-PHONE` (BLOCKED on an owner phone sitting); counts unchanged · after review w1118a.91 2026-11-22: passed `RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS` (since closed DONE 626b56a694 by w1118a-helperappr, archived, so its mention here is history; its architecture, file map and security read on the row, the owner's two rulings built as the lead's policy answering for its helper) and re-read `RT-FU-A-PLACED-INSTALL-LISTS-A-SECOND-UNMARKED-BASE` (Eternia `TASK-BUNDLED-AGENTS-STAY-ONE-AGENT`'s, READY: its premise is decided by an Eternia live read); no rows filed or closed; counts unchanged · handoff 2026-11-22 (w1118a-pick): closed RT-FU-A-CHAT-OPENED-ON-AN-AGENTS-BARE-NAME-NO-LONGER-MAKES-A-HELD-ROW DONE 69703fdb0a (option b: a bare-name open is placed, an idle instance takes the selected chat, a new placement announces persona_instance.created; landed f0bf07d7f4); filed RT-FU-A-PLACED-AGENTS-LENS-TRIGGER-AND-HARNESS-QUERY-ARE-READ-LIVE-IN-ETERNIA (LIVE CHECK, the QA read carried from the readers row, not yet reviewed); Eternia golden copy owed as launcher MC-FU-ETERNIAS-STREAM-GOLDENS-CARRY-THE-PLACEMENTS-NEW-ANNOUNCE · handoff 2026-11-22 (w1118a-coord): RT-FU-A-PLACED-INSTALL-LISTS-A-SECOND-UNMARKED-BASE closed REFUTED 09f364a46c (one Base seen live by w1118a-agentsA); mentions of it above are history; one subtask fewer · handoff 2026-11-22 (w1122b-hmcreate): main lane w1122b-hmcreate closed RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED and RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE DONE eb70a3779c as one change (an unseated runtime.agent.create makes the template only; read live through hermes' CLI in an isolated namespace); their mentions above are history; Eternia reader owed as launcher MC-FU-A-COPY-MADE-WITH-NO-WORKSPACE-IS-SHOWN-AS-THE-NEW-AGENT-IT-IS (6d27d2fbe7e, awaits review; land it before the hermes primary is fast-forwarded past eb70a3779c). Open subtasks now 9: RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT (TAKEN w1122b-hmpress, then its read of RT-FU-A-PROVIDERS-OWN-REFUSAL-CODE-INSIDE-ITS-ERROR-DETAILS-IS-DROPPED, LIVE CHECK); RT-FU-A-PLACED-AGENTS-LENS-TRIGGER-AND-HARNESS-QUERY-ARE-READ-LIVE-IN-ETERNIA (LIVE CHECK, Eternia lane w1122b-agentsD); RT-FU-A-PHONE-SERVE-STARTS-NO-WORK-GIT-OR-MESSAGING-STEP-ITS-PROFILE-SWITCHES-OFF (LIVE CHECK, emulator lane); RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH (owner GitHub step); RT-FU-RIPGREPS-MATCHER-LOADS-ON-A-PHYSICAL-ANDROID-PHONE and its Android fallback waiter (owner phone); RT-SCHEDULE-SYNC-AND-KNOB-2 and RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR (DEFERRED, owner) · handoff 2026-11-22 (w1122b-coord): w1122b-hmpress closed RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT DONE 220ed9afac and RT-FU-A-PROVIDERS-OWN-REFUSAL-CODE-INSIDE-ITS-ERROR-DETAILS-IS-DROPPED DONE 9ef9e164fa; mentions of both above are history; two subtasks fewer · handoff 2026-11-22 (w1122b-emu4): 2026-11-22 w1122b-emu4 (emulator sitting): closed DONE RT-FU-A-COMPUTER-USING-A-PHONES-AGENTS-IS-HANDED-THE-PICTURES-IN-THE-CHATS-IT-MAY-READ (79c56e829e), RT-FU-A-COMPUTER-GIVEN-RUN-CHATS-OPENS-THE-CHAT-IT-STARTED-AND-STARTS-ONE-BY-AGENT (9beb9d50c5), RT-FU-A-PHONE-CHANGING-A-COMPUTERS-LEVEL-KEEPS-ITS-CREDENTIAL-AND-ITS-ACCEPT (f3c838e433), read live through Eternia; mentions of them above are history
- **`RT-FU-EACH-CHAT-AGENT-HERMES-KEEPS-READY-COSTS-A-KNOWN-AMOUNT-OF-MEMORY` — Each chat agent Hermes keeps ready costs a known amount of memory, so the number kept ready can be chosen on evidence** · group: windows-handoffs · from: `RT-FU-HERMES-STARTS-UP-READYING-ONLY-HOMES-AGENT` · owner 2026-11-24: "leave the measurement as a row" · not measured: the owner's cap is `max_hot_sessions: 2`, chosen without a memory number · first read: on a QA serve with hot sessions on, process RSS after boot with 0, 1 and 2 resident agents (open a second agent's chat to make the second), and boot-to-ready plus the boot pass's `persona_chat_actor_prewarm` elapsed_ms under the one-agent boot rule · done when: the row records MB per resident agent at 0/1/2 agents and the boot time under the new boot rule · READY 2026-11-24 · REQUIRES windows
- **`RT-FU-THE-FIRST-REPLY-AFTER-HERMES-STARTS-DOES-NOT-SPEND-HALF-A-SECOND-LOADING-THE-SEND-CODE` — The first message after Hermes starts begins its reply as fast as the next one** · group: runtime-followups · from: `RT-FU-THE-FIRST-MESSAGE-IN-A-NEW-CHAT-STARTS-WITHOUT-A-THREE-SECOND-WAIT` (lane w1123q-replytimings) · seen: `chat_turn_accept_to_anchor dispatch_ms=684` on a QA serve's first turn after boot and 31-47 ms on every later one; owner serve 678 ms at 15:51 (first send after a restart), 31-138 ms after · guess: the send handler's own imports on first use (dispatch = argv parse + handler imports, `turn_activity.ACCEPT_TO_ANCHOR_RECEIPT`) · first read: an import-time split of dispatch_ms on a fresh QA serve · done when: the first send after a serve start reads dispatch_ms within 100 ms of the second · READY 2026-11-23
- **`RT-FU-OPENING-A-NEW-CHAT-DOES-NOT-SLOW-ITS-OWN-FIRST-REPLY-WITH-READS-OF-OTHER-CHATS` — Starting a chat from Home does not make Hermes read every other chat while the reply is being prepared** · group: runtime-followups · from: `RT-FU-THE-FIRST-MESSAGE-IN-A-NEW-CHAT-STARTS-WITHOUT-A-THREE-SECOND-WAIT` (lane w1123q-replytimings) · seen on the owner's serve 2026-11-23 21:43:47-57: one Home send set off 15 `runtime.operator.conversation.read` (run 0.2-7.2 s, queued up to 8.8 s, restoring other chats such as dev_agent and agent_07c76f93), `conversation.list` 12.2 s, `conversation.models` 10.0 s, `prompt_observability.agent` 1.2-2.3 s, `provider.list` 1-3.9 s; the turn's own CPU was 625 ms of an 11.2 s prep (`send_prep_receipt`) · landed meanwhile: shared/read-lane jobs now wait (max 2 s) for a preparing turn's request to leave (`lane_held_for_turn`, 66fb8f49b0) · left: why each read costs seconds on the hermes side (conversation.read restore + message-alternation repair per read), and which of them Eternia needs at all (Eternia lane w1123p-homeinstant) · done when: a Home send on the owner's box logs no read of another chat's transcript between accept and request_sent · Eternia side: launcher `MC-FU-A-HOME-SEND-READS-ONLY-ITS-OWN-CHAT` (lane w1123p-homeinstant, 2026-11-23: each Home send is followed within 5 s by 12–14 pairs of persona.instance.slots.show + workspace.slots.show and 3 prompt_observability.agent) · READY 2026-11-23
- **`RT-FU-A-DISCUSSION-ROOM-TURN-IS-REFUSED-BECAUSE-ITS-TEST-AGENT-IS-NOT-THE-ROOMS-OWNER` — A discussion room's turn runs for the agent that owns the room, and its test proves it again** · group: runtime-followups · from: lane w1123l-choicecap · SEEN 2026-11-23 on origin/main 370e308976c3 (no lane change applied): `tests/agent_runtime/test_discussion_native_admission.py::test_native_room_turn_preserves_operator_pointer_and_concurrent_row_fields` is red in all 6 cases; the turn is refused with "chat session 'persona_chat_personainst_dev_a01234567890' belongs to instance 'personainst_dev'; it cannot be bound onto 'personainst_dev_agent_1'" · GUESS: the test's instance id no longer matches the room owner since the instance-id respelling; not yet known whether the product path or the fixture drifted · done when: the test is green against the real admission path, or the product refusal is fixed if a real room turn is refused · READY 2026-11-23

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

### Owner request — 2026-11-25 (saved chat title)


- **`RT-FU-THE-CHAT-LIST-AND-HISTORY-RECOVERY-LOAD-WHILE-ANOTHER-CHAT-IS-BUSY` — The chat list, Chat history and a chat's recovery information load while another chat is busy, instead of "Conversations could not be loaded" and "Recovery information could not be loaded"** · group: runtime-followups · task in Eternia: `TASK-MISSION-CONTROL-FOLLOWUPS-7` · reported by the owner 2026-11-23 15:53 (Eternia b796063b76, serve e5c81cd4a130), not seen by the filer: after a serve restart with a chat's notice turns still looping, the Chat panel said "Conversations could not be loaded. Try again.", Chat history was empty and Active agents listed only "New chat" rows; the recovery banner ("Recovery information could not be loaded") showed on every launch since 2026-11-22 with Eternia logging `[ConsoleHistory] history_unavailable stage=runtime reason=rpc_timeout` · seen in a QA copy 2026-11-23 (same serve code, no loop, stagec-smoke): the list loaded, no error — not reproduced without the load · read in code: `runtime.operator.conversation.list`, `...history.pending` and every console inspection are deferred replies run on the serve's SHARED lane (`hermes_cli/harness_parts/serve/request_pool.py`, 4 workers), the same lane as every non-turn argv request; the serve logged nothing for a deferred reply, so the owner's agent.log had no line for either read · guess: argv work waiting on the looping chat held the shared workers · fix: the reads run on a read lane of their own (`serve_rpc.protocol.defer_read`, `RequestPool.submit_read`), and a wait or run past 1 s on either lane logs `shared_lane_slow lane= label= queue_ms= run_ms= busy_at_submit=` · READY 2026-11-23 · done when: with every shared worker held, the chat list still answers (test `tests/agent_runtime/test_shared_lane_slow_receipt.py`), and the owner's Chat panel lists their chats after a restart · handoff 2026-11-23 (w1123k-chatissues): landed 7eb9bf3f7283 (read lane + shared_lane_slow receipt) and 52066bfcad16 (read lane narrowed to the list, conversation.read, history.pending and history.origin after the live receipt showed conversation.models at 15954 ms); tests red under their mutations; live on a Windows QA copy at 7eb9bf3f7283: the Chat panel lists a new chat, no error; owed: the owner's Chat panel after their serve restarts on 52066bfcad16 or later · **TAKEN 2026-11-23 w1123k-chatissues on DESKTOP-QJ7DDV2 as nekwo in w1123k-chatissues**

- **`RT-FU-A-TURN-OUTCOME-TEST-PATCHES-A-HISTORY-READ-THE-CHAT-LIST-NO-LONGER-MAKES` — The test that a failed turn's history row keeps its block runs again instead of erroring on a name the chat-list code no longer has** · group: runtime-followups · seen in a test 2026-11-23 by lane w1123k-chatissues on Windows at origin/main 64f210498f99: `tests/agent_runtime/test_turn_outcome.py::test_the_history_row_carries_the_block_and_an_older_record_leaves_it_untouched` fails with `AttributeError: module agent_runtime.persona_chat_history.curation has no attribute mission_chat_turn_elements` (test line 196 monkeypatches it) · read in code, not reproduced elsewhere: the read moved behind the once-per-chat journal read in d5b5b081397a / 05424d7b9b9b, so the patch target is gone · READY 2026-11-23 · done when: the test patches the read where curation now takes it and passes, red when the block is dropped

### Filed on arrival — 2026-11-23 (owner request: the operator can dismiss an agent's question card)

### Filed on arrival — 2026-11-23 (review w1122d.14: the owner's QR and pasted-code re-pair parity ruling)


### Filed on arrival — 2026-11-22 (Eternia lane w1122d-phonechat: the agent chat doors on a computer using a phone's agents)


### Filed on arrival — 2026-11-22 (Eternia lane w1122g-serveboot: `MC-AGENT-RUNTIME-IS-READY-SOONER-AFTER-LAUNCH`, the serve's own share of a cold start)

- **`RT-FU-A-HARNESS-SERVE-REGISTERS-WITHOUT-BUILDING-EVERY-COMMAND-FIRST` — Your agents are ready sooner after a cold start once git is quick, because the runtime stops building every command and running every start-time step before it registers** · group: runtime-followups · from: `RT-FU-A-COLD-HARNESS-SERVE-REGISTERS-SECONDS-SOONER` (lane w1123b-serveboot) · measured 2026-11-23 on DESKTOP-QJ7DDV2 (stack sampler, cold `harness serve --ndjson --service` from a worktree): with the git stamp off the critical path (a repacked clone, `FH-A-HERMES-CLONE-WITH-THOUSANDS-OF-PACKS-MAKES-EVERY-GIT-READ-TAKE-TWO-SECONDS`) the main thread's ~2.7 s before registering is the critical path: `hermes_cli/main.py` import ~0.9 s (upstream: `hermes_bootstrap` 0.3 s, `hermes_cli.config` 0.2 s), the whole harness parser built for one verb (`setup_harness_parser`; `add_mission_chat` imports `agent_runtime.mission_chat_turns` for `TurnResolution` choices, 0.09-0.19 s), the start-time setup 0.3-0.5 s (`agent_runtime.character_assignment_migration` 0.16-0.28 s, `process_presence` importing `tools.process_registry` 0.18-0.25 s), and the serve package 0.26 s (`serve.in_memory` keeps `hermes_state_registry` eager on purpose) · not measured: whether each start-time step may run after `ready` for the serve · done when: a cold start on a repacked clone registers measurably sooner with the named imports deferred · READY 2026-11-23

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

- **`RT-PEER-CANCEL-LIVE-STOP-PROOF` — D1.07's peer Stop has never been proven across two real installs (durable cancel_requested, partial output kept)** · group: remote-parity-and-two-machine-proof · moved 2026-11-10 (w1110a-org): from console-smooth-and-fast.design-sweep-d1 · fork / gateway · plan `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` D1.07 (built 5a2c887621) · `tools/agent_chat_dispatch/cancel_watch.py` · DEFERRED 2026-11-09: owner triage — Proof of a built feature; no reported failure; until the owner reopens it · waits: owner-ruling · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 3, option (a): the five remote-agents rows that wait on the owner (Eternia `MC-PROFILE-OWNER-INSTALL-SUBJECTS`, `MC-NEXT-PROMPT-PAIRED-REMOTE` and `MC-REMOTE-PORTRAIT-BINDING`, hermes `RT-PEER-CANCEL-LIVE-STOP-PROOF` and `RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM`) all wait on ONE two-machine sitting with the owner and stay deferred; not taken: (b) close the three built-only-a-proof-left rows, (c) leave as is; the `waits:` field reads `owner-ruling` for that sitting, because the three brains' wait events (`WAIT_EVENTS`) have no two-machine event

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

- **`RT-PHONE-TLS-TRUST-UNPROVEN` — Nobody has shown that the agent engine on a phone can verify the websites and providers it connects to** · group: mission-control-on-mac · fork / `agent/ssl_verify.py::install_truststore` · read in code, not reproduced: TLS trust is pointed at the OS store through the `truststore` library, which sends every OS that is not Windows or macOS to its OpenSSL arm (read in pip's vendored copy, not the locked version), and that arm looks for OpenSSL's default paths or a short list of Linux certificate files; `certifi` is in the phone closure but nothing selects it · guess: none of those files exists on a phone, so the trust store is empty and every HTTPS call is refused · guess: the fix is to point `SSL_CERT_FILE` at certifi's bundle under the phone profile · done when: an HTTPS request to a provider succeeds and one to a host with an untrusted certificate is refused, on an Android emulator and an iOS simulator, with the phone profile · was LIVE CHECK 2026-11-19: on the Android x86_64 emulator with the phone bundle, an HTTPS request to a provider succeeds and one to self-signed.badssl.com is refused (the iOS simulator half needs a Mac) · reviewed 2026-11-15 w1115p.1 · unblocked 2026-11-17: `RT-PHONE-EMULATOR-TARGETS` closed DONE c6da3eebc358 (the x86_64 bundle and a recipe to run it on the emulator are on `RT-PHONE-PILLOW-ANDROID`; the iOS simulator half needs a Mac) · was BLOCKED 2026-11-15 on `RT-PHONE-EMULATOR-TARGETS` · handoff 2026-11-19 (w1118a-hphone): built 5374a58860: `agent_runtime/phone_tls_trust.py::ensure_phone_tls_trust` exports certifi's bundle as SSL_CERT_FILE on sys.platform android/ios (unless the host set SSL_CERT_FILE/SSL_CERT_DIR), called in `EmbeddedServe.start`; read on Linux with a simulated phone (OpenSSL defaults and truststore's file sweep emptied): before, urllib to openrouter.ai refused SSLCertVerificationError; after, urllib and resolve_httpx_verify's httpx 200, self-signed.badssl.com refused by both. left: the emulator read (lane w1118a-phoneqa holds the emulator this wave) and the iOS simulator read (needs a Mac, REQUIRES macos for that half) · handoff 2026-11-19 (w1118a-phoneE): re-read on the Android x86_64 emulator 2026-11-19 (Eternia debug APK ad11dbe861 with the embedded engine, bundled-phone 73b1c13115, which holds 5374a58860): the trust half holds — the phone engine cloned https://github.com/ArcadiaLabsLLC/eternia-qa-realm.git (dulwich over urllib3) and fetched it again on Check now, both verified connections from inside the app (realm record, clone at 65900af713, checked_at moving); the refusal half (self-signed.badssl.com refused) was not read: no route from Eternia sends the phone engine to an arbitrary host, and the iOS half still needs a Mac; stays LIVE CHECK for the refusal read; evidence EterniaLauncher/docs/stages/qa-reboot/live/2026-11-19/RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR/w1118a-phoneE/README.md · review w1118a.34: re-read after w1118a-phoneE — the trust half is seen live (two verified HTTPS connections from the phone engine: the realm clone and its re-fetch); what is left on Android is the refusal half, and no Eternia route sends the phone engine to an arbitrary host (seen by phoneE); the iOS half still needs a Mac (REQUIRES macos for that half, unchanged) · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.34 D9: read the refusal through a product route, no new code: first a custom provider in Eternia's Settings (`custom_provider_dialog.dart`) whose base URL is `https://self-signed.badssl.com/v1`, whose model read on the phone runs in the in-app engine (Eternia 0b9b1ec676, phoneG: Connections reads a provider's models from the in-app engine — read in its commit title, not traced; the lane confirms the request leaves the engine, not Eternia's Dart client, before it counts) and must fail with a certificate error; if that read is served by Dart, the fallback is the realm route — a private staging test repository's realm whose remote points at `https://self-signed.badssl.com/` (staging test repos and staging realms are allowed to lanes, owner 2026-11-14), whose Check now must fail with a certificate verification error, not a 404; either way the read names the exception text the engine logged; rejected: a QA hook that makes the phone engine fetch any URL (a shipped fetch-anything surface in the engine for one read, and it would prove the hook's HTTP client, not the paths users take) · architecture: no code; a live read on the Android x86_64 emulator with the phone bundle that holds 5374a58860; evidence beside phoneE's under `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-19/` · same-file sweep (runtime queue): `RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR` and `RT-PHONE-BUNDLE-LEAVES-OUT-THE-HARNESS-SKILLS-A-REALM-PULL-INSTALLS` share the emulator sitting — lane w1118a-hbundle takes this read after its realm reads, in the same sitting · reviewed 2026-11-19 w1118a.34 · handoff 2026-11-19 (w1118a-hbundle): w1118a-hbundle checked both of review w1118a.34 D9's routes before the read and neither sends the phone engine to an arbitrary host (read in code, Eternia 13ecf8dd42, hermes f38b8c32f5, eternia-backend main): (1) Settings' custom provider (`lib/features/account/tabs/settings/custom_provider/custom_provider_dialog.dart`) is a MEDIA search provider (`CustomMediaProviderConfig`, a URL template; its Test runs `CustomProviderTestSearch` -> `MediaSearchPage` in Dart), not a model provider, so its request never leaves the engine; and phoneG's Connections model read (Eternia 0b9b1ec676, hermes 8b53197eb0 `runtime.provider.models`) answers models.dev catalog entries by id from `agent/models_dev.py::fetch_models_dev()`, never a provider's own base URL; no Eternia screen sets a model provider base_url on the phone; (2) a server realm's remote is the backend's `clone_url_for` (`eternia-backend/realms/github.py`: always `https://github.com/<repo>.git`), which hermes adopts as `sync_manifest_ref` (`agent_runtime/realm_sync/git.py::_take_server_credential_url`), so no staging realm can point at self-signed.badssl.com without new backend code. The trust half stands, re-read this sitting: the phone engine cloned, fetched, pushed (publish `eae3ffd`, `c14a734`) and pulled github.com over HTTPS many times (RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR). Left: a route for the refusal half needs a new ruling — e.g. a model-provider custom endpoint the phone engine itself calls, or a QA-only fixture; the rejected fetch-anything hook stays rejected; iOS half still needs a Mac · review w1118a.36: hbundle's reading of both D9 routes is confirmed — the Settings custom provider is a media-search provider tested in Dart, `runtime.provider.models` reads only models.dev, and a server realm's remote is always `https://github.com/<repo>.git` (backend `clone_url_for`); no product path sends the phone engine to a host Eternia names · RULED 2026-11-19: owner said "when there is a decision for this session, do an analysis on it and go with reccomended" — review w1118a.36 D5: the Android half closes on the trust read already seen (the phone engine's verified clone, fetch, push and pull of github.com) plus a hermes test of the refusal: the refusal does not depend on the device — every client the engine uses verifies with CERT_REQUIRED against the anchors it is given, and which anchors a phone has (the device-dependent part) is what the trust read proved; so `tests/agent_runtime/test_phone_tls_trust.py`'s simulated-phone child (which already refuses an untrusted private CA through urllib and httpx, no network) adds the realm sync client, `git_dulwich._BrokeredHttpClient` (dulwich over urllib3, the client the trust read used): it completes the handshake with the trusted local server (any error is git's, not the certificate's) and is refused the untrusted one with a certificate verification error, through `_wire`'s typed refusal; killing mutation: the brokered client built with `http.sslVerify` false reds the refusal assertion; rejected: a QA hook that fetches any URL (still rejected — a shipped fetch-anything surface), a new model-provider base URL screen on the phone or a backend realm remote override just for this read (new product scope for one read), self-signed.badssl.com in a test (network in a unit test; a local server proves the same), and running the test on the emulator (the device adds nothing the trust read did not) · done when (Android half, replaces the emulator refusal read): that test passes and its red is recorded; then this row goes LIVE CHECK for the iOS simulator half only, with `REQUIRES macos` · architecture: test only, `tests/agent_runtime/test_phone_tls_trust.py`; no product code · same-file sweep (runtime queue): no other open row names that test or `phone_tls_trust.py` · reviewed 2026-11-19 w1118a.36 · LIVE CHECK 2026-11-19: on an iOS simulator with the phone profile and the phone bundle that holds 5374a58860, read that the phone engine reaches a provider (or clones the QA realm) over HTTPS with a verified certificate, and that a host with an untrusted certificate is refused; the Android half is closed (see the w1118a-htls handoff) · handoff 2026-11-19 (w1118a-htls): the Android half is closed (review w1118a.36 D5): the trust half was seen live on the Android x86_64 emulator (w1118a-phoneE and w1118a-hbundle: the phone engine cloned, fetched, pushed and pulled https://github.com/ArcadiaLabsLLC/eternia-qa-realm.git through dulwich over urllib3, verified); the refusal half is a test, 8ae3448ca6: tests/agent_runtime/test_phone_tls_trust.py's simulated-phone child (no OS store, certifi = a private CA) now also clones through DulwichSyncGit (git_dulwich._BrokeredHttpClient via _wire), reaches the trusted local server (fails on git's answer, not the certificate) and is refused the untrusted one with CERTIFICATE_VERIFY_FAILED, beside urllib and httpx; no network; killing mutation _BrokeredHttpClient built with http.sslVerify false reds 'the realm client trusted a CA nothing names' (1 failed, 8 passed), restored 9 passed; left: the iOS simulator half, which needs a Mac · REQUIRES macos · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 5, option (a): the iPhone and Mac rows of the phone work move to Eternia `TASK-MISSION-CONTROL-ON-MAC` so the Android phone task can close (a host never holds a feature task open); not taken: (b) keep them where they were until a Mac sitting · handoff 2026-11-22 (w1122b-rulings): moved from Eternia `TASK-PHONE-HARNESS` to Eternia `TASK-MISSION-CONTROL-ON-MAC` (`group: mission-control-on-mac`; hermes has no Mac task of its own, and a task may hold subtasks in any brain) — its Android half is closed (w1118a-htls), so only the iOS simulator read is left; its status is kept

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




- **`RT-VERIFY-IMPROVE-FIRST-RESPONSE` — Verify and improve first-response selection of the Launcher generated-content tools for ordinary comparison requests; the A/B eval is built (`evals/genui_first_response_ab.py`, b05ccafe29)** · group: windows-handoffs · fork / tool selection · plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §3 · RULED 2026-10-19: owner — arms switched by QA build · RULED 2026-10-25: owner — an agent runs this sitting on this PC · live phase 2026-10-25: a launcher_qa lane runs it — two QA builds (arm A before launcher 469e500730, arm B at it), 15 turns × 2 agents × each QA provider per arm; it does not touch the owner's serve (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · BLOCKED 2026-11-15: another lane — `RT-GENUI-AB-VERIFIES-THE-AGENT-AND-PROVIDER` verify actual routing and receipt attribution before each arm is approved and sends begin · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — the A/B test exists (`evals/genui_first_response_ab.py`); it costs provider turns · was dEFERRED 2026-11-09: owner triage — Evaluation of a nice-to-have behavior; until the owner reopens it · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — the live A/B (arm A, arm B) over launcher_qa; the owner keeps ONE QA build of HEAD (11-11), so arm A on a build before launcher 469e500730 needs a plan · moved 2026-11-12 (w1112b-ctt-hm): from console-transcript-truthful.p10-agent — owner rule 2026-11-12 ("any fine tuning stuff like that and performance should go into the windows task"): an A/B of which tool a model picks first is tuning, not a defect in the chat · handoff 2026-11-12 (w1112b-ctt-hm): not run on Linux — it costs real-model turns (15 turns × 2 agents × each QA provider × 2 arms) and this wave runs the fixture model only; arm A needs a QA build before Eternia 469e500730 (a throwaway local branch at that commit, built by `launch_or_attach` from a tree checked out there) · REQUIRES windows, linux

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

- **`RT-WORK-LIST-OWNER-SIZE-PAST-HALF` — Work's Refresh at the owner's real workspace size stays well inside its ten-second limit** · group: windows-handoffs · `runtime.work.list` · seen live 2026-11-12 on Windows (Eternia lane w1112c-winperf2, Debug `94fcaeabc3`, Harness `0b8a6aa0d3`): with QA Fixture plus the hermes and backend checkouts bound (5 brains, 831 live rows) three clean Refreshes took 5.35 / 3.29 / 3.37 s at 13-35% load, and the list step is 3.1-4.8 s of each — the same as 2026-11-10 (5.32 / 3.58 / 3.43 s), so the fetch-only-when-moved fix did not move the owner-size number · guess, unverified: the boards are still synced one after another · done when: each board's sync is timed inside `runtime.work.list`, the cause is fixed, and a Refresh at this size reads under 5 s three times in a row · consumer: Eternia `COMP-WORK-REFRESH-OWNER-SIZE-PAST-HALF` waits on it and re-times on Windows · filed 2026-11-12 by the w1112c orchestrator · REQUIRES windows · READY 2026-11-12 · handoff 2026-11-12 (w1112b-hm-turnfu): re-grouped from shared-work-v1 to shared-work-v1-followups: TASK-SHARED-WORK-V1 was archived (Eternia c8c433dfb8) with this row still open, which left it under no task and turned hermes main's queue gate red (test_every_row_is_a_task_or_a_subtask…, seen in a test at 272b0ae714); the Eternia TASK-SHARED-WORK-V1-FOLLOWUPS count goes up by one · handoff 2026-11-12 (w1112b-swfu, at the orchestrator's word): moved from shared-work-v1-followups to windows-handoffs (Eternia `TASK-WINDOWS-HANDOFFS`) — a Windows-filed speed measurement at the owner's workspace size; owner 2026-11-12: performance goes to the Windows task and never holds a feature task · handoff 2026-11-15 (codex-win-hermes): Eternia removed the duplicate destination list and landed the client fix at `cd87462285`; app Debug `cd874622859b`, 956 live rows and five brains, Harness `3997c2cc4e` over `823c73fda5`. Each of four Windows Refresh presses sent one wire list: 2.853 / 11.874 / 2.367 / 4.728 s, app composite 2.891 / 11.908 / 2.414 / 4.771 s, full reconciliation 5.237 / 14.673 / 4.662 / 8.688 s. Stable tips, zero warm note-history misses and no fetch. At CPU 6/5/5, the 11.715 s sync started the four boards within 1.21 ms after 2.675 s of pre-worker work; `backend` and `launcher` overlapped, with `git status` taking 4.513 s and 2.764 s. The serial-board guess is superseded. The exact app and per-board receipts are in `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-15/COMP-WORK-REFRESH-ASKS-HARNESS-TWICE/README.md` at `64aa3a835b`. Next source question: can lifecycle list consume a tip-pinned, owned snapshot with equivalent tracked and untracked cleanliness while preserving the writer admission, recoverable index/lock handling, and the separate checked-out user-branch guard? Today Writer._reset normalizes the dedicated worktrees and filesystem queue globbing would otherwise see abandoned untracked notes. The three-consecutive performance bound remains open.

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

- **`RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN` — Telegram can run on upstream's connector as a second option, off by default, so the owner can try it with a real bot before anything is switched** · group: remote-parity-and-two-machine-proof.p10-messaging · fork / messaging · filed 2026-11-14 at the owner's ask in chat ("if so then just switch it", then "i need a proper audit") · seen in a test: on branch `audit/upstream-telegram-switch` (62920f2b68) the upstream Telegram adapter, connected over HTTP to a local stand-in for the Bot API with no GatewayRunner, did what the fork's own transport does — queued turn on the persona's one root, real reply, 4,096 split, `/persona`, forum topics, approval cards — once five defects were fixed in the shim: a stranger's media fetched before refusal, replies sent silently, upstream's command menu pushed to the bot, the bot token logged at INFO, message text logged at DEBUG; note `docs/agent-runtime-harness/evidence/upstream-adapter-as-transport-2026-11-14/SWITCH_AUDIT.md` · not shown: real Telegram, and two upstream Windows tests of stuck-poll recovery fail on this box (cause not investigated) · to build: a harness setting that picks the transport per token (never both: one poller per bot), the shim and its Telegram subclass from the branch, the token from `agent_runtime/messaging/credentials.py::bot_token`, the Allow list fed from the shim's refusals with the display name it lacks today, the press handler registered through upstream's plugin handler factory so a rebuilt application keeps it · done when: with the setting on, the owner's real bot answers on a phone (it buzzes, the reply threads, a card's buttons work) for a day of ordinary use, and with it off nothing about today's Telegram changes · related: `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS`, `FORK-PARALLEL-MESSAGING-GATEWAY` · folded 2026-11-15 (w1115e-rr2, owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"): `FORK-PARALLEL-MESSAGING-GATEWAY` (its question — keep the fork's own gateway beside upstream's — was answered by the owner's ruling to reuse the upstream connectors; owner 2026-10-20 "sounds good persona system for our custom gateway is the way") and `RT-MESSAGING-PLATFORMS-TELEGRAM` (the fork Telegram transport is on main, off by default; its remainder is this row's opt-in trial; owner triage 2026-11-09 "New optional channel; off by default") are closed into this row: after the opt-in trial, retire the fork transport in `agent_runtime/messaging/` · deferred 2026-11-15: owner — "unclaim that telegram row for now" (the real-bot trial is off the owner's list; the opt-in stays shipped, off by default) · handoff 2026-11-22 (wave-start sweep w1122b-sweep): the agent half the owner's 2026-11-19 undefer asked for is done (w1118a-htele re-checked every step against the local Bot API stand-in on main 17485839f2; the upstream adapter is the one Telegram connector since d7542acf2d); what is left needs the owner's bot token, his phone and his Telegram account for a day of use, which no lane holds or may make (a new bot is a new account), so the row was a LIVE CHECK no lane could start · was LIVE CHECK 2026-11-19: the owner's real bot on a phone for a day of ordinary use — the reply buzzes and threads, an approval card's buttons work, a stranger gets no answer · waits: phone-sitting · BLOCKED 2026-11-22: owner sitting — on the owner's phone with his own bot: set its token with `runtime.messaging.credential.set`, enable messaging, use it for a day (it buzzes, the reply threads, a card's buttons work); optionally `scripts/live_telegram_check.py` with a throwaway bot the owner makes, for the stranger step · RULED 2026-11-19: owner said "undefer it and have an aggent see and fix if need be" · handoff 2026-11-14 (msg-live-note): the live check ran against real Telegram on a throwaway bot, branch audit/upstream-telegram-switch 790202d002, script scripts/live_telegram_check.py there (reported by the owner, not seen by the lane): the bot reached step 6 of 6, so connect, the threaded reply, the formatted reply, the split long reply, the approval card press and edit, and a photo all went through real Telegram; asked whether the phone buzzed, the reply threaded, the formatting rendered, line 130 arrived and the card changed, the owner answered yes; the console summary was not pasted and the stranger step is not confirmed; not covered by it: a day of ordinary use, and the two failing upstream Windows stuck-poll tests · handoff 2026-11-14 (msg-opt-in): built and on main a682b32b82 (seen in a test): the setting messaging_telegram_transport picks fork (default) or upstream in the serve lane, a changed setting stops the running connector before the other starts, the operator list is asked at the adapter's intake with the sender's name, the card press handler is registered on every application the adapter builds; 111 messaging tests pass, each new check watched red; left is only the owner's own bot: turn it on with hermes config set plugins.entries.eternia-harness.settings.messaging_telegram_transport upstream on the machine whose Harness holds the bot token, use it from a phone for a day, and switch back with fork if anything is off; the builder could not do this read — it needs the owner's bot token, phone and Telegram account · handoff 2026-11-19 (w1118a-htele): re-checked on main 17485839f2 against the local Bot API stand-in (seen): scripts/live_telegram_check.py, unchanged, driven end to end — connect, threaded notifying reply, MarkdownV2 formatted reply, 130-line reply split into 3 (none over 4,096, last ends at line 130), approval card sent/pressed/answered/edited, operator photo fetched and handed on, a stranger's photo and text refused at the adapter's intake with no getFile or download and no answer; at DEBUG neither the bot token nor any message text reached the log; all passed. Real Telegram not driven: no staging or throwaway bot token is provisioned here (the credential store reads absent). The upstream adapter is now the ONE Telegram connector (RT-MESSAGING-RETIRE-FORK-TELEGRAM, d7542acf2d); the messaging_telegram_transport setting is gone, so the owner's read is: set the bot token with runtime.messaging.credential.set, enable messaging, and use it from a phone for a day (it buzzes, the reply threads, a card's buttons work), optionally scripts/live_telegram_check.py with a throwaway bot for the stranger step · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 2, option (a): the owner runs a day's trial with his own bot from his own phone (sets its token, enables messaging); not taken: (b) a throwaway bot token for a lane, (c) park it again; stays BLOCKED owner sitting until he has
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
- **`RT-FU-FAILED-STAGING-REPORTS-AN-EMPTY-CHECKPOINT-DIFF-AND-SAFE-RESTORE-PLAN` — A failed staging operation reports an empty checkpoint diff and safe-restore plan** · group: runtime-followups · from: `RT-FU-COLD-CHECKPOINT-STAGING-EXPIRES-BEFORE-A-TURN-HAS-A-BASELINE` · observed 2026-11-25 on Windows: checkpoint one file, hold the project index lock, change the file and record the write. The legacy diff returned success with an empty patch and safe restore planned zero files. The recorded turn diff contained the edit, reviewed restore returned checkpoint_read_failed and the existing lock stayed intact · confirmed cause: `tools/checkpoint_manager.py::CheckpointManager._diff` and `_safe_restore_plan` ignore the staging result and compare the previous index · done when: validate the existing upstream fix against the current manager, surface a failed staging result through both legacy callers, preserve the workspace and lock, and verify the real edit appears after the lock is released · Upstream tracking: [issue #109992](https://github.com/NousResearch/hermes-agent/issues/109992) and [Liuzikaii's open PR #109993](https://github.com/NousResearch/hermes-agent/pull/109993), which needs a rebase · READY 2026-11-25

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

- **`RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM` — once the owner's first gateway answers: stop the alice upstream gateway, remove its logon task, delete the shared bot token from the eight profile `.env` files (no code)** · group: remote-parity-and-two-machine-proof.external-gateway-access · `docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md` §2 D4, §5 · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: after the owner's first gateway is live · waits: owner-ruling · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 3, option (a): the five remote-agents rows that wait on the owner (Eternia `MC-PROFILE-OWNER-INSTALL-SUBJECTS`, `MC-NEXT-PROMPT-PAIRED-REMOTE` and `MC-REMOTE-PORTRAIT-BINDING`, hermes `RT-PEER-CANCEL-LIVE-STOP-PROOF` and `RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM`) all wait on ONE two-machine sitting with the owner and stay deferred; not taken: (b) close the three built-only-a-proof-left rows, (c) leave as is; the `waits:` field reads `owner-ruling` for that sitting, because the three brains' wait events (`WAIT_EVENTS`) have no two-machine event



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

- **`RT-WINDOWS-UPDATE-RESTART-DEFAULT-IDENTITY` — Updating Hermes restores the host gateway under its default identity** · group: windows-handoffs · seen 2026-11-13 by hermes-creation: canonical updates from 51014a80 through 1825fa6445 and 4d29a8936c pause the zero-turn default multiplexer but automatic Windows restart repeatedly selects sticky active profile amelia and refuses a separate poller; explicit hermes -p default gateway restart restores all eight original profiles and Telegram · cause: gateway_windows._launcher_settings uses gateway._profile_arg which returns an empty selector for the default root; detached boot follows active_profile; the later update fleet also labelled the root multiplexer amelia, classification cause not yet traced · done when: canonical Windows update preserves the root gateway identity and restores its original served profiles with one poller through existing lifecycle authority · READY 2026-11-19 · REQUIRES windows · handoff 2026-11-15 (codex-win-hermes): The update watcher, not the supervised launcher renderer, chose the wrong home: its Windows overlay was based on the updating CLI, and its unpinned selectorless root followed active_profile. Five Windows regressions red on 1e7d9652a5 and green on topic 8179f588ed. An isolated native Windows pause/resume restored the default and all eight profiles; the replacement default PID was the only new Telegram poller against a loopback fixture, and the fleet labelled it default. The topic waits on the footprint ruling (three base lines moved into else) and a landing; a full source/dependency swap was not exercised. · handoff 2026-11-19 (w1118a-coord): RULED 2026-11-19: owner answered the decision 'May the restart fix move three upstream watcher lines into the fallback branch, raising deleted_lines from 874 to 877?' with "yes" — build the recommended fix (candidate on wave/codex-win-hermes at 83869ce5d3); REQUIRES windows

## Filed on arrival — 2026-11-13 (lane w1112b-hm5: review batch w1112b-6 §2)


## Filed on arrival — 2026-11-13 (Eternia orchestrator: GitHub-quota read)


## Filed on arrival — 2026-11-13 (Eternia orchestrator: git-host architecture read)



## Filed by Eternia review batch w1114a.2 — 2026-11-14

- **`RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` — When GitHub refuses a realm's push because the owner disconnected the repository, the member is told to ask for a reconnect within a minute, instead of retrying a dead token for up to 44 minutes** · group: runtime-followups · from: `TASK-WORKSPACE-ABSORBS-PROJECTS` · `agent_runtime/realm_sync/` · read in code 2026-11-14 (`eternia-backend` `603184bc`, `REALM-GIT-BINDING-DEATH-UNSEEN-WHILE-TOKEN-CACHED`): the backend now takes `POST /api/realms/{id}/sync/auth-rejected` (local `/api/me/realms/{ref}/sync/auth-rejected`) with the credential's `api_token`, answering 204 (re-broker) or 409 `realms.git_host_binding_lost`; hermes calls it nowhere · the Eternia half is already mapped (read in code: Eternia `realm_sync_credential_failure.dart` maps `realms.git_host_binding_lost` to reconnect), so it is this row's own live read, not a separate row · done when: a push or fetch refused 401/403 by github.com reports once, a 204 re-brokers, a 409 reaches the snapshot as `git_host_binding_lost`, pinned by tests; and the builder reads Mission Control showing reconnect, not retry, in a QA copy · NEW 2026-11-14 · reviewed 2026-11-14 w1114a.2 · the read, once unblocked: built ef70922059 (report on 401/403/404 from publish, pull, status; 204 re-broker, 409 host-state mark; 13 tests on a local refusing HTTP host) — read Mission Control showing reconnect after GitHub refuses a server realm's push · handoff 2026-11-14: not read live — making github.com refuse a staging realm's token means uninstalling the staging GitHub App or dropping a repo from its installation, a GitHub account settings change no lane may make unasked; the hermes→snapshot half is pinned by test (sync.revoked reason git_host_binding_lost, host_state true), the Eternia render of that mark is existing code (mission_snapshot_realms.dart) · handoff 2026-11-14 (w1114a-realmlive): probe approved by the owner and staging rolled to backend 4c38b903, but no tool on the Linux box can take a repo out of the staging App's installation (gh's OAuth token is refused 403 on installation repositories, the built-in browser is signed out of GitHub, the Chrome extension is not connected), so GitHub's refusal was never provoked; what is left: the owner unticks ArcadiaLabsLLC/eternia-probe-org-create-2026-11 in the eternia-server-realms-staging installation, a lane binds QA Realm to the probe (staging manage.py shell: realms.subject_git_host _upsert of the realm subject with installation 181291722, then connect_realm_github as the server owner), Pulls as account B and reads the sheet, then the owner re-ticks it and the lane unbinds (disconnect_realm_github) · READY 2026-11-21 · waits: owner-ruling · reviewed 2026-11-16 w1115e.18 · handoff 2026-11-21 (orchestrator): 2026-11-21 orchestrator, the owner asked for a read that needs no GitHub settings change ("can't you test that another way it can on its own"): a GitHub App installation token can revoke itself (DELETE https://api.github.com/installation/token with that token), so the lane makes github.com refuse the realm's cached token for real with no installation edit — bind QA Realm to the probe as the row says, Pull once so hermes holds a token, revoke that token, Pull again: GitHub answers 401, hermes reports auth-rejected, and with the binding intact the backend answers 204 and re-brokers (the 204 leg read live); for the 409 leg the lane first reads in eternia-backend how auth-rejected decides git_host_binding_lost, and if that decision reads the staging binding row (not a live GitHub installation call), breaks the binding on staging only (manage.py shell, the probe realm's subject binding) before the revoked Pull, reads Mission Control showing reconnect, then restores it; if the backend asks GitHub live, only the installation untick reaches 409 and the row says so; never print a token · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 6, option (a): the owner unticks `ArcadiaLabsLLC/eternia-probe-org-create-2026-11` in the `eternia-server-realms-staging` GitHub App installation (no lane may change it), then a lane reads the refusal live as the w1114a-realmlive handoff says; not taken: (b) close it on its tests; the owner's step is pending, so the row's status and its `owner-ruling` wait stay as they are until he has done it
- **`RT-SCHEDULE-SYNC-AND-KNOB-2` — Agent schedules stay in step between your two machines, like the rest of your agent setup** · group: runtime-followups · from: `TASK-REALM-SYNC-FAMILY-DESCRIPTOR` · reopened 2026-11-16 (review w1115e.18, B68): `RT-SCHEDULE-SYNC-AND-KNOB` was DEFERRED by the owner and folded into the READY `RT-SYNC-FAMILY-DESCRIPTOR`, which undeferred it silently; it returns to DEFERRED here under a new ID (the old one is archived) · architecture: `agent_runtime/work_store/schedule_store.py`, `agent_runtime/realm_sync/document_family.py`; plan `docs/agent-runtime-harness/archive/dispatcher-and-libraries-2026-10-18.md` §2.3; the knob half landed (root config `agent_runtime.scheduler.max_parallel`) · RULED 2026-10-18: owner — schedules stay local to the machine that armed them for now; the realm-sync family waits for a design of delete propagation and per-fire publish · RULED 2026-11-16: owner — "Accept all" (on review w1115e.18, B68) · DEFERRED 2026-11-16: owner — schedules stay local for now (ruled 2026-10-18); waits for a design of delete propagation and per-fire publish · waits: owner-ruling · reviewed 2026-11-16 w1115e.18

## Filed by Eternia review batch w1114a.3 — 2026-11-14

## Filed on arrival — 2026-11-14 (lane w1114a-hanthropic)

## Filed on arrival — 2026-11-14 (lane w1114a-hlens-rules)


## Filed on arrival — 2026-11-14 (lane w1114a-hlens-budget)

- **`RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` — Message your agents from Discord, through upstream's ready-made connector** · group: runtime-followups · from: `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF` · fork / messaging · the build the owner's ruling on `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS` opened: a `Platform` member in `agent_runtime/messaging/models.py`, the token in `credentials.py`, a factory in `serve_lane.py` over the shim, Discord's own answer to each SWITCH_AUDIT finding (the sender gate: `RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM`; read in code, not run: after connect the adapter bulk-syncs upstream's slash commands with `tree.sync`, which its `sync_policy` `off` skips; whether discord.py logs the token or message text was not checked), approval cards as Discord components, and its Eternia page · bundle fit measured 2026-11-14 (w1114a-hmsgadapt): no adapter library enters the bundled-desktop or bundled-phone closure (both ship only the anthropic, mcp and fal extras, and switch off `agent_runtime.messaging`); on a full Harness the locked `discord.py[voice]` adds 14.7 MB installed over the base install, aiohttp's stack included · not shown: a real Discord message, which is the owner's sitting · RULED 2026-11-14: owner — "go with your recommendation after an architecture investigation for this session" (orchestrator, REVIEW_W1114A_B27: the NEXT-APPS ruling chose how, not when; Discord waits with its DEFERRED parent) · NEW 2026-11-14 · DEFERRED 2026-11-14: waits with the DEFERRED parent Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`; the gate it needed, `RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM`, is being built by w1114a-hmsggate · waits: launcher `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`

## Filed on arrival — 2026-11-14 (lane w1114a-hcensus)

## Filed on arrival — 2026-11-15 (lane w1115e-h3)
- **`RT-GENUI-AB-VERIFIES-THE-AGENT-AND-PROVIDER` — The comparison evaluation counts each answer under the agent and provider that actually produced it** · group: windows-handoffs · `evals/genui_first_response_ab.py` (`drive`, `collect`, `PromptResult.provider_key`) · `EterniaLauncher/lib/app/app_functions/app_function_agent_chat.dart` · source-audited 2026-11-15 by codex-win-hermes-handoffs on the exact two Eternia arm commits (`8ee367c821`, `469e500730`): new chat uses the selected agent and ignores the emitted agent/provider args, while scores prefer the planned provider label over the observed context receipt; no provider calls sent. · done when: dry-run each historical Console contract via the existing selected-agent and model-picker doors, pin their readbacks to the fresh chat, and prove a wrong agent/provider/model or absent receipt stays unverified before it can enter a passing cell. · NEW 2026-11-15 · reviewed 2026-11-15 codex-win-handoffs · LIVE CHECK 2026-11-15: open each pinned historical Debug executable in a lane-scoped nonbillable fixture, verify its build stamp and Console agent/session/model readbacks through the v2 preflight · handoff 2026-11-15 (codex-win-hermes-handoffs): v2 eval driver and Windows offline coverage are in `567aff25ec`, `04a3dee9bc` and `90cc579f4e`. Both exact historic console sources expose the required doors. Next read: drive the two historical Debug executables with an isolated model fixture, verify their compiled Stage C build and zero-send Console readbacks, then keep the real A/B behind its separate per-arm approvals. Evidence `docs/agent-runtime-harness/evidence/windows-handoffs-2026-11-15/genui-readiness.md`. · REQUIRES windows, linux
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

- **`RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS` — A command your agent's terminal gave up on stops, rather than finishing its work after the agent was told it timed out** · group: windows-handoffs · moved 2026-11-22 from `runtime-followups` (wave-start sweep w1122b-sweep; owner 2026-11-16: "there should already be a standing rule no windows checks only linux and windows performance rows go into their task"): the Linux half is built and pinned (`tests/tools/test_local_timeout_leaves_no_descendant.py`, landed 572ed14b60); what is left is running that test on the Windows box, a real Windows need (a Windows process tree and a dart shim), so it no longer holds `TASK-RUNTIME-FOLLOWUPS` open · from: launcher `QA-FU-A-HELPER-CLAIMS-IN-THE-SHARED-CHECKOUT-AND-STOPS-ON-ITS-OWN-CLAIM` (w1120a-helperclaim) · seen 2026-11-20 read-only in the owner's install on Windows: session `persona_chat_personainst_dev_agent_8b319ebf_144d0dee5352` ran `dart tool/queue/task.dart --claim … --as dev` with `timeout: 30`; the terminal answered exit 124 "[Command timed out after 30s]" at 18:13:26Z, and the claim commit `b3316bc20a` it was making landed on the EterniaLauncher primary's `main` at 18:13:32Z, six seconds later; the agent's retry was then refused on that claim · cause not read: `tools/environments/local.py` `_kill_process` routes Windows to `_kill_process_windows` (a tree kill); whether `dart` (a shim launching `dart.exe`) or its `git` child escaped it is a guess · done when: a foreground command killed for its timeout on Windows leaves no descendant running (checked with a child that writes a file after the timeout), or the timeout answer says the command may still be running · review w1118a.63: passed; seen in the owner's install (the claim commit landed 6 s after the timeout answer), the cause not read · Eternia's `QA-FU-A-QUEUE-CLAIM-TAKES-A-MINUTE-ON-WINDOWS` is the speed half and went to the Windows handoffs; this row is the half that loses work · architecture: `tools/environments/local.py` is an upstream file already in the fork's footprint ledger; fork-owned seams first — if the tree kill cannot reach a `dart` shim's children, the fork-side answer (the timeout reply says the command may still be running) is the one owner of what the agent is told · the done when's check (a child that writes a file after the timeout) runs on Linux too, so the lane runs it there first and the Windows read is REQUIRES windows · reviewed 2026-11-20 w1118a.63 · REQUIRES windows · READY 2026-11-20 · handoff 2026-11-20 (w1118a-hrt4): Linux half done and pinned: the done-when check runs on Linux and passes (a child, a grandchild, a setsid child and a backgrounded subshell of a command timed out after 2 s, none wrote its file after the 124 answer); `tests/tools/test_local_timeout_leaves_no_descendant.py` (895c398cce, landed 572ed14b60) is that check through the real local backend, red when `LocalEnvironment._kill_process` kills only the shell. Windows not read (this host has none): run that test on the Windows box (it is on Eternia QA-WINDOWS-LIVE-READS-OWED-1). If it is red there, the candidate read in code (not reproduced) is `_kill_process_windows` falling back to `proc.kill()`, the shell alone, when `terminate_pid`'s start-time guard refuses; else the tree kill not reaching a dart shim's children (guess). Nothing fork-side changed: with no survivor seen, a timeout reply saying the command may still be running would be untrue on Linux

## Filed on arrival — 2026-11-20 (Eternia lane mc-running-now: the hermes halves of `MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT`)


## Filed on arrival — 2026-11-20 (review w1118a.58: the hermes halves of Eternia's Running now and stopped-request rows)


## Filed on arrival — 2026-11-20 (Eternia lane w1120a-unseated: agents a lead added that stood on no office level)


## Filed on arrival — 2026-11-20 (review w1118a.63: what hermes lane w1118a-hrt3 reported)


## Filed on arrival — 2026-11-20 (lane w1118a-hrt4: the live read of the built-in skill rule)


## Filed on arrival — 2026-11-20 (lane w1120a-slotrules: the shipped lead's prompt)


## Filed on arrival — 2026-11-21 (lane w1118a-sw71-hm: what the discussion-view fix left)


## Filed on arrival — 2026-11-21 (Eternia lane w1118a-sw71-el: the realm banner and the composer refusal line)


## Filed on arrival — 2026-11-21 (lane w1118a-onepath-el2: the hermes half of Eternia MC-ONE-DOOR-PLACES-AN-AGENT-FROM-EVERY-SURFACE)

## Filed on arrival — 2026-11-21 (Eternia lane w1118a-sw73-mc: the realm banner's kinds, read live)



## Filed on arrival — 2026-11-21 (coordinator, from Eternia lane w1118a-sw74-a: a send to an unplaced agent)

## Filed on arrival — 2026-11-21 (review w1118a.76: the hermes half of Eternia's last argv callers)

## Filed on arrival — 2026-11-21 (review w1118a.78: the template plan's history and cleanup rows)

## Filed on arrival — 2026-11-21 (review w1118a.80: the root flaw under the phone's second-profile pydantic stop)

## Filed on arrival — 2026-11-21 (review w1118a.84: who may read an agent's project files)

## Filed on arrival — 2026-11-21 (review w1118a.81: the phone git port's status and history, moved from Eternia)


## Filed on arrival — 2026-11-21 (owner: "live" means an alive instance with its live chat)

## Filed on arrival — 2026-11-21 (owner: one file-tool interface on every platform, ripgrep in process)

- **`RT-PHONE-FILE-TOOLS-TAKE-THE-SAME-ARGUMENTS-AS-ON-DESKTOP-WITH-RIPGREPS-ENGINE-IN-PROCESS` — Regex search by an agent on a phone runs ripgrep's own engine inside Hermes, bounded like a desktop's** · group: mission-control-on-mac · from: Eternia `MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES` (closed DONE 83a9176f12d; its fork tools `agent_runtime/phone_file_tools.py` are a subset of upstream's schemas) · seen in code 2026-11-21 w1118a-coord: upstream `tools/file_tools.py` `patch` takes `mode` (replace or a V4A multi-file patch) and `search_files` takes `target` (content or files), `file_glob`, `limit`, `offset`, `output_mode`, `context` and a regex `pattern` (run by `rg`); the phone versions take `path`/`old_string`/`new_string`/`replace_all` and `pattern`/`path` (literal) only, so an agent that uses the desktop arguments fails on a phone · RULED 2026-11-21: owner — "so the agent calls the same interface on all platform though right its just the lower level thats platform specific?" then, asked whether to file it with ripgrep's engine through FFI first and the `regex` package as the fallback, "yea sounds good" · done when: the phone tools register upstream's exact schemas (a test diffs them against `tools/file_tools.py`'s and reds on any drift); `patch` V4A mode goes through `project_files/writer.py` per file; `search_files` supports `target: files` (the spec's file-name glob), `file_glob`, `limit`/`offset`, `output_mode` and `context` over the reader; regex runs ripgrep's own crates (`regex`, `grep-searcher`, `ignore`) built as an in-process native module (pyo3 or a C ABI through ctypes), called on a worker thread with the GIL released and a cancel flag at the 2000 ms search deadline, built for Android arm64/x86_64 and iOS device/simulator and shipped in the phone bundle; if the Rust build cannot ship on a target, that target falls back to the `regex` package (already in `uv.lock`) with its `timeout=`, and if neither can ship, regex is refused in words — never Python `re` on caller input · architecture: hermes fork files only (`agent_runtime/phone_file_tools.py`, `project_files/`, a new native module under `agent_runtime/` with its Rust crate, the phone bundle packager); upstream file tools untouched; the native module may later be loaded by Eternia through `dart:ffi` (the owner's shared-FFI question) but this row does not do that · security: the native search reads only the reader's confined roots (paths resolved by `project_files` before the call, never by the native side); no process is started; the deadline holds; V4A patches pass every writer check per file · rewritten 2026-11-21 review w1118a.86: was 'An agent calls read_file, write_file, patch and search_files the same way on a phone as on a desktop, and regex search on a phone runs ripgrep's own engine inside Hermes' — split; the arguments half is `RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT`, which ships first, and this row keeps the owner's ruling and the in-process regex engine · review w1118a.86: passed and split; schema list checked; native plan, packaging, toolchain and fallback read; path corrected · done when after the split: the clauses on upstream's schemas, V4A mode and the non-regex search options move to `RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT`; this row's done-when is its regex clause (ripgrep's crates in process, GIL released, the cancel flag at the deadline, built and shipped for the phone targets, then the owner's fallback order) with the `ignore` crate dropped as below · schema list, read in code (hermes 90aeedf7f3): right, with two gaps — `search_files` also takes `order` (discovery or modified), and patch's base schema is replace-only: `mode`/`patch` (V4A) are layered by `_patch_schema_overrides` for OpenAI-family mains only, while `_handle_patch` accepts them from any model; both now sit on `RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT` · path correction: the reader and writer are `agent_runtime/project_files/reader.py` and `agent_runtime/project_files/writer.py`, not `project_files/` · architecture correction: drop ripgrep's `ignore` crate — the reader's walk (`agent_runtime/project_files/ignore.py`, the rule spec Eternia and hermes both follow) stays the one owner of which files are searched, so Python walks, confines and size-caps, and the native side only matches (`regex` + `grep-searcher`) over the paths or bytes it is handed; a second walker would be a second owner of the ignore rules · native plan, read in code: GIL release and a cancel flag fit either binding — ctypes releases the GIL on every `CDLL` call and needs no CPython headers, one library per ABI; pyo3 builds per CPython (cp314) and releases it with `allow_threads`; Rust's `regex` is linear-time, so the 2000 ms deadline (`agent_runtime/project_files/rules.py` `SEARCH_DEADLINE_MS`) bounds tree size, not backtracking · packaging today, read in code: the phone packager builds nothing from source — Android Pillow is Flet's prebuilt wheel pinned by URL and sha256 in `agent_runtime/bundle_profiles/phone_wheels.lock.json` (`scripts/bundles/phone_wheels.py`), its libraries loaded by path in `agent_runtime/phone_native_libs.py`, and the gate (`scripts/bundle_profile_gate.py`) admits only the compiled distributions named in `agent_runtime/bundle_profiles/bundled-phone.yaml` `packaging.admitted_native` (Pillow and its four companions; the yaml says architecture §6 admits Pillow alone); shipped targets are `android_arm64` and `ios_arm64`, with `android_x86_64` and `ios_arm64_simulator` QA-only (`scripts/bundles/targets.py`); iOS packaging of any phone native module has not been tried · toolchain, seen 2026-11-21 on this box: there is one now — rustup stable 1.100.0 under `~/.cargo/bin` (folder dated 2026-11-21 21:29, a minute after the ruling), host target `x86_64-unknown-linux-gnu` only, not on the default PATH, no Android target, no maturin; Android NDK 28.2.13676358 is installed; iOS needs a Mac; `apps/bootstrap-installer/src-tauri` is still the only crate in the repo · fallback, read in code: `regex` is in `uv.lock` only as a dependency of curated-tokenizers, misaki, segments and transformers, with desktop wheels only (no android or ios wheel), and it is compiled C — so on a phone it needs the same cross-build as the Rust module and is a second admitted native distribution; the owner's order (ripgrep's engine, then `regex` with `timeout=`, then a refusal in words, never Python `re`) stands, and the plan states what each step costs and brings back to the owner any step that cannot ship · security, added: the native side opens only paths `project_files` resolved and never follows a link (or Python opens and hands bytes); the compiled pattern is bounded (`RegexBuilder` size and DFA limits, a pattern-length cap) so caller input cannot exhaust memory; the cancel flag is checked per file and per match batch · same-file sweep: no other open runtime or fork-hygiene row names `phone_file_tools.py`, `project_files/` or `bundled-phone.yaml`; Eternia `MC-PHONE-SIZE-BUDGET-NEVER-MEASURED` will want the module's size per ABI · edge cases documented, not worked: a file swapped for a link between resolve and open; a pattern valid for ripgrep and not for `regex` (or the reverse) when one target falls back; a match inside a 5 MB file near the deadline · order: the plan can start now; the build waits for `RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT`, which owns the same `search_files` handler · group kept: runtime-followups · size L · reviewed 2026-11-21 w1118a.86 · review w1118a.87: the plan (591fa64d7c) read in code; it stays within the ruling; the three build rows passed with corrections on them; BLOCKED on them is right, and C may close on the `regex` fallback, which the ruling covers; the wheel-hosting choice is with the owner (on `RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID`) · reviewed 2026-11-21 w1118a.87 · BLOCKED 2026-11-21: hermes — `RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE`: planned (`docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md`); closes when the last build row closes · handoff 2026-11-21 (w1118a-rgplan): plan written at 591fa64d7c: `docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md` — recommends (not ruled) ctypes over a C ABI, crates regex + grep-regex + grep-searcher (grep-regex added: ripgrep's own matcher, 2–11x faster on 5 MB and refuses a literal newline as rg does; no ignore crate), bytes in and line numbers out, a pinned library wheel through phone_wheels.lock.json committed in the repo; spike ran: arm64 .so 1.89 MB, 16 KB-aligned, GIL released, iOS links only on a Mac; fallback correction: Flet's index has cp314 Android and iOS regex wheels (2026.5.9, 2026.11.9), so step 2 needs no cross-build, only uv.lock's regex 2026.9.29 bumped; build rows filed READY: RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY, RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID, RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE (REQUIRES macos); this row closes when the last of them does · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 5, option (a): the iPhone and Mac rows of the phone work move to Eternia `TASK-MISSION-CONTROL-ON-MAC` so the Android phone task can close (a host never holds a feature task open); not taken: (b) keep them where they were until a Mac sitting · handoff 2026-11-22 (w1122b-rulings): moved from `TASK-RUNTIME-FOLLOWUPS` to Eternia `TASK-MISSION-CONTROL-ON-MAC` (`group: mission-control-on-mac`; hermes has no Mac task of its own, and a task may hold subtasks in any brain) — it waits on `RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE` and moves with it; its status is kept
- **`RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE` — An agent on an iPhone can search its project files with a regular expression** · from: `RT-PHONE-FILE-TOOLS-TAKE-THE-SAME-ARGUMENTS-AS-ON-DESKTOP-WITH-RIPGREPS-ENGINE-IN-PROCESS` (plan `docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md` §6, §8, §9 C) · RULED 2026-11-21: owner (on the parent) — asked whether to file it with ripgrep's engine through FFI first and the `regex` package as the fallback, "yea sounds good" · ran 2026-11-21 (w1118a-rgplan spike): `aarch64-apple-ios` compiles here as a staticlib (8.6 MB .a) but a cdylib fails at link without Xcode · guess: CPython's iOS layout (binaries in .framework bundles) also serves a plain library loaded by ctypes — this row reads it first · order: after `RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY` · done when: on the Mac the matcher links for `aarch64-apple-ios` and `aarch64-apple-ios-sim`, each is wrapped as a framework, loads through `ctypes.CDLL` in CPython 3.14's iOS testbed on the simulator and answers a regex search, and is pinned for `ios_arm64` and `ios_arm64_simulator`; if a plain library cannot ship on iOS, iOS takes the plan's step 2 (Flet's cp314 iOS `regex` wheels, with `uv.lock`'s regex bumped 2026.9.29 → 2026.11.9 — only a refused bump goes to the owner) and Android keeps the native engine · architecture: fork-owned — the build script, `phone_wheels.lock.json`, `bundled-phone.yaml`; Eternia embeds no Python on iPhone yet, so this row proves the library in CPython's testbed, not in Eternia · group: mission-control-on-mac · size M · REQUIRES macos · filed 2026-11-21 w1118a-rgplan · review w1118a.87: passed; REQUIRES macos stands (the iOS cdylib links only with Xcode; this box has no Mac) · the fallback bump, read in uv.lock at 4355243f0f: `regex` 2026.9.29 is pulled only by transformers, misaki, segments and curated-tokenizers, all reached through the opt-in `kittentts` extra (misaki[en] → transformers, phonemizer-fork → segments; spacy-curated-transformers is removed by a never-true marker), and the KittenTTS closure ships in no bundle (pyproject.toml's note at l.619) — so on a desktop the bump moves only the `regex` a user gets when they install KittenTTS; unread: that 2026.11.9 has PyPI wheels for every desktop target uv.lock resolves; once a phone pins `regex`, any later desktop move of it must move the phone pin too (`phone_wheels.version_problems`) · if the fallback is taken: `regex` joins `admitted_native` for iOS only and Eternia's §6 amendment (row B) names it · architecture: confirmed; the read is in CPython's iOS testbed, not in Eternia · security: confirmed; signing the framework belongs to the day Eternia ships Python on iPhone, not this row · reviewed 2026-11-21 w1118a.87 · READY 2026-11-21 · review w1118a.90: its "if the fallback is taken" clause meets the owner's 2026-11-22 ruling on the Android twin (`RT-FU-AN-ANDROID-PHONE-WHOSE-MATCHER-DOES-NOT-LOAD-STILL-SEARCHES-WITH-THE-REGEX-PACKAGE`: "a ideally you should get ripgrep working even if it fails"); that ruling names Android only, so whether it binds iPhone too is put to the owner (recommend: yes, make the matcher load on iPhone, no `regex` fallback); nothing else changes and the row stays READY, REQUIRES macos · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 5, option (a): the iPhone and Mac rows of the phone work move to Eternia `TASK-MISSION-CONTROL-ON-MAC` so the Android phone task can close (a host never holds a feature task open); not taken: (b) keep them where they were until a Mac sitting · handoff 2026-11-22 (w1122b-rulings): moved from `TASK-RUNTIME-FOLLOWUPS` to Eternia `TASK-MISSION-CONTROL-ON-MAC` (`group: mission-control-on-mac`; hermes has no Mac task of its own, and a task may hold subtasks in any brain) — iPhone only (REQUIRES macos: the iOS library links only with Xcode); its status is kept
- **`RT-FU-AN-ANDROID-PHONE-WHOSE-MATCHER-DOES-NOT-LOAD-STILL-SEARCHES-WITH-THE-REGEX-PACKAGE` — On an Android phone where ripgrep's matcher library cannot load, an agent's regex file search still runs, through the regex package** · group: runtime-followups · from: `RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID` (lane w1118a-regex; the coordinator's brief asked for it, the row's done-when did not) · read 2026-11-21 in plan `docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md` §8 step 2 (not re-read on the index): Flet's index has cp314 `regex` wheels for android_24_arm64_v8a and android_24_x86_64 at 2026.11.9; `uv.lock` pins regex 2026.9.29 and `phone_wheels.version_problems` refuses a phone pin at another version, so the pins need the lock bumped to 2026.11.9 (a desktop transitive dependency of transformers, misaki, segments, curated-tokenizers) · held by w1118a-regex: Android ships the matcher, so this is only a second engine for a failed load, and the bump moves a desktop dependency and needs network downloads; iPhone needs the same pins if `RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE` cannot ship the library · done when: `regex` is pinned per Android target in `phone_wheels.lock.json` with a `loaded_by` of `agent_runtime.project_files.fallback_match`, `uv.lock` pins the same version, `bundled-phone.yaml` admits it citing the owner's ruling, its .so files pass the 16 KB read, and a test reds when the pin and the lock differ · architecture: fork-owned, `agent_runtime/bundle_profiles/`, `uv.lock` · size S · filed 2026-11-21 w1118a-regex · plan question 2026-11-21 (was NEEDS PLAN): whether an Android fallback is worth a desktop lock bump; if the bump is refused, the owner picks between a cross-build of 2026.9.29 and a per-name exemption (plan §8) · DEFERRED 2026-11-22 · RULED 2026-11-22: owner — "a ideally you should get ripgrep working even if it fails": no `regex` fallback and no desktop lock bump now; if ripgrep's matcher fails to load on a device, the work is to make the matcher load there, not to fall back; reopen only if a device read shows a load failure that cannot be fixed · waits: RT-FU-RIPGREPS-MATCHER-LOADS-ON-A-PHYSICAL-ANDROID-PHONE · review w1118a.90: ruling recorded, not re-opened; the waits field names the one read that could re-open it (`RT-FU-RIPGREPS-MATCHER-LOADS-ON-A-PHYSICAL-ANDROID-PHONE`, BLOCKED owner sitting), so `wake.dart` puts it on the owner list when that read closes; nothing to dispatch
- **`RT-FU-RIPGREPS-MATCHER-LOADS-ON-A-PHYSICAL-ANDROID-PHONE` — On a real Android phone, an agent's regex file search loads ripgrep's matcher from the library the app ships, so its size figure can be accepted** · group: runtime-followups · from: `RT-FU-A-REGEX-SEARCH-ON-THE-ANDROID-EMULATOR-RUNS-THE-SHIPPED-MATCHER` · carried from that row's close (w1118a-emu3, 2026-11-22): read live on the x86_64 emulator only; the physical-device load its done-when also named (Eternia architecture §6 as amended 10ebfee6102: the size figure is accepted after the same load on a physical Android device) cannot be read without one · done when: on the owner's arm64 phone, with an engine-bundled APK packaged at or after 3bfe7ac796, a regex `search_files` turn answers with matches, `libproject_files_match.so` is mapped in the app's process and the agent log has no "regex search falls back" line, read through `launcher_qa` · architecture: fork-owned, read only · size XS · filed 2026-11-22 w1118a-emu3 · waits: phone-sitting · read 2026-11-23 in the owner sitting (Eternia lane w1123a-sitting; APK packaged from hermes 6c0f433bbb, after 3bfe7ac796): `libproject_files_match.so` is mapped in the app's process (4 lines in `/proc/<pid>/maps`) and no agent log holds "regex search falls back"; a Base turn on Claude ran `search_files` in regex mode, but it answered "Path not found … this device has no project folder yet" (`outside_root`) and 0 matches with no path — the owner cleared Eternia's storage on 2026-11-22, so the phone holds no project folder; the matches half waits for a project folder with files on the phone; not read through `launcher_qa` (adb from this PC) · BLOCKED 2026-11-22: owner sitting — the owner's physical Android phone · review w1118a.90: passed as an owner sitting (the owner's physical arm64 phone is the only way to read it); its `waits: phone-sitting` and status agree; the DEFERRED Android fallback row waits on it, which is right under the owner's 2026-11-22 ruling there · reviewed 2026-11-22 w1118a.90 · RULED 2026-11-22: owner said "yes go as reccomended" — w1122b owner list item 4, option (a): one Android phone sitting with the owner (about 15 minutes) covers this row and Eternia `MC-PHONE-DICTATION-HEARD-ON-THE-OWNERS-PHONE` (dictation heard on his phone) together; not taken: (b) defer both; stays BLOCKED owner sitting until that shared sitting

## Filed on arrival — 2026-11-21 (review w1118a.88: what the phone engine left out, and the phone's recipe platform, moved from Eternia)

## Filed on arrival — 2026-11-22 (review w1118a.90: the owner's same-account sharing ruling, from Eternia)


## Filed on arrival — 2026-11-22 (Eternia lane w1122b-vtree: the engine reads a virtual tree with no turn)
- **`RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN` — A device driving this one, or an agent with no chat open in Eternia, reads Eternia's generated documents on this device by asking this device's Eternia** · group: phone-harness · from: Eternia `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA` (its hermes half; task Eternia `TASK-PHONE-HARNESS`) · read in code 2026-11-22 (w1122b-vtree, hermes 0f3e6ed1dc): `agent_runtime/launcher_app_functions.py` asks Eternia only through a turn's bound link (`offered_to_bound_link`, `current_launcher_link`), and `hermes_cli/harness_parts/serve/lanes.py::_launcher_link` builds a link only for a turn or an open-chat; a caller with no turn (a remote device's file view on `runtime.agent.files.*`) has no way to reach a virtual root · architecture (Eternia plan `docs/embedded_hermes/planned/PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md` §4, §7, §8, §11): one new seam, a device-local Eternia link in `launcher_app_functions.py` chosen from owner connections only (`local_console` or `stdio_owner`) that declared `answers: ["launcher."]`, by the existing most-recent-declarer rule (`latest_answerer`); never a peer link and never a paired device's own Eternia; a virtual-root read with no bound turn link is asked there over `launcher_client_requests.py` (`launcher.generated.tree` / `read` / `grep`), origin `paired_device` when a remote caller asked, `local` otherwise; a remote caller is held to `read` tier for reads and `console` tier for writes (`launcher.generated.patch` / `write` / `move`) before anything is asked; hermes' own reader refuses a write to a virtual root `virtual_root_read_only`; with no declared owner connection the call refuses `virtual_tree_unavailable` ("Eternia is not open on this device") · Eternia half: the six verbs admit origin `paired_device` (they refused it `not_reachable_from_caller`), built by w1122b-vtree in Eternia e096aa46853 · security: the peer allowlist is not widened; a view-only device gets reads only · done when: with no turn open, a call through the serve dispatch reads a generated document's tree, file and grep on this device's Eternia; the same from a paired device is held to its tier; with Eternia closed it refuses `virtual_tree_unavailable` (tests, and the Eternia row's live read) · size M · review w1122b.3 2026-11-22: passed; architecture confirmed, fork-owned seams only: the device-local link is one new chooser in `agent_runtime/launcher_app_functions.py` over owner connections by the existing `latest_answerer`, and `hermes_cli/harness_parts/serve/lanes.py::_launcher_link` stays the turn path; the reach tiers live once in `agent_runtime/call_authorization.py` (the `runtime.agent.files.*` entries), never a second table in the new seam; the new refusal `virtual_tree_unavailable` is a file-rule-spec code, whose one owner is Eternia's `packages/eternia_file_tree_spec/spec/rules.json`: Eternia `MC-PHONE-FILES-THE-FILE-RULES-NAME-ETERNIA-IS-NOT-OPEN-ON-THIS-DEVICE` (XS, passed this batch) adds it first, then this lane vendors it with `scripts/vendor_launcher_catalog.py` into `tests/fixtures/file_tree_spec/` and `agent_runtime/project_files/rules.py`'s code set, never a hand copy; file map: `launcher_app_functions.py`, `call_authorization.py`, `project_files/rules.py`, the vendored spec, `launcher_client_requests.py` (read; the request shape stays) and their tests; security: confirmed — the chooser takes owner connections only, never a peer link or a paired device's Eternia; the tier is checked here before Eternia is asked, and Eternia's `paired_device` admission (e096aa46853) relies on that check, so a test reds a view-only caller's write before any request leaves hermes; same-file sweep: no other open row in this queue names these files · reviewed 2026-11-22 w1122b.3 · RULED 2026-11-22: owner answered "rest as reccomended" to the recommendation "virtual folders through the engine from another device: console tier only" — the console tier for reads and writes as built (cd23f961b9) stands, not the read tier the row's architecture first wrote · LIVE CHECK 2026-11-22: from a device driving this engine (two paired Linux QA copies, or the emulator), with no turn open call runtime.agent.files.virtual tree/read/grep on a generated document and read its files, send a patch and read it land through Eternia's validated edit, then close this device's Eternia and read the refusal virtual_tree_unavailable (Eternia `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA` owns the read) · handoff 2026-11-22 (w1122b-hmfour): built cd23f961b9 by w1122b-hmfour: runtime.client.capabilities records the sink of a declaring connection whose caller is the machine owner (call_authorization.is_machine_owner); launcher_app_functions.device_local_launcher_link chooses among those only by latest_answerer (never a peer's or a paired device's Eternia; a closed connection drops out); new verb runtime.agent.files.virtual {verb: tree|read|grep|patch|write|move, args} asks launcher.generated.<verb> there with origin local (owner) or paired_device (anyone else), on the worker lane, and refuses virtual_tree_unavailable with no owner Eternia; the code vendored from Eternia f5a6ad55551 (scripts/vendor_launcher_catalog.py --file-tree-spec). Tier: console for reads and writes, NOT read for reads as this row's architecture wrote — the plan's §11 (corrected by review w1118a.84) and runtime.agent.files.* hold an agent's files at console, so a view-only device is refused both before any request leaves hermes; owner asked in the lane report. Tests tests/agent_runtime/test_agent_files_virtual_tree.py, red under: every caller's sink an owner sink; a closed connection's sink kept; the verb at read tier; origin local for every caller. Not in any computer grant allowlist (filed RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS). Not read live: the read needs Eternia driving this engine from another device (the emulator or two paired Linux copies), the Eternia row's read; claim released
- **`RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS` — A computer driving a phone's agents reads the phone's generated documents too** · group: runtime-followups · from: `RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN` (lane w1122b-hmfour) · read in code (hermes cd23f961b9): `runtime.agent.files.virtual` is one verb carrying reads (tree/read/grep) and writes (patch/write/move), and it is in no computer grant allowlist (`agent_runtime/call_authorization.py` `COMPUTER_LOOK_METHOD_ALLOWLIST` / `COMPUTER_CHAT_METHOD_ALLOWLIST`), so a computer on the reverse lane is refused it while it reads the phone's real folders through `runtime.agent.files.*`; adding the verb to the look allowlist as it stands would hand a look grant the writes · likely fix (guess): split the verb into a read verb and a write verb, or check the grant per `verb` in `agent_runtime/serve_rpc/agent_files.py` with the reach stated once in `call_authorization.py`; a look grant reaches the reads, a chat grant the writes · security: a look grant never reaches patch/write/move; the peer allowlist stays unwidened · done when: a test reds a look-grant computer's patch before any request leaves the phone's hermes and admits its tree read, and the Eternia reverse-route read shows a computer listing a phone's generated document · size S · filed 2026-11-22 w1122b-hmfour · review w1122b.4 2026-11-22: passed, changed: the reads only — the title's "on a chat grant, changes them" is cut, because a Run chats grant today reaches chat turns and never the phone's documents, and giving it writes is a widening only the owner can choose (asked in the w1122b.4 report; review decision note, not an owner ruling: writes stay off both computer grants; a computer on the phone's own account already reaches them through `paired_device_answers` at console, owner 2026-11-22); architecture: the computer grants are method-name allowlists that ignore a verb's tier (`agent_runtime/call_authorization.py`, "the tier a verb declares does not enter into it"), so a per-`verb` check inside `agent_runtime/serve_rpc/agent_files.py` would state reach a second time and is refused; the one-owner fix is to split the method: `runtime.agent.files.virtual` keeps tree / read / grep, and patch / write / move move to a new console-tier method (`runtime.agent.files.virtual.write`, name the lane's), whose dispatch stays the existing device-local link and worker lane; `runtime.agent.files.virtual` joins `COMPUTER_LOOK_METHOD_ALLOWLIST` beside `runtime.agent.files.*`, the write method joins no computer allowlist; no Eternia code calls either yet (Eternia `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA` will, and its handoff names the split); file map: `agent_runtime/serve_rpc/agent_files.py` (the two methods and their manifest params), `agent_runtime/call_authorization.py` (the look allowlist), tests `tests/agent_runtime/test_agent_files_virtual_tree.py` and the reverse-lane grant tests; security: a look or Run chats computer reads only; its write is refused before any request leaves the phone's hermes; the peer allowlist is not widened; Eternia's `paired_device` admission still relies on this check; done when (as changed): a test reds a look-grant computer's write (any of patch / write / move) and admits its tree read, a same-account computer's write is still admitted, and the Eternia reverse-route read shows a computer listing a phone's generated document; same-file sweep: the open rows naming these files (`RT-FU-A-DEVICE-DRIVING-THIS-ENGINE-OPENS-THE-DIFFS-AND-CONTEXT-FILES-ITS-AGENT-WROTE`, `RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN`) are LIVE CHECK, none READY, so nothing bundles · reviewed 2026-11-22 w1122b.4 · RULED 2026-11-22: owner answered "rest as reccomended" to the recommendation "a computer on another account at Run chats changing a phone's generated documents: no" — writes stay off both computer grants, as built (c6332a4d2f: `runtime.agent.files.virtual.write` is in no computer allowlist) · BLOCKED 2026-11-24: launcher — `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA`: the hermes half is built and green; the owed live read (a computer on your account lists and reads a phone's generated document over the reverse route) needs Eternia's first caller of runtime.agent.files.virtual · handoff 2026-11-22 (w1122b-hmsplit): built c6332a4d2f: runtime.agent.files.virtual keeps tree/read/grep and is in COMPUTER_LOOK_METHOD_ALLOWLIST (so Run chats too); patch/write/move moved to the new console-tier runtime.agent.files.virtual.write, in no computer allowlist; one shared dispatch (_ask_virtual), no per-verb grant check; the owner and a same-account computer still write. Tests test_agent_files_virtual_tree.py and test_reverse_grant.py, red under: the look allowlist without virtual; the look allowlist with virtual.write; VIRTUAL_READ_VERBS naming the writes; the write method asked with the read verbs. No Eternia code names either method yet, so the Eternia row must call virtual for reads and virtual.write for writes. Not read live: no Eternia caller exists yet, so the reverse-route read waits on the Eternia row; claim released · handoff 2026-11-22 (w1122b-emu3): 2026-11-22 w1122b-emu3: live read still owed — the emulator sitting (Eternia 9f4dcca0a61 APK, hermes bundled-phone edae6608af, at/after c6332a4d2f) could not reach it: no Eternia code calls runtime.agent.files.virtual or runtime.agent.files.virtual.write yet (the remote file view's caller is Eternia MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA's left half), so the read waits on that Eternia wiring · handoff 2026-11-22 (w1122b-emu4): 2026-11-22 w1122b-emu4: not read — no Eternia code calls runtime.agent.files.virtual from a computer yet (searched lib/ and packages/ at Eternia 67761448da9), so the computer has no way to list the phone's generated documents; the live read stays owed to Eternia MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA's client; claim released · handoff 2026-11-24 (w1122d-hmauthz): premise re-checked at hermes 370ec836ea, nothing built: the hermes half still holds and is green (tests/agent_runtime/test_agent_files_virtual_tree.py 16 passed): since account-only pairing (RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN) the Look and Run chats grants and COMPUTER_LOOK/CHAT_METHOD_ALLOWLIST are gone, so the done-when's look-grant write refusal is moot: a retired-level computer is refused before any request leaves hermes (test_a_retired_level_computer_is_refused_before_any_request_leaves_hermes), and the one account-level computer reads runtime.agent.files.virtual and writes runtime.agent.files.virtual.write like a console device (test_a_same_account_computer_reads_the_phones_generated_documents, test_the_owner_and_a_same_account_computer_still_write); the access_off arm (ee464b532f) never reads a computer caller (_access_arm, is_remote_user); the one-call row (8f7285815d) keeps a grant-holding computer a computer caller on a call lane, so the same answer applies. What is left is only the live read, and no Eternia code calls either method yet: it waits on Eternia MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA (its title covers a device driving this one); claim released · waits: `MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA`

## Filed on arrival — 2026-11-22 (lane w1122c-sweep: rows the owner's w1122b answers asked for)

## Filed on arrival — 2026-11-22 (Eternia lane w1122a-bgquestion: the hermes half of a question asked in a background turn)


## Filed on arrival — 2026-11-22 (Eternia lane w1122d-emu, the emulator sitting; filed and reviewed by review w1122d.4)


## Filed on arrival — 2026-11-22 (lane w1122e-sessioninfo: the crash after every finished turn on the owner's serve)


## Filed on arrival — 2026-11-22 (lane w1122e-homeslow-rt: the two waits on a send from Eternia's home)

- **`RT-FU-THE-AGENT-LIST-REBUILD-RE-READS-EVERY-CHAT-WORD-BY-WORD-EACH-TIME` — Eternia's agent and chat lists refresh in about a second instead of four, because unchanged chats are not re-checked line by line on every rebuild** · group: runtime-followups · from: Eternia `MC-HOME-FIRST-SEND-IS-SLOW` (lane w1122e-homeslow-rt) · seen 2026-11-22 (owner's `agent.log`, hermes 1c98abe30bbb): every `snapshot_build_core` after boot costs 3.8-4.7 s with `persona_chat` 2,093-2,439 ms of it, and a one-shot `cli_stream` hydrate after a send waited 9,203 ms on one (Eternia's refresh asks for an authoritative core: `stream/session.py` `stale_first` refuses a one-shot by design) · measured, hermetic (12 chats x 300 rows, cProfile, lane scratch only): `persona_chat` 1,002 ms of a 1,260 ms build; `history_rows.py` `_history_row` -> `curation.py` `_safe_curated_messages` curates EVERY stored row of every listed chat on every build (3,600 `CurationState.curate` calls, 1.13 s of 1.69 s profiled), each row redacted twice (`text.py` `_curate_chat_message_text` then `_safe_display_body_text`, 7,236 `mask_known_key_shapes`), though the frame keeps only recency pointers and the tail is 40 rows · not measured on the owner's data (the lane may not copy the namespace) · likely fix (guess): memo the curated tail, `visible_message_count` and redaction status per chat on a key that moves with everything curation reads (the lineage's stored rows, the turn journal records AND each turn's `elements`, the vault registry), so an unchanged chat costs one read; the double redaction is a second, smaller cut once its idempotence is shown · done when: a steady-state build on the owner's box reports `persona_chat` under 500 ms with the chat views unchanged (`test_persona_assignments_chat_history.py` green) · READY 2026-11-22 · handoff 2026-11-22 (w1122f-agentlist): w1122f-agentlist landed 05424d7b9b9b (each chat's turn journal read once, not once per turn; each row scrubbed once, not twice), 7a763d20255e (per-chat curation memo keyed on a blake2b of the stored rows, the journal file bytes of the chat and its history sources, tip, archived ids, preview, redaction mode, llama gate; mid-turn element and in-place row rewrite proven to show) and 72d4e5e01bcf (new log receipt snapshot_persona_chat history_ms trace_ms channels_ms). Bench at the owner's scale (50 chats, 1,190 rows, 2.69 MB, synthetic text): persona_chat_history_summary 1,439 -> 936 -> 261 ms. Live on the owner's box (seen live): steady persona_chat 2,073-2,439 ms before; 1,656 ms after the first two (19:41:34); 1,090 ms with the memo (19:51:33, gen 2, build_ms 3,040 from 3,818-4,702). Not yet under 500 ms: the owner's primary is at ddf4ced377ca, so the split receipt is not live; the next read of snapshot_persona_chat names which of history, trace (page_chat_trace_by_turn re-reads each chat's journal) or operator channels pays the rest. Not done · handoff 2026-11-22 (w1122f-agentlist, recent ten): c2ed192dd994 bounds the frame to 10 recent chats plus pins; read live on bc46eec6be32 (seen live): the persisted core kept 19 of 400 persona chats (10 recent, 9 bound pins), yet snapshot_persona_chat read history 1,868 / trace 521 / channels 36 ms cold (21:39:44) and 724 / 662 / 78 steady (21:40:24), against 500 / 396 / 23 steady on 72d4 with the bound at 50 - the kept count was not the cost: `_session_pool` still paged all 400 rows (children included) in pages of 40 for omission accounting, and every build walks the turn journal (94 files, 2.6 MB) and the clarify tickets for the pins. This lane then reads the frame pool as ONE activity-ordered page and the pins by id (fork-side, `history_rows._session_rows_by_id`, the list query's own projection; upstream untouched), counts the rest with one COUNT(*) for the by-design `limit` drop, and logs `pins_ms` inside history_ms; the trace was checked and walks one bound chat per instance only (each pinned in the frame). Before/after pool numbers: read on the next live build after landing · handoff 2026-11-22 (w1122f-agentlist): (w1122f-agentlist, released) after 7c0f1704485f (one recent page plus pins by id, COUNT(*) for the limit drop, pins_ms), seen live cold boot 23:02:10 (serve pid 21476, box under 5 lanes): snapshot_persona_chat history 3,606, trace 799, channels 41, pins 126 ms, build_ms 16,121 (prompt_observability 2,812 against 1,815 the boot before, so the box ran about 50% slower) against 1,868, 521, 36 cold on bc46; no steady build came in the 6 minutes after boot (no demote at all), so the steady before/after is still owed; cold history is now the curation of the 19 kept chats with an empty in-process memo, so the next cut is a persisted curation memo; the pins could come from the in-flight rows the running_work section of the same build already reads
- **`RT-FU-EVERY-AGENT-LIST-BUILD-WAITS-FOR-ITS-CACHE-COPY-TO-REACH-THE-DISK` — Eternia's agent list arrives as soon as it is built, not after the copy kept for the next start is written** · group: runtime-followups · from: `TASK-RUNTIME-FOLLOWUPS` (lane w1122f-agentlist audit) · seen live 2026-11-22 (owner's `agent.log`): every led build's waiters are released only after `core_cache.persist.write_back` returns (`snapshot/build.py` calls it before `_release_coalescer`): `snapshot_build_core` to `snapshot_core_cache_write` 213-293 ms on gens 1, 2, 4 and 2,272 ms on gen 3 (18:48:29.393 -> 31.665, `restat=refreshed`), the cli hydrate answering 37 ms after the write · read in code, not reproduced: the write's only reader is the NEXT process's boot consult · guess: release the waiters first and land the write-back on one serialized background thread, keeping the pre-build key and the IC-2 restat window as narrow as now (the restat runs right after the build; a thread hop must not let a concurrent turn's WAL write be adopted) · not in done-when · done when: `snapshot_build` lines on the owner's box answer within 50 ms of their `snapshot_build_core` line while `snapshot_core_cache_write ok=true` still follows every led build · LIVE CHECK 2026-11-23: on the owner's serve read a led build's snapshot_build_core line against its snapshot_build answer line (target under 50 ms) and that snapshot_core_cache_write ok=true still follows with its foreign_moved= count · handoff 2026-11-22 (w1122f-agentlist): absorbed as step 6 of RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE (persist the resident core off the response path); not started by w1122f-agentlist · handoff 2026-11-23 (w1122i-residentframe): landed 9646edfc6784 (+7b849dea47e6, cb43ae1d52b9): restat/key on the build thread, the landing on one writer thread. Live: snapshot_build_core -> hub answer 148-184 ms, cli 209 ms, cache_write ok=true AFTER both (before: 879 ms, write first). Not yet the 50 ms of done-when: what is left is the coalescer handing riders a deepcopy (_release_coalescer, then _join_or_lead copies again) of a ~1 MB core; likely fix: one copy, or riders share an immutable core · handoff 2026-11-23 (w1123g-frame2): built 62443ad22007: seen live 13:13 and 13:28 that a led demote still answered 263-266 ms after its build line; read in code: the IC-2 restat walked the WHOLE closure (4,080 inputs) on the build thread to adopt a handful of audited files, and a rider deep-copied a ~1 MB core a second time (18-28 ms each on the owner's core.json); now the build thread re-stats only the audited classes (same key), foreign_moved= is counted by one whole walk at the landing on the writer thread, and the last rider takes the release copy; not yet read live · **TAKEN 2026-11-23 w1123g-frame2 on DESKTOP-QJ7DDV2 as nekwo in w1123g-frame2**
- **`RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE` — Eternia's agent list follows each change in place, and a one-shot read answers at once instead of waiting seconds for a rebuild** · group: runtime-followups · from: `RT-FU-ONE-EVENT-AFTER-BOOT-REBUILDS-THE-WHOLE-AGENT-LIST` (lane w1122f-agentlist; owner 2026-11-22: "we need to make it so what builds the frame doesn't have to be rebuilt / that way everything can be rpcs", design note go 2026-11-22) · seen live 2026-11-22 (owner's `agent.log` and `events.jsonl` types): the serve holds no frame it updates; every batch the patch, turn-overlay and running-work lanes cannot express demotes to a FULL core in the worker (3-10 s), and a one-shot hydrate rides it (9.2 s once); demoting kinds that day: `workspace.updated` change=task_activity, and two watchdog `state.reconciled` (chat_db+running_work, no chat named) after every boot · read in code: Eternia already folds the patch, overlay and section frames the stream sends, so the deltas exist and only the serve throws them away · proposal (weakness escalation): 1) a chat_db file move that changed no session row or message digest is not a chat move (landed with this row); 2) the demote line names its event kinds (`kinds=`, landed with this row); 3) ONE resident core in the serve, with the offset it is applied through, to which every patch / overlay / running_work-section frame is applied by the same rules Eternia folds, behind a switch, pinned by a resident == fresh-build equality test; 4) one-shot and hydrate readers answered from the resident core when it is applied through the log end (else they wait for the pending apply, never a build); 5) per-section rebuild for the remaining demote kinds (`workspace.updated` -> boards/goals; an unnamed chat_db move -> the recent-10 chat slice); full rebuild only for a resync or a cold start; 6) persist the resident core off the response path (absorbs `RT-FU-EVERY-AGENT-LIST-BUILD-WAITS-FOR-ITS-CACHE-COPY-TO-REACH-THE-DISK`) · done when: on the owner's box a demote-kind batch costs no full core (`snapshot_build reason=demote` lines gone or section-only) and a one-shot hydrate after boot answers in under 500 ms, the switch read live before it defaults on · LIVE CHECK 2026-11-23: with snapshot.resident_core on, wait for (or cause) a workspace.updated task_activity or an unnamed chat_db reconcile and read agent.log for snapshot_build reason=demote role=sections and its resident_core sections= line, then flip the switch's default on · handoff 2026-11-22 (w1122f-agentlist): (w1122f-agentlist) steps 1 and 2 landed bc46eec6be32; seen live on 7c0f1704485f: no demote build in the 6 minutes after the 23:02 boot, while on bc46 one demote still came 40 s after boot (kinds=state.reconciled:chat_db+running_work, a boot write that changed a chat row); steps 3 to 6 NOT started (lane context spent; owner go for 3 to 6 stands); step 3 design read in code: seed one resident core in the serve hub from every full-core frame it fans out (hermes_cli/harness_parts/serve/subscriptions.py _broadcast_lanes), apply patch frames by a Python port of Eternia's fold (lib/core/services/hermes/runtime/data/mission_read_model_patch.dart: persona_instance and incident keyed upserts with the created stamp, office_actor nested, office_surface, office_conflict, scope with its re-projected active flags, persona in the agents list), the persona_chat_turn overlay (mission_read_model_turn_fold.dart) and running_work section replace; the resident equals fresh-build test can use core_cache.shadow.compare_cores, which already ignores the volatile envelope keys; a hazard the fold resyncs on in Eternia drops the resident core to the next full build · handoff 2026-11-23 (w1122i-residentframe): steps 3-6 landed: step 3 b9340d896402+46d79dd59cae (resident core folded by Eternia's rules, == fresh build test), step 4 55aca25b0f64 (one-shot hydrate from the resident core), step 6 9646edfc6784+7b849dea47e6+cb43ae1d52b9 (cache write off the response path), step 5 c7033ce0aa6a+c6e56920037a (task_activity and unnamed chat_db demotes re-read only their sections); all behind snapshot.resident_core except step 6. Live on the owner's box 2026-11-23 (hermes c4c6137069ff, switch ON in profiles/base config.yaml): an Eternia restart against the warm serve answered the hub hydrate AND the cli --max-frames 1 one-shot from the resident core, waited_ms=1 role=resident each (before: 10.9-14.6 s riding a boot build, 27 s once), at an offset two chat turns past boot, no drop/resync/demote. NOT yet seen live: a demote-kind batch taking role=sections (none arrived in ~15 min). Owed: that read, then flip snapshot.resident_core default on · handoff 2026-11-23 (w1123g-frame2): beside the live read still owed (a demote answered role=sections, hydrates role=resident, no resync/drop, then flip snapshot.resident_core's code default), the resident core now also takes a saved seed at launch (fa97b9512e71) and folds a steer with its channel threads (865e8c3af01a); the owner's base config.yaml keeps snapshot: resident_core: true (owner 2026-11-23) · **TAKEN 2026-11-23 w1123g-frame2 on DESKTOP-QJ7DDV2 as nekwo in w1123g-frame2**

## Filed on arrival — 2026-11-22 (review w1122d.8: the hermes halves of two Eternia rows)



## Filed on arrival — 2026-11-22 (lane w1122g-promptobs: an agent's prompt details leave the agent list, owner ruling 2026-11-22)


## Filed on arrival — 2026-11-22 (lane w1122h-upstreamchat: chat reads and upstream hermes' session reads, owner approved)

- **`RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT` — A reply in a long chat reaches Eternia in well under a second instead of after re-reading the whole chat** · group: runtime-followups · from: `RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE` (lane w1122i-residentframe live read) · seen live 2026-11-23 (owner's `agent.log`): `turn_section history_ms` for root `persona_chat_personainst_neko_supervisor_agent_346352af_763d89aa30b4` 180 ms at 21:03 (frame 15 KB) -> ~1.5 s at 23:02 (145 KB) -> 3.6-5.2 s on every start/trace/end since midnight; the boot build's `snapshot_persona_chat history_ms` 1,868 ms at 21:39 -> 4,193-5,549 ms since 22:23; trace/channels/pins flat · read in code: not yet · guess: the history read curates every row of the live chat on each read; it should take only rows past the last read plus the kept 40-row tail · done when: on the owner's box `turn_section history_ms` for that chat is under 500 ms and the boot `history_ms` under 1 s · READY 2026-11-23 · handoff 2026-11-23 (w1123g-frame2, readings by w1122i-residentframe on the owner's serve, hermes 66ff90af1a69 + Eternia bd43221c21, 12:49-12:51): snapshot_persona_chat history_ms 4.2-5.5 s -> 1,094 / 784 ms; turn_section history_ms 3.9-4.8 s -> 395 / 242 / 422 / 403 ms; not on the big Neko chat, so the close waits on a turn read on that chat (coordinator's end-of-wave pass); one overlay was still 142 KB: measured on the owner's saved core, a channel's trace (its recent tool trace, 83 entries, 127 KB on neko_mission_lead_beta) rides every frame and overlay though the transcript does not, filed RT-FU-A-REPLY-UPDATE-STILL-CARRIES-THE-AGENTS-WHOLE-RECENT-TOOL-TRACE · **TAKEN 2026-11-23 w1123g-frame2 on DESKTOP-QJ7DDV2 as nekwo in w1123g-frame2**
- **`RT-FU-A-REPLY-UPDATE-STILL-CARRIES-THE-AGENTS-WHOLE-RECENT-TOOL-TRACE` — An agent's reply reaches Eternia as a small update, instead of one that carries the agent's whole recent tool trace every time** · group: runtime-followups · from: `RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT` (lane w1123g-frame2) · seen live 2026-11-23 (w1122i-residentframe's reading on the owner's serve): one persona_chat_turn overlay was 142 KB after the frame stopped carrying transcripts · measured 2026-11-23 on the owner's saved core (serve_read_model core.json, 947 KB): operator_channels is 401 KB over 15 channels, almost all of it each channel's `trace` (neko_mission_lead_beta 127 KB, 83 entries: tool_result, command, summary, tool_input, output), its `history` carries no messages (1-2 KB); the top-level persona_chat_trace section is 375 KB · read in code: `snapshot/receipts.py::_operator_channels_frame` strips conversation.messages but keeps `trace`, and `turn_section_read.py` ships `_operator_channels_frame([channel])[0]` on every turn · guess: the frame and overlay carry the live turn's trace entries only (or a count and the newest entry), and the rest loads with the chat like the transcript (owner ruling 2026-11-23, titles only); Eternia's readers of channel.trace need checking first · done when: a turn overlay on the owner's box is under 20 KB and the frame's operator_channels under 50 KB, with the console's live tool rows still shown · READY 2026-11-23
- **`RT-FU-ETERNIA-SHOWS-THE-SAVED-AGENT-LIST-AT-LAUNCH-EVEN-AFTER-AN-UPDATE` — After hermes updates, Eternia's agent list appears at launch from the saved copy and refreshes in the background, instead of waiting 9-13 s for a full build** · group: runtime-followups · from: `RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE` · seen live 2026-11-22/23 (owner's `agent.log`): every first boot after a hermes update logs `snapshot_core_cache ... reason=build_stamp_mismatch` and a full `snapshot_build_core reason=boot` of 9,202-16,121 ms that Eternia's hydrate waits on (waited 11-15 s) · read in code: not yet · guess: the saved core is refused whenever its build stamp differs; a stamp mismatch could still serve the saved core (marked stale) at once and rebuild behind it, refusing only on a schema change · owner ruling 2026-11-22: what builds the frame should not have to be rebuilt; readers never wait on a build · done when: on the owner's box, the first launch after a hermes update shows the agent list from the saved copy within 1 s of attach and the rebuilt frame replaces it without a resync, read live · LIVE CHECK 2026-11-23: with snapshot.resident_core on, after a hermes update restart the owner's serve and Eternia; read agent.log for snapshot_core_cache core_source=cache stale=true caller=cli and snapshot_build reason=hydrate role=saved within 1 s of attach, then the hub's authoritative hydrate replacing it with no resync · handoff 2026-11-23 (w1123g-frame2): built fa97b9512e71: a --max-frames 1 hydrate in the boot window (cache lane armed and a build in flight) is answered from the saved core labeled stale and seeds the resident slot (never folded, never a wait answer, replaced by the hub's first full core); refused only for a contract, root or home change (STALE_PAINTABLE_REASONS, which now also bounds the hub's stale-first paint); seen before the change 2026-11-23 12:49: the hub got its stale paint but the cli one-shot rode the boot build 17,860 ms; not yet read live (needs a hermes update + restart, the coordinator's end-of-wave pass) · **TAKEN 2026-11-23 w1123g-frame2 on DESKTOP-QJ7DDV2 as nekwo in w1123g-frame2**
- **`RT-FU-THE-AGENT-LIST-FRAME-IS-CONFIRMED-LEGACY-AFTER-A-DAY-OF-NORMAL-USE` — Every change Eternia sees arrives as its own update, and the agent-list frame is only ever built at a cold start or a real resync** · group: runtime-followups · from: `RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE` · owner ruling 2026-11-22: "what builds the frame doesn't have to be rebuilt ... that way everything can be rpcs" · step: after a day of the owner's normal use with the switch on, read every `snapshot_build ... reason=demote` and section-rebuild line in the owner's `agent.log` by its `kinds=`; each kind other than a cold start or a genuine resync becomes its own row that gives that change a patch/overlay of its own (today's known per-section fallbacks: `workspace.updated` task_activity -> boards/goals, an unnamed chat_db move -> the chat slice) · done when: a full day's log shows no demote and no per-section rebuild except cold start or resync, and every kind found is filed or fixed · BLOCKED 2026-11-23: another lane — `RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-CHANGES-IT-COULD-APPLY-IN-PLACE` defaults the resident core on first
- **`RT-FU-THE-ENGINE-LOADS-EVERY-MESSAGING-PLATFORM-PLUGIN-WHETHER-OR-NOT-A-LANE-RUNS-IT` — Starting Eternia loads a messaging plugin such as Home Assistant only when its messaging lane is switched on** · group: runtime-followups · from: `RT-FU-A-PLUGIN-OUTSIDE-THE-PLUGIN-USES-RECORD-ALWAYS-LOADS` (lane w1123a-plugins) · seen 2026-11-23 (reading the code, `agent_runtime/plugin_uses.py::_row_needed`): the serve now holds every plugin its readied agents do not use, except one that registers a messaging platform (`register_platform`), which it keeps because the serve runs the messaging lanes (`agent_runtime/messaging/serve_lane.py` builds the Telegram adapter through `platform_registry`; `hermes_cli/status.py` and the dashboard messaging router read the registry too); a catalog `homeassistant` registers a platform beside its toolset, so the serve still loads it (1.5-2 s, measured in the worker 2026-11-22) while the snapshot worker holds it · not measured: homeassistant in the serve · likely fix: admit platform plugins per platform a lane or the dashboard asks for (`plugin_uses.admit_platform(<name>)` before `platform_registry.create_adapter` or a registry read), the serve holding the rest · done when: a cold boot with homeassistant installed and no Home Assistant lane shows it held in the serve's `plugin_uses op=install` · READY 2026-11-23
- **`RT-FU-AN-IDLE-BOX-READ-OF-THE-READ-MODEL-SLO-CHECK-IS-OWED` — The read model's two-second check is measured on a quiet box before it leaves the idle-box list** · group: runtime-followups · from: `RT-FU-SEVEN-MORE-AGENT-RUNTIME-TEST-FILES-RED-ON-MAIN-ON-WINDOWS` (lane w1123i-hreds) · seen 2026-11-23: `tests/agent_runtime/test_read_model_slo.py` moved to `scripts/test_idle_box_files.txt` in 7a4a40b8f5cc after 2.3-3.3 s against its absolute 2 s budget on a loaded Windows box; w1123i-hreds found the box busy again (about five cores in use by other work) and did not read it · done when: the file is run alone on an idle Windows box and the reading is recorded, and the budget either holds (the file may leave the idle-box list) or the overrun is filed as a performance row · REQUIRES windows · READY 2026-11-23
- **`RT-FU-A-DESKTOP-WITHOUT-CLAUDE-CODE-NAMES-A-CURRENT-CLAUDE-CODE-VERSION` — On a desktop without the Claude Code command, a Claude turn signed in with a Claude subscription names a current Claude Code version, as a phone now does, instead of upstream's stale fallback** · group: runtime-followups · from: `RT-FU-A-CLAUDE-SUBSCRIPTION-TURN-ON-A-PHONE-REPORTS-A-CURRENT-CLAUDE-CODE-VERSION` (closed DONE 6c0f433bbb) · read in code 2026-11-23, not seen live: `agent/anthropic_adapter.py::_detect_claude_code_version` (upstream-owned) answers `claude --version`, else `_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"`; on a phone the stand-in now asks `agent_runtime/claude_code_release.py` (the published release, kept 24 h), but a desktop is not bound to stand-ins (`agent_runtime/spawn_stand_ins.py` runs only under `agent.provider_sdks: false`), so a desktop install with no `claude` on PATH or in the probed prefixes sends 2.1.74, which Anthropic refused on the phone for Claude Opus 5.5 (`HTTP 400: Claude Code 2.1.74 does not support this model; version 2.1.280 or newer is required`) · first read: reproduce on a desktop with the CLI absent (or a test with `_claude_code_candidates` empty) and confirm the 400; then route a desktop's no-CLI answer through the same `current_claude_code_version` (a fork seam at boot, not an upstream edit), keeping an installed CLI's own version first · done when: a desktop without the CLI names the published release on a subscription request, pinned by a test, and a Claude subscription turn answers there · READY 2026-11-23
- **`RT-FU-NEKO-HAS-HAD-NO-LAUNCHER-QA-TOOLS-ON-ANY-TURN-SINCE-2026-11-20` — Neko and the other agents that declare the Eternia QA tools get them on their turns again** · group: runtime-followups · from: `RT-FU-A-TOOL-AVAILABILITY-NOTICE-RE-SENDS-ITSELF-AS-A-NEW-CHAT-TURN-EVERY-FEW-SECONDS` (lane w1123j-noticeloop) · seen live (owner's `agent.log` files, every profile): every `chat_lane_tool_form tool_form_receipt` since 2026-11-20 17:26 reads `admitted=0` (567 turns through 2026-11-23 15:58); the last turns with QA tools read `admitted=46` at 15:46 that day; the 2026-11-23 turns steered `launcher_qa (mcp_not_registered_on_lane)`, an execution-time denial (`mcp_admission/registration.py::Admission.outcome`: the registrar returned and `registered_mcp_server_names()` found no `mcp-launcher_qa` toolset); each serve boot shows the same churn: a prewarm registers 47 tools (`MCP: registered 47 tool(s)`), the next admission logs `re-registers 'launcher_qa': transport session replaced or gone` (a second `starting MCP server 'launcher_qa'` in `mcp-stderr.log`), the server's `tools/list_changed` re-registers the tools outside the scope, the next admission logs `a tool was re-registered outside the scope`, and no registration line follows it; not reproduced and not bisected; suspects: the warm re-registration (`mcp_admission/transport.py::_reregister_warm_server`) publishing into a connection-owner registry scope the outcome read does not see (upstream `_register_server_tools` registers under `_server_registry_scope(key)`), or a resident scope recorded with no tools that then reads as still standing (`resident._invalid_reason`: an empty tool set compares equal and `_metered_by` holds over nothing); the plugin holding of lane w1123a-plugins (bc9f28e4f2be, 3c99b1ad8fee) landed 2026-11-23 and cannot explain an outage that began 2026-11-20 · first read: bisect the owner checkout's 2026-11-20 15:46-17:26 window with one Neko turn per step on a QA copy, reading `tool_form_receipt admitted=` · done when: a Neko turn on a fresh serve lists the launcher_qa tools, and a second turn after the `tools/list_changed` churn still does, pinned by a test with its red recorded · READY 2026-11-23
- **`RT-FU-A-PHONE-AGENT-IS-NOT-OFFERED-A-TERMINAL-IT-CANNOT-RUN` — On a phone, an agent is not offered the terminal tool, instead of spending a turn on a command the phone cannot start** · group: runtime-followups · from: Eternia `MC-PHONE-AGENT-CALL-CONTROLS-SIT-ABOVE-THE-CHAT-NOT-ON-IT` · seen 2026-11-23 on the owner's Android phone (engine at 6c0f433bbb), a Base voice turn on Claude Opus 5.5 asked for the weather: the model called `terminal` with `curl -s "wttr.in/Brooklyn,NY?format=j1"` and got `{"exit_code": -1, "error": "Command execution failed: ModuleNotFoundError: No module named 'tools.terminal_tool_macos_open'"}` (profile `base` state.db), then recovered through `web_extract`; the turn took 41 s with two failed tools · read: a phone cannot start a process (`agent_runtime/spawn_stand_ins.py`), yet the terminal tool is in the phone agent's toolset, and its import reaches a module the phone bundle does not ship · guess, not traced: whether the fix is the phone profile dropping `terminal` from every phone toolset (with the platform hint saying so) or a typed "no terminal on this device" answer before any import · done when: a phone agent's tool list has no terminal it cannot run (or one call answers a typed refusal with no import error), read on a phone or in the phone-bundle closure test · READY 2026-11-23
- **`RT-FU-A-PHONE-AGENT-SEARCHES-THE-WEB-PAGE-IT-JUST-SAVED` — On a phone, an agent can search a web page it just saved to its own cache, instead of being refused as outside a project folder** · group: runtime-followups · from: Eternia `MC-PHONE-AGENT-CALL-CONTROLS-SIT-ABOVE-THE-CHAT-NOT-ON-IT` · seen 2026-11-23 on the owner's Android phone (engine at 6c0f433bbb), same weather turn: `web_extract` saved `profiles/base/cache/web/wttr.in-b6a2b68490.md`; the model's `search_files` over that path answered `{"error": "Path not found: …/profiles/base/cache/web/wttr.in-b6a2b68490.md. this device has no project folder yet", "code": "outside_root"}` · read: on a phone `search_files` is rooted at the device's project folders, so a file the agent's own tool wrote under its profile cache is outside every root and named "not found" · guess, not traced: whether the agent's own cache joins the readable roots, or `web_extract` returns the content without asking the model to search a file it cannot reach · done when: a phone agent reads back what its own web tool saved, read on a phone or pinned by a test · READY 2026-11-23
- **`RT-ACCOUNT-ONLY-YOUR-DEVICES-HOLD-ONLY-THE-CALL-ONCE-ETERNIA-USES-IT` — Once Eternia uses the one call, your phone and computers hold only that call, with no second connection beside it and no one-shot sockets for offers** · group: pairing-through-your-account-only · task in Eternia: `TASK-PAIRING-THROUGH-YOUR-ACCOUNT-ONLY` · from: `RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST` (lane w1122d-hmonecall): what that row's design folds into the call and its lane could not retire while Eternia still drives the old lane · built there (read in code and real-socket tests): the call (`agent_runtime/pair_call/`), `runtime.gateway.call.dial|hangup|calls`, Eternia's `call_attach` lane, and the grant arm on a lane, so a computer's Eternia already drives a phone's engine on a lane of the call the phone opened · left: retire the reverse lane's own socket (`reverse_lane/dialer.py`, the park and splice in `reverse_lane/lanes.py`, the `reverse_lane` / `reverse_attach` hello arms, `runtime.gateway.reverse.dial|hangup|lanes`); send the offer and withdraw (`reverse_lane/offer.py`) and the peer methods (`gateway_peers/dial.py`) on the call when one is up; a peer-secret arm for a lane between two computers (only device and grant credentials prove a lane today) · edge case, documented not worked: lanes on a call closed `duplicate_call` close and their caller attaches again, rather than moving to the kept call · BLOCKED 2026-11-24: launcher — `MC-ACCOUNT-ONLY-YOUR-PHONE-AND-COMPUTERS-EACH-TRY-TO-REACH-THE-OTHER-AND-SHARE-ONE-CONNECTION`: Eternia dials and attaches through the call first; then the old lane goes with no legacy path kept · mandate: owner 2026-11-23 "and in regards to using ones connection i meant the call" · rewritten 2026-11-26 w1122d.35: was "send the offer and withdraw (`reverse_lane/offer.py`, with `RT-ACCOUNT-ONLY-THE-COMPUTERS-ETERNIA-HEARS-AT-ONCE-WHEN-YOUR-PHONE-OFFERS-ITS-AGENTS`'s frame)"; that row was closed by the owner as churn (owner 2026-11-26 "Drop all four", 528cfc8347), so no new offer frame rides the call, only the existing offer and withdraw · premise checked 2026-11-26 w1122d.35 (hermes b21f226548, Eternia a15116205f0): holds; the old reverse lane is still served beside the call (`agent_runtime/reverse_lane/dialer.py`, `lanes.py`, `offer.py`, `agent_runtime/serve_rpc/reverse_lane.py`; nothing in them changed since 8f7285815d) and Eternia still dials and attaches through it (its one-call row `MC-ACCOUNT-ONLY-YOUR-PHONE-AND-COMPUTERS-EACH-TRY-TO-REACH-THE-OTHER-AND-SHARE-ONE-CONNECTION` was woken READY by this review, unbuilt), so the block stands; owner 2026-11-24 (relayed by coordinator-w1122d) kept the reverse socket until Eternia moves · architecture: deletion in fork-owned seams only, no upstream file; ONE owner of a connection between two of your devices = the call registry (`agent_runtime/pair_call/registry.py`); the offer and withdraw and the peer methods become frames on a lane of the call, never a second socket; a peer-secret proof for a lane between two computers reuses the existing peer secret check in `agent_runtime/serve_gateway_auth/` (guess: the first step names the file), no new credential kind; the serve-frame and serve-manifest mirrors Eternia reads are re-synced, never hand-copied · files: `agent_runtime/reverse_lane/dialer.py`, `agent_runtime/reverse_lane/lanes.py`, `agent_runtime/reverse_lane/offer.py`, `agent_runtime/serve_rpc/reverse_lane.py`, `agent_runtime/gateway_peers/dial.py`, `agent_runtime/pair_call/` (lanes for offer, withdraw and peer methods), the `reverse_lane` / `reverse_attach` hello arms (guess: `agent_runtime/serve_socket/handshake.py`), `hermes_cli/harness_parts/serve/reverse_lanes.py`; tests `tests/agent_runtime/test_reverse_lane.py` (retired cases go), `tests/agent_runtime/test_pair_call.py` · tests, each red under its named mutation: a hello naming `reverse_lane` or `reverse_attach` is refused with the one refusal (mutation: keep the arm); an offer and a withdraw reach the far engine on the call with no new socket opened (mutation: send them on the one-shot socket); a peer method between two computers rides a lane of their call (mutation: dial `gateway_peers/dial.py` directly); `runtime.gateway.reverse.dial|hangup|lanes` answer unknown method (mutation: keep the verbs) · mandate: owner 2026-11-23 "and in regards to using ones connection i meant the call", under Eternia `TASK-PAIRING-THROUGH-YOUR-ACCOUNT-ONLY`; it narrows (one socket per pair) and adds no account, level or trust path · churn (strict pass): not churn: two sockets per pair are what the owner asked to end, and the retired lane is a second path every later fix would have to patch · no legacy (owner 2026-11-22 "no old-Hermes support", 2026-11-23 "don't develop for legacy stuff"): no version floor or fallback for an Eternia that still dials the reverse lane · done when: the tests above pass on real sockets; the reverse lane verbs and hello arms are gone; read live by this lane with Eternia at or after the landing of `MC-ACCOUNT-ONLY-YOUR-PHONE-AND-COMPUTERS-EACH-TRY-TO-REACH-THE-OTHER-AND-SHARE-ONE-CONNECTION` on two Linux QA copies served from its own worktree: each lists the other's agents both ways and each serve's connection list shows one call and no reverse lane; the phone half on the emulator once the phone pin in Eternia's `installer/hermes/bundled-hermes.lock.json` moves to this row's commit · size M (guess) · filed by lane w1122d-hmonecall · reviewed 2026-11-26 w1122d.35
- **`RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR` — Before release, phones move to a `cryptography` at or above the 50.0.0 security floor, so a phone carries no library the desktop refuses** · group: runtime-followups · from: `RT-ACCOUNT-ONLY-YOUR-COMPUTER-CAN-OPEN-THE-CALL-TO-YOUR-PHONE-WHILE-ETERNIA-IS-IN-FRONT` (lane w1122d-hmphonelisten, filed on the owner ruling below) · RULED 2026-11-24: owner (relayed by coordinator-w1122d) "for now use 48 but before release we need to update it file it as a deffered release row" · seen (read 2026-11-24, w1122d-hmonecall measure): `pypi.flet.dev` has `cryptography` for cp314 only up to 48.0.0 build 10 (android_24_arm64_v8a, android_24_x86_64, ios_13_0_arm64_iphoneos); PyPI has no Android or iOS wheel of 50.x; the desktop pins 50.0.2 with a 50.0.0 floor (`pyproject.toml`) for CVE-2026-69247 (Bleichenbacher oracle in PKCS#7 EnvelopedData, fixed 50.0.0), GHSA-m2h6-j472-rp4c (a wildcard DNS name escapes permittedSubtrees, fixed 49.0.0) and GHSA-jwv3-5hgf-82ww (exponential path-building on duplicate self-signed intermediates, fixed 49.0.0) · the exception meanwhile: phones only ship 48.0.0, pinned in `agent_runtime/bundle_profiles/phone_wheels.lock.json` and admitted by ONE named phone-only exception in `scripts/bundles/phone_wheels.py::version_problems` (`PHONE_ONLY_VERSION_EXCEPTIONS`), used for the phone listener certificate only (`agent_runtime/gateway_tls.py`); the phone mints and verifies its own self-signed certificate and does no PKCS#7 or chain building, so none of the three is reached on the listener path (read, not proven by a test) · ways out: build cryptography 50.x ourselves (Android here with the NDK and `cargo-ndk`, iOS on the Mac: this box compiles iOS targets but cannot link them), commit the wheels and pin them by repo path as `eternia-project-files-match` is; or request 50.x in Flet's GitHub discussions (Packages) and pin their build · done when: every phone target's `cryptography` wheel in `phone_wheels.lock.json` is at or above 50.0.0 and the 48.0.0 entry of `PHONE_ONLY_VERSION_EXCEPTIONS` is removed, so `version_problems` holds phones to `uv.lock` again · waits: v0.1 · DEFERRED 2026-11-24: owner ruling — a release row; 48.0.0 ships on phones until then · see 2026-11-24 (review w1122d.33): owner 2026-11-24 "Every phone ships engine"; Eternia `MC-ACCOUNT-ONLY-EVERY-ANDROID-BUILD-CARRIES-THE-AGENT-ENGINE` puts this closure in every Android build, so 48.0.0 rides every Android build until this row lands, and the iPhone build after it
- **`RT-FU-THE-PHONE-ENGINE-DOWNLOAD-STAYS-UNDER-ITS-LIMIT-WITH-THE-LISTENERS-CRYPTOGRAPHY` — The phone engine download stays within its size limit now that the phone listener ships cryptography** · group: runtime-followups · from: `RT-ACCOUNT-ONLY-YOUR-COMPUTER-CAN-OPEN-THE-CALL-TO-YOUR-PHONE-WHILE-ETERNIA-IS-IN-FRONT` (lane w1122d-hmphonelisten) · seen 2026-11-24 (measured, nekwo-ubuntu24, `scripts/bundle_profile_package.py --profile bundled-phone --target android_arm64`, verify 0, deflate -9 per file as in `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT`): origin/main ec42e5f920 16.30 MiB (57.77 raw), with the listener f86966221f 19.39 MiB (66.65 raw): +3.09 MiB, of it `cryptography/hazmat/bindings/_rust.abi3.so` 7.84 MB raw (~2.9 MiB compressed), cffi and `_cffi_backend` 0.18 MiB, pycparser 0.05 MiB; the bundle alone is now over Eternia's 18 MiB limit (RELEASE_GATES.md, Eternia's to hold) · guess: the certificate needs only EC key generation, X.509 build and PEM; a cryptography built here for `RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR` could be trimmed, or the mint could use a smaller library (a design call, the DECISION row's option (c)) · architecture: the closure stays the one owner of what ships (`bundled-phone.yaml`); no hand exclude list · done when: the android_arm64 bundle is measured under the share of the 18 MiB limit Eternia assigns it, or the gap named per part · corrected 2026-11-24 (review w1122d.33, read in Eternia's code at 763e98c7637): Eternia's held limit is no longer 18 MiB for the bundle; it is one shrink-only 28 MiB ceiling on the WHOLE Android engine download per ABI (`tool/mobile_core/release_budgets.json` `android_aab_delta_mib_max`, Eternia `docs/security/hermes_mobile/RELEASE_GATES.md`), re-based 2026-11-19 on this repo's `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` ruling from a measured 24.90 MiB (interpreter libraries 4.34 MiB + an engine library of stdlib and bundle at 30142caea7); with the listener's +3.09 MiB the whole is about 28 MiB (guess, from the two measures, not an APK pair), so this row's done-when reads: the whole Android engine delta stays under 28 MiB, never by raising it; Eternia `MC-ACCOUNT-ONLY-EVERY-ANDROID-BUILD-CARRIES-THE-AGENT-ENGINE` (owner 2026-11-24 "Every phone ships engine") measures the APK pair at its phone pin and records it here · RULED 2026-11-24: owner said "accept the size check failing but make sure its a row to bring it under if possible" (relayed by coordinator-w1122d; it means: Eternia's 28 MiB Android engine gate may stay red meanwhile, it is never raised, and this row is the work that brings the download under it where that can be done) · seen in a build 2026-11-24 by Eternia lane w1122d-androidengine (Eternia `MC-ACCOUNT-ONLY-EVERY-ANDROID-BUILD-CARRIES-THE-AGENT-ENGINE`, recorded in Eternia `docs/security/hermes_mobile/RELEASE_GATES.md`): the arm64 profile APK pair at the phone pin 126a5f8931 (Eternia 3e6e0f5019 without the engine, 210f73aa9e with it) is 37.45 MiB apart raw and **29.39 MiB gzip -9, 1.39 MiB OVER the shrink-only 28 MiB ceiling** (`tool/mobile_core/release_budgets.json` `android_aab_delta_mib_max`), ceiling not raised · premise checked 2026-11-26 w1122d.35: holds; Eternia's phone pin has since moved to 8a00dc4bf2 (Eternia a24d76ed94b, 2026-11-24, the other box: 15 hermes commits past 126a5f8931, history pointer and journal recovery, no new dependency read in its closure; guess: the size is within a few hundred KiB of the measure, not re-measured); nothing has cut the closure since (`agent_runtime/bundle_profiles/bundled-phone.yaml` and `scripts/bundles/phone_wheels.py` untouched since 0dbebe73c4); the one gate stays red by the owner's word above · done when: the arm64 profile APK pair at Eternia's phone pin, measured by the RELEASE_GATES method (`dart tool/heavy_run/apk_build.dart --mode=profile`, gzip -9 of the difference), is under 28 MiB and recorded in Eternia `docs/security/hermes_mobile/RELEASE_GATES.md`; or, where no cut can reach it, the gap is named per part of the closure and put to the owner as a DECISION, never a raised ceiling · architecture: the closure (`agent_runtime/bundle_profiles/bundled-phone.yaml`) stays the one owner of what ships; a cut is a closure change or a smaller build of one wheel in `scripts/bundles/phone_wheels.py`, never a hand exclude list in Eternia; the 28 MiB figure stays owned by Eternia `tool/mobile_core/release_budgets.json` · mandate: owner 2026-11-24 above and "for now use 48" (the phone-only cryptography 48.0.0 exception, `RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR`), under `TASK-RUNTIME-FOLLOWUPS`; widens nothing · churn (strict pass): not churn: a download over its ceiling is a release gate the owner asked to bring under · reviewed 2026-11-26 w1122d.35 · measured 2026-11-26 (w1122d-hmsize, nekwo-ubuntu24): `scripts/bundle_profile_package.py --profile bundled-phone --target android_arm64 --python-version 3.14 --no-serve-probe` at the phone pin 8a00dc4bf2 (verify 0), plus the pinned interpreter python-3.14.9-aarch64-linux-android (sha256 e2601ffe… as Eternia's `python-runtime.lock.json`) with Eternia's stdlib leave-outs (`kStdlibLeftOut`), deflate -9 per file: 28.78 MiB (96.44 raw); by part (compressed / raw MiB): `cryptography` 2.84/7.93 (its `_rust.abi3.so` alone 2.74/7.48, which links its OWN OpenSSL 3.0.20 statically, read in the binary), app/hermes_cli 2.50/9.57, app/agent_runtime 1.82/6.66, libpython3.14.so 1.74/5.57, libcrypto_python.so (the interpreter's OpenSSL 3.5.9) 1.60/4.33, app/locales 1.53/5.21, app/agent 1.37/5.18, app/gateway 1.27/4.87, stdlib modules 1.17/4.60, flet image libs (site-packages/opt) 1.16/2.61, eternia-project-files-match 0.83/1.91, dulwich 0.68/2.92, app/tools 0.63/2.22, libsqlite3_python.so 0.61/1.16, PIL 0.60/1.74, phone_forced/tools 0.49/1.79, app/tui_gateway 0.41/1.60, libssl_python.so 0.39/0.92, stdlib `_zstd` 0.37/1.90, unicodedata 0.31/0.71, wcwidth 0.27/1.57 (agent/markdown_tables.py), cffi + `_cffi_backend` + pycparser 0.22/0.85; groups: app 10.59, site-packages 8.27, phone_forced 0.52, stdlib 5.07, interpreter libraries 4.33; every shipped .so already stripped (read). The per-file sum runs about 0.6 MiB under the APK-pair method (guess: zip and APK overhead; 29.39 measured at 126a5f8931), so the cut needed is at least 1.4 MiB per file, about 2 MiB to keep a margin · plan 2026-11-26 (w1122d-hmsize), cuts with no phone feature lost, in order: (A) build cryptography 48.0.0 for android_arm64 and android_x86_64 here (NDK 28.2 + cargo-ndk, as `scripts/native/build_project_files_match.py` builds its wheel), linked against the interpreter's own `libcrypto_python.so` / `libssl_python.so` instead of a second, static OpenSSL; commit the wheels and pin them by repo path in `agent_runtime/bundle_profiles/phone_wheels.lock.json` (`scripts/bundles/phone_wheels.py` already reads path pins), same version so the owner's 48.0.0 ruling holds: expected -1.0 to -1.6 MiB (guess: bounded by the whole interpreter libcrypto at 1.60; the static copy is most of the 2.74 MiB module), and it is the same build route `RT-FU-BEFORE-RELEASE-PHONES-SHIP-A-CRYPTOGRAPHY-AT-OR-ABOVE-THE-SECURITY-FLOOR` needs later for 50.x; (B) stop shipping cffi, `_cffi_backend` and pycparser: cryptography 48 imports none of them at run time (read: no import in the shipped package; it only names cffi in Requires-Dist), so a closure change in `bundled-phone.yaml` (`omitted_distributions` entry for cffi with its degrades line, and drop cffi from `admitted_native`): -0.22 MiB; (C, Eternia-side, an Eternia row) Eternia's payload also leaves out CPython's test-only extension modules in lib-dynload (`_testcapi`, `_testlimitedcapi`, `_testinternalcapi`, `_ctypes_test`, `_testbuffer`, `_testmultiphase`, `_testsinglephase`, `_testclinic*`, `_testimportmultiple`, `_xxtestfuzz`, `xx*`, `_remote_debugging`; nothing imports them): -0.31, `pydoc_data` (interactive help() topics) -0.17 and `_pyrepl` (the interactive REPL) -0.07, a `kStdlibLeftOut` change in Eternia's own row; (D, needs an import audit first, guess) `_zstd` -0.37 if nothing on the phone opens a zstd archive. Expected per-file total: 28.78 - (A 1.0..1.6) - 0.22 = 26.96..27.56 MiB with A+B (about 27.6..28.2 by the APK method, guess: at the line), 26.4..27.0 with C as well (about 27.0..27.6 by the APK method, guess); so A+B+C get under, and D is the margin. Checks per step: package and verify at Eternia's phone pin of the day, measure per file as above, then the done-when's APK pair. If A builds but saves under 1.0 MiB and A+B+C+D still leave the APK pair over 28 MiB, the row goes DECISION with the gap named per part (options then: the mint through the interpreter's OpenSSL by ctypes with no cryptography at all, about -2.9 MiB but a second mint path beside the desktop's; or cutting the locales per phone language, -1.5 MiB at most, a feature loss) · READY 2026-11-26: build cryptography 48.0.0 for both Android ABIs against the interpreter's OpenSSL and pin it by path (A), omit cffi/pycparser from the phone closure (B), with Eternia's stdlib leave-outs (C) beside it, re-measure per file and by the APK pair at Eternia's phone pin · handoff 2026-11-26 (w1122d-hmsize): plan lane only, nothing built; measured at 8a00dc4bf2 as above (APK-pair method not re-run: it needs an APK build); claim released; step C is Eternia's and needs its own Eternia row (not filed from this hermes lane; relayed to the coordinator) · step C filed 2026-11-26 by Eternia review w1122d.36 as Eternia `MC-FU-THE-PHONE-ENGINE-DOWNLOAD-LEAVES-OUT-PYTHONS-TEST-MODULES-AND-HELP-PAGES` (READY S, under `TASK-MISSION-CONTROL-FOLLOWUPS-7`); read there: the leave-out is `packages/agents/eternia_hermes_embedded/lib/src/engine_payload.dart`, and `_pyrepl` (~0.07 MiB) is imported at top level by the stdlib's `pdb` and `pydoc`, so it goes only if an import audit of the payload finds neither; count C as about -0.48 MiB, -0.41 without `_pyrepl`
- **`RT-FU-ONE-PROFILE-CLOSING-CAN-FAIL-ANOTHER-PROFILES-WAITING-SEND` — Closing one profile can fail a send waiting in another profile, and two chats starting together can open two connections to the same store** · group: runtime-followups · from: `RT-FU-NEKO-RESUME-REPORTS-A-BUSY-ROTATED-TIP-AFTER-AN-IDLE-REPLY` · seen in a test: on fork main bac2926297, put one real `_Turn` per home in `_pending`, call `_on_lost(A)`, and both A and B are removed and marked failed. In the same isolated process, two threads calling `_gateway_peer(A)` with a barrier at worker startup returned different live peers. These probes used no app traffic. · read in code, not reproduced: `_SessionActor.close` routes its detach through the peer currently registered for the store. An attachment made by the other starting peer can therefore outlive its actor. · done when: simultaneous first sends use a single existing gateway peer per store, a lost or superseded peer retires only its own waiting turns and attachments, and overlapping two-store tests show the other profile completes once with its session intact. · handoff 2026-11-25: the reproductions exercise fork `agent_runtime/operator_gateway_turn.py` at `_gateway_peer` and `_on_lost`. Keep release on the existing native transport ownership path. · READY 2026-11-25

## Filed on arrival — 2026-11-25 (Neko Mission Lead Beta, operator chat: a refused send after the owner's hard refresh)


