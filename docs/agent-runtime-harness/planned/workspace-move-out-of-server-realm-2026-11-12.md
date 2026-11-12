# Moving a workspace out of a server-bound realm (2026-11-12)

Status: PLANNED, not built — waits on one owner decision (§4). Row `RT-WORKSPACE-MOVE-OUT-OF-SERVER-REALM`
(`Harness_Brain/20 — Active Initiatives/runtime-queue.md`). Written by lane w1112b-hm-ws against `origin/main`
at `bfb4beaac0`.

## 1. What works today

`runtime.workspace.move_realm` (`agent_runtime/workspace_manage.py::move_workspace_realm`) moves a workspace
between local realms and from a local realm INTO a server-bound one. A workspace owned by a server-bound
realm is refused `workspace_realm_server_bound`; Eternia draws that reason.

## 2. Why the move out is refused (read in the tree)

A server-bound realm's workspaces travel through realm sync, which knows a workspace by its id only:

1. **No tombstone → it comes back.** Every other member still holds the workspace with the source realm's
   `realm_id`; their next publish puts it back in the source realm, and the mover's next pull of the source
   overwrites the local workspace file with that older copy (`realm_sync/pull.py`, the generic overwrite loop).
2. **A tombstone → the moved workspace is deleted.** `_apply_workspace_tombstones` hard-deletes, by id, every
   local workspace on the pulled realm's `deleted_workspace_ids` — it never reads the workspace's current
   `realm_id` — so the mover's next pull of the SOURCE realm deletes the workspace that now lives in the target,
   office and boards included.
3. **Who may do it.** Leaving a shared realm is a write to that realm. The role check happens at publish, with
   the launcher-brokered credential; `move_realm` takes none, so a member without the role would move locally
   and then never be able to publish the removal.

## 3. The build, once ruled (hermes, then the launcher)

- **S1 — a realm-scoped tombstone.** `_apply_workspace_tombstones(realm_id)` skips a workspace whose current
  `realm_id` is another realm (it moved; it was not deleted). The pull's overwrite loop skips an incoming
  workspace file whose id is on the merged delete ledger of the realm being pulled. Tests: a pull of the source
  after a move keeps the workspace, its office and its boards.
- **S2 — the move writes the leave.** For a server-bound source, `move_workspace_realm` removes the id from
  `workspace_ids`, appends it to `deleted_workspace_ids` and supersedes a live lift (what
  `WorkspaceStore.delete` writes), then joins the target as today. Moving back lifts it again.
- **S3 — the role is checked before the write.** `runtime.workspace.move_realm` takes the optional
  `credential` object the `runtime.realm.*` verbs take; a server-bound source without one, or with a role that
  may not publish, is refused (`sync_auth_failed` / `role_insufficient`) and nothing is written. The reply
  gains `publish_owed: [realm ids]` so the client offers Publish for the source (and the target, when bound).
- **S4 — the launcher.** Eternia passes the credential, confirms with the words of §4, and offers the publish
  (a launcher row in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`, filed
  when this is ruled).
- **Order across machines.** A member of both realms who pulls the source first loses the local copy until the
  pull of the target brings it back; one who pulls the target first keeps it (S1's skip). The mover publishes
  the TARGET first, then the source, so the workspace is never absent from both remotes.

## 4. The owner decision

Moving a workspace out of a shared realm removes it for every member of that realm who is not also a member of
the target: after their next sync it is gone from their machine (S2 is a delete for them). Is that the move the
owner wants, or should a shared workspace only ever be COPIED out (the existing create-from-template) and then
archived in the shared realm by hand?

Recommend: build the move (S1–S4) behind a confirm that names the realm and says its other members lose the
workspace; keep copy-then-archive as the path for someone without the publish role.

## 5. Which task

Not `manage-workspace-genui`: the Manage Workspace page is complete without it (Move to realm… works for local
realms and into a shared one, and draws this refusal's reason). It is realm-sync behaviour, filed under the
"Workspaces and realms" task, group `workspace-absorbs-projects`.
