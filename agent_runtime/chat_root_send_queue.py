"""Operator sends accepted while their chat root was busy, run in arrival order.

Owner ruling 2026-10-10: busy is not a reason to refuse. A send whose chat root is
held by another turn is persisted here, answered "queued", and run by the serve's
queued-send runner once the root frees. Contract:
``docs/agent-runtime-harness/planned/busy-root-queue-2026-10-10.md``.

One JSON file per entry under ``<store_root>/chat_root_send_queue/<root>/``, keyed
by the digest of its ``client_message_id``, so a re-presented id converges on the
one entry. Order is the per-root ``seq`` assigned under the root's lock.

It is NOT a turn-outcome authority. The mission-chat journal owns what a turn did;
an entry only says "this message is waiting for its root", and it is deleted once
the turn has run and its settle is recorded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping

from hermes_time import now
from utils import atomic_json_write

from . import paths
from .locks import chat_root_send_queue_lock
from .serde import read_versioned_receipt

__layer__ = "stores"

_SCHEMA_VERSION = 1

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
_VALID_STATES = frozenset({STATE_QUEUED, STATE_RUNNING})

#: Set on the argument namespace of a send the runner executes FROM the queue, so
#: the turn's pre-lease gate lets the head through instead of answering "queued".
QUEUED_RUN_ARG = "queued_send_run"
#: The persisted origin of the send's app-function link (``LauncherLink.origin``),
#: ``None`` when the send had none; the serve's queued-turn stream binds it again.
LINK_ORIGIN_ARG = "launcher_link_origin"

#: Fields of the send's argument namespace that are never persisted: the
#: transport (the queued run is answered through the door's sink, never a
#: stream) and in-process objects.
_TRANSIENT_ARGS = frozenset({"func", "payload_sink", "stream", "json", QUEUED_RUN_ARG})


@dataclass(frozen=True)
class QueuedSend:
    root_session_id: str
    client_message_id: str
    seq: int
    queued_at: str
    args: dict[str, Any]
    state: str = STATE_QUEUED
    attempts: int = 0
    updated_at: str = ""


def persistable_args(args: Any) -> dict[str, Any]:
    """The send's argument namespace as JSON: every public, serializable field."""

    kept: dict[str, Any] = {}
    for name, value in sorted(vars(args).items()):
        if name.startswith("_") or name in _TRANSIENT_ARGS or callable(value):
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        kept[name] = value
    return kept


def enqueue(
    root_session_id: str, client_message_id: str, args: Mapping[str, Any]
) -> tuple[QueuedSend, int, bool]:
    """Persist a send for *root_session_id*. Returns ``(entry, position, replay)``.

    Idempotent on (root, client message id): an entry that already exists is
    returned unchanged with ``replay`` True, so a re-presented message never
    queues a second turn. ``position`` is 1-based among the root's entries.
    """

    root, cmid = _queued_send_key(root_session_id, client_message_id)
    with chat_root_send_queue_lock(root):
        existing = _read_or_none(root, cmid)
        if existing is not None:
            return existing, _position_of(root, cmid), True
        entries = _entries(root)
        stamp = _timestamp()
        entry = QueuedSend(
            root_session_id=root,
            client_message_id=cmid,
            seq=(max((item.seq for item in entries), default=0) + 1),
            queued_at=stamp,
            args=dict(args),
            updated_at=stamp,
        )
        _write(entry)
        return entry, len(entries) + 1, False


def find(root_session_id: str, client_message_id: str) -> QueuedSend | None:
    root, cmid = _queued_send_key(root_session_id, client_message_id)
    return _read_or_none(root, cmid)


def position(root_session_id: str, client_message_id: str) -> int:
    """1-based place of the entry in its root's order, 0 when it is not queued."""

    root, cmid = _queued_send_key(root_session_id, client_message_id)
    return _position_of(root, cmid)


def has_entries(root_session_id: str) -> bool:
    """Whether any send is waiting for (or running on) this root."""

    directory = _root_dir(str(root_session_id or "").strip())
    return directory.is_dir() and any(directory.glob("*.json"))


