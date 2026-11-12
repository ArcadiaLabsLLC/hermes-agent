# Leaving and re-joining a server: the local copy stays, the server's realm comes back fresh (2026-11-12)

Status: PLANNED 2026-11-12 by lane w1112b-hm-rejoin2; slice 1 BUILT the same day (`agent_runtime/realm_rekey.py`:
the place table as top-level store entries, the map, the journal, the JSON-store steps, the census — one module,
not the package §3 names; nothing calls it). Task `TASK-REJOIN-FRESH-REALM` (slug `rejoin-fresh-realm`,
runtime queue). Nothing here is built unless §9 says so; until the switch-over row lands a member sees the
behaviour of ed84b2c01a / 30bf4d08c7 (the realm turns local at the leave; a re-join binds the SAME realm id again
and merges).

## 1. The rulings (owner, 2026-11-12)

- After you leave a server — any member-side reason, "Yes, keep it wide" — its realm stays and "is now a local
  realm" (built, ed84b2c01a).
- Re-join: "it would be less buggy if it kept your local realm and then re-pulled the fresh one from the community
  server". Identity: "it should be rekeyd as soon as you leave and checked for a rekey again once joined back".
- "Yes, own task", accepting two recommendations: (1) the leave makes the realm local at once and records the
  re-key as OWED; the one owned re-key function runs the first moment nothing is running in that realm, at the
  latest at the next serve start; a re-join finishes any owed or half-done re-key before its fresh pull and answers
  a retryable "realm busy" while a turn is live. (2) The agents and their chats return with the fresh server realm
  under the team's ids (chats never leave the machine); the local copy keeps workspaces, boards and cards, office
  layout, levels, brain and Work history under new ids and gets new agents of the same personas at its desks, with
  empty chats.

## 2. Why a re-key at all (survey, lane w1112b-hm-rejoin, verified here)

Workspace ids are global on an install (`paths.workspace_path`), the generic pull writes the team's workspace files
over them and re-homes a colliding workspace (`realm_sync/pull.py`), and a persona instance id is account-wide and
is the team's identity (`persona_instance_sync/contract.py`; chat sessions are named after it,
`persona_assignments/identity.py`). So the local copy and the fresh server realm cannot share a realm id, a
workspace id or an agent id.

## 3. Three kinds of place — the one table

Every place that holds a realm id, a workspace id or an agent id is in exactly one class. The table is code
(`agent_runtime/realm_rekey/places.py`), total over `agent_runtime/paths.py` (a path function that takes a
`workspace_id`, `realm_id`, `board_id` or `persona_instance_id` and is in no class reds the census test).

| class | what happens at the re-key | places |
|---|---|---|
| MOVES | renamed / rewritten to the new ids; this is the local copy | `realms/<realm>.json`; `workspaces/<ws>.json`; `workspace_slots/<ws>.json`; `office/<ws>/` (surface, actors, archive, conflicts) and `office_archive/<ws>/`; `boards/board_default_<ws>/` and every board whose `workspace_id` is in the map (board id, each card's `board_id`); `levels/<ws>.json`; `slot_worktrees/<ws>/`; `work/<ws>/` (default brain, `default_brain.json`'s absolute path, runs, activity, claim goals, lane worktrees); `schedules/*.json` whose workspace is in the map; `realm_sync/<realm>/` baselines and conflicts (keys `<ws>:actor:<key>`, level tokens, board ids); `realm_sync_state/<realm>.shared_from.json`; the local sync clone subtree `realms/<realm>/`; `<skills>/.realm_inbox/<realm>/` and skill provenance `source.realm_id`; pointers `active_workspace.json`, `active_realm.json`, `default_realm.json`, `brain_paths.json`; `<root>/machine_roots.json` slot folders, `machine_slot_env.json`, `machine_slot_runs.json`; lens monitors (`lens.sqlite3`, workspace column) |
| PARKS | untouched, keeps the team's ids, invisible until the re-join brings the realm back | the agents: `persona_instances/<agent>.json` (moved to `persona_instances_parked/<old realm>/`, NOT a retire tombstone — a tombstone would stop the pull bringing the agent back), `chat_folders/<agent>/`, `state.db` sessions, discussion tables, conversation routes, `chat_goal_bindings`, mint receipts; workspace chats: `workspace_chats/<ws>.db`, `workspace_chat_fold/<ws>.json`, `workspace_chat_exports/<ws>/`, `work/workspace_chats_<ws>/`; `realm_sync_state/<realm>.team_baselines/` (dropped at the switch-over, §7) |
| HISTORY | never touched | `events.jsonl` and its archive, `prompt_observability*`, `patch_diffs*`, the deleted archive, `migration_backups`, `persona_instances_archive`, `persona_assignments_archive`, `runs/`, `incidents/`, git object stores (`.git/` of a brain, a sync clone) |

