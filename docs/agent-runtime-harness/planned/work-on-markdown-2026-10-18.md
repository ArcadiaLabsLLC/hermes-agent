# Planned — Work on the workspace todo boards: the brain queues of every repo in the workspace, worked by persona agents, written through git (q/work-md-scope, 2026-10-18)

**Owner domain:** transport and wire ([03-transport-and-wire.md](../03-transport-and-wire.md) § Native
Work methods), the office and board ([06-office-and-board.md](../06-office-and-board.md) § The board),
multi-device ([09-multi-device-runtime.md](../09-multi-device-runtime.md), repo slots).
**Status:** scoped, nothing built. One doc, no code. Second cut, redirected by the owner (§0).
**Measured / read:** 2026-10-18 against hermes `origin/main` 54b5a8f3fa and `EterniaLauncher`
`origin/main` (read with `git show`, never checked out).

## 0. Rulings and the owner's model

- `RULED 2026-10-18: owner — Work keyed on upstream profiles is incorrect design and must change; Work
  targets the owner's PERSONA agents (persona templates / persona instances), never upstream's profiles.`
- `RULED 2026-10-18: owner — Work is backed by the markdown todo system (the brain queue .md files in the
  ADR 0011 § Row grammar), not by upstream's kanban database.`
- `RULED 2026-10-18: owner — the workspaces USE the todo: a workspace's todo board lists each of its repos'
  brain todo tasks and the worker engine works on that; a workspace with no repo folders gets an
  auto-created default brain; git is part of the design and nothing may conflict.`
- Standing: ADR 0015 marks upstream kanban unused; ADR 0011 § Row grammar is the grammar's one home here
  (the launcher's twin is `EterniaLauncher/Launcher_Brain/30 — Decisions/0025` with its 2026-09-03
  claim amendment and 2026-10-18 ID amendment); the launcher's board never authors a git commit
  (`EterniaLauncher/docs/mission_control/planned/WORK_QUEUE_BOARD_2026-10-16.md` D6).

## 1. What is true today

### 1.1 `runtime.work.*` — the hermes side

- Five console-tier methods, `agent_runtime/work/rpc.py::register`: `capabilities`, `context`, `list`,
  `inspect`, `start`; off the reader lane; typed refusals (`agent_runtime/work/model.py::Reason`).
- Owners are PROFILES × kanban boards: `agent_runtime/work/native.py::scopes` crosses
  `hermes_cli.kanban_db.list_boards` with `hermes_cli.profiles.list_profile_names` / `get_profile_dir`;
  a task's `assignee` is a profile name and `native.py::_owned` refuses any other. `service.py::execute`
  re-resolves the scope (`model.py::WorkScope(install, board, profile, database, home)`) on every call.
- Reads: `native.py::list_work` → `kanban_db.list_tasks(assignee=profile)` keyset-sliced at 40;
  `native.py::inspect` → `kanban_db.get_task` + `latest_summary`. Projection fields
  (`native.py::project`): `id, title, status, assignee, block_kind, created_at, started_at,
  completed_at, heartbeat_at, result, body, in_conversation, revision`.
- The one write: `native.py::start` → `kanban_db.create_task(created_by="user",
  workspace_kind="scratch", idempotency_key="eternia:work:"+fingerprint(actor, client, owner, request))`
  under `kanban_db.write_txn`, replay by key, `Reason.CONFLICT` on a changed payload. No edit, move,
  comment, cancel or delete; `operations: ["inspect", "start"]`.
- Conversation scope: `agent_runtime/work/context.py::resolve` — a `native` reference (profile, home,
  session) or an `operator` reference (workspace / persona / persona_instance / session, validated by
  `agent_runtime/operator_conversation.py::validate_operator_conversation`). `context.py::_operator`
  returns `WorkContext(session, profile=None, can_start=True)` with the comment "A persona instance is
  not a native dispatcher profile" — the persona is deliberately NOT an assignee.
- Who creates tasks: only the operator through the launcher. No hermes agent can — the `kanban` toolset
  is deregistered on every lane (`agent_runtime/personas.py::REGISTRY_HYGIENE_BLOCKED_TOOLSETS`, folded
  into `PERSONA_BLOCKED_TOOLS` and unioned at the `profile_runner` chokepoint).
