"""Every Project folds into one home workspace, once, on the first boot of the new edition (RT-WS-ABSORB-MIGRATION).

Plan ``EterniaLauncher/docs/mission_control/planned/WORKSPACE_ABSORBS_PROJECTS_2026-11-04.md`` §4 step 1.
One plain pass, nothing kept for compatibility (owner 2026-11-04: "we have no users right now so don't do
any rituals just simple migration no weird rituals"): no alias table, no receipt file, no old file left in
place. Run by ``boot_phases._boot_sweeps_and_ready_frame`` on every serve; a namespace with nothing
Project-keyed left is a no-op that writes nothing.

For each Project (a record under ``store/projects/``, or an id a workspace record still lists):

1. **Its home.** The workspace a ``ws-<ws>`` Project came from, else the first workspace (by id) whose
   record lists it, else — for a record no workspace lists — a new workspace in the default realm named
   after the Project. A reference with neither a record nor a listing workspace has no home and is dropped.
2. **Its content** moves into the home's slot document (``store/workspace_slots/<ws>.json``). The
   ``ws-`` Project of its own origin REPLACES the document's frozen slots and reports (they were copied
   from that document). Any other Project's live slot whose name the document already holds live is
   renamed ``<project_slug>_<slot>`` (a slot name is ``[A-Za-z0-9_]+``, so the plan's ``-`` joins with
   ``_``); a category the document already declares keeps the document's; guidance moves only when the
   document has none; each machine report's rows follow the renames.
3. **Every Project-keyed store is rekeyed to the home**: ``machine_roots.json`` ``project_roots`` →
   ``slot_folders``; the env fills' ``projects`` → ``workspaces``; ``slot_worktrees/<project>/`` →
   ``slot_worktrees/<ws>/``; the shared chat store, its fold offsets and export cursors →
   ``workspace_chats`` / ``workspace_chat_fold`` / ``workspace_chat_exports`` (a home that already has
   one keeps its own and the Project's is deleted: the fold rebuilds from the chats folder); instance slot
   keys ``<project>/<slot>`` → the bare (renamed) slot in the home, dropped in any other workspace; Work
   run records and schedules' row refs lose the Project and take the renamed slot. Hermes's own Work
   worktrees keyed ``<project>/<slot>`` and the chats writer's ``project_<id>`` worktrees are removed (and
   pruned on the bound clone); the next write recuts them at the workspace key.
4. **Then the old shapes go**: ``store/projects/``, every workspace record's ``project_ids`` and
   ``project_assignment_revision`` (stripped from the JSON itself), every ``migrated_to`` stamp.

The receipt ``workspace_merge.completed`` lists each Project's home, whether it was created, its renames
and the counts moved.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from . import paths

__layer__ = "stores"

PROJECT_PREFIX = "ws-"
#: The workspace record keys the merge deletes.
RETIRED_WORKSPACE_KEYS = ("project_ids", "project_assignment_revision")


def migrate_namespace() -> dict[str, Any]:
    """Fold every Project of this namespace into its home workspace; the receipt (empty on a no-op)."""

    workspaces = _workspace_records()
    fills = _project_fills()
    projects = _project_ids(workspaces, fills)
    stamped = _stamped_documents()
    retired_keys = any(raw.get("project_ids") or raw.get("project_assignment_revision")
                       for raw in workspaces.values())
    if not projects and not stamped and not retired_keys and not _project_stores_left():
        return {"merged": [], "dropped": [], "stamps_removed": 0}
    merged, dropped = [], []
    # A workspace's own ``ws-`` Project first: it replaces the frozen document the others then merge into.
    for project_id in sorted(projects, key=lambda pid: (not pid.startswith(PROJECT_PREFIX), pid)):
        home, created = _home(project_id, workspaces)
        if home is None:
            _forget(fills, project_id)
            dropped.append(project_id)
            continue
        merged.append({"project_id": project_id, "workspace_id": home, "created": created,
                       **_merge_one(fills, project_id, home, workspaces)})
    for workspace_id in stamped:
        document = _load_document(workspace_id)
        if document.pop("migrated_to", None) is not None:
            _write_document(workspace_id, document)
    _strip_workspace_records(workspaces)
    for leftover in _PROJECT_STORE_DIRS:
        folder = paths.store_root() / leftover
        if folder.is_dir():
            shutil.rmtree(folder)
    receipt = {"merged": merged, "dropped": dropped, "stamps_removed": len(stamped)}
    from .brain_paths import changed
    from .work_store import receipts

    changed("workspace_merge.completed")  # the slot fills moved: the brain path list is recomputed

    receipts.emit("workspace_merge.completed", **receipt)
    return receipt


#: The Project-keyed store directories that go once every Project has moved.
_PROJECT_STORE_DIRS = ("projects", "project_chats", "project_chat_fold", "project_chat_exports")


def _project_stores_left() -> bool:
    return any((paths.store_root() / name).exists() for name in _PROJECT_STORE_DIRS)


# ── what there is ────────────────────────────────────────────────────────────


def _workspace_records() -> dict[str, dict[str, Any]]:
    """Every workspace record's raw JSON, by id (raw, so the retired keys are read whatever the model says)."""

    folder = paths.workspaces_dir()
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        raw = _raw_json(path)
        if isinstance(raw, dict) and isinstance(raw.get("id"), str):
            out[raw["id"]] = raw
    return out


