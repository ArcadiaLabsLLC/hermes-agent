"""Workspace connections to Launcher Projects; references, never another roster.

Slots, instance placement, instructions and work retain their existing owners.
A connection neither assigns slots nor shares content. WorkspaceStore is the
single writer; this command adds revision and realm authorization checks.
"""

from . import paths
from .models import Workspace
from .store import WorkspaceStore
from .workspace_slots import SlotRefused, require_publish_right

__layer__ = "stores"


def set_project_connection(workspace_id: str, project_id: str, *, connected: bool,
                           expected_revision: int, credential=None, machine_own: bool = False) -> dict:
    """Connect or disconnect one Project reference under the realm publish right.

    ``machine_own`` is the slot migration's door (``project_migration``): moving this machine's own
    workspace slot document into its generated Project is this machine's write, so it runs without a
    realm credential; the record then syncs under the realm's right as any publish does.
    """

    for key, value in (("workspace_id", workspace_id), ("project_id", project_id)):
        if not isinstance(value, str) or not value or paths.safe_path_token(value) != value:
            raise SlotRefused("invalid_reference", key)
    if not isinstance(connected, bool) or type(expected_revision) is not int or expected_revision < 0:
        raise SlotRefused("invalid_declaration", "connected and expected_revision are required")
    def change(workspace: Workspace) -> None:
        if not machine_own:
            require_publish_right(workspace_id, credential)
        if workspace.archived and connected:
            raise SlotRefused("workspace_archived")
        if workspace.project_assignment_revision != expected_revision:
            raise SlotRefused("stale_revision")
        present = project_id in workspace.project_ids
        if present != connected:
            workspace.project_ids = ([*workspace.project_ids, project_id] if connected
                                     else [value for value in workspace.project_ids if value != project_id])
            workspace.project_assignment_revision += 1
    workspace = WorkspaceStore().update_project_connections(workspace_id, change)
    dropped: list[str] = []
    if not connected:
        from .persona_slots import drop_project_slots

        # The Project's slots leave every instance of THIS workspace with the reference (plan §3, H-P3).
        dropped = drop_project_slots(project_id, workspace_id=workspace_id)
        from .project_store import project_workspaces

        if not project_workspaces(project_id):
            from .project_chat_fold import drop_project_chats

            # The last workspace of this namespace let go: the shared store goes, nothing else (plan §6).
            drop_project_chats(project_id, reason="project_disconnected")
    return {"workspace_id": workspace.id, "project_ids": workspace.project_ids,
            "revision": workspace.project_assignment_revision, "assignments_dropped": dropped}
