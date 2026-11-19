---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue





## Shipped agents stay one agent — 2026-11-19 (owner; task row in Eternia `mission-control-queue`)

- **`RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD` — Base Agent and Neko Mission Lead come from the Eternia build, so every install gets each update** · group: bundled-agents-stay-one-agent · design: Eternia `Launcher_Brain/20 — Active Initiatives/bundled-agents-stay-one-agent-design.md` · owner 2026-11-19: only Base Agent and Neko Mission Lead ship; shipped agents always update, nobody pins a version; a local change to one is reset by the next update · read in code 2026-11-19: Neko is copied into the store once on an empty roster and never updated (`agent_runtime/fresh_install_seed.py:83-107`) · done when: a fresh root's Neko and Base are references with origin `eternia`; a changed shipped SOUL reaches the next turn on an existing install with no store write; the directory and instance detail carry `origin`, `based_on`, `agent_name`, and a `locally_changed` flag for a shipped agent edited in place · reviewed 2026-11-19 bundled-agents.1 (owner design sitting) · READY 2026-11-19
- **`RT-BUNDLED-AGENT-DUPLICATE-IN-ONE-STEP` — Duplicating a shipped agent under a new name takes one step and keeps its memory** · group: bundled-agents-stay-one-agent · design: Eternia `Launcher_Brain/20 — Active Initiatives/bundled-agents-stay-one-agent-design.md` · owner 2026-11-19: changing Neko or Base is allowed but warned (reset on update); the duplicate is made easy and strongly encouraged, never forced; a copy is a full duplicate, memory included; a per-instance model choice changes the instance, not the persona · done when: one verb copies a persona's definition and memory under a name no other agent has (`agent_name_taken` otherwise, never a suffix), records `based_on`, and can re-point a given instance at the copy with its chats; a definition write to a shipped agent succeeds and sets `locally_changed` · reviewed 2026-11-19 bundled-agents.1 (owner design sitting) · waits: `RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD` · BLOCKED 2026-11-19: another lane — `RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD`
- **`RT-BUNDLED-AGENTS-EXISTING-RECORDS-SORTED` — The owner's changed Neko becomes "Neko Mission Lead Beta", with the shipped Neko beside it** · group: bundled-agents-stay-one-agent · design: Eternia `Launcher_Brain/20 — Active Initiatives/bundled-agents-stay-one-agent-design.md` · owner 2026-11-19: rename the owner's own Neko to "Neko Mission Lead Beta" and also place the shipped Neko in the owner's namespace to compare · done when: an unchanged seeded Neko or Base becomes a reference with every chat still opening; a changed one becomes a `based_on` copy under a new name with its instances and chats; a dry run prints the plan and writes nothing · reviewed 2026-11-19 bundled-agents.1 (owner design sitting) · waits: `RT-BUNDLED-AGENT-DUPLICATE-IN-ONE-STEP` · BLOCKED 2026-11-19: another lane — `RT-BUNDLED-AGENT-DUPLICATE-IN-ONE-STEP`
- **`RT-REALM-SHARES-A-SHIPPED-AGENT-BY-REFERENCE` — A realm that uses a shipped agent sends members a pointer, never its own copy** · group: bundled-agents-stay-one-agent · design: Eternia `Launcher_Brain/20 — Active Initiatives/bundled-agents-stay-one-agent-design.md` · done when: publishing a realm with a shipped agent placed carries no SOUL, prompt or memory file for it; a pull leaves the member's shipped agent unchanged; a `based_on` copy still travels whole · reviewed 2026-11-19 bundled-agents.1 (owner design sitting) · waits: `RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD` · BLOCKED 2026-11-19: another lane — `RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD`
- **`RT-NAMESPACE-SEED-SKIPS-SHIPPED-AGENTS` — A new namespace made from another one does not get a second copy of a shipped agent** · group: bundled-agents-stay-one-agent · design: Eternia `Launcher_Brain/20 — Active Initiatives/bundled-agents-stay-one-agent-design.md` · done when: `hermes namespace seed --dry-run` lists shipped agents as resolved from the build and copies none, and instances placed in the copied office still resolve · reviewed 2026-11-19 bundled-agents.1 (owner design sitting) · waits: `RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD` · BLOCKED 2026-11-19: another lane — `RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD`

## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)


