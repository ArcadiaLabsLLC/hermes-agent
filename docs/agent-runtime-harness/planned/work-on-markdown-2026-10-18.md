# Planned — Work on the workspace todo boards: the brain queues of every repo in the workspace, worked by persona agents, written through git (q/work-md-scope, 2026-10-18)

**Owner domain:** transport and wire ([03-transport-and-wire.md](../03-transport-and-wire.md) § Native
Work methods), the office and board ([06-office-and-board.md](../06-office-and-board.md) § The board),
multi-device ([09-multi-device-runtime.md](../09-multi-device-runtime.md), repo slots).
**Status:** IMPLEMENTATION-READY (third cut, lane q/work-plan-ready). An Opus lane builds each of W1–W5
from its §6 section without a design decision; every open point is a `Decided (plan):` rule in §8 or an
owner decision in §9. No code in this lane.
**Measured / read:** 2026-10-18 against hermes `origin/main` 78911c6cc3 and `EterniaLauncher`
`origin/main` (read with `git show` / `git grep`, never checked out). Companion plan:
[dispatcher-and-libraries-2026-10-18.md](dispatcher-and-libraries-2026-10-18.md) — W3's engine sits behind
its § 2.2 EXECUTOR contract, restated in §6.3 here verbatim.

## 0. Rulings and the owner's model

- `RULED 2026-10-18: owner — Work keyed on upstream profiles is incorrect design and must change; Work
  targets the owner's PERSONA agents (persona templates / persona instances), never upstream's profiles.`
- `RULED 2026-10-18: owner — Work is backed by the markdown todo system (the brain queue .md files in the
  ADR 0011 § Row grammar), not by upstream's kanban database.`
- `RULED 2026-10-18: owner — the workspaces USE the todo: a workspace's todo board lists each of its repos'
  brain todo tasks and the worker engine works on that; a workspace with no repo folders gets an
  auto-created default brain; git is part of the design and nothing may conflict.`
- `RULED 2026-10-18: owner — Work = the workspace's todo board (the brain queue notes of every repo folder
  the workspace binds), worked by persona instances, written through hermes's own worktree with
  replay-by-ID; reads from the tip via runtime.work.list; done = row deleted; assignee persona:<instance>
  or persona:<persona_id>; claim-only first; default brain local-only until slots.declare; hermes's own
  per-machine commit identity; agent work.* tools = engine only first; kanban retirement as W5`
  (`RT-WORK-W1-STORE`; the §8 questions of the second cut are all answered by it).
- `RULED 2026-10-18: owner — Work targets persona agents and the markdown todo boards, not kanban and
  upstream profiles` (launcher `MC-WORK-W4-BOARD`).
- Standing: ADR 0015 marks upstream kanban unused; ADR 0011 § Row grammar is the grammar's one home here
  (the launcher's twin is `EterniaLauncher/Launcher_Brain/30 — Decisions/0025` with its 2026-09-03
  claim amendment and 2026-10-18 ID amendment); the launcher's board never authors a git commit
  (`EterniaLauncher/docs/mission_control/planned/WORK_QUEUE_BOARD_2026-10-16.md` D6).

## 1. What is true today

### 1.1 `runtime.work.*` — the hermes side

- Five console-tier methods, `agent_runtime/work/rpc.py::register` (`for operation in ("capabilities",
  "context", "list", "inspect", "start")`), off the reader lane through `context.spawn_reply`; typed
  refusals `agent_runtime/work/model.py::Reason {INVALID, OWNER_CHANGED, UNAVAILABLE, CONFLICT, DENIED,
  UNKNOWN}` answered by `rpc.py::_work_reply` as error 4090 `{"reason": …}`. Registration is lazy:
  `agent_runtime/serve_rpc/registry.py::_ensure_work_methods` mounts them when `shipped("agent_runtime.work")`;
  the phone bundle lists `agent_runtime.work` under `switched_off_modules`
  (`agent_runtime/bundle_profiles/bundled-phone.yaml`). The manifest fixture
  `tests/agent_runtime/serve_rpc_manifest.expected.json` names the five (plus the unrelated
  `runtime.work.cancel` / `runtime.work.restart` twins of `agent_runtime/serve_rpc/work.py`).
- Owners are PROFILES × kanban boards: `agent_runtime/work/native.py::scopes` crosses
  `hermes_cli.kanban_db.list_boards` with `hermes_cli.profiles.list_profile_names` / `get_profile_dir`;
  `model.py::WorkScope(install, board, profile, database, home)`, `.owner` = `fingerprint([...])`,
  `.wire(label)` = `{owner, board, profile, label, operations: ["inspect", "start"]}`.
  `service.py::execute` authorizes (`authorize_call(TIER_CONSOLE, caller, method=…)`), reads
  `read_install_identity(store_root()).install_id`, routes `capabilities` → `_work_capabilities`, else
  `_scoped_work_request` (install check → `context.resolve` → owner lookup → `start | list | inspect`).
- Reads: `native.py::list_work` → `kanban_db.list_tasks(assignee=profile)` keyset-sliced at 40;
  `native.py::inspect` → `kanban_db.get_task` + `latest_summary`; `native.py::project` fields
  `id, title, status, assignee, block_kind, created_at, started_at, completed_at, heartbeat_at, result,
  result_truncated, body, body_truncated, in_conversation, revision`.
- The one write: `native.py::start` → `kanban_db.create_task(... idempotency_key="eternia:work:"+
  fingerprint([actor, client, owner, request]))` under `write_txn`; replay by key; `Reason.CONFLICT` on a
  changed payload.
- Conversation scope: `agent_runtime/work/context.py::resolve` → `_native` (profile, home, session) or
  `_operator` (validated by `agent_runtime/operator_conversation.py::validate_operator_conversation`,
  whose `exact_operator_target` requires `install_id, persona_id, persona_instance_id, session_id` and
  resolves the instance through `PersonaInstanceStore`). `_operator` returns `WorkContext(session,
  profile=None, can_start=True)` — "A persona instance is not a native dispatcher profile".
