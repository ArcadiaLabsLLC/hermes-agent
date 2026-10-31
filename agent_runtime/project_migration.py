"""Every workspace slot document becomes a Project, without loss (H-P2, plan §4).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §4. Run once
per namespace on the first serve after landing (``boot_phases._boot_sweeps_and_ready_frame``) and
idempotent under crash and retry: the migration identity is the workspace id, the Project it makes is
``ws-<workspace-id>``, and every write is "set to this value".

For each ``store/workspace_slots/<ws>.json`` with live slots whose workspace record exists:

1. Project ``ws-<ws>`` named "<workspace name> repos", with ``migrated_from: {workspace_id, workspace_name}``
   so a reader can say where it came from (RT-MIGRATED-PROJECT-NAME), takes the document's slots VERBATIM (tombstones
   included) and its ``machines`` (``ProjectStore.adopt_workspace_document``), and is connected to the
   workspace (``set_project_connection(machine_own=True)``). A workspace that already holds connected
   Projects still gets its own ``ws-`` Project: nothing is merged by clone URL or path.
2. This machine's fills are COPIED: ``workspace_roots[ws]`` → ``project_roots["ws-<ws>"]`` (machine_roots
   schema 4), the env fills ``workspaces[ws]`` → ``projects["ws-<ws>"]``, the worktree records
   ``slot_worktrees/<ws>/<slot>.json`` → ``slot_worktrees/ws-<ws>/<slot>.json``. Copied, not moved, so an
   older edition sharing the namespace keeps reading its workspace-keyed fills (the store epoch stays
   additive); this edition reads the Project's, because every workspace-keyed read resolves through
   ``workspace_slots.slot_owner``. Hermes's own Work worktrees are NOT renamed under git:
   ``work_store.writer.work_worktree_for`` keeps using a worktree at its old ``<slot>-<token>`` path until it
   is recut at ``<project>/<slot>``.
3. Every instance of the workspace has its bare slot names re-keyed to ``ws-<ws>/<slot>``
   (``persona_slots.rekey_workspace_assignments``, ``slots_issued_at`` stamped).
4. The old document stays, stamped ``migrated_to: "ws-<ws>"`` with a fresh ``issued_at``; realm sync
   still merges it (the stamp survives the merge) and every reader then reads the Project.

The receipt ``project_migration.completed`` carries per-workspace counts read back from the NEW places
(slots, fills, env fills, worktree records) beside the counts taken from the old ones, and ``equal``.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Any

from . import paths

__layer__ = "stores"

PROJECT_PREFIX = "ws-"


def migrated_project_name(workspace_name: str) -> str:
    """The name a migrated Project takes: what it holds, the workspace's repos."""

    return f"{workspace_name} repos"


def legacy_migrated_project_name(workspace_name: str) -> str:
    """The name the migration gave before RT-MIGRATED-PROJECT-NAME, renamed on the next boot."""

    return f"{workspace_name} slots"


def migrated_project_id(workspace_id: str) -> str:
    return f"{PROJECT_PREFIX}{workspace_id}"


def migrate_namespace() -> dict[str, Any]:
    """Migrate every unmigrated workspace slot document of this namespace; the receipt."""

    from .errors import NotFound
    from .store import WorkspaceStore
    from .workspace_slots import live_slots, load_document_from

    directory = paths.workspace_slots_dir()
    migrated, skipped, already, renamed = [], [], 0, 0
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        document = load_document_from(path)
        workspace_id = str(document.get("workspace_id") or path.stem)
        if document.get("migrated_to"):
            already += 1
            renamed += _rename_legacy(workspace_id, str(document["migrated_to"]))
            continue
        if not isinstance(document.get("slots"), dict) or not live_slots(document):
            continue
        try:
            workspace = WorkspaceStore().get(workspace_id)
        except NotFound:
            skipped.append({"workspace_id": workspace_id, "reason": "workspace_not_found"})
            continue
        migrated.append(migrate_workspace(workspace, document))
    receipt = {"migrated": migrated, "skipped": skipped, "already_migrated": already, "renamed": renamed,
               "equal": all(row["equal"] for row in migrated)}
    if migrated or skipped or renamed:
        from .work_store import receipts

        receipts.emit("project_migration.completed", **receipt)
    return receipt


