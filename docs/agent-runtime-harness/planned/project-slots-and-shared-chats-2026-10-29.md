# Planned — the Project record hermes reads, slots re-keyed to `<project>/<slot>`, and the shared chat store (2026-10-29)

**Owner domain:** runtime data ([02-runtime-data-and-shapes.md](../02-runtime-data-and-shapes.md)), the repo
slots (`agent_runtime/workspace_slots.py`), chat / recall (`hermes_state.py::SessionDB`,
`tools/session_search_tool.py`).
**Status:** READY 2026-10-29 (lane w1029p-projects). Rows: `RT-PROJECT-SHARED-CHAT-STORE` (chat half, this doc
§5–§7) and the launcher's `COMP-PROJECTS-SLOTS-AND-SHARING` (`EterniaLauncher` row; its plan is
`EterniaLauncher/docs/companion/planned/PROJECTS_SLOTS_AND_SHARING_2026-10-29.md`). Build rows in §9; hermes moves
first, the launcher plan names each hermes row it waits on.
**Spec:** the owner's rulings quoted in §1, the landed connections slice (`agent_runtime/workspace_projects.py`,
`f9e9dc4c64`), and [naming-and-address-map-2026-10-25.md](naming-and-address-map-2026-10-25.md), whose
`launcher-project` / `slot-folder` rows already name this direction and whose address grammar §8 amends.

## In plain English

A Launcher Project stops being a list of folders and becomes the thing that DECLARES repo slots; a realm
workspace is assigned Projects (already built: `Workspace.project_ids`) and its agents read the slots of those
Projects. Hermes therefore keeps a Project record of its own — slots, category folders, share switches — synced by
realm sync exactly as the slot document is today, and every fill, worktree and agent assignment is re-keyed from
`<workspace>/<slot>` to `<project>/<slot>`. A Project's chats, documents, boards and artifacts are folders declared
the same way (a sub-folder of one of its slots), shareable only when that slot is source-controlled and the realm
lets the member publish. Shared chats never enter an agent's own `state.db`: they travel as per-chat append-only
turn logs in the Project's chats folder, are folded into a separate per-Project store, and recall searches that
store beside the agent's own only when the agent's switch is on.

## 1. What is settled (owner, quoted) and what is built

Owner, 2026-10-28: "since projects manage 'folders' the idea is to replace that with slots and then have proejcts
as amanager for a workspaces slots"; "workspaces should be assigned projects and then the workspace and its agents
parses the projects slots and any other data" (several Projects per workspace); sharing is opt-in per category and
the server's permissions must allow it (`eternia-backend/realms/models.py` `granted_role_ids` /
`publisher_role_ids`), assigning a Project to a realm's or server's workspace shares everything it supports within
those, artifacts / documents / boards in a Project sub-folder, chats tagged or foldered; "slots should support
source controlled and non source controlled, but if its not source controlled then it can't be shared"; "assign
the methodology of the slots to the chats, documents boards, artifacts as well"; and on chats: "team members
polluting the state db, could we have it in a separate shared one that dynamically incorporates it if enabled".
Owner, 2026-10-29: "Yes, re-file it" (the direction stands after the connections slice; ADR 0038 in the launcher
brain). Maximus Shaban's 2026-10-28 "keep existing owners" scoped the connections slice only.

Built, read 2026-10-29 on `main`:

- `Workspace.project_ids` + `project_assignment_revision` (`agent_runtime/models.py::Workspace`), written only by
  `workspace_projects.set_project_connection` under `require_publish_right` (`workspace_slots.py:697`); the
  launcher's connections and avatars (`EterniaLauncher/docs/companion/evidence/PROJECT_WORKSPACE_AGENTS_2026-10-28.md`).
  Hermes holds nothing of a Project but its id.