def _project_ids(workspaces: dict[str, dict[str, Any]], fills: dict[str, dict[str, str]]) -> list[str]:
    """Every Project id there is a trace of: a record, a workspace's reference, a path or env fill."""

    from .workspace_slot_env import _read

    folder = paths.store_root() / "projects"
    found = {path.stem for path in folder.glob("*.json")} if folder.is_dir() else set()
    found.update(fills)
    env = _read().get("projects")
    if isinstance(env, dict):
        found.update(str(pid) for pid in env)
    for raw in workspaces.values():
        found.update(pid for pid in raw.get("project_ids") or [] if isinstance(pid, str))
    return sorted(pid for pid in found if pid and paths.safe_path_token(pid) == pid)


def _stamped_documents() -> list[str]:
    folder = paths.workspace_slots_dir()
    out = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        raw = _raw_json(path)
        if isinstance(raw, dict) and raw.get("migrated_to"):
            out.append(str(raw.get("workspace_id") or path.stem))
    return out


def _raw_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _project_record(project_id: str) -> dict[str, Any] | None:
    raw = _raw_json(paths.store_root() / "projects" / f"{paths.safe_path_token(project_id)}.json")
    return raw if isinstance(raw, dict) and isinstance(raw.get("slots"), dict) else None


def _home(project_id: str, workspaces: dict[str, dict[str, Any]]) -> tuple[str | None, bool]:
    """``(home workspace id, created)``: the ``ws-`` origin, else the first listing workspace, else a new one."""

    if project_id.startswith(PROJECT_PREFIX) and project_id[len(PROJECT_PREFIX):] in workspaces:
        return project_id[len(PROJECT_PREFIX):], False
    listing = sorted(ws for ws, raw in workspaces.items() if project_id in (raw.get("project_ids") or []))
    if listing:
        return listing[0], False
    record = _project_record(project_id)
    if record is None:
        return None, False
    from .default_scope import DEFAULT_REALM_ID
    from .errors import NotFound
    from .store import RealmStore, WorkspaceStore

    try:
        realm_id: str | None = RealmStore().get(DEFAULT_REALM_ID).id
    except NotFound:
        realm_id = None
    created = WorkspaceStore().create(name=str(record.get("name") or "").strip() or project_id, realm_id=realm_id)
    workspaces[created.id] = _raw_json(paths.workspace_path(created.id)) or {"id": created.id}
    return created.id, True


# ── one Project into its home ────────────────────────────────────────────────


def _slug(project_id: str, record: dict[str, Any] | None) -> str:
    name = str((record or {}).get("name") or "")
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or re.sub(r"[^A-Za-z0-9]+", "_", project_id).strip("_") or "project"


def _load_document(workspace_id: str) -> dict[str, Any]:
    from .workspace_slots import load_document

    return load_document(workspace_id)


def _write_document(workspace_id: str, document: dict[str, Any]) -> None:
    from .workspace_slots import write_document

    write_document(workspace_id, document)