def head(root_session_id: str) -> QueuedSend | None:
    """The entry that runs next on this root (the lowest ``seq``)."""

    entries = _entries(str(root_session_id or "").strip())
    return entries[0] if entries else None


def roots_with_entries() -> list[str]:
    """Every root with a readable entry, in the order their heads arrived."""

    base = paths.chat_root_send_queue_dir()
    if not base.is_dir():
        return []
    heads: list[QueuedSend] = []
    for directory in sorted(base.iterdir()):
        if not directory.is_dir():
            continue
        entries = _entries_in(directory)
        if entries:
            heads.append(entries[0])
    heads.sort(key=lambda item: (item.queued_at, item.seq))
    return [item.root_session_id for item in heads]


def mark(root_session_id: str, client_message_id: str, *, state: str, attempts: int | None = None) -> QueuedSend | None:
    """Move an entry to *state* (and record *attempts*). ``None`` if it is gone."""

    if state not in _VALID_STATES:
        raise ValueError(f"unknown queued-send state {state!r}")
    root, cmid = _queued_send_key(root_session_id, client_message_id)
    with chat_root_send_queue_lock(root):
        entry = _read_or_none(root, cmid)
        if entry is None:
            return None
        updated = replace(
            entry,
            state=state,
            attempts=entry.attempts if attempts is None else int(attempts),
            updated_at=_timestamp(),
        )
        _write(updated)
        return updated


def remove(root_session_id: str, client_message_id: str) -> bool:
    """Delete an entry whose turn has run. True when a file was removed."""

    root, cmid = _queued_send_key(root_session_id, client_message_id)
    with chat_root_send_queue_lock(root):
        path = _entry_path(root, cmid)
        if not path.is_file():
            return False
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass  # other entries remain
        return True


def _queued_send_key(root_session_id: str, client_message_id: str) -> tuple[str, str]:
    root = str(root_session_id or "").strip()
    cmid = str(client_message_id or "").strip()
    if not root or not cmid:
        raise ValueError("a queued send needs a chat root and a client message id")
    return root, cmid


def _root_dir(root: str) -> Path:
    return paths.chat_root_send_queue_dir() / paths.safe_path_token(root)


def _entry_path(root: str, cmid: str) -> Path:
    digest = hashlib.sha256(cmid.encode("utf-8")).hexdigest()
    return _root_dir(root) / f"{digest}.json"


def _position_of(root: str, cmid: str) -> int:
    for index, entry in enumerate(_entries(root), start=1):
        if entry.client_message_id == cmid:
            return index
    return 0


def _entries(root: str) -> list[QueuedSend]:
    return _entries_in(_root_dir(root)) if root else []


def _entries_in(directory: Path) -> list[QueuedSend]:
    if not directory.is_dir():
        return []
    entries = []
    for path in directory.glob("*.json"):
        try:
            entries.append(_read_file(path))
        except Exception:
            continue  # torn or foreign: never runs, never blocks the rest
    entries.sort(key=lambda item: item.seq)
    return entries


def _read_or_none(root: str, cmid: str) -> QueuedSend | None:
    path = _entry_path(root, cmid)
    if not path.is_file():
        return None
    try:
        return _read_file(path)
    except Exception:
        return None


def _read_file(path: Path) -> QueuedSend:
    raw, state = read_versioned_receipt(
        path, schema_version=_SCHEMA_VERSION, valid_states=_VALID_STATES
    )
    args = raw.get("args")
    if not isinstance(args, dict):
        raise ValueError("queued send has no argument record")
    return QueuedSend(
        root_session_id=str(raw["root_session_id"]),
        client_message_id=str(raw["client_message_id"]),
        seq=int(raw["seq"]),
        queued_at=str(raw.get("queued_at") or ""),
        args=args,
        state=state,
        attempts=int(raw.get("attempts") or 0),
        updated_at=str(raw.get("updated_at") or ""),
    )


def _write(entry: QueuedSend) -> None:
    payload = asdict(entry)
    payload["schema_version"] = _SCHEMA_VERSION
    atomic_json_write(
        _entry_path(entry.root_session_id, entry.client_message_id),
        payload,
        indent=2,
        sort_keys=True,
    )


def _timestamp() -> str:
    return now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
