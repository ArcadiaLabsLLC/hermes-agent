# Planned — Work on the markdown todo system, targeting persona agents (q/work-md-scope, 2026-10-18)

**Owner domain:** transport and wire ([03-transport-and-wire.md](../03-transport-and-wire.md) § Native
Work methods) and the office and board ([06-office-and-board.md](../06-office-and-board.md) § The board).
**Status:** scoped, nothing built. One doc, no code. The rulings below are the owner's; the options are
open only where the HOW is open.
**Measured / read:** 2026-10-18 against hermes `origin/main` 54b5a8f3fa and
`EterniaLauncher` `origin/main` (read with `git show`, not checked out).

## 0. Rulings this plan is built on

- `RULED 2026-10-18: owner — Work keyed on upstream profiles is incorrect design and must change; Work
  targets the owner's PERSONA agents (persona templates / persona instances, agent_runtime's persona
  model), never upstream's profiles.`
- `RULED 2026-10-18: owner — Work is backed by the markdown todo system (the queue .md files with the
  ADR 0011 § Row grammar), not by upstream's kanban database.`
- Standing: ADR 0015 (`Harness_Brain/30 — Decisions/0015 — …`) marks upstream kanban UNUSED in
  production; ADR 0011 § Row grammar is the grammar's one home in this repo; the launcher's board never
  writes a queue (`EterniaLauncher/docs/mission_control/planned/WORK_QUEUE_BOARD_2026-10-16.md` D6).

## 1. What is true today

### 1.1 `runtime.work.*` — the hermes side

- Five console-tier methods, registered by `agent_runtime/work/rpc.py::register`:
  `capabilities`, `context`, `list`, `inspect`, `start`. Every call runs off the reader lane
  (`spawn_reply`) and every refusal is a typed `Reason` (`agent_runtime/work/model.py::Reason`).
- Authority: `agent_runtime/work/service.py::execute` authorises at `TIER_CONSOLE`, reads the install
  id from `gateway_identity.read_install_identity`, and re-resolves the scope on EVERY call. A scope
  (`model.py::WorkScope`) is `(install, board, profile, database, home)`; its `owner` fingerprint is the
  opaque wire handle the launcher pins.
- The owners are PROFILES: `agent_runtime/work/native.py::scopes` crosses
  `hermes_cli.kanban_db.list_boards` with `hermes_cli.profiles.list_profile_names` /
  `get_profile_dir`, one owner per (database, profile, home). A task's `assignee` is the profile name;
  `native.py::_owned` refuses a task whose assignee is not the scope's profile.
- Reads: `native.py::list_work` → `kanban_db.list_tasks(assignee=profile, order_by="created-desc",
  session_id=…)`, keyset-sliced at `PAGE_SIZE = 40`; `native.py::inspect` → `kanban_db.get_task` +
  `kanban_db.latest_summary`. The projection (`native.py::project`) ships `id, title, status, assignee,
  block_kind, created_at, started_at, completed_at, heartbeat_at, result (≤64,000), body (≤50,000),
  in_conversation, revision`.
- The one write: `native.py::start` → `kanban_db.create_task(title, body, assignee=profile,
  idempotency_key="eternia:work:"+fingerprint(actor, client, owner, request), created_by="user",
  workspace_kind="scratch", board, session_id)` inside `kanban_db.write_txn`, with replay by
  idempotency key and `Reason.CONFLICT` on a changed payload. Nothing here edits, moves, comments on,
  cancels or deletes a task; capabilities advertise `operations: ["inspect", "start"]` only.
- Conversation scope: `agent_runtime/work/context.py::resolve` accepts a `native` reference (profile +
  profile_home + session) or an `operator` reference (workspace / persona / persona_instance / session,
  validated by `agent_runtime/operator_conversation.py::validate_operator_conversation`). For the
  operator kind, `context.py::_operator` returns `WorkContext(session, profile=None, can_start=True)`
  with the comment "A persona instance is not a native dispatcher profile" — the persona is deliberately
  NOT an assignee; the launcher then offers the profile owners as "destinations".
