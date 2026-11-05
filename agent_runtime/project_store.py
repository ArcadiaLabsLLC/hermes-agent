"""The Launcher Project record hermes keeps — slots, category folders, share switches (H-P1).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §2.
A Launcher Project DECLARES repo slots; a realm workspace is assigned Projects
(``Workspace.project_ids``, ``workspace_projects.set_project_connection``) and its agents read
the slots of those Projects. The record lives at ``paths.project_path`` (``store/projects/
<token>.json``) and syncs as the realm family ``project`` (``project_sync``), merged by the slot
document's key-wise rules. :class:`ProjectStore` is its ONE writer.

* ``slots.<name>`` is byte-for-byte the record ``workspace_slots.normalize_declaration`` and
  ``apply_declared_set`` produce for a workspace slot document (tombstones, recipe revisions),
  plus the optional ``context.document_dirs`` / ``adr_dirs``.
* ``categories.<chats | documents | boards | artifacts | guidance>`` is a FOLDER DECLARATION,
  never content: ``slot`` names one of the Project's slots (``None`` = no folder yet) and
  ``subpath`` a folder under it (default ``.eternia/<category>``). A category is source-controlled
  iff its slot has a clone URL; ``shared`` may be true only then (``category_not_source_controlled``,
  the owner's rule, enforced at the write and re-enforced after a merge). ``guidance`` has no
  folder: it is the Project's description + instructions, carried in the record ONLY while
  ``categories.guidance.shared`` is true, so an unshared Project's instructions never sync.
* ``machines.<id>`` is each machine's report, written by the probe (H-P2), never a path.

Authorization (§2): a Project assigned to no realm workspace in this namespace is this machine's
own; otherwise every write runs the realm PUBLISH decision (``realm_sync.git._authorize``) for EACH
realm whose workspace holds the Project, and refuses ``realm_publish_denied`` naming that realm.
"""

from __future__ import annotations

import json
from typing import Any

from utils import atomic_json_write

from . import paths
from .machine_roots import _ROOT_NAME_RE
from .workspace_categories import (
    CATEGORIES,
    FOLDER_CATEGORIES,
    GUIDANCE,
    GUIDANCE_MAX_CHARS,
    apply_category,
    apply_guidance,
    category,
    enforce_share_rule,
    source_controlled,
)
from .workspace_slots import (
    REASON_INVALID_DECLARATION,
    REASON_REALM_PUBLISH_DENIED,
    REASON_SLOT_NOT_DECLARED,
    SlotRefused,
    _declared_record,
    apply_declared_set,
    live_slots,
    normalize_declaration,
    refuse_stale,
    stamp_epoch,
)

__layer__ = "stores"

PROJECT_SCHEMA_VERSION = 1
NAME_MAX_CHARS = 200

REASON_INVALID_REFERENCE = "invalid_reference"


def valid_project_id(project_id: Any) -> str:
    """``project_id`` when it is one safe path token, else ``invalid_reference``."""

    if not isinstance(project_id, str) or not project_id or paths.safe_path_token(project_id) != project_id:
        raise SlotRefused(REASON_INVALID_REFERENCE, "project_id")
    return project_id


def empty_project(project_id: str) -> dict[str, Any]:
    return {"schema_version": PROJECT_SCHEMA_VERSION, "project_id": project_id, "name": "", "issued_at": "",
            "slots": {}, "categories": {}, "machines": {}}


