# Naming and address map — machine, install, namespace, agent, realm (2026-10-25)

Designed, not implemented. Owner sitting 2026-10-25 (the Neko trial audit), rulings recorded below.
The as-built half was verified the same day against this tree and the owner's live account namespace;
every claim cites the file that proves it.

## Why

One audit of one chat turn had to search three roots before it found the turn record, because the words
that name where data lives each mean several things: "namespace" (account data, a pinned QA store, "both
editions", Centrifugo), "workspace" (the realm's team workspace, a per-chat folder, upstream's per-profile
`workspace/`, a Projects tab), "profile" (launcher profile, agent profile), "machine" (a slot report key that
is really a namespace's install id) and "base" (three things). Owner: "it might be cleaner to specify …
because they all are referenced and when programming it can be an issue to distinguish, especially since
namespaces would stack by index to get an accurate reference like an IP address."

## The map as built (verified 2026-10-25)

```
machine                                     (no id of its own today — see D1)
├─ installs (code only, read-only to every namespace)
│  ├─ Developer Edition: the hermes-agent checkout, editable install + the base root's venvs/, bin/
│  └─ bundled Eternia Harness: a pinned closure (EterniaLauncher installer/hermes/bundled-hermes.lock.json,
│     profile bundled-desktop) + python-build-standalone — not a wheel (setup.py refuses bdist_wheel)
├─ base root per install                    Developer: X:\Eternia\.hermes   bundled: %LOCALAPPDATA%\Eternia\bundled-hermes
│  └─ namespace-active.json                 which namespace an outside-the-launcher process reaches (Q9)
└─ namespaces folder, shared by both installs (ADR 0037; owner override X:\Eternia\hermes-namespaces)
   ├─ acct-<sha256(keycloak sub)[:16]>      id chosen by the launcher from the signed-in account
   ├─ stagec-smoke, stagec-smoke-2          id chosen by the launcher from ETERNIA_PROFILE
   └─ <namespace>
      ├─ namespace.json                     manifest: id, seeded_from, instances, last_written_by {edition, commit}
      ├─ <store>/gateway install record     the namespace's install id (peers, pairing, hosted rooms)
      ├─ machine_roots.json                 roots.<name> (config path tokens) + workspace_roots.<ws>.<slot> (slot folders)
      ├─ projects.db, kanban.db             UPSTREAM stores (per-profile projects; upstream's collaboration board)
      ├─ profiles/<agent profile>/          alice, neko, base … — config, SOUL, skills, memories, state.db
      └─ agent-runtime/
         ├─ realms/<id>.json                realm: name, server_id, agent_publish_mode — synced by realm_sync
         ├─ workspaces/<id>.json            realm workspace: name, realm_id
         ├─ workspace_slots/<ws>.json       declared slots + machines.<"machine id">.slots reports
         ├─ boards/board_default_<ws>/      OUR board, one per realm workspace (models.py Board)
         ├─ persona_instances/<id>.json     the agent: persona_id, profile_id, realm_id, workspace_id,
         │                                  assigned_slots, default_chat_session_id, chat_head_home
         └─ mission_chat_turns/<chat>_<n>.json   one record per chat turn: elements (every tool call), phases, budgets
```

Facts the tree rests on:

- A namespace is a complete data root that borrows an install read-only; `base` names the base root and is
  NOT a namespace (`hermes_cli/_namespace_bootstrap.py` module docstring, `layout`). Namespaces are siblings in
  one folder, never nested (`namespaces_dir` refuses containment either way).
- Account and launcher-profile namespaces are the same mechanism; only the id's origin differs, and only the
  launcher knows it (`EterniaLauncher/lib/core/services/hermes/hermes_namespace.dart`). `SOURCE_ENV` is declared
  in the bootstrap and never written, so the manifest cannot say which kind it is.
- The slots' "machine" key is `workspace_slots.machine_id()` = the gateway install id of the store root
  (`agent_runtime/workspace_slots.py`) — per namespace, and re-minted by a reseed: testv4's only report sits
  under an id no namespace holds any more.
- Every persona instance's chat history is the `base` agent profile's `state.db`, chosen by
  `agent_runtime/chat_session_scope.py` to retire the 2026-07-27 split read; `session_search`
  (`tools/session_search_tool.py`) reads `get_hermes_home()/state.db`, so during a turn it searches either
  the agent's own profile (which holds none of its Mission Control chats) or `base` (which holds every
  agent's) — which of the two is unverified and is pinned by `RT-CHAT-HEAD-PER-PROFILE`; neither is
  per-agent recall.
- The account namespace was seeded from the base root on 2026-10-20 (`namespace.json` `seeded`), and the base
  root still holds those copies plus older logs; nothing writes them.
- The only per-chat folder on the machine is `…\com.arcadialabs\eternia_launcher\agents\workspaces\<hash>`,
  empty, from the single row in `agent-runtime/native_conversation_routes.db` (2026-10-08) — outside every
  namespace.
- `kanban.db` and `projects.db` are upstream features (`hermes_cli/kanban_db.py`, `hermes_cli/projects_cmd.py`);
  Mission Control's board is ours (`agent_runtime/models.py`, `agent-runtime/boards/`) and only borrows the word.

## Rulings (owner, 2026-10-25)

1. **The base root holds an install only** — code, environments, `namespace-active.json`. Its pre-seed copies
   are marked as moved (`RT-BASE-ROOT-STALE-AFTER-SEED`); no agent works from it.
2. **One kind of namespace, with an origin**: `origin: account | launcher-profile` in `namespace.json`.
   Deletion-on-account-removal and sandbox treatment follow the origin.
3. **Machine id and install id are split.** One machine id per PC, kept beside the shared namespaces folder
   (outside both installs, read by both editions); the install id stays per namespace.
4. **Chats are stored per agent profile**: a persona instance's chat head is its own agent profile, so each
   agent has its own `state.db` and its own recall; reads and writes move together through
   `chat_session_scope`, and existing chats in `base` move once.
5. **Chat folders live inside the namespace**, under their persona instance; the launcher's AppData folder and
   its route are deleted. Git worktrees an agent cuts are development workspaces — machine-level checkouts of
   a repo slot — and the harness records each one against that slot's folder.
6. **`machine_roots.json` names its two halves**: config roots and slot folders, then merges them so one slot
   folder is one config root.
7. **Realm and workspace records stay per-namespace copies kept in step by realm sync.**
8. **Upstream's kanban leaves our map**, and our board stops calling itself kanban (name: see the open question).
9. **Editions are not an address segment** — the data is the same whichever edition reads it; every turn record
   and audit line carries the edition, commit and code-tree digest that ran it.

## The qualified names

| Name | Meaning |
| --- | --- |
| `machine` | one PC (new id, ruling 3) |
| `install` | one edition's code: `developer` or `bundled`; `base-root` is its own folder |
| `namespace` | one data root; attribute `origin` (`account` / `launcher-profile`); attribute `install-id` |
| `agent-profile` | `profiles/<name>`: config, SOUL, skills, memories, chat `state.db` (ruling 4) |
| `persona` / `persona-instance` | the role / the agent you chat with; players see "role" and "agent" |
| `chat` / `turn` / `chat-folder` | a conversation / one turn / a chat's scratch space inside the namespace |
| `realm` / `realm-workspace` / `repo-slot` | the shared world / its team workspace / a named repository it declares |
| `slot-folder` | a repo slot's folder on one machine in one namespace; it points at a `project` |
| `development-workspace` | a git worktree cut from a slot's repository |
| `project` | upstream's per-profile project (folders, chats, context) |
| `centrifugo-channel-namespace` | the server's realtime channel group, always written in full |

Player-facing copy uses the short word only where it has one meaning: "Workspace" (realm workspace), "Agent
data" (a namespace), "Sandbox" (a launcher-profile namespace), "agent", "role".

## The address

```
machine:<machine-id>/namespace:<id>/persona-instance:<id>/chat:<id>/turn:<id>
realm:<id>/realm-workspace:<id>/repo-slot:<name>                       (shared, synced)
machine:<machine-id>/namespace:<id>/slot-folder:<workspace>/<slot>     (the join → project, worktrees)
```

Each segment carries its kind, so a bare id never names anything. One typed address value on each side
(hermes and launcher) with one print/parse format; every audit line, turn record and agent commit trailer
(`RT-AGENT-COMMIT-ATTRIBUTION`) prints it.

## Open question (owner)

What our board is called once it stops borrowing "kanban". Recommend **Mission Board** — the launcher's code is
already `mission_board_*`; "todo" is taken twice (upstream's `todo` toolset, and the brains' `TODO.md` / work
queues).

## Rows

Hermes `runtime-queue.md`, 2026-10-25: `RT-NAMING-ADDRESS-VALUE`, `RT-MACHINE-ID`, `RT-NAMESPACE-ORIGIN`,
`RT-CHAT-HEAD-PER-PROFILE`, `RT-CHAT-FOLDER-IN-NAMESPACE`, `RT-WORKTREE-RECORDED-ON-SLOT`,
`RT-MACHINE-ROOTS-TWO-HALVES`, `RT-BOARD-NOT-KANBAN`, `RT-TURN-EDITION-STAMP`, plus the already-filed
`RT-SLOT-MACHINE-ID-IS-NAMESPACE-INSTALL`, `RT-BASE-ROOT-STALE-AFTER-SEED`, `RT-THREE-BASES`,
`RT-TURN-AUDIT-ENTRY`, `RT-AGENT-COMMIT-ATTRIBUTION`. Launcher: `MC-TERMS-NAMESPACE-WORKSPACE-PROFILE`
(copy), `MC-ADDRESS-VALUE-LAUNCHER`.