def _merge_one(fills: dict[str, dict[str, str]], project_id: str, home: str,
               workspaces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = _project_record(project_id)
    rename = _merge_content(project_id, home, record) if record is not None else {}
    holders = sorted(ws for ws, raw in workspaces.items() if project_id in (raw.get("project_ids") or []))
    # The Work worktrees first: pruning them reads the Project's fill, which the move below takes away.
    worktrees = _remove_work_worktrees(fills.get(project_id) or {}, project_id, sorted({home, *holders}), record)
    moved_fills = _move_path_fills(fills, project_id, home, rename)
    env_fills = _move_env_fills(project_id, home, rename)
    worktree_records = _move_worktree_records(project_id, home, rename)
    chats = _move_chats(project_id, home)
    from .persona_slots import rekey_project_assignments

    instances = rekey_project_assignments(project_id, home, rename)
    refs = _rekey_row_refs(project_id, rename)
    return {"renamed": {old: new for old, new in sorted(rename.items()) if old != new},
            "slots": len(rename), "fills": moved_fills, "env_fills": env_fills, "worktree_records": worktree_records,
            "chats": chats, "worktrees_removed": worktrees, "instances": len(instances), "row_refs": refs}


def _merge_content(project_id: str, home: str, record: dict[str, Any]) -> dict[str, str]:
    """Step 2: the Project's slots, categories, guidance and reports into the home's document; the renames."""

    from .workspace_categories import enforce_share_rule
    from .workspace_slots import live_slots

    document = _load_document(home)
    project_slots = live_slots(record)
    rename: dict[str, str] = {}
    if document.get("migrated_to") == project_id:
        # Its own origin: the document's slots were copied into this Project; the Project's are newer.
        document["slots"] = copy.deepcopy(record.get("slots") or {})
        document["machines"] = copy.deepcopy(record.get("machines") or {})
        rename = {name: name for name in project_slots}
    else:
        held = live_slots(document)
        slots = document.setdefault("slots", {})
        slug = _slug(project_id, record)
        for name in sorted(project_slots):
            target = name
            if name in held:
                target, suffix = f"{slug}_{name}", 2
                while target in live_slots(document):
                    target, suffix = f"{slug}_{name}_{suffix}", suffix + 1
            slots[target] = copy.deepcopy(project_slots[name])
            rename[name] = target
        _merge_reports(document, record, rename)
    categories = document.setdefault("categories", {})
    for name, held_category in sorted((record.get("categories") or {}).items()):
        if name in categories or not isinstance(held_category, dict):
            continue  # a category the workspace already declares keeps the workspace's own
        moved = copy.deepcopy(held_category)
        if moved.get("slot") is not None:
            moved["slot"] = rename.get(moved["slot"])
        categories[name] = moved
    if not categories:
        document.pop("categories", None)
    if "guidance" not in document and isinstance(record.get("guidance"), dict):
        document["guidance"] = copy.deepcopy(record["guidance"])
    document.pop("migrated_to", None)
    enforce_share_rule(document)
    document.update({"workspace_id": home, "issued_at": datetime.now(UTC).isoformat()})
    _write_document(home, document)
    return rename


def _merge_reports(document: dict[str, Any], record: dict[str, Any], rename: dict[str, str]) -> None:
    """Each machine's report rows of the Project, under the renamed slot names, beside the workspace's rows."""

    machines = document.setdefault("machines", {})
    for machine, entry in sorted((record.get("machines") or {}).items()):
        if not isinstance(entry, dict):
            continue
        rows = {rename[slot]: copy.deepcopy(row) for slot, row in (entry.get("slots") or {}).items() if slot in rename}
        if not rows:
            continue
        held = machines.get(machine) if isinstance(machines.get(machine), dict) else None
        if held is None:
            machines[machine] = {**copy.deepcopy(entry), "slots": rows}
            continue
        held.setdefault("slots", {}).update(rows)
        held["reported_at"] = max(str(held.get("reported_at") or ""), str(entry.get("reported_at") or ""))


# ── the Project-keyed stores ─────────────────────────────────────────────────


def _project_fills() -> dict[str, dict[str, str]]:
    """The Project edition's ``project_roots`` (``{project: {slot: path}}``), read raw from the registry file."""

    from .machine_roots import machine_roots_registry_paths

    raw = _raw_json(machine_roots_registry_paths()[0])
    held = raw.get("project_roots") if isinstance(raw, dict) else None
    return {str(pid): {str(k): str(v) for k, v in slots.items()} for pid, slots in (held or {}).items()
            if isinstance(slots, dict)} if isinstance(held, dict) else {}


def _move_path_fills(fills: dict[str, dict[str, str]], project_id: str, home: str | None,
                     rename: dict[str, str]) -> int:
    """``project_roots[project]`` → ``slot_folders[home]`` (the Project's fill wins); the slots moved.

    The registry is rewritten through its one write site, which writes no ``project_roots``: the first
    move drops every Project's fill from the file, so ``fills`` is the snapshot read before any move.
    """

    from .machine_roots import load_machine_roots, write_machine_roots

    if project_id not in fills:
        return 0
    moving = fills.pop(project_id) or {}
    current = load_machine_roots(refresh=True)
    scoped = {ws: dict(slots) for ws, slots in current.workspace_roots.items()}
    moved = [slot for slot in moving if slot in rename and home]
    for slot in moved:
        scoped.setdefault(str(home), {})[rename[slot]] = moving[slot]
    write_machine_roots(dict(current.roots), workspace_roots=scoped, dry_run=False)
    return len(moved)


def _move_env_fills(project_id: str, home: str | None, rename: dict[str, str]) -> int:
    """The env fills' ``projects[project]`` → ``workspaces[home]`` (the Project's fill wins)."""

    from .workspace_slot_env import _read, _write

    payload = _read()
    projects = payload.get("projects") if isinstance(payload.get("projects"), dict) else {}
    if project_id not in projects:
        return 0
    moving = projects.pop(project_id) or {}
    moved = 0
    for slot, entry in moving.items():
        if slot in rename and home:
            payload["workspaces"].setdefault(home, {})[rename[slot]] = entry
            moved += 1
    if not projects:
        payload.pop("projects", None)
    _write(payload)
    return moved


def _move_worktree_records(project_id: str, home: str | None, rename: dict[str, str]) -> int:
    """``slot_worktrees/<project>/<slot>.json`` → ``slot_worktrees/<home>/<renamed>.json``."""

    source = paths.store_root() / "slot_worktrees" / paths.safe_path_token(project_id)
    if not source.is_dir():
        return 0
    moved = 0
    for record in sorted(source.glob("*.json")):
        slot = next((name for name in rename if paths.safe_path_token(name) == record.stem), None)
        if slot is None or not home:
            continue
        target = paths.slot_worktrees_path(home, rename[slot])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record, target)
        moved += 1
    shutil.rmtree(source)
    return moved


