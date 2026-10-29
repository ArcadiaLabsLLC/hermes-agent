"""A chat shared into a Project travels as append-only turn logs in the Project's chats folder (H-P5).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §5. Linking a
chat to a Project in the launcher is organisation and shares nothing; sharing is the explicit
``runtime.project.chat.share`` (:func:`share`), refused unless the Project's ``chats`` category is
shared (hence source-controlled) and the caller holds the publish right of every realm the Project is
assigned into.

* **File form.** ``<chats folder>/<session>/<machine>.<namespace>.jsonl`` — one append-only file PER CHAT
  PER WRITER, so two machines continuing one chat never write the same file and git never conflicts —
  plus ``<session>/chat.json`` (title, persona instance, first turn stamp, format). A line is one ACTIVE
  message: ``{turn_uid, seq, role, ts, content, tool_name?, tool_calls?, attachments?, parent_turn_uid,
  author, address}``, keyed by ``messages.message_uid``; content and tool calls pass
  ``redaction.scrub_secret_values`` / ``scrub_secret_value_tree``, and an attachment declaration
  (``MEDIA:`` / ``FILE:`` path line) leaves only as its ``media_handles`` handle
  (:func:`shared_attachments`). A line is never rewritten.
* **Cursor.** ``paths.project_chat_export_path(project, session)``: the last exported message id and uid,
  advanced only after the lines are PUBLISHED, so a failed push re-exports from the old cursor and the
  Work writer's ``request_id`` replay keeps the retry from doubling a line.
* **Publication.** The Work writer's ``chat_turns_appended`` operation in Hermes's own worktree of the
  category's slot (pseudo-workspace ``project_<id>``, its own worktree and sparse root, never the
  operator's checkout), pushed fast-forward with replay: the files are machine-written logs, so they
  publish without an operator commit.
* **When.** On every turn end of a shared session (:func:`export_after_turn`, from the turn's commit
  lane, off the turn thread) and from the first turn when a share is enabled (backfill).
* **Unshare** stops the export and removes ``<session>/`` in one writer commit; git history and copies
  already pulled remain, and the receipt says so.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from utils import atomic_json_write

from . import paths

__layer__ = "stores"

EXPORT_FORMAT = 1
CHATS = "chats"
WRITER_WHO = "hermes"

REASON_CATEGORY_NOT_SHARED = "category_not_shared"
REASON_CHATS_FOLDER_UNBOUND = "chats_folder_unbound"
REASON_SESSION_NOT_FOUND = "session_not_found"


def _refused(reason: str, detail: str = ""):
    from .workspace_slots import SlotRefused

    return SlotRefused(reason, detail)


def load_cursor(project_id: str, session_id: str) -> dict[str, Any] | None:
    try:
        record = json.loads(paths.project_chat_export_path(project_id, session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("shared") else None


def _write_cursor(project_id: str, session_id: str, record: dict[str, Any]) -> None:
    target = paths.project_chat_export_path(project_id, session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, record, indent=2, sort_keys=True)


def shared_projects_of(session_id: str) -> list[str]:
    """The Projects this machine exports ``session_id`` into (a cursor with ``shared: true``)."""

    root = paths.store_root() / "project_chat_exports"
    name = f"{paths.safe_path_token(session_id)}.json"
    return sorted(path.parent.name for path in root.glob(f"*/{name}")) if root.is_dir() else []


def writer_file_name() -> str:
    """``<machine>.<namespace>.jsonl``: this writer's one file per chat."""

    from .workspace_slots import machine_id, report_namespace

    return f"{paths.safe_path_token(machine_id())}.{paths.safe_path_token(report_namespace())}.jsonl"


# ── the lines ────────────────────────────────────────────────────────────────


def _tip(session_db: Any, session_id: str) -> str:
    try:
        return str(session_db.get_compression_tip(session_id) or session_id)
    except Exception:  # an older store with no lineage answers the session itself
        return session_id


