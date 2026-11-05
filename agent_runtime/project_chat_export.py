"""A chat shared into a workspace travels as append-only turn logs in the workspace's chats folder.

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §5, re-homed on
the workspace (``EterniaLauncher/docs/mission_control/planned/WORKSPACE_ABSORBS_PROJECTS_2026-11-04.md``).
Sharing is the explicit ``runtime.workspace.chat.share`` (:func:`share`), refused unless the workspace's
``chats`` category is shared (hence source-controlled) and the caller holds the publish right of the
workspace's realm. (The module keeps its Project-edition name until RT-WS-ABSORB-CHAT-NAMES-RESIDUE.)

* **File form.** ``<chats folder>/<session>/<machine>.<namespace>.jsonl`` — one append-only file PER CHAT
  PER WRITER, so two machines continuing one chat never write the same file and git never conflicts —
  plus ``<session>/chat.json`` (title, persona instance, first turn stamp, format). A line is one ACTIVE
  message: ``{turn_uid, seq, role, ts, content, tool_name?, tool_calls?, attachments?, parent_turn_uid,
  author, address}``, keyed by ``messages.message_uid``; content and tool calls pass
  ``redaction.scrub_secret_values`` / ``scrub_secret_value_tree``, and an attachment declaration
  (``MEDIA:`` / ``FILE:`` path line) leaves only as its ``media_handles`` handle
  (:func:`shared_attachments`). A line is never rewritten.
* **Cursor.** ``paths.workspace_chat_export_path(workspace, session)``: the last exported message id and uid,
  advanced only after the lines are PUBLISHED, so a failed push re-exports from the old cursor and the
  Work writer's ``request_id`` replay keeps the retry from doubling a line.
* **Publication.** The Work writer's ``chat_turns_appended`` operation in Hermes's own worktree of the
  category's slot (pseudo-workspace ``workspace_chats_<id>``, its own worktree and sparse root, never the
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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ChatHome:
    """Where a shared chat lives: a workspace, through its slot document's ``chats`` category.

    Every store, cursor and fold path, the content record, the slot fill and the publish decision are
    the workspace's. A bare string is a workspace id (:func:`home_of`).
    """

    id: str

    @classmethod
    def workspace(cls, workspace_id: str) -> ChatHome:
        from .workspace_slots import REASON_INVALID_DECLARATION

        if not isinstance(workspace_id, str) or not workspace_id:
            raise _refused(REASON_INVALID_DECLARATION, "workspace_id")
        return cls(workspace_id)

    def tag(self) -> dict[str, str]:
        return {"workspace_id": self.id}

    def record(self) -> dict[str, Any]:
        """The content record: the workspace slot document."""

        from .workspace_slots import load_document

        return load_document(self.id)

    def bound(self, slot: str) -> Path | None:
        """This machine's fill of one of the workspace's slots."""

        from .workspace_slots import bound_path

        return bound_path(slot, workspace_id=self.id)

    def exports_dir(self) -> Path:
        return paths.workspace_chat_exports_dir() / paths.safe_path_token(self.id)

    def export_path(self, session_id: str) -> Path:
        return paths.workspace_chat_export_path(self.id, session_id)

    def fold_path(self) -> Path:
        return paths.workspace_chat_fold_path(self.id)

    def writer_workspace(self) -> str:
        """The Work writer's pseudo-workspace: its own worktree and sparse root, never a board's."""

        return f"workspace_chats_{paths.safe_path_token(self.id)}"

    def require_publish(self, credentials: dict[str, Any] | None) -> None:
        """The realm PUBLISH decision of the workspace's realm (``credentials`` keyed by realm id)."""

        from .store import WorkspaceStore
        from .workspace_slots import require_publish_right

        realm_id = WorkspaceStore().get(self.id).realm_id
        require_publish_right(self.id, (credentials or {}).get(realm_id) if realm_id else None)


def home_of(home: ChatHome | str) -> ChatHome:
    """``home`` as a :class:`ChatHome`; a bare string is a workspace id."""

    return home if isinstance(home, ChatHome) else ChatHome.workspace(home)


