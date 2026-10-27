"""Turn-scoped secrets held in the serve process, never in argv (RT-COURSE-TURN-SECRETS).

Plan ``docs/agent-runtime-harness/archive/course-turn-credential-2026-10-25.md`` §2.1-2.3. A
``runtime.chat.message`` param becomes argv, and argv is durable: the accept receipt fingerprints
it and keeps it to answer a replay. A credential the turn needs (the course credential the
Launcher brokers) therefore rides :attr:`agent_runtime.chat_turn.ChatTurnRequest.secrets`
instead, outside argv and the fingerprint, and lives HERE for the turn's duration only:

* :func:`put` — the method lane, just before the turn is handed to the pool;
* :func:`bound` — the serve's turn wrapper binds the CURRENT turn id around the run, so a
  tool inside the turn (``contextvars`` are copied onto tool threads) reads it with :func:`get`;
* :func:`drop` — the same wrapper's ``finally``, and the lane on a refused spawn.

Never written to disk, never logged; a value past its ``expires_at`` reads as absent.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping

from agent_runtime.process_state import register_process_state

__layer__ = "stores"
__all__ = ["bound", "current_turn_request_id", "drop", "get", "put"]

#: turn_request_id -> {name: (value, expires_at epoch seconds | None)}
_SECRETS: dict[str, dict[str, tuple[Any, float | None]]] = {}
_LOCK = threading.Lock()
_CURRENT: ContextVar[str | None] = ContextVar("agent_runtime_turn_secrets_current", default=None)


def _reset() -> None:
    with _LOCK:
        _SECRETS.clear()


register_process_state("agent_runtime.turn_secrets", _reset, holds=("_SECRETS",))


def _expires_at(value: Any) -> float | None:
    moment = getattr(value, "expires_at", None)
    try:
        return moment.timestamp() if moment is not None else None
    except Exception:
        return None


def put(turn_request_id: str, secrets: Mapping[str, Any]) -> None:
    """Hold ``secrets`` for the turn ``turn_request_id``. An empty mapping holds nothing."""

    if not turn_request_id or not secrets:
        return
    with _LOCK:
        _SECRETS[turn_request_id] = {name: (value, _expires_at(value)) for name, value in secrets.items()}


def drop(turn_request_id: str) -> None:
    """Forget every secret of the turn. Idempotent."""

    with _LOCK:
        _SECRETS.pop(turn_request_id, None)


@contextmanager
def bound(turn_request_id: str) -> Iterator[None]:
    """The turn ``turn_request_id`` is the CURRENT turn for this context while the block runs."""

    token = _CURRENT.set(turn_request_id or None)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_turn_request_id() -> str | None:
    return _CURRENT.get()


def get(name: str) -> Any | None:
    """The CURRENT turn's secret ``name``, or None (no turn bound, none held, or expired)."""

    turn_request_id = _CURRENT.get()
    if not turn_request_id:
        return None
    with _LOCK:
        held = _SECRETS.get(turn_request_id, {}).get(name)
    if held is None:
        return None
    value, expires_at = held
    return None if expires_at is not None and expires_at <= time.time() else value