def _author(session_db: Any, session_id: str, persona_instance_id: str | None) -> dict[str, Any]:
    from .workspace_slots import machine_id, report_namespace

    config: Any = {}
    if persona_instance_id is None:
        session = session_db.get_session(session_id) or {}
        config = session.get("model_config") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                config = {}
    return {"persona_instance_id": persona_instance_id or (config or {}).get("persona_instance_id"),
            "profile_id": (config or {}).get("profile_id"), "machine_id": machine_id(),
            "namespace": report_namespace()}


def _address(author: dict[str, Any], session_id: str) -> str | None:
    from .address import Address, AddressError, Kind

    try:
        chain = Address.of((Kind.MACHINE, author["machine_id"]), (Kind.NAMESPACE, author["namespace"]))
        if author.get("persona_instance_id"):
            chain = chain.child(Kind.PERSONA_INSTANCE, author["persona_instance_id"]).child(Kind.CHAT, session_id)
        return str(chain)
    except (AddressError, KeyError):
        return None


#: A shared line names an attachment by its content handle only (plan §5): the declaration line
#: (``MEDIA:<path>`` / ``FILE:<path>``, ``media_handles.parse_media_declaration``) is replaced by
#: ``ATTACHMENT:<sha256 handle>``, a prefix no declaration parser admits, so no path leaves the machine.
ATTACHMENT_PREFIX = "ATTACHMENT:"
#: The marker for a declared attachment this machine cannot back (the file is gone): typed, pathless.
ATTACHMENT_UNAVAILABLE = "ATTACHMENT:unavailable"


def shared_attachments(content: Any) -> tuple[str, list[dict[str, Any]]]:
    """``(content with every attachment declaration replaced by its handle marker, attachments)``.

    ``attachments`` is ``[{handle, media_type, size_bytes}]`` in declaration order, or
    ``{handle: None, status: "unavailable"}`` for one this disk cannot back. Prose that only mentions
    ``MEDIA:`` (not absolute, not an admitted file) is not a declaration and passes unchanged.
    """

    from .media_handles import mint_reply_media, parse_media_declaration

    text = content if isinstance(content, str) else str(content)
    out_lines: list[str] = []
    attachments: list[dict[str, Any]] = []
    for line in text.split("\n"):
        reference = parse_media_declaration(line)
        if reference is None:
            out_lines.append(line)
            continue
        minted = mint_reply_media(line, max_artifacts=1)
        if minted:
            row = minted[0]
            attachments.append({"handle": row["handle"], "media_type": row["media_type"],
                                "size_bytes": row["size_bytes"]})
            out_lines.append(ATTACHMENT_PREFIX + row["handle"])
        else:
            attachments.append({"handle": None, "status": "unavailable"})
            out_lines.append(ATTACHMENT_UNAVAILABLE)
    return "\n".join(out_lines), attachments


