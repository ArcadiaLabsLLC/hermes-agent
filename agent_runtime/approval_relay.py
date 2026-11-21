"""A dispatched turn's pending approval, readable and answerable from the serve (MC-A-HELPERS-APPROVAL-NEVER-REACHES-THE-LEADS-CHAT).

Upstream's gateway approval queue (``tools.approval._gateway_queues``) lives in the memory of the
process running the turn. An operator's own turn runs in the serve, so the Launcher's approval read
(``runtime.operator.conversation.approvals``) sees its requests. A turn an agent dispatched to a
helper runs in a child process (``tools/agent_chat_dispatch/local.py``): its request waited in the
child, the serve listed nothing, and it timed out after a minute unseen (seen 2026-11-20, helper
``personainst_dev_agent_8b319ebf``, events.jsonl 00:04:52Z).

The relay is a file per pending request under the runtime root, written by the process that waits on
it. :func:`publish` is called by the turn's gateway notifier (``session_controls._notify_root``) and
starts a watcher that answers the local queue when an answer file appears, and removes both files when
the wait ends by any path. The serve reads :func:`relayed_approvals` beside its own queue and answers
through :func:`answer_relayed`. A record whose writer is gone is never listed or answered. The local
queue stays the authority: the relay only carries a request to it and a choice back.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

__layer__ = "lanes"
__all__ = ["answer_relayed", "publish", "relayed_approvals"]

logger = logging.getLogger(__name__)

#: How often a waiting process looks for an answer.
ANSWER_POLL_SECONDS = 0.5
_RECORD = ".json"
_ANSWER = ".answer.json"


def _session_dir(session_id: str) -> Path:
    from . import paths

    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return paths.store_root() / "approval_relay" / digest


def _safe_id(request_id: Any) -> str | None:
    text = str(request_id or "")
    return text if text and len(text) <= 64 and text.isalnum() else None


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _writer_alive(record: dict[str, Any]) -> bool:
    from .parent_watch import process_alive, process_create_time

    pid = record.get("owner_pid")
    if not isinstance(pid, int) or not process_alive(pid):
        return False
    started = record.get("owner_started")
    return started is None or process_create_time(pid) == started


def publish(session_id: str, data: dict[str, Any]) -> None:
    """Record one pending request of this process's turn and watch for its answer. Never raises."""

    request_id = _safe_id(data.get("request_id"))
    if not session_id or request_id is None:
        return
    try:
        from .parent_watch import process_create_time

        folder = _session_dir(session_id)
        _write(folder / f"{request_id}{_RECORD}", {
            "schema_version": 1, "session_id": session_id, "request_id": request_id,
            "command": str(data.get("command") or ""), "description": str(data.get("description") or ""),
            "owner_pid": os.getpid(), "owner_started": process_create_time(os.getpid()),
            "created_at": time.time(),
        })
    except Exception:
        logger.warning("approval relay: could not record %s", request_id, exc_info=True)
        return
    threading.Thread(target=_watch, args=(session_id, request_id, folder), daemon=True,
                     name=f"approval-relay-{request_id[:8]}").start()


def _pending_here(session_id: str, request_id: str) -> bool:
    from tools.approval import list_gateway_approvals

    return any(row.get("request_id") == request_id for row in list_gateway_approvals(session_id))


def _watch(session_id: str, request_id: str, folder: Path) -> None:
    """Carry an answer file's choice to the local queue; clean up once the wait has ended."""

    from tools.approval import resolve_gateway_approval

    record, answer = folder / f"{request_id}{_RECORD}", folder / f"{request_id}{_ANSWER}"
    try:
        while _pending_here(session_id, request_id):
            reply = _read(answer)
            if reply is not None:
                resolve_gateway_approval(session_id, str(reply.get("choice") or "deny"), request_id=request_id)
                break
            time.sleep(ANSWER_POLL_SECONDS)
    finally:
        for path in (record, answer):
            try:
                path.unlink()
            except OSError:
                pass


def _records(session_id: str) -> list[dict[str, Any]]:
    folder = _session_dir(session_id)
    try:
        paths = sorted(folder.glob(f"*{_RECORD}"))
    except OSError:
        return []
    rows = []
    for path in paths:
        if path.name.endswith(_ANSWER):
            continue
        record = _read(path)
        if record and record.get("session_id") == session_id and _safe_id(record.get("request_id")):
            rows.append(record)
    return sorted(rows, key=lambda row: float(row.get("created_at") or 0.0))


def relayed_approvals(session_id: str) -> list[dict[str, Any]]:
    """Requests another live process of this runtime is waiting on in this chat, oldest first."""

    return [{"request_id": row["request_id"], "command": row.get("command") or "",
             "description": row.get("description") or ""}
            for row in _records(session_id)
            if row.get("owner_pid") != os.getpid() and _writer_alive(row)]


def answer_relayed(session_id: str, request_id: str, choice: str) -> bool:
    """Hand *choice* to the process waiting on *request_id*; False when no live process waits on it."""

    safe = _safe_id(request_id)
    if safe is None:
        return False
    folder = _session_dir(session_id)
    record = _read(folder / f"{safe}{_RECORD}")
    if (record is None or record.get("session_id") != session_id or record.get("owner_pid") == os.getpid()
            or not _writer_alive(record) or (folder / f"{safe}{_ANSWER}").exists()):
        return False
    _write(folder / f"{safe}{_ANSWER}", {"choice": choice, "answered_at": time.time()})
    return True