def _project_chat_paths(project_id: str) -> tuple[Path, Path, Path]:
    """``(store, fold offsets, export cursors dir)`` of a Project, where the Project edition kept them."""

    token = paths.safe_path_token(project_id)
    root = paths.store_root()
    return (root / "project_chats" / f"{token}.db", root / "project_chat_fold" / f"{token}.json",
            root / "project_chat_exports" / token)


def _move_chats(project_id: str, home: str | None) -> dict[str, Any]:
    """The shared store, fold offsets and export cursors → the home's, unless the home has its own."""

    store, fold, cursors = _project_chat_paths(project_id)
    sidecars = [store.with_name(store.name + suffix) for suffix in ("-wal", "-shm")]
    moved_store = False
    if home and store.is_file() and not paths.workspace_chat_store_path(home).exists():
        target = paths.workspace_chat_store_path(home)
        target.parent.mkdir(parents=True, exist_ok=True)
        for source in (store, *sidecars):
            if source.is_file():
                source.replace(target.with_name(target.name + source.name[len(store.name):]))
        moved_store = True
        held = _raw_json(fold)
        files = held.get("files") if isinstance(held, dict) else None
        destination = paths.workspace_chat_fold_path(home)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(destination, {"workspace_id": home, "files": files or {}}, indent=2, sort_keys=True)
    for source in (store, *sidecars, fold):
        source.unlink(missing_ok=True)
    moved_cursors = 0
    for cursor in sorted(cursors.glob("*.json")) if cursors.is_dir() and home else []:
        destination = paths.workspace_chat_exports_dir() / paths.safe_path_token(home) / cursor.name
        held = _raw_json(cursor)
        if destination.exists() or not isinstance(held, dict):
            continue
        held.pop("project_id", None)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(destination, {**held, "workspace_id": home}, indent=2, sort_keys=True)
        moved_cursors += 1
    if cursors.is_dir():
        shutil.rmtree(cursors)
    return {"store": moved_store, "cursors": moved_cursors}


