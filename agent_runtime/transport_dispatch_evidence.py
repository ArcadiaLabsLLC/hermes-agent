"""Per-attempt transport evidence for one chat turn (RT-PROVIDER-REQUEST-START, ruled 2026-10-21).

**The question.** A turn that raised after the provider boundary settles ``outcome_unknown``
unless something proves what the provider did. ``request_sent`` (httpcore's
``send_request_body.complete``, :mod:`agent_runtime.transport_phase_trace`) is positive proof a
request LEFT; its absence proves nothing on a path that carries no hook (Bedrock's boto3, the
Codex app-server subprocess). So "nothing left" is read only off a per-attempt fact: every
physical attempt's request client was hooked by ``install_transport_phase_trace`` AND that hook
saw the attempt's transport (an httpcore trace event), and no attempt sent a body.

**The ledger.** One :class:`TransportAttempts` per turn, hung on the agent at agent-ready
(:func:`begin_turn_attempts`). ``conversation_observability.time_provider_dispatch`` opens an
attempt per physical dispatch; the transport trace notes facts on the newest one. An attempt
nobody hooked stays unhooked, which keeps the turn ambiguous: over-approximating "maybe sent"
is the safe direction. Never raises.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .model_route import ModelRoute, execution_model_route

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The per-turn receipt: grep-able, never a key on the terminal frame.
TRANSPORT_EVIDENCE_RECEIPT = "turn_transport_evidence turn=%s attempts=%d hooked=%d traced=%d sent=%d unsent_proven=%s"

_LEDGER_ATTR = "_hermes_transport_attempts"


class AttemptFact(StrEnum):
    """What the transport can say about one physical attempt."""

    HOOKED = "hooked"  # install_transport_phase_trace put the trace hook on the attempt's client
    TRACED = "traced"  # that hook saw an httpcore event: the attempt's request reached the hooked transport
    SENT = "sent"  # httpcore finished sending a request body (``request_sent``)


@dataclass(slots=True)
class _Attempt:
    hooked: bool = False
    traced: bool = False
    sent: bool = False


class TransportAttempts:
    """The physical provider attempts of one turn and what their transport proved."""

    def __init__(self, publish_route: Callable[[ModelRoute], bool] | None = None) -> None:
        self._lock = threading.Lock()
        self._attempts: list[_Attempt] = []
        self._publish_route = publish_route
        self._active_route: ModelRoute | None = None
        self._published_route: ModelRoute | None = None
        self._request_id: object = None
        self._reply_route: ModelRoute | None = None

    def open(self) -> None:
        with self._lock:
            self._attempts.append(_Attempt())

    def dispatch(self, provider: object, model: object, request_id: object) -> None:
        route = execution_model_route(provider, model)
        with self._lock:
            self._request_id = request_id
            self._active_route = route
            if route is None or route == self._published_route or self._publish_route is None:
                return
            try:
                if self._publish_route(route):
                    self._published_route = route
            except Exception:
                logger.warning("turn model route publish failed", exc_info=True)

    def record_reply(self, response_model: object, request_id: object) -> None:
        with self._lock:
            route = self._active_route
            if route is not None and request_id == self._request_id:
                self._reply_route = execution_model_route(route["provider"], response_model) or route

    @property
    def reply_route(self) -> ModelRoute | None:
        with self._lock:
            return self._reply_route.copy() if self._reply_route is not None else None

    def note(self, fact: AttemptFact) -> None:
        with self._lock:
            if self._attempts:
                setattr(self._attempts[-1], fact.value, True)

    def proven_unsent(self) -> bool:
        """True only when there was an attempt, every attempt was hooked and traced, and none sent."""

        with self._lock:
            return bool(self._attempts) and all(
                attempt.hooked and attempt.traced and not attempt.sent for attempt in self._attempts
            )

    def log_receipt(self, turn_id: str) -> None:
        with self._lock:
            attempts = list(self._attempts)
        logger.info(
            TRANSPORT_EVIDENCE_RECEIPT, turn_id, len(attempts), sum(a.hooked for a in attempts),
            sum(a.traced for a in attempts), sum(a.sent for a in attempts), self.proven_unsent(),
        )


def begin_turn_attempts(
    agent: Any, *, publish_route: Callable[[ModelRoute], bool] | None = None,
) -> TransportAttempts:
    """A fresh ledger for the turn *agent* is about to run (a resident agent serves many turns)."""

    ledger = TransportAttempts(publish_route)
    try:
        setattr(agent, _LEDGER_ATTR, ledger)
    except Exception:
        logger.debug("transport attempt ledger not attached", exc_info=True)
    return ledger


def open_attempt(agent: Any) -> None:
    """One physical provider attempt begins on *agent*'s turn."""
    ledger = getattr(agent, _LEDGER_ATTR, None)
    if isinstance(ledger, TransportAttempts):
        ledger.open()


def record_dispatched_route(
    agent: Any, model: object, *, provider: object, request_id: object = None,
) -> None:
    """The main turn passed middleware and handed a request to its actual provider route."""
    ledger = getattr(agent, _LEDGER_ATTR, None)
    if isinstance(ledger, TransportAttempts):
        ledger.dispatch(provider, model, request_id)


def record_reply_route(agent: Any, response_model: object = None, *, request_id: object = None) -> None:
    """An accepted response contained text from the same execution attempt."""
    ledger = getattr(agent, _LEDGER_ATTR, None)
    if isinstance(ledger, TransportAttempts):
        ledger.record_reply(response_model, request_id)


def note_attempt(agent: Any, fact: AttemptFact) -> None:
    """Record *fact* on *agent*'s current attempt; a turn without a ledger records nothing."""

    ledger = getattr(agent, _LEDGER_ATTR, None)
    if isinstance(ledger, TransportAttempts):
        ledger.note(fact)


__all__ = [
    "TRANSPORT_EVIDENCE_RECEIPT",
    "AttemptFact",
    "TransportAttempts",
    "begin_turn_attempts",
    "note_attempt",
    "open_attempt",
    "record_dispatched_route",
    "record_reply_route",
]