Built by slice 3 (`agent_runtime/realm_rekey_agents.py`): `persona_instances/` is classed MOVES, because the
`agents` step runs first and moves the team's rows to `persona_instances_parked/<old realm>/` (PARKS); what is
left there is the install's own channels and the local copy's new agents, re-pointed like any other row.
`flow_graphs/` is MOVES too (a canvas is its owner's and follows the desk: `runtime_<agent>.json`).

"Chats park" is the reading of ruling (2): chats never leave the machine and return with the agents. Workspace
chats and discussions are chats, so they park too; the local copy starts with none.

## 4. The owned re-key operation (`agent_runtime/realm_rekey/`)

One function, `rekey_realm(journal)`. Nothing else renames a realm or a workspace.

- **The map.** `RekeyMap(realm: old→new, workspaces: {old: new}, boards: {old: new}, agents: {old: new})`, minted
  once and written to the journal BEFORE the first step, so a resume uses the same new ids. New ids come from the
  stores' own minting (`realm_<slug>_<hex6>`, `ws_<slug>_<hex6>`, `personainst_<persona>_agent_<hex8>`); a board
  id that embeds its workspace (`board_default_<ws>`) follows it; other board ids get a fresh suffix only when
  the team's copy publishes that id (they all do — boards sync), so every board of a moved workspace is re-keyed.
- **The journal.** `realm_rekey/<old realm id>.json`: `state` (`owed` | `running` | `done`), the map, `owed_at`,
  `reason`, `steps_done`. Written atomically (temp + replace). `owed` → `running` when the first step starts;
  `done` is written last and kept (it is what a re-join's collision re-check and Eternia's id map read).
- **Steps, each idempotent** (does nothing when the old shape is gone), in an order that keeps the store loadable
  after a crash at any point: (a) content rewrites inside MOVES files, by exact id and by the known derived forms
  only (`board_default_<ws>`, `<ws>:actor:<key>`, `ws-<ws>` — the level `sceneId`, §8 — and a path segment equal
  to the id inside an absolute path); JSON is walked as values and keys, never by text search, so an id that is a
  substring of another id cannot be hit; (b) renames of MOVES files and directories, old → new (when both exist
  after a crash or a late write, the old one's entries are merged in and never overwrite a newer file); (c) the
  realm record last: its id, `workspace_ids`, `default_workspace_id`, ledgers (`deleted_workspace_ids`,
  `workspace_lifts` are dropped — they speak to the team's copy); (d) pointers; (e) git: `git worktree repair` in
  the default brain and each lane worktree, and ONE new commit in the default brain that rewrites the workspace id
  in `BATCH-*.md` frontmatter and `persona:<old agent>` claim text to the new ids — history is never rewritten,
  old commits keep the old ids and that is correct (they describe the past); a brain repository that is the
  user's own clone (a folder slot) is not touched: its `work/<machine>.<ws>.<name>` branches keep their names
  (HISTORY), new lanes cut under the new id; (f) the journal turns `done`, one `realm.rekeyed` event carries the map.
- **The census test** (`tests/agent_runtime/test_realm_rekey_census.py`): seeds one runtime root through the real
  stores with every MOVES and PARKS place populated for one server realm of two workspaces, runs a publish and a
  pull while local (lane hm-leftrealm's INEFF: the unit test passed while the real path lost a card), re-keys, then
  walks every file name and every file's content under the runtime root (sqlite read row by row): an old id may
  appear only under a PARKS or HISTORY place, a new id never under one; the stores load the local copy under the
  new ids and it equals the before-state id for id. A second test kills the process after each step in turn and
  re-runs: same end state.

## 5. When it runs — owed, idle, serve start, re-join

- **Leave** (`realm_leave.make_realm_local`): as today, plus the journal `owed` (map minted). Nothing is renamed.
- **How idle is known.** Inside the serve: the re-key takes `profile_runner.workdir._WORKDIR_LOCK` without
  blocking (every run body passes through it) and requires `agent_runs_in_flight() == 0`, no live turn
  (`live_turns`), no Work run open and no build running for a workspace in the map; then holds
  `workspace_realm_assign_lock` for the whole operation. This is serve-wide for runs (coarser than "in that
  realm"): simpler, and it is what makes Windows safe — no run has a cwd or an open file under a directory that
  is about to be renamed. Outside a serve (an argv child): `namespace_admin.busy_reason` — a live serve holds
  the socket lock → the child never re-keys, it asks the serve.
- **Triggers.** (1) idle: the serve's housekeeping tick tries each `owed`/`running` journal; (2) serve start:
  before the socket accepts a connection, so Eternia never sees the old ids from a serve that was restarted;
  (3) re-join: `adopt_realms` finishes it first.
- **A rename that fails** (Windows: Eternia or an editor holds a folder open) leaves the journal `running` with
  the failing step named; the next trigger resumes. Nothing is half-visible: step (a)/(b) for one workspace run
  under that workspace's office and board locks.
- **"Realm busy".** `runtime.realm.adopt` (and the argv twin) answers the retryable refusal `realm_busy` with
  `realm_id`, `retry_after_ms` and what is running (`turn` | `work_run` | `build` | `rename_blocked`) when an owed
  re-key cannot run now. Nothing is adopted in that call.

## 6. Agents

- **The team's agents park** (§3). Their records move to `persona_instances_parked/<old realm>/`; chats, sessions
  and routes are not touched.
- **The local copy gets new agents of the same personas.** For each parked agent with a desk in a moved workspace
  the re-key mints one instance through the existing door (`PersonaInstanceStore.replicate_instance`,
  `persona_assignments/replicate.py` — the mint a first-time joiner's pull uses: definition copied, runtime state born fresh, a fresh chat root) and records
  old → new in the map. Afterwards the desk's office actor (actor key and file name), the flow-graph owner,
  schedules and open Work claims of the local copy name the NEW agent. Claim text committed in the brain's history
  keeps the old agent id; the one new commit of §4(e) rewrites the live rows.
- **At the re-join** the parked records go back into `persona_instances/` before the fresh pull, so the pull finds
  the team's agents present (its mint is for a missing one) and their chats re-attach by id.
- A parked agent with a live turn cannot exist: the re-key runs only when idle (the step refuses an agent with
  a live run binding and leaves the journal `running`).
- **As built.** The map carries `agents: {old: new}`; a new id is the old one with a fresh placement tail
  (`personainst_<persona>_agent_<hex8>`). A persona's own channel (`personainst_<persona>`) belongs to no realm
  and never parks. The agents of the map are the ones the realm held when the re-key was OWED (the leave): an
  agent added while local is the member's own, keeps its id and its chats, and is only re-pointed. The new agent
  keeps the travelling definition (name, model lane, skills, slots, character) plus the two local answers
  `display_name_custom` and `slot_context_custom`; it is born idle with an empty chat. Its steering edges are the
  old ones mapped through the agents map. Rewritten tokens: the id, the placement id (the id without
  `personainst_`, the office item's id where Eternia minted it), `runtime_<id>` (the stored flow-graph id), and
  the capped actor file token of a long key.
- **Work claims.** A claim held in the store's JSON (`work/<ws>/` runs, activity, claim goals) reads
  `persona:<new agent>` after the re-key; claim text in the brain's markdown is slice 2's one new commit.

## 7. The fresh adopt, and what is removed

- `adopt_realms` for a granted realm whose id is not on this install: finish every owed re-key (or `realm_busy`),
  **re-check for collisions** — any local workspace, board or agent id the team's manifest publishes that is still
  held by another realm here is re-keyed aside through the same operation (a one-workspace map) — restore parked
  agents, then adopt and pull exactly as a first-time joiner. The team repository's head is not moved by a re-join.
- An install that already re-bound under ed84b2c01a (same realm id, bound again) is left as it is: it has no
  `shared_from` record and no journal, so nothing here matches it.
- Removed in the switch-over landing: `keep_team_baselines` / `restore_team_baselines` and
  `realm_sync_state/<realm>.team_baselines/` (`realm_sync/revocation.py`); the re-bind in
  `realm_membership.adopt_realms`; the re-join branch of 30bf4d08c7 (a pull that re-homes on re-join); the wire
  doc's re-join wording (`docs/agent-runtime-harness/03-transport-and-wire.md`). The leave itself, the wide reason
  set, the archive rules and the ordinary-move fixes of 30bf4d08c7 stand.

## 8. Eternia

- **The id map.** The snapshot's realm row for a re-keyed realm carries `rekeyed_from` (`realm_id`,
  `workspaces: {old: new}`, `agents: {old: new}`, `at`), and one `realm.rekeyed` event carries the same. Eternia
  honours it for: the active workspace, the open Office subscription, discussion persistence and view state keyed
  by workspace id (view state follows the local copy; discussion persistence stays with the old id — discussions
  park).
- **The label.** The local copy is named from `shared_from` ("local copy, was shared from <server>") beside the
  live shared realm of the same name after a re-join.
- **Level documents** (read in `EterniaLauncher`, not edited): a scene document's top-level keys are `version`,
  `sceneId`, `assets`, `environment`, `landscape`, `props`, `spawns`, `audioZones`, `triggers`
  (`lib/core/spatial/maps/level_link.dart`); `packages/eternia_spatial/lib/src/scene/scene_document.dart` names
  no workspace, persona or agent. The one embedded id is `sceneId`, the store address `ws-<workspace id>`
  (`lib/core/spatial/editor/level_ref.dart`). hermes rewrites that one top-level string when it equals
  `ws-<old id>` exactly; a link document has no `sceneId` and is moved untouched.

## 9. Slices (rows, group `rejoin-fresh-realm`), in landing order

1. `RT-REKEY-ONE-OWNED-OPERATION` — the table, the map, the journal, the operation for realm and workspace ids,
   the census test. No caller.
2. `RT-REKEY-BRAIN-AND-WORKTREES-FOLLOW` — §4(e). No caller.
   `RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE` — the MOVES places slice 1 does not reach (lens monitors,
   `machine_roots.json`, the skills inbox and provenance, the local sync clone's subtree). No caller.
3. `RT-REKEY-LOCAL-COPY-GETS-NEW-AGENTS` — §6 (park, mint, re-point, restore). No caller.
4. `RT-REKEY-RUNS-WHEN-IDLE-AND-AT-START` — §5 triggers and the busy facts; nothing owes a re-key yet.
5. `RT-REKEY-ID-MAP-FOR-ETERNIA` — §8 `rekeyed_from` + the event, fixture mirrored.
   (`RT-REKEY-NOTICE-LOCAL-COPY-HAS-OWN-AGENTS` is the owner question of §10; it holds nothing.)
6. `RT-REJOIN-PULLS-THE-SERVER-REALM-FRESH` — the switch-over, one landing: the leave owes, the re-join adopts
   fresh with the collision re-check and `realm_busy`, §7's removals, the wire doc, and the two-machine walk
   (leave → edit, new card, move a workspace, archive → idle re-key → re-join → the fresh realm equals the team's
   copy, the local copy holds every local change under new ids, the team head is unchanged, no duplicate id,
   agents and chats are with the fresh realm, a second cycle works, a re-join during a live turn is `realm_busy`).

Eternia rows (filed by the Eternia side): honour `rekeyed_from`; label the local copy; confirm the level reader
accepts a rewritten `sceneId`.

## 10. Open questions, each with a recommendation

- **Idle is serve-wide for runs, not per realm.** Recommend: build it serve-wide (§5); narrow to the realm only
  if owners report re-keys that wait for days. A serve restart always runs it.
- **Schedules of a parked agent.** Recommend: they move with the local copy and name the new agent (a schedule
  is workspace work, not a chat); the fresh realm's schedules come from the team as for any joiner.
- **Do readers tolerate parked data whose workspace is absent** (an orphan sweep that deletes a chat db with no
  workspace)? ANSWERED by slice 3, read in code and pinned in a test: no. Every delete site under
  `agent_runtime/` and `hermes_cli/harness_parts/` was read; none is keyed on "the workspace (or agent) is
  absent". The boot sweeps (`boot_phases._run_boot_sweeps`), the chat-receipt repair and
  `reconcile_persona_instances` run for real over a re-keyed store in
  `test_the_local_copy_gets_new_agents…` and the parked rows and their chat sessions are still there. The only
  chat deletes are operator verbs (`drop_chats` on un-sharing chats, a session delete) and the retired-scratch
  purge (by session source).
- **Never re-joined.** The parked agents' chats stay on disk and are not shown. Recommend: leave them (the
  realm's archive rules already cover deleting a local realm); a row if the owner wants them browsable.
- **Product choice on the row, not inferred:** between the leave and the idle re-key the local realm still shows
  the team's agents with their chats; after it, new agents with empty chats. That change happens on its own,
  later, with no click. Recommend: a one-line notice on the realm ("this copy now has its own agents; the team's
  agents and their chats return when you re-join") — DECISION row
  `RT-REKEY-NOTICE-LOCAL-COPY-HAS-OWN-AGENTS`.