- Who executes: NOBODY in the fork (`gateway/kanban_watchers.py` is upstream's gateway mixin; `harness
  serve` runs no gateway). The plugin's two hooks observe that absent dispatcher:
  `plugins/eternia-harness/__init__.py::route_blocked_kanban_cards` (→ `hermes_cli/kanban_blocked_pm_tick.py
  ::on_kanban_dispatch_tick`) and `::record_kanban_crash_evidence` (→ `hermes_cli/kanban_crash_evidence.py
  ::on_kanban_worker_exited`), registered by the two `ctx.register_hook("on_kanban_…")` lines. The
  three fork kanban modules (absent from `upstream/main`): `hermes_cli/kanban_blocked_pm.py`,
  `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py`. The FIVE fork-only kanban tests (absent from
  `upstream/main`, checked with `git cat-file -e upstream/main:<path>`): `tests/hermes_cli/
  test_kanban_blocked_pm_hook.py`, `test_kanban_blocked_pm_tick.py`, `test_kanban_db_crashed_workers_downstream.py`,
  `test_kanban_db_downstream.py`, `test_kanban_write_guard_downstream.py`; plus the autouse fixture
  `tests/_downstream/conftest_plugin.py::_kanban_guard_denies_recorded_root`. Fixture rows that name them:
  `tests/fixtures/import_layers_grandfathered.json` (`hermes_cli/kanban_crash_evidence.py|hermes_cli.kanban_db|_pid_alive`),
  `tests/fixtures/process_globals_allowlist.json` (`hermes_cli/kanban_blocked_pm_tick.py|_cursors`),
  `tests/fixtures/upstream_footprint.json` (a `reason` string only — text, not a path row).
  `tests/agent_runtime/test_no_kanban_dependency.py::_native_work_import` admits exactly `work/native.py`'s
  two imports.
- The live store `X:/Eternia/.hermes/kanban.db` holds 0 tasks. **Nothing to migrate.**

### 1.2 The launcher side

- Running work (`lib/core/services/hermes/runtime/data/capabilities/harness_work_capabilities.dart`,
  `mission_action_work_twin_lane.dart::kMissionWorkTwinMethods` → `runtime.work.cancel/restart`): builds
  and processes; UNTOUCHED by this plan.
- The Work page: `lib/app/work/work_composition.dart::_WorkHost.connect` requires
  `manifest.supports('runtime.work.capabilities')` and builds `packages/agents/eternia_hermes_adapter/lib/
  src/work/hermes_work_catalog.dart::HermesWorkCatalog.connect` (checks `version == 1`, `owners is List`,
  `install_id`, `chat_scopes`) → one `hermes_work_backend.dart::HermesWorkBackend.fromWire(owner)` per
  owner (reads `owner, label, profile, operations`), whose `_call` sends `install_id, owner, client_scope`
  (+ `conversation` except on `start`) and refuses `work_owner_changed` when the reply's `version/install_id/
  owner` differ. `hermes_work_projection.dart::hermesWorkObservation(task, owner, profile)` throws
  `FormatException('Work owner changed.')` when `task['assignee'] != profile`, maps `_states {ready→queued,
  todo→queued, triage→needsInput, scheduled→queued, running→running, review→needsInput,
  blocked→needsInput, done→succeeded}` with `_labels`, needs `id, title, status, body, result,
  result_truncated, in_conversation, revision` and one of `completed_at|heartbeat_at|started_at|created_at`
  (epoch seconds). `packages/work/eternia_work_experience/lib/src/work_models.dart::WorkExperienceOperation
  {start, inspect, redirect, cancel, retry}`; `WorkOwnerCapabilities {owner, label, operations, durable,
  limitations}`. Destination picker `lib/shared/work/work_assignment_sheet.dart` (dropdown over
  `owners`, label `<board> · <profile>`), `work_assignment_menu.dart`.
- The Queues tab: `lib/features/mission_control/work_queue/data/work_queue_source.dart::WorkQueueRepo` is a
  FIXED enum `{launcher, hermes, backend}` with `brainDir` and `matchesSlot(name, cloneUrl)`;
  `WorkQueueRepoLocator.locate({workspaceId, repo})` → `WorkQueueRepoLocated(root) | NotHere |
  LocatorUnavailable(reason)`; `WorkQueueSource.read({root, repo})` → `List<WorkQueueNote{path, name, text,
  modified}>`; `LocalWorkQueueSource` is the `dart:io` implementation. `lib/app/mission_control/
  work_queue_locator_binding.dart::SlotsWorkQueueRepoLocator` asks `MissionWorkspaceSlotsClient.show`.
  `state/work_queue_board_provider.dart::loadWorkQueueBoard({locator, source, key})` →
  `WorkQueueBoardLoaded(root, files, rows, readAt) | NotHere | Unavailable | Failed`; `workQueueBoardProvider`,
  `workQueueBlockerIdsProvider`, `WorkQueueBoardSelection`. `policy/work_queue_row_parser.dart::WorkQueueRowParser`
  (`parseFile`, `parseLine`, `splitSegments`, `idOf`, `titleOf`, `markDuplicateIds`, `_status`, `_ruled`,
  `_taken = \*\*TAKEN (\d{4}-\d{2}-\d{2}) ([^*]+?)\*\*`, `_recommend`) is the one grammar owner;
  `policy/work_queue_row.dart::WorkQueueRow {domain, file, line, id, title, continued, duplicateId, status,
  recommend, taken: WorkQueueClaim{date, lane}, rulings, pointers, raw}`. `widgets/work_queue_filters.dart::
  WorkQueueRepoSwitcher` is a `SegmentedButton<WorkQueueRepo>`; `widgets/work_queue_card_actions.dart::
  WorkQueueCardMenu` is read-only (Open row / Open plan / Open <pointer> / Copy row reference).
  Gate: `test/architecture/work_queue_status_grammar_test.dart` over the real `Launcher_Brain` plus the
  shared fixtures `test/fixtures/work_queue/grammar_valid.md` / `grammar_defects.md`.

### 1.3 Workspaces, repo slots, checkout folders

- `agent_runtime/models.py::Workspace {id, slug, name, …, max_concurrent_lanes: int | None, realm_id}`;
  `agent_runtime/store.py::WorkspaceStore.get`; `agent_runtime/office_store/store.py::OfficeStore.list_workspaces()
  -> list[str]` (the ids with an `office.json`); default `agent_runtime/default_scope.py::DEFAULT_WORKSPACE_ID
  = "ws_default"`.
- Slots: `agent_runtime/workspace_slots.py` (`__layer__ = "stores"`): `load_document(ws)` /
  `write_document`, `live_slots(document)`, `normalize_declaration(entry)` (REFUSES a clone URL that is
  not http(s)/ssh — `REASON_INVALID_CLONE_URL`), `declare(ws, slots, *, issued_at, machine)` (REPLACES the
  declared set; names missing are tombstoned), `bound_path(slot)` (the machine-roots registry,
  `agent_runtime/machine_roots.py::load_machine_roots`), `bind(ws, slot, path, *, issued_at)` (refuses
  `slot_not_declared`; writes `write_machine_roots`), `show(ws)` → `{document, here: {slot: {bound_here,
  path, unknowns, fill}}}`, `machine_id()` (the gateway install id; `SlotRefused(machine_identity_unavailable)`),
  `require_publish_right(ws, credential)` (a no-realm workspace returns at once; a server-bound realm fails
  closed without the credential). RPC: `agent_runtime/serve_rpc/workspace_slots.py` (`@method(name,
  tier=TIER_CONSOLE)` + `@_guarded` turning `SlotRefused` into `_refused`). Probe:
  `agent_runtime/workspace_slots_probe.py::report` (`_SlotProbe.checkout` → `matches | remote_mismatch |
  not_a_repo`; `_status` via `workspace_slot_recipe.readiness`). Clone: `agent_runtime/workspace_slot_setup.py
  ::clone_slot`.
- Git door: `agent_runtime/git_cmd.py::run_git(args, *, repo=None, config=None, **run_kwargs)` →
  `subprocess.CompletedProcess[str]`, never raises on non-zero, `-c` pairs per invocation (never written to
  `.git/config`); switched off on the phone bundle with a loud stand-in. Realm sync sets its identity with
  `git config user.email realm-sync@localhost` (`agent_runtime/realm_sync/git.py`) — the Work writer does
  NOT copy that (it would write the operator's clone config); it uses `-c` pairs (§5).
- `agent_runtime/build_identity.py::NON_RUNTIME_PREFIXES = ("docs/", "tests/", ".github/", "Harness_Brain/")`:
  a commit in the hermes PRIMARY touching only these does not restart a live serve. The writer never
  commits in a primary anyway (§5).

### 1.4 The todo system — files and how they are written

- hermes: `Harness_Brain/TODO.md` → `Harness_Brain/20 — Active Initiatives/runtime-queue.md`,
  `fork-hygiene-queue.md`, `dead-code-burn-down-queue.md`; lint `tests/tooling/test_work_queue_row_grammar.py`
  (`ROW`, `ROW_ID`, `ID_SHAPE`, `STATUS`, `RULED`, `RETIRED`, `BLOCKED_REASONS`, `LANE_REASONS`, `BLOCKER`,
  `CROSS_REPO`, `BLOCKER_ID_CEILING = 4`; `split_segments`, `row_defects`, `queue_rows`, `is_queue`;
  positive controls `VALID` / `DEFECTS`). launcher: `Launcher_Brain/TODO.md` → 31 `*-queue.md`; gate
  `test/architecture/work_queue_status_grammar_test.dart`. backend: `EterniaBackend_brain/20 — Active Initiatives/`.
- Every row is written by a SESSION with a git commit (fetch, `**TAKEN <date> <who>**`, commit that line
  alone, push; the landing commit deletes the row — ADR 0025 2026-09-03, this repo's CLAUDE.md "Work
  tracking"). Concurrent sessions share ONE git index per clone.

### 1.5 Persona vs profile; the chat lane the engine rides

- `agent_runtime/models.py::PersonaInstance {id, persona_id, role, display_name, profile_id, runtime_root,
  state: WorkerSessionState, mode, goal_id, realm_id, workspace_id, …}`;
  `agent_runtime/states.py::WorkerSessionState {IDLE, ASSIGNED, RUNNING, WAITING_ON_TOOL, WAITING_ON_PROOF,
  SELF_HEALING, WAITING_ON_HUMAN, POSSESSED, COMPLETED, BLOCKED}`; store
  `agent_runtime/persona_assignments/store.py::PersonaInstanceStore.get(id)` / `.list_all()`; the
  instance's chat root `agent_runtime/persona_assignments/lookups.py::resolve_default_chat_session_id_for_instance(store,
  *, persona_id, persona_instance_id) -> str | None` (never mints); `agent_runtime/workspace_scope.py::
  effective_workspace_id(instance, active_workspace_id=None)`.
- A runtime-forged turn: `agent_runtime/dispatch_delivery/forge.py::forge_delivery_turn(*, root_session_id,
  persona_id, persona_instance_id, message, client_message_id, …)` builds the `SimpleNamespace` the door
  takes (`new_session=False, intent_hint="chat", stream=False, json=True, requested_by=…,
  requested_by_session=root, relay_chain=[]`) and calls `agent_runtime/mission_chat_door.py::
  run_mission_chat_turn(args) -> (exit_code, payload)`; `MissionChatDoorUnbound` when nothing is bound;
  `run_open_chat(args)` opens a chat the same way. A finished turn's payload carries `ok, persona_id,
  persona_instance_id, root_chat_session_id, session_id, client_message_id, turn_id, execution_state,
  reply` (`hermes_cli/harness_parts/persona/chat_admission.py`); a busy root answers `queued: True`.
- The busy-root queue: `agent_runtime/chat_root_send_queue.py::enqueue(root, client_message_id, args) ->
  (QueuedSend, position, replay)` (idempotent on the pair), `persistable_args(args, *, origin)`,
  `ORIGIN_ARG = "send_origin"`; the runner `agent_runtime/chat_root_send_runner.py::RunnerPolicy
  {root_is_idle, run_turn, stream}`, `_run_entry` → `_settle(entry, exit_code, outcome_from_payload(payload))`
  → `agent_runtime/chat_turn_settles.py::record_settle` (durable `SettleRecord {settle_id, client_message_id,
  session_id, turn_id, request_id, exit_code, refusal_class, summary, …}`, `settle_id_for(session, cmid)`,
  `read_settle(settle_id)`); `wake_queued_send_runner()`; the serve starts it in
  `hermes_cli/harness_parts/serve/session.py` (`start_queued_send_runner(stop_event=self.liveness_stop,
  home=…, policy=queued_turn_runner_policy(self))`, beside the dispatch drain and
  `agent_runtime/lens/poller.py::start_lens_poller(stop_event=self.liveness_stop)`).

## 2. The model

**A workspace's todo board is the union of the `type: queue` notes of every repo checkout folder assigned
to the workspace** — for each live slot bound on this machine, `<bound path>/<brain dir>/*.md` with
`type: queue` (the brain dir is discovered or pinned, §6.1) — plus, when the workspace binds no slot with a
brain directory, its auto-created default brain (§4). A row in the ADR 0011 grammar IS a task. Nothing is
copied: no second store, no database, no projection that can disagree with the file. The board keys a task
by `(slot, ID)`.

**The worker engine works claimed rows** (claim-only, RULED): a row `**TAKEN <date> persona:<instance_id>**`
(claimed by the operator through `runtime.work.claim`, or by `start` with an assignee) is handed to that
instance as one chat turn carrying the row, its pointers and its brief, and written back when the turn
ends: done = the row is deleted (the deleting commit's body carries the result, the receipt log keeps it);
a question = `BLOCKED <date>: owner decision — <question> · Recommend: <answer>` with the claim released;
a stop = the claim released with `DEFERRED <date>: stopped — <reason>`; an unreadable ending = the claim
released with `NEEDS PLAN <date>: …`. Every write-back is one row operation keyed by ID (§5), never a text
merge. A row `TAKEN` by a session lane (`<who>` not `persona:…`) is never touched by the engine.

**Git is the store's transport and history.** hermes is the ONE writer per machine (one `harness serve` per
root, the OS lock of `agent_runtime/serve_socket/` — doc 09 R-L2), writing in its own worktree and pushing
fast-forward; sessions keep today's protocol; the launcher reads and asks, never commits.

## 3. The grammar — the ADR 0011 amendment, the lint, the launcher parser

### 3.1 The exact ADR 0011 edit (W1, `Harness_Brain/30 — Decisions/0011 — One brain per repo, one Mission Control queue in the launcher.md`)

Under `## Row grammar`, after the `**Claim:**` bullet, append these two bullets verbatim:

```
- **Assignee (amendment 2026-10-18, Work W1):** an optional segment `assignee: persona:<token>` names who the
  row is FOR — `<token>` is a persona instance id (this instance) or a persona id (any instance of that
  persona); the token is `[A-Za-z0-9_.-]+`. At most one such segment; a segment opening `assignee:` in any
  other shape is a defect. A claim by the engine is `**TAKEN <date> persona:<instance_id>**`; a claim by a
  lane keeps its lane name. The assignee is not a status and does not change the status.
- **Engine-minted IDs (amendment 2026-10-18, Work W1):** a row the Work engine appends is `WORK-<6>` —
  `WORK-` plus six base32 characters (`[A-Z2-7]{6}`), minted by the engine, unique within the brain like
  any ID. Lane rows keep their domain prefixes; nothing existing is renumbered.
```

And in the header paragraph of the ADR (the `> Owner decisions 2026-10-18:` line) append one sentence:
`Amended 2026-10-18 (Work W1): the optional assignee segment and engine-minted WORK-<6> IDs; the
launcher's twin amendment is ADR 0025 "Amendment 2026-10-18b".`

### 3.2 The lint change (W1, `tests/tooling/test_work_queue_row_grammar.py`)

- Add `ASSIGNEE = re.compile(r"^assignee: persona:[A-Za-z0-9_.-]+$")` beside `RULED`, and
  `WORK_ID = re.compile(r"^WORK-[A-Z2-7]{6}$")`.
- In `row_defects`, inside the `for segment in segments[1:]` loop, add:
  `if segment.startswith("assignee:") and not ASSIGNEE.match(segment): defects.append(f"assignee shape:
  {segment[:40]!r}; the segment is `assignee: persona:<token>`")`; after the loop:
  `if sum(1 for s in segments[1:] if ASSIGNEE.match(s)) > 1: defects.append("2 assignee segments; at most one")`.
- In `row_defects`, after the ID shape check: `elif match.group(1).startswith("WORK-") and not
  WORK_ID.match(match.group(1)): defects.append(f"ID `{match.group(1)}` opens WORK- but is not WORK-<6 base32>")`.
- Update the module docstring (one line each for the assignee segment and `WORK-<6>`).
- `VALID` gains: `"- **`RT-I` — assigned** · assignee: persona:pi_alice_01 · READY 2026-10-18"`,
  `"- **`WORK-A2B3C4` — minted** · assignee: persona:alice · READY 2026-10-18 · **TAKEN 2026-10-18 persona:pi_alice_01**"`.
  `DEFECTS` gains: `"- **`RT-A` — bad assignee** · assignee: bob · READY 2026-10-18": "assignee shape"`,
  `"- **`RT-A` — two assignees** · assignee: persona:a · assignee: persona:b · READY 2026-10-18": "2 assignee"`,
  `"- **`WORK-abc` — bad mint** · READY 2026-10-18": "is not"` (lower-case fails `ID_SHAPE` first; keep
  the row — it proves the two checks compose), `"- **`WORK-ABCDE` — short mint** · READY 2026-10-18": "WORK-<6>"`.
- New test `test_the_shared_fixtures_pass_and_fail_as_the_launcher_says`: reads
  `tests/fixtures/work_queue/grammar_valid.md` (every row → `row_defects == []`) and
  `grammar_defects.md` (every row → defects non-empty); the fixtures are W1's port of the launcher's two
  files plus the three assignee rows of §6.4.

Killing mutations (each recorded as a red in the W1 commit body): drop the `ASSIGNEE` arm → the
`"assignee shape"` DEFECTS row fails `test_each_defect_class_is_caught`; drop the `WORK_ID` arm → the
`"WORK-<6>"` row fails; make `ASSIGNEE` accept `assignee: bob` → the same row fails.

### 3.3 The launcher parser change it implies (W4, `lib/features/mission_control/work_queue/policy/`)

- `work_queue_row_parser.dart`: `static final RegExp _assignee = RegExp(r'^assignee:\s*persona:([A-Za-z0-9_.-]+)$');`
  and `static final RegExp _assigneeOpen = RegExp(r'^assignee:');` In `parseLine`'s segment loop: a segment
  matching `_assignee` sets `assignee = WorkQueueAssignee(token)` (a second one sets `assigneeDefect = true`);
  a segment matching `_assigneeOpen` but not `_assignee` sets `assigneeDefect = true`. `_taken`'s group 2 is
  split: `lane` keeps the whole `<who>`; `personaInstanceId` = the text after `persona:` when it opens so.
  `WORK-` IDs: `static final RegExp _workId = RegExp(r'^WORK-[A-Z2-7]{6}$');` — an ID opening `WORK-` that
  fails it is a defect (`idDefect`), reported like a missing ID.
- `work_queue_row.dart`: `final class WorkQueueAssignee { const WorkQueueAssignee(this.token); final String
  token; }`; `WorkQueueRow` gains `this.assignee` (nullable), `this.assigneeDefect = false`,
  `this.idDefect = false`; `WorkQueueClaim` gains `this.personaInstanceId` (nullable); `grammarDefect`
  (the existing getter the gate reads) ORs in `assigneeDefect || idDefect`.
- The twin amendment, `EterniaLauncher/Launcher_Brain/30 — Decisions/0025 — One master TODO, domain queues,
  reports split on arrival.md`: `## Amendment 2026-10-18b — the assignee segment and engine-minted IDs`,
  the same two bullets as §3.1 with "hermes ADR 0011" named as the twin.
- Fixtures: `test/fixtures/work_queue/grammar_valid.md` gains `FX-ASSIGNEE` (`assignee: persona:alice`),
  `FX-PERSONA-TAKEN` (`**TAKEN 2026-10-18 persona:pi_alice_01**`), `WORK-A2B3C4` (an engine-minted row);
  `grammar_defects.md` gains `FX-BAD-ASSIGNEE` (`assignee: bob`), `FX-TWO-ASSIGNEES`, `WORK-ABCDE`.
  hermes's `tests/fixtures/work_queue/*.md` are byte-identical copies (W1 ports the launcher's current
  files and adds the same six rows; W4 adds them on the launcher side — the lint on each side proves its
  own copy; `Decided (plan):` the launcher file is canonical, hermes re-copies on drift).

## 4. The default brain — a board always has a home

Built by W1 (`agent_runtime/work_store/default_brain.py`), called by W2's `capabilities` and
`create_brain`, and by W3's tick.

- Trigger: `boards(workspace_id)` finds NO live slot whose bound checkout has a brain directory.
- Location: `<store_root>/work/<safe_path_token(workspace_id)>/brain/` (`agent_runtime/paths.py` gains
  `work_dir()`, `work_workspace_dir(ws)`, `default_brain_dir(ws)`, `work_worktree_dir(ws, slot)`,
  `work_runs_dir(ws)` — five one-line path helpers in the existing style).
- Skeleton (`default_brain.skeleton(root: Path) -> list[Path]`): `Work_Brain/TODO.md` (frontmatter
  `type: moc`, one pointer paragraph naming `work-queue.md`, a Dataview block ```` ```dataview\nTABLE
  program, status FROM "Work_Brain/20 — Active Initiatives" WHERE type = "queue"\n``` ````),
  `Work_Brain/20 — Active Initiatives/work-queue.md` (frontmatter `type: queue`, `program: work`,
  `status: open`, `tags: [queue, program/work]`; the one-line grammar reminder copied from
  `runtime-queue.md` line 19; no rows).
- Git: `run_git(["init", "-q", "-b", "main"], repo=None, cwd=root)` → `add -A` → `commit` with the §5
  identity pairs and message `work: default brain for <workspace_id>`. No remote.
- Declaration: `workspace_slots.declare_local_slot(workspace_id, "brain", *, path, issued_at, machine)
  -> dict` (NEW, additive, `stores`): writes ONE slot into the document without touching the others —
  `{"repo": {"clone_url": None, "default_branch": "main", "local": True}, "toolchain": _toolchain(None),
  "context": {**_context(None), "role": "brain", "brain_dir": "Work_Brain/20 — Active Initiatives"},
  "recipe": _revised(None, bump=False), "declared_at", "declared_by_machine", "issued_at", "removed_at": None}`
  — then `bind(workspace_id, "brain", path, issued_at=…)`. Publish right: `require_publish_right(workspace_id,
  None)` is called first; a no-realm workspace passes, a server-less realm passes (the local allow stub), a
  server-bound realm without a credential refuses `realm_publish_denied` → `capabilities` answers
  `default_brain: {"state": "needs_publish_right"}` and the launcher's `Create brain` sends the credential
  through `runtime.work.create_brain` (§6.2). `Decided (plan):` the auto-create never holds a credential;
  the operator's one click does.
- `normalize_declaration` (additive edit): when `repo.get("local") is True`, `clone_url` may be `None`
  and the body keeps `"local": True`; a re-declare from the launcher round-trips it
  (`MissionSlotDeclarationWire` gains `local`, §6.4). `workspace_slots_probe._SlotProbe.checkout` answers
  `"local"` for a local slot whose path has a `.git` (no remote check); `workspace_slot_recipe.readiness`
  treats `"local"` like `"matches"`. `workspace_slot_setup.clone_slot` refuses a local slot with
  `SlotRefused("slot_local_only")`. Realm sync carries the declaration key-wise as today; another machine
  sees slot `brain` unbound there ("not on this machine") — the ruled local-only behaviour. When the owner
  later declares a `clone_url` for `brain`, `declare()` replaces the body, `local` drops, and the §5 push
  steps apply unchanged on the next write (`git remote add origin <url>` is done by the writer's `_ensure_remote`
  when the worktree's clone has none and the slot declares one).
- A slot whose checkout has no brain directory (a third-party repo) is NOT given one; the board lists it
  as `brain_dir: null`; `create_brain` with `slot=<name>` runs `skeleton()` inside that checkout and
  commits through the §5 writer (one `APPEND`-shaped op whose payload is the two new files).

## 5. The write path — step table with every failure branch

Terms: *clone* = the slot's bound checkout on this machine (`bound_path(slot)`); *hermes worktree* =
`work_worktree_dir(ws, slot)` = `<store_root>/work/<ws token>/<slot>/worktree`, a `git worktree` of the
clone on branch `work/<machine_id>`, owned by hermes alone; *tip* = `origin/<default_branch>`
(`slot.repo.default_branch`); *identity pairs* = `("user.name=Eternia Harness",
f"user.email=harness+{machine_id}@eternia.local")` passed as `run_git(config=…)` on `init`, `commit`.

A row operation is `RowOp(ref: RowRef(slot, note, id), op: Op, who: str, request_id: str, payload: dict)`,
`Op(StrEnum) = APPEND | CLAIM | RELEASE | SET_STATUS | DELETE` — one line, found by ID; `payload` is
`{"row": "<full row line>"}` for APPEND, `{"status": "<status segment>"}` for SET_STATUS, `{"result": str}`
for DELETE, `{}` otherwise. The writer is `agent_runtime/work_store/writer.py::Writer.apply(op) -> Receipt`
(§6.2). Every step runs through `run_git`; no `merge`, `rebase`, `pull`, `stash`, ever.

| # | step (git, where) | success → | failure branch | caller sees (`WorkRefused(reason)` or receipt field) |
|---|---|---|---|---|
| 0 | preconditions: `bound_path(slot)` is a dir with `.git`; `machine_id()`; `shipped("agent_runtime.git_cmd")` | 1 | slot not bound here | `slot_unbound` |
| | | | no machine identity | `machine_identity_unavailable` (re-raised from `SlotRefused`) |
| | | | phone bundle (git switched off) | `git_unavailable`; the phone is read-only against a desktop runtime |
| 1 | `git -C <clone> worktree prune` then, if `<hermes worktree>/.git` is absent: `git -C <clone> worktree add --no-checkout <hermes worktree> -B work/<machine_id> <tip or HEAD>`; `git -C <wt> sparse-checkout set --no-cone "/<brain dir>/"` | 2 | `worktree add` fails (locked `.git`, disk) | `worktree_failed`, stderr tail scrubbed |
| | | | registration stale (dir deleted, entry kept) | handled by the `prune`; never a refusal |
| 2 | `git -C <clone> fetch origin <default_branch>` — refs only; skipped for a local slot (`repo.local`) | 3 | remote missing (`fatal: 'origin' does not appear…`) while the slot declares a `clone_url` | `remote_missing` (the bind's remote check lied; `slots.report` shows it) |
| | | | network / auth failure | `fetch_failed`; nothing written; the read falls back to the last fetched tip with `stale: true` |
| 3 | `git -C <wt> reset --hard origin/<default_branch>` (local slot: `reset --hard main`); then `git -C <wt> status --porcelain` must be empty | 4 | dirty worktree after reset (an untracked file someone dropped in) | `git -C <wt> clean -fdq` once, re-check; still dirty → `worktree_dirty` |
| | | | tip has no `<default_branch>` | `branch_missing` |
| 4 | idempotency: `git -C <wt> log -n 1 --fixed-strings --grep "request_id: <rid>" <tip> -- "<note>"` | hit → return the recorded receipt (`replayed: true`, its commit) without applying | — | receipt `{…, "replayed": true}` |
| 5 | read `<note>` at the tip; `grammar.find(rows, id)`; check the precondition for `op`: CLAIM → present and untaken; RELEASE / SET_STATUS / DELETE → present and `taken.who == who` (or `who == "operator"`); APPEND → ID absent in every `type: queue` note of the brain | 6 | row absent | `row_gone` |
| | | | CLAIM on a taken row | `already_taken` (receipt names the holder) |
| | | | write-back by a non-holder | `not_claimant` |
| | | | APPEND with an existing ID | `id_exists` |
| | | | the note's rows fail `grammar.parse_note` at the tip | `grammar_invalid` (the row that fails, line) — the writer never edits a note it cannot parse |
| | | | note missing | `note_missing` |
| 6 | `grammar.apply(line, op) -> str`; write temp + `os.replace` | 7 | — | — |
| 7 | `git -C <wt> add -- "<note>"`; `git -C <wt> -c user.name=… -c user.email=… commit -q -m "<subject>" -m "<body>"`; subject `work: <OP> <ID> <who> (ws <workspace_id>, <slot>/<note name>)`, body `request_id: <rid>` + for DELETE `result: <one line>` | 8 | commit fails (hook, identity) | `commit_failed`, stderr tail |
| 8 | `git -C <wt> push -q origin work/<machine_id>:<default_branch>` (default fast-forward only); local slot: skip | done; receipt `work.row_<op>` `{ref, who, request_id, commit, replays, pushed}` | push rejected non-fast-forward (`! [rejected]` / `fetch first`) | **replay**: go to 2 with `replays += 1`; the tip moved under us |
| | | | push rejected by policy (protected branch, auth) | `push_refused`; the local commit stays on `work/<machine_id>` and the next apply resets it away |
| 9 | replay budget: `replays == 8` | — | exhausted | `push_contended`; receipt carries the 8 tip SHAs seen |

Two machines: both run steps 2–8 on their own worktrees; the first fast-forward wins; the loser's step 8
rejects, its replay reads the winner's line at step 5 and answers `already_taken` (CLAIM) or `row_gone`
(the row landed meanwhile) — exactly one `TAKEN` exists after any race. Two sessions and the engine on one
clone touch three indices (the primary's, each session worktree's, hermes's). A session that races the
engine sees its own non-fast-forward and does what ADR 0025 says (fetch, re-apply); for a textual conflict
on adjacent rows it runs `scripts/work_row.py` (§6.2), which applies the op by ID in the session's own
checkout. Reads (`board.rows`) come from the hermes worktree after step 2–3 (a read runs 1–3 only); the
default brain has no remote, so steps 2 and 8 are skipped and one writer on one machine has nothing to race.

Why nothing conflicts: no textual merge ever runs (conflict markers cannot appear from this path;
`merge=union` is rejected because it can duplicate a row); one writer per machine with its own index; a
claim is atomic because the push is; sessions keep their protocol; multi-device is the same race as two
sessions.

## 6. Lanes — what each builds, exactly

Common to every hermes lane: new modules declare `__layer__` (`tests/tooling/test_fork_import_layers.py`;
layers lowest first `models → policy → stores → lanes → wiring`, `scripts/god_file_probe.py::LAYERS`); every
new file is ≤ 800 code lines (`test_downstream_size_ceiling.py`, counter `god_file_probe.code_lines`:
non-blank, not `#`-led), every function ≤ 150 lines and ≤ 4 deep (`test_function_legibility_floor.py`),
routing on an op / kind / status is a `dict` table, never an `if x == "…"` ladder
(`test_no_ladder_routing.py`); no fork module imports a `_private` upstream name. Upstream files are
untouched by every lane (no lane edits one; the whole program is fork-owned code plus deletions of fork
files). Commit trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Each lane runs
`scripts/run_tests_bundled.sh --affected` while writing and one `python -m pytest -q -p no:cacheprovider
<its test files>` at the end; the landing session runs `scripts/run_tests_bundled.sh tests` once per batch
(`Harness_Brain/50 — Agent Handoffs/Running the tests.md`).

### 6.1 W1 — the store (`RT-WORK-W1-STORE`; one CHANGE commit)

Files (all new unless marked; fork-owned):

| file | layer | contents |
|---|---|---|
| `agent_runtime/work_store/__init__.py` | `models` | module map docstring (one line per module below), `__all__` empty |
| `agent_runtime/work_store/reasons.py` | `models` | `class Reason(StrEnum)`: the six `work/model.py::Reason` values verbatim (`INVALID="invalid_request"`, `OWNER_CHANGED="work_owner_changed"`, `UNAVAILABLE="work_unavailable"`, `CONFLICT="idempotency_conflict"`, `DENIED="scope_denied"`, `UNKNOWN="work_outcome_unknown"`) plus `ROW_GONE="row_gone"`, `ALREADY_TAKEN="already_taken"`, `NOT_CLAIMANT="not_claimant"`, `ID_EXISTS="id_exists"`, `PUSH_CONTENDED="push_contended"`, `PUSH_REFUSED="push_refused"`, `SLOT_UNBOUND="slot_unbound"`, `GRAMMAR_INVALID="grammar_invalid"`, `NOTE_MISSING="note_missing"`, `BRANCH_MISSING="branch_missing"`, `REMOTE_MISSING="remote_missing"`, `FETCH_FAILED="fetch_failed"`, `WORKTREE_FAILED="worktree_failed"`, `WORKTREE_DIRTY="worktree_dirty"`, `COMMIT_FAILED="commit_failed"`, `GIT_UNAVAILABLE="git_unavailable"`, `MACHINE_UNIDENTIFIED="machine_identity_unavailable"`, `NO_BRAIN="no_brain"`, `NEEDS_PUBLISH_RIGHT="needs_publish_right"`, `ASSIGNEE_UNKNOWN="assignee_unknown"`; `class WorkRefused(ValueError)` with `.reason` and `.detail: str = ""`. `work/model.py` keeps its `Reason` until W2 re-exports (`Reason = reasons.Reason`). B1 of the dispatcher plan EXTENDS this file (executor / scheduler values) — it does not create it. |
| `agent_runtime/work_store/grammar.py` | `policy` | the Python twin of `WorkQueueRowParser`: `Status(StrEnum) READY, BLOCKED, DEFERRED, NEEDS_PLAN` (values the grammar words); `@dataclass(frozen=True) RowRef(slot: str, note: str, id: str)`; `Claim(date: str, who: str)` with `.persona_instance_id -> str \| None` (after `persona:`); `Assignee(token: str)`; `Row(ref, title, status: Status \| None, status_date: str \| None, status_body: str, recommend: str \| None, assignee: Assignee \| None, taken: Claim \| None, rulings: tuple[str, ...], pointers: tuple[str, ...], segments: tuple[str, ...], heading: str, line_no: int, raw: str)`, `.defects: tuple[str, ...]`; `split_segments(line)` (the lint's, verbatim); `parse_row(line, *, slot, note, line_no, heading) -> Row \| None`; `parse_note(text, *, slot, note) -> list[Row]` (frontmatter / fence / continuation rules of the lint's `queue_rows`, tracking the current `##`/`###` heading); `is_queue(text) -> bool` (the lint's); `find(rows, id) -> Row \| None`; `render_status(status, date, body) -> str`; `mint_id(rand: bytes \| None = None) -> str` = `"WORK-" + base64.b32encode(rand or os.urandom(5)).decode()[:6]`; `apply(line: str, op: Op, *, who: str, date: str, payload: dict) -> str` — the pure one-line edit: `CLAIM` appends ` · **TAKEN <date> <who>**`; `RELEASE` removes the `**TAKEN …**` segment; `SET_STATUS` replaces the one status segment with `payload["status"]` and drops a trailing `Recommend:` segment unless the new status is `owner decision`; `DELETE` returns `None` (the caller drops the line); `APPEND` is not a line edit (the caller appends `payload["row"]` under the note's last heading). `Op(StrEnum)` lives here too. Regexes are the lint's (`STATUS`, `RULED`, `ASSIGNEE`, `WORK_ID`, `TAKEN = \*\*TAKEN (\d{4}-\d{2}-\d{2}) ([^*]+?)\*\*`, `RECOMMEND`). |
| `agent_runtime/work_store/board.py` | `stores` | `@dataclass(frozen=True) Board(workspace_id, slot, read_root: Path \| None, brain_dir: str \| None, default_branch: str, clone_url: str \| None, local: bool, bound_here: bool, is_default: bool)`; `brain_dir_of(root: Path, slot: dict) -> str \| None` (`slot["context"].get("brain_dir")` first; else the first of `sorted(root.glob("*_Brain/20 — Active Initiatives")) + sorted(root.glob("*_brain/20 — Active Initiatives"))`, relative, posix); `boards(workspace_id, *, read_roots: Mapping[str, Path] \| None = None) -> list[Board]` (one per `live_slots(load_document(ws))`, `bound_path(slot)`, `read_root = read_roots.get(slot) or bound path`; W2 passes the hermes worktree paths); `notes(board) -> list[Path]` (`sorted(<read_root>/<brain_dir>/*.md)` with `is_queue`); `rows(workspace_id, *, status=None, slot=None, assignee=None, read_roots=None) -> list[Row]`; `ready(workspace_id) -> list[Row]` (status READY and `taken is None`); `ids_in_brain(board) -> set[str]`; `needs_default_brain(boards) -> bool` (no board with `brain_dir`). |
| `agent_runtime/work_store/default_brain.py` | `stores` | §4: `skeleton(root) -> list[Path]`, `ensure_default_brain(workspace_id, *, issued_at: str) -> Board` (idempotent: an existing live `brain` slot returns its board), `TODO_TEMPLATE`, `QUEUE_TEMPLATE` module constants, `IDENTITY_PAIRS(machine_id) -> tuple[str, str]` shared with W2's writer (`Decided (plan):` the pairs live here; W2 imports them). |
| `agent_runtime/paths.py` (edit, fork-owned) | — | the five helpers of §4 |
| `agent_runtime/workspace_slots.py` (edit, fork-owned) | — | `declare_local_slot(...)` (§4) and the `local` arm in `normalize_declaration` |
| `agent_runtime/workspace_slots_probe.py`, `agent_runtime/workspace_slot_recipe.py`, `agent_runtime/workspace_slot_setup.py` (edits) | — | the three `local` arms of §4 |
| `Harness_Brain/30 — Decisions/0011 …md` (edit) | — | §3.1 verbatim |
| `tests/tooling/test_work_queue_row_grammar.py` (edit) | — | §3.2 |
| `tests/fixtures/work_queue/grammar_valid.md`, `grammar_defects.md` (new) | — | §3.3 port |
| `tests/fixtures/import_layers_grandfathered.json`, `size_ceiling_grandfathered.json`, `legibility_grandfathered.json`, `ladder_routing_grandfathered.json` | — | UNCHANGED (new modules declare their layer and stay under every ceiling; a lane that needs a row has over-built) |

Tests (new under `tests/agent_runtime/work_store/`, package with `__init__.py` declaring `__layers__ = {}`
is NOT needed — tests are not a layered root; a flat directory with a `conftest.py` that builds a tmp store
root via `monkeypatch.setattr(paths, "store_root", lambda: tmp)` and a fake git identity):

| test file | cases | killing mutation (expected red) |
|---|---|---|
| `test_grammar.py` | `test_every_valid_fixture_row_parses_with_no_defect`; `test_every_defect_fixture_row_is_a_defect`; `test_the_twin_agrees_with_the_lint_on_every_fixture_row` (imports `tests.tooling.test_work_queue_row_grammar.row_defects` and asserts `bool(defects)` agrees row by row); `test_apply_claim_release_set_status_round_trip`; `test_set_status_keeps_exactly_one_status`; `test_mint_id_is_work_six_base32`; `test_split_segments_never_splits_in_a_code_span`; `test_assignee_persona_instance_vs_persona_token` | `parse_row` accepts two statuses → `test_every_defect_fixture_row_is_a_defect` red; `apply(SET_STATUS)` appends instead of replacing → `test_set_status_keeps_exactly_one_status` red; `mint_id` uses base64 → `test_mint_id…` red |
| `test_board.py` | `test_boards_one_per_live_bound_slot_with_brain_dir_discovered`; `test_pinned_brain_dir_wins_over_discovery`; `test_a_slot_without_a_brain_lists_as_no_brain`; `test_rows_keyed_slot_id_never_collide_across_repos` (two slots, same `RT-A`); `test_ready_excludes_taken`; `test_unbound_slot_is_listed_not_read` | union by `(slot, id)` collapses to `id` → `test_rows_keyed…` red; `ready` ignores `taken` → red |
| `test_default_brain.py` | `test_skeleton_writes_todo_and_queue_with_frontmatter`; `test_ensure_default_brain_inits_commits_declares_and_binds` (real `git`, tmp store, `machine_id` patched); `test_ensure_is_idempotent`; `test_a_workspace_with_a_brain_slot_gets_none`; `test_declare_local_slot_keeps_the_other_slots` (positive control against `declare`'s replace semantics); `test_server_bound_realm_without_credential_refuses_needs_publish_right` | `ensure_default_brain` calls `declare([brain])` → `test_declare_local_slot_keeps_the_other_slots` red; skeleton omits `type: queue` → `test_skeleton…` red |
| `tests/agent_runtime/test_workspace_slots.py` (edit) | add `test_a_local_slot_round_trips_normalize_declaration` and the `local` clone refusal in `tests/agent_runtime/test_workspace_slot_clone.py` | `normalize_declaration` drops `local` → red |

W1 hands W2: `grammar.apply` / `parse_note` / `find`, `Board` with `read_root`, `IDENTITY_PAIRS`,
`ensure_default_brain`, the `Reason` enum, the path helpers.

### 6.2 W2 — the writer and the RPC (`RT-WORK-W2-WRITER`; one CHANGE commit, then one DELETE commit)

Commit A (CHANGE) files:

| file | layer | contents |
|---|---|---|
| `agent_runtime/work_store/writer.py` | `stores` | `@dataclass(frozen=True) RowOp(ref: RowRef, op: Op, who: str, request_id: str, payload: Mapping[str, Any] = field(default_factory=dict))`; `Receipt(ref, op, who, request_id, commit: str \| None, replays: int, pushed: bool, replayed: bool, kind: str)` with `.wire()`; `class Writer: __init__(self, board: Board, *, machine_id: str, run: Callable = run_git, now: Callable[[], datetime] = …, replay_budget: int = 8)`; `sync(self) -> Path` (steps 0–3; returns the worktree path; used by reads); `apply(self, op: RowOp) -> Receipt` (steps 0–9); `history(self, ref) -> dict \| None` (`git log -n 1 --format=%H%n%ct%n%B -S"`<ID>`" <tip> -- <note>` → `{commit, at, subject, body}`; the deleting commit of a gone row); `note_committed_at(self, note) -> int \| None`; private steps `_prune_and_add_worktree`, `_fetch`, `_reset`, `_replayed(request_id)`, `_edit(note_text, op) -> str` (uses `grammar`), `_commit`, `_push`; the op → precondition table is a `dict[Op, Callable]`; the failure → reason table of §5 is a `dict[str, Reason]` keyed on stderr markers (`"! [rejected]"`, `"fetch first"`, `"does not appear to be a git repository"`, `"Could not read from remote"`, `"couldn't find remote ref"`). Receipts: `work.row_append \| row_claim \| row_release \| row_set_status \| row_delete` emitted through `receipts.emit`. |
| `agent_runtime/work_store/receipts.py` | `models` | `emit(kind: str, **fields) -> dict` → `logging.getLogger("agent_runtime.work_store.receipts").info("%s", json.dumps({"kind": kind, "at": …, **fields}, sort_keys=True))`; the serve log is the receipt log (CLAUDE.md: observability is log receipts, never envelope keys). |
| `agent_runtime/work/model.py` (edit) | `models` | `Reason` becomes `from agent_runtime.work_store.reasons import Reason, WorkRefused` (re-export, old values kept); `WorkScope` becomes `WorkScope(install: str, workspace_id: str)` with `.owner = fingerprint([install, workspace_id])` and `.wire(label) = {"owner", "workspace_id", "label", "operations": OPERATIONS}` where `OPERATIONS = ("inspect", "start", "assign", "claim", "release", "set_status", "done", "create_brain")`; `text`, `fingerprint` unchanged. |
| `agent_runtime/work/context.py` (edit) | `lanes` | `WorkContext(session, profile, can_start, assignee: str \| None = None)`; `.wire()` gains `"assignee"`; `_operator` returns `WorkContext(session, None, True, assignee=f"persona:{reference['persona_instance_id']}")` (the refusing comment goes); `_native` unchanged (assignee None). |
| `agent_runtime/work/service.py` (edit) | `lanes` | `execute` unchanged in shape; `_work_capabilities(install)` → `{"version": 2, "install_id", "execution_identity_guard": True, "chat_scopes": True, "owners": [scope.wire(workspace.name) for every OfficeStore().list_workspaces() ∪ {DEFAULT_WORKSPACE_ID}], "default_brain": {ws: {"state": "present" \| "created" \| "needs_publish_right"}}, "limitations": ["Claims and write-backs land as git commits in Eternia Harness's own worktree; the operator's checkout sees them after a pull."]}` — it calls `ensure_default_brain` for each workspace whose boards need one and records the state; `_scoped_work_request`: owner lookup by `WorkScope(install, ws).owner`; the operation table is `dict[str, Callable]` → `store.py` functions below. `version` 2 because the owner shape changed (`board/profile` gone); the launcher's catalog checks `version != 1` → W4 accepts 2 (§6.4). |
| `agent_runtime/work/store.py` (new; replaces `native.py`) | `stores` | the operations over `Board`/`Writer`: `list_work(scope, params, *, context)`, `inspect(scope, params, *, context)`, `start(scope, params, actor, *, context)`, `assign`, `claim`, `release`, `set_status`, `done`, `create_brain`; `project(row, board, *, context, detail=False) -> dict` (the wire row below). |
| `agent_runtime/work/rpc.py` (edit) | `lanes` | the loop names the eleven operations (`capabilities, context, list, inspect, start, assign, claim, release, set_status, done, create_brain`); `_work_reply` unchanged (`WorkRefused` → 4090 `{"reason": refusal.reason, "detail": refusal.detail}`). |
| `agent_runtime/work/__init__.py` (edit) | — | docstring: `model: wire scope and refusals; store: the board and writer adapters; service: authorization and scope checks; rpc: registration. No scheduler, worker or task database lives here.` |
| `scripts/work_row.py` (new, flat script, not layered) | — | `python scripts/work_row.py <claim\|release\|set-status\|delete\|append> <ID> --who <lane> [--note <path>] [--status "<segment>"] [--row "<line>"] [--repo <checkout>] [--no-commit]`: finds the row by ID across the checkout's `*_Brain/20 — Active Initiatives/*.md` (or `--note`), applies `grammar.apply`, writes, `git add -- <note>`, `git commit -m "queue: <OP> <ID> <who>"` (the SESSION's identity, no `-c`), `git push`; exit 3 on a non-fast-forward with the one-line hint "fetch, then re-run"; never `fetch`, `reset`, `stash` on the session's checkout. |
| `tests/agent_runtime/serve_rpc_manifest.expected.json` (edit) | — | add `runtime.work.assign`, `.claim`, `.release`, `.set_status`, `.done`, `.create_brain` to the sorted name list and the tier map (`"console"`); regenerate with the fixture's own writer: `python -m tests.agent_runtime._serve_rpc_manifest --write` (the test venv's python). |
| `docs/agent-runtime-harness/03-transport-and-wire.md` (edit) | — | `## Native Work methods` and `### Conversation-scoped Work` rewritten to the table below (the kanban paragraphs go). |
| `docs/agent-runtime-harness/06-office-and-board.md` (edit) | — | new `## The todo board` before `## The board — method twins…`: the model of §2, the write path of §5 in six lines, the receipts. |

The RPC contract (all `TIER_CONSOLE`, all deferred through `spawn_reply`; every call carries `install_id`,
`client_scope`, and — except `capabilities` / `context` — `owner`; replies carry `version: 2, install_id,
owner`):

| method | params beyond scope | reply | typed refusals (`Reason`) |
|---|---|---|---|
| `runtime.work.capabilities` | — | `owners[]`, `default_brain{}`, `limitations[]`, `chat_scopes`, `execution_identity_guard` | `DENIED`, `UNAVAILABLE` (no install id) |
| `runtime.work.context` | `conversation` | `scopes`, `agent_profile`, `assignee`, `can_start` | `INVALID`, `OWNER_CHANGED` |
| `runtime.work.list` | `slot?`, `status?` (grammar word), `assignee?` (`persona:<token>`), `view?` (`all \| conversation`), `conversation?`, `stale_ok?: bool` | `boards[] {slot, brain_dir, bound_here, local, is_default, default_branch, committed_at}`, `rows[] (projection)`, `cursor: null`, `read_at`, `stale: bool` | `OWNER_CHANGED`, `FETCH_FAILED` (unless `stale_ok`) |
| `runtime.work.inspect` | `slot`, `task_id` | `task: projection \| null`, `ending: {commit, at, subject, body} \| null` (the deleting commit when `task` is null) | `OWNER_CHANGED`, `SLOT_UNBOUND` |
| `runtime.work.start` | `request_id`, `title` (≤160), `body` (≤50000, the `WorkBrief` JSON instruction), `slot?` (default: the default brain, else the first board with a brain), `note?` (default: the board's first queue note), `assignee?` (`persona:<token>`), `conversation?` | `task: projection`, `disposition: "accepted"`, `receipt` | `INVALID`, `ID_EXISTS` (never: minted), `NO_BRAIN`, `SLOT_UNBOUND`, `ASSIGNEE_UNKNOWN`, `PUSH_CONTENDED`, the git reasons of §5 | 
| `runtime.work.assign` | `request_id`, `slot`, `task_id`, `assignee` (`persona:<token>` or `null` to clear) | `task`, `receipt` | `ROW_GONE`, `ASSIGNEE_UNKNOWN`, git reasons |
| `runtime.work.claim` | `request_id`, `slot`, `task_id`, `who` (`persona:<instance_id>`; defaults to `context.assignee`) | `task`, `receipt` | `ROW_GONE`, `ALREADY_TAKEN`, `ASSIGNEE_UNKNOWN`, git reasons |
| `runtime.work.release` | `request_id`, `slot`, `task_id`, `status?` (a full status segment; default: the row keeps its status) | `task`, `receipt` | `ROW_GONE`, `NOT_CLAIMANT` (the operator — `caller.kind` stdio owner / local console — overrides as `who="operator"`), git reasons |
| `runtime.work.set_status` | `request_id`, `slot`, `task_id`, `status` (full segment, validated by `grammar`) | `task`, `receipt` | `ROW_GONE`, `GRAMMAR_INVALID`, `NOT_CLAIMANT`, git reasons |
| `runtime.work.done` | `request_id`, `slot`, `task_id`, `result` (≤4000, one paragraph) | `ending`, `receipt` | `ROW_GONE`, `NOT_CLAIMANT`, git reasons |
| `runtime.work.create_brain` | `request_id`, `slot?` (omitted = the default brain), `credential?` | `board`, `receipt` | `NEEDS_PUBLISH_RIGHT`, `SLOT_UNBOUND`, git reasons |

`start` mints `WORK-<6>` and writes the row `- **`<ID>` — <title>** · brief: `<Brain>/50 — Agent Handoffs/work/<ID>.md`
· [assignee: persona:<token> ·] READY <date>` as ONE `APPEND` op whose payload also carries the brief
note (`{"row": line, "files": {"50 — Agent Handoffs/work/<ID>.md": body}}` — the writer adds every payload
file in the same commit; `Decided (plan):` a short start with an empty body writes no brief note and no
`brief:` segment). The idempotency key is `request_id` (step 4); a replay returns the same row.

Assignee resolution (`store.py::resolve_assignee(token) -> Assignee`): `PersonaInstanceStore().get(token)`
succeeds → an instance; else the token equals the `persona_id` of at least one instance in
`PersonaInstanceStore().list_all()` → "any instance" of that persona; else `ASSIGNEE_UNKNOWN` (a persona
with no instance cannot be worked, so the instance store is the one lookup).

Wire row (`store.py::project`): `{id, slot, note, line, title, status (grammar word: "READY" | "BLOCKED" |
"DEFERRED" | "NEEDS PLAN" | "TAKEN" when claimed), status_word, status_date, status_body, recommend,
assignee, taken: {date, who, persona_instance_id} | null, rulings[], pointers[], heading, raw, body (the
brief note text when a `brief:` pointer names one and detail=True, else ""), body_truncated, result "",
result_truncated false, in_conversation (taken.who == context.assignee), updated_at (the note's
`committed_at`), revision (fingerprint of the row minus revision)}`.

Commit B (DELETE, `RT-WORK-PROFILE-OWNERS` lands): delete `agent_runtime/work/native.py`;
`tests/agent_runtime/test_no_kanban_dependency.py` back to the blanket prohibition — `_native_work_import`
and `test_native_adapter_admits_only_the_two_public_doors` deleted, the `and not _native_work_import(...)`
clause removed; its killing mutation is `import hermes_cli.kanban_db` anywhere under `agent_runtime/`
(recorded by adding the line to `work/store.py`, running the one file, reverting).

Tests:

| test file | cases | killing mutation |
|---|---|---|
| `tests/agent_runtime/work_store/test_writer.py` (real `git` in `tmp_path`: a bare `origin.git`, a clone bound as the slot, the hermes worktree; a second clone plays "the other machine") | `test_claim_lands_as_one_commit_pushed_fast_forward`; `test_a_raced_claim_replays_and_exactly_one_taken_exists` (the second clone pushes a different row's edit between fetch and push → replay → one `TAKEN`; then a second claimant → `already_taken`); `test_row_landed_meanwhile_answers_row_gone`; `test_not_claimant_and_operator_override`; `test_append_refuses_an_existing_id`; `test_replay_by_request_id_returns_the_recorded_commit`; `test_push_contended_after_eight_replays` (a fake `run` that always rejects); `test_fetch_failure_is_typed_and_writes_nothing`; `test_slot_unbound_and_remote_missing`; `test_a_local_slot_skips_fetch_and_push`; `test_dirty_worktree_is_cleaned_once_then_refused`; `test_stale_worktree_registration_is_pruned`; `test_the_clone_index_and_tree_never_change` (hash the clone's index + a staged file before/after); `test_commit_identity_is_hermes_via_c_pairs_not_config` (reads `git log --format=%an %ae` and asserts `.git/config` has no `user` section); `test_grammar_invalid_note_is_never_edited` | step 8 uses `push --force` → `test_a_raced_claim…` red; identity written with `git config` → `test_commit_identity…` red; step 5 reads a cached tree instead of the tip → `test_row_landed_meanwhile…` red; replay budget unbounded → `test_push_contended…` red |
| `tests/agent_runtime/test_work_service.py` (rewritten; the kanban fixture goes) | `test_capabilities_lists_one_owner_per_workspace_and_creates_the_default_brain`; `test_start_mints_a_work_id_and_replays_by_request_id`; `test_claim_release_set_status_done_through_the_writer`; `test_operator_reference_is_the_assignee`; `test_unknown_caller_and_wrong_install_refuse`; `test_inspect_of_a_gone_row_carries_its_ending`; `test_list_filters_slot_status_assignee`; `test_refusals_are_typed_and_leak_nothing` | owner keyed by profile again → `test_capabilities…` red; `inspect` returns `{task: None}` without `ending` → red |
| `tests/agent_runtime/test_work_rpc.py` (edit) | the loop names eleven operations; `test_work_refusal_carries_reason_and_detail` | a method missing from `register` → the manifest test (`tests/agent_runtime/_serve_rpc_manifest.py`) red |
| `tests/tooling/test_work_row_script.py` (new) | `test_claim_by_id_commits_by_pathspec_and_pushes`; `test_non_fast_forward_exits_3_and_touches_nothing_else`; `test_never_fetches_or_resets` (a recording fake `git`) | the script runs `git fetch` → red |
| `tests/agent_runtime/test_no_kanban_dependency.py` (edit) | as above | as above |

W2 hands W3: `Writer.apply` / `sync` / `history`, `store.py::project`, `resolve_assignee`, the RPC
`claim` whose `receipt` W3's tick reads; the serve's `capabilities` creating default brains.

### 6.3 W3 — the engine (`RT-WORK-W3-ENGINE`; one CHANGE commit)

The EXECUTOR contract is the dispatcher plan's § 2.2, verbatim; W3 creates the file, B3 extends it.

| file | layer | contents |
|---|---|---|
| `agent_runtime/work_store/executor.py` | `lanes` | `ExecutorKind(StrEnum) PERSONA_TURN, BATCH_LANE`; `GoalMode(StrEnum) NONE, UNTIL_DONE`; `RunStatus(StrEnum) QUEUED, RUNNING, SETTLED, STOPPED`; `Verdict(StrEnum) DONE, BLOCKED, STOPPED, FAILED`; `StopReason(StrEnum) OPERATOR, DRAIN, CAP`; `@dataclass(frozen=True) Brief(title, objective, inputs, constraints, acceptance)`; `Assignment(rows: tuple[RowRef, ...], persona_instance_id: str, brief: Brief, request_id: str, heavy: bool = False, goal_mode: GoalMode = GoalMode.NONE)`; `RowEnding(verdict: Verdict, result: str = "", question: str = "", recommend: str = "", reason: str = "")`; `Outcome(verdict, per_row: Mapping[RowRef, RowEnding], report: str, tool_calls: int \| None, commits: tuple[str, ...])`; `Run(run_id, request_id, assignment, root_session_id, client_message_id, started_at, status)`; `class Executor(Protocol): kind; can_start(a) -> Reason \| None; start(a) -> Run; status(run_id) -> RunStatus; stop(run_id, reason) -> dict; on_settle(cb) -> None`. |
| `agent_runtime/work_store/persona_turn.py` | `lanes` | `PersonaTurnExecutor(Executor)`: `__init__(self, *, enqueue=chat_root_send_queue.enqueue, wake=wake_queued_send_runner, open_chat=run_open_chat, instances: PersonaInstanceStore \| None = None, root_of=resolve_default_chat_session_id_for_instance)`; `can_start(a)`: instance missing → `PERSONA_UNAVAILABLE` (new `Reason` value `persona_unavailable`), `instance.runtime_root != this runtime's root` → `PERSONA_UNAVAILABLE`, drain begun (`session.drain_state is not None`, read through the serve's `liveness`) → `DRAIN_BEGUN`, `a.goal_mode is UNTIL_DONE` → `GOAL_MODE_UNSUPPORTED` (B3 lifts it), else `None`; `start(a)`: `root = root_of(...)` or, when None, `run_open_chat(SimpleNamespace(persona_id, persona_instance_id, json=True, stream=False))` → `payload["session_id"]`; `cmid = f"work-{a.request_id}"`; `args = forge-shaped namespace` (the fields `forge_delivery_turn` sets, with `message = render_brief(a)`, `requested_by = {"kind": "work", "request_id": a.request_id}`, `intent_hint="chat"`); `enqueue(root, cmid, persistable_args(args, origin={"owner": None, "gateway": False, "work": a.request_id}))`; `wake()`; returns `Run(status=QUEUED)`; `status(run_id)`: `read_settle(settle_id_for(root, cmid))` → `SETTLED` if a record exists, else `RUNNING` if `chat_root_send_queue.find(root, cmid)` is in state running, else `QUEUED`; `stop(run_id, reason)`: `chat_root_send_queue.remove(root, cmid)` when still queued (returns `{"stopped": True}`), else `{"stopped": False, "detail": "the turn ends on its own"}` (RULED: stop waits); `on_settle(cb)`: stores `cb`; `settled(entry: QueuedSend, exit_code: int, payload: dict \| None)` is the hook the runner calls (below) — it parses `payload["reply"]` with `parse_work_report` and calls `cb(run, outcome)`. `render_brief(a) -> str` (≤ 40 lines: the row line(s) verbatim, each pointer, the brief fields, and the closing instruction: "End your reply with a fenced code block whose info string is `work_report`, carrying `verdict: done\|blocked\|stopped`, `result:` one line, and for blocked `question:` + `recommend:`"); `parse_work_report(reply: str) -> RowEnding \| None` (the LAST fenced `work_report` block; key: value lines; unknown verdict → None). |
| `agent_runtime/work_store/engine.py` | `lanes` | `RunRecord(request_id, ref: RowRef, workspace_id, persona_instance_id, root_session_id, client_message_id, started_at, state)` persisted as `<work_runs_dir(ws)>/<request_id>.json` (atomic write; the whole in-memory state is rebuilt from these on boot); `WorkEngine.__init__(self, *, executor: Executor, writer_for: Callable[[Board], Writer], boards=board.boards, instances=PersonaInstanceStore, workspaces=OfficeStore().list_workspaces, cap_for: Callable[[str], int] = lambda ws: WorkspaceStore().get(ws).max_concurrent_lanes or 4, now=…)`; `tick(self) -> dict[str, int]` — three phases, in order: (1) `_settle_pending()`: for each `RunRecord` with `executor.status(run) is SETTLED` and no outcome yet (the serve was down when it settled) → `Outcome(FAILED, …)` → write-back; (2) `_start_claimed()`: for each workspace, `writer.sync()` then `board.rows(ws, read_roots=…)`; for each row with `taken` whose `who` opens `persona:` and whose `ref` has no `RunRecord`, build `Assignment(rows=(ref,), persona_instance_id, brief=Brief from the row + its `brief:` note, request_id=f"{ws}:{slot}:{id}:{taken.date}")`, `executor.can_start` → `None` and `running(ws) < cap_for(ws)` → `executor.start` → `RunRecord`; a refusal is a receipt `work.run_refused {ref, reason}` and the row is left as is (the operator sees it in the Activity surface — doc 06); (3) `_reap()`: delete `RunRecord`s whose row is gone and run settled. `on_settle(run, outcome)` (registered on the executor): the write-back table `dict[Verdict, Callable]`: `DONE → writer.apply(RowOp(ref, DELETE, who, request_id+":done", {"result": ending.result}))`; `BLOCKED → SET_STATUS(render_status(BLOCKED, date, f"owner decision — {question} · Recommend: {recommend}"))` then `RELEASE`; `STOPPED → RELEASE` then `SET_STATUS(DEFERRED, date, f"stopped — {reason}")`; `FAILED → RELEASE` then `SET_STATUS(NEEDS_PLAN, date, f"work run {request_id} ended without a readable work_report ({detail}); re-claim to retry")`; each a separate `RowOp` with a derived `request_id` so a replay cannot double-apply; receipts `work.run_start \| run_settle \| run_refused \| engine_tick {ws, counts}`. `start_work_engine(*, stop_event: threading.Event, interval_s: float = 15.0, engine: WorkEngine \| None = None) -> threading.Thread` — a daemon thread looping `engine.tick()` until `stop_event`, every exception logged and swallowed per tick (the lens poller's shape). |
| `agent_runtime/chat_root_send_runner.py` (edit, fork-owned, additive) | `stores` | `RunnerPolicy` gains `on_settle: Callable[[queue.QueuedSend, int, dict \| None], None] \| None = None`; `_run_entry` calls `policy.on_settle(entry, exit_code, payload)` right after `_settle(...)` for a terminal (non-queued) outcome, inside a `try/except Exception: logger.warning(...)`. |
| `hermes_cli/harness_parts/serve/queued_turns.py` (edit, fork-owned) | — | `queued_turn_runner_policy(session)` passes `on_settle=session.work_executor.settled` when `session.work_executor` is set (built before the runner starts). |
| `hermes_cli/harness_parts/serve/session.py` (edit, fork-owned) | — | after the queued-send runner and before the lens poller: build `self.work_executor = PersonaTurnExecutor()`, `self.work_engine = WorkEngine(executor=self.work_executor, writer_for=…)`, `start_work_engine(stop_event=self.liveness_stop, engine=self.work_engine)`; the same `try/except … warning("work engine did not start; claimed rows wait for the next serve")` shape as the lens poller; skipped when `not shipped("agent_runtime.work")` (the phone). |
| `agent_runtime/work_store/reasons.py` (edit) | — | add `PERSONA_UNAVAILABLE="persona_unavailable"`, `DRAIN_BEGUN="drain_begun"`, `GOAL_MODE_UNSUPPORTED="goal_mode_unsupported"`, `CAP_REACHED="cap_reached"`, `EXECUTOR_BUSY="executor_busy"`, `DOOR_UNBOUND="door_unbound"` (the dispatcher § 2.2 names; `WORKTREE_FAILED` already exists). |

`Decided (plan):` the engine runs in the serve only (one writer per machine); `runtime.work.claim` does
not call the engine — the next tick (≤ 15 s) hands off, which keeps the RPC lane free of turn cost. The
engine never auto-claims READY rows (RULED claim-only); a per-workspace `auto_claim` setting is a later row.
`Decided (plan):` one row per `Assignment` in W3 (the dispatcher's thick lanes come with B2's planner).

Tests:

| test file | cases | killing mutation |
|---|---|---|
| `tests/agent_runtime/work_store/test_engine.py` (a fake `Executor` recording calls, a fake `Writer` recording `RowOp`s, a tmp store) | `test_tick_starts_a_run_for_each_persona_claimed_row_and_none_for_a_lane_claim` (`TAKEN … r-x` ignored); `test_tick_never_claims_a_ready_row` (claim-only); `test_cap_limits_running_per_workspace`; `test_a_refused_start_leaves_the_row_and_emits_a_receipt`; `test_done_deletes_blocked_sets_owner_decision_stopped_defers_failed_needs_plan` (the four write-back shapes, exact status segments asserted through `grammar`); `test_write_backs_use_derived_request_ids_so_a_replay_cannot_double_apply`; `test_a_run_settled_while_down_is_failed_on_boot` (a `RunRecord` + a settle record, no callback); `test_run_records_rebuild_state_after_restart` | phase order swapped (start before settle) → `test_a_run_settled_while_down…` red; engine claims READY rows → `test_tick_never_claims…` red; BLOCKED write-back omits `Recommend:` → `test_done_deletes_…` red (the segment would fail the lint's owner-decision rule, asserted via `grammar`) |
| `tests/agent_runtime/work_store/test_persona_turn.py` | `test_start_enqueues_on_the_instance_root_with_a_work_origin_and_wakes`; `test_no_root_opens_a_chat_through_the_door`; `test_can_start_refuses_missing_instance_other_root_drain_and_until_done`; `test_settled_parses_the_last_work_report_block`; `test_unparsable_reply_is_failed`; `test_stop_removes_a_queued_send_and_waits_on_a_running_turn`; `test_render_brief_is_under_forty_lines_and_names_the_row_and_pointers` | `start` calls `run_mission_chat_turn` directly → `test_start_enqueues…` red (the dispatcher plan's `test_busy_root_queues_never_steers`, owned here first) |
| `tests/agent_runtime/test_busy_root_send_queue.py` (edit) | `test_on_settle_is_called_once_after_a_terminal_settle_and_not_for_queued` | `on_settle` called before `_settle` or for `queued: True` → red |

W3 hands B3: `PersonaTurnExecutor` with `goal_mode` refusing `UNTIL_DONE`; `executor.py` as the contract.

### 6.4 W4 — the launcher (`MC-WORK-W4-BOARD`; one CHANGE commit, launcher repo)

Exact dart files:

| file | change |
|---|---|
| `lib/features/mission_control/work_queue/policy/work_queue_row_parser.dart`, `work_queue_row.dart` | §3.3 |
| `lib/features/mission_control/work_queue/data/work_queue_source.dart` | `WorkQueueRepo` enum → `final class WorkQueueBoardSlot { slot, label, brainDir, boundHere, local, isDefault, defaultBranch, committedAt }` (`fromWire(Map)` from `runtime.work.list`'s `boards[]`; `label` = the slot name, `Work` for the default); `WorkQueueRepoLocator` → `abstract interface class WorkQueueBoardsLocator { Future<WorkQueueBoardsLocation> boards({required String? workspaceId}); }` with `WorkQueueBoardsLocated(List<WorkQueueBoardSlot>) \| WorkQueueBoardsUnavailable(reason)`; `WorkQueueSource.read` → `Future<WorkQueueBoardRead> read({required String workspaceId, required String slot})` returning `WorkQueueBoardRead(rows: List<Map<String, Object?>>, notes: List<String>, readAt, stale)`; `LocalWorkQueueSource` DELETED (the grammar gate reads the vault with `dart:io` itself); new `RuntimeWorkQueueSource` in `lib/features/mission_control/work_queue/data/runtime_work_queue_source.dart` over `MissionWorkClient.list`. |
| `lib/features/mission_control/data/rpc/mission_work_rpc.dart` (new), `lib/features/mission_control/data/mission_work_client.dart` (new) | the wire types `MissionWorkBoardWire`, `MissionWorkRowWire` (every field of §6.2's projection), `MissionWorkReceiptWire`; `MissionWorkClient { list, inspect, claim, release, assign, setStatus, done, createBrain }` returning `MissionWorkOutcome<T> = Answered \| Refused(reason, detail) \| Unavailable`, the `MissionWorkspaceSlotsClient` shape. |
| `lib/features/mission_control/data/rpc/mission_workspace_slots_rpc.dart` | `MissionSlotDeclarationWire` gains `local` (bool, default false) and round-trips `repo.local`; `cloneUrl` may be empty when `local`. |
| `lib/app/mission_control/work_queue_locator_binding.dart` | `SlotsWorkQueueRepoLocator` → `RuntimeWorkQueueBoardsLocator` over `MissionWorkClient.list(workspaceId)`'s `boards[]`; `workQueueOverrides()` also overrides `workQueueSourceProvider` with `RuntimeWorkQueueSource`; the `supports('runtime.work.list')` manifest check is the gate (unsupported → `WorkQueueBoardsUnavailable('This Eternia Harness cannot serve the todo board yet')`). |
| `lib/features/mission_control/work_queue/state/work_queue_board_provider.dart` | `WorkQueueBoardKey(workspaceId, slot: String)`; `loadWorkQueueBoard({locator, source, key})` parses `rows[].raw` with `WorkQueueRowParser.parseLine` (the grammar owner stays the parser; the runtime's structured fields are cross-checked only for `id` and the board shows a `Defect` chip when they disagree); `WorkQueueBoardSelection.repo` → `.slot`; `switching slot clears the filter` (the existing test's rule). |
| `lib/features/mission_control/work_queue/widgets/work_queue_filters.dart` | `WorkQueueRepoSwitcher` → `WorkQueueSlotSwitcher` (`SegmentedButton<String>` over the located boards; a `brainDir == null` board renders disabled with tooltip "no brain"; `!boundHere` renders "not on this machine"). |
| `lib/features/mission_control/work_queue/widgets/work_queue_card.dart` | an assignee chip (`persona:<token>` resolved to the instance's `display_name` through the existing roster provider, else the token) and the `TAKEN persona:` claim rendered as "Working: <display_name>". |
| `lib/features/mission_control/work_queue/widgets/work_queue_card_actions.dart` | `WorkQueueCardMenu` gains `Claim for <persona>` (a submenu over the workspace's persona instances → `MissionWorkClient.claim`) and `Release` (→ `.release`; shown only on a `TAKEN persona:` row); each action confirms in a one-line dialog and shows the refusal `reason` on failure; no launcher commit (D6 holds). |
| `packages/agents/eternia_hermes_adapter/lib/src/work/hermes_work_projection.dart` | `_states` → `{'READY': queued, 'TAKEN': running, 'BLOCKED': needsInput, 'NEEDS PLAN': needsInput, 'DEFERRED': needsInput}` with `_labels` in the board's words; the `assignee != profile` throw DELETED; a null `task` with an `ending` → `succeeded` with `output = ending.body`; a null `task` without → `unknown`. |
| `packages/agents/eternia_hermes_adapter/lib/src/work/hermes_work_backend.dart`, `hermes_work_catalog.dart` | `connect` accepts `version == 2`; `fromWire` reads `workspace_id` instead of `profile`; `operations` maps the eight words to `WorkExperienceOperation` (`assign`, `release` new; `redirect`, `cancel`, `retry` stay unsupported); `start` sends `slot`, `note`, `assignee`; new `assign(id, assignee)`, `release(id)`. |
| `packages/work/eternia_work_experience/lib/src/work_models.dart` | `WorkExperienceOperation` gains `assign, release`; `WorkStartRequest` gains `slot`, `note`, `assignee` (all nullable). |
| `lib/shared/work/work_assignment_sheet.dart`, `work_assignment_menu.dart` | destination = workspace (owner) + a persona-instance dropdown (`display_name`, from the roster) + a target queue dropdown (board slot + note, default the default brain). |
| `Launcher_Brain/30 — Decisions/0025 …md`, `test/fixtures/work_queue/grammar_valid.md`, `grammar_defects.md` | §3.3 |
| `lib/features/mission_control/work_queue/MAP.md` | the table rows for `data/` and `widgets/` rewritten (slot-driven, runtime source, two write actions). |

Launcher tests: `test/features/mission_control/work_queue/work_queue_row_parser_test.dart` (+ group
`assignee`: valid, bad shape, two segments, `persona:` claim id; group `ID`: `WORK-A2B3C4` passes,
`WORK-ABCDE` is `idDefect`); `work_queue_source_test.dart` (rewritten: `WorkQueueBoardSlot.fromWire`,
`RuntimeWorkQueueSource` over a fake client, unavailable when the manifest lacks `runtime.work.list`);
`work_queue_board_provider_test.dart` (key by slot; a stale read is loaded with `stale`; switching slot
clears the filter); `work_queue_board_panel_test.dart` (slot switcher; "no brain" disabled; assignee chip;
Claim / Release menu items present only when they apply; a refused claim shows its reason);
`packages/agents/eternia_hermes_adapter/test/hermes_work_test.dart` (the five md statuses; a gone row
with an ending is succeeded; no throw on a foreign assignee); `test/shared/work/work_assignment_menu_test.dart`
(destinations = workspaces × personas); `test/architecture/work_queue_status_grammar_test.dart` runs
unchanged over the new fixtures. Killing mutations: parser accepts `assignee: bob` → the defects fixture
test red; `_states` keeps `'done'` and drops `'TAKEN'` → `hermes_work_test` red; `WorkQueueCardMenu` calls
`claim` without the manifest check → the panel test's refused-claim case red.

### 6.5 W5 — the kanban retirement (`RT-WORK-W5-KANBAN-RETIRE`; one DELETE commit in W2's batch)

Delete: `hermes_cli/kanban_blocked_pm.py`, `hermes_cli/kanban_blocked_pm_tick.py`,
`hermes_cli/kanban_crash_evidence.py`; in `plugins/eternia-harness/__init__.py` the functions
`route_blocked_kanban_cards`, `record_kanban_crash_evidence` and the two `ctx.register_hook("on_kanban_…")`
lines (the comment block above them about the claim TTL stays if it names anything else; else goes);
the five fork-only tests `tests/hermes_cli/test_kanban_blocked_pm_hook.py`, `test_kanban_blocked_pm_tick.py`,
`test_kanban_db_crashed_workers_downstream.py`, `test_kanban_db_downstream.py`,
`test_kanban_write_guard_downstream.py`; `tests/_downstream/conftest_plugin.py::_kanban_guard_denies_recorded_root`
(and the `_kanban_write_guard` fixture it depends on ONLY if nothing else uses it — `Decided (plan):`
grep first; keep what another fixture names); fixture rows
`tests/fixtures/import_layers_grandfathered.json` `hermes_cli/kanban_crash_evidence.py|…|_pid_alive` and
`tests/fixtures/process_globals_allowlist.json` `hermes_cli/kanban_blocked_pm_tick.py|_cursors` (their
gates red on a stale row — `test_a_fixed_site_loses_its_row`, `test_process_globals_declared` — which is
the proof the deletion reached them). `tests/fixtures/upstream_footprint.json`'s `reason` text that names
`kanban_blocked_pm_tick.py` is prose on an upstream-file row and stays (it records why that seam was taken;
the footprint lane may reword it). `REGISTRY_HYGIENE_BLOCKED_TOOLSETS` keeps `kanban`; the `unused: kanban`
skip rows in `tests/fixtures/upstream_skip_list.txt` stay right; ADR 0015's "kanban unused" then holds
for fork code (one sentence appended to the ADR). No existing test asserts the plugin's hook list (checked:
`grep -rn on_kanban tests/` hits only the deleted files and `tests/plugins/test_kanban_dashboard_task_updated_hook.py`,
an upstream test about another hook), so W5 adds ONE gate, `tests/plugins/test_eternia_harness_registers_no_kanban_hook.py`:
a recording `ctx` (the `register_hook(self, name, _callback)` stub shape of
`tests/plugins/test_security_guidance_plugin.py`) is passed to the plugin's `register`, and the recorded hook
names contain no name opening `on_kanban_`; its positive control asserts `pre_tool_call` IS recorded (the
walk saw the real list). Killing mutation: re-add one `register_hook("on_kanban_…")` line → that gate red;
re-add `import hermes_cli.kanban_db` under `agent_runtime/` → `test_no_kanban_dependency` red (the W2-B gate).

## 7. Order, parallelism, hand-offs, what `--affected` picks up

- **Batch 1: W1** (one CHANGE). Landing gate once. Hands W2 the store API (§6.1).
- **Batch 2: W2-A (CHANGE) → W2-B (DELETE) → W5 (DELETE)**, three commits, one landing gate. W2-A must
  land before W2-B (`service.py` stops importing `native.py` in A; B deletes it). W5 after W2-B so
  `test_no_kanban_dependency`'s blanket prohibition is already the rule when the last fork kanban module
  goes. Hands W3 the writer and the RPC; hands W4 the wire (`version: 2`, the eleven methods, the
  projection, `boards[]`).
- **Batch 3: W3 ∥ W4** — different repos, no shared file; W4 reads W2's landed wire from `origin/main`
  (`git show`), never a branch. One landing gate per repo.
- Then the dispatcher plan's B1 (extends `reasons.py` / `executor.py`) → B2 / B4 → B3 → B5 → B6.
- `--affected` (`scripts/run_tests_bundled.sh --affected`, `Running the tests.md`) selects: every edited
  or NEW test file (untracked files count), each recorded test whose imports reach a changed module
  within two hops — for W1/W2 that is `tests/agent_runtime/test_workspace_slots.py`,
  `test_workspace_slot_clone.py`, `test_workspace_slot_recipe.py`, `test_realm_sync_workspace_slots.py`
  (through `workspace_slots.py`), `test_work_rpc.py`, `test_work_service.py`, the manifest test
  (`_serve_rpc_manifest.py` through `serve_rpc/registry.py`), the tooling gates (`test_fork_import_layers.py`,
  `test_downstream_size_ceiling.py`, `test_function_legibility_floor.py`, `test_no_ladder_routing.py`,
  `test_process_globals_declared.py` through the fixture change, `test_work_queue_row_grammar.py` through
  the vault edit); for W3 `test_busy_root_send_queue.py` (through `chat_root_send_runner.py`) and the serve
  session tests reached from `hermes_cli/harness_parts/serve/session.py`; for W5 the plugin registration
  tests. A session-chain or dynamic-import reach is not selected — the batch's landing gate is the backstop.
- Each lane reports: tip SHA, tool-call count, the recorded reds (killing mutations), ≤ 3 queue rows.

## 8. Decided (plan) — the one-line rules an Opus lane builds from

- `Decided (plan):` `reasons.py` is created by W1 with every Work refusal; B1 extends it (one enum, one
  home; `work/model.py::Reason` becomes a re-export in W2).
- `Decided (plan):` `grammar.py` is `policy`; `board.py`, `writer.py`, `default_brain.py` are `stores`;
  `executor.py`, `persona_turn.py`, `engine.py` are `lanes`; `receipts.py`, `reasons.py` are `models`.
- `Decided (plan):` the Python twin's regexes are the lint's, and the lint and the twin are proven to agree
  on the shared fixtures by one test (`test_the_twin_agrees_with_the_lint_on_every_fixture_row`); the
  launcher's fixture files are canonical and hermes re-copies on drift.
- `Decided (plan):` `assignee: persona:<token>` resolves instance-first, then persona id, else
  `assignee_unknown`; the token charset is `[A-Za-z0-9_.-]+`.
- `Decided (plan):` `WORK-<6>` is `WORK-` + six base32 characters of `os.urandom(5)`; collisions are a
  precondition refusal (`id_exists`), never a retry loop inside `mint_id`.
- `Decided (plan):` reads come from the hermes worktree after `sync()` (steps 1–3); a fetch failure answers
  the last tip with `stale: true` only when the caller passes `stale_ok`.
- `Decided (plan):` the hermes worktree is cut with `--no-checkout` and a non-cone sparse checkout of the
  brain dir; branch `work/<machine_id>`; `worktree prune` runs before every `add`.
- `Decided (plan):` the commit identity is `-c` pairs on `commit` (never `git config`), name
  `Eternia Harness`, email `harness+<machine_id>@eternia.local`.
- `Decided (plan):` idempotency is `request_id: <rid>` in the commit body, found with `git log --grep` over
  the note's history at the tip; a hit replays the receipt.
- `Decided (plan):` the operator (`CALLER_STDIO_OWNER` / `CALLER_LOCAL_CONSOLE`) may release or re-status a
  row another claimant holds, as `who="operator"`; no other caller may.
- `Decided (plan):` the default brain declaration is `declare_local_slot` (one slot, others untouched),
  with `require_publish_right(ws, None)`; a server-bound realm answers `needs_publish_right` and the
  operator's `create_brain` carries the credential.
- `Decided (plan):` `capabilities` answers `version: 2`; the launcher's catalog accepts 1 or 2 during W4
  and drops 1 in B6.
- `Decided (plan):` the engine runs only in the serve, ticks every 15 s, hands off what is claimed, never
  claims; one row per `Assignment` until B2's planner; a write-back's `request_id` is derived
  (`<claim request_id>:<verdict>`).
- `Decided (plan):` the turn's ending is the LAST fenced `work_report` block of `payload["reply"]`; no block
  or an unknown verdict → `FAILED` → `NEEDS PLAN` with the claim released.
- `Decided (plan):` a run that settled while the serve was down is `FAILED` (the reply is not re-read from
  the transcript); the row says so and a re-claim retries.
- `Decided (plan):` `stop` on a running turn waits for the turn (RULED on `RT-DISPATCH-B2-BATCH`); on a
  queued send it removes the entry.
- `Decided (plan):` `scripts/work_row.py` runs in the SESSION's checkout with the session's identity and
  never fetches, resets or stashes; a non-fast-forward is exit 3.
- `Decided (plan):` W5 keeps `tests/_downstream/conftest_plugin.py::_kanban_write_guard` if any other
  fixture names it (grep first), and deletes only `_kanban_guard_denies_recorded_root`.
- `Decided (plan):` no grandfather fixture gains a row in W1–W5; a lane that needs one has over-built and
  splits the module instead.

## 9. Owner decisions

Ruled 2026-10-18 (recorded on `RT-WORK-W1-STORE` and `MC-WORK-W4-BOARD`, binding here): reads from the
tip; done = delete; both assignee forms; claim-only first; default brain local-only; hermes's own identity;
engine the only agent-side writer; kanban retirement as W5.

New (one, because it changes the operator's product):

- **Default brain in a server-bound realm.** The auto-create cannot hold the realm publish credential, so a
  workspace in a server-bound realm with no repo slot gets its brain only when the operator clicks
  `Create brain` (one `runtime.work.create_brain` with the launcher-brokered credential) — or the auto-create
  is allowed to write a declaration the realm may later refuse to sync. **Recommend: the click; the realm's
  publish right stays the one authority (`require_publish_right`), and `capabilities` says
  `needs_publish_right` so the board explains itself.**

## 10. Rows this plan files / amends (verbatim, `runtime-queue.md` § Fork-owned)

- `RT-WORK-W1-STORE`, `RT-WORK-W2-WRITER`, `RT-WORK-W3-ENGINE`, `RT-WORK-W5-KANBAN-RETIRE` and the launcher's
  `MC-WORK-W4-BOARD`: unchanged; their pointers (`§2–§4`, `§5`, `§3`, `§6`, `§7`) now resolve to §6.1,
  §6.2 + §5, §6.3, §6.5 and §6.4 + §3.3 of this cut — a lane reads its §6 section.
- **`RT-WORK-DEFAULT-BRAIN-REALM` — the default brain in a server-bound realm: auto-create cannot hold the publish credential; `Create brain` (operator, credentialed) vs an unsynced auto declaration** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §9 · BLOCKED 2026-10-18: owner decision — may hermes auto-declare a local `brain` slot in a realm it cannot publish to? · Recommend: no; the operator's one click carries the credential, `capabilities` says `needs_publish_right`
- **`RT-WORK-PROFILE-OWNERS` — `agent_runtime/work/native.py::scopes` keys Work owners by upstream profile and `context.py::_operator` refuses the persona as assignee; both go with W2** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §6.2 · BLOCKED 2026-10-18: another lane — `RT-WORK-W2-WRITER` commit B deletes the module (unchanged from the second cut)