- Slots: `store/workspace_slots/<ws>.json` (`paths.workspace_slots_path`), `declare` REPLACES the set with
  tombstones (`workspace_slots.py:380`), `declare_one_slot` adds one, `bind` writes the fill through
  `machine_roots.workspace_roots[ws][slot]` (`_write_fill`, `:530`), `show` / `snapshot_slots` read it; realm sync
  merges the document key-wise (`workspace_slots_sync.py`, family `WORKSPACE_SLOTS`). A local slot is
  `repo.local: true` with no clone URL (`normalize_declaration`, `:344`) — the source-controlled / machine-local
  split the owner asked for already exists at the declaration.
- Agents: `PersonaInstance.assigned_slots` / `primary_slot` / `slots_issued_at` (`models.py:594`), edited by
  `persona_slots.set_instance_slots`, read by `load_slot_context` (`persona_slots.py:223`) through
  `bound_path(slot, workspace_id=instance.workspace_id)`; `drop_removed_slots` is called from `declare` when a
  slot is tombstoned. Verbs: `runtime.workspace.slots.show/declare/report`, `runtime.workspace.slot.bind/env.set`,
  `runtime.persona.instance.slots.show/set` (`serve_rpc/workspace_slots.py`), all `TIER_CONSOLE`.
- Per-slot machine state: worktrees `store/slot_worktrees/<ws>/<slot>.json` (`paths.slot_worktrees_path`,
  `agent_runtime/slot_worktrees.py`), Work's own worktree `work_worktree_dir(ws, slot, token)`, the address
  `slot-folder:<workspace>/<slot>` and `realm:/realm-workspace:/repo-slot:` (`agent_runtime/address.py`).
- Chats: one `state.db` per chat head (`chat_session_scope.py`; `per_profile` records own their profile's
  `state.db`), `messages.message_uid` is a stable per-message id (`hermes_state_common.py:558`,
  `hermes_state_messages.py::stamp_message_uid`), `SessionDB.export_session` / `import_sessions`
  (`hermes_state_portability.py:347`, `:789`) move WHOLE sessions and skip an id already present — the
  "two machines continued one chat" case loses the second machine's turns, which is why the fold below is by
  turn, not by session. `session_search` opens ONE db (`session_search_tool.py:601–652`) and `_discover` ranks
  inside it; memory extraction (`agent/background_review.py`) reads the turn's live messages, never a store.
- `own_session_import.py` is the one import door for Hermes' own exports and binds each chat to a persona
  instance of the target; its ladder (`BoundBy`) is reused for the author identity below, not for the fold.

## 2. The Project record (hermes stores it, realm sync carries it)

Decided (plan): `store/projects/<project-id>.json` (`paths.project_path(project_id)`, token-safe like
`workspace_slots_path`), a new realm-sync family `PROJECT = "project"` merged by the slot document's rules
(`workspace_slots_sync`: names union, newer `recipe.revision` then newer `issued_at` per slot, tombstones,
`machines.<id>` disjoint and this machine's own key authored here only, future stamps not believed). Shape:

```
{ schema_version: 1, project_id, name, issued_at,
  slots:      { <name>: { repo, toolchain, context, recipe, declared_at, declared_by_machine, issued_at, removed_at } },
  categories: { chats | documents | boards | artifacts | guidance:
                { slot: <name> | null, subpath: "<relative>", shared: bool, issued_at, revision } },
  guidance:   { description, instructions, revision }          # shared only when categories.guidance.shared
  machines:   { <machine-id>: { reported_at, namespace, slots: { <name>: {bound, status, checkout} } } } }
```

- `slots.<name>` is byte-for-byte the record `normalize_declaration` produces today; `context` gains two
  optional lists `document_dirs` / `adr_dirs` (relative paths inside the checkout, validated by `_inside_checkout`)
  — the launcher's `ProjectFolder.documentDirectories` / `adrDirectories` move here as slot-relative config.
- A category is a FOLDER DECLARATION, not content: `slot` names one of the Project's slots and `subpath` a folder
  under it (default `.eternia/<category>`); `slot: null` means the category has no folder yet. It is
  source-controlled iff that slot has a `clone_url` (not `repo.local`). `shared` may be true only when
  source-controlled (`category_not_source_controlled`) — the owner's rule, enforced at the write.
- `guidance` is the Project's description + instructions (the launcher's `Project.instructions`, ≤ 32000 chars)
  with its own switch, off by default; the record carries it only while `categories.guidance.shared` is true, so
  an unshared Project's instructions never sync. The owner's "any other data" is read as this block plus the
  category folders; nothing private (pins, chat links, context review, paths, env values) is ever in the record.