- Who executes: NOBODY in the fork. The dispatcher is upstream's gateway mixin
  (`gateway/kanban_watchers.py::GatewayKanbanWatchersMixin`, imported by `gateway/run.py`); `harness
  serve` runs no gateway; `agent_runtime/bundle_profiles/bundled-phone.yaml` drops the whole
  `hermes_cli.kanban*` family; `service.py::_work_capabilities` tells the launcher "Tasks wait in Eternia
  Harness until its native dispatcher is running." The plugin's two hooks are observers of that absent
  dispatcher: `plugins/eternia-harness/__init__.py::route_blocked_kanban_cards`
  (`on_kanban_dispatch_tick` → `hermes_cli/kanban_blocked_pm_tick.py::on_kanban_dispatch_tick`, default
  off) and `::record_kanban_crash_evidence` (`on_kanban_worker_exited` →
  `hermes_cli/kanban_crash_evidence.py::on_kanban_worker_exited`). The three fork kanban modules are
  `hermes_cli/kanban_blocked_pm.py`, `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py` (absent
  from `upstream/main`); their tests are the five fork `tests/hermes_cli/test_kanban_*` files and
  `tests/_downstream/conftest_plugin.py::_kanban_guard_denies_recorded_root`.
  `tests/agent_runtime/test_no_kanban_dependency.py` admits exactly `work/native.py`'s two imports.
- The live store `X:/Eternia/.hermes/kanban.db` (`kanban_db.kanban_db_path`) holds **0 tasks, 0
  comments, 0 events, 0 runs** (read-only query 2026-10-18). **There is nothing to migrate.**

### 1.2 The launcher side

