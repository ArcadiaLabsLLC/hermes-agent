"""One SHARED chat store per Project per namespace, folded turn by turn from every writer's log (H-P6).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §6. Shared chats
never enter an agent's own ``state.db``: they are folded into ``paths.project_chat_store_path(project)``,
a :class:`ProjectSharedSessionDB` (a ``SessionDB`` at that path — schema, FTS and ``search_messages``
come with it) that is NEVER a chat head: ``chat_session_scope`` cannot resolve to it and
``is_canonical_session_persistence`` answers False for it, so no turn guard, writer or memory pass
treats it as an agent's chat persistence.

* **The fold** (:func:`fold`) reads every ``<session>/<writer>.jsonl`` of the chats folder from the byte
  offset it recorded last time (``paths.project_chat_fold_path``; complete lines only) and inserts each
  line whose ``turn_uid`` the store does not hold yet — idempotent BY TURN, never by session, so a chat
  continued on two machines folds turn by turn in ``(ts, seq)`` order and a re-pull folds nothing twice
  (``import_sessions`` skips a whole session id already present, which is the defect this replaces).
  A UNIQUE index on ``messages.message_uid`` backs the check. A session row is created on its first
  turn with ``source = "project_shared"`` and the author's ``persona_instance_id`` in ``model_config``.
* **The folder** is the chats folder as this machine sees it at the remote tip: Hermes's own worktree
  of the chats slot (``project_chat_export.chats_writer``), synced before a fold — which carries every
  writer's pushed lines, this machine's own included, so the store is complete on every machine.
* **When**: after every local export (the turn-end hook) and on ``runtime.project.chat.fold``.
* **Drop** (:func:`drop_project_chats`): when the chats share turns off, or the last workspace of this
  namespace disconnects the Project, the store, its offsets and the export cursors go — and nothing
  else: the agent's own ``state.db``, the git folder and every other Project's store are untouched.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from hermes_state import SessionDB

from . import paths

__layer__ = "stores"

SHARED_SOURCE = "project_shared"
UNIQUE_UID_INDEX = "project_shared_message_uid_unique"


class ProjectSharedSessionDB(SessionDB):
    """A Project's shared chat store: a ``SessionDB`` that is never canonical chat persistence."""

    __hermes_canonical_session_persistence__ = False


def open_shared_store(project_id: str, *, read_only: bool) -> ProjectSharedSessionDB | None:
    """The Project's shared store; ``None`` for a read of a store that does not exist (a read creates nothing)."""

    target = paths.project_chat_store_path(project_id)
    if read_only and not target.is_file():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    db = ProjectSharedSessionDB(db_path=target, read_only=read_only)
    if not read_only:
        db._execute_write(lambda conn: conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_UID_INDEX} ON messages(message_uid)"))
    return db