def load_cursor(home: ChatHome | str, session_id: str) -> dict[str, Any] | None:
    return _shared_record(home_of(home).export_path(session_id))


def _write_cursor(home: ChatHome, session_id: str, record: dict[str, Any]) -> None:
    target = home.export_path(session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, record, indent=2, sort_keys=True)


def shared_homes_of(session_id: str) -> list[ChatHome]:
    """Every workspace this machine exports ``session_id`` into (a cursor with ``shared: true``)."""

    root = paths.workspace_chat_exports_dir()
    name = f"{paths.safe_path_token(session_id)}.json"
    return [ChatHome(path.parent.name) for path in sorted(root.glob(f"*/{name}"))
            if _shared_record(path) is not None] if root.is_dir() else []


def shared_sessions_of(home: ChatHome | str) -> list[str]:
    """The sessions this machine exports into a workspace — ``slots.show``'s ``shared_chats``.

    Read from the record's own ``session_id`` (the file name is a lossy path token), so the launcher's
    shared badge and "Stop sharing" survive a relaunch.
    """

    folder = home_of(home).exports_dir()
    if not folder.is_dir():
        return []
    sessions = (str(record["session_id"]) for record in map(_shared_record, folder.glob("*.json"))
                if record is not None and record.get("session_id"))
    return sorted(set(sessions))


def _shared_record(path: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("shared") else None


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


def chats_writer(home: ChatHome | str) -> tuple[Any, str]:
    """``(Writer, path of the chats folder relative to the writer's root)`` or a typed refusal."""

    from .work_store.board import Board
    from .work_store.writer import Writer
    from .workspace_categories import category, source_controlled
    from .workspace_slots import live_slots, machine_id

    home = home_of(home)
    record = home.record()
    held = category(record, CHATS)
    if not held.get("shared") or not source_controlled(record, held.get("slot")):
        raise _refused(REASON_CATEGORY_NOT_SHARED, f"{home.id} does not share its chats")
    slot = held["slot"]
    checkout = home.bound(slot)
    if checkout is None or not (checkout / ".git").exists():
        raise _refused(REASON_CHATS_FOLDER_UNBOUND, f"{home.id}/{slot} is not bound here")
    repo = live_slots(record)[slot].get("repo") or {}
    board = Board(workspace_id=home.writer_workspace(), slot=slot, read_root=None,
                  brain_dir=str(held["subpath"]), default_branch=str(repo.get("default_branch") or "main"),
                  clone_url=repo.get("clone_url"), local=False, bound_here=True, is_default=False,
                  checkout=checkout)
    writer = Writer(board, machine_id=machine_id())
    return writer, PurePosixPath(str(held["subpath"])).relative_to(writer.brain_root).as_posix()


def _publish_chat_turns(home: ChatHome, session_id: str, request_id: str, payload: dict[str, Any]) -> Any:
    from .work_store.grammar import Op, RowRef
    from .work_store.writer import RowOp

    writer, folder = chats_writer(home)
    rooted = {key: {f"{folder}/{rel}" if folder != "." else rel: body for rel, body in value.items()}
              for key, value in payload.items() if key in ("appends", "files")}
    if payload.get("remove"):
        rooted["remove"] = [f"{folder}/{rel}" if folder != "." else rel for rel in payload["remove"]]
    op = RowOp(RowRef(writer.board.slot, writer.board.brain_dir or "", session_id), Op.CHAT_TURNS_APPENDED,
               WRITER_WHO, request_id, rooted)
    return writer.apply(op)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def export_session(home: ChatHome | str, session_id: str, session_db: Any, *,
                   persona_instance_id: str | None = None) -> dict[str, Any]:
    """Append this chat's new active messages to this writer's file and publish them; the counts."""

    from .work_store import receipts

    home = home_of(home)
    cursor = load_cursor(home, session_id)
    if cursor is None:
        return {**home.tag(), "session_id": session_id, "exported": 0, "shared": False}
    lines, following = pending_lines(session_db, session_id, cursor, persona_instance_id=persona_instance_id)
    if not lines:
        return {**home.tag(), "session_id": session_id, "exported": 0, "shared": True}
    body = "".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines)
    payload: dict[str, Any] = {"appends": {f"{paths.safe_path_token(session_id)}/{writer_file_name()}": body}}
    if not cursor.get("chat_written"):
        session = session_db.get_session(session_id) or {}
        payload["files"] = {f"{paths.safe_path_token(session_id)}/chat.json": json.dumps({
            "format": EXPORT_FORMAT, "session_id": session_id, "title": session.get("title"),
            "persona_instance_id": lines[0]["author"].get("persona_instance_id"),
            "mission_chat_root_id": session_id, "first_turn_at": lines[0]["ts"]}, indent=2, sort_keys=True) + "\n"}
    receipt = _publish_chat_turns(home, session_id, f"chat.{paths.safe_path_token(session_id)}.{lines[-1]['turn_uid']}",
                                  payload)
    _write_cursor(home, session_id, {**following, "chat_written": True, "updated_at": _now()})
    receipts.emit("project_chat.exported", **home.tag(), session_id=session_id, lines=len(lines),
                  commit=receipt.commit, pushed=receipt.pushed)
    return {**home.tag(), "session_id": session_id, "exported": len(lines), "shared": True,
            "commit": receipt.commit, "pushed": receipt.pushed}


