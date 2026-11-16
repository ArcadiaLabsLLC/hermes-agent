---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue

- **`RT-FLAKE-DISCUSSION-GROUP-MIGRATION-UNDER-LOAD` — A full Hermes test run stops failing at random in the group-chat migration test when the box is busy** · rewritten 2026-11-14 (w1114a-boardtitles, plain-English title rule): was "`tests/agent_runtime/test_discussion_group_migration.py::test_atomic_adoption_preserves_log_member_ids_defaults_and_continues_natively` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry" · group: upstream-load-flakes · `tests/agent_runtime/test_discussion_group_migration.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it
- **`RT-MACHINE-ROOTS-FOLD-BREAKING` — fold `machine_roots.json`'s five maps (`roots`, `config_roots`, `workspace_roots`, `slot_folders`, `project_roots`) to `roots` (config roots, the one map the launcher's `qa_mcp_server_freshness.dart` reads) + one owner-keyed slot map (`<ws>` / `project:<id>`, the keys `MachineRoots.slot_folder_bindings` already speaks), schema 5, with a migration** · group: agent-config-cleanup · `agent_runtime/machine_roots.py::write_machine_roots` · `agent_runtime/machine_roots.py::_read_registry_file` · `agent_runtime/store_epoch.py` · found 2026-11-02 by lane w1102c-rt (RT-BRAIN-PATHS-PLAIN-LIST slice 3, left): dropping the mirrored keys is BREAKING by `store_epoch.py`'s own entry `machine-roots-schema-3-named-halves` ("dropping the old keys is a later breaking entry") — an older edition reads a schema-5 file as schema 1 (no `workspace_roots`), migrates it in `workspace_slots.scoped_roots` and rewrites it with every slot fill gone; the fold is the store's FIRST breaking epoch raise (STORE_EPOCH 1 → 2, the consent flow for every namespace) · DEFERRED 2026-11-02: owner "reccomendations sound good" — fold it in the next breaking store-epoch batch, never alone




## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)

- **`TASK-WINDOWS-HANDOFFS-FOLLOWUPS` — Windows gateway setup and update reports keep the profiles the user chose** · task: windows-handoffs-followups · 2 ready subtasks found while checking Eternia `TASK-WINDOWS-HANDOFFS` · NEW 2026-11-15 · READY 2026-11-15
- **`TASK-AGENT-CONFIG-CLEANUP` — Agent settings: each agent's folders, data, options and abilities live in one clear place** · task: agent-config-cleanup · 3 subtasks on 2026-11-15 (1 ready, 2 deferred) · READY 2026-11-15 · unblocked 2026-11-15: `FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` woken READY by w1115e-rr2 (deep sweep 2026-11-15 §D); the other subtasks stay deferred (was DEFERRED 2026-11-09: owner — every live subtask is deferred (owner sittings parked 2026-11-09); until the owner reopens it)
- **`TASK-DISCUSSION-ROOMS-RELIABILITY` — Discussion tables: group rooms of agents keep running, explain refusals and work in release builds** · task: discussion-rooms-reliability · 3 subtasks on 2026-11-09 (1 blocked, 2 deferred) · READY 2026-11-15 · unblocked 2026-11-15: `RT-ROOM-LEASE-LAPSES-MID-CYCLE` closed by the owner
- **`TASK-ENGINE-SUITE-GREEN-FOLLOWUPS` — Agent engine follow-ups: the engine's own checks pass on main again after a lane broke them** · task: engine-suite-green-followups · 3 open subtasks on 2026-11-15 (1 ready: FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY; 2 NEEDS PLAN filed by w1115c-h2 and waiting on a review batch: RT-RUNNING-TURN-START-ROW-WAITS-OUT-THE-DEMOTE-HOLD, RT-RUNNING-TURN-START-NEVER-PUBLISHED-ONCE-UNDER-LOAD; FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD closed DONE 36a1e1d45c and FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD closed DONE c157f48749 by w1115c-h2; FH-GAME-WATCH-TEST-READS-THE-MACHINES-REAL-PROCESSES and FH-BUNDLE-SERVE-PROBE-REPORT-LOST-TO-STDERR-ON-LINUX closed by other w1115c lanes; FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN closed DONE e64d77c9f6 by w1114a-h5 through fork seams) · filed 2026-11-14 by the w1114a.30 queue pass (REVIEW_W1114A_B29), for reds met on hermes main — the twin of Eternia's architecture-gate-green-followups · was DONE 2026-11-15 0495762a2e (all 1 subtasks closed) · reopened 2026-11-15 (review batches w1114a.40 and w1114a.42, REVIEW_W1114A_B39/B41): FH-NATIVE-INDEPENDENT-TURN-TEST-TIMES-OUT-UNDER-LOAD moved in from the DEFERRED TASK-UPSTREAM-LOAD-FLAKES and FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN from the DEFERRED TASK-HERMES-TEST-ISOLATION · handoff 2026-11-15 (w1114a-h4): FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN reproduced and its fixture fixes written, but they edit three upstream test files (upstream footprint 224->226), so it waits on an owner ruling (DECISION); claim released · BLOCKED 2026-11-15: another lane — `FH-BUNDLE-OPENTELEMETRY-API-KNOWN-VULNERABILITY` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-ETERNIA-LENS` — Lens: agents watch your sources and report what changed** · task: eternia-lens · 2 open subtasks on 2026-11-15 (1 ready, 1 blocked on its predecessor; RT-LENS-RECIPE-SHELF-SHARE-AND-ADD closed DONE 3faf6ffa4e by w1115k-hlens) · READY 2026-11-15: RT-LENS-RECIPE-REALM-SYNC-FAMILY can start (reviewed w1115k.2); RT-LENS-RECIPE-DRIFT-AND-REVERT follows it · handoff 2026-11-14 (w1114a-lensrows): owner accepted the act/investigate design's five decisions ("yes reccomendations are good , the budget limits should be easily editable"), RT-LENS-ACT-ADMISSION closed DONE as the design row, its six build rows filed; Eternia's four sit under launcher TASK-LENS-ACT-AND-SAFE-INVESTIGATE · handoff 2026-11-14 (w1114a-lensact): owner un-deferred act today; design written, build rows wait on the review · handoff 2026-11-14 (w1114a.19 queue pass): RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS closed today by the owner's sitting ("yes lens says 0"), so the owner-sitting block is gone; what is left waits on a plan (SHARE-RECIPE) and an owner deferral (ACT-ADMISSION) · unblocked 2026-11-10: owner deferral triage ("rest of the triage is good") reopened `RT-ETERNIA-LENS-L2-L4`; 9 deferred idea rows archived (the Lens plan keeps them) · handoff 2026-11-10 (w1110d-lens): RT-ETERNIA-LENS-L2-L4 closed DONE ea08d34880 (L4 lens_read read live on an isolated Linux serve, fixture model, red under the lens_root mutation); RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS's hermes half read live, the owner's five orphans left as owner-sitting steps; RT-LENS-SHARE-RECIPE-TO-WORKSPACE left NEEDS PLAN with a recommendation (realm sync family) · handoff 2026-11-10: w1110a-hm closed RT-LENS-SHARED-RECIPES-OPT-IN and filed RT-LENS-SHARE-RECIPE-TO-WORKSPACE (NEEDS PLAN); the one READY row, RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS, has only the live close of the owner's five orphans on the Windows box's serve left · handoff 2026-11-10 (w1110a-org): `RT-GATEWAY-START-MANAGED-PYTHON` (a gateway that will not start) moved to Eternia's `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`; its two other-feature deferred subtasks moved 2026-11-10 to TASK-BUNDLED-VOICE and TASK-CONSOLE-TRANSCRIPT-TRUTHFUL to reopen: `RT-PIPER-FIRST-AUDIO-LATENCY` (voice speed, Eternia `TASK-BUNDLED-VOICE`) and `RT-LEAN-OPERATIVE-RULES` (agent chat prompt rules) · handoff 2026-11-15 (w1115k-hdesign): recipe sharing designed (docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md, a1f31bda92): a realm-sync shelf, a pulled recipe becomes a draft only on the person's Add; RT-LENS-SHARE-RECIPE-TO-WORKSPACE closed as the design row, three build rows filed; Eternia's row MC-LENS-SHARED-RECIPES-LIST is in the plan §6 for the orchestrator to file
- **`TASK-SLOT-SETUP-RECIPE-DESIGN` — Workspace slots: the setup recipe gets its own design** · task: slot-setup-recipe-design · 1 subtask on 2026-11-15 (1 waits on the owner's decision) · opened 2026-11-13 (Eternia owner in chat) · DECISION 2026-11-15: do you accept the setup recipe design's seven decisions (a recipe per slot shared with the workspace, holding every setup step, never blocking anything, with a per-computer "not needed here")? · Recommend: yes — the design cited on `RT-SLOT-SETUP-RECIPE-SCOPED-DESIGN` · handoff 2026-11-15 (w1115k-hdesign): design written (slot-setup-recipe-2026-11-15.md under the harness docs' planned folder, e0c2ff513c), decisions table at its top; on a yes, file its three build slices (§6) and Eternia's row (§3, verbatim there); on changes, edit the table first; two follow-up rows sit under TASK-SLOT-SETUP-RECIPE-DESIGN-FOLLOWUPS
- **`TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF-FOLLOWUPS` — Remote agents follow-ups: messaging your agents from more apps** · task: remote-parity-and-two-machine-proof-followups · 3 open subtasks on 2026-11-14 after w1114a-hmsggate (the three hardening rows closed; Discord DEFERRED; two new rows wait for review) · filed 2026-11-14 by w1114a-hmsgadapt, from Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`'s hermes subtask `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS` · NEW 2026-11-14 · READY 2026-11-14
- **`TASK-ETERNIA-LENS-FOLLOWUPS-2` — Lens follow-ups: what designing recipe sharing found beside its own rows** · task: eternia-lens-followups-2 · 2 open subtasks on 2026-11-15 (1 ready, filed this wave and waiting for a review batch: RT-LENS-SEAL-OWNER-CHANGED-TWO-ERROR-CODES; 1 blocked on RT-LENS-RECIPE-REALM-SYNC-FAMILY; closed DONE: RT-LENS-CREDENTIAL-NOT-BOUND-TO-A-HOST 9fea7d6ac4 by w1115k-hlens, RT-LENS-RPC-REFUSALS-FIVE-EXCEPTION-SHAPES e9e059c315 and RT-LENS-RECIPE-DROPPED-UPDATE-STILL-READS-ADDED bc06b114cd by w1115k-hlens2) · opened 2026-11-15 by w1115k-hdesign while designing recipe sharing · NEW 2026-11-15 · READY 2026-11-15 · handoff 2026-11-15 (w1115k orchestrator): two rows filed from Eternia's Lens UI lane (RT-LENS-RESHARE-AFTER-RESEAL-HAS-NO-STATE, RT-LENS-UPDATE-MOVED-SITE-CANNOT-SIGN-IN-BEFORE-SEAL), both READY and reviewed w1115k.5; RT-LENS-SEAL-OWNER-CHANGED-TWO-ERROR-CODES is READY too; the subtask count in this line predates them
- **`TASK-SLOT-SETUP-RECIPE-DESIGN-FOLLOWUPS` — Workspace slots follow-ups: what designing the setup recipe found beside its own row** · task: slot-setup-recipe-design-followups · 2 open subtasks on 2026-11-15 (1 ready, 1 blocked on the design's owner decision; both wait for a review batch) · opened 2026-11-15 by w1115k-hdesign · NEW 2026-11-15 · BLOCKED 2026-11-15: another lane — `RT-SLOT-RECIPE-REVISION-ALSO-RANKS-THE-WHOLE-SLOT-RECORD` every live subtask waits (1 on other work); the task turns READY when one of them does
- **`TASK-SHARED-WORK-V1-FOLLOWUPS` — Shared Work follow-ups: refresh and details agree on what was saved** · task: shared-work-v1-followups · follow-up task of Eternia `TASK-SHARED-WORK-V1` (archived) · 1 subtask awaiting design and review · NEW 2026-11-15 · READY 2026-11-15

## Design-fix tasks — 2026-11-15 (review batch w1115e.8, B58; filed by lane w1115e-dfile)

- **`RT-LENS-STORE-HAS-ONE-REVISION` — Every change to your Lens watches is numbered once, so Eternia can tell when what it shows is out of date** · group: lens-reads-from-one-store · task in Eternia: `TASK-LENS-READS-FROM-ONE-STORE` · architecture: fork-owned `agent_runtime/lens/store.py` (`LensStore` keeps per-monitor `revision`s and no store-wide one today) and its sibling `store_*.py` writers — one monotonically increasing store revision stamped at the store's single commit point; one optional field on the 4 existing `lens.*.changed` events (`decision_contract_registry.py:338-344`) and on every `runtime.lens.*` read answer (`lens/manifest.py`); traffic: 0 new realtime messages, about 20 bytes per event · coordinate with vm: its realm-sync lane (`RT-LENS-RECIPE-REALM-SYNC-FAMILY`, w1115k) writes the store, so the bump must hold on vm's write path too — name it on vm's row, never edit its files; `agent_runtime/lens/poller.py`'s observations are store writes and bump it · the Lens stream contract goldens change (the new field): regenerate them on both sides with Eternia's `MC-LENS-READS-FROM-ONE-STORE` (B57's mirror rule); the field is optional, so an older Eternia ignores it · done when: every Lens write bumps the revision exactly once, and every read answer and event carries it · mutation red: skip the bump in one writer (for example `store_proposals`), and the "every writer bumps" test names it — the writers are enumerated from the store's own write entry, not from a source list · reviewed 2026-11-15 w1115e.8 · READY 2026-11-15

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

- **`RT-LATE-STEER-TYPED-ON-A-PAIRED-DEVICE-IS-NOT-ANSWERED-THERE` — A late steer you typed on a paired device is answered on that device** · group: mobile-dm-input-device-qa · `agent_runtime/mission_chat_steer.py` · `hermes_cli/harness_parts/persona/chat_turn_commit/leftover_steer.py` · `hermes_cli/harness_parts/serve/queued_turn_origin.py` · found 2026-11-12 (w1112b-hm-latesteer, building `RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT`) · read in code, not reproduced: an accepted steer's ledger record keeps its id, text and turn but not who sent it, so its own turn is queued with an origin that is not the steer's — `{owner: None, gateway: False}` for a steer typed at a Work turn (`_operators_own_send`), the FIRST message's sender for a steer typed at an operator's turn; `queued_turn_peer` answers a paired device only when the origin says `gateway` and names its live connection · guess: a steer typed on a phone at a running task gets its late turn's frames and `turn_settled` on the desktop app only, and one typed on the desktop at a turn the phone sent is answered to the phone; whether the steer door runs on the sender's serve request (so `send_origin()` could be read there) was not checked · sibling: `RT-LATE-STEER-AT-YOUR-OWN-MESSAGE-CARRIES-ITS-ATTACHMENTS-AGAIN` · already there at 77feaff8b5 · not in done-when · done when: a test steers late from a gateway connection and the late turn's queued origin names that connection, or the read shows the app already gets the turn another way and the row closes refuted · LIVE CHECK 2026-11-12: built 1de21f3c20 (on hermes origin/main); read with a paired phone: type a /steer on the phone at a desktop message whose reply has started, and read that the late steer's answer arrives on the phone (and a desktop late steer at the phone's message is not sent to the phone) · handoff 2026-11-12 (w1112b-hm-turnfu): read in code (origin decides delivery: the serve answers a device only when the send's origin names its connection), fixed and pinned by test_late_steer_is_an_ordinary_message (two device tests; 3 mutations red); read live on Linux what one desktop can show (hermes ecc419e1eb, Eternia e3d3df244a, fixture, Base): the accepted steer record now carries send_origin {owner conn-1, gateway false} and the steer-next send's origin is that same sender; NOT read: delivery to a paired device — this box has no paired phone or gateway client a lane can drive, so this check needs a box with a paired phone · handoff 2026-11-12 (w1112b-hm2): moved from `TASK-TURN-CLEANUP-FOLLOWUPS` to EterniaLauncher `TASK-MOBILE-DM-INPUT-DEVICE-QA` (owner: every check that needs a real phone lives in that one task; review batch w1112b-3 §7) — the row stays in this queue because its fix is here; it waits only on the phone sitting

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

- **`RT-FLAKE-COMPARE-IMPORT-CALLER-UNDER-LOAD` — A full Hermes test run stops failing at random in the compare-import test when the box is busy** · rewritten 2026-11-14 (w1114a-boardtitles, plain-English title rule): was "`tests/agent_runtime/test_compare_import_caller.py::test_compare_import_preserves_source_actor_across_prepare_and_finish` times out under load ("condition did not become true", `tests/agent_runtime/test_discussion_runtime.py:134` wait helper); make its wait event-driven or its budget load-proof, never a bare retry" · group: upstream-load-flakes · fork-owned · `tests/agent_runtime/test_compare_import_caller.py` · found 2026-11-08 by w1108c-hm-reds-fork: red in the w1108c daily full run on main f353a2a4ed (beside Eternia's full fake tier, load high); green alone 4× (one run, then 3 more at -j 4) and once with its three siblings at -j 24 on 95ca419262 · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it
- **`RT-FLAKE-CONSOLE-SUGGESTION-MODES-UNDER-LOAD` — A full Hermes test run stops failing at random in the console suggestion test when the box is busy** · rewritten 2026-11-14 (w1114a-boardtitles, plain-English title rule): was "`tests/agent_runtime/test_console_suggestion_modes_native.py::test_manual_rpc_observation_click_and_owner_fences` times out under load ("timed out after 5s waiting for the condition", `tests/waiting.py:45`); make its wait event-driven or its budget load-proof" · group: upstream-load-flakes · fork-owned · `tests/agent_runtime/test_console_suggestion_modes_native.py` · found 2026-11-08 by w1108c-hm-reds-fork: red in the w1108c daily full run on main f353a2a4ed (beside Eternia's full fake tier, load high); green alone 4× (one run, then 3 more at -j 4) and once with its three siblings at -j 24 on 95ca419262 · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it
- **`RT-FLAKE-DISCUSSION-RUNTIME-CLARIFICATION-UNDER-LOAD` — A full Hermes test run stops failing at random in the discussion clarification test when the box is busy** · rewritten 2026-11-14 (w1114a-boardtitles, plain-English title rule): was "`tests/agent_runtime/test_discussion_runtime.py::test_clarification_resumes_same_member_session_with_fresh_turn_identity` times out under load ("condition did not become true", its own wait at line 134); make the wait event-driven or load-proof" · group: upstream-load-flakes · fork-owned · `tests/agent_runtime/test_discussion_runtime.py` · found 2026-11-08 by w1108c-hm-reds-fork: red in the w1108c daily full run on main f353a2a4ed (beside Eternia's full fake tier, load high); green alone 4× (one run, then 3 more at -j 4) and once with its three siblings at -j 24 on 95ca419262 · DEFERRED 2026-11-09: owner triage — Test-only timing flake; no user impact; until the owner reopens it

### Filed on arrival — 2026-11-10 (launcher lane w1110a-office: `MC-PROFILE-NAME-REVERTED-ON-RELAUNCH`)


### Filed on arrival — 2026-11-08 (launcher lane w1108c-work: `COMP-WORK-ADD-TASK-HARNESS-NOT-CONFIRMED`)


### Filed on arrival — 2026-11-08 (launcher lane w1108c-mc-console: `MC-USAGE-PROBE-PROCESS-PROFILE-NOT-AGENT`)


### Filed on arrival — 2026-11-06 (lane w1106a-hm: RT-NO-MODEL-CHAT-SENDS-AND-404S)


### Filed on arrival — 2026-11-04 (launcher lane w1104a-mc-board: `MC-BOARD-DRAG-USE-WORK-MOVE`)


### Filed on arrival — 2026-11-04 (launcher lane w1104a-mc-runtime: `MC-REALMLESS-WORKSPACE-UNREACHABLE`)






### Filed on arrival — 2026-11-03 (launcher planning lane w1103a-p-work-v1: the Work board — truth, waves, the Intelligence mount, metrics)
- **`RT-WORK-READS-MIX-ROWS-AND-HISTORY-FROM-TWO-COMMITS` — Work refresh and details describe one saved version of each board** · group: shared-work-v1-followups · `agent_runtime/work/store.py` (`synced`, `_queues`, `inspect`, `archived_ending`) · `agent_runtime/work_store/writer.py` (`sync`, `admitted`, `_tip_commit`, `history`) · source-audited 2026-11-15 at `a4f1445bad` by codex-win-hermes-handoffs, not reproduced live: after sync releases admission the read retains mutable worktree paths. A normal fetch after reset can advance the tracking ref before history resolves it, giving rows from the acquired HEAD timestamps from a later tip; an ordinary Work writer can also edit the worktree between discovery and reads. · done when: deterministic fetch and writer interleavings prove list/inspect each derive note discovery, queue bytes, metadata, brief and archive/history from one acquired commit per board, with equivalent stale/refusal and owned-worktree cleanliness and existing write/checkout safety. Observed mode keeps its last-fetched, no-fetch contract. · NEW 2026-11-15 · NEEDS PLAN 2026-11-15: choose one committed snapshot read through the Git WorkStore authority and prove the same ownership, cleanliness and freshness contracts.

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

- **`RT-CORE-CACHE-CONVERGENCE-CENSUS` — core cache convergence on the live store: the four chat-turn sidecar families are ruled (leases and steer excluded, turns and prompt_observability kept as real inputs — lane w1027k-h-rt); left is the field half, a week of the demote census over operator boots, and IC-4 (WAL raw-content keying) only if that week still names WAL triples** · group: windows-handoffs · fork / core cache · plan `docs/agent-runtime-harness/planned/core-cache-input-closure.md` (2026-10-27 section) · `agent_runtime/core_cache/vocabulary.py::_EXCLUDED_STORE_ENTRIES`, `scripts/core_cache_demote_census.py` · live phase w1027k: a week of `python scripts/core_cache_demote_census.py` reads; file IC-4 as its own row if WAL triples remain · moved 2026-11-15 from `agent-start-up-cost.core-cache-input-closure` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-09: owner triage — Week-long measurement; no user-felt problem named; until the owner reopens it · left 2026-11-05 (w1105g-hm-runtime): a week of `python scripts/core_cache_demote_census.py` reads over the operator's own boots on the Windows box; file IC-4 as its own row if WAL triples remain · REQUIRES windows
- **`RT-PEER-CANCEL-LIVE-STOP-PROOF` — D1.07's peer Stop has never been proven across two real installs (durable cancel_requested, partial output kept)** · group: remote-parity-and-two-machine-proof · moved 2026-11-10 (w1110a-org): from console-smooth-and-fast.design-sweep-d1 · fork / gateway · plan `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` D1.07 (built 5a2c887621) · `tools/agent_chat_dispatch/cancel_watch.py` · DEFERRED 2026-11-09: owner triage — Proof of a built feature; no reported failure; until the owner reopens it

### Filed on arrival — 2026-10-27 (lane w1027f-h-rt, w1027g-h-fix)


### Filed on arrival — 2026-10-27 (lane w1027b-h-fix)


### Lens plan reconciliation — 2026-10-26 (codex-lens-status)

Reconciled against the built code and the plan, not inferred from an absent old row. Optional branches retain their decision/deferral gates. Evidence and coverage: `docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md` § Current implementation and queue coverage.

- **`RT-LENS-RECIPE-REALM-SYNC-FAMILY` — A watch shared on one PC shows up on every teammate's PC as a recipe they can add, and never starts by itself** · group: eternia-lens · fork / Lens and realm sync · plan `docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md` §3, §8 and §9 slice 2 · `SyncFamily.LENS_RECIPE`, its `SYNC_PATH_FAMILIES` row, the realm-scoped publish scan and baseline, the pull applier with the new `admit` argument of `apply_document_pull`, the status and ack rows, the workspace re-key of the shelf; `tests/agent_runtime/lens/test_lens_shared_recipes_opt_in.py` then names the realm-sync modules that import `lens.recipe_shelf` · designed, not built · done when: a recipe published from one namespace is pulled into another on one Linux box and reads `not_added` there with no monitor created and nothing polled; a recipe for another realm's workspace is refused `recipe_outside_realm`; a withdrawal reaches the peer; an update leaves a running monitor's sealed digest unchanged — the plan §7 rows 1, 2, 8, 9 and 10 each red under its named mutation, and the builder reads it live · NEW 2026-11-15 · READY 2026-11-15 · unblocked 2026-11-15: `RT-LENS-RECIPE-SHELF-SHARE-AND-ADD` closed DONE 3faf6ffa4e · reviewed 2026-11-15 w1115k.2 · handoff 2026-11-15 (w1115k-hlens): slice 1 is built: `lens/recipe_shelf.py` holds `LENS_RECIPE_FAMILY` complete but unwired (its `sync_kind` is the string `SYNC_KIND`; swap it for the new `SyncFamily.LENS_RECIPE`), the baseline and conflict path helpers exist in `paths`, `filed_token` is the misfiled check a pull needs beside `admit`, `runtime.lens.recipe.list` answers `held: []` until this row reads the realm's parked tokens, and the plan's §2 to §4 are corrected to the tree; the shelf is already a MOVES place of the realm re-key (`realm_rekey.STORE_PLACES`), whose content step rewrites each document's `workspace_id`, so a re-keyed recipe has a new hash and its monitor reads `update_available` until this row decides what the mark should do there
- **`RT-LENS-RECIPE-DRIFT-AND-REVERT` — A shared watch you changed but have not published shows as a pending change, and you can put the workspace's copy back** · group: eternia-lens · fork / realm sync · plan `docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md` §3 and §9 slice 3 · a drift walk and counts on the level family's pattern (`agent_runtime/realm_sync/level_drift.py`), a `realm_revert._FAMILY_ARMS` row, the history item shape · designed, not built · done when: every `lens_recipe` drift row is revert-addressable and a revert restores the last-pulled bytes through the shelf's store door without touching any monitor, red when the arm's table row is omitted · NEW 2026-11-15 · BLOCKED 2026-11-15: another lane — `RT-LENS-RECIPE-REALM-SYNC-FAMILY` adds the family and its baseline · reviewed 2026-11-15 w1115k.2
- **`RT-REALM-LEVEL-PULL-NOT-SCOPED-TO-REALM-WORKSPACES` — A server's sync can only bring in levels for its own workspaces** · group: eternia-lens-followups-2 · fork / realm sync · `agent_runtime/level_sync.py` (`apply_level_pull`) · `agent_runtime/realm_sync/document_family.py` (`apply_document_pull`) · read in code, not reproduced (w1115k-hdesign): the publish scan sends only this realm's workspaces' levels, but the pull takes every `store/levels/<token>.json` in the subtree, so a realm can deliver a level for a workspace of another realm (adopted where that workspace has none) · the scope predicate is designed in plan `docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md` §3 and §8 (`admit`) · done when: a pulled level whose workspace is not one of the realm's is refused typed and not written, red without the predicate · NEW 2026-11-15 · BLOCKED 2026-11-15: another lane — `RT-LENS-RECIPE-REALM-SYNC-FAMILY` adds the `admit` argument this passes for levels · reviewed 2026-11-15 w1115k.2

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

- **`RT-PHONE-PILLOW-ANDROID` — Image handling works on Android phones: the fork builds the one image library Android has no ready-made build of** · group: phone-harness · fork / phone bundle · plan `docs/agent-runtime-harness/planned/bundled-phone-pool-2026-10-22.md` § Open rulings · RULED 2026-10-22: owner — a fork-built Android Pillow wheel (BeeWare mobile-forge recipe) pinned by URL and hash, psutil's Android pin shape; Pillow stays 12.3.0 · the lock has since moved: the ruling's recorded reason was to keep the lock's one version (plan § Open rulings 2), and `uv.lock` now pins 13.0.0, so the wheel is built for the lock's version · rewritten 2026-11-15: was "the phone closure needs Pillow on both targets and no Pillow release ships an Android wheel, so the Android phone bundle cannot finish (iOS has a wheel)" · seen live: PyPI's file list for Pillow 12.1.1 through 13.0.0 holds no Android wheel (probed 2026-11-15) · read in code, not reproduced: the row and `.github/workflows/fork-pillow-android-wheel.yml` named 12.3.0 as the lock's pin, but `uv.lock` pins 13.0.0 (the security override in `pyproject.toml`, which replaces every Pillow requirement and so would replace an Android URL pin too); the workflow has never run (0 runs), checks neither download against a pinned hash, and its first run would publish a release it then refuses to replace · done when: the workflow reads the version and sdist hash from `uv.lock`, builds an arm64 wheel and an x86_64 wheel that is imported on an emulator, a published fork release holds both, and `pyproject.toml` pins them for Android by URL with their hashes in `uv.lock`, the override scoped to every other platform · moved 2026-11-15 (w1115p-phone): from `TASK-MOBILE-STORE-RELEASE` to Eternia's `TASK-PHONE-HARNESS` — the owner reopened the phone track ("yes go ahead with what this cloud session can do and claim them") · handoff 2026-11-15: w1115p-phone rewrote the workflow on branch `ccr-1aad3a0d-a3ce2x` (commits 755101bc, c8944382: version and sdist hash read from `uv.lock`, an arm64 and an emulator-tested x86_64 wheel, 16 KB alignment checked, publishing off by default) and could not run it — the dispatch was refused, "Actions has been disabled for this repository" (seen live), which is also why the workflow shows 0 runs; this session cannot build it locally either (no Android NDK, and its network refuses the SDK host). Once it can run: dispatch with publish off, pin the libjpeg-turbo hash it prints, dispatch with publish on, then pin both assets in `pyproject.toml` with the Pillow override scoped off Android · DECISION 2026-11-15: GitHub Actions is switched off for the hermes-agent repository, so the Android image-library build cannot run there — turn Actions on for this repository, or build the wheel somewhere else? · Recommend: turn Actions on and leave every workflow but this manually started one disabled, so nothing inherited from upstream starts running; the other choice is to move the build to Eternia's repository, which splits one dependency's build from the lock that pins it

### Filed on arrival — 2026-10-21 (lane w1021j-bundle, branch `w1021j/bundle`)

- **`RT-BUNDLED-PHONE-POOL` — The Android phone bundle is packaged and verified the way the iPhone one already is** · group: phone-harness · fork / `scripts/bundle_profile_package.py` · plan `docs/agent-runtime-harness/planned/bundled-phone-pool-2026-10-22.md` S5 · rewritten 2026-11-15: was "the packager's pool installs the whole uv export for a phone target, so `--profile bundled-phone` never reaches verify" · read in code, not reproduced: the plan's S1–S4 are in the tree (`agent_runtime/bundle_profiles/manifest.py::PoolScope`, `pool: closure` in the phone profile, `scripts/bundle_profile_package.py::pool_selection`, `--seed-site`), so the old title's defect is gone; what is left is S5's Android receipt, which needs the Pillow wheel · done when: `--profile bundled-phone --target android_arm64` reaches `verify: 0 problem(s)` and the receipt is recorded · moved 2026-11-15 (w1115p-phone): from `TASK-MOBILE-STORE-RELEASE` to Eternia's `TASK-PHONE-HARNESS` · BLOCKED 2026-11-15: another lane — `RT-PHONE-PILLOW-ANDROID`: the Android pool cannot resolve Pillow until the wheel is pinned
- **`RT-PHONE-EMULATOR-TARGETS` — The phone bundle can be built for Android emulators and the iPhone simulator, so it can be tried without a physical phone** · group: phone-harness · fork / `scripts/bundles/targets.py::TARGETS`, `agent_runtime/bundle_profiles/manifest.py::PACKAGING_TARGETS` · read in code, not reproduced: the only phone targets are `android_arm64` and `ios_arm64` (device); the emulator on the x86_64 CI runner needs an x86_64 bundle and the simulator needs its own binaries, so neither can load the bundle, though `uv.lock` already carries simulator wheels for Pillow · these targets are for QA only and are marked not-shipped where they are declared · done when: `--profile bundled-phone` reaches `verify: 0 problem(s)` for an Android x86_64 target and an iOS simulator target, and a test reds if either is ever listed as shipped · the iOS simulator half can start now; the Android half needs the x86_64 wheel `RT-PHONE-PILLOW-ANDROID` publishes · READY 2026-11-15 · reviewed 2026-11-15 w1115p.1
- **`RT-PHONE-HISTORY-PROTECTION-CLASS` — Choose how strongly an iPhone locks away chat history: fully while the screen is locked, or only until the phone is first unlocked** · group: phone-harness · fork / `agent_runtime/host_store/binding.py` (the `protect_history_dir` contract) · read in code, not reproduced: the owner's 2026-09-30 ruling says Hermes seals nothing and the OS protects the folder, but not at which class; the docstring names `NSFileProtectionComplete`, under which the history is unreadable about ten seconds after lock, while `hermes_state.py` (upstream's) keeps pooled connections open and has threads that write outside any turn, logs share the folder, and the spec plans image sheets that run under OS background tasks · guess: a voice call is also expected to continue with the screen locked — the iOS app declares no background mode and Eternia's `MC-PHONE-VOICE-CAPABILITY` asks it as an open question · no phone was used · DECISION 2026-11-15: should the iPhone protect chat history completely while locked — so no agent work, call or image sheet survives the screen locking, and every lock needs the store closed and reopened — or only until the first unlock after a restart? · Recommend: until first unlock, with the backup exclusion kept — the stricter class needs a close-and-reopen protocol through upstream's store on every lock, and one of Eternia's two secret stores already sits at first unlock (`EterniaLauncher/lib/core/services/secure_storage_options.dart`; which one the phone port uses is not chosen), so history would be no weaker than sign-ins kept there · reviewed 2026-11-15 w1115p.1
- **`RT-PHONE-TLS-TRUST-UNPROVEN` — Nobody has shown that the agent engine on a phone can verify the websites and providers it connects to** · group: phone-harness · fork / `agent/ssl_verify.py::install_truststore` · read in code, not reproduced: TLS trust is pointed at the OS store through the `truststore` library, which sends every OS that is not Windows or macOS to its OpenSSL arm (read in pip's vendored copy, not the locked version), and that arm looks for OpenSSL's default paths or a short list of Linux certificate files; `certifi` is in the phone closure but nothing selects it · guess: none of those files exists on a phone, so the trust store is empty and every HTTPS call is refused · guess: the fix is to point `SSL_CERT_FILE` at certifi's bundle under the phone profile · done when: an HTTPS request to a provider succeeds and one to a host with an untrusted certificate is refused, on an Android emulator and an iOS simulator, with the phone profile · BLOCKED 2026-11-15: another lane — `RT-PHONE-EMULATOR-TARGETS`: nothing can run the phone bundle to try it until an emulator target exists · reviewed 2026-11-15 w1115p.1
- **`RT-PHONE-REALM-SYNC-BACKEND-UNCHOSEN` — Realms cannot sync on a phone until something replaces the git program phones do not have** · group: phone-harness · fork / the `realm_sync` seam · read in code, not reproduced: `EterniaLauncher/docs/embedded_hermes/subsystems/SPEC_2026-09-28.md` §4.1 says realm sync needs a git replacement, dulwich or an HTTP API, and chooses neither; neither is among the 28 distributions of the phone closure (`docs/agent-runtime-harness/planned/bundled-phone-pool-2026-10-22.md` §1.2) · done when: a plan picks the backend, says what it adds to the phone closure, and realm sync runs under the phone profile without a git binary · NEEDS PLAN 2026-11-15: a pure-Python git library inside the closure, or the realm host's HTTP API with no git on the device · reviewed 2026-11-15 w1115p.1

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

- **`RT-POSIX-TURNS-SERIALIZE-BEHIND` — POSIX turns still serialize behind one process lock: the fork writes `HOME` per profile turn because upstream's in-process `expanduser`/`Path.home()` readers have no context hook** · group: windows-handoffs · upstream door (run-serialization decision 3) · `agent_runtime/profile_context.py::persona_profile_context` (the `HOME` write and its pinned-readers comment) · draft the one upstream door for a context-aware home hook (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files); once it lands, delete `_PROCESS_HOME_LOCK` on the h3-runser branch and POSIX gets per-root turns like Windows · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-09: owner triage — Mac/Linux perf; waits on upstream; until the owner reopens it · no fork-owned caller to memo (the readers are upstream) · handoff 2026-11-12: narrowed by `RT-NEW-TURN-WAITS-ON-ANOTHER-AGENTS-MODEL-CALL` (lane w1112b-hm-turn4) — `_PROCESS_HOME_LOCK` is gone; `agent_runtime/profile_runner/workdir.py::_ProcessHomeGate` lets runs that want the same `HOME` hold it together, so on a host (no profile has a `home/`, nothing is written) turns of different chat roots run side by side on POSIX too; what is left for the upstream door is only runs whose profiles carry DIFFERENT `home/` directories, which still take turns

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

- **`RT-ALWAYS-HARNESS-SKILLS-PAID` — The always-on harness skills are paid per turn through `skill_view` instead of once in the cached prefix: Amelia turn `agent-chat-send-db7a2d34` (2026-10-08) read `harness-dev-delivery` (13.7 KB) and `harness-runtime-model` (18 KB, frontmatter `load_policy: required_preload`) by tool, and the relay receipt shows `required_preload_skills: []` — `required_preload_skill_ids` filters the persona's OWN assigned identifiers by surface, and nothing is assigned, so the mechanism never fires. Owner ruling owed: which skills each harness persona preloads, then assign them (persona config, not code) and compress their bodies to short operational rules per the 2026-10-08 plan; a preloaded skill `skill_view` re-reads should answer "already in your prompt" cheaply.** · group: windows-handoffs · fork / `agent_runtime/mission_chat_turn_context.py::_required_preload_skills`, `agent_runtime/skill_resolution.required_preload_skill_ids`, persona skill assignment · filed by lane host-guidance 2026-10-08 · RULED 2026-10-10 owner: skills load on demand by default; each persona preloads at most its top one or two · RULED 2026-10-15 owner: Launcher Dev and Backend Dev preload the delivery contract; Neko and Base preload the runtime model; everything else loads on demand · the preload half landed 6d7938ce1ab; the "preloaded skill_view re-read answers cheaply" half is upstream `tools/skills_tool.py` · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-09: owner triage — Our half landed; remainder is upstream cost tweak; until the owner reopens it · the fork does not own `skill_view`'s caller (the model calls the tool); preload half on main 6d7938ce1ab
- 2026-10-08 evidence for the GenUI selection row below: with the eager pair delivered (runtime `94043a1a42`, listing `26 core/visible tools kept, 18 deferred` at 13:23:09), the first-response path still did not call `launcher_generated_list` directly — the turn loaded five skills (`launcher-generated-ui`, `harness-dev-delivery`, `harness-continuity`, `harness-runtime-model`, one not found; ~44 KB of skill text), searched, described, queried the roster, took the wrong door, then relayed to a peer and burned the rest of the 240 s on the deadlock row above. The profile-local skill is a second copy of the tool contract (it says "discover with `launcher_generated_list`" without saying it is direct); F2 of the launcher audit stands.


### Filed on arrival — 2026-10-07 (GenUI selection audit)




- **`RT-VERIFY-IMPROVE-FIRST-RESPONSE` — Verify and improve first-response selection of the Launcher generated-content tools for ordinary comparison requests; the A/B eval is built (`evals/genui_first_response_ab.py`, b05ccafe29)** · group: windows-handoffs · fork / tool selection · plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §3 · RULED 2026-10-19: owner — arms switched by QA build · RULED 2026-10-25: owner — an agent runs this sitting on this PC · live phase 2026-10-25: a launcher_qa lane runs it — two QA builds (arm A before launcher 469e500730, arm B at it), 15 turns × 2 agents × each QA provider per arm; it does not touch the owner's serve (`docs/agent-runtime-harness/planned/live-sitting-results-2026-10-25.md`) · READY 2026-11-12 · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, reopen them" — the A/B test exists (`evals/genui_first_response_ab.py`); it costs provider turns · was dEFERRED 2026-11-09: owner triage — Evaluation of a nice-to-have behavior; until the owner reopens it · handoff 2026-11-12: owner — the Linux box takes this; branch wave/w1112c-hmtruth; left: all of it, nothing started — the live A/B (arm A, arm B) over launcher_qa; the owner keeps ONE QA build of HEAD (11-11), so arm A on a build before launcher 469e500730 needs a plan · moved 2026-11-12 (w1112b-ctt-hm): from console-transcript-truthful.p10-agent — owner rule 2026-11-12 ("any fine tuning stuff like that and performance should go into the windows task"): an A/B of which tool a model picks first is tuning, not a defect in the chat · handoff 2026-11-12 (w1112b-ctt-hm): not run on Linux — it costs real-model turns (15 turns × 2 agents × each QA provider × 2 arms) and this wave runs the fixture model only; arm A needs a QA build before Eternia 469e500730 (a throwaway local branch at that commit, built by `launch_or_attach` from a tree checked out there) · REQUIRES windows, linux · **TAKEN 2026-11-15 codex-win-hermes-handoffs on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes-handoffs**

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

- **`RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN` — Telegram can run on upstream's connector as a second option, off by default, so the owner can try it with a real bot before anything is switched** · group: remote-parity-and-two-machine-proof.p10-messaging · fork / messaging · filed 2026-11-14 at the owner's ask in chat ("if so then just switch it", then "i need a proper audit") · seen in a test: on branch `audit/upstream-telegram-switch` (62920f2b68) the upstream Telegram adapter, connected over HTTP to a local stand-in for the Bot API with no GatewayRunner, did what the fork's own transport does — queued turn on the persona's one root, real reply, 4,096 split, `/persona`, forum topics, approval cards — once five defects were fixed in the shim: a stranger's media fetched before refusal, replies sent silently, upstream's command menu pushed to the bot, the bot token logged at INFO, message text logged at DEBUG; note `docs/agent-runtime-harness/evidence/upstream-adapter-as-transport-2026-11-14/SWITCH_AUDIT.md` · not shown: real Telegram, and two upstream Windows tests of stuck-poll recovery fail on this box (cause not investigated) · to build: a harness setting that picks the transport per token (never both: one poller per bot), the shim and its Telegram subclass from the branch, the token from `agent_runtime/messaging/credentials.py::bot_token`, the Allow list fed from the shim's refusals with the display name it lacks today, the press handler registered through upstream's plugin handler factory so a rebuilt application keeps it · done when: with the setting on, the owner's real bot answers on a phone (it buzzes, the reply threads, a card's buttons work) for a day of ordinary use, and with it off nothing about today's Telegram changes · related: `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS`, `FORK-PARALLEL-MESSAGING-GATEWAY` · folded 2026-11-15 (w1115e-rr2, owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"): `FORK-PARALLEL-MESSAGING-GATEWAY` (its question — keep the fork's own gateway beside upstream's — was answered by the owner's ruling to reuse the upstream connectors; owner 2026-10-20 "sounds good persona system for our custom gateway is the way") and `RT-MESSAGING-PLATFORMS-TELEGRAM` (the fork Telegram transport is on main, off by default; its remainder is this row's opt-in trial; owner triage 2026-11-09 "New optional channel; off by default") are closed into this row: after the opt-in trial, retire the fork transport in `agent_runtime/messaging/` · DEFERRED 2026-11-15: owner — "unclaim that telegram row for now" (the real-bot trial is off the owner's list; the opt-in stays shipped, off by default) · handoff 2026-11-14 (msg-live-note): the live check ran against real Telegram on a throwaway bot, branch audit/upstream-telegram-switch 790202d002, script scripts/live_telegram_check.py there (reported by the owner, not seen by the lane): the bot reached step 6 of 6, so connect, the threaded reply, the formatted reply, the split long reply, the approval card press and edit, and a photo all went through real Telegram; asked whether the phone buzzed, the reply threaded, the formatting rendered, line 130 arrived and the card changed, the owner answered yes; the console summary was not pasted and the stranger step is not confirmed; not covered by it: a day of ordinary use, and the two failing upstream Windows stuck-poll tests · handoff 2026-11-14 (msg-opt-in): built and on main a682b32b82 (seen in a test): the setting messaging_telegram_transport picks fork (default) or upstream in the serve lane, a changed setting stops the running connector before the other starts, the operator list is asked at the adapter's intake with the sender's name, the card press handler is registered on every application the adapter builds; 111 messaging tests pass, each new check watched red; left is only the owner's own bot: turn it on with hermes config set plugins.entries.eternia-harness.settings.messaging_telegram_transport upstream on the machine whose Harness holds the bot token, use it from a phone for a day, and switch back with fork if anything is off; the builder could not do this read — it needs the owner's bot token, phone and Telegram account
- **`RT-MACOS-LINUX-BUNDLED-DESKTOP` — macOS / Linux bundled desktop ships no OS secure store: `keyring` (Keychain / Secret Service) is not in the bundled-desktop packaging, so `auth.os_secure_store: true` refuses to start there — add it to those targets' packaging when they exist** · group: signed-installs · `fork` · evidence: `agent_runtime/host_store/desktop.py::admitted_keyring_backend` · filed 2026-09-28 (lane w5-hdpapi) · `keyring` is in neither pyproject.toml nor uv.lock; add it as an optional extra + networked `uv lock` + bundled-desktop.yaml darwin/linux extras in the change that first builds those targets · RULED 2026-10-16: owner — "add keyring when mac/linux builds exist, not now"; prove it at the Mac sitting · RULED 2026-11-10: owner — split: the Mac half (Keychain `keyring` extra + proving `admitted_keyring_backend` on a Mac) moves to the Mac sitting task `TASK-MISSION-CONTROL-ON-MAC` (Eternia, "…move the mac to a mac sitting task"); the Linux half (Secret Service in a Linux bundled target) stays in this task · DEFERRED 2026-10-18: `bundled-desktop.yaml` declares no darwin/linux target yet, so there is no packaging to add it to; the change that adds the first such target adds `keyring` (optional extra + networked `uv lock` + that target's extras) and proves `admitted_keyring_backend` at the Mac sitting — owner 2026-10-16 · moved 2026-11-12 (triage w1112b): from `TASK-EMBEDDED-HERMES` to `TASK-SIGNED-INSTALLS` — both halves wait on a macOS or Linux bundled-desktop target, which that task builds (Eternia `COMP-HERMES-POSIX-BUNDLE`); owner 2026-11-12 kept it deferred (deferred-task review, batch 3: "the other nine stay deferred (phones, release, Linux packaging)") and then "undefer everything in the open ready tasks being worked on so they can complete"; the 2026-11-10 split named a Mac row that was never filed, so the row keeps both halves

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

- **`RT-DISCUSSION-TYPED-REFUSAL` — Discussion Tables (hermes half): D3 closes the typed-refusal lane by subclass, leaving three families on the raw-text boundary** · group: discussion-rooms-reliability · `hermes` · `agent_runtime/discussions/rpc.py:90-105`: `DiscussionPolicyError` (the base), the `DriverStateError` family (`gateway/hosted_room_driver.py:104-111`) and checkpoint `RuntimeError`s (`gateway/hosted_room_policy_checkpoint.py:183,291,298`) still reach `serve_rpc` as `handler_failed` with `f\"handler error: {exc}\"`. Latent — not live-reachable today. Same review @ `20b148694e`. · the policy base and `DriverStateError` family are typed in d151314bcfe; the checkpoint's three plain `RuntimeError`s are raised by upstream `gateway/hosted_room_policy_checkpoint.py`, so typing them is an upstream door (a typed subclass) · READY 2026-11-15 · unblocked 2026-11-15: w1115e-rr2, owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure": the refusal mapping at `agent_runtime/discussions/rpc.py:90-105` is fork-owned, so the fork route needs no upstream PR (deep sweep 2026-11-15 §D); try the fork seam first (was DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs)

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

- **`RT-WINDOWS-ELEVATED-GATEWAY-KEEPS-PROFILE` — Elevating a Windows gateway install or uninstall keeps the selected profile** · group: windows-handoffs-followups · seen in an isolated Windows probe 2026-11-15 by codex-win-hermes on `8179f588ed`: a default-scoped install captured `gateway install --elevated-handoff` at ShellExecuteW; the real CLI bootstrap of those arguments selected the saved `sticky` profile, no actual elevation performed · cause read in code: `gateway_windows._current_profile_cli_args` omits the default selector and both install and uninstall use `_launch_elevated_gateway_command` before supervision starts · done when: the elevated child's CLI preserves explicit default and named selections with a different saved active profile · NEW 2026-11-15 · READY 2026-11-15 · REQUIRES windows

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

- **`RT-RECHECK-AFTER-THE-PRE-LAUNCH-HERMES-UPDATE` — After the pre-launch Hermes update, 33 old findings in upstream code are checked once more and only the ones still true come back** · group: upstream-footprint-ledger · upstream-owned code the fork cannot edit (§ Upstream-owned) · filed 2026-11-15 by w1115e-rr2 from the deep sweep 2026-11-15 §H-B3 (owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure") · read in git, not re-run: the update (merge-base 3b42157858 to `upstream/main`) rewrites the files these rows cite — `hermes_cli/gateway.py` +30/−123, `hermes_cli/gateway_windows.py` +96/−27, `hermes_cli/config.py` +64/−235, `agent/ssl_verify.py` +74, `tools/delegate_tool_config.py` +41, `agent/prompt_builder.py` +60/−25, `tui_gateway/host_supervisor.py` +41/−15, `hermes_state.py` +31/−21, `gateway/hosted_room_policy_checkpoint.py` +30 · architecture: no fork edit and no upstream edit — a re-check only; each survivor is filed as its own row by the layer it lands in (a fork seam per the fork-route-first rule, or an upstream issue); each row's full text is in `Harness_Brain/80 — Archive/Queues/` (runtime-queue-2026-11.md, fork-hygiene-queue-2026-11.md) · checklist (each row closed into this one, its owner quote kept): `RT-REQUEST-BUILT-RESOLVES-WEB`: re-time the per-request web-search provider lookup in `agent/transports/codex.py::_alias_wire_tools` (owner triage 2026-11-09 "Small latency; owner ruled wait on upstream"); `RT-SEND-PREP-H7-UNRESOLVED`: re-split the 47–50 ms warm request build in `ResponsesApiTransport.build_kwargs` ("Small latency measurement; waits on upstream"); `RT-SEND-PREP-H2-H6`: re-measure skill preload and package stamps on a skill-heavy persona; it did not reproduce on the fresh route ("Small latency; waits on upstream"); `RT-SKILL-CATALOG-FRONTMATTER`: re-time `tools/skills_tool._skill_catalog` frontmatter parsing and the kanban gate's 1.3 s first import ("Small performance gain; upstream-owned"); `RT-DASHBOARD-AUTH-SCRYPT-IMPORT`: check `plugins/dashboard_auth/basic` still computes its scrypt dummy hash (~0.2 s) at import ("Test-speed issue only; no user impact"); `RT-PROCESS-STARTUP-UPSTREAM-WORK`: re-time the provider discovery (~1.6 s) that importing `hermes_cli.config` runs for read-only verbs ("Noticeable but not broken; depends on upstream accepting PRs"); `RT-I18N-BUNDLED-PER-HOME`: check `agent/i18n.py::_load_catalog` still re-reads the bundled translations per profile ("Performance mostly felt in tests; upstream-owned"); `RT-CONFIG-NOFILE-REBUILD`: re-time a profile with no `config.yaml` through `hermes_cli/config.py::_load_config_impl` (config.py +64/−235 in the update; 72.5 s vs 41.2 s test file) ("Performance tweak; upstream-owned, workaround is adding a file"); `RT-AUX-KEY-CHAIN-LOAD-CONFIG`: count `load_config()` calls per `agent/auxiliary_client._resolve_api_key_provider` auto resolution (~48 providers) ("Performance gain only; upstream-owned"); `RT-NATIVE-WORKER-UPSTREAM-BOOT`: re-time a native worker's ~5 s to first reply: `tui_gateway.server` import, first agent build, first `model.options` ("Felt latency but depends entirely on upstream work"); `RT-CHECKPOINT-PM-ENSURE`: check `tools/checkpoint_manager._run_git` still calls `pm.client.ensure` on every git call (~11 ms each) ("Speed-up mostly felt in test runs; upstream owns the fix"); `RT-DELEGATION-KNOB-ENV-DEAD`: check `DELEGATION_MAX_CONCURRENT_CHILDREN` / `DELEGATION_CHILD_TIMEOUT_SECONDS` still lose to DEFAULT_CONFIG in `tools/delegate_tool_config.py::_knob` (+41 in the update) ("Settings work through config instead; minor"); `RT-CONTEXT-MANIFEST-WITHIN-KIND`: check `/context` still marks every candidate of a kind loaded while `agent/prompt_builder.py` (+60/−25) loads only the nearest ("Misleading display in a power-user command; upstream-blocked"); `RT-HERMES-STATE-SCHEMA-STALE`: check Windows chat search recovers by itself after its search index is damaged (`hermes_state.py` +31/−21) ("Real but rare; owner already ruled to wait for upstream"); `RT-SPARK-PRO-USAGE-BUCKET`: check `gpt-5.3-codex-spark` on the ChatGPT-account Codex route; `hermes_cli/codex_models.py` already lists it ("Model is already safely disabled; adding it is a nice-to-have"); `FORK-WINDOWS-SIGNAL-SAFETY-CARRY`: check whether upstream now ships an equal Windows Ctrl+C safety fix; if it does, drop the carry ("Reminder only; nothing to do until upstream changes"); `RT-GATEWAY-START-MANAGED-PYTHON`: check `hermes --profile <name> gateway start` from the managed venv (`hermes_cli/gateway.py` +30/−123) (owner 2026-11-05 "thats upstreams gateway stuff im going to build my own external gateways"); `FH-FLAKE-API-ADMISSION-OFF-LOOP-UNDER-LOAD`: re-run `tests/gateway/test_api_admission_off_loop.py` (owner triage 2026-11-09 "Test-only timing flake; the product itself is not shown broken"); `FH-FLAKE-SESSION-AUTHORITY-OWNER-KILL-UNDER-LOAD`: re-run `tests/gateway/test_session_authority.py` (same triage); `FH-FLAKE-BROWSE-SCHEMA-DRIFT-CONCURRENT-UNDER-LOAD`: re-run `tests/hermes_cli/test_browse_schema_drift.py` (same triage); `FH-FLAKE-SCHEDULER-PROVIDER-RECOVERY-THREAD`: re-run `tests/cron/test_scheduler_provider.py` (same triage); `FH-FLAKE-API-PENDING-DAEMON-DEADLINE`: re-run `tests/gateway/test_api_pending_daemon.py` (same triage); `FH-FLAKE-EXECUTE-CODE-GATE-LOOP-TICK`: re-run `tests/gateway/test_local_turn_origin_execute_code_gate.py` (same triage); `FH-FLAKE-LOCAL-SESSION-APPROVAL-CHILD`: re-run `tests/gateway/test_local_session.py` (same triage); `FH-FLAKE-SHARED-BUSY-RECEIVE-DEADLINE`: re-run `tests/gateway/test_shared_busy_receive_loop.py`, an upstream file the fork edits (same triage); `FH-FLAKE-WEBHOOK-AUTHORITY-CHILD`: re-run `tests/gateway/test_webhook_authority.py`, an upstream file the fork edits (same triage); `FH-FLAKE-SESSION-CONFIG-PROJECTION-PROVIDERS`: re-run `tests/gateway/test_session_config_projection.py` ("Only seen under heavy test load; no user report"); `FH-FLAKE-CONNECTOR-OPERATION-RPC-NO-REPLY`: re-run `tests/tui_gateway/test_connector_operation_rpc.py` (same triage); `FH-FLAKE-PM-STREAMING-DEADLINE-UNDER-LOAD`: re-run `tests/pm/test_environment_build.py` (same triage); `RT-FLAKE-UPDATE-EXISTING-MAIN-SWITCH-HANDOFF`: re-run `tests/hermes_cli/test_update_existing_branch_baseline.py`, on a quiet box first (deferred 2026-11-10 into the load-flakes batch); `RT-UPSTREAM-TEST-RACES-TWO`: re-run `tests/tools/test_browser_eval_supervisor_path.py` and `tests/agent/test_run_agent.py::TestExecuteToolCalls` (owner 2026-10-16 "pr branches should remain idle"); `FH-UPSTREAM-TESTS-STRIP-SYSTEMROOT`: re-run `tests/hermes_cli/test_update_restore_authority.py` and `tests/hermes_cli/test_runtime_maintenance_exclusion.py` on Windows ("Upstream test bug; product unaffected"); `FORK-QUALIFY-NATIVE-WINDOWS-MSYS`: re-check MSYS foreground-child cleanup on native Windows ("Rare leftover processes; upstream-owned; needs report first") · done when: the update has landed; the 16 test files are re-run at -j 24 on a busy box, the 11 latencies re-measured once (as Eternia `TASK-WINDOWS-HANDOFFS` rows), the 6 behaviours re-read; only what still fails is filed, and this row closes · NEW 2026-11-15 · awaits review · DEFERRED 2026-11-15: waiting on the pre-launch hermes update; until it lands

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
- **`RT-NATIVE-HISTORY-REREAD` — Native history is re-read from SessionDB and re-filtered against the turn ledger on every turn though the resident actor holds the same lineage; now measured as `context_native_history_ms`** · group: windows-handoffs · fork / `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_build_context` · decide whether a reused actor whose `native_revision` is unchanged may hand its own messages to the turn (SessionDB stays the authority, the revision is the guard) · evidence: turn `15c73e0c` had 168 ms of `context_built` unattributed (1035 − preload 858 − hud 7 − signature 2) · RULED 2026-10-10 owner: yes: a reused actor with an unchanged `native_revision` hands its messages to the turn; SessionDB stays the authority, the revision the guard · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` approved by owner 2026-10-15; S1–S3 built on `build/h1-lineage` (the turn hand-off is S3, 52.6 → 6.4 ms on an 800-message lineage); S4, the upstream door draft, waits on the orchestrator sequencing it with Phase B wave 2 · S1–S3 landed (fc3350d3044; `build/h1-lineage` has no unlanded patch) · moved 2026-11-15 from `agent-start-up-cost.sessiondb-lineage-stamp` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-09: owner triage — User-visible win already shipped; leftover is upstream paperwork; until the owner reopens it · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` § S4

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
- **`RT-SCHEDULE-SYNC-AND-KNOB` — Agent schedules stay in step between your two machines, like the rest of your agent setup** · rewritten 2026-11-14 (w1114a-boardtitles, plain-English title rule): was "`store/schedules/` is not a realm-sync family (plan §2.3 says key-wise like `workspace_slots`); the knob half LANDED (lane w6-misc: root config `agent_runtime.scheduler.max_parallel`, read each tick)" · group: remote-parity-and-two-machine-proof · fork / scheduling · `agent_runtime/work_store/schedule_store.py`, `agent_runtime/realm_sync/document_family.py`; plan `docs/agent-runtime-harness/archive/dispatcher-and-libraries-2026-10-18.md` §2.3 · RULED 2026-10-18: owner — schedules stay local to the machine that armed them for now; the realm-sync family waits for a design of delete propagation and per-fire publish · DEFERRED 2026-10-18: owner — schedules local per machine until the sync design is planned

## Filed on arrival — 2026-10-19 (launcher wave w1020)

- **`RT-WIN-CONSOLE-FLASH-CODEX-SWITCH` — A Windows console window flashes when the Agent Console switches a chat to openai-codex** · group: provider-api-key-and-usage-source · owner 2026-10-19 13:04:41Z (launcher `[MissionModelPick]` chosen=openai-codex/gpt-6-sol): the launcher spawns nothing on that path (RPC-only; its serve child is started detached, with no console), so a console child of hermes opened it. Candidate: `agent/transports/codex_app_server.py::check_codex_binary` runs `codex --version` without `windows_hide_flags()` while the Popen beside it hides; audit the openai-codex select / models / first-turn paths for subprocesses spawned without CREATE_NO_WINDOW and pin one with a Windows test · launcher `MC-PROVIDER-SWITCH-LOCKS-PICKER` waits on it (filed by launcher lane w1020-console) · BLOCKED 2026-11-12: owner sitting — one provider sitting: the owner signs in to their own provider accounts on Windows and watches one switch to Codex for a console window flash (probably fixed by 620de2c049) · reopened 2026-11-12: owner — deferred-task review, batch 2: "Yes, as recommended" · was dEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: switch a chat to openai-codex on the Windows box and watch for the flash (check_codex_binary now hides its console, 620de2c049)

## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)


## Filed on arrival — 2026-10-20 (launcher plan: edition switch and the shared namespace store, `EterniaLauncher` `9185222120`)


## Filed on arrival — 2026-10-22 (launcher session, owner report from a Neko Mission Lead turn)

- **`RT-HEADER-SAYS-STANDING-BY-AFTER-A-RUNTIME-STARTED-TURN-BEGAN` — The agent header says a reply is running as soon as the agent starts one by itself** · group: windows-handoffs · `agent_runtime/chat_turn_presence.py` · `hermes_cli/harness_parts/persona/chat_turn_commit/run.py` · found 2026-11-12 (Eternia lane w1112b-turn6, `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-12/TASK-TURN-CLEANUP/w1112b-turn6/README.md`) · seen live: ONE sighting, not timed — 5 s after the helper-result turn of Base started (14:25:30Z) its console header still read "Standing by" (14:25:35Z); a minute later it read "Turn running · 50 s"; the box was at load about 30 · read in code, not reproduced (w1112b-hm-turn5): every turn through the mission-chat door, whoever started it, publishes its start from `_write_ahead` (`presence.publish_started`) once the journal record persisted, with no gate on `stream` or `requested_by` — so the runtime does not skip the start of a runtime-started turn; not read: when a forged turn reaches its write-ahead after the delivery drain picks it (the 14:25:30Z clock may be the drain, not the write-ahead), how long the hub takes to build the frame at load, and what the header reads (the presence row or the state of its own send) · guess: a late frame under load, or a header that follows only turns the console sent · handoff 2026-11-12 (w1112b-hm-turn5): first step is an Eternia live read — start a helper, note the `write_ahead` instant in the turn journal `phases`, the instant the `chat_turn` row first appears in a `running_work` frame, and the instant the header changes; the layer that owns the gap owns the fix (move this row to the Eternia queue if it is the header) · done when: the three instants are read once on a quiet box and either the gap is under a second or the owning layer has a row that says why · READY 2026-11-12 · handoff 2026-11-12 (w1112b-hm-latesteer): first step read by Eternia lane w1112b-turn7 — not reproduced on nekwo-ubuntu24 (load average 63, not quiet; hermes 45e66e82a1, client 27de4bea6d): three runtime-started turns with the console open and the display recorded at 5–10 fps — a forged `bg-completion-…` turn on Base (write-ahead 16:20:26.44Z → header "Turn running" 1.1–1.3 s later, the composer strip in the same frame), a `steer-next-…` turn on QA Agent B (1.6–1.8 s) and another from "Standing by" (2.2–2.4 s; the running strip came 0.6 s AFTER the header); the header never trailed the other on-screen sign of the row and no Eternia row was filed. Not read: the instant the `chat_turn` row is first in a `running_work` frame on the wire — neither the serve nor the client keeps a clock a lane can read, so the 1–2.4 s is not split between the runtime building the frame and the client applying it. Next step, cheap and not built here: a frame-sent timestamp on the serve log line that pushes a `running_work` frame (or `measured_at` surfaced through the client's runtime state) would split it; then repeat the read on a quiet box. Evidence: `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-12/MC-CONSOLE-WORK-TURN-FOLLOW-UP-IS-QUEUED-NOT-STEERED/w1112b-turn7/README.md` (strips 06, 07, 08) · handoff 2026-11-12 (w1112b-hm-turnfu): nothing to build in hermes (read in code 2026-11-12): every running_work frame the serve sends already carries generated_at, stamped right after the section is read (agent_runtime/stream/frames.py running_work_frame; the overlay and the sequenced section frame alike) — the frame-sent timestamp the last handoff asked for exists. What no lane can read is the client side: Eternia keeps only the NEWEST applied frame's lag (lastFrameLagMs = applied-at minus generated_at, EterniaLauncher lib/core/services/hermes/runtime/data/mission_transport_stats.dart), not the lag of the frame that first listed a turn's row, so turn7's 1–2.4 s still cannot be split. Next step is an Eternia read: surface, through get_runtime_state, the generated_at and applied-at of the running_work frame (or core) that FIRST lists a chat_turn row, then repeat turn7's three reads on a quiet box (seen live, side note, this lane's sitting at hermes ecc419e1eb: while an until-done run checked a pass, the header read 'Standing by' for the whole 183 s while Activity listed the run's chat_turn row Running — relayed to EterniaLauncher as its own finding). Not reproduced here: this lane drove no runtime-started turn for this row's three instants · handoff 2026-11-12 (w1112b-turnapp): Eternia read built (MC-RUNNING-TURN-ARRIVAL-NOT-READABLE, b09608e852: get_runtime_state.running_work_first_seen) and read live on nekwo-ubuntu24 (not quiet; hermes 561ed6242c, fixture, QA Agent B, until-done run): pass row started 19:26:27.506Z, first frame generated 27.895Z, applied 27.910Z; checking row started 19:29:27.708Z, frame 28.154Z, applied 28.196Z — so ~0.4 s is the runtime putting the start on a frame and 15-42 ms the app applying it; the header-change instant was not timed (screenshots only). Left: one read on a quiet box with a recorded display for the header instant · handoff 2026-11-12 (w1112b-turnapp2): moved from turn-cleanup-followups to windows-handoffs (Eternia `TASK-WINDOWS-HANDOFFS`) under the owner's rule 2026-11-12 (timing and fine-tuning go to the Windows task; it never holds a feature task open) — the feature works (the header reads Turn running for a runtime-started turn, read live by w1112b-turn7 and w1112b-turnapp, ~0.4 s runtime-to-frame and 15–42 ms frame-to-applied measured); all that is left is a TIMING read: on a quiet box, record the display while a runtime-started turn begins and time the header change against `get_runtime_state.running_work_first_seen` — this Linux box runs at load 30–60 under the wave, so it cannot give a quiet-box instant · REQUIRES windows · **TAKEN 2026-11-15 codex-win-hermes-handoffs on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes-handoffs**

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

- **`RT-USAGE-ANTHROPIC-UNITS-SCOPE` — Your Anthropic usage reads the right percentage, not a hundred times too high** · rewritten 2026-11-14 (w1114a-boardtitles, plain-English title rule): was "`_fetch_anthropic_account_usage` reads `/api/oauth/usage` with `_usage_windows(..., fraction=True)`, which multiplies any value ≤ 1 by 100, so if utilization already arrives as a percent a 0.5 % window shows 50 % and 1 % shows full (the fixture in `tests/agent/test_account_usage_pool_fetch.py` encodes fractions, the same unverified belief); the extra-usage credit goes out as a free-text details line, not a typed balance; and `_serialize_usage_window` drops each window's `scope`, so the client cannot tell an Opus-only cap from the account cap" · group: provider-api-key-and-usage-source · `agent/account_usage.py::_fetch_anthropic_account_usage` · `hermes_cli/harness_parts/usage/serialize.py::_serialize_usage_window` · 2026-11-02: launcher `MC-USAGE-ANTHROPIC-RESEARCH` landed `7019b2c2fb` and found the `/api/oauth/usage` units on no Anthropic page, so the units wait on one recorded payload; the `scope` half needs no units and is split out as `RT-USAGE-WINDOW-SCOPE-SERIALIZE` · DEFERRED 2026-11-09: owner — waits on deferred `MC-USAGE-ANTHROPIC-OAUTH-UNITS` (owner sittings parked 2026-11-09: "the whole tasks of them should be deffered if they aren't blocking work"); was BLOCKED 2026-11-02: launcher — `MC-USAGE-ANTHROPIC-OAUTH-UNITS` one recorded `/api/oauth/usage` payload beside Settings › Usage settles fraction vs percent and cents vs dollars · note 2026-11-12 (deferred-task review): the scope half is already done (`serialize.py`); what is left is the units and the typed balance, which wait on launcher `MC-USAGE-ANTHROPIC-OAUTH-UNITS`

## Filed on arrival — 2026-11-01 (lane w1101b-perf, the first idle-box run)


## Filed on arrival — 2026-11-02 (launcher lane w1101h-teardown)





## Optional suggestion post-call work — 2026-11-03




## Filed on arrival — 2026-11-04 (owner via Eternia: the workspace absorbs Projects; plan w1104-wsmerge)

- **`RT-EXTERNAL-GATEWAY-RETIRE-UPSTREAM` — once the owner's first gateway answers: stop the alice upstream gateway, remove its logon task, delete the shared bot token from the eight profile `.env` files (no code)** · group: remote-parity-and-two-machine-proof.external-gateway-access · `docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md` §2 D4, §5 · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: after the owner's first gateway is live



## w1108b hand-off to the Linux box — 2026-11-08


## Filed on arrival — 2026-11-08 (lane w1108b-hfh)


## Filed on arrival — 2026-11-08 (Eternia lane w1108d-mclive)


## Filed on arrival — 2026-11-09 (Eternia lane queue-grammar-at-write)


## Filed on arrival — 2026-11-09 (Eternia lane w1109a-console-live)

## Filed on arrival — 2026-11-09 (Eternia lane w1109a-console2)

## Filed on arrival — 2026-11-09 (Eternia lane w1109a-lens3)


## Filed on arrival — 2026-11-10 (Eternia lane w1110c-hmsync)

## Filed on arrival — 2026-11-10 (lane w1110c-hm3)

- **`RT-ROOM-TURN-CONNECTION-CHURN` — Discussion rooms would move between members faster if a turn did not open the room database about seventy times** · group: windows-handoffs · `agent_runtime/discussions/service.py::DiscussionService.prepare`, `gateway/hosted_room_policy_checkpoint.py`, `tui_gateway/hosted_room_driver.py` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2: after 5cd83a166db a twelve-member room still takes ~0.8 s per member turn with an instant model, CPU-bound on SQLite connection opens (~4,100 per two-round test; every op opens and closes its own connection); `prepare` runs twice per turn (the terminal publish, then the next cycle), each reading the room three times and the policy checkpoint twice; most opens are in upstream hosted-room modules (a door, never an edit); Windows also pays `tests/home_io_guard.py`'s realpath per mkdir · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-10: joins the owner-deferred speed task TASK-AGENT-START-UP-COST

## Filed on arrival — 2026-11-11 (launcher plan w1111e-manage-ws)

- **`RT-GROUP-MEMBER-FIRST-TURN-COLD-START` — A group member with turn isolation on asks its model sooner after you message the room** · group: windows-handoffs · measured 2026-11-12 by w1112a-hmtests on DESKTOP-QJ7DDV2 (moderate load, eight runs of `tests/agent_runtime/test_discussion_group_compute.py` with temporary monotonic stamps): submit → claim 0.05 s, → member worker `main` 0.6-1 s, → worker ready 1.3-2.3 s more, → `open_member` done 2-3.7 s more, → compute host `main` 1-1.4 s more, → `send` returns 1.5-2 s more, → first model request 6.2-9.6 s more; 15-17 s on a quiet box, 27 s on a busier one; the last leg (compute host to first request) is the largest · REQUIRES windows · moved 2026-11-15 from `agent-start-up-cost` (w1115e-rr2): owner 2026-11-12 — measured performance work goes to Eternia `TASK-WINDOWS-HANDOFFS`, which replaces the surfaces' speed tasks; owner 2026-11-15 "yes prioritize the ones that drop rows the most starting with launcher , do all of them that drop rows though for sure"; stays DEFERRED with its own owner quote · DEFERRED 2026-11-12: its task is deferred until the owner reopens it

## Filed on arrival — 2026-11-12 (safe local runtime restart)

- **`RT-WINDOWS-UPDATE-RESTART-DEFAULT-IDENTITY` — Updating Hermes restores the host gateway under its default identity** · group: windows-handoffs · seen 2026-11-13 by hermes-creation: canonical updates from 51014a80 through 1825fa6445 and 4d29a8936c pause the zero-turn default multiplexer but automatic Windows restart repeatedly selects sticky active profile amelia and refuses a separate poller; explicit hermes -p default gateway restart restores all eight original profiles and Telegram · cause: gateway_windows._launcher_settings uses gateway._profile_arg which returns an empty selector for the default root; detached boot follows active_profile; the later update fleet also labelled the root multiplexer amelia, classification cause not yet traced · done when: canonical Windows update preserves the root gateway identity and restores its original served profiles with one poller through existing lifecycle authority · BLOCKED 2026-11-15: owner decision — May the restart fix move three upstream watcher lines into the fallback branch, raising deleted_lines from 874 to 877 with 224 files and one heavy file unchanged? · Recommend: yes. The Windows branch uses the proved paused home once and keeps the shared watcher as the only respawn path; the candidate and eight-profile native drill receipt are on wave/codex-win-hermes at 83869ce5d3. · REQUIRES windows · handoff 2026-11-15 (codex-win-hermes): The update watcher, not the supervised launcher renderer, chose the wrong home: its Windows overlay was based on the updating CLI, and its unpinned selectorless root followed active_profile. Five Windows regressions red on 1e7d9652a5 and green on topic 8179f588ed. An isolated native Windows pause/resume restored the default and all eight profiles; the replacement default PID was the only new Telegram poller against a loopback fixture, and the fleet labelled it default. The topic waits on the footprint ruling (three base lines moved into else) and a landing; a full source/dependency swap was not exercised. · **TAKEN 2026-11-15 codex-win-hermes on MUltiversalLabsInc as maximusenglandshaban@gmail.com in codex-win-hermes**

## Filed on arrival — 2026-11-13 (lane w1112b-hm5: review batch w1112b-6 §2)

- **`RT-SLOT-SETUP-RECIPE-SCOPED-DESIGN` — Setting up a repository's dev environment (tools, keys, .env, setup commands) is designed on its own, apart from whether the slot is there** · group: slot-setup-recipe-design · RULED 2026-11-13 owner: "a workspace slot recipe should probably be its own scoped design"; today the recipe lives inside the slot declaration (`toolchain.tools`, `env_keys`, `dotenv`, recipe command steps in `agent_runtime/workspace_slot_recipe.py`) and, until `RT-SLOT-READY-IGNORES-TOOLS-AND-KEYS`, decided Ready; tools and keys vary by dev environment · read in code, not designed · done when: a plan says where a recipe lives (per slot, per workspace or per person), who it is for, whether it ever gates anything, and what Eternia's Set up shows for it · DECISION 2026-11-15: do you accept the setup recipe design's seven decisions (a recipe per slot shared with the workspace, holding every setup step, never blocking anything, with a per-computer "not needed here")? · Recommend: yes — `docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md` · reviewed 2026-11-15 w1115k.1 · handoff 2026-11-15 (w1115k-hdesign): design written (docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md, e0c2ff513c), decisions table at its top; on a yes, file its three build slices (§6) and Eternia's row (§3, verbatim there); on changes, edit the table first; two follow-up rows sit under TASK-SLOT-SETUP-RECIPE-DESIGN-FOLLOWUPS
- **`RT-SLOT-RECIPE-REVISION-ALSO-RANKS-THE-WHOLE-SLOT-RECORD` — A teammate editing a slot's setup steps and another changing the slot itself no longer overwrite each other when they sync** · group: slot-setup-recipe-design-followups · fork / workspace slots · `agent_runtime/workspace_slots.py` (`_revised`) · `agent_runtime/workspace_slots_sync.py` · read in code, not reproduced (w1115k-hdesign): `recipe.revision` is also the slot record's edit counter and the realm merge ranks the whole record by it, so the side with more recipe edits takes repo, toolchain and context too · the structural answer (the recipe as its own entry with its own counter) is `docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md` §2 · done when: two peers' documents, one with a newer recipe and one with a newer declaration, merge with both kept · NEW 2026-11-15 · BLOCKED 2026-11-15: another lane — `RT-SLOT-SETUP-RECIPE-SCOPED-DESIGN` waits on the owner's answer to the design that retires this · reviewed 2026-11-15 w1115k.2

## Filed on arrival — 2026-11-13 (Eternia orchestrator: GitHub-quota read)


## Filed on arrival — 2026-11-13 (Eternia orchestrator: git-host architecture read)



## Filed by Eternia review batch w1114a.2 — 2026-11-14

- **`RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH` — When GitHub refuses a realm's push because the owner disconnected the repository, the member is told to ask for a reconnect within a minute, instead of retrying a dead token for up to 44 minutes** · group: workspace-absorbs-projects-followups-2 · `agent_runtime/realm_sync/` · read in code 2026-11-14 (`eternia-backend` `603184bc`, `REALM-GIT-BINDING-DEATH-UNSEEN-WHILE-TOKEN-CACHED`): the backend now takes `POST /api/realms/{id}/sync/auth-rejected` (local `/api/me/realms/{ref}/sync/auth-rejected`) with the credential's `api_token`, answering 204 (re-broker) or 409 `realms.git_host_binding_lost`; hermes calls it nowhere · the Eternia half is already mapped (read in code: Eternia `realm_sync_credential_failure.dart` maps `realms.git_host_binding_lost` to reconnect), so it is this row's own live read, not a separate row · done when: a push or fetch refused 401/403 by github.com reports once, a 204 re-brokers, a 409 reaches the snapshot as `git_host_binding_lost`, pinned by tests; and the builder reads Mission Control showing reconnect, not retry, in a QA copy · NEW 2026-11-14 · reviewed 2026-11-14 w1114a.2 · LIVE CHECK 2026-11-14: built ef70922059 (report on 401/403/404 from publish, pull, status; 204 re-broker, 409 host-state mark; 13 tests on a local refusing HTTP host) — read Mission Control showing reconnect after GitHub refuses a server realm's push · handoff 2026-11-14: not read live — making github.com refuse a staging realm's token means uninstalling the staging GitHub App or dropping a repo from its installation, a GitHub account settings change no lane may make unasked; the hermes→snapshot half is pinned by test (sync.revoked reason git_host_binding_lost, host_state true), the Eternia render of that mark is existing code (mission_snapshot_realms.dart) · handoff 2026-11-14 (w1114a-realmlive): probe approved by the owner and staging rolled to backend 4c38b903, but no tool on the Linux box can take a repo out of the staging App's installation (gh's OAuth token is refused 403 on installation repositories, the built-in browser is signed out of GitHub, the Chrome extension is not connected), so GitHub's refusal was never provoked; what is left: the owner unticks ArcadiaLabsLLC/eternia-probe-org-create-2026-11 in the eternia-server-realms-staging installation, a lane binds QA Realm to the probe (staging manage.py shell: realms.subject_git_host _upsert of the realm subject with installation 181291722, then connect_realm_github as the server owner), Pulls as account B and reads the sheet, then the owner re-ticks it and the lane unbinds (disconnect_realm_github)

## Filed by Eternia review batch w1114a.3 — 2026-11-14

## Filed on arrival — 2026-11-14 (lane w1114a-hanthropic)

## Filed on arrival — 2026-11-14 (lane w1114a-hlens-rules)


## Filed on arrival — 2026-11-14 (lane w1114a-hlens-budget)

- **`RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` — Message your agents from Discord, through upstream's ready-made connector** · group: remote-parity-and-two-machine-proof-followups · fork / messaging · the build the owner's ruling on `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS` opened: a `Platform` member in `agent_runtime/messaging/models.py`, the token in `credentials.py`, a factory in `serve_lane.py` over the shim, Discord's own answer to each SWITCH_AUDIT finding (the sender gate: `RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM`; read in code, not run: after connect the adapter bulk-syncs upstream's slash commands with `tree.sync`, which its `sync_policy` `off` skips; whether discord.py logs the token or message text was not checked), approval cards as Discord components, and its Eternia page · bundle fit measured 2026-11-14 (w1114a-hmsgadapt): no adapter library enters the bundled-desktop or bundled-phone closure (both ship only the anthropic, mcp and fal extras, and switch off `agent_runtime.messaging`); on a full Harness the locked `discord.py[voice]` adds 14.7 MB installed over the base install, aiohttp's stack included · not shown: a real Discord message, which is the owner's sitting · RULED 2026-11-14: owner — "go with your recommendation after an architecture investigation for this session" (orchestrator, REVIEW_W1114A_B27: the NEXT-APPS ruling chose how, not when; Discord waits with its DEFERRED parent) · NEW 2026-11-14 · DEFERRED 2026-11-14: waits with the DEFERRED parent Eternia `TASK-REMOTE-PARITY-AND-TWO-MACHINE-PROOF`; the gate it needed, `RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM`, is being built by w1114a-hmsggate
- **`RT-MESSAGING-DISCORD-GATE-LISTS-EVERY-GUILD-SENDER-AS-REFUSED` — On a shared Discord server, the console's refused list shows only people who tried to talk to your agent** · group: remote-parity-and-two-machine-proof-followups · fork / messaging · `agent_runtime/messaging/upstream_adapter_transport.py::DiscordUpstreamAdapterTransport._user_gate` · read in code, not run (w1114a-hmsggate): the Discord adapter asks `_is_allowed_user` for every guild message, reaction and voice event before its mention rules, so the fork's gate there records every non-operator on a shared server through `on_refused` (`RefusedSenders`), not just senders who addressed the bot · latent: no serve wires Discord in (`RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` is DEFERRED); to settle with that build · NEW 2026-11-14 · DEFERRED 2026-11-14: waits with `RT-MESSAGING-DISCORD-THROUGH-UPSTREAM-CONNECTOR` · reviewed 2026-11-14 w1114a.31

## Filed on arrival — 2026-11-14 (lane w1114a-hcensus)
- **`RT-MAKE-ME-A-CHARACTER-GETS-NO-CHARACTER` — Asking your agent to "make me a character" makes one, instead of stopping on a teammate that does not exist** · group: console-top-bar-and-menu-proposal-followups-2 · task in Eternia: `TASK-CONSOLE-TOP-BAR-AND-MENU-PROPOSAL-FOLLOWUPS-2` · seen live 2026-11-15 (Eternia lane w1115e-e7, Linux QA copy, QA account on staging, Base on gpt-6-luna, a lane namespace with only Base on the roster): the operator message "Make me a character: a fox ranger … Drive it all the way through in one go" made no draft and no image — Base sent the work with `agent_chat_send` to `personainst_charsheet`, which no roster row names, the handoff came back "unknown persona personainst_charsheet", and Base ended asking whether to place an authoring agent; `launcher.agent.skills.list` answered Base with `skills: []` and `available: []`, so the operator could not give Base the skill either (Eternia evidence `EterniaLauncher/docs/stages/qa-reboot/live/2026-11-15/w1115e-e7/13_real_first_ask_handed_to_missing_teammate.png`); the same sitting made the character only when the message told Base to author it itself · read in code: `agent_runtime/mission_chat_prompts.py:196-202` makes character authoring a delegation unless `harness-charsheet-authoring` is in the turn's context, and says to `clarify` when no teammate carries it · guess, not checked: `harness-charsheet-authoring` (a `CANONICAL_SHARED_SKILL_IDS` member, `agent_runtime/profile_home.py:61`) is not installed in a fresh namespace's skills (`agent_runtime/skill_install.py`), which is why the picker offers nothing; the invented `personainst_charsheet` handle is the model ignoring the prompt's "never an id you memorized" line, and hermes refused it correctly · architecture: hermes runtime owns it (the delegation prompt plus the shared skills a namespace gets); the Eternia skill picker only lists what hermes answers, so no Eternia change unless the decision below needs a door · RULED 2026-11-15: owner — "reccomendations are good" (a: with no authoring teammate on the roster, Base loads the charsheet authoring skill and authors the character itself) · fix: (i) `mission_chat_prompts.py` delegation rule says "if no teammate on your HUD roster carries it, author it yourself with the skill" and keeps "never an id you memorized"; (ii) a namespace hermes creates or resets installs the canonical shared skills (`skill_install.install_harness_skills`) so the skill loads and the picker lists it · architecture: hermes fork-owned — the mission chat prompt (`agent_runtime/mission_chat_prompts.py`, fork file) and the namespace create path (`agent_runtime/namespace_seed/`), reusing `install_harness_skills`; no upstream edit, no Eternia change · done when: on a fresh namespace with only Base, "make me a character" makes a draft and an image in that turn, read live, and a prompt test pins the rule (mutation red) · fix (i) landed 07873b62a6 (w1115e-h3): both the full and the lean operator-chat rules say "if no teammate on your HUD roster carries it, author it yourself" (test_with_no_authoring_teammate_base_authors_the_character_itself, red with the old sentence restored) · fix (ii) REFUTED in code and live: every serve boot already installs the canonical shared skills into the namespace (`install_harness_skills_at_boot`, RT-SKILL-INSTALL-TARGETS-BASE-ROOT; its test reds when the canonical install is dropped) — seen live in lane namespace stagec-smoke-lane-10a3153a2b: `shared/skills` held `harness-charsheet-authoring` and Base's `skill_view` resolved it `shared_core`; the picker's empty `available` is Eternia's `missionAgentProfileSkillOptions`, the union of roster agents' assigned skills, not the shared skills · seen live 2026-11-15 (w1115e-h3, Linux QA copy, account A on staging, Base on gpt-6-luna, hermes_checkout at the fix, the served prompt carrying the new rule): "Make me a character: a fox ranger …" — Base still first sent the ask with `agent_chat_send` to the invented `personainst_profile_charsheet`, which was ACCEPTED (`dispatched: true`) and failed in the background "Hermes profile 'charsheet' does not exist"; on that delivery Base loaded the skill and authored itself (`characters start` made draft 20261115-203827-098e3d), but `characters auto` refused "has no base image", so no image was made (0 generations) · skill size (review B57): `harness-charsheet-authoring/SKILL.md` sits at its shrink-only preload ceiling; anything this row adds to the skill goes into its `references/`, never into `SKILL.md` · READY 2026-11-15 · unblocked 2026-11-15: `RT-AGENT-CHAT-SEND-ACCEPTS-AN-AGENT-WITH-NO-PROFILE` closed DONE 4d43a3036c · reviewed 2026-11-15 w1115e.3 · 2026-11-15 w1115e-h4: both blockers fixed (6947b5998f base from the words, 4d43a3036c refusal at admission), each read live in a fresh Base-only namespace: the invented-teammate send was refused inline and Base went on to author itself; the base drawn from the words and a composed sheet came from a by-hand `characters auto` run from the fix; the one-turn re-run with a pinned `hermes_checkout` now waits on `RT-AGENT-TERMINAL-HERMES-RUNS-ANOTHER-INSTALL` (an agent's terminal `hermes` ran the machine install) or a machine install at or after 4d43a3036c

## Filed on arrival — 2026-11-15 (lane w1115e-h3)
- **`RT-PERSONAL-BRAIN-JOIN-ON-A-SECOND-COMPUTER-READ-LIVE` — Pressing "Make this brain remote" on the personal board of a second computer is seen joining the first computer's personal repository with both computers' rows** · group: workspace-absorbs-projects · live read owed by w1115e-h7 for RT-PERSONAL-BRAIN-PRESS-ON-A-SECOND-MACHINE-HITS-ITS-OWN-REPOSITORY (DONE 80c265ea0d, unit-tested with a local bare repository only): a QA copy has no GitHub identity by default and the case needs two installs on one login; `STAGEC_QA_MACHINE_GITHUB=1` would reach the owner's login (its repositories go on `QA-GITHUB-TEST-REPOS-TO-DELETE`) · architecture: no code expected; fork-owned `agent_runtime/work_store/default_brain.py::_adopt_personal_remote`, Eternia shows the press unchanged · step 1: two lane namespaces (or Linux + Windows) on one login, promote on the first, add a row on each, press on the second; read `work.brain_joined` and both rows in `eternia-work-personal` · extra traffic: one GitHub GET and one clone per joining press · REQUIRES windows, linux · filed NEW, waits for a review batch · READY 2026-11-15
- **`RT-GENUI-AB-VERIFIES-THE-AGENT-AND-PROVIDER` — The comparison evaluation counts each answer under the agent and provider that actually produced it** · group: windows-handoffs · `evals/genui_first_response_ab.py` (`drive`, `collect`, `PromptResult.provider_key`) · `EterniaLauncher/lib/app/app_functions/app_function_agent_chat.dart` · source-audited 2026-11-15 by codex-win-hermes-handoffs on the exact two Eternia arm commits (`8ee367c821`, `469e500730`): new chat uses the selected agent and ignores the emitted agent/provider args, while scores prefer the planned provider label over the observed context receipt; no provider calls sent. · done when: dry-run each historical Console contract via the existing selected-agent and model-picker doors, pin their readbacks to the fresh chat, and prove a wrong agent/provider/model or absent receipt stays unverified before it can enter a passing cell. · NEW 2026-11-15 · READY 2026-11-15