def pending_lines(session_db: Any, session_id: str, cursor: dict[str, Any], *,
                  persona_instance_id: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``(lines, next cursor)``: every active message after the cursor, as turn-log lines."""

    from .redaction import scrub_secret_value_tree, scrub_secret_values

    messages = session_db.get_messages(_tip(session_db, session_id), include_ancestors=True)
    last_id = int(cursor.get("last_id") or 0)
    seen = set(cursor.get("seen_uids") or [])
    author = _author(session_db, session_id, persona_instance_id)
    address = _address(author, session_id)
    seq, parent = int(cursor.get("seq") or 0), cursor.get("last_uid")
    lines = []
    for message in messages:
        uid = message.get("message_uid")
        if not uid or int(message.get("id") or 0) <= last_id or uid in seen:
            continue
        seq += 1
        content, attachments = shared_attachments(message.get("content") or "")
        line = {"turn_uid": uid, "seq": seq, "role": message.get("role"), "ts": message.get("timestamp"),
                "content": scrub_secret_values(content), "parent_turn_uid": parent,
                "author": author, "address": address}
        if attachments:
            line["attachments"] = attachments
        if message.get("tool_name"):
            line["tool_name"] = message["tool_name"]
        if message.get("tool_calls"):
            line["tool_calls"] = scrub_secret_value_tree(message["tool_calls"])
        lines.append(line)
        parent = uid
        last_id = max(last_id, int(message.get("id") or 0))
    following = {**cursor, "last_id": last_id, "last_uid": parent, "seq": seq,
                 "seen_uids": sorted(seen | {line["turn_uid"] for line in lines})}
    return lines, following


# ── publication through the Work writer ──────────────────────────────────────


def chats_writer(project_id: str) -> tuple[Any, str]:
    """``(Writer, path of the chats folder relative to the writer's root)`` or a typed refusal."""

    from .project_store import category, load_project, source_controlled
    from .work_store.board import Board
    from .work_store.writer import Writer
    from .workspace_slots import bound_path, live_slots, machine_id

    record = load_project(project_id)
    held = category(record, CHATS)
    if not held.get("shared") or not source_controlled(record, held.get("slot")):
        raise _refused(REASON_CATEGORY_NOT_SHARED, f"{project_id} does not share its chats")
    slot = held["slot"]
    checkout = bound_path(slot, project_id=project_id)
    if checkout is None or not (checkout / ".git").exists():
        raise _refused(REASON_CHATS_FOLDER_UNBOUND, f"{project_id}/{slot} is not bound here")
    repo = live_slots(record)[slot].get("repo") or {}
    board = Board(workspace_id=f"project_{paths.safe_path_token(project_id)}", slot=slot, read_root=None,
                  brain_dir=str(held["subpath"]), default_branch=str(repo.get("default_branch") or "main"),
                  clone_url=repo.get("clone_url"), local=False, bound_here=True, is_default=False,
                  checkout=checkout, project_id=project_id)
    writer = Writer(board, machine_id=machine_id())
    return writer, PurePosixPath(str(held["subpath"])).relative_to(writer.brain_root).as_posix()


def _publish_chat_turns(project_id: str, session_id: str, request_id: str, payload: dict[str, Any]) -> Any:
    from .work_store.grammar import Op, RowRef
    from .work_store.writer import RowOp

    writer, folder = chats_writer(project_id)
    rooted = {key: {f"{folder}/{rel}" if folder != "." else rel: body for rel, body in value.items()}
              for key, value in payload.items() if key in ("appends", "files")}
    if payload.get("remove"):
        rooted["remove"] = [f"{folder}/{rel}" if folder != "." else rel for rel in payload["remove"]]
    op = RowOp(RowRef(writer.board.slot, writer.board.brain_dir or "", session_id), Op.CHAT_TURNS_APPENDED,
               WRITER_WHO, request_id, rooted)
    return writer.apply(op)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def export_session(project_id: str, session_id: str, session_db: Any, *,
                   persona_instance_id: str | None = None) -> dict[str, Any]:
    """Append this chat's new active messages to this writer's file and publish them; the counts."""

    from .work_store import receipts

    cursor = load_cursor(project_id, session_id)
    if cursor is None:
        return {"project_id": project_id, "session_id": session_id, "exported": 0, "shared": False}
    lines, following = pending_lines(session_db, session_id, cursor, persona_instance_id=persona_instance_id)
    if not lines:
        return {"project_id": project_id, "session_id": session_id, "exported": 0, "shared": True}
    body = "".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines)
    payload: dict[str, Any] = {"appends": {f"{paths.safe_path_token(session_id)}/{writer_file_name()}": body}}
    if not cursor.get("chat_written"):
        session = session_db.get_session(session_id) or {}
        payload["files"] = {f"{paths.safe_path_token(session_id)}/chat.json": json.dumps({
            "format": EXPORT_FORMAT, "session_id": session_id, "title": session.get("title"),
            "persona_instance_id": lines[0]["author"].get("persona_instance_id"),
            "mission_chat_root_id": session_id, "first_turn_at": lines[0]["ts"]}, indent=2, sort_keys=True) + "\n"}
    receipt = _publish_chat_turns(project_id, session_id, f"chat.{paths.safe_path_token(session_id)}.{lines[-1]['turn_uid']}",
                       payload)
    _write_cursor(project_id, session_id, {**following, "chat_written": True, "updated_at": _now()})
    receipts.emit("project_chat.exported", project_id=project_id, session_id=session_id, lines=len(lines),
                  commit=receipt.commit, pushed=receipt.pushed)
    return {"project_id": project_id, "session_id": session_id, "exported": len(lines), "shared": True,
            "commit": receipt.commit, "pushed": receipt.pushed}


def share(project_id: str, session_id: str, shared: Any, *, session_db: Any,
          credentials: dict[str, Any] | None = None) -> dict[str, Any]:
    """``runtime.project.chat.share``: start (and backfill) or stop exporting one chat into a Project."""

    from .project_store import require_project_publish_rights, valid_project_id
    from .workspace_slots import REASON_INVALID_DECLARATION

    valid_project_id(project_id)
    if not isinstance(session_id, str) or not session_id or not isinstance(shared, bool):
        raise _refused(REASON_INVALID_DECLARATION, "session_id and shared are required")
    require_project_publish_rights(project_id, credentials)
    if not shared:
        return _unshare(project_id, session_id)
    chats_writer(project_id)  # refuses before anything is recorded when the chats folder cannot publish
    if session_db is None or not session_db.get_session(session_id):
        raise _refused(REASON_SESSION_NOT_FOUND, session_id)
    if load_cursor(project_id, session_id) is None:
        _write_cursor(project_id, session_id, {"project_id": project_id, "session_id": session_id, "shared": True,
                                               "last_id": 0, "seq": 0, "shared_at": _now()})
    return export_session(project_id, session_id, session_db)


def _unshare(project_id: str, session_id: str) -> dict[str, Any]:
    from .work_store import receipts

    receipt = None
    if load_cursor(project_id, session_id) is not None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        receipt = _publish_chat_turns(project_id, session_id, f"chat.{paths.safe_path_token(session_id)}.unshare.{stamp}",
                           {"remove": [paths.safe_path_token(session_id)]})
    paths.project_chat_export_path(project_id, session_id).unlink(missing_ok=True)
    receipts.emit("project_chat.unshared", project_id=project_id, session_id=session_id,
                  commit=receipt.commit if receipt else None)
    return {"project_id": project_id, "session_id": session_id, "shared": False,
            "commit": receipt.commit if receipt else None,
            "note": "git history and copies other machines already pulled remain"}


def export_after_turn(session_db: Any, session_id: str | None, *, persona_instance_id: str | None = None,
                      background: bool = True) -> threading.Thread | None:
    """The turn-end hook: export ``session_id`` into every Project it is shared into, off the turn thread."""

    projects = shared_projects_of(session_id) if session_id else []
    if not projects:
        return None

    def run() -> None:
        from .work_store import receipts

        from .project_chat_fold import fold_from_remote

        for project_id in projects:
            try:
                export_session(project_id, str(session_id), session_db, persona_instance_id=persona_instance_id)
                fold_from_remote(project_id)  # the store carries this machine's turns and every peer's pushed ones
            except Exception as exc:  # a failed export retries from its cursor on the next turn end
                receipts.emit("project_chat.export_failed", project_id=project_id, session_id=session_id,
                              error=type(exc).__name__, reason=getattr(exc, "reason", None))

    if not background:
        run()
        return None
    thread = threading.Thread(target=run, name="project-chat-export", daemon=True)
    thread.start()
    return thread


def cursor_path(project_id: str, session_id: str) -> Path:
    return paths.project_chat_export_path(project_id, session_id)