- Who creates tasks: the operator through the launcher (`created_by="user"`); never a hermes agent on
  an agent-runtime lane — the whole `kanban` toolset is deregistered on every lane by
  `agent_runtime/personas.py::REGISTRY_HYGIENE_BLOCKED_TOOLSETS` (folded into
  `PERSONA_BLOCKED_TOOLS` and unioned at the `profile_runner` chokepoint); `runtime-queue.md`
  `RT-DELEGATE-VS-CHAT-VS-WORK` records that a Work clause in agent guidance "waits on the `kanban`
  toolset being admitted". Upstream's own creators (`hermes kanban` CLI, the dashboard, the gateway's
  decomposition) are not run by the fork.
- Who executes: NOBODY in the fork. The dispatcher is upstream's gateway mixin
  (`gateway/kanban_watchers.py::GatewayKanbanWatchersMixin`, imported by `gateway/run.py`); `harness
  serve` imports no gateway runner, `agent_runtime/bundle_profiles/bundled-phone.yaml` drops
  `hermes_cli.kanban_db_dispatch` and the whole `hermes_cli.kanban*` family, and
  `service.py::_work_capabilities` tells the launcher so: "Tasks wait in Eternia Harness until its native
  dispatcher is running." The wire doc says the same: "acceptance means queued in Hermes, never proof
  of execution."
- The plugin's two kanban hooks are OBSERVERS of that dispatcher, not a dispatcher:
  `plugins/eternia-harness/__init__.py::route_blocked_kanban_cards` (`on_kanban_dispatch_tick` →
  `hermes_cli/kanban_blocked_pm_tick.py::on_kanban_dispatch_tick`, default off behind
  `kanban.pm_blocked_hook.enabled`) and `::record_kanban_crash_evidence` (`on_kanban_worker_exited` →
  `hermes_cli/kanban_crash_evidence.py::on_kanban_worker_exited`). With no dispatcher ticking they
  never fire. The three fork kanban modules are `hermes_cli/kanban_blocked_pm.py`,
  `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py` (absent from `upstream/main`); their tests
  are the five fork `tests/hermes_cli/test_kanban_*` files plus `tests/_downstream/conftest_plugin.py::
  _kanban_guard_denies_recorded_root`. `tests/agent_runtime/test_no_kanban_dependency.py` admits
  exactly the two public imports in `work/native.py` and forbids kanban everywhere else in
  `agent_runtime/`.
- The live store: `X:/Eternia/.hermes/kanban.db` (one `kanban.db` per HERMES_HOME root, via
  `kanban_db.kanban_db_path`) holds **0 tasks, 0 comments, 0 events, 0 runs** (read-only query,
  2026-10-18). There is nothing to migrate.

### 1.2 The launcher side

