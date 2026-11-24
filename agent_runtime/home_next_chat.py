"""Home's one ready next chat (owner 2026-11-23, row RT-FU-THE-FIRST-MESSAGE-IN-A-NEW-CHAT-STARTS-WITHOUT-A-THREE-SECOND-WAIT).

Eternia's Home starts a NEW chat on every first message, and that chat's agent setup (the
prewarm the open queues) ran beside the send: on the owner's serve 2026-11-23 21:43 the first
message waited 7.6 s for it. Home now keeps ONE ready chat per account (``client_scope``): an
empty chat for Home's selected agent, minted and prewarmed when the agent is set, hidden from
every list until it has a message.

* :func:`ensure_ready_chat` (``runtime.home.next_chat.ensure``) assigns it: mints it through the
  open-chat seam (``perform_persona_instance_open_chat``, ``new_session``, unselected; that seam
  queues the prewarm), hides it with the session store's own ``hidden`` flag (every list reads
  ``hidden=0``), and re-queues the prewarm. The same agent again is a no-op; another instance of the
  same agent MOVES the same chat (the open-chat ``move`` seam); another agent retires the old one
  (deleted only while empty, ``SessionDB.delete_session_if_empty``) and mints the new agent's,
  because a chat root belongs to its agent instance. One ready chat per account at any time.
* :func:`ready_chat` (``runtime.home.next_chat.get``) reads it, so a relaunched Eternia adopts it.
* :func:`promote_on_send` runs at the send's anchor: the first message shows the chat and Home
  forgets it (Eternia calls ensure again for the next one).
* :func:`rewarm_if_ready` runs after a model pick on it (``conversation.model.select``): the
  prewarm is re-queued so the built agent is the one the pick will run.

The record is one small JSON file per account under the runtime store: ``session_id``,
``persona_id``, ``persona_instance_id``. Ids only.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

__layer__ = "lanes"

logger = logging.getLogger(__name__)

READY_DIR = "home_next_chat"
#: One INFO line per assign / re-point / promote / retire. Ids and outcomes only.
READY_CHAT_RECEIPT = "home_next_chat op=%s scope=%s session=%s persona=%s instance=%s outcome=%s"
_SCOPE = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.RLock()


class HomeNextChatRefused(ValueError):
    """A typed refusal; ``str(exc)`` is the reason."""


def _text(params: dict, key: str) -> str | None:
    value = params.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _scope(params: dict) -> str:
    scope = _text(params, "client_scope")
    if scope is None or not _SCOPE.match(scope):
        raise HomeNextChatRefused("client_scope_required")
    return scope


def _record_path(scope: str) -> Path:
    from agent_runtime import paths

    return Path(paths.store_root()) / READY_DIR / f"{scope}.json"


def _read_record(scope: str) -> dict | None:
    from agent_runtime.serde import read_json_dict

    record = read_json_dict(_record_path(scope))
    return record if isinstance(record, dict) and record.get("session_id") else None


def _write_record(scope: str, record: dict) -> None:
    from agent_runtime.serde import write_json_atomic

    path = _record_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, record)


def _forget(scope: str) -> None:
    _record_path(scope).unlink(missing_ok=True)


@contextmanager
def _chat_db(session_id: str, persona_instance_id: str | None = None) -> Iterator[Any]:
    """The writer for ONE chat's own store: its conversation head, never the process store.

    A persona chat lives in its profile's ``state.db`` (``resolve_conversation_chat_scope``), and
    the serve's process store is base's: a hide written there lands on no row (read live on the QA
    serve 2026-11-23, the ready chat stayed in ``conversation.list`` and the snapshot)."""

    from agent_runtime.chat_heads import resolve_conversation_chat_scope
    from agent_runtime.chat_session_scope import SessionDbAccess, open_chat_session_db

    scope = resolve_conversation_chat_scope(session_id=session_id, persona_instance_id=persona_instance_id)
    db = open_chat_session_db(scope, access=SessionDbAccess.WRITE)
    if db is None:
        raise HomeNextChatRefused("chat_store_unavailable")
    with closing(db):
        yield db


def _still_ready(record: dict) -> bool:
    """The chat exists, is still hidden and has no message (else it is no longer Home's ready chat)."""

    with _chat_db(record["session_id"], record.get("persona_instance_id")) as db:
        row = db.get_session(record["session_id"])
    return bool(row) and bool(row.get("hidden")) and not int(row.get("message_count") or 0)


def _live_record(scope: str) -> dict | None:
    record = _read_record(scope)
    if record is not None and not _still_ready(record):
        _forget(scope)
        return None
    return record


def _shape(record: dict | None, **extra: Any) -> dict:
    if record is None:
        return {"session_id": None}
    return {"session_id": record["session_id"], "persona_id": record.get("persona_id"),
            "persona_instance_id": record.get("persona_instance_id"), "hidden": True, **extra}


def _receipt(op: str, scope: str, record: dict | None, outcome: str) -> None:
    record = record or {}
    logger.info(READY_CHAT_RECEIPT, op, scope[:12], record.get("session_id") or "-",
                record.get("persona_id") or "-", record.get("persona_instance_id") or "-", outcome)


def ready_chat(params: dict) -> dict:
    """``runtime.home.next_chat.get``: the account's ready chat, or ``{"session_id": None}``."""

    scope = _scope(params)
    with _LOCK:
        return _shape(_live_record(scope))


def _open_chat(params: dict, *, caller: Any) -> dict:
    from agent_runtime.persona_open_chat import perform_persona_instance_open_chat

    # An absent key, never a None one: open-chat refuses an ``install_id`` that is present but empty.
    params = {key: value for key, value in params.items() if value is not None}
    outcome = perform_persona_instance_open_chat(params, caller=caller, select_session=False)
    if outcome.refusal is not None:
        raise HomeNextChatRefused(str((outcome.refusal.data or {}).get("reason") or outcome.refusal.message))
    return dict(outcome.result or {})


def _mint_ready_chat(params: dict, persona_id: str, scope: str, *, caller: Any) -> dict:
    opened = _open_chat({
        "persona_id": persona_id,
        "persona_instance_id": _text(params, "persona_instance_id"),
        "client_scope": scope,
        "install_id": _text(params, "install_id"),
        "requested_by": _text(params, "requested_by") or "home",
        "new_session": True,
        "idempotency_key": f"home-ready-{uuid.uuid4().hex}",
    }, caller=caller)
    session_id = opened.get("session_id")
    if not session_id:
        raise HomeNextChatRefused("ready_chat_not_minted")
    instance_id = opened.get("persona_instance_id")
    with _chat_db(session_id, instance_id) as db:
        # MUTATION: drop this hide and test_a_ready_chat_is_in_no_list_until_its_first_message reddens.
        db.set_session_hidden(session_id, True)
    return {"session_id": session_id, "persona_id": persona_id, "persona_instance_id": instance_id}


def _retire(record: dict) -> str:
    """Delete the old ready chat while it is still empty (upstream's guarded empty-only delete).

    The mint gives every chat an automatic title and ``delete_session_if_empty`` keeps a titled row;
    the ready chat's title is the mint's, never the user's, so it is cleared first and the store's
    own one-transaction check (messages, children, turn lease) decides. A row it refuses gets its
    title back, stays hidden and is named in the receipt."""

    session_id = record["session_id"]
    with _chat_db(session_id, record.get("persona_instance_id")) as db:
        title, source = db.get_session_title(session_id), db.get_session_title_source(session_id)
        if title is not None:
            db.set_session_title(session_id, "")
        # MUTATION: skip this delete and test_switching_agent_deletes_the_empty_old_chat reddens.
        if db.delete_session_if_empty(session_id):
            return "deleted"
        if title is not None:
            db.set_session_title(session_id, title)
            db.set_session_title_source(session_id, source)
    return "kept_hidden"


def ensure_ready_chat(params: dict, *, caller: Any = None, launcher_link: Any = None) -> dict:
    """``runtime.home.next_chat.ensure``: the account's ONE ready chat, for ``persona_id``."""

    from agent_runtime.persona_chat_actor_prewarm import request_chat_actor_prewarm

    scope = _scope(params)
    persona_id = _text(params, "persona_id")
    if persona_id is None:
        raise HomeNextChatRefused("persona_id_required")
    instance_id = _text(params, "persona_instance_id")
    with _LOCK:
        record = _live_record(scope)
        created = repointed = False
        if record is not None and record.get("persona_id") == persona_id:
            if instance_id and instance_id != record.get("persona_instance_id"):
                moved = _open_chat({"persona_id": persona_id, "persona_instance_id": instance_id,
                                    "session_id": record["session_id"], "move": True,
                                    "client_scope": scope, "install_id": _text(params, "install_id")},
                                   caller=caller)
                record = {**record, "persona_instance_id": moved.get("persona_instance_id") or instance_id}
                repointed = True
                _receipt("ensure", scope, record, "moved")
        else:
            if record is not None:
                _receipt("retire", scope, record, _retire(record))
                repointed = True
            record = _mint_ready_chat(params, persona_id, scope, caller=caller)
            created = True
            _receipt("ensure", scope, record, "minted")
        _write_record(scope, record)
    prewarm = request_chat_actor_prewarm(record["session_id"], launcher_link=launcher_link)
    return _shape(record, created=created, repointed=repointed, prewarm=prewarm)


def _scope_of(session_id: str) -> str | None:
    folder = _record_path("0" * 64).parent
    if not session_id or not folder.is_dir():
        return None
    for path in folder.glob("*.json"):
        record = _read_record(path.stem)
        if record is not None and record.get("session_id") == session_id:
            return path.stem
    return None


def ready_session_ids_for(persona_id: str) -> list[str]:
    """Every account's live ready chat for ``persona_id`` (the boot prewarm's first pick)."""

    folder = _record_path("0" * 64).parent
    if not persona_id or not folder.is_dir():
        return []
    with _LOCK:
        records = [_live_record(path.stem) for path in sorted(folder.glob("*.json")) if _SCOPE.match(path.stem)]
    # MUTATION: drop the persona match and test_the_boot_pass_reads_the_ready_chat_of_the_agent_it_names reddens.
    return [record["session_id"] for record in records if record is not None and record.get("persona_id") == persona_id]


def promote_on_send(session_id: str | None) -> bool:
    """The send's first message makes Home's ready chat a visible chat; Home forgets it. Never raises."""

    try:
        with _LOCK:
            scope = _scope_of(str(session_id or ""))
            if scope is None:
                return False
            record = _read_record(scope) or {}
            _forget(scope)
            with _chat_db(str(session_id), record.get("persona_instance_id")) as db:
                db.set_session_hidden(session_id, False)
        _receipt("promote", scope, record, "shown")
        return True
    except Exception:  # a send never fails on Home's bookkeeping
        logger.debug("home ready chat promote failed for %s", session_id, exc_info=True)
        return False


def rewarm_if_ready(session_id: str | None, *, launcher_link: Any = None) -> str | None:
    """After a pick on Home's ready chat, rebuild its agent for the pick. ``None`` if it is not one."""

    try:
        if _scope_of(str(session_id or "")) is None:
            return None
        from agent_runtime.persona_chat_actor_prewarm import request_chat_actor_prewarm

        return request_chat_actor_prewarm(session_id, launcher_link=launcher_link)
    except Exception:
        logger.debug("home ready chat rewarm failed for %s", session_id, exc_info=True)
        return None