def share(home: ChatHome | str, session_id: str, shared: Any, *, session_db: Any,
          credentials: dict[str, Any] | None = None) -> dict[str, Any]:
    """``runtime.workspace.chat.share``: start (and backfill) or stop exporting one chat into a workspace."""

    from .workspace_slots import REASON_INVALID_DECLARATION

    home = home_of(home)
    if not isinstance(session_id, str) or not session_id or not isinstance(shared, bool):
        raise _refused(REASON_INVALID_DECLARATION, "session_id and shared are required")
    home.require_publish(credentials)
    if not shared:
        return _unshare(home, session_id)
    chats_writer(home)  # refuses before anything is recorded when the chats folder cannot publish
    if session_db is None or not session_db.get_session(session_id):
        raise _refused(REASON_SESSION_NOT_FOUND, session_id)
    if load_cursor(home, session_id) is None:
        _write_cursor(home, session_id, {**home.tag(), "session_id": session_id, "shared": True,
                                         "last_id": 0, "seq": 0, "shared_at": _now()})
    return export_session(home, session_id, session_db)


def _unshare(home: ChatHome, session_id: str) -> dict[str, Any]:
    from .work_store import receipts

    receipt = None
    if load_cursor(home, session_id) is not None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        receipt = _publish_chat_turns(home, session_id, f"chat.{paths.safe_path_token(session_id)}.unshare.{stamp}",
                                      {"remove": [paths.safe_path_token(session_id)]})
    home.export_path(session_id).unlink(missing_ok=True)
    receipts.emit("project_chat.unshared", **home.tag(), session_id=session_id,
                  commit=receipt.commit if receipt else None)
    return {**home.tag(), "session_id": session_id, "shared": False,
            "commit": receipt.commit if receipt else None,
            "note": "git history and copies other machines already pulled remain"}


def export_after_turn(session_db: Any, session_id: str | None, *, persona_instance_id: str | None = None,
                      background: bool = True) -> threading.Thread | None:
    """The turn-end hook: export ``session_id`` into every home it is shared into, off the turn thread."""

    homes = shared_homes_of(session_id) if session_id else []
    if not homes:
        return None

    def run() -> None:
        from .work_store import receipts

        from .project_chat_fold import fold_from_remote

        for home in homes:
            try:
                export_session(home, str(session_id), session_db, persona_instance_id=persona_instance_id)
                fold_from_remote(home)  # the store carries this machine's turns and every peer's pushed ones
            except Exception as exc:  # a failed export retries from its cursor on the next turn end
                receipts.emit("project_chat.export_failed", **home.tag(), session_id=session_id,
                              error=type(exc).__name__, reason=getattr(exc, "reason", None))

    if not background:
        run()
        return None
    thread = threading.Thread(target=run, name="project-chat-export", daemon=True)
    thread.start()
    return thread


def cursor_path(home: ChatHome | str, session_id: str) -> Path:
    return home_of(home).export_path(session_id)