- Two different things are both called "work" in the launcher. (a) **Running work** —
  `lib/core/services/hermes/runtime/data/capabilities/harness_work_capabilities.dart`
  (`work.list` / `work.peek` / `work.cancel` / `work.restart`, the Activity surface's probe-and-kill
  lane over the snapshot's `running_work` section) and its method twins
  `lib/features/mission_control/data/bridge/mission_action_work_twin_lane.dart::kMissionWorkTwinMethods`
  (`runtime.work.cancel` / `runtime.work.restart`, lowered through
  `mission_action_method_lanes.dart::submitWorkTwin`). This is builds and processes, not tasks, and
  this plan does not touch it. (b) **The Work page** — the native-task surface this plan moves.
- The Work page: composition `lib/app/work/work_composition.dart::_WorkHost.connect` pins the selected
  runtime + account, requires `route.manifest.supports('runtime.work.capabilities')`, and builds
  `packages/agents/eternia_hermes_adapter/lib/src/work/hermes_work_catalog.dart::HermesWorkCatalog.connect`
  — one `HermesWorkBackend` per wire owner (= per profile). The backend
  (`hermes_work_backend.dart::HermesWorkBackend`) calls `list` / `inspect` / `start` only; the
  projection (`hermes_work_projection.dart::hermesWorkObservation`) needs `id, title, status, body,
  result, result_truncated, in_conversation, revision`, one of `completed_at|heartbeat_at|started_at|
  created_at`, and maps upstream's statuses to `WorkProgressState {queued, running, needsInput,
  succeeded, unknown}`. It throws when `assignee != profile`.
- What the page edits: nothing but START. `packages/work/eternia_work_experience/lib/src/work_models.dart::
  WorkExperienceOperation` lists `start, inspect, redirect, cancel, retry`; the hermes backend advertises
  `inspect` + `start`, and the archived record (`EterniaLauncher/docs/archive/companion/
  HERMES_WORK_VIEW_2026-09-30.md`) says "Stop, redirect and retry are not advertised." A start carries a
  `WorkBrief {title, objective, inputs, constraints, acceptance}` JSON-encoded into the body
  (`work_brief.dart::WorkBriefCodec.instruction`), and a pending submission is written to the encrypted
  intent file BEFORE send (`lib/app/work/work_submission_file.dart`). The destination picker
  (`lib/shared/work/work_assignment_sheet.dart`, `work_assignment_menu.dart`) lists the wire owners by
  `label` = `"<board name> · <profile>"`. No assignee change, no history, no runs, no comments, no
  ordering is shown or edited — the page needs only the fields the projection names.
- The Queues tab already reads markdown: `lib/features/mission_control/work_queue/data/work_queue_source.dart::
  WorkQueueRepo` names the three brain directories (`Harness_Brain/20 — Active Initiatives` for hermes),
  `LocalWorkQueueSource` lists `type: queue` notes under the checkout the workspace's repo slot resolves
  to (`lib/app/mission_control/work_queue_locator_binding.dart` → hermes `slots.show`,
  `agent_runtime/workspace_slots.py`), and `policy/work_queue_row_parser.dart::WorkQueueRowParser`
  is the one owner of the grammar: ID, title, exactly one status (`READY|BLOCKED|DEFERRED|NEEDS PLAN
  <date>`), `Recommend:`, `RULED`, `**TAKEN**`, pointers, duplicate-ID and wrapped-row defects. The board
  (`widgets/work_queue_card_actions.dart`) is read-only: Open row, Open plan, Open file, Copy row
  reference. Refresh is on open / focus / manual; no watcher; a slot unfilled on this machine renders
  "not on this machine".

### 1.3 The owner's todo system — which files, written how

- hermes: `Harness_Brain/TODO.md` (pointer list, holds no rows) → `Harness_Brain/20 — Active
  Initiatives/runtime-queue.md` (115 rows, 858 lines), `fork-hygiene-queue.md` (56 rows),
  `dead-code-burn-down-queue.md` (0 rows). Grammar: ADR 0011 § Row grammar; gate:
  `tests/tooling/test_work_queue_row_grammar.py` (vault-unique IDs, one status, blocker IDs, the
  shrink-only `BLOCKER_ID_CEILING`).
- launcher: `Launcher_Brain/TODO.md` → 31 `*-queue.md` notes under `Launcher_Brain/20 — Active
  Initiatives/` (`mission-control-queue.md` 102 rows, `qa-tooling-queue.md`, …); rule ADR 0025 and its
  2026-10-18 amendment; gate `test/architecture/work_queue_status_grammar_test.dart`.
- backend: `EterniaBackend_brain/20 — Active Initiatives/` (same grammar, per the launcher's reader).
- No per-workspace todo exists today. Every row is written by a SESSION (Claude Code / GPT lane) with
  a git commit: claim = append `**TAKEN <date> <who>**`, commit that alone, push
  (`Harness_Brain/TODO.md`, CLAUDE.md "Work tracking"); landing commit deletes the row. The runtime
  never writes the vault; `agent_runtime/build_identity.py::NON_RUNTIME_PREFIXES` lists `Harness_Brain/`
  so a vault commit does not count as a code change. Rows reach another machine by `git fetch`, not by
  realm sync; realm sync (doc 09 § The entities a runtime holds) moves the runtime STORE (install,
  devices, realm/workspace/persona instances, `workspace_slots` key-wise), never a checkout.

### 1.4 Who a Work task would be assigned to, and who runs it

- A persona instance (`agent_runtime/models.py::PersonaInstance {id, persona_id, role, display_name,
  profile_id, runtime_root, realm_id, workspace_id, steered_by, …}`) is the fork's agent; a persona
  template (`models.py::Persona.hermes_profile`) names the upstream profile that BACKS it, and the
  office actor row (`models.py::OfficeActor.backing_profile`) carries the same. The profile is a
  materialisation detail (`agent_runtime/profile_context.py` resolves a published profile token to its
  own home via `get_profile_dir`); the identity the realm shares is `(persona_id, persona_instance_id)`.
- Today Work inverts that: `native.py::scopes` enumerates PROFILES × boards and `context.py::_operator`
  explicitly refuses to treat the persona as an assignee. A task is therefore assigned to a profile that
  no persona may even use, and nothing executes it (1.1). Under the ruling, a Work row's assignee is a
  persona instance id (or a persona template id when the owner wants "any instance of this persona"), and
  execution is a persona CHAT TURN in that instance's conversation — the lane the fork already runs
  (doc 05), with `agent_chat_send` / the operator chat as the hand-off, not upstream's worker subprocess.

## 2. What Work needs from a store, and what a md row gives

| need | md row (ADR 0011) today | gap |
|---|---|---|
| stable id | `<ID>` uppercase, vault-unique, never renumbered | minting rule for Work (prefix per workspace or persona); uniqueness across files only by lint |
| title + brief | title in the bold lead; a brief has no home | a pointer to a brief note, or a bounded `objective` segment |
| one status | `READY / BLOCKED(reason) / DEFERRED / NEEDS PLAN` | no `running` / `done` (done = row deleted; running = `TAKEN`); the page's `WorkProgressState` must map onto these, or the grammar grows `DONE <date>` |
| assignee | none (`**TAKEN <date> <who>**` is a claim by a LANE) | an assignee segment that names a persona (`persona:<instance_id>`) — a grammar change in all three repos |
| owner decisions / rulings | `BLOCKED … owner decision — … · Recommend:` and `RULED <date>:` | fits as is; better than kanban's `triage` |
| history / events / runs / comments | git log of the line; nothing structured | the page shows none today (1.2), so the gap costs nothing until a surface asks |
| ordering | file order | fine; the board sorts by status/date |
| concurrent writers | one shared git index per clone; sessions race on the same file | the writer must be ONE process per checkout, writing by line and committing atomically (or not committing at all — see options) |
| write cost | one commit + push per edit | a status flip costs a commit; batching or a non-git local lane is needed for a UI |
| multi-device | `git fetch`; the launcher's board reads the checkout the slot resolves to | a device without the slot sees nothing; realm sync does not carry the vault |
| agent writes | none; agents have no tool for the vault | a Work write verb on the method lane (RPC first, argv fallback — the standing rule) |
| 1,000-row file | the parser is a regex per line (`WorkQueueRowParser.parseFile`), read whole on open/focus | fine for reads (<10 ms); a per-edit rewrite of an 80 KB file is fine; the lint's cross-file uniqueness is O(rows) |

## 3. The target, in one paragraph

Work is a queue note. One `type: queue` markdown file per WORKSPACE, in the ADR 0011 grammar extended
with an assignee segment, where a row's assignee is a persona instance of that workspace. hermes owns
the ONE writer (a fork-owned md store behind `runtime.work.*`: parse, mint IDs, append, flip status,
claim, delete; atomic rename, git commit optional and batched). The launcher's Work page keeps its
contract (`capabilities / list / inspect / start`) plus the edits the page never had (status, assign,
cancel), and the Queues tab reads the same file through the parser it already has. Execution is a
persona chat turn: `start` writes the row AND hands the brief to the instance's conversation; the turn
flips `TAKEN` → done. Upstream kanban storage, the `kanban` toolset and the three fork kanban modules
become unused in fact as well as by ruling.

## 4. Options — only where the HOW is open

Dimensions every option shares (ruled, not optional): the assignee is a persona instance; the store is
markdown in the ADR 0011 grammar; hermes is the one writer; the launcher never authors git commits.

### A. Rows live in the brain queues (`Harness_Brain/20 — Active Initiatives/*queue*.md`)

- hermes: `agent_runtime/work/native.py` replaced by a md adapter over the vault path the repo slot
  names; `scopes` becomes one owner per (workspace, queue file); ID minting `WORK-<n>`; writes through a
  file lock + atomic rename; a `git commit` of the queue line per write (the owner's claim protocol).
- launcher: destination picker lists workspaces (one owner each); the Queues tab shows Work rows beside
  lane rows with no change.
- unused: everything in C's list.
- migration: none (0 tasks).
- effort: 2 lanes (hermes store + launcher picker/projection).
- risks: Work rows and lane rows share one file and one git index — a UI flip and a session's claim
  commit race on `runtime-queue.md`; the vault is a REPO artefact (not on a phone, not on a device with
  no slot); every edit is a commit in `main`'s history. Rejected on the second point alone: the vault is
  the lanes' queue, Work is the owner's.

### B. A fork-owned md store per workspace, same grammar (RECOMMENDED)

- hermes: a new `agent_runtime/work_store/` (models / parser / writer / git) — one `work-queue.md` per
  workspace, path = `<store_root>/work/<workspace_token>/work-queue.md` (realm-synced like
  `workspace_slots`, key-wise by row ID; or, owner call, inside the workspace's repo slot checkout under
  `Harness_Brain/20 — Active Initiatives/work-<workspace>.md` so the lanes' board shows it). `runtime.work.*`
  keeps its five methods and adds `status`, `assign`, `cancel`, `claim` on the same console tier;
  `start` = append row + hand the brief to the persona instance's conversation
  (`agent_runtime/conversations` door, the existing `agent_chat_send` path); the persona's turn end flips the
  row. Parser: a Python twin of `WorkQueueRowParser` (the lint already restates the regexes), one owner.
- launcher: `hermes_work_projection.dart` maps the md statuses (`READY → queued`, `TAKEN → running`,
  `BLOCKED → needsInput`, deleted/`DONE` → succeeded); the destination picker lists persona instances of
  the workspace (`PersonaInstance.display_name`) instead of `board · profile`; the Queues tab gets a
  fourth repo-less source (the workspace's work note) or reads it from the slot if the owner picks that
  placement.
- unused: everything in C's list.
- migration: none.
- effort: 4 lanes — W1 hermes store + parser + gate (killing mutation: a second status segment accepted);
  W2 `runtime.work.*` on the store + the persona hand-off; W3 launcher projection + picker + Queues source;
  W4 the kanban retirement (`RT-FORK-KANBAN-CODE-SERVES`, the skip rows, `test_no_kanban_dependency`
  re-aimed to "no kanban import anywhere").
- risks: a second grammar owner (Python twin) — mitigated by porting the launcher's
  `test/fixtures/work_queue/*.md` fixtures as the shared contract (plan D3 names them for exactly this);
  realm sync of a text file is line-merge, so the writer must be the ONLY writer (one serve per root
  already holds the OS lock, R-L2); `DONE` needs a grammar amendment in all three repos or the
  convention "done = deleted, history = git/receipt".

### C. Keep kanban storage, project md rows into it — REJECTED by the ruling, kept for the unused list

Listed only so the retirement is explicit. Were it chosen nothing below would retire. Under A or B the
following become unused in fact: `agent_runtime/work/native.py`'s two public kanban imports (so
`tests/agent_runtime/test_no_kanban_dependency.py` goes back to the blanket prohibition);
`hermes_cli/kanban_blocked_pm.py`, `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py` and the
plugin's two `register_hook` lines; the five fork `tests/hermes_cli/test_kanban_*` files and
`conftest_plugin.py::_kanban_guard_denies_recorded_root`; `REGISTRY_HYGIENE_BLOCKED_TOOLSETS` keeps
`kanban` (the toolset still exists upstream); the `unused: kanban` skip rows in
`tests/fixtures/upstream_skip_list.txt` stay RIGHT and ADR 0015's "kanban unused" becomes true of the
fork's own code too; the wire doc § Native Work methods is rewritten for the md store; the launcher's
`_labels` ("Queued for the Eternia Harness dispatcher") go. Upstream PROFILE pieces that leave Work:
`hermes_cli.profiles.list_profile_names` / `get_profile_dir` in `work/native.py` (profiles stay for
persona backing everywhere else — `Persona.hermes_profile` is unchanged).

## 5. Recommendation

Option B, placement inside the runtime store (realm-synced, device-portable, no git) unless the owner
wants Work rows on the lanes' board, in which case placement is the slot checkout and the writer commits.
Order: W1 → W2 → W3 in parallel with W4. One grammar amendment to ADR 0011 (and the launcher's ADR 0025):
an optional assignee segment `· assignee: persona:<id>` and, if the owner wants history in the file,
`DONE <date>` as a fifth status — otherwise done = deleted and the receipt log is the history.

## 6. Owner decisions

- Placement: runtime store (`<store_root>/work/<workspace>/work-queue.md`, realm-synced) vs the repo
  slot checkout (`Harness_Brain/…/work-<workspace>.md`, git). **Recommend: runtime store.**
- Assignee granularity: persona INSTANCE id only, or also persona TEMPLATE id ("any instance").
  **Recommend: instance only; a template target is a follow-on row.**
- Done semantics: delete the row (history in git/receipts) or add `DONE <date>` to the grammar in all
  three repos. **Recommend: delete; history is the receipt log.**
- Grammar amendment for the assignee segment, in ADR 0011 and the launcher's ADR 0025 together.
  **Recommend: yes, one segment `assignee: persona:<id>`, optional, so lane rows are unchanged.**
- Execution: `start` hands the brief to the persona instance's conversation immediately, or the row
  waits `READY` until the operator or an agent claims it. **Recommend: wait READY; claim = hand-off.**
- Kanban retirement: land `RT-FORK-KANBAN-CODE-SERVES` now (modules, hooks, five tests) and re-aim
  `test_no_kanban_dependency` to the blanket prohibition once `work/native.py` is replaced.
  **Recommend: yes, as W4, same batch as W2.**
- Agent writes: give persona agents a Work write verb (RPC) in the first cut, or operator-only first.
  **Recommend: operator-only first; the agent verb is the `RT-DELEGATE-VS-CHAT-VS-WORK` plan's call.**

## 7. Rows this plan files (verbatim, for `runtime-queue.md` § Fork-owned)

- **`RT-WORK-ON-MARKDOWN` — Move Work off kanban onto a per-workspace markdown queue with persona-instance assignees (W1–W4)** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` · BLOCKED 2026-10-18: owner decision — placement, assignee granularity, done semantics, grammar amendment (§6) · Recommend: runtime store; instance only; done = delete; one optional assignee segment
- **`RT-WORK-PROFILE-OWNERS` — `agent_runtime/work/native.py::scopes` keys Work owners by upstream profile and `context.py::_operator` refuses the persona as assignee; both go with W2** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §1.4 · BLOCKED 2026-10-18: another lane — `RT-WORK-ON-MARKDOWN` W2 replaces the module
