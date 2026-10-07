"""The bounded process-scoped one-resident-agent-per-root registry."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable

from ..clock import now_iso_micro

__layer__ = "stores"

logger = logging.getLogger(__name__)


@dataclass
class ResidentPersonaChatRuntime:
    root_session_id: str
    active_session_id: str
    signature: str
    revision: str
    agent: Any
    last_used_at: float
    created_at: float
    last_resumed_at: str
    turn_count: int = 0
    #: The per-component digest map the entry's ``signature`` was folded from
    #: (``mission_chat_turn_context.mission_chat_runtime_signature_digests``).
    #: Carried purely so the NEXT acquire can name the component that moved;
    #: it is never compared to decide reuse — the composite is the key, and a
    #: second authority for "are these the same actor" is how the two answers
    #: drift. Empty when the caller supplied none, in which case a mismatch
    #: reports the composite change and nothing more, honestly.
    signature_components: dict[str, str] = dataclass_field(default_factory=dict)
    #: Built by the chat-actor prewarm, not by a turn (h-chatperf). With
    #: ``turn_count == 0`` it is a prewarm no turn has used yet, and a
    #: signature change that discards it is a WASTED prewarm -- recorded as
    #: the prewarm's own outcome, not only as the turn's rebuild.
    prewarmed: bool = False


#: One line per rebuild whose cause is a moved signature component. Component
#: NAMES only, never digests and never values: the components include
#: prompt-adjacent material (the surface-prompt hash, the resolved tool
#: contract), and the diagnostic question is which input moved, not what it
#: moved to. Names come from a closed vocabulary — the keys of
#: ``mission_chat_runtime_signature_components``.
RESIDENT_SIGNATURE_DIFF_RECEIPT = "resident_signature_diff root=%s components=%s"


def _signature_component_diff(
    before: Any, after: Any
) -> tuple[str, ...]:
    """The component NAMES whose digests differ between two signatures.

    A name present on one side only counts as moved — a composition that gained
    or lost a component is exactly the kind of change this receipt exists to
    make visible, and treating an absent digest as "unchanged" would hide it.

    Returns ``()`` when either side carries no component map, which is the
    honest answer for a caller that supplied none: the composite moved and this
    registry cannot say which part of it did.
    """

    left = before if isinstance(before, dict) else {}
    right = after if isinstance(after, dict) else {}
    if not left or not right:
        return ()
    missing = object()
    return tuple(
        sorted(
            name
            for name in set(left) | set(right)
            if left.get(name, missing) != right.get(name, missing)
        )
    )


#: h-chatperf: the chat-open prewarm's after-the-fact outcome. Only a TURN can
#: know its prewarmed actor was wasted, so the registry -- where the turn throws
#: it away -- writes the prewarm's receipt, in the prewarm's own line format.
OUTCOME_DISCARDED_SIGNATURE_MISMATCH = "discarded_signature_mismatch"
PREWARM_DISCARDED_RECEIPT = "persona_chat_actor_prewarm root=%s outcome=%s components=%s"


def _record_prewarm_discard(root_session_id: str, components: tuple[str, ...]) -> None:
    try:
        logger.info(
            PREWARM_DISCARDED_RECEIPT,
            root_session_id,
            OUTCOME_DISCARDED_SIGNATURE_MISMATCH,
            ",".join(components) or "unknown",
        )
    except Exception:  # pragma: no cover - an instrument never fails a turn
        pass


#: The registry's own lifecycle vocabulary, read by name in :meth:`transition`.
#: Not ``states.TaskState``/``RunState``: ``failed`` is spelled there too, for a
#: different question (program batch-1 rule: a fork-wide word is named in its
#: single reader, never enum-ised).
RUNTIME_STATES: tuple[str, ...] = ("cold", "busy", "hot", "failed")
RUNTIME_STATE_FAILED = "failed"


class PersonaChatRuntimeRegistry:
    """Bounded process-scoped one-resident-agent-per-root registry."""

    def __init__(self, *, max_entries: int = 8, ttl_seconds: float = 900.0):
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._entries: OrderedDict[str, ResidentPersonaChatRuntime] = OrderedDict()
        self._transitions: dict[str, dict[str, Any]] = {}
        #: root -> the component names of the last prewarmed actor a turn
        #: discarded, until :meth:`take_prewarm_discard` collects it.
        self._prewarm_discards: dict[str, tuple[str, ...]] = {}
        self._lock = threading.RLock()

    def acquire(
        self,
        *,
        root_session_id: str,
        active_session_id: str,
        signature: str,
        revision: str,
        factory: Callable[[], Any],
        signature_components: dict[str, str] | None = None,
        prewarm: bool = False,
    ) -> tuple[ResidentPersonaChatRuntime, bool, str | None, tuple[str, ...]]:
        """Reuse this root's actor, or build one. Reports WHY, and WHAT moved.

        The fourth element is the component NAMES that differ between the
        stored entry's signature and this caller's — empty for every outcome
        except a ``runtime_signature_changed`` rebuild whose caller supplied a
        component map on BOTH sides. It is a receipt, not a decision: reuse is
        decided by the composite ``signature`` exactly as before, because two
        authorities for "is this the same actor" is how the two answers drift.
        """

        now = time.monotonic()
        components = dict(signature_components or {})
        with self._lock:
            self._evict_expired(now)
            entry = self._entries.pop(root_session_id, None)
            rebuild_reason = None
            signature_diff: tuple[str, ...] = ()
            if entry is not None and entry.signature != signature:
                rebuild_reason = "runtime_signature_changed"
                signature_diff = _signature_component_diff(
                    entry.signature_components, components
                )
                if signature_diff:
                    logger.info(
                        RESIDENT_SIGNATURE_DIFF_RECEIPT,
                        root_session_id,
                        ",".join(signature_diff),
                    )
                if entry.prewarmed and entry.turn_count == 0 and not prewarm:
                    self._prewarm_discards[root_session_id] = signature_diff
                    _record_prewarm_discard(root_session_id, signature_diff)
                self._close_entry(entry)
                entry = None
            elif entry is not None and (entry.revision != revision or entry.active_session_id != active_session_id):
                rebuild_reason = "disk_revision_changed"
                self._close_entry(entry)
                entry = None
            reused = entry is not None
            if entry is None:
                entry = ResidentPersonaChatRuntime(
                    root_session_id=root_session_id,
                    active_session_id=active_session_id,
                    signature=signature,
                    revision=revision,
                    agent=factory(),
                    created_at=now,
                    last_used_at=now,
                    last_resumed_at=now_iso_micro(),
                    signature_components=components,
                    prewarmed=bool(prewarm),
                )
                self._record_transition(
                    root_session_id,
                    "cold",
                    "rebuilt" if rebuild_reason else "rehydrated",
                )
            entry.last_used_at = now
            self._entries[root_session_id] = entry
            while len(self._entries) > self.max_entries:
                evicted_root, evicted = self._entries.popitem(last=False)
                self._close_entry(evicted)
                self._record_transition(evicted_root, "cold", "evicted")
            return entry, reused, rebuild_reason, signature_diff

    def take_prewarm_discard(self, root_session_id: str) -> tuple[str, ...] | None:
        """The components of the prewarmed actor the last acquire discarded, once.

        ``None`` when the last rebuild of this root did not discard an unused
        prewarm. Popped, so one discard is reported on exactly one turn.
        """

        with self._lock:
            return self._prewarm_discards.pop(root_session_id, None)

    def finish(self, root_session_id: str, *, active_session_id: str, revision: str) -> None:
        with self._lock:
            entry = self._entries.get(root_session_id)
            if entry is None:
                return
            tip_advanced = entry.active_session_id != active_session_id
            entry.active_session_id = active_session_id
            entry.revision = revision
            entry.last_used_at = time.monotonic()
            entry.turn_count += 1
            self._entries.move_to_end(root_session_id)
            self._record_transition(
                root_session_id,
                "hot",
                "tip_advanced" if tip_advanced else None,
            )

    def transition(self, root_session_id: str, state: str) -> None:
        """Record process-local lifecycle truth for an owning serve observer."""

        if state not in RUNTIME_STATES:
            raise ValueError(f"invalid persona chat runtime state: {state}")
        with self._lock:
            self._record_transition(
                root_session_id,
                state,
                RUNTIME_STATE_FAILED if state == RUNTIME_STATE_FAILED else None,
            )

    def evict(self, root_session_id: str) -> bool:
        with self._lock:
            entry = self._entries.pop(root_session_id, None)
            removed = entry is not None
            if entry is not None:
                self._close_entry(entry)
            self._record_transition(root_session_id, "cold", "evicted")
            return removed

    def observation(self, root_session_id: str, *, owning_process: bool) -> dict[str, Any]:
        if not owning_process:
            return {
                "runtime_state": "unknown",
                "runtime_observer_id": "external_cli",
                "runtime_observed_at": now_iso_micro(),
            }
        with self._lock:
            entry = self._entries.get(root_session_id)
            transition = self._transitions.get(root_session_id) or {}
            state = transition.get("state") or ("hot" if entry else "cold")
            return {
                "runtime_state": state,
                "last_runtime_transition": transition.get("transition"),
                "runtime_observer_id": f"serve:{os.getpid()}",
                "runtime_observed_at": now_iso_micro(),
                "active_session_id": entry.active_session_id if entry else None,
                "last_resumed_at": entry.last_resumed_at if entry else None,
            }

    def export_observations(self) -> dict[str, Any]:
        """Every root this registry would answer other than ``cold``, for a process
        that builds rows on this one's behalf (:class:`RecordedRuntimeObserver`)."""

        with self._lock:
            roots: dict[str, dict[str, Any]] = {}
            for root in set(self._entries) | set(self._transitions):
                entry = self._entries.get(root)
                transition = self._transitions.get(root) or {}
                roots[root] = {
                    "runtime_state": transition.get("state") or ("hot" if entry else "cold"),
                    "last_runtime_transition": transition.get("transition"),
                    "active_session_id": entry.active_session_id if entry else None,
                    "last_resumed_at": entry.last_resumed_at if entry else None,
                }
        return {"observer_id": f"serve:{os.getpid()}", "roots": roots}

    def _record_transition(
        self, root_session_id: str, state: str, transition: str | None = None
    ) -> None:
        previous = self._transitions.get(root_session_id) or {}
        self._transitions[root_session_id] = {
            "state": state,
            "transition": transition or previous.get("transition"),
        }

    @staticmethod
    def _close_entry(entry: ResidentPersonaChatRuntime) -> None:
        close = getattr(entry.agent, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _evict_expired(self, now: float) -> None:
        expired = [key for key, value in self._entries.items() if now - value.last_used_at > self.ttl_seconds]
        for key in expired:
            entry = self._entries.pop(key, None)
            if entry is not None:
                self._close_entry(entry)
            self._record_transition(key, "cold", "evicted")


_REGISTRY: PersonaChatRuntimeRegistry | None = None


def initialize_persona_chat_runtime_registry(
    *, enabled: bool = True, max_entries: int = 8, ttl_seconds: float = 1800.0
) -> PersonaChatRuntimeRegistry | None:
    global _REGISTRY
    _REGISTRY = (
        PersonaChatRuntimeRegistry(max_entries=max_entries, ttl_seconds=ttl_seconds)
        if enabled
        else None
    )
    # h-idle-turn: the idle keeper (policy) asks this store whether resident chats are on.
    from agent_runtime import idle_turn_keeper

    idle_turn_keeper.bind_registry_live(lambda: persona_chat_runtime_registry() is not None)
    return _REGISTRY


def persona_chat_runtime_registry() -> PersonaChatRuntimeRegistry | None:
    return _REGISTRY


class RecordedRuntimeObserver:
    """The serve's registry as one export, answering :meth:`observation` exactly as
    the serve would (its ``serve:<pid>`` observer, its states; ``cold`` for any root
    it holds nothing for). The snapshot worker builds history rows with it: the
    worker owns no resident chat, so its own registry would say nothing true."""

    def __init__(self, recorded: dict[str, Any]) -> None:
        self._observer_id = str(recorded.get("observer_id") or "")
        roots = recorded.get("roots")
        self._roots = dict(roots) if isinstance(roots, dict) else {}

    def observation(self, root_session_id: str, *, owning_process: bool) -> dict[str, Any]:
        if not owning_process:
            return {
                "runtime_state": "unknown",
                "runtime_observer_id": "external_cli",
                "runtime_observed_at": now_iso_micro(),
            }
        row = self._roots.get(root_session_id) or {}
        return {
            "runtime_state": row.get("runtime_state") or "cold",
            "last_runtime_transition": row.get("last_runtime_transition"),
            "runtime_observer_id": self._observer_id,
            "runtime_observed_at": now_iso_micro(),
            "active_session_id": row.get("active_session_id"),
            "last_resumed_at": row.get("last_resumed_at"),
        }


_RECORDED_OBSERVER: ContextVar[RecordedRuntimeObserver | None] = ContextVar(
    "persona_chat_recorded_runtime_observer", default=None
)


def export_runtime_observations() -> dict[str, Any] | None:
    """This process's registry as a worker request carries it; ``None`` = no registry."""

    registry = _REGISTRY
    return None if registry is None else registry.export_observations()


@contextmanager
def recorded_runtime_registry(recorded: dict[str, Any] | None):
    """Answer :func:`persona_chat_runtime_observer` from ``recorded`` (the worker's side)."""

    token = _RECORDED_OBSERVER.set(RecordedRuntimeObserver(recorded) if isinstance(recorded, dict) else None)
    try:
        yield
    finally:
        _RECORDED_OBSERVER.reset(token)


def persona_chat_runtime_observer() -> PersonaChatRuntimeRegistry | RecordedRuntimeObserver | None:
    """Who answers a history row's runtime observation: the serve's export when a
    worker build carries one, else this process's registry."""

    recorded = _RECORDED_OBSERVER.get()
    return recorded if recorded is not None else _REGISTRY