def load_project(project_id: str) -> dict[str, Any]:
    """The Project's record, or an empty one (an unreadable file reads empty until the next write)."""

    try:
        payload = json.loads(paths.project_path(project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_project(project_id)
    if not isinstance(payload, dict) or payload.get("schema_version") != PROJECT_SCHEMA_VERSION:
        return empty_project(project_id)
    for key in ("slots", "categories", "machines"):
        payload.setdefault(key, {})
    return payload


def write_project(project_id: str, record: dict[str, Any]) -> None:
    """The file write; :class:`ProjectStore` (local edits) and ``project_sync`` (a pull) call it."""

    target = paths.project_path(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, record, indent=2, sort_keys=True)
    from .brain_paths import changed

    changed("project.written")


# ── who may write: the publish right of every realm the Project is assigned into ──


def project_workspaces(project_id: str) -> list[Any]:
    """Every live workspace of this namespace whose ``project_ids`` hold the Project."""

    from .store import WorkspaceStore

    return [ws for ws in WorkspaceStore().list_all(include_archived=False) if project_id in ws.project_ids]


def project_realms(project_id: str) -> list[str]:
    """The realms the Project is assigned into (through a workspace of each), sorted."""

    return sorted({ws.realm_id for ws in project_workspaces(project_id) if ws.realm_id})


def require_project_publish_rights(project_id: str, credentials: dict[str, Any] | None = None) -> list[str]:
    """Run the realm publish decision for EACH realm holding the Project; the realms, or a refusal naming one.

    ``credentials`` maps a realm id to the launcher-brokered credential for it (``None`` = the
    server-less allow stub, or a fail-closed refusal for a server-bound realm).
    """

    from .realm_sync.git import _authorize
    from .realm_sync.models import RealmSyncError
    from .store import RealmStore

    realms = project_realms(project_id)
    for realm_id in realms:
        try:
            _authorize(RealmStore().get(realm_id), "publish", None, (credentials or {}).get(realm_id))
        except RealmSyncError as exc:
            raise SlotRefused(REASON_REALM_PUBLISH_DENIED, f"{realm_id}: {exc.code}") from exc
    return realms


# ── the single writer ─────────────────────────────────────────────────────────


class ProjectStore:
    """The ONE writer of ``store/projects/``: every local edit of a Project record goes through here."""

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._credentials = dict(credentials or {})

    def get(self, project_id: str) -> dict[str, Any]:
        return load_project(valid_project_id(project_id))

    def _open(self, project_id: str, issued_at: str, last_stamp: Any = None) -> dict[str, Any]:
        """Authorize, then the record a write lands in, or ``stale_revision`` against ``last_stamp``."""

        valid_project_id(project_id)
        require_project_publish_rights(project_id, self._credentials)
        record = load_project(project_id)
        refuse_stale(record.get("issued_at") if last_stamp is None else last_stamp, issued_at)
        return record

    def _commit(self, project_id: str, record: dict[str, Any], *, issued_at: str | None) -> list[str]:
        unshared = enforce_share_rule(record)
        if issued_at is not None:
            record["issued_at"] = issued_at
        record["project_id"] = project_id
        write_project(project_id, record)
        return unshared

    def declare(self, project_id: str, slots: Any, *, issued_at: str, machine: str,
                name: str | None = None) -> dict[str, Any]:
        """REPLACE the Project's declared slot set (tombstones, never deletes); creates the record."""

        record = self._open(project_id, issued_at)
        declared, tombstoned = apply_declared_set(record, slots, issued_at=issued_at, machine=machine)
        if name is not None:
            record["name"] = _project_name(name)
        unshared = self._commit(project_id, record, issued_at=issued_at)
        from .persona_slots import drop_project_slots

        # A removed slot leaves every assignment of it, in every workspace holding the Project (§3).
        dropped = drop_project_slots(project_id, removed=frozenset(tombstoned)) if tombstoned else []
        return {"document": record, "declared": sorted(declared), "tombstoned": sorted(tombstoned),
                "categories_unshared": unshared, "assignments_dropped": dropped}

    def declare_one_slot(self, project_id: str, entry: Any, *, issued_at: str, machine: str) -> dict[str, Any]:
        """Declare ONE slot, leaving every other slot as it is (nothing tombstoned)."""

        record = self._open(project_id, issued_at)
        slot, body = normalize_declaration(entry)
        current = record.setdefault("slots", {})
        current[slot] = _declared_record(current.get(slot) or {}, body, issued_at=issued_at, machine=machine)
        unshared = self._commit(project_id, record, issued_at=issued_at)
        return {"document": record, "declared": [slot], "tombstoned": [], "categories_unshared": unshared}

    def set_recipe(self, project_id: str, slot: str, steps: Any, *, base_revision: Any, issued_at: str,
                   machine: str, persona_instance_id: str | None = None) -> int:
        """Replace one slot's owner recipe steps (``workspace_slot_recipe_store.apply_recipe``); the new revision."""

        from .workspace_slot_recipe_store import apply_recipe

        record = self._open(project_id, issued_at)
        live = live_slots(record)
        if slot not in live:
            raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{project_id} declares no slot {slot!r}")
        revision = apply_recipe(slot, live[slot], live, steps, base_revision=base_revision, issued_at=issued_at,
                                machine=machine, persona_instance_id=persona_instance_id)
        self._commit(project_id, record, issued_at=issued_at)
        return revision

    def set_category(self, project_id: str, name: str, *, slot: Any, subpath: Any, shared: Any,
                     issued_at: str, context_files: Any = None) -> dict[str, Any]:
        """Declare one category's folder and its share switch (``workspace_categories.apply_category``)."""

        valid_project_id(project_id)
        require_project_publish_rights(project_id, self._credentials)
        record = load_project(project_id)
        held = apply_category(record, name, slot=slot, subpath=subpath, shared=shared, issued_at=issued_at,
                              context_files=context_files, owner=project_id)
        self._commit(project_id, record, issued_at=None)
        if name == "chats" and held.get("shared") and not shared:
            from .project_chat_export import ChatHome
            from .project_chat_fold import drop_chats

            # Unsharing the chats drops the shared store and nothing else (plan §6).
            drop_chats(ChatHome.project(project_id), reason="chats_unshared")
        return {"project_id": project_id, "category": name, "record": record["categories"][name]}

    def set_guidance(self, project_id: str, *, description: Any, instructions: Any, issued_at: str) -> dict[str, Any]:
        """The Project's description + instructions; refused ``guidance_not_shared`` while the switch is off."""

        valid_project_id(project_id)
        require_project_publish_rights(project_id, self._credentials)
        record = load_project(project_id)
        guidance = apply_guidance(record, description=description, instructions=instructions, issued_at=issued_at)
        self._commit(project_id, record, issued_at=None)
        return {"project_id": project_id, "guidance": guidance}


    def adopt_workspace_document(self, project_id: str, *, name: str, document: dict[str, Any],
                                 migrated_from: dict[str, Any] | None = None) -> dict[str, Any]:
        """The slot migration's write (plan §4 step 1): ``document``'s slots VERBATIM (tombstones included)
        and its machine reports into ``project_id``, set-to-value so a retried migration writes the same
        bytes. This machine's own write — no realm right is asked; the record syncs under it afterwards.
        ``migrated_from`` (:func:`migration_origin`) records the workspace the slots came from."""

        import copy

        record = load_project(valid_project_id(project_id))
        if valid_migration_origin(migrated_from) is not None:
            record["migrated_from"] = valid_migration_origin(migrated_from)
        record.update({"project_id": project_id, "name": record.get("name") or _project_name(name[:NAME_MAX_CHARS]),
                       "slots": copy.deepcopy(document.get("slots") or {}),
                       "machines": copy.deepcopy(document.get("machines") or {}),
                       "issued_at": document.get("issued_at") or record.get("issued_at") or ""})
        record.setdefault("categories", {})
        self._commit(project_id, record, issued_at=None)
        return record


    def rename_legacy_migrated(self, project_id: str, *, legacy_name: str, name: str,
                               migrated_from: dict[str, Any]) -> bool:
        """A Project the slot migration made before RT-MIGRATED-PROJECT-NAME: still named ``legacy_name``
        (``"<workspace> slots"``) takes ``name`` and its ``migrated_from``. A name anyone changed since
        is theirs and stays; True when the record was rewritten. Like the migration, this machine's
        own set-to-value write (every machine of the realm runs it, so the copies converge)."""

        if not paths.project_path(valid_project_id(project_id)).is_file():
            return False  # nothing to rename; never write an empty record into being
        record = load_project(project_id)
        if record.get("name") != legacy_name and record.get("migrated_from") is not None:
            return False
        if record.get("name") == legacy_name:
            record["name"] = _project_name(name[:NAME_MAX_CHARS])
        if record.get("migrated_from") is None and valid_migration_origin(migrated_from) is not None:
            record["migrated_from"] = valid_migration_origin(migrated_from)
        self._commit(project_id, record, issued_at=None)
        return True


def migration_origin(workspace: Any) -> dict[str, str]:
    """``migrated_from`` for a Project the slot migration makes from ``workspace``: its id and its name then."""

    return {"workspace_id": str(workspace.id), "workspace_name": str(workspace.name or "")[:NAME_MAX_CHARS]}


def valid_migration_origin(value: Any) -> dict[str, str] | None:
    """``value`` as a ``migrated_from`` record (a safe-token ``workspace_id`` and a short name), or None."""

    if not isinstance(value, dict):
        return None
    workspace_id, workspace_name = value.get("workspace_id"), value.get("workspace_name")
    if (not isinstance(workspace_id, str) or not workspace_id or paths.safe_path_token(workspace_id) != workspace_id
            or not isinstance(workspace_name, str) or len(workspace_name) > NAME_MAX_CHARS):
        return None
    return {"workspace_id": workspace_id, "workspace_name": workspace_name}


def _project_name(value: Any) -> str:
    if not isinstance(value, str) or len(value) > NAME_MAX_CHARS:
        raise SlotRefused(REASON_INVALID_DECLARATION, f"name is text of at most {NAME_MAX_CHARS} characters")
    return value.strip()


def show(project_id: str) -> dict[str, Any]:
    """The record, the realms it is assigned into, THIS machine's fill per slot (never another's path), and the
    sessions THIS machine shares into it (``shared_chats``)."""

    from .project_chat_export import shared_sessions_of
    from .workspace_slot_env import fill_shape
    from .workspace_slots import bound_path

    record = load_project(valid_project_id(project_id))
    here = {}
    for name in sorted(live_slots(record)):
        path = bound_path(name, project_id=project_id)
        bound_here = bool(path and path.is_dir())
        here[name] = {"bound_here": bound_here, "path": str(path) if path else None,
                      "folder_missing": bool(path) and not bound_here,
                      "fill": fill_shape(None, name, project_id=project_id)}
    return {"document": record, "here": here, "realms": project_realms(project_id),
            "exists": paths.project_path(project_id).is_file(), "shared_chats": shared_sessions_of(project_id)}


def list_projects() -> list[dict[str, Any]]:
    """Every Project this namespace knows — a record under ``store/projects/`` or a live workspace's
    reference — with its name, live slot names and the workspaces it is connected to, by id.

    The agent's way in (``hermes harness project list``, RT-PROJECT-SLOTS-AGENT-VERBS): a workspace's
    slots live on its connected Projects, so a reader that starts from a workspace needs this map.
    A reference with no record yet reads ``exists: false`` and no slots."""

    from .store import WorkspaceStore

    connected: dict[str, list[dict[str, Any]]] = {}
    for ws in WorkspaceStore().list_all(include_archived=False):
        for project_id in ws.project_ids:
            connected.setdefault(project_id, []).append(
                {"workspace_id": ws.id, "name": ws.name, "realm_id": ws.realm_id})
    folder = paths.projects_dir()
    on_disk = {path.stem for path in folder.glob("*.json")} if folder.is_dir() else set()
    rows = []
    for project_id in sorted(on_disk | set(connected)):
        if paths.safe_path_token(project_id) != project_id:
            continue
        record = load_project(project_id)
        rows.append({"project_id": project_id, "name": record.get("name") or "",
                     "migrated_from": record.get("migrated_from"),
                     "exists": paths.project_path(project_id).is_file(), "slots": sorted(live_slots(record)),
                     "workspaces": sorted(connected.get(project_id, []), key=lambda row: row["workspace_id"])})
    return rows


def stamp_order(value: Any) -> float:
    """A record stamp as an epoch for ranking (unusable = 0)."""

    return stamp_epoch(value) or 0.0


def valid_root_name(value: Any) -> bool:
    return isinstance(value, str) and bool(_ROOT_NAME_RE.match(value))


def migrated_next_step(project_id: Any) -> str:
    """A ``slot_migrated`` refusal's detail for a CLI reader: the Project's id FIRST (what the RPC
    detail carries), then its name and the verbs that now read and edit those slots."""

    project_id = str(project_id)
    name = load_project(project_id).get("name") if paths.safe_path_token(project_id) == project_id else ""
    named = f" ({name!r})" if name else ""
    return (f"{project_id} — this workspace's slots moved to Project {project_id}{named}; read them with "
            f"`hermes harness project show {project_id}` and edit them with `hermes harness project declare` / "
            f"`project slot bind|clone|env-set` (`hermes harness project list` shows every Project and its workspaces)")


__all__ = [
    "CATEGORIES",
    "FOLDER_CATEGORIES",
    "GUIDANCE",
    "ProjectStore",
    "category",
    "enforce_share_rule",
    "list_projects",
    "load_project",
    "migrated_next_step",
    "migration_origin",
    "project_realms",
    "project_workspaces",
    "require_project_publish_rights",
    "show",
    "source_controlled",
    "valid_migration_origin",
    "valid_project_id",
    "write_project",
]