- **`TASK-AGENT-CONFIG-CLEANUP` — Agent settings: each agent's folders, data, options and abilities live in one clear place** · task: agent-config-cleanup · 3 subtasks on 2026-11-15 (1 ready, 2 deferred) · DEFERRED 2026-11-16: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` closed as churn (owner 2026-11-16 — "Close as churn"); the one subtask left, Eternia `MC-OWNER-NAMESPACES-ADOPT`, is DEFERRED by the owner (2026-11-09), and the queue grammar keeps a task while a subtask lives, so this is parked, not closed · unblocked 2026-11-15: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` woken READY by w1115e-rr2 (deep sweep 2026-11-15 §D); the other subtasks stay deferred (was DEFERRED 2026-11-09: owner — every live subtask is deferred (owner sittings parked 2026-11-09); until the owner reopens it) · waits: `MC-OWNER-NAMESPACES-ADOPT`
- **`TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` — Agent engine follow-ups: the engine's own checks pass on main again after a lane broke them** · task: engine-suite-green-followups · 3 open subtasks on 2026-11-15 (1 ready: FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY; 2 NEEDS PLAN filed by w1115c-h2 and waiting on a review batch: RT-RUNNING-TURN-START-ROW-WAITS-OUT-THE-DEMOTE-HOLD, RT-RUNNING-TURN-START-NEVER-PUBLISHED-ONCE-UNDER-LOAD; FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD closed DONE 36a1e1d45c and FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD closed DONE c157f48749 by w1115c-h2; FH-GAME-WATCH-TEST-READS-THE-MACHINES-REAL-PROCESSES and FH-BUNDLE-SERVE-PROBE-REPORT-LOST-TO-STDERR-ON-LINUX closed by other w1115c lanes; FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN closed DONE e64d77c9f6 by w1114a-h5 through fork seams) · filed 2026-11-14 by the w1114a.30 queue pass (REVIEW_W1114A_B29), for reds met on hermes main — the twin of Eternia's architecture-gate-green-followups · was DONE 2026-11-15 0495762a2e (all 1 subtasks closed) · reopened 2026-11-15 (review batches w1114a.40 and w1114a.42, REVIEW_W1114A_B39/B41): FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD moved in from the DEFERRED TASK-UPSTREAM-LOAD-FLAKES and FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN from the DEFERRED TASK-HERMES-TEST-ISOLATION · handoff 2026-11-15 (w1114a-h4): FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN reproduced and its fixture fixes written, but they edit three upstream test files (upstream footprint 224->226), so it waits on an owner ruling (DECISION); claim released · BLOCKED 2026-11-15: another lane — `FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-RUNTIME-FOLLOWUPS` — Agent runtime: what the tasks behind this queue's rows found on the way gets fixed after them** · task: runtime-followups · after w1118a-hrealm5 2026-11-19: closed DONE dee4e42839 `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (both read live), and design-fix `TASK-REALM-DELETE-MEETS-AN-EDIT` closed with both its subtasks; filed `RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` and `RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` (an edge), both waiting for a review batch; net two subtasks fewer and two more than the counts that follow · review w1118a.36 passed with corrections hbundle's `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` (READY: one owner of the push-refused tells, `cannot lock ref` added; a repeat of archived `RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE`) and `RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES` (READY: publish writes only what the content compare says changed), and moved `RT-PHONE-REALM-CONFLICT-HAS-NO-WAY-OUT` and `RT-REALM-LOCAL-EDIT-OUTLIVES-A-TEAMMATES-DELETE` out to design-fix task `TASK-REALM-DELETE-MEETS-AN-EDIT` (one gap: no rule for a delete meeting an edit); net two subtasks more and two fewer than the counts that follow · review w1118a.31 corrected the hsurf segment below: the Eternia Home row it woke is closed, not open (DONE a8c7bead20), and so is `TASK-HOME-SHELL-FOLLOWUPS-3` (099dc3c1bd) · review w1118a.30 closed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` as an edge case (D6) and filed and closed `RT-SURFACE-NOTE-RESENT-EVERY-TURN-IN-MOA-AND-CODEX-MODES` as an edge case (D7), both on Eternia's sweep list (one root: what the model was last told is read from the transcript); net one subtask fewer than the counts that follow · after w1118a-hsurf 2026-11-19: closed DONE `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` 7787bd8a8f (a changed surface prompt rides the turn's tail; the stored prompt stays byte-identical), which wakes Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` for its live read (since closed DONE in Eternia a8c7bead20, w1118a-home4; Eternia `TASK-HOME-SHELL-FOLLOWUPS-3` closed DONE 099dc3c1bd); filed `RT-SURFACE-PROMPT-CLEARED-MID-CHAT-IS-NOT-ANNOUNCED` (an edge, waits for a review batch) · was: review w1118a.29 filed and passed `RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN` from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE` (ready; one subtask more than the counts that follow) · after w1118a-folderedit 2026-11-19: closed DONE `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED` fff568201e, read live in Eternia before and after on fresh lane namespaces (the folder is saved, no sync banner) · was: review w1118a.23 moved w1118a-hrealm's two realm rows (the persona-api-mode one, since closed DONE 68a504deb7, and `RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK`) out to `TASK-REALM-MEMBERS-SEE-WHAT-THE-OWNER-SHARES`; the counts that follow never held them · 5 subtasks open on 2026-11-19 after w1118a-hprov (closed DONE: the catalog's sign-in field 2e5f209c5d, which woke Eternia `MC-FU-COMPOSER-SILENT-WHEN-THE-CHATS-PROVIDER-IS-SIGNED-OUT` (since closed DONE in Eternia 9f1bb6eccd, w1118a-mcfu8); the phone readiness row cc78fac067, read first on a phone bundle; closed as churn on review w1118a.21 D6: the fresh Default office row, read on a desktop serve — the one effect found filed as `RT-FOLDER-EDIT-ON-A-NEW-ACCOUNTS-EMPTY-OFFICE-IS-REFUSED`, passed by review w1118a.22, since closed DONE; the other four wait on the owner) · was: review w1118a.21 filed and passed the sign-in-field and phone-readiness rows and rewrote the fresh-office row (w1118a-hphone2) · 6 subtasks open on 2026-11-19 after w1118a-hphone2 (filed `RT-FRESH-ENGINE-DEFAULT-WORKSPACE-HAS-NO-OFFICE`, waits for a review batch; the phone row the duplicate below merged onto, `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER`, closed DONE 82d80229be in `TASK-PHONE-HARNESS`) · was 5 subtasks open on 2026-11-19 after w1118a-rtfu2 (closed DONE: `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` efc2140d79, `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` 69aab89b99, `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` 4d43a3036c read live on a real model; filed `RT-PHONE-CHAT-TURN-HAS-NO-HARNESS-PARSER`, which review w1118a.19 closed as a duplicate of `RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER` (merged onto that row); the other four wait on the owner: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` blocked, three deferred) · was 8 subtasks open on 2026-11-19 after w1118a-realm2 (`RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` closed DONE afb168e807, read live on two Eternia QA copies; `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` also read right in Eternia's realm sheet: two new namespaces' first pulls read In sync with nothing to publish) · was review w1118a.16 (Eternia review batch): passed `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER` (both ready), closed `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` (a red on main is not a row — owner 2026-11-15) · 9 subtasks open on 2026-11-19 after w1118a-rtfu (closed DONE: `RT-READ-ONLY-TREE-REMOVAL-COPIED-THREE-TIMES` 2967e07ab1, `RT-PHONE-BUILD-STALE-SEED-BLAMES-AN-EXTRA` d197d1c389, `RT-FIRST-PULL-INSTALLS-SKILLS-THAT-READ-AS-YOURS-TO-PUSH` 34e21dbfe8; filed `RT-TWO-COMPUTER-REALM-TESTS-SHARE-ONE-SKILLS-FOLDER`, waits for a review batch; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` waits on a real-model sitting and `RT-REALM-PULL-REFUSES-FIRST-CHARACTER-AGENT` on an Eternia QA read, each with a handoff; `RT-PHONE-E2E-TURN-RUNS-WITH-THE-HOSTS-PSUTIL` and `RT-REALM-REKEY-CENSUS-TEST-RED-ON-MAIN` filed by w1118a-hphone wait for review) · was 9 subtasks open on 2026-11-19 after w1118a-hbundle3 (`RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` closed DONE d5012e054b: 18.86 -> 15.66 MiB arm64, the limit re-based by ruling, Eternia's edit) · was 11 subtasks open on 2026-11-19 after w1118a-hbundle (`RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED` closed DONE 75c5913569; `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` stays READY with a handoff — 28.80 -> 23.30 MiB landed 5febe61183, gap per part on the row; `RT-DESKTOP-BUNDLE-VERIFY-REFUSES-THE-DULWICH-REALM-SYNC` closed DONE 9962731e85 (w1118a-hbundle)) · was 11 subtasks open on 2026-11-19 after review w1118a.10 (6 ready, 1 live check, 1 blocked, 3 deferred; the review passed `RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT` and filed `RT-BUNDLED-LINUX-INTERPRETER-STRIPPED-AND-PRUNED`, from Eternia `TASK-DISTRIBUTION-FOLLOWUPS`) · was 9 subtasks open on 2026-11-19 after review w1118a.8 (4 ready, 1 live check, 1 blocked, 3 deferred; `RT-PHONE-ANDROID-TLS-IGNORES-DEVICE-CERTIFICATES` closed as a documented edge case on the owner's standing call) · was, on 2026-11-17 after w1116b-rtfu: `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, `RT-CLOSE-NAMES-SIBLING-TASK-LINES-THAT-STILL-MENTION-THE-ROW` and `RT-REALM-OWNER-RECORD-LISTS-A-WORKSPACE-IT-DELETED` closed DONE; `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` stays READY for its real-model live re-run only; `RT-SKILL-NAME-READ-TWO-WAYS` filed, waits for a review batch; was 5 subtasks open on 2026-11-16 after w1115e-q4 (2 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`; 1 blocked on an owner sitting; 2 deferred; closed since: `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM` DONE, `RT-LENS-RECIPE-HISTORY-AND-COUNTS-NOT-BUILT` as a documented edge, owner 2026-11-16 "sounds good" on review w1115e.19); was 7 subtasks open on 2026-11-16 after owner "Accept all" on B68 (4 ready: `RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER`, `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`, and the two narrow realm-sync fixes `RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS` and `RT-LENS-RECIPE-DRIFT-ARM`; 1 blocked on an owner sitting: `RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH`; 2 deferred: `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR`, `RT-SCHEDULE-SYNC-AND-KNOB-2`; closed: `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS` and `RT-WORK-READS-MIX-ROWS-AND-HISTORY-FROM-TWO-COMMITS` as edges, `RT-READY-FRAME-SHELL-KEY-DOCUMENTED-NEVER-SENT` folded; each keeps its own status; its `from:` segment names the task it came from); was "7 subtasks open on 2026-11-15" · opened 2026-11-15 by w1115e-rr3 as this queue's one standing follow-ups task (owner 2026-11-15: "yea do the cleanup"; a follow-up goes here, not under a per-task `-FOLLOWUPS` task): received `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF-FOLLOWUPS` (2), `TASK-SHARED-WORK-V1-FOLLOWUPS` (1), `TASK-ONE-TURN-RECORD-FOLLOWUPS` (1), and the hermes rows of Eternia `TASK-PHONE-HARNESS-FOLLOWUPS` (1) and `TASK-CONSOLE-TOP-BAR-AND-MENU-PROPOSAL-FOLLOWUPS-2` (1) and backend `TASK-WORKSPACE-ABSORBS-PROJECTS-FOLLOWUPS-2` (1); `TASK-ETERNIA-LENS-FOLLOWUPS-2`'s 5 rows are Eternia's, now under Eternia `TASK-MISSION-CONTROL-FOLLOWUPS`; `TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` stays (its one row is a security row), each closed as merged · READY 2026-11-19 · unblocked 2026-11-19: `RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE` closed DONE dee4e42839
- **`TASK-ONE-MESSAGING-TRANSPORT` — Agents reach Telegram and Discord through one transport with one sender gate** · task: one-messaging-transport · 1 subtask open on 2026-11-16 (deferred behind the Telegram trial; the sender gate closed DONE) · filed 2026-11-15 by lane w1115e-dfile from review batch B59 H3 (deep sweep H-B6) · architecture: fork-side only — `agent_runtime/messaging/` holds the fork's own httpx transport (`telegram_api.py`, `transport.py`) and the shim `upstream_adapter_transport.py`, with `refused.py` and `bindings.py` re-derived per transport; the upstream adapters become the only transport with ONE fork sender gate (allow and refused lists) on the shim; upstream adapters are not edited · retires 4 DEFERRED after the owner's opt-in trial (not folded now): `FORK-PARALLEL-MESSAGING-GATEWAY`, `RT-MESSAGING-PLATFORMS-TELEGRAM`, `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR`, `RT-MESSAGING-DISCORD-GATE-LISTS-EVERY-GUILD-SENDER-AS-REFUSED` · risk: it talks to real chat platforms — live reads use the owner's staging bots only · RULED 2026-11-15: owner — "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure" · reviewed 2026-11-15 w1115e.9 · DEFERRED 2026-11-16: the sender gate is done (`RT-MESSAGING-ONE-SENDER-GATE`, 990a6c15b9, w1115e-fh2); the one subtask left, `RT-MESSAGING-RETIRE-FORK-TELEGRAM`, waits on the owner's Telegram trial (owner 2026-11-15 — "unclaim that telegram row for now"), and the queue grammar keeps a task while a subtask lives, so this is parked, not closed, until that trial · waits: `RT-MESSAGING-RETIRE-FORK-TELEGRAM`
- **`TASK-REALM-MEMBERS-SEE-WHAT-THE-OWNER-SHARES` — Realm members get what the owner shares, and are never told they changed what they did not touch** · task: realm-members-see-what-is-shared · review w1118a.36 (D4) weighed hbundle's four realm rows against this task and kept them out: none makes this task's spec false (each needs two members changing one realm at once); they went to `TASK-RUNTIME-FOLLOWUPS` and the new `TASK-REALM-DELETE-MEETS-AN-EDIT` · on 2026-11-19 after w1118a-hrealm2 (hermes 68a504deb7): `RT-REALM-PULLED-PERSONA-WITHOUT-API-MODE-READS-CHANGED` closed DONE 68a504deb7 (real, not an edge case: Eternia leaves api_mode empty; a config-declared persona's projection no longer carries this machine's defaults); `RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK` built and landed, now LIVE CHECK waiting on an Eternia live read (recipe on the row), claim released · review w1118a.23 moved in and passed with corrections `RT-REALM-PULLED-PERSONA-WITHOUT-API-MODE-READS-CHANGED` and `RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK` (filed by w1118a-hrealm under the follow-ups task; both break what this task specified and are instances of its archive-list flaw; the board fix reuses the office's who-archived owner, lifted to one helper; both ready) · review w1118a.21 passed `RT-REALM-MEMBER-DESK-ARCHIVED-BY-A-PULL-BLOCKS-THE-AGENT-COMING-BACK` with corrections (filed by w1118a-realm3, ready; the second flaw's fifth instance, same files as `RT-REALM-PULL-SHOWS-AN-UNTOUCHED-AGENT-AS-CHANGED`) · on 2026-11-19 after w1118a-realm3: Eternia `MC-REALM-MEMBER-SETUP-SAYS-FAILED-WHEN-IT-SET-UP` closed DONE (Eternia 0202ef390d, a lost set-up reply asks this repo's status verb first; read live on two new namespaces); Eternia `MC-REALM-MEMBER-OFFICE-STAYS-EMPTY-AFTER-FIRST-PULL` stays READY in Eternia, not reproduced (the snapshot was never read lacking the agents, so it did not move here); the same read filed hermes `RT-REALM-MEMBER-DESK-ARCHIVED-BY-A-PULL-BLOCKS-THE-AGENT-COMING-BACK` (READY, waiting for a review batch) · was on 2026-11-19 after w1118a-realm2: Eternia `MC-REALM-IDLE-PULL-SAYS-ARTIFACTS-UPDATED` and `MC-REALM-CARD-SHOWS-AN-EMPTY-AGENT-CHANGES-HEADING` closed DONE b31c13e630 (read live on two staging copies); the same read filed Eternia `MC-REALM-MEMBER-OFFICE-STAYS-EMPTY-AFTER-FIRST-PULL` and `MC-REALM-MEMBER-SETUP-SAYS-FAILED-WHEN-IT-SET-UP` (review w1118a.18 passed both with corrections, ready; the office row's first step decides whether it moves to this queue); hermes `RT-REALM-PULL-SHOWS-AN-UNTOUCHED-AGENT-AS-CHANGED` unchanged · was on 2026-11-17 after w1117-realm: 1 hermes subtask open — `RT-REALM-PULL-SHOWS-AN-UNTOUCHED-AGENT-AS-CHANGED` BLOCKED on Eternia `QA-NO-PRESS-STEERS-A-REALM-AGENT-BY-A-PARENT-THE-REALM-DOES-NOT-SHARE` (its two-account read now runs on the fixture accounts; its case needs that fixture); `RT-REALM-PULL-NEVER-APPLIES-A-PUBLISHED-STEERING-EDGE` closed REFUTED c8bb046ed6 (read live: the member's copy is steered by the parent; the stored record's spelling is follow-up `RT-REALM-REPLICA-SAVED-STEERING-DISAGREES-WITH-ITS-READERS`); Eternia rows of this task: `MC-REALM-IDLE-PULL-SAYS-ARTIFACTS-UPDATED` and `MC-REALM-CARD-SHOWS-AN-EMPTY-AGENT-CHANGES-HEADING` (filed 2026-11-17, waiting for a review batch); was, after w1116b-rtfu: `RT-REALM-IDLE-PULL-SAYS-ARTIFACTS-UPDATED` closed DONE 911dd57e38 · filed 2026-11-16 by lane w1115e-rs from the owner's report of 2026-11-16 (the realm card of "test realm" on a member's machine) · architecture: hermes fork-owned only — `agent_runtime/realm_sync/status.py`, `realm_sync/drift.py`, `realm_sync/workspace_changes.py`, `agent_runtime/realm_revert.py`, `agent_runtime/persona_instance_sync/pull.py`; Eternia reads `unpublished_changes` and the drift rows as they are · the two subtasks do not share one cause (one is a change the status never counts, the other a change it counts that nobody made) · siblings, closed: `RT-REALM-STATUS-MISSES-A-WAITING-WORKSPACE-LEAVE` (the status blind to a waiting change, the slots row's shape) and `RT-REALM-PUBLISH-BASELINE-KEEPS-REMOVED-AGENTS` (a baseline that disagrees with the store, the agent row's shape); the class fix `RT-SYNC-DRIFT-AND-REVERT-GENERIC` was closed as churn by the owner on 2026-11-16 — these are the third and fourth instances of "the unpublished-changes accounting is not what publish and pull write", for the review batch to weigh · review w1115e.30: passed with both subtasks and both Eternia QA rows; the design cluster weighed — of the four rows, two (the waiting workspace leave, these slots) are one flaw: the status walks a hand-kept list of families that publish does not share, so a family publish writes and the walk forgot is invisible; the other two (the baseline that kept removed agents, this agent) are a second flaw: the baseline's writers (pull, publish, revert) do not agree on the shape they record; one design fix does not replace both rows — the slots row is built AS the first flaw's fix (below), the agent row keeps its own ledger fix, and `RT-SYNC-DRIFT-AND-REVERT-GENERIC` (descriptor-generic drift and revert, closed as churn) is not reopened: neither fix needs it · reviewed 2026-11-16 w1115e.30 · READY 2026-11-16 · handoff 2026-11-16 (w1115e-hm): both subtasks built and landed (c0680e925e slots in the status via publish's own compare, machine reports left out per the owner's RULED; 308a54da63 the untouched agent: ledger-aware drift, publish projection and revert); both now LIVE CHECK, waiting only on a live read with two staging QA accounts through launcher_qa (Eternia QA-NO-PRESS-PUTS-AN-AGENT-IN-A-WORKSPACE and QA-SEED-SLOT-REFUSED-IN-A-SERVER-REALM, w1115e-qf3, not landed when this lane ended); close the task when both reads pass · handoff 2026-11-16 (w1115e-qf3): slots row closed DONE c0680e925e after its live read; a new defect from that read filed as RT-REALM-MEMBER-TOLD-UNPUBLISHED-OVER-A-WORKSPACE-NEVER-SHARED (a member reads Unpublished changes because the published realm record names a workspace the owner never shared); the agent row stays LIVE CHECK waiting on Eternia QA-NO-PRESS-GIVES-AN-AGENT-A-STEERING-PARENT; task stays open, claim released · handoff 2026-11-16 (w1115e-qs): w1115e-qs: RT-REALM-PULL-SHOWS-AN-UNTOUCHED-AGENT-AS-CHANGED stays LIVE CHECK — its case (a published agent steered by a parent the member lacks) cannot be set up through the product, see its handoff; its reachable twin read clean (no change after four pulls); two new subtasks filed from the read, READY and waiting for a review batch: RT-REALM-PULL-NEVER-APPLIES-A-PUBLISHED-STEERING-EDGE, RT-REALM-IDLE-PULL-SAYS-ARTIFACTS-UPDATED; the task stays open · handoff 2026-11-19 (w1118a-realm4): w1118a-realm4 read both pull fixes live in Eternia and closed RT-REALM-MEMBER-DESK-ARCHIVED-BY-A-PULL-BLOCKS-THE-AGENT-COMING-BACK DONE ce3b47fc6a and RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK DONE 68a504deb7; on the Eternia side MC-REALM-GRANT-OFFERS-NOT-RE-READ-AFTER-SIGN-IN closed DONE 35ef620dc6 and MC-REALM-MEMBER-OFFICE-STAYS-EMPTY-AFTER-FIRST-PULL stays open, not reproduced again
- **`TASK-FRESH-INSTALL-NEKO` — A new install opens with Neko Mission Lead ready to talk, instead of an empty agent list** · task: fresh-install-neko · 3 subtasks on 2026-11-18 (2 ready here, 1 in Eternia's `mission-control-queue.md`: `MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME`) · RULED 2026-11-18: owner — "new installs default agent should be neko mission lead"; "base is still the base for the protocol layer though don't change that aspect of base" · READY 2026-11-18 · **TAKEN 2026-11-18 w1118-neko on DESKTOP-QJ7DDV2 as nekwo in w1118-neko**

## Design-fix tasks — 2026-11-15 (review batch w1115e.9, B59; filed by lane w1115e-dfile)

- **`RT-MESSAGING-RETIRE-FORK-TELEGRAM` — Hermes stops carrying its own Telegram transport once the upstream one has passed the owner's trial** · group: one-messaging-transport · architecture: remove `telegram_api.py` / `transport.py` from `agent_runtime/messaging/` after the trial · reviewed 2026-11-15 w1115e.9 · DEFERRED 2026-11-15: owner — "unclaim that telegram row for now" — behind `RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN`, the upstream-adapter trial, deferred with the same words · waits: `RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN`

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

- **`RT-LATE-STEER-TYPED-ON-A-PAIRED-DEVICE-IS-NOT-ANSWERED-THERE` — A late steer you typed on a paired device is answered on that device** · group: mobile-dm-input-device-qa · `agent_runtime/mission_chat_steer.py` · `hermes_cli/harness_parts/persona/chat_turn_commit/leftover_steer.py` · `hermes_cli/harness_parts/serve/queued_turn_origin.py` · found 2026-11-12 (w1112b-hm-latesteer, building `RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT`) · read in code, not reproduced: an accepted steer's ledger record keeps its id, text and turn but not who sent it, so its own turn is queued with an origin that is not the steer's — `{owner: None, gateway: False}` for a steer typed at a Work turn (`_operators_own_send`), the FIRST message's sender for a steer typed at an operator's turn; `queued_turn_peer` answers a paired device only when the origin says `gateway` and names its live connection · guess: a steer typed on a phone at a running task gets its late turn's frames and `turn_settled` on the desktop app only, and one typed on the desktop at a turn the phone sent is answered to the phone; whether the steer door runs on the sender's serve request (so `send_origin()` could be read there) was not checked · sibling: `RT-LATE-STEER-AT-YOUR-OWN-MESSAGE-CARRIES-ITS-ATTACHMENTS-AGAIN` · already there at 77feaff8b5 · not in done-when · done when: a test steers late from a gateway connection and the late turn's queued origin names that connection, or the read shows the app already gets the turn another way and the row closes refuted · LIVE CHECK 2026-11-12: built 1de21f3c20 (on hermes origin/main); read with a paired phone: type a /steer on the phone at a desktop message whose reply has started, and read that the late steer's answer arrives on the phone (and a desktop late steer at the phone's message is not sent to the phone) · handoff 2026-11-12 (w1112b-hm-turnfu): read in code (origin decides delivery: the serve answers a device only when the send's origin names its connection), fixed and pinned by test_late_steer_is_an_ordinary_message (two device tests; 3 mutations red); read live on Linux what one desktop can show (hermes ecc419e1eb, Eternia e3d3df244a, fixture, Base): the accepted steer record now carries send_origin {owner conn-1, gateway false} and the steer-next send's origin is that same sender; NOT read: delivery to a paired device — this box has no paired phone or gateway client a lane can drive, so this check needs a box with a paired phone · handoff 2026-11-12 (w1112b-hm2): moved from `TASK-TURN-CLEANUP-FOLLOWUPS` to EterniaLauncher `TASK-MOBILE-DM-INPUT-DEVICE-QA` (owner: every check that needs a real phone lives in that one task; review batch w1112b-3 §7) — the row stays in this queue because its fix is here; it waits only on the phone sitting · handoff 2026-11-15 (w1115e-dz23): TASK-ONE-TURN-RECORD closed 8ce7470b6b: a turn's origin is now taken once at admission (chat_turn_commit/turn_record.py) and the steer queues read it; the late steer's own sender still comes from its accepted record, unchanged; the live read still needs a box with a paired phone · handoff 2026-11-17 (w1116b-rtfu): not read: this Windows box has no paired phone or gateway client a lane can drive; unchanged — waits on the phone sitting (EterniaLauncher TASK-MOBILE-DM-INPUT-DEVICE-QA); claim released

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

- **`RT-INDEPENDENT-AGENT-COPY-HAS-ONE-ACTION` — People can make an independent copy of an agent wherever they create or share one** · group: runtime-followups · from: `TASK-INDEPENDENT-AGENT-CREATION` · companion UI slice lives in Eternia; return the destination identities and report cross-realm reuse from the Harness so the UI can offer the general copy action · REQUIRES windows, linux · LIVE CHECK 2026-11-18: Create an agent from a shared source both from Agents and from Agent Sync. Confirm the copy has its own persona, profile and chat and the original still opens. · unblocked 2026-11-18: `RT-NEW-AGENTS-GET-OWN-PERSONA-AND-PROFILE` closed DONE c2e221d1a4 · waits: `RT-NEW-AGENTS-GET-OWN-PERSONA-AND-PROFILE` · handoff 2026-11-18 (independent-agent-creation): Eternia bf00e6d3e0 offers one-click copy in Agents and warns in Agent Sync before sharing an identity already used by another realm. The Mac host ran the widget and RPC coverage. Live launcher_qa requires Windows or Linux.

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

- **`RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN` — Telegram can run on upstream's connector as a second option, off by default, so the owner can try it with a real bot before anything is switched** · group: remote-parity-and-two-machine-proof.p10-messaging · fork / messaging · filed 2026-11-14 at the owner's ask in chat ("if so then just switch it", then "i need a proper audit") · seen in a test: on branch `audit/upstream-telegram-switch` (62920f2b68) the upstream Telegram adapter, connected over HTTP to a local stand-in for the Bot API with no GatewayRunner, did what the fork's own transport does — queued turn on the persona's one root, real reply, 4,096 split, `/persona`, forum topics, approval cards — once five defects were fixed in the shim: a stranger's media fetched before refusal, replies sent silently, upstream's command menu pushed to the bot, the bot token logged at INFO, message text logged at DEBUG; note `docs/agent-runtime-harness/evidence/upstream-adapter-as-transport-2026-11-14/SWITCH_AUDIT.md` · not shown: real Telegram, and two upstream Windows tests of stuck-poll recovery fail on this box (cause not investigated) · to build: a harness setting that picks the transport per token (never both: one poller per bot), the shim and its Telegram subclass from the branch, the token from `agent_runtime/messaging/credentials.py::bot_token`, the Allow list fed from the shim's refusals with the display name it lacks today, the press handler registered through upstream's plugin handler factory so a rebuilt application keeps it · done when: with the setting on, the owner's real bot answers on a phone (it buzzes, the reply threads, a card's buttons work) for a day of ordinary use, and with it off nothing about today's Telegram changes · related: `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS`, `FORK-PARALLEL-MESSAGING-GATEWAY` · folded 2026-11-15 (w1115e-rr2, owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"): `FORK-PARALLEL-MESSAGING-GATEWAY` (its question — keep the fork's own gateway beside upstream's — was answered by the owner's ruling to reuse the upstream connectors; owner 2026-10-20 "sounds good persona system for our custom gateway is the way") and `RT-MESSAGING-PLATFORMS-TELEGRAM` (the fork Telegram transport is on main, off by default; its remainder is this row's opt-in trial; owner triage 2026-11-09 "New optional channel; off by default") are closed into this row: after the opt-in trial, retire the fork transport in `agent_runtime/messaging/` · DEFERRED 2026-11-15: owner — "unclaim that telegram row for now" (the real-bot trial is off the owner's list; the opt-in stays shipped, off by default) · waits: owner-ruling · handoff 2026-11-14 (msg-live-note): the live check ran against real Telegram on a throwaway bot, branch audit/upstream-telegram-switch 790202d002, script scripts/live_telegram_check.py there (reported by the owner, not seen by the lane): the bot reached step 6 of 6, so connect, the threaded reply, the formatted reply, the split long reply, the approval card press and edit, and a photo all went through real Telegram; asked whether the phone buzzed, the reply threaded, the formatting rendered, line 130 arrived and the card changed, the owner answered yes; the console summary was not pasted and the stranger step is not confirmed; not covered by it: a day of ordinary use, and the two failing upstream Windows stuck-poll tests · handoff 2026-11-14 (msg-opt-in): built and on main a682b32b82 (seen in a test): the setting messaging_telegram_transport picks fork (default) or upstream in the serve lane, a changed setting stops the running connector before the other starts, the operator list is asked at the adapter's intake with the sender's name, the card press handler is registered on every application the adapter builds; 111 messaging tests pass, each new check watched red; left is only the owner's own bot: turn it on with hermes config set plugins.entries.eternia-harness.settings.messaging_telegram_transport upstream on the machine whose Harness holds the bot token, use it from a phone for a day, and switch back with fork if anything is off; the builder could not do this read — it needs the owner's bot token, phone and Telegram account
- **`RT-MACOS-LINUX-BUNDLED-DESKTOP` — macOS / Linux bundled desktop ships no OS secure store: `keyring` (Keychain / Secret Service) is not in the bundled-desktop packaging, so `auth.os_secure_store: true` refuses to start there — add it to those targets' packaging when they exist** · group: signed-installs · see: Eternia `TASK-MISSION-CONTROL-ON-MAC` · `fork` · evidence: `agent_runtime/host_store/desktop.py::admitted_keyring_backend` · filed 2026-09-28 (lane w5-hdpapi) · `keyring` is in neither pyproject.toml nor uv.lock; add it as an optional extra + networked `uv lock` + bundled-desktop.yaml darwin/linux extras in the change that first builds those targets · RULED 2026-10-16: owner — "add keyring when mac/linux builds exist, not now"; prove it at the Mac sitting · RULED 2026-11-10: owner — split: the Mac half (Keychain `keyring` extra + proving `admitted_keyring_backend` on a Mac) moves to the Mac sitting task `TASK-MISSION-CONTROL-ON-MAC` (Eternia, "…move the mac to a mac sitting task"); the Linux half (Secret Service in a Linux bundled target) stays in this task · DEFERRED 2026-10-18: `bundled-desktop.yaml` declares no darwin/linux target yet, so there is no packaging to add it to; the change that adds the first such target adds `keyring` (optional extra + networked `uv lock` + that target's extras) and proves `admitted_keyring_backend` at the Mac sitting — owner 2026-10-16 · moved 2026-11-12 (triage w1112b): from `TASK-EMBEDDED-HERMES` to `TASK-SIGNED-INSTALLS` — both halves wait on a macOS or Linux bundled-desktop target, which that task builds (Eternia `COMP-HERMES-POSIX-BUNDLE`); owner 2026-11-12 kept it deferred (deferred-task review, batch 3: "the other nine stay deferred (phones, release, Linux packaging)") and then "undefer everything in the open ready tasks being worked on so they can complete"; the 2026-11-10 split named a Mac row that was never filed, so the row keeps both halves · folded 2026-11-16 (review w1115e.18, B68; owner "Accept all"): hermes `RT-NAMESPACE-DELETE-LEAVES-SAVED-SIGN-INS` — done when also: deleting a namespace removes its `hermes-agent/<ns>` keyring entries (`namespace_admin.py` touches no host store today, and no shipped build binds the keyring yet)

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

- **`RT-RECHECK-AFTER-THE-PRE-LAUNCH-HERMES-UPDATE` — After the pre-launch Hermes update, 33 old findings in upstream code are checked once more and only the ones still true come back** · group: upstream-footprint-ledger · upstream-owned code the fork cannot edit (§ Upstream-owned) · filed 2026-11-15 by w1115e-rr2 from the deep sweep 2026-11-15 §H-B3 (owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure") · read in git, not re-run: the update (merge-base 3b42157858 to `upstream/main`) rewrites the files these rows cite — `hermes_cli/gateway.py` +30/−123, `hermes_cli/gateway_windows.py` +96/−27, `hermes_cli/config.py` +64/−235, `agent/ssl_verify.py` +74, `tools/delegate_tool_config.py` +41, `agent/prompt_builder.py` +60/−25, `tui_gateway/host_supervisor.py` +41/−15, `hermes_state.py` +31/−21, `gateway/hosted_room_policy_checkpoint.py` +30 · architecture: no fork edit and no upstream edit — a re-check only; each survivor is filed as its own row by the layer it lands in (a fork seam per the fork-route-first rule, or an upstream issue); each row's full text is in `Harness_Brain/80 — Archive/Queues/` (runtime-queue-2026-11.md, fork-hygiene-queue-2026-11.md) · checklist (each row closed into this one, its owner quote kept): `RT-REQUEST-BUILT-RESOLVES-WEB`: re-time the per-request web-search provider lookup in `agent/transports/codex.py::_alias_wire_tools` (owner triage 2026-11-09 "Small latency; owner ruled wait on upstream"); `RT-SEND-PREP-H7-UNRESOLVED`: re-split the 47–50 ms warm request build in `ResponsesApiTransport.build_kwargs` ("Small latency measurement; waits on upstream"); `RT-SEND-PREP-H2-H6`: re-measure skill preload and package stamps on a skill-heavy persona; it did not reproduce on the fresh route ("Small latency; waits on upstream"); `RT-SKILL-CATALOG-FRONTMATTER`: re-time `tools/skills_tool._skill_catalog` frontmatter parsing and the kanban gate's 1.3 s first import ("Small performance gain; upstream-owned"); `RT-DASHBOARD-AUTH-SCRYPT-IMPORT`: check `plugins/dashboard_auth/basic` still computes its scrypt dummy hash (~0.2 s) at import ("Test-speed issue only; no user impact"); `RT-PROCESS-STARTUP-UPSTREAM-WORK`: re-time the provider discovery (~1.6 s) that importing `hermes_cli.config` runs for read-only verbs ("Noticeable but not broken; depends on upstream accepting PRs"); `RT-I18N-BUNDLED-PER-HOME`: check `agent/i18n.py::_load_catalog` still re-reads the bundled translations per profile ("Performance mostly felt in tests; upstream-owned"); `RT-CONFIG-NOFILE-REBUILD`: re-time a profile with no `config.yaml` through `hermes_cli/config.py::_load_config_impl` (config.py +64/−235 in the update; 72.5 s vs 41.2 s test file) ("Performance tweak; upstream-owned, workaround is adding a file"); `RT-AUX-KEY-CHAIN-LOAD-CONFIG`: count `load_config()` calls per `agent/auxiliary_client._resolve_api_key_provider` auto resolution (~48 providers) ("Performance gain only; upstream-owned"); `RT-NATIVE-WORKER-UPSTREAM-BOOT`: re-time a native worker's ~5 s to first reply: `tui_gateway.server` import, first agent build, first `model.options` ("Felt latency but depends entirely on upstream work"); `RT-CHECKPOINT-PM-ENSURE`: check `tools/checkpoint_manager._run_git` still calls `pm.client.ensure` on every git call (~11 ms each) ("Speed-up mostly felt in test runs; upstream owns the fix"); `RT-DELEGATION-KNOB-ENV-DEAD`: check `DELEGATION_MAX_CONCURRENT_CHILDREN` / `DELEGATION_CHILD_TIMEOUT_SECONDS` still lose to DEFAULT_CONFIG in `tools/delegate_tool_config.py::_knob` (+41 in the update) ("Settings work through config instead; minor"); `RT-CONTEXT-MANIFEST-WITHIN-KIND`: check `/context` still marks every candidate of a kind loaded while `agent/prompt_builder.py` (+60/−25) loads only the nearest ("Misleading display in a power-user command; upstream-blocked"); `RT-HERMES-STATE-SCHEMA-STALE`: check Windows chat search recovers by itself after its search index is damaged (`hermes_state.py` +31/−21) ("Real but rare; owner already ruled to wait for upstream"); `RT-SPARK-PRO-USAGE-BUCKET`: check `gpt-5.3-codex-spark` on the ChatGPT-account Codex route; `hermes_cli/codex_models.py` already lists it ("Model is already safely disabled; adding it is a nice-to-have"); `FORK-WINDOWS-SIGNAL-SAFETY-CARRY`: check whether upstream now ships an equal Windows Ctrl+C safety fix; if it does, drop the carry ("Reminder only; nothing to do until upstream changes"); `RT-GATEWAY-START-MANAGED-PYTHON`: check `hermes --profile <name> gateway start` from the managed venv (`hermes_cli/gateway.py` +30/−123) (owner 2026-11-05 "thats upstreams gateway stuff im going to build my own external gateways"); `FH-FLAKE-API-ADMISSION-OFF-LOOP-UNDER-LOAD`: re-run `tests/gateway/test_api_admission_off_loop.py` (owner triage 2026-11-09 "Test-only timing flake; the product itself is not shown broken"); `FH-FLAKE-SESSION-AUTHORITY-OWNER-KILL-UNDER-LOAD`: re-run `tests/gateway/test_session_authority.py` (same triage); `FH-FLAKE-BROWSE-SCHEMA-DRIFT-CONCURRENT-UNDER-LOAD`: re-run `tests/hermes_cli/test_browse_schema_drift.py` (same triage); `FH-FLAKE-SCHEDULER-PROVIDER-RECOVERY-THREAD`: re-run `tests/cron/test_scheduler_provider.py` (same triage); `FH-FLAKE-API-PENDING-DAEMON-DEADLINE`: re-run `tests/gateway/test_api_pending_daemon.py` (same triage); `FH-FLAKE-EXECUTE-CODE-GATE-LOOP-TICK`: re-run `tests/gateway/test_local_turn_origin_execute_code_gate.py` (same triage); `FH-FLAKE-LOCAL-SESSION-APPROVAL-CHILD`: re-run `tests/gateway/test_local_session.py` (same triage); `FH-FLAKE-SHARED-BUSY-RECEIVE-DEADLINE`: re-run `tests/gateway/test_shared_busy_receive_loop.py`, an upstream file the fork edits (same triage); `FH-FLAKE-WEBHOOK-AUTHORITY-CHILD`: re-run `tests/gateway/test_webhook_authority.py`, an upstream file the fork edits (same triage); `FH-FLAKE-SESSION-CONFIG-PROJECTION-PROVIDERS`: re-run `tests/gateway/test_session_config_projection.py` ("Only seen under heavy test load; no user report"); `FH-FLAKE-CONNECTOR-OPERATION-RPC-NO-REPLY`: re-run `tests/tui_gateway/test_connector_operation_rpc.py` (same triage); `FH-FLAKE-PM-STREAMING-DEADLINE-UNDER-LOAD`: re-run `tests/pm/test_environment_build.py` (same triage); `RT-FLAKE-UPDATE-EXISTING-MAIN-SWITCH-HANDOFF`: re-run `tests/hermes_cli/test_update_existing_branch_baseline.py`, on a quiet box first (deferred 2026-11-10 into the load-flakes batch); `RT-UPSTREAM-TEST-RACES-TWO`: re-run `tests/tools/test_browser_eval_supervisor_path.py` and `tests/agent/test_run_agent.py::TestExecuteToolCalls` (owner 2026-10-16 "pr branches should remain idle"); `FH-UPSTREAM-TESTS-STRIP-SYSTEMROOT`: re-run `tests/hermes_cli/test_update_restore_authority.py` and `tests/hermes_cli/test_runtime_maintenance_exclusion.py` on Windows ("Upstream test bug; product unaffected"); `FORK-QUALIFY-NATIVE-WINDOWS-MSYS`: re-check MSYS foreground-child cleanup on native Windows ("Rare leftover processes; upstream-owned; needs report first") · done when: the update has landed; the 16 test files are re-run at -j 24 on a busy box, the 11 latencies re-measured once (as Eternia `TASK-WINDOWS-HANDOFFS` rows), the 6 behaviours re-read; only what still fails is filed, and this row closes · reviewed 2026-11-15 w1115e.10 · DEFERRED 2026-11-15: waiting on the pre-launch hermes update; until it lands

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

- **`RT-ROOM-TURN-CONNECTION-CHURN` — Discussion rooms would move between members faster if a turn did not open the room database about seventy times** · group: windows-handoffs · `agent_runtime/discussions/service.py::DiscussionService.prepare`, `gateway/hosted_room_policy_checkpoint.py`, `tui_gateway/hosted_room_driver.py` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2: after 5cd83a166db a twelve-member room still takes ~0.8 s per member turn with an instant model, CPU-bound on SQLite connection opens (~4,100 per two-round test; every op opens and closes its own connection); `prepare` runs twice per turn (the terminal publish, then the next cycle), each reading the room three times and the policy checkpoint twice; most opens are in upstream hosted-room modules (a door, never an edit); Windows also pays `tests/home_io_guard.py`'s realpath per mkdir · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-10: joins the owner-deferred speed task TASK-AGENT-START-UP-COST · waits: owner-ruling

## Filed on arrival — 2026-11-11 (launcher plan w1111e-manage-ws)

- **`RT-GROUP-MEMBER-FIRST-TURN-COLD-START` — A group member with turn isolation on asks its model sooner after you message the room** · group: windows-handoffs · measured 2026-11-12 by w1112a-hmtests on DESKTOP-QJ7DDV2 (moderate load, eight runs of `tests/agent_runtime/test_discussion_group_compute.py` with temporary monotonic stamps): submit → claim 0.05 s, → member worker `main` 0.6-1 s, → worker ready 1.3-2.3 s more, → `open_member` done 2-3.7 s more, → compute host `main` 1-1.4 s more, → `send` returns 1.5-2 s more, → first model request 6.2-9.6 s more; 15-17 s on a quiet box, 27 s on a busier one; the last leg (compute host to first request) is the largest · REQUIRES windows · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-12: its task is deferred until the owner reopens it · waits: owner-ruling

## Filed on arrival — 2026-11-12 (safe local runtime restart)

- **`RT-WINDOWS-UPDATE-RESTART-DEFAULT-IDENTITY` — Updating Hermes restores the host gateway under its default identity** · group: windows-handoffs · seen 2026-11-13 by hermes-creation: canonical updates from 51014a80 through 1825fa6445 and 4d29a8936c pause the zero-turn default multiplexer but automatic Windows restart repeatedly selects sticky active profile amelia and refuses a separate poller; explicit hermes -p default gateway restart restores all eight original profiles and Telegram · cause: gateway_windows._launcher_settings uses gateway._profile_arg which returns an empty selector for the default root; detached boot follows active_profile; the later update fleet also labelled the root multiplexer amelia, classification cause not yet traced · done when: canonical Windows update preserves the root gateway identity and restores its original served profiles with one poller through existing lifecycle authority · BLOCKED 2026-11-15: owner decision — May the restart fix move three upstream watcher lines into the fallback branch, raising deleted_lines from 874 to 877 with 224 files and one heavy file unchanged? · Recommend: yes. The Windows branch uses the proved paused home once and keeps the shared watcher as the only respawn path; the candidate and eight-profile native drill receipt are on wave/codex-win-hermes at 83869ce5d3. · REQUIRES windows · handoff 2026-11-15 (codex-win-hermes): The update watcher, not the supervised launcher renderer, chose the wrong home: its Windows overlay was based on the updating CLI, and its unpinned selectorless root followed active_profile. Five Windows regressions red on 1e7d9652a5 and green on topic 8179f588ed. An isolated native Windows pause/resume restored the default and all eight profiles; the replacement default PID was the only new Telegram poller against a loopback fixture, and the fleet labelled it default. The topic waits on the footprint ruling (three base lines moved into else) and a landing; a full source/dependency swap was not exercised. · **TAKEN 2026-11-15 codex-win-hermes on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes**

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
- **`RT-REALM-PULL-SHOWS-AN-UNTOUCHED-AGENT-AS-CHANGED` — A member who never touched an agent is not told it has local changes after a pull, and Revert all keeps it clean through the next pull** · group: realm-members-see-what-is-shared · reported by the owner, not seen by the filer: 2026-11-16, a member's realm card after a pull read "Unpublished agent changes: 1 agent changed" with `personainst_dev_agent_8b319ebf` Changed (Agent · in ws_testv4_afb811); Revert all answered `reverted_to_upstream` ("Local edits discarded — the realm version is back"); the next pull showed the same agent changed again; Recent activity alternated "Pulled realm — 2 artifacts updated · skills reconciled" with "Reverted local changes — 1 reverted to the realm version" (once "2 reverted … and 1 refused") · seen in a test 2026-11-16 (w1115e-rs, a scratch hermes home, hermes 31d884a5ba, hermes' own `apply_persona_instance_pull`, `store_drift_items` and `revert_realm_sync`): a pulled agent whose `steered_by` names a parent this machine does not hold (here `personainst_profile_base`, a canonical channel, which publish never ships) mints with the edge dropped (`steering_dropped … parent_absent`) and reads `persona_instance:…:changed` at once; Revert all answers `reverted_to_upstream` and the change clears; the next pull answers `adopted` and the change is back — three rounds, the same each time; the same agent with no steering edge pulls `converged` with no change · read in code: the pull settles the baseline at the REMOTE hash (`persona_instance_sync/pull.py::PullPass._settle`) while the replica it wrote projects without the dropped edge, and `realm_sync/drift.py::_persona_instance_store_drift_items` compares that projection with the baseline without reading the dropped-steering ledger the pull keeps for this case (`_healable_dropped_parents` honours it for `kept_local` rows only); Revert writes the upstream body through the same lossy write and realigns the baseline to the LOCAL hash (`realm_revert.py::_realign_baseline`), so the next pull reads local unchanged and remote moved, takes it again (`adopted`, an updated artifact) and resets the baseline to the remote hash · guess: the owner's `personainst_dev_agent_8b319ebf` carries such an edge (a steering parent the member's machine does not hold); other lossy fields are not ruled out — the same scratch probe minted a `model_override_issued_at` spelled without microseconds or with `+00:00` as a change, which no current publisher writes · architecture: hermes fork-owned `agent_runtime/realm_sync/drift.py` (count a replica against the body as minted, the pull's ledger being the one owner of what was dropped) and `agent_runtime/realm_revert.py` (a revert leaves the baseline the next pull agrees with); no second hash beside the pull's baseline and ledger · done when: on a member, a pulled agent whose steering parent is absent reads no local change after the pull, after Revert all and after the next pull; red when the ledger read is removed; read live on two staging accounts once a lane can place an agent through the QA controls (Eternia `QA-NO-PRESS-PUTS-AN-AGENT-IN-A-WORKSPACE`) · review w1115e.30: the premise was seen in a scratch test and reported live by the owner; the architecture holds — the drift compare reads the pull's dropped-steering ledger (its one owner) for every row, not only `kept_local`, and revert leaves the baseline the next pull agrees with; the `model_override_issued_at` spelling is an edge, documented only (no current publisher writes it) · not churn: a member is told, after every pull, that they changed an agent they never touched, and Revert all cannot clear it · same-file sweep: none open on `drift.py`, `realm_revert.py`, `persona_instance_sync/pull.py`; it shares nothing with the slots row (`status.py`), so the two can run as one main lane and one row lane · reviewed 2026-11-16 w1115e.30 · unblocked 2026-11-19: Eternia `QA-NO-PRESS-STEERS-A-REALM-AGENT-BY-A-PARENT-THE-REALM-DOES-NOT-SHARE` closed by the owner as churn (w1118a.7: no product path publishes an agent steered by a parent a member lacks, so no QA fixture is built for it); whether its unit proof (test_persona_instance_dropped_edge_rounds.py) now closes this row, against the owner's 2026-11-17 live-read ruling, is the owner's to re-confirm · LIVE CHECK 2026-11-19: the owner opens his own member's realm card after the next pull of the realm that held personainst_dev_agent_8b319ebf, presses Revert all, pulls again — no 'Unpublished agent changes' and no revert/pull alternation in Recent activity · handoff 2026-11-16 (w1115e-hm): built and landed 308a54da63 (the pull's ledger records the body as minted; drift, publish projection and revert read it), the owner's three rounds pinned in tests/agent_runtime/test_persona_instance_dropped_edge_rounds.py; the live read is not done for the same reason: no launcher_qa surface in this lane, and QA-NO-PRESS-PUTS-AN-AGENT-IN-A-WORKSPACE (w1115e-qf3) had not landed · handoff 2026-11-16 (w1115e-qf3): live read not done: launcher_qa has no product path that gives an agent a steering parent (placing Base through the inspector Library mints steered_by []; the Agent Flow chart has no QA controls), and setting it with the harness CLI in the lane namespace was refused as a side door around launcher_qa; Eternia QA-NO-PRESS-GIVES-AN-AGENT-A-STEERING-PARENT filed for it; agent placement itself now works (QA-NO-PRESS-PUTS-AN-AGENT-IN-A-WORKSPACE, read live). Stays LIVE CHECK; claim released · handoff 2026-11-16 (w1115e-qs): live read 2026-11-16 (w1115e-qs, staging, QA Realm, A and B, Eternia a7e5c733c5, hermes primary 40aebfdc56): the row's case could not be set up through the product — Agent Flow applies only a chart owner's own edges, the canonical personainst_profile_base never joins a chart roster once its persona has a placement, and deleting a parent through the office strips it from the child's steered_by (read in B's store: c97988bb left 1f933b64 at 00:37:17); read instead: B wired baff1388 -> 1f933b64 through Eternia's new Agent Flow controls and published, and A pulled four times with no unpublished change and no agent taken again (updated_at unmoved), but A's copy never got the edge (RT-REALM-PULL-NEVER-APPLIES-A-PUBLISHED-STEERING-EDGE) and every idle pull said "2 artifacts updated" (RT-REALM-IDLE-PULL-SAYS-ARTIFACTS-UPDATED); Revert all is offered only with a change and none appeared. Stays LIVE CHECK: the dropped-edge case is pinned only by test_persona_instance_dropped_edge_rounds.py — whether a test-only read closes it is the owner's call · handoff 2026-11-17 (w1116b-rtfu): not read: nothing new was built, and w1115e-qs found the dropped-edge case cannot be set up through the product; whether test_persona_instance_dropped_edge_rounds.py closes it stays the owner's call; claim released · handoff 2026-11-17 (orchestrator-w1116b): owner ruled 2026-11-17 in chat: a test-only read does not close this row; it stays open for a live two-account (owner + member, one realm) read, done with RT-REALM-PULL-NEVER-APPLIES-A-PUBLISHED-STEERING-EDGE · handoff 2026-11-17 (w1117-realm): two-account read set up live 2026-11-17 on the Windows box (staging, QA Realm: owner B stagec-smoke-2 session w1117b, member A stagec-smoke session w1117a, both signed in with browser_login, both set QA Realm up; hermes c8bb046ed6 served from the lane worktree, Eternia 81506811f4): A's fresh pull minted all three published agents, every steering parent present, and the realm card read no agent change after the pull, after a Revert all and after another pull — the reachable twin reads clean again; the row's own case (a published agent steered by a parent the member lacks) still cannot be set up: Agent Flow binds only the active workspace's placements (Eternia agent_flow_roster.dart l.59-94), publish ships every placed realm agent, every member derives the canonical channels (A held personainst_profile_base before the realm arrived), and deleting a parent strips its child's edge; filed Eternia QA-NO-PRESS-STEERS-A-REALM-AGENT-BY-A-PARENT-THE-REALM-DOES-NOT-SHARE (a qa.runtime fixture beside qa.runtime.workspace.seed that steers a realm agent by a parent in the owner's own non-realm workspace through the app's Agent Flow apply door) and set this row BLOCKED on it; the read itself needs no real account — the fixture accounts A and B suffice · handoff 2026-11-19 (w1118a-orch): 2026-11-19: decided on the owner's standing call ('when there is a decision for this session, do an analysis on it and go with reccomended'): the unit proof does NOT close it — the owner's 2026-11-17 ruling stands (a test-only read does not close it) and the case was seen on the owner's own realm, which is the one real setup that reproduces it; no agent can set up the two-account case through a product path, so the read is the owner's own card on his next pull

## Filed on arrival — 2026-11-17 (lane w1116b-rtfu)

- **`RT-SKILL-NAME-READ-TWO-WAYS` — Which skill a tool call used is read one way, so the live trace and the context report never name different skills for one call** · group: runtime-followups · from: `TASK-ONE-FACT-ONE-PLACE` · read in code, not reproduced (w1116b-rtfu, 2026-11-16, working `RT-DUPLICATE-LITERAL-TABLES-BURN-DOWN`): `agent_runtime/profile_runner/tool_payloads.py::_safe_skill_identifier_from_value` and `agent_runtime/prompt_observability/skills_context.py::_extract_skill_name` are two copies of one reader — the same name keys, the nested keys walked in a different order (`tool_input` before `invocation` in one, after in the other), and only the second reads `command_label`; baseline lines ac313ebd and b961ddf2 of `tests/tooling/duplicate_literal_tables_baseline.txt` · guess: a payload naming a skill under both nested keys reads as two different skills · B67 had marked both lines exempt with no recorded reason; read in code they are one fact · architecture: one reader in the lower module, the other calls it (layer order per `tests/tooling/test_fork_import_layers.py`) · done when: one function owns the key walk, both baseline lines are cut, and a test pins one payload read the same by both callers · NEW 2026-11-16 · churn 2026-11-17 w1115e.36: a dedupe whose disagreement is a guess: read in code, the two readers take different inputs (`tool_payloads.py` the raw invocation, `skills_context.py` the payload that one emits, `command_label` included), and no payload read two ways was seen — the precedent `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` (owner 2026-11-16) · DEFERRED 2026-11-17: churn, per the owner's 2026-11-17 "strictly look for churn"; until the owner rules · waits: owner-ruling
- **`RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES` — A member who takes the team's copy of a held desk is left with nothing to publish, instead of "1 placement removed" and "office layout changed"** · group: runtime-followups · from: `TASK-REALM-DELETE-MEETS-AN-EDIT` · `agent_runtime/office_store/conflicts.py::resolve_conflict` (take remote, edit-vs-remove arm) · `agent_runtime/realm_sync/drift.py` · seen 2026-11-19 (w1118a-hrealm5, Linux, Eternia QA Debug 1b80a0648d + hermes dee4e42839 served from the lane tree, owner B `stagec-smoke-2` in QA Realm): after a pull held agent 7b570c4d's desk (a teammate deleted it, B had moved it) and B took the team's copy (`harness office resolve-conflict --take remote`, archived), the sheet read Unpublished changes: "1 placement removed" and "office layout changed"; Revert all cleared both (1 reverted, 1 stale baseline entry dropped) · guess: the take-remote arm archives the desk without dropping its baseline entry and its archive changes the surface hash, so drift reads both as this member's; the team already has neither · not churn: the member is offered a Publish for a choice that changes nothing for the team · filed 2026-11-19 by w1118a-hrealm5 · READY 2026-11-19
- **`RT-PHONE-PUSH-TO-A-LOCKED-LOCAL-REMOTE-RAISES-AN-UNTYPED-ERROR` — A phone publishing to a realm whose local bare repository is locked gets a typed realm-sync refusal, instead of a raw dulwich FileLocked** · group: runtime-followups · from: `TASK-REALM-DELETE-MEETS-AN-EDIT` · `agent_runtime/realm_sync/git_dulwich.py::_wire` · seen 2026-11-19 (w1118a-hrealm5, a scratch test only): the dulwich push to a local-path bare remote holding `refs/heads/main.lock` raised `dulwich.file.FileLocked` out of `publish_realm_sync`; the git program answers `[remote rejected] … (cannot lock ref …)` · read in code: `_wire` catches HTTP, protocol and OS errors, not `FileLocked` · edge case: only a local-path remote (a phone syncs over HTTPS) · filed 2026-11-19 by w1118a-hrealm5 · READY 2026-11-19

## Filed on arrival — 2026-11-18 (side session from Eternia's realm push alert, `EterniaLauncher` `360d3de929`)

- **`RT-BUNDLED-NEKO-USER-INJECTOR` — An agent's SOUL or profile text can say `{user}` and the agent reads the signed-in Eternia account's name there, so no shipped agent hardcodes a person** · group: fresh-install-neko · reported 2026-11-18 by the owner: "one thing i want to add is the `user` injector from the eternia profile"; clarified 2026-11-18: "in the soul or profile md data we can put {user} and it will take the eternia account profiles name instead of hardcoding Tony or a name" · read in code 2026-11-18: no placeholder exists today, and the runtime holds no account display name (the namespace is keyed by account id only) · RULED 2026-11-18: owner (quotes above) · do: where the runtime reads an agent's SOUL, SOUL overlay and system prompt into a turn, replace the exact token `{user}` with the account's display name, and with "the user" when none is known; the name comes from Eternia through the contract in `EterniaLauncher` row `MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME` (file `account_profile.json` at the namespace root, `{"display_name": "<name>"}`, written by Eternia); the upstream `SOUL.md` load goes through a fork seam, never an upstream edit; then the bundled Neko SOUL from `RT-FRESH-INSTALL-SEEDS-NEKO` says `{user}` where it now says "the person you work with" / "they" · architecture: one fork-owned resolver of the account name (namespace file, then the fallback) read by every prompt-text reader; no reader re-reads the file itself · done when: a persona whose SOUL says "Protect {user}'s attention" gets the account's name in its turn prompt, "the user" with no file, and a literal `{users}` or `{ user }` is left alone · READY 2026-11-18 · handoff 2026-11-18 (orchestrator): left for the Linux box (owner 2026-11-18 'Leave for Linux'); start after RT-FRESH-INSTALL-SEEDS-NEKO lands, it ships the bundled Neko SOUL this row edits; pairs with EterniaLauncher MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME, which owns the account_profile.json writer · handoff 2026-11-18 (orchestrator): also owed from RT-FRESH-INSTALL-SEEDS-NEKO (landed 2f502b2544ba, seen live in the CLI only): read Eternia on a fresh namespace through launcher_qa and see Neko Mission Lead selected by default; do it in this row's live read

## Filed on arrival — 2026-11-19 (review w1118a.29, from Eternia `HOME-AGENT-REQUEST-AFTER-A-REJECTED-UPDATE-SAYS-DOCUMENT-UNAVAILABLE`)

## Filed on arrival — 2026-11-19 (lane w1118a-hsurf)