- Writer: `agent_runtime/project_store.py::ProjectStore`, the single writer, with `declare(project_id, slots,
  issued_at, machine)` / `declare_one_slot` / `set_category(project_id, category, slot, subpath, shared, issued_at)`
  / `set_guidance` — same `stale_revision` horizon as `_fresh_document`, same credential refusals.
  Authorization: a Project assigned to no realm workspace in this namespace is this machine's own (no right
  needed, as a workspace in no realm is today); otherwise every write runs `require_publish_right` for EACH realm
  whose workspace holds the Project in `project_ids` and refuses `realm_publish_denied` naming the realm. The
  record publishes into every such realm's subtree; a realm whose right is denied gets no copy and the launcher
  shows "not shared in <realm>". The backend's `granted_role_ids` / `publisher_role_ids` are inputs to that one
  decision (`realm_sync.git._authorize`), never re-implemented.
- Verbs (`serve_rpc/project.py`, `TIER_CONSOLE`): `runtime.project.show`, `runtime.project.declare`,
  `runtime.project.slot.bind`, `runtime.project.slot.env.set`, `runtime.project.category.set`,
  `runtime.project.guidance.set`, `runtime.project.report`, `runtime.project.chat.share` (§5). The workspace-keyed
  slot verbs stay registered through the cutover and answer `slot_migrated` with the Project id after §4 runs, so
  an older launcher gets a typed answer, never a silent empty table.

## 3. Re-keying slots to `<project>/<slot>`

Decided (plan): the slot identity is `project_id + slot name`; the pair prints as `<project>/<slot>` wherever a
slot used to be named by `<workspace>/<slot>`.

- Fill: `machine_roots.json` schema 4 adds `project_roots.<project>.<slot>` beside `workspace_roots`;
  `bound_path(slot, project_id=…)`, `_write_fill`, `MachineRoots.project_root` are the Project-keyed reads and the
  one write. The fill is per PROJECT, not per workspace: the same Project in two workspaces is one declaration and
  one fill per machine (the collision that made the fill per workspace — two workspaces both declaring `brain` —
  cannot recur because two Projects are two keys). `${roots.<slot>}` resolves against the config's own
  workspace's assigned Projects; a name two assigned Projects both declare is `root_ambiguous`, as today.
- Census: `slot_census` / `realm_workspace_ids` iterate each realm workspace's `project_ids` and each Project's
  live slots; `BoundSlot` gains `project_id`; `slot_for_path` is unchanged.
