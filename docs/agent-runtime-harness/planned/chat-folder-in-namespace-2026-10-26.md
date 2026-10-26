# Planned — a chat's scratch folder inside the namespace (RT-CHAT-FOLDER-IN-NAMESPACE, 2026-10-26)

**Owner domain:** transport and wire ([03-transport-and-wire.md](../03-transport-and-wire.md), native
conversations), chat turn lane ([05-chat-turn-lane.md](../05-chat-turn-lane.md), the workdir ladder).
**Status:** RULED 2026-10-26 (lane w1026a-h-b, by the wave brief's "go with recommendations"); build rows in §5.
**Spec:** [naming-and-address-map-2026-10-25.md](naming-and-address-map-2026-10-25.md) ruling 5 — "chat
folders live inside the namespace, under their persona instance; the launcher's AppData folder and its
route are deleted."

## 1. What is true today (read 2026-10-26 on `main`)

- The only per-chat folder is the launcher's `…\eternia_launcher\agents\workspaces\<hash>`. The LAUNCHER
  chooses it and hands it as `cwd` to `agent_runtime/conversations/service.py::ConversationService.open`,
  which refuses a relative or missing directory and stores it on the route
  (`native_conversation_routes.db`, `conversation_routes.cwd`). A resume must present the same `cwd` or
  is refused `wrong_owner`.
- A Mission Control turn has no chat folder: `agent_runtime/mission_chat_workdir.py` resolves persona
  workdir → workspace pointer → `repo_scope` → the operator's HOME → process cwd.
- `persona_instances/` holds one JSON per instance, so a folder cannot live inside it.

## 2. Decisions

1. **The path.** Decided (plan): `<store_root>/chat_folders/<persona_instance_id>/<chat_session_id>/`,
   one helper `paths.chat_folder(instance_id, session_id)`; a native route that has no persona instance
   yet uses `<store_root>/chat_folders/profile-<profile>/<route_id>/` until `migrate_conversation` adopts it.
2. **`open` mints the folder when no `cwd` is given.** Decided (plan): `cwd` becomes optional on
   `runtime.conversation.open` (additive wire); omitted → hermes creates the folder and stores it on the
   route. A given `cwd` keeps today's behaviour (a deliberate project folder). The launcher stops passing
   its AppData path — a launcher row.
3. **Mission Control turns get the folder too.** Decided (plan): the workdir ladder gains the chat folder
   as rung 4, before the operator's home; a configured workdir, workspace pointer or `repo_scope` still
   wins. The folder is created on the turn's first use, never pre-created for every chat.
4. **The old folder and route.** Decided (plan): a one-shot `hermes harness conversation chat-folder
   migrate [--apply] --json` (dry-run default): for each route whose `cwd` is under the launcher's
   `agents/workspaces/`, an EMPTY folder is removed and the route's `cwd` rewritten to its new chat folder
   (so a resume presents the new path); a non-empty folder is MOVED into the new path first. The route row
   is deleted only after `migrate_conversation` has bound it (its receipt `bound`) — the transcript then
   lives in the persona chat and the route has nothing left to resume. Never run by a lane against a live
   namespace.

## 3. Recommendation

Build F1 (path + optional `cwd`) and F2 (ladder rung) on hermes, then the launcher row, then F3 (the move).

## 4. Not decided here

- Retention of chat folders after a chat is retired: archive with the chat (retire never deletes), so
  nothing is removed until an archive policy exists.

## 5. Build rows

Hermes: `RT-CHAT-FOLDER-F1-OPEN-MINTS`, `RT-CHAT-FOLDER-F2-WORKDIR-RUNG`, `RT-CHAT-FOLDER-F3-MOVE-VERB`.
Launcher (handed to the orchestrator): `MC-CHAT-FOLDER-STOP-APPDATA` — stop passing
`agents/workspaces/<hash>` as `cwd` once hermes advertises the optional `cwd`.
