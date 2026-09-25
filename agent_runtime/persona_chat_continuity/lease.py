"""The chat-root lease, and the scopes a native turn holds while it runs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import paths
from ..file_locks import try_lock_fd as _try_lock, unlock_fd as _unlock
from ..serde import safe_assignment_text, safe_assignment_token
from contextvars import ContextVar

__layer__ = "stores"

logger = logging.getLogger(__name__)


_TOOL_EXECUTION_SCOPE: ContextVar[str | None] = ContextVar(
    "persona_chat_tool_execution_scope", default=None
)


@contextmanager
def tool_execution_scope(scope_id: str | None) -> Iterator[None]:
    token = _TOOL_EXECUTION_SCOPE.set(safe_assignment_text(scope_id, limit=240))
    try:
        yield
    finally:
        _TOOL_EXECUTION_SCOPE.reset(token)


def current_tool_execution_scope() -> str | None:
    return _TOOL_EXECUTION_SCOPE.get()


@contextmanager
def chat_root_session_key_scope(scope_id: str | None) -> Iterator[None]:
    """Bind ``tools.approval``'s session-key ContextVar to this run's chat root.

    Session-scoped upstream surfaces resolve their identity through
    ``tools.approval.get_current_session_key``: the process registry stamps it
    onto every background spawn as ``session_key``, ``delegate_task`` records it
    on delegations, and the terminal tool keys cwd records by it. On the
    mission-chat lane nothing ever bound it, so a terminal spawned from a chat
    turn wrote ``session_key: ""`` — which meant (live incident 2026-08-11,
    ``proc_b0593bc9fb0e``):

    * its ``notify_on_complete`` completion event named no session that
      resolves to a persona chat root, so serve's completion drain
      (``dispatch_delivery._chat_root_of_completion`` — positive proof only,
      the #64484 no-guessing rule) re-queued it every pass forever, and the
      ledgerless event evaporated on the next serve restart with the output
      tail it carried;
    * the ``running_work`` projection could not attribute the row to an agent
      (the ``1c0e95bc3`` commit message predicted exactly this while wiring
      the resolver).

    Binding the ROOT chat session id here is positive knowledge at spawn time,
    not drain-time guessing: the run knows which chat root it executes under.
    Bound only for ids that name a persona chat root — this scope exists to
    make attribution resolvable, and pushing any other string into upstream's
    session-key surface would widen its meaning for no gain. ContextVar
    propagation into tool worker threads is owned by
    ``tools.thread_context.propagate_context_to_thread`` (copy_context), the
    same mechanism the terminal envelope scope already rides on this lane.

    Permission posture is unchanged by design: gated terminal commands on the
    governed mission-chat lane are decided by ``agent_runtime.terminal_envelope``,
    which does not consult the approval session key.
    """

    key = safe_assignment_text(scope_id, limit=240) if scope_id else ""
    if not key or not key.startswith("persona_chat_"):
        yield
        return
    try:
        from tools.approval_context import (
            reset_current_session_key,
            set_current_session_key,
        )
    except Exception:  # pragma: no cover - upstream surface unavailable
        yield
        return
    token = set_current_session_key(key)
    try:
        yield
    finally:
        reset_current_session_key(token)


class PersonaChatBusyError(RuntimeError):
    error_kind = "chat_busy"

    def __init__(self, root_session_id: str, owner: dict[str, Any] | None = None):
        super().__init__(f"persona chat root is busy: {root_session_id}")
        self.root_session_id = root_session_id
        self.owner = dict(owner or {})


def _root_stem(root: str) -> str:
    prefix = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in root)[:80]
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    return f"{prefix or 'chat'}_{digest}"


def _lease_paths(root: str) -> tuple[Path, Path]:
    base = paths.store_root() / "persona_chat_leases"
    stem = _root_stem(root)
    return base / f"{stem}.lock", base / f"{stem}.owner.json"


@contextmanager
def persona_chat_root_lease(
    root_session_id: str,
    *,
    owner_id: str | None = None,
    observer_kind: str = "cli",
    timeout_seconds: float = 0.0,
) -> Iterator[dict[str, Any]]:
    """Hold the OS-backed root lease for an entire native turn."""

    root = safe_assignment_text(root_session_id, limit=240)
    if not root:
        raise ValueError("root_session_id is required")
    lock_path, owner_path = _lease_paths(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    acquired = False
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    try:
        while True:
            try:
                _try_lock(fd)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    owner = None
                    try:
                        owner = json.loads(owner_path.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                    raise PersonaChatBusyError(root, owner)
                time.sleep(0.01)
        owner = {
            "root_chat_session_id": root,
            "owner_id": safe_assignment_token(owner_id) or f"pid-{os.getpid()}",
            "observer_kind": safe_assignment_token(observer_kind) or "cli",
            "pid": os.getpid(),
            "acquired_at": time.time(),
        }
        tmp = owner_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(owner, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(owner_path))
        yield owner
    finally:
        # Control flow is UNCHANGED: both arms still swallow, the release order
        # is still unlink-owner → unlock → close, and ``os.close(fd)`` is still
        # always reached. What is new is that neither failure is silent any
        # more. This is the producer-side half of the stale-lock discriminator:
        # a WARNING here, correlated by root and time with the delivery drain's
        # ``lease_busy_ownerless``, turns a hypothesis into a diagnosis.
        if acquired:
            try:
                owner_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "persona chat root lease owner file for %s could not be removed"
                    " (%s) — release continues",
                    root,
                    exc,
                    exc_info=True,
                )
            try:
                _unlock(fd)
            except OSError as exc:
                logger.warning(
                    "persona chat root lease byte-unlock FAILED for %s (%s) — the lock"
                    " will be released by handle close, whose timing Windows does not"
                    " guarantee; if the delivery drain then reports"
                    " lease_busy_ownerless, this line is the cause",
                    root,
                    exc,
                )
        os.close(fd)


def repair_orphaned_chat_turns() -> list[str]:
    """Settle in-flight turn records whose executor process died (boot sweep).

    A native turn holds the OS-backed root lease for its ENTIRE execution and
    the kernel releases the lock when the holding process dies, so "in-flight
    record AND acquirable lease" is proof the turn can no longer settle itself
    (live incident 2026-07-25: the Stage C MCP flow reaped the Launcher, which
    took the serve child executing a QA relay turn with it; the record froze
    at ``executing`` and the console showed a running turn forever). A session
    whose lease is HELD is a live turn in another process and is skipped.

    Runs at ``harness serve`` boot — the moment a launcher restart replaces a
    dead runtime — before the first hydrate is served, so the repaired records
    project as typed ``turn_interrupted`` markers instead of frozen output.
    When anything flips, a ``state.reconciled`` event is appended so any
    already-connected watermark-gated consumer converges too (turn files are
    not patch-covered). Best-effort per session; the next boot retries.
    """

    from ..mission_chat_turns import (
        inflight_chat_session_roots,
        mark_stale_inflight_turns_interrupted,
    )

    repaired: list[str] = []
    for root in inflight_chat_session_roots():
        try:
            with persona_chat_root_lease(root, observer_kind="orphan_sweep"):
                flipped = mark_stale_inflight_turns_interrupted(
                    session_id=root,
                    active_client_message_id=None,
                )
        except PersonaChatBusyError:
            continue
        except Exception:  # noqa: BLE001 — sweep must never block serve boot
            continue
        if flipped:
            repaired.append(root)
    if repaired:
        try:
            from hermes_time import now

            from ..events import EventLog
            from ..models import Event

            digest = hashlib.sha1("|".join(sorted(repaired)).encode("utf-8")).hexdigest()[:16]
            EventLog().append(
                Event(
                    now(),
                    "state.reconciled",
                    None,
                    None,
                    None,
                    {"fingerprint": digest, "source": "chat_orphan_sweep"},
                )
            )
        except Exception:  # noqa: BLE001 — the repair itself already landed
            pass
    return repaired
