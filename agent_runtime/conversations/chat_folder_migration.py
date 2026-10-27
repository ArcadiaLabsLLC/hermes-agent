"""Move native routes off the launcher's AppData workspaces into namespace chat folders.

``docs/agent-runtime-harness/archive/chat-folder-in-namespace-2026-10-26.md`` §2.4, the one-shot
``hermes harness conversation chat-folder migrate [--apply] --json``. Dry-run by default; a second
apply finds nothing to do. For each route whose ``cwd`` is a launcher
``eternia_launcher/agents/workspaces/<hash>`` folder:

* the folder is REMOVED when empty, MOVED into the route's chat folder otherwise;
* a route ``migrate_conversation`` has BOUND (its imported root exists and its mint receipt is
  ``bound``) moves into the persona chat's folder and its route row is deleted — the transcript
  lives in the persona chat and the route has nothing left to resume;
* any other route has its ``cwd`` rewritten to ``chat_folders/profile-<profile>/<route_id>``, so a
  resume presents (or omits, ``paths.chat_folder``) the new path;
* a route with unsettled work or a live worker is SKIPPED, never touched.

Never run by a lane against a live namespace; the operator applies it after the launcher stops
passing its AppData folder (launcher row ``MC-CHAT-FOLDER-STOP-APPDATA``).
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .model import ConversationRoute
from .process_evidence import execution_possible
from .store import ConversationStore

__layer__ = "lanes"

#: A launcher-chosen per-chat folder: ``…/eternia_launcher/agents/workspaces/<hash>``, either separator.
LAUNCHER_WORKSPACE = re.compile(r"[\\/]eternia_launcher[\\/]agents[\\/]workspaces[\\/][^\\/]+[\\/]?$", re.IGNORECASE)


class FolderStep(StrEnum):
    REMOVE_EMPTY = "remove_empty"
    MOVE = "move"
    #: The launcher folder is already gone; only the route moves.
    ABSENT = "absent"


class RouteStep(StrEnum):
    REWRITE = "rewrite_cwd"
    DELETE = "delete_bound_route"
    #: Unsettled work or a live worker: nothing is touched.
    SKIP_BUSY = "skip_busy"


@dataclass(frozen=True, slots=True)
class FolderMove:
    route_id: str
    profile: str
    old_cwd: str
    new_cwd: str
    folder: FolderStep
    route: RouteStep

    def row(self) -> dict:
        return {"route_id": self.route_id, "profile": self.profile, "old_cwd": self.old_cwd,
                "new_cwd": self.new_cwd, "folder": self.folder.value, "route": self.route.value}


def is_launcher_workspace(cwd: str) -> bool:
    return bool(LAUNCHER_WORKSPACE.search(str(cwd or "")))


def plan_chat_folder_moves(store: ConversationStore, *, root: Path, bound_root=None) -> list[FolderMove]:
    """Every move the apply would make, in route-id order. Reads only.

    ``bound_root(route)`` answers ``(persona_instance_id, root_session_id)`` for a route
    ``migrate_conversation`` bound, else ``None``; the default reads the migration fence, the mint
    receipts and the chat store.
    """
    from agent_runtime.paths import chat_folder, native_route_chat_folder_owner

    bound_root = bound_root or _bound_persona_root
    busy = {receipt.conversation_id for receipt in store.unsettled()}
    moves = []
    for route in store.routes():
        if not is_launcher_workspace(route.cwd):
            continue
        old = Path(route.cwd)
        folder = FolderStep.ABSENT if not old.is_dir() else (
            FolderStep.MOVE if any(old.iterdir()) else FolderStep.REMOVE_EMPTY)
        # A route that never recorded a worker (pid 0) has none to be live.
        if route.id in busy or (route.worker_pid > 0 and execution_possible(route.worker_pid, route.worker_created)):
            moves.append(FolderMove(route.id, route.profile, route.cwd, route.cwd, folder, RouteStep.SKIP_BUSY))
            continue
        bound = bound_root(store, route)
        if bound is not None:
            target = chat_folder(bound[0], bound[1], root=root)
            step = RouteStep.DELETE
        else:
            target = chat_folder(native_route_chat_folder_owner(route.profile), route.id, root=root)
            step = RouteStep.REWRITE
        moves.append(FolderMove(route.id, route.profile, route.cwd, str(target), folder, step))
    return moves


def apply_chat_folder_move(store: ConversationStore, move: FolderMove) -> None:
    """One move: the folder first, then the route — a crash between leaves a route the next run redoes."""
    if move.route is RouteStep.SKIP_BUSY:
        return
    old, new = Path(move.old_cwd), Path(move.new_cwd)
    if move.folder is FolderStep.MOVE:
        new.parent.mkdir(parents=True, exist_ok=True)
        if new.exists() and not any(new.iterdir()):
            new.rmdir()
        shutil.move(str(old), str(new))
    else:
        if move.folder is FolderStep.REMOVE_EMPTY:
            old.rmdir()
        new.mkdir(parents=True, exist_ok=True)
    if move.route is RouteStep.DELETE:
        store.delete_route(move.route_id)
    else:
        store.rewrite_cwd(move.route_id, old=move.old_cwd, new=str(new.resolve()))


def migrate_chat_folders(*, root: Path, apply: bool) -> dict:
    """The verb's whole answer: ``{"applied", "moves": [...], "counts": {...}}``."""
    store = ConversationStore(root / "native_conversation_routes.db")
    moves = plan_chat_folder_moves(store, root=root)
    if apply:
        for move in moves:
            apply_chat_folder_move(store, move)
    counts: dict[str, int] = {}
    for move in moves:
        counts[move.route.value] = counts.get(move.route.value, 0) + 1
    return {"applied": apply, "moves": [move.row() for move in moves], "counts": counts}


def _bound_persona_root(store: ConversationStore, route: ConversationRoute) -> tuple[str, str] | None:
    """``(instance, root)`` when the route's import exists and its mint receipt is ``bound``."""
    target = store.migration_target(route)
    if target is None:
        return None
    instance_id = target[1]
    from agent_runtime import paths
    from agent_runtime.chat_session_scope import (
        SessionDbAccess,
        open_chat_session_db,
    )
    from agent_runtime.chat_heads import resolve_conversation_chat_scope
    from agent_runtime.store_file_io import read_json_object

    receipts = paths.persona_chat_mint_receipts_dir()
    if not receipts.is_dir():
        return None
    # The receipt's instance names the head its root lives in: a ``per_profile``
    # instance's own store, else the process one (plan §7.2 decision 5).
    db = open_chat_session_db(
        resolve_conversation_chat_scope(persona_instance_id=instance_id), access=SessionDbAccess.READ
    )
    if db is None:
        return None
    try:
        for path in sorted(receipts.glob("*.json")):
            raw = read_json_object(path)
            if raw.get("persona_instance_id") != instance_id or raw.get("state") != "bound":
                continue
            session = db.get_session(str(raw.get("session_id") or ""))
            config = (session or {}).get("model_config") or {}
            config = json.loads(config) if isinstance(config, str) else config
            if isinstance(config, dict) and config.get("legacy_conversation", {}).get("route_id") == route.id:
                return instance_id, str(raw["session_id"])
        return None
    finally:
        db.close()


__all__ = ["FolderMove", "FolderStep", "RouteStep", "apply_chat_folder_move", "is_launcher_workspace",
           "migrate_chat_folders", "plan_chat_folder_moves"]