def migrate_workspace(workspace: Any, document: dict[str, Any]) -> dict[str, Any]:
    """Steps 1, 2 and 4 for one workspace; its counts, old and new."""

    from .project_store import ProjectStore, load_project, migration_origin
    from .workspace_projects import set_project_connection
    from .workspace_slot_env import copy_workspace_fills
    from .workspace_slots import scoped_roots, write_document

    workspace_id, project_id = workspace.id, migrated_project_id(workspace.id)
    before = {"slots": len(document.get("slots") or {}),
              "fills": len(scoped_roots().workspace_roots.get(workspace_id) or {})}
    # 1. the Project, then its connection (both set-to-value)
    ProjectStore().adopt_workspace_document(project_id, name=migrated_project_name(workspace.name), document=document,
                                            migrated_from=migration_origin(workspace))
    if project_id not in workspace.project_ids:
        set_project_connection(workspace_id, project_id, connected=True,
                               expected_revision=workspace.project_assignment_revision, machine_own=True)
    # 2. this machine's fills
    _copy_path_fills(workspace_id, project_id)
    env_copied = copy_workspace_fills(workspace_id, project_id)
    worktrees = _copy_worktree_records(workspace_id, project_id)
    # 3. the assignments
    from .persona_slots import rekey_workspace_assignments
    from .workspace_slots import live_slots

    instances = rekey_workspace_assignments(workspace_id, project_id, frozenset(live_slots(document)))
    # 4. the stamp
    document = {**document, "migrated_to": project_id, "issued_at": datetime.now(UTC).isoformat()}
    write_document(workspace_id, document)
    after = {"slots": len(load_project(project_id).get("slots") or {}),
             "fills": len(scoped_roots().project_roots.get(project_id) or {})}
    return {"workspace_id": workspace_id, "project_id": project_id, "before": before, "after": after,
            "env_fills": env_copied, "worktree_records": worktrees, "instances": len(instances),
            "equal": before["slots"] == after["slots"] and before["fills"] <= after["fills"]}


def _rename_legacy(workspace_id: str, project_id: str) -> int:
    """A Project migrated under the old name takes the new one and its origin (1), else 0."""

    from .errors import NotFound
    from .project_store import ProjectStore, migration_origin
    from .store import WorkspaceStore
    from .workspace_slots import SlotRefused

    if project_id != migrated_project_id(workspace_id):
        return 0  # a Project the migration did not make keeps whatever it is called
    try:
        workspace = WorkspaceStore().get(workspace_id)
        return int(ProjectStore().rename_legacy_migrated(
            project_id, legacy_name=legacy_migrated_project_name(workspace.name),
            name=migrated_project_name(workspace.name), migrated_from=migration_origin(workspace)))
    except (NotFound, SlotRefused):
        return 0


def _copy_path_fills(workspace_id: str, project_id: str) -> None:
    """``workspace_roots[ws]`` into ``project_roots[project]``; a Project fill already set wins."""

    from .machine_roots import write_machine_roots
    from .workspace_slots import scoped_roots

    current = scoped_roots()
    copying = dict(current.workspace_roots.get(workspace_id) or {})
    if not copying:
        return
    projects = {pid: dict(slots) for pid, slots in current.project_roots.items()}
    projects[project_id] = {**copying, **projects.get(project_id, {})}
    write_machine_roots(dict(current.roots), workspace_roots=current.workspace_roots, project_roots=projects,
                        dry_run=False)


def _copy_worktree_records(workspace_id: str, project_id: str) -> int:
    """Each ``slot_worktrees/<ws>/<slot>.json`` into the Project's directory; a record already there wins."""

    source = paths.store_root() / "slot_worktrees" / paths.safe_path_token(workspace_id)
    if not source.is_dir():
        return 0
    copied = 0
    for record in sorted(source.glob("*.json")):
        target = paths.slot_worktrees_path(project_id, record.stem)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record, target)
            copied += 1
    return copied