- Two "works". (a) Running work — `lib/core/services/hermes/runtime/data/capabilities/
  harness_work_capabilities.dart` (`work.list/peek/cancel/restart`, the Activity surface over the
  snapshot's `running_work` section) and its twins `lib/features/mission_control/data/bridge/
  mission_action_work_twin_lane.dart::kMissionWorkTwinMethods` (`runtime.work.cancel/restart`, lowered by
  `mission_action_method_lanes.dart::submitWorkTwin`): builds and processes, untouched by this plan.
  (b) The Work page — the native-task surface this plan moves.
- The Work page: `lib/app/work/work_composition.dart::_WorkHost.connect` pins runtime + account,
  requires `manifest.supports('runtime.work.capabilities')`, builds
  `packages/agents/eternia_hermes_adapter/lib/src/work/hermes_work_catalog.dart::HermesWorkCatalog.connect`
  — one `hermes_work_backend.dart::HermesWorkBackend` per wire owner (= per profile), calling `list`,
  `inspect`, `start` only. `hermes_work_projection.dart::hermesWorkObservation` needs `id, title, status,
  body, result, result_truncated, in_conversation, revision` and one of `completed_at|heartbeat_at|
  started_at|created_at`, maps statuses to `WorkProgressState {queued, running, needsInput, succeeded,
  unknown}`, and throws when `assignee != profile`. The page EDITS nothing but START
  (`packages/work/eternia_work_experience/lib/src/work_models.dart::WorkExperienceOperation` lists
  `start, inspect, redirect, cancel, retry`; hermes advertises two). A start carries a
  `work_brief.dart::WorkBrief {title, objective, inputs, constraints, acceptance}` JSON-encoded into the
  body (`WorkBriefCodec.instruction`), written to the encrypted intent file before send
  (`lib/app/work/work_submission_file.dart`). The destination picker (`lib/shared/work/
  work_assignment_sheet.dart`, `work_assignment_menu.dart`) lists owners by label `<board> · <profile>`.
- The Queues tab already reads the brains: `lib/features/mission_control/work_queue/data/
  work_queue_source.dart::WorkQueueRepo` is a FIXED enum of three repos with their brain directories
  (`Harness_Brain/20 — Active Initiatives`, `Launcher_Brain/…`, `EterniaBackend_brain/…`);
  `LocalWorkQueueSource` lists `type: queue` notes under the checkout the workspace's repo slot resolves
  to (`lib/app/mission_control/work_queue_locator_binding.dart::SlotsWorkQueueRepoLocator` → hermes
  `runtime.workspace.slots.show`); `policy/work_queue_row_parser.dart::WorkQueueRowParser` is the one
  grammar owner; `widgets/work_queue_card_actions.dart` is read-only (Open row / plan / file, Copy row
  reference). One board per repo, never merged (plan D5, RULED 2026-10-16 on the queue row); refresh on
  open / focus / manual; a slot unfilled here renders "not on this machine".

### 1.3 Workspaces, repo slots, checkout folders

- A workspace (`agent_runtime/models.py::Workspace {id, slug, name, realm_id, agent_ids, …}`,
  `store/workspaces/`) declares named repo slots in `store/workspace_slots/<token>.json`
  (`agent_runtime/workspace_slots.py::declare`; the shape is `planned/build-running-work-2026-10-04.md`
  §3.1: per slot `repo.clone_url`, `repo.default_branch`, `toolchain`, `context.files`, `recipe`). The
  declaration is realm-synced key-wise (`workspace_slots_sync`); the MACHINE fills a slot with a local
  checkout path (`workspace_slots.py::bind` → `write_machine_roots`, `roots.<slot>`), private and never
  synced; `workspace_slots.py::show` answers this machine's fill; `workspace_slots_probe.py::report`
  checks `git remote get-url origin` against `clone_url` (`matches | remote_mismatch | not_a_repo`);
  `runtime.workspace.slot.clone` (`agent_runtime/workspace_slot_setup.py`) clones a declared slot with
  the machine's own git. A workspace supports any number of slots (owner, no limits). The default
  workspace is `agent_runtime/default_scope.py::DEFAULT_WORKSPACE_ID = "ws_default"`.
- The one git door for fork code is `agent_runtime/git_cmd.py::run_git` (switched off on the phone
  bundle). Realm sync already drives git through it.

### 1.4 The todo system — files and how they are written

- hermes: `Harness_Brain/TODO.md` (pointer list, no rows) → `Harness_Brain/20 — Active Initiatives/
  runtime-queue.md` (115 rows), `fork-hygiene-queue.md` (56), `dead-code-burn-down-queue.md` (0); lint
  `tests/tooling/test_work_queue_row_grammar.py`. launcher: `Launcher_Brain/TODO.md` → 31 `*-queue.md`
  (`mission-control-queue.md` 102 rows); gate `test/architecture/work_queue_status_grammar_test.dart`.
  backend: `EterniaBackend_brain/20 — Active Initiatives/`.
- Every row is written by a SESSION with a git commit: fetch, append `**TAKEN <date> <who>**`, commit
  that line alone, push; the landing commit deletes the row (ADR 0025 2026-09-03 amendment; this repo's
  CLAUDE.md "Work tracking"). Concurrent sessions share ONE git index per clone, so they stage and commit
  by pathspec; a commit in the hermes PRIMARY checkout restarts a live serve unless it touches only
  `NON_RUNTIME_PREFIXES` (`agent_runtime/build_identity.py`, which lists `Harness_Brain/`). Rows reach
  another machine by `git fetch`; realm sync carries the store, never a checkout.

### 1.5 Persona vs profile — who a task is for, who runs it

- `agent_runtime/models.py::PersonaInstance {id, persona_id, role, display_name, profile_id,
  runtime_root, realm_id, workspace_id, steered_by, …}` is the agent; `models.py::Persona.hermes_profile`
  and `models.py::OfficeActor.backing_profile` name the upstream profile that BACKS it — a
  materialisation detail (`agent_runtime/profile_context.py` resolves a profile token to its home via
  `get_profile_dir`). The realm shares `(persona_id, persona_instance_id)`; profiles are per-machine.
- Today Work assigns to profiles no persona may use and nothing executes (1.1). Under the ruling the
  assignee is a persona instance of the workspace and execution is that instance's CHAT TURN (doc 05),
  not upstream's worker subprocess.

## 2. The model

**A workspace's todo board is the union of the `type: queue` notes of every repo checkout folder assigned
to the workspace** — for each live slot, `<bound path>/<Brain>/20 — Active Initiatives/*.md` with
`type: queue` — plus, when the workspace binds no repo, its auto-created default brain (§4). A row in the
ADR 0011 grammar IS a task. Nothing is copied: there is no second store, no database, no projection that
can disagree with the file. The board keys a task by `(slot, ID)`.

**The worker engine works those rows**: a READY row whose assignee is a persona instance of the
workspace (or that the operator hands to one) is claimed (`**TAKEN <date> persona:<instance_id>**`),
handed to that instance as a chat turn carrying the row reference, its pointers and the brief, and
written back when the turn ends: done = the row is deleted (the commit body carries the result and the
receipt log keeps it); a question = `BLOCKED <date>: owner decision — <question> · Recommend: <answer>`
with the claim released; a stop = the claim released with a `DEFERRED` or `NEEDS PLAN` status and the
reason. Every write-back is one row operation keyed by ID (§5), never a text merge.

**Git is the store's transport and history.** hermes is the ONE writer per machine (one `harness serve`
per root, the OS lock of `agent_runtime/serve_socket/` — doc 09 R-L2), writing in its own worktree and
pushing fast-forward; sessions and the operator keep today's protocol; the launcher reads and asks,
never commits.

## 3. The grammar — what Work adds to ADR 0011 (one amendment, three repos)

| need | row today | Work adds |
|---|---|---|
| id | `<ID>` uppercase, vault-unique | rows the engine mints are `WORK-<6 base32>` (lane rows keep their prefixes); the board keys `(slot, ID)` so two repos' IDs never collide |
| title + brief | title in the bold lead | a `brief:` pointer segment to a note under `<Brain>/50 — Agent Handoffs/work/<ID>.md` holding the `WorkBrief` fields; a short task needs none |
| assignee | none (`TAKEN <who>` is a lane's claim) | optional segment `assignee: persona:<instance_id>` (or `persona:<persona_id>` for "any instance"); `TAKEN`'s `<who>` is `persona:<instance_id>` when the engine claims |
| status | `READY / BLOCKED / DEFERRED / NEEDS PLAN` | unchanged; running = `TAKEN`, done = deleted, question = `BLOCKED owner decision`; `WorkProgressState` maps `READY→queued, TAKEN→running, BLOCKED/NEEDS PLAN/DEFERRED→needsInput, deleted→succeeded` |
| result / history | none in the file | the deleting commit's body + a receipt (`work.row_done`) in the serve log; the launcher's Open row → git log of the line |
| ordering | file order | unchanged |

The lint (`test_work_queue_row_grammar.py`) and the launcher parser gain the one optional segment and
the `persona:` who; `WorkQueueRow` gains `assignee`. Nothing existing changes shape.

## 4. The default brain — a board always has a home

- When `runtime.work.capabilities` (or the engine's tick) finds a workspace with NO live slot whose bound
  checkout has a brain directory, hermes creates one: `git init` at `<store_root>/work/<workspace_token>/
  brain/` (through `run_git`), skeleton `Work_Brain/TODO.md` (frontmatter `type: moc`, the pointer
  paragraph, a Dataview block), `Work_Brain/20 — Active Initiatives/work-queue.md` (frontmatter
  `type: queue`, `program: work`, `status: open`, the one-line grammar reminder, no rows), an initial
  commit, and declares it as slot `brain` with `repo.clone_url: null` (local-only) and binds it here.
  `ws_default` gets one on first use like any other.
- It is a slot, so every reader and the writer treat it like a repo brain: the board lists it, the engine
  writes it, `slots.show` reports it. When the owner gives it a remote (`slots.declare` with a
  `clone_url`), the next write pushes it and the §5 protocol applies unchanged; until then the "push" step
  is skipped and the brain travels by realm sync of the store directory only if the owner asks (§7) —
  default: local to the machine, like any other unbound slot.
- A repo whose checkout has no brain directory (a third-party repo bound as a slot) is NOT given one;
  the board shows the slot as "no brain", and `Create brain` is an operator action that runs the same
  skeleton inside that checkout, committed by the §5 writer.

## 5. The write path — which git operations run, where, and why none can conflict

Terms: *clone* = the slot's bound checkout on this machine (the operator's or a session's primary,
shared index); *hermes worktree* = `git worktree add <store_root>/work/<workspace_token>/<slot>/
worktree work/<machine_id>` of that clone, owned by hermes alone; *tip* = `origin/<default_branch>`.

A row operation is `(slot, file, ID, op)` where `op ∈ {append(row), claim(who), release, set_status(status),
delete(result)}` — one line, found by ID. The writer (`agent_runtime/work_store/writer.py`, fork-owned):

1. `git -C <clone> fetch origin <default_branch>` — touches refs only, never the clone's index or tree.
2. `git -C <hermes worktree> reset --hard origin/<default_branch>` — the worktree has its OWN index and
   tree; the clone's shared index is never read or written, so no session's staged state is disturbed
   and the hermes primary's code tree never moves (no serve restart).
3. Parse the queue file at the tip, apply `op` to the row with that ID (atomic write: temp + rename).
   Preconditions are checked against the TIP, not against a cached read: `claim` requires the row to be
   present and untaken; `release`/`set_status`/`delete` require it taken by this persona (or an operator
   override); `append` requires the ID absent in every queue of that brain. A failed precondition is a
   typed refusal (`row_gone`, `already_taken`, `not_claimant`, `id_exists`) — never a conflict.
4. `git -C <hermes worktree> add -- "<queue file>"` then `commit` with a message that names the op
   (`work: TAKEN WORK-… persona:… (ws …)`), one op per commit, pathspec only. The commit author is the
   machine's hermes identity; `Co-Authored-By` is not used for engine commits.
5. `git -C <hermes worktree> push origin work/<machine_id>:<default_branch>` — git's default is
   fast-forward only. Accepted → done; emit the `work.row_<op>` receipt.
6. Rejected (non-fast-forward: a session, the operator, another machine or another persona pushed in
   between) → go to step 1 and REPLAY the same `(ID, op)` on the new tip. A replay re-runs the
   preconditions, so a claim raced across two machines ends with exactly one `TAKEN` (the second sees
   `already_taken`); a row landed meanwhile answers `row_gone`. Bounded to 8 attempts, then `push_contended`
   with the receipt; the operation is idempotent by `(ID, op, request_id)` so a retry cannot double-apply.

Why nothing conflicts:
- **No textual merge ever runs.** The writer never calls `merge`, `rebase`, `pull` or `stash`; the only
  reconciliation is replay-by-ID on the fresh tip. Git conflict markers cannot appear in a queue file
  from this path. (`merge=union` in `.gitattributes` is rejected: it can duplicate a line, i.e. mint two
  copies of one row.)
- **One writer per machine, with its own index.** The serve holds the root lock; its worktree is not the
  clone's primary and no session is told to work in it. Two sessions and the engine sharing one clone
  touch three indices.
- **Claims are atomic because the push is.** A `TAKEN` becomes true the instant the fast-forward lands;
  there is no window in which two claimants both believe they hold a row, because the loser's push is
  refused and its replay reads the winner's line.
- **Sessions keep their protocol unchanged** (fetch, commit by pathspec, push). A session that races the
  engine on the same file sees a non-fast-forward and does what ADR 0025 already says: fetch and
  re-apply. For adjacent-row edits that would textually conflict in a human's `pull`, the same Python
  store ships as `scripts/work_row.py` so a session can apply its row op by ID instead of resolving a hunk.
- **Multi-device** is the same race as two sessions: the tip is the truth, every machine's engine
  replays on it, and the launcher on a machine without the slot reads through hermes (§6), not from a
  checkout it lacks.
- **The default brain** has no remote by default, so steps 1 and 5 are skipped; one writer, one machine,
  nothing to race.
- **Phone bundles** have no git (`git_cmd` is switched off): the phone's Work page is read-only against a
  desktop runtime's `runtime.work.*`, which is how it already aims a remote install.

Reads come from the hermes worktree at the tip after a `fetch` (cheap; cached by `fetch` output),
so a claim is visible to every reader the moment it is pushed, independent of whether the operator's
checkout has pulled. The Queues tab today reads the checkout's working tree (`LocalWorkQueueSource`);
§6 moves it to the same source so the two surfaces cannot disagree.

## 6. What changes where

hermes (fork-owned, `agent_runtime/`):
- `work_store/` — `grammar.py` (Python twin of `WorkQueueRowParser`, validated against the launcher's
  `test/fixtures/work_queue/*.md` ported as the shared contract), `board.py` (the union over a
  workspace's live slots → rows keyed `(slot, ID)`), `writer.py` (§5), `default_brain.py` (§4),
  `engine.py` (the tick: READY rows with a persona assignee → claim → hand-off through the existing
  conversation door — the `agent_chat_send` / operator-chat path — → write-back on turn end; a per-
  workspace concurrency cap from `Workspace.max_concurrent_lanes`).
- `work/` — `native.py` and its two kanban imports deleted; `service.py::scopes` become one owner per
  workspace (label = workspace name); methods: `capabilities`, `context`, `list` (rows of the board, filter
  by slot / status / assignee / persona scope), `inspect`, `start` (append + optional assignee),
  `assign`, `claim`, `release`, `set_status`, `done`, `create_brain`; all console tier, all through the
  writer; `context.py::_operator` returns the persona instance as `WorkContext.assignee` and
  `can_start` as today.
- Gates: `tests/agent_runtime/test_no_kanban_dependency.py` back to the blanket prohibition (its killing
  mutation: an `import hermes_cli.kanban_db` anywhere in `agent_runtime/`); a grammar gate on the Python
  twin whose killing mutation is a row with two statuses accepted; a writer gate that replays a claim
  against a tip moved under it and proves exactly one `TAKEN`.
- Docs: 03 § Native Work methods rewritten; 06 gains "§ The todo board"; ADR 0011 § Row grammar amended
  (assignee segment, `persona:` who, engine-minted IDs); `RT-FORK-KANBAN-CODE-SERVES` lands.

launcher (`EterniaLauncher`):
- `WorkQueueRepo` stops being a fixed three-repo enum: the board's repo switcher lists the workspace's
  live slots from `slots.show` (brain directory per slot discovered as `*_Brain/20 — Active Initiatives`
  or `*_brain/…`, or `Work_Brain/…` for the default), and `LocalWorkQueueSource` is replaced by a
  `runtime.work.list` source (plan D1 already reserves this: "a serve read model … returns the same
  `(path, text)`"). The grammar test keeps reading the launcher's own vault locally.
- `hermes_work_projection.dart` maps the md statuses (§3); `hermes_work_backend.dart` drops the
  `assignee != profile` throw; the destination picker lists the workspace's persona instances
  (`display_name`) and the target queue (slot + note, default the workspace's default brain or the
  slot whose `context.role` matches the brief); `WorkExperienceOperation` gains `assign` and `release`
  as advertised operations; the card actions gain `Claim for <persona>` and `Release` (writes through
  hermes, still never a launcher commit — D6 holds).
- Running-work (`harness_work_capabilities.dart`, the twin lane) is untouched.

unused afterwards (the kanban retirement, ADR 0015 made true of fork code too): `work/native.py`'s two
kanban imports; `hermes_cli/kanban_blocked_pm.py`, `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py`
and the plugin's two `register_hook` lines; the five fork `tests/hermes_cli/test_kanban_*` files and
`conftest_plugin.py::_kanban_guard_denies_recorded_root`; the launcher's `_labels` ("Queued for the Eternia
Harness dispatcher"). The `unused: kanban` skip rows in `tests/fixtures/upstream_skip_list.txt` stay right;
`REGISTRY_HYGIENE_BLOCKED_TOOLSETS` keeps `kanban` (the toolset still exists upstream). Upstream PROFILE
pieces that leave Work: `hermes_cli.profiles.list_profile_names` / `get_profile_dir` in `work/native.py`
(profiles stay as persona backing everywhere else; `Persona.hermes_profile` is unchanged).

Migration: none — 0 kanban tasks; the Work page's pending-intent files are `start` requests that replay
as `append` by `request_id`.

## 7. Lanes and order

- **W1** hermes `work_store/grammar.py` + `board.py` + `default_brain.py` + the ADR 0011 amendment + lint;
  gate with its killing mutation recorded. (one CHANGE commit)
- **W2** `work_store/writer.py` (§5) + the replay gate; `runtime.work.*` on the store; `native.py` deleted;
  `test_no_kanban_dependency` re-aimed. (one MOVE for the deletion, one CHANGE)
- **W3** `work_store/engine.py` — claim → persona hand-off → write-back, cap, receipts. (one CHANGE)
- **W4** launcher: slot-driven `WorkQueueRepo`, the `runtime.work.list` source, projection, picker, the
  two new card actions, ADR 0025 amendment + parser. (one CHANGE, launcher)
- **W5** kanban retirement (`RT-FORK-KANBAN-CODE-SERVES`) — same batch as W2.
- Order: W1 → W2 (+W5) → W3 ∥ W4. One landing gate per batch (affected tests only).

Risks: a second grammar owner (Python twin) — mitigated by the shared fixtures; the engine's hand-off
rides the chat lane's prep cost (doc 05 numbers) — one turn per claim, not per tick; a brain directory
name is discovered by pattern — the slot declaration may pin it (`context.brain_dir`) when the pattern
misses; the hermes worktree per slot per workspace multiplies checkouts on disk (shallow is not an
option for push; `--no-checkout` + sparse `*_Brain/` keeps each under a few MB).

## 8. Owner decisions

- Reads: the board and the Work page read from the hermes worktree at `origin/<default_branch>` (claims
  visible on push) rather than the operator's checkout working tree (visible after a pull).
  **Recommend: the tip, through `runtime.work.list`; the checkout stays the sessions' view.**
- Done semantics: delete the row (result in the commit body + receipt) vs add a `DONE <date>` status.
  **Recommend: delete; the grammar stays four statuses.**
- Assignee segment: optional `assignee: persona:<instance_id>` in ADR 0011 and 0025 together, with
  `persona:<persona_id>` allowed for "any instance". **Recommend: yes, both forms.**
- Engine start: auto-claim every READY row with a persona assignee on the tick, or operator/agent claim
  only (the engine then hands off what is claimed). **Recommend: claim-only first; auto-claim as a
  per-workspace setting after the first live proof.**
- Default brain remote: local-only until the owner declares a `clone_url`, or hermes creates a repo on
  the owner's GitHub org. **Recommend: local-only; declaring the remote is one `slots.declare`.**
- Engine commit identity: a per-machine hermes git identity (`Eternia Harness <harness@<machine>>`) vs the
  operator's git identity on that machine. **Recommend: hermes's own, so `git log` shows who wrote.**
- Agent write verb: persona agents get `work.*` tools (append / claim / release / done) in the first cut,
  or the engine is the only agent-side writer. **Recommend: engine only first; the tools are the
  `RT-DELEGATE-VS-CHAT-VS-WORK` plan's call.**
- Kanban retirement as W5 in W2's batch. **Recommend: yes.**

## 9. Rows this plan files (verbatim, for `runtime-queue.md` § Fork-owned)

- **`RT-WORK-ON-TODO-BOARDS` — Work = the workspace's todo board (union of its repo brains' queue notes), worked by persona instances, written through hermes's own worktree with replay-by-ID (W1–W5)** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` · BLOCKED 2026-10-18: owner decision — reads from the tip vs the checkout, done = delete, assignee segment, claim-only vs auto-claim, default-brain remote, engine identity (§8) · Recommend: tip; delete; both forms; claim-only; local-only; hermes identity
- **`RT-WORK-PROFILE-OWNERS` — `agent_runtime/work/native.py::scopes` keys Work owners by upstream profile and `context.py::_operator` refuses the persona as assignee; both go with W2** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §1.5 · BLOCKED 2026-10-18: another lane — `RT-WORK-ON-TODO-BOARDS` W2 replaces the module