def _remove_work_worktrees(fills: dict[str, str], project_id: str, workspaces: list[str],
                           record: dict[str, Any] | None) -> int:
    """Hermes's Work worktrees keyed ``<project>/<slot>``, and the chats writer's ``project_<id>`` ones."""

    from .work_store.writer import remove_worktree

    def clone(slot: str) -> Path | None:
        return Path(fills[slot]) if fills.get(slot) else None

    removed = 0
    for workspace_id in workspaces:
        parent = paths.work_worktrees_dir(workspace_id)
        for name in sorted((record or {}).get("slots") or {}):
            prefix = paths.safe_path_token(f"{project_id}/{name}") + "-"
            for worktree in sorted(parent.glob(f"{prefix}*")) if parent.is_dir() else []:
                remove_worktree(worktree, repo=clone(name))
                removed += 1
    pseudo = f"project_{paths.safe_path_token(project_id)}"
    for worktree in sorted(paths.work_worktrees_dir(pseudo).glob("*")) if paths.work_worktrees_dir(pseudo).is_dir() else []:
        remove_worktree(worktree, repo=clone(worktree.name.rsplit("-", 1)[0]))
        removed += 1
    if paths.work_workspace_dir(pseudo).is_dir():
        shutil.rmtree(paths.work_workspace_dir(pseudo))
    return removed


def _rekey_row_refs(project_id: str, rename: dict[str, str]) -> int:
    """Work run records and schedules: a ref owned by the Project names the home's (renamed) slot instead."""

    changed = 0
    for path in sorted(paths.work_dir().glob("*/runs/*.json")):
        raw = _raw_json(path)
        ref = raw.get("ref") if isinstance(raw, dict) else None
        if not isinstance(ref, dict) or ref.get("project_id") != project_id:
            continue
        ref.pop("project_id", None)
        ref["slot"] = rename.get(ref.get("slot"), ref.get("slot"))
        atomic_json_write(path, raw, indent=2, sort_keys=True)
        changed += 1
    schedules = paths.schedules_dir()
    for path in sorted(schedules.glob("*.json")) if schedules.is_dir() else []:
        rewritten, count = _rekeyed_lists(_raw_json(path), project_id, rename)
        if count:
            atomic_json_write(path, rewritten, indent=2, sort_keys=True)
            changed += count
    return changed


def _rekeyed_lists(node: Any, project_id: str, rename: dict[str, str]) -> tuple[Any, int]:
    """Every ``[slot, note, id, project]`` list form of a ref owned by the Project, as ``[slot', note, id]``."""

    if isinstance(node, dict):
        count, out = 0, {}
        for key, value in node.items():
            out[key], found = _rekeyed_lists(value, project_id, rename)
            count += found
        return out, count
    if isinstance(node, list):
        if len(node) == 4 and all(isinstance(part, str) for part in node) and node[3] == project_id:
            return [rename.get(node[0], node[0]), node[1], node[2]], 1
        items = [_rekeyed_lists(value, project_id, rename) for value in node]
        return [item for item, _ in items], sum(found for _, found in items)
    return node, 0


def _forget(fills: dict[str, dict[str, str]], project_id: str) -> None:
    """A reference with no home: its fills, stores and assignment keys go with it."""

    _remove_work_worktrees(fills.get(project_id) or {}, project_id, [], None)
    _move_path_fills(fills, project_id, None, {})
    _move_env_fills(project_id, None, {})
    _move_worktree_records(project_id, None, {})
    _move_chats(project_id, None)
    from .persona_slots import rekey_project_assignments

    rekey_project_assignments(project_id, None, {})


def _strip_workspace_records(workspaces: dict[str, dict[str, Any]]) -> None:
    """``project_ids`` and ``project_assignment_revision`` leave every workspace record's JSON."""

    for workspace_id in workspaces:
        path = paths.workspace_path(workspace_id)
        raw = _raw_json(path)
        if isinstance(raw, dict) and any(key in raw for key in RETIRED_WORKSPACE_KEYS):
            for key in RETIRED_WORKSPACE_KEYS:
                raw.pop(key, None)
            atomic_json_write(path, raw, indent=2, sort_keys=True)