def _offsets(project_id: str) -> dict[str, int]:
    try:
        held = json.loads(paths.project_chat_fold_path(project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = held.get("files") if isinstance(held, dict) else None
    return {str(k): int(v) for k, v in (files or {}).items() if isinstance(v, int) and v >= 0}


def _write_offsets(project_id: str, files: dict[str, int]) -> None:
    target = paths.project_chat_fold_path(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, {"project_id": project_id, "files": dict(sorted(files.items()))}, indent=2, sort_keys=True)


def _read_new(path: Path, offset: int) -> tuple[list[dict[str, Any]], int, int]:
    """``(lines, new offset, malformed)`` from ``offset``: complete lines only; a shrunk file re-reads from 0."""

    data = path.read_bytes()
    if len(data) < offset:
        offset = 0  # rewritten under us: refold from the start, idempotent by turn id
    end = data.rfind(b"\n") + 1
    lines, malformed = [], 0
    for raw in data[offset:end].splitlines() if end > offset else []:
        try:
            line = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            malformed += 1
            continue
        if isinstance(line, dict) and isinstance(line.get("turn_uid"), str) and line["turn_uid"]:
            lines.append(line)
        else:
            malformed += 1
    return lines, max(end, offset), malformed


def _held_uids(db: SessionDB, uids: list[str]) -> set[str]:
    def read(conn):
        found: set[str] = set()
        for start in range(0, len(uids), 500):
            chunk = uids[start:start + 500]
            rows = conn.execute(f"SELECT message_uid FROM messages WHERE message_uid IN ({','.join('?' * len(chunk))})",
                                chunk).fetchall()
            found.update(row[0] for row in rows)
        return found

    return db._execute_write(read) if uids else set()


def fold(project_id: str, folder: Path) -> dict[str, Any]:
    """Fold every new line under ``folder`` (``<session>/<writer>.jsonl``) into the shared store; the counts."""

    from .work_store import receipts

    offsets = _offsets(project_id)
    db = open_shared_store(project_id, read_only=False)
    assert db is not None
    inserted, skipped, malformed, sessions = 0, 0, 0, set()
    try:
        for session_dir in sorted(p for p in Path(folder).iterdir() if p.is_dir()) if Path(folder).is_dir() else []:
            pending: list[tuple[float, int, str, dict[str, Any]]] = []
            for log in sorted(session_dir.glob("*.jsonl")):
                rel = f"{session_dir.name}/{log.name}"
                lines, offsets[rel], bad = _read_new(log, offsets.get(rel, 0))
                malformed += bad
                pending.extend((float(line.get("ts") or 0.0), int(line.get("seq") or 0), log.name, line)
                               for line in lines)
            if not pending:
                continue
            pending.sort(key=lambda item: item[:3])
            held = _held_uids(db, [item[3]["turn_uid"] for item in pending])
            session_id = session_dir.name
            for _ts, _seq, _writer, line in pending:
                if line["turn_uid"] in held:
                    skipped += 1
                    continue
                _ensure_session(db, session_id, line)
                try:
                    db.append_message(session_id, str(line.get("role") or "user"), line.get("content"),
                                      tool_name=line.get("tool_name"), tool_calls=line.get("tool_calls"),
                                      timestamp=line.get("ts"), message_uid=line["turn_uid"])
                except sqlite3.IntegrityError:  # the UNIQUE index: a turn another fold already inserted
                    skipped += 1
                    continue
                held.add(line["turn_uid"])
                inserted += 1
                sessions.add(session_id)
    finally:
        db.close()
    _write_offsets(project_id, offsets)
    result = {"project_id": project_id, "inserted": inserted, "skipped": skipped, "malformed": malformed,
              "sessions": sorted(sessions)}
    if inserted or malformed:
        receipts.emit("project_chat.folded", **result)
    return result


def _ensure_session(db: SessionDB, session_id: str, line: dict[str, Any]) -> None:
    if db.get_session(session_id):
        return
    author = line.get("author") if isinstance(line.get("author"), dict) else {}
    db.create_session(session_id, SHARED_SOURCE, model_config={
        "persona_instance_id": author.get("persona_instance_id"), "profile_id": author.get("profile_id"),
        "shared_from_machine": author.get("machine_id")})


def fold_from_remote(project_id: str) -> dict[str, Any]:
    """Sync Hermes's worktree of the chats slot to the remote tip, then fold its chats folder."""

    from .project_chat_export import chats_writer

    writer, folder = chats_writer(project_id)
    root = writer.sync(stale_ok=True)
    return {**fold(project_id, root / writer.brain_root / folder if folder != "." else root / writer.brain_root),
            "stale": writer.stale}


#: How many Projects one realm pull folds (each is a git fetch of the chats slot); the rest wait for the next pull.
FOLD_ON_PULL_LIMIT = 8


def fold_realm_projects(realm_id: str, *, limit: int = FOLD_ON_PULL_LIMIT) -> dict[str, Any]:
    """After a realm pull: fetch-and-fold every Project a workspace of the realm holds whose chats are shared.

    The chats folder travels by git in the chats slot, never in the realm subtree, so without this a
    machine that only READS a shared chat would fold peers' turns only when it exported one of its own
    (row RT-PROJECT-CHAT-FOLD-WITHOUT-SENDING). Bounded to ``limit`` Projects per pull, sorted by id;
    a Project whose chats folder is not bound here, or whose fetch is refused, is accounted and
    skipped — a fold never fails the pull.
    """

    from .project_store import category, load_project
    from .store import WorkspaceStore
    from .work_store.reasons import WorkRefused
    from .workspace_slots import SlotRefused

    held = sorted({project_id for ws in WorkspaceStore().list_all(include_archived=False)
                   if ws.realm_id == realm_id for project_id in ws.project_ids})
    shared = [project_id for project_id in held if category(load_project(project_id), "chats").get("shared")]
    folded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for project_id in shared[:limit]:
        try:
            result = fold_from_remote(project_id)
        except SlotRefused as exc:
            skipped.append({"project_id": project_id, "reason": exc.reason})
            continue
        except (WorkRefused, OSError) as exc:
            skipped.append({"project_id": project_id,
                            "reason": getattr(getattr(exc, "reason", None), "value", type(exc).__name__)})
            continue
        folded.append({"project_id": project_id, "inserted": result.get("inserted", 0),
                       "stale": bool(result.get("stale"))})
    return {"folded": folded, "skipped": skipped, "deferred": shared[limit:]}


def drop_project_chats(project_id: str, *, reason: str) -> dict[str, Any]:
    """Delete the Project's shared store, its fold offsets and its export cursors — and nothing else."""

    from .work_store import receipts

    store = paths.project_chat_store_path(project_id)
    removed = []
    for path in (store, store.with_name(store.name + "-wal"), store.with_name(store.name + "-shm"),
                 paths.project_chat_fold_path(project_id)):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    cursors = paths.store_root() / "project_chat_exports" / paths.safe_path_token(project_id)
    if cursors.is_dir():
        shutil.rmtree(cursors)
        removed.append(cursors.name + "/")
    receipts.emit("project_chat.store_dropped", project_id=project_id, reason=reason, removed=removed)
    return {"project_id": project_id, "removed": removed}