- Worktrees: `paths.slot_worktrees_path(project_id, slot)` and `work_worktree_dir(workspace_id, slot_key, token)`
  where `slot_key` is the token of `<project>/<slot>`; the Work board stays per workspace (the board is the
  workspace's view; the brain it reads is a slot of one of its Projects).
- Address: `project:<id>/repo-slot:<name>` (shared, synced) and `machine:…/namespace:…/slot-folder:<project>/<slot>`
  (§8 amends the naming map; `address.py` gains `Kind.PROJECT` and `slot-folder`'s pair becomes
  `<project>/<slot>`); `realm:/realm-workspace:/repo-slot:` is kept parseable for old turn records and never printed again.

## 4. Migration — every workspace slot document, without loss

Decided (plan), `agent_runtime/project_migration.py`, run once per namespace on the first serve after landing
and idempotent under crash/retry (the migration identity is the workspace id):

1. For every `store/workspace_slots/<ws>.json` with live slots: create Project `ws-<workspace-id>` named
   "<workspace name> repos" with `migrated_from: {workspace_id, workspace_name}` (RT-MIGRATED-PROJECT-NAME,
   2026-10-31: "<workspace> slots" read as a stray Connect-menu entry; a Project still carrying that name is
   renamed by the next boot's pass, a name someone chose stays) (a Project the launcher adopts into its
   catalog on open — launcher plan §4),
   copy every slot record VERBATIM (tombstones included) into `store/projects/ws-<ws>.json`, copy `machines`,
   and connect it: `project_ids += ["ws-<ws>"]` through `set_project_connection` with the local allow (the
   migration is this machine's own write; the record then syncs under the realm's right as any publish does).
   A workspace that already holds connected Projects still gets its own `ws-` Project — matching clone URLs or
   paths never merges a Project (`§4A.8` of the recoverable design, kept).
2. Fills: `workspace_roots[ws][slot]` → `project_roots["ws-<ws>"][slot]`; worktree records
   `slot_worktrees/<ws>/<slot>.json` → `slot_worktrees/ws-<ws>/<slot>.json`; Work worktrees are re-pointed by
   directory rename under `work_worktrees_dir(ws)`.
3. Assignments: every instance of that workspace gets `assigned_slots: [f"ws-{ws}/{slot}" …]`,
   `primary_slot` likewise, `slots_issued_at` stamped — one write per instance through `set_instance_slots`.
4. The old document is left in place with `migrated_to: "ws-<ws>"` and `issued_at` stamped (realm sync still
   merges it; a peer that has not migrated reads it unchanged; a peer that has ignores a document carrying
   `migrated_to`). Counts (slots, fills, worktrees, instances) are written to a receipt
   `project_migration.completed` and asserted equal before the old writer is retired.
5. A namespace whose documents are all already migrated does nothing; a crash after step 1 and before step 4
   re-runs steps 1–3 as no-ops (every write is "set to this value").

## 5. Shared chats — the turn log in the Project's chats folder

Decided (plan): a chat is shared into a Project by an explicit `runtime.project.chat.share` (session id, project
id, `shared: bool`), refused unless the Project's `chats` category is `shared` (hence source-controlled) and the
caller holds the publish right of a realm the Project is assigned into. Linking a chat to a Project in the
launcher (`ProjectChatRef`) is organisation and shares nothing — the launcher plan keeps that distinction.

- File form: `<chats folder>/<session-id>/<machine-id>.<namespace>.jsonl` — one append-only file PER CHAT PER
  WRITER, so two machines continuing one chat never write the same file and git never conflicts; plus
  `<session-id>/chat.json` (title, persona id, `mission_chat_root_id`, first turn stamp, format version). A line
  is one message: `{turn_uid: <message_uid>, seq, role, ts, content, tool_name?, tool_calls?, parent_turn_uid,
  author: {persona_instance_id, profile_id, machine_id, namespace}, address}`. `message_uid` is the stable turn
  id the row asks for (the column exists and is minted on write today). Content passes `redaction` (the
  `SECRET_ASSIGNMENT_RE` scrub realm sync already uses) and attachments are referenced by `media_handles` id only
  — never bytes, never a path. Compacted / inactive rows are not exported (`active = 1` only).
- Cursor: `store/project_chat_exports/<project>/<session>.json` holds the last exported `message_uid`; the
  export appends on every turn end of a shared session (`chat_turn_reservations` release hook, the same place
  `slot_worktrees` observes) and backfills from the first turn on enable. Export never rewrites a line.
- Publication: the chats folder is a sub-folder of a source-controlled slot, so the bytes reach other machines
  by git. The existing Work writer (`work_store/writer.py`: one operation per commit in Hermes' own worktree of
  the slot, pushed fast-forward with replay) gains a second operation kind, `chat_turns_appended`; the chats
  category publishes automatically because the files are machine-written logs, not operator edits. Documents,
  boards and artifacts (§7) publish when the operator's own commit lands — the launcher shows the uncommitted
  count — never auto-committed (the recoverable design's rule, kept for operator-edited content).
- Unshare (`shared: false`) stops the export and removes the chat's folder in the next writer commit; git history
  and copies already pulled remain, and the receipt says so.

## 6. The shared store per Project, and recall across both stores

Decided (plan): one shared store per Project PER NAMESPACE, `store/project_chats/<project-id>.db`, a `SessionDB`
opened at that path (the schema, FTS and `search_messages` come for free) with a UNIQUE index on
`messages.message_uid` added by the fold. It is never a chat head: `chat_session_scope` cannot resolve to it, and
`is_canonical_session_persistence` answers false for it (gate in §10).

- Fold: `agent_runtime/project_chat_fold.py::fold(project_id)` walks the chats folder in this machine's fill of
  the category's slot, reads every `<session>/<writer>.jsonl` from the per-file byte offset it recorded last
  time (`store/project_chat_fold/<project>.json`), and inserts each line whose `turn_uid` is not yet in the
  store — idempotent by turn id, so a chat continued on two machines folds turn by turn in `(ts, seq)` order and
  a re-pull re-folds nothing. A session row is created on its first turn with `source = "project_shared"`
  (a new `_HIDDEN_SESSION_SOURCES`-exempt source), `model_config.persona_instance_id` = the author's. The fold
  runs after each realm-sync pull that touched the folder and after each turn end that appended locally; the
  author's own turns fold too, so the shared store is complete on every machine.
- Recall: `session_search` gains `shared_stores: list[tuple[label, SessionDB]]` resolved by the turn from the
  instance's switch (below): for each store `_discover` runs as today; results merge by per-store rank
  (round-robin, own store first on ties) because FTS5 BM25 is not comparable across databases; every shared hit
  carries `shared_from: {project: <name>, author: <persona display>, machine}` and its `link` is
  `@project:<project-id>/<session-id>`, which `_read_scoped` / `_scroll` resolve back to the shared store
  read-only. A teammate's turn is labelled by its author in the rendered line ("— Alice's agent, on
  nekwo-ubuntu24"). The own store's exclusions (`current_lineage_root`, hidden sources) do not apply to shared
  stores; the shared store is always opened read-only by recall.
- The switch: `PersonaInstance.recall_shared_projects: bool` (default false; persona-instance family, edited by
  `runtime.persona.instance.slots.set`'s sibling `runtime.persona.instance.recall.set`). An agent with it on
  searches the shared store of every Project assigned to ITS workspace whose `chats` category is shared. Per
  agent rather than per Project because the owner's words were about one agent's recall being polluted; the
  Project's share switch is the other gate and both must be on.
- Memory extraction never reads the shared store: `background_review` reads the live turn; the only opener of
  `store/project_chats/` is the fold (write) and recall (read-only). Default never, as the row says; no switch
  is added for it.
- Drop: `set_project_connection(connected=False)` for the last workspace of this namespace holding the Project,
  or `category.set(chats, shared=False)`, deletes `store/project_chats/<project>.db`, the fold offsets and the
  export cursors for that Project — "the shared store and nothing else": the agent's own `state.db`, the git
  folder and every other Project's store are untouched. Turning the agent's switch off drops nothing.

## 7. Documents, boards, artifacts, guidance — the same folder model, what hermes reads

- `documents`: the folder hermes offers as context — `load_slot_context` adds the documents folder's files
  that the launcher's selected-context list names (a `context_files` list in the category record, relative
  paths), each a section like a slot's `CLAUDE.md`; it reads nothing not listed.
- `boards`: the Project's Work brain directory — `context.brain_dir` of the category's slot, so
  `runtime.work.list` lists the board under the Project; the board publisher stays the Work writer, one
  publisher per board (never both the workspace's old family and a Project path).
- `artifacts`: a folder hermes only LISTS (`runtime.project.artifacts.list` over the fill, names and sizes);
  what is written there is the launcher's owner-serialised outputs. Hermes writes nothing into it.
- `guidance`: §2; injected as a prompt section headed by the Project name when shared and the instance's workspace
  holds the Project, with a receipt beside the slot receipts.

## 8. Naming-map amendment (owner's open direction, now the design)

`launcher-project`: "declares its slots; a Hermes workspace holds its id in `project_ids`; its record is
`store/projects/<id>.json`, synced by the `project` family"; `repo-slot`: "a named repository a Project
declares"; `slot-folder`: "a Project's slot's folder on one machine in one namespace". Address:
`project:<id>/repo-slot:<name>` (shared) and `machine:<id>/namespace:<id>/slot-folder:<project>/<slot>`
(the join); `realm:/realm-workspace:/repo-slot:` is read, never printed. A dated paragraph in the map records
this when H-P2 lands; the rows table there gains the §9 ids.

## 9. Slices (one lane each, file-disjoint, in build order)

| Row | Files | Done when |
| --- | --- | --- |
| `RT-PROJECT-RECORD-STORE` (H-P1) | `agent_runtime/project_store.py` (new), `paths.project_path`, `realm_sync/families.py` (`PROJECT`), `agent_runtime/project_sync.py` (new, the applier), `serve_rpc/project.py` (new: show / declare / slot.bind / slot.env.set / category.set / guidance.set / report), `call_authorization.py`, `02-runtime-data-and-shapes.md` §55 | the record round-trips; `category.set(shared=True)` on a local slot refuses `category_not_source_controlled`; a Project in two realms publishes to both and refuses `realm_publish_denied` naming the one denied; the applier drops a malformed peer slot whole |
| `RT-PROJECT-SLOT-REKEY` (H-P2) | `machine_roots.py` (schema 4 `project_roots`), `workspace_slots.py` (`bound_path(project_id=)`, census), `address.py` (`Kind.PROJECT`, pair), `paths.slot_worktrees_path`, `slot_worktrees.py`, `work_store/writer.py` worktree key, `project_migration.py` (new), naming map §8 | the migration of a fixture namespace (2 workspaces, 3 slots, 2 fills, 1 worktree record, 2 instances) produces equal counts, is a no-op the second time, and a crash after step 1 completes on retry without a duplicate Project |
| `RT-PROJECT-SLOTS-FOR-AGENTS` (H-P3) | `persona_slots.py` (`<project>/<slot>` keys, `load_slot_context` over `workspace.project_ids`, `show_instance_slots` grouped by Project), `workspace_projects.py` (disconnect drops that Project's assignments in the same write), `serve_rpc/workspace_slots.py` (`slot_migrated` answers) | an instance assigned `p1/launcher` loads that slot's files; an empty assignment loads nothing; disconnecting `p1` removes `p1/*` from every instance of the workspace and no other |
| `RT-PROJECT-CATEGORY-FOLDERS` (H-P4) | `agent_runtime/project_categories.py` (new: folder resolution, `context_files`, documents section, guidance section, `artifacts.list`), `work_store/default_brain.py` (boards = the category's `brain_dir`) | the documents folder's listed files load as sections; an unlisted file does not; guidance loads only when shared; a board under a Project path has one publisher |
| `RT-PROJECT-CHAT-TURN-LOGS` (H-P5) | `agent_runtime/project_chat_export.py` (new), `serve_rpc/project.py` (`chat.share`), `chat_turn_reservations.py` hook, `work_store/writer.py` (`chat_turns_appended`), `redaction.py` reuse | a shared chat's turns appear as lines keyed by `message_uid`; a second turn appends one line; a secret-shaped assignment is scrubbed; an unshared chat exports nothing; unshare removes the folder in one commit |
| `RT-PROJECT-CHAT-SHARED-FOLD` (H-P6) | `agent_runtime/project_chat_fold.py` (new), `paths.project_chat_store_path`, `workspace_projects.py` + `project_store.set_category` (drop), `chat_session_scope.py` (never a head) | two writers' files for one chat fold into one session in `(ts, seq)` order; a re-fold inserts nothing; disconnecting the Project deletes the store and leaves `state.db` byte-identical |
| `RT-PROJECT-CHAT-RECALL-ACROSS-STORES` (H-P7) | `tools/session_search_tool.py` (`shared_stores`, merge, label, `@project:` links), `models.py::PersonaInstance.recall_shared_projects`, `serve_rpc/workspace_slots.py` (`recall.set`), the turn's tool wiring | with the switch off a shared hit never appears; on, it appears labelled with its author; `@project:` scroll reads the shared store; the own store's `current_lineage` exclusion still holds |

Order: H-P1 → H-P2 → H-P3 → H-P4 → H-P5 → H-P6 → H-P7. The launcher's slices wait on H-P1 (contract), H-P2/H-P3
(slot authority and picker), H-P4 (share switches), H-P7 (chat actions and the recall switch).

## 10. Test plan — the red each test must show

- `tests/agent_runtime/test_project_store.py`: revert the `category_not_source_controlled` check → a local slot's
  category shares (red); revert the per-realm loop → a Project denied in realm B still publishes there (red).
- `tests/agent_runtime/test_project_migration.py`: delete the `migrated_to` stamp → the second run creates
  `ws-<ws>` twice / doubles counts (red); swap step 2's key → a fill lands under the workspace id (red).
- `tests/agent_runtime/test_persona_instance_slots.py` (extended): make `load_slot_context` read
  `workspace_slots` again → an instance assigned `p1/launcher` loads nothing (red).
- `tests/agent_runtime/test_project_chat_export.py`: drop the cursor update → the second turn re-exports the
  first line (red); drop redaction → a `TOKEN=…` line reaches the file (red).
- `tests/agent_runtime/test_project_chat_fold.py`: replace the `turn_uid` check with a session-id check → the
  second machine's turns are skipped (the `import-sessions` defect, red); drop the UNIQUE index → a re-fold
  doubles rows (red).
- `tests/agent_runtime/test_project_chat_recall.py`: make `session_search` fold shared hits into the own list
  without the label → the assertion on `shared_from` reds; with the switch forced on in code → the switch-off
  case reds. A gate asserts no module but the fold and recall opens `store/project_chats/` (source walk, a
  NEGATIVE guarantee), and `is_canonical_session_persistence(shared_db) is False` at runtime.
- Realm-sync fixture round trip for the `project` family beside `test_realm_sync_workspace_slots.py`.

## 11. Blast radius

`workspace_slots.py`, `machine_roots.py`, `persona_slots.py`, `address.py`, `paths.py`, the realm-sync families and
pull, `work_store/writer.py`, `session_search_tool.py`, `PersonaInstance`; every launcher reader of the
workspace-keyed slot verbs (answered `slot_migrated` until the launcher's `COMP-PROJECT-SLOT-AUTHORITY-REKEY` lands).
`state.db` is not touched by any slice: the shared store is a separate file and the export reads only. The
`upstream footprint` ratchet is untouched (every new module is under `agent_runtime/`; `session_search_tool.py`
is already fork-edited).

## 12. Decisions the plan took (the owner may veto; none is a blocker)

1. One shared store per Project per namespace (not per Project and agent): the fold is one, the per-agent
   switch decides who reads it.
2. The recall switch is per persona instance, default off, gated by the Project's chats share.
3. The chats category publishes automatically through the Work writer; documents / boards / artifacts publish
   on the operator's own commit (never auto-committed).
4. `guidance` (description + instructions) is a fifth category with its own switch, default off.
5. Workspace-only slots migrate into a generated `ws-<workspace>` Project; nothing is merged by path or URL.
6. The fill is keyed per Project, not per workspace.
