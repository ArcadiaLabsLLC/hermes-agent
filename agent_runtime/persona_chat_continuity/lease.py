"""The chat-root lease, and the scopes a native turn holds while it runs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

from .. import paths
from ..file_locks import try_lock_fd, unlock_fd
from ..serde import safe_assignment_text, safe_assignment_token

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
    base = paths.store_root() / paths.PERSONA_CHAT_LEASES_DIRNAME
    stem = _root_stem(root)
    return base / f"{stem}.lock", base / f"{stem}.owner.json"


def _acquire(fd: int, root: str, owner_path: Path, timeout_seconds: float) -> None:
    """Take the byte lock, polling until *timeout_seconds*; busy past it is typed."""

    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while True:
        try:
            try_lock_fd(fd)
            return
        except OSError:
            if time.monotonic() >= deadline:
                owner = None
                try:
                    owner = json.loads(owner_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
                raise PersonaChatBusyError(root, owner)
            time.sleep(0.01)


def _write_owner(
    owner_path: Path, root: str, owner_id: str | None, observer_kind: str
) -> dict[str, Any]:
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
    return owner


def _release(fd: int, root: str, owner_path: Path, *, acquired: bool) -> None:
    """Release in the one order the stale-lock discriminator reads: unlink-owner → unlock → close.

    Both arms swallow and ``os.close(fd)`` is always reached; neither failure is
    silent. This is the producer-side half of the stale-lock discriminator: a
    WARNING here, correlated by root and time with the delivery drain's
    ``lease_busy_ownerless``, turns a hypothesis into a diagnosis.
    """

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
            unlock_fd(fd)
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
    try:
        _acquire(fd, root, owner_path, timeout_seconds)
        acquired = True
        yield _write_owner(owner_path, root, owner_id, observer_kind)
    finally:
        _release(fd, root, owner_path, acquired=acquired)


def chat_root_lease_holder(root_session_id: str, *, probe_owner: str) -> dict[str, Any] | None:
    """Who holds the root's lease right now: ``None`` when no turn does, else its owner record.

    THE busy-chat check (row RT-ONE-CHECK-FOR-WHETHER-A-CHAT-IS-BUSY): a zero-wait
    acquire, released at once, so a probe never holds the root a turn is about to
    take. A held lease whose owner file cannot be read answers ``{}`` (busy, owner
    unknown) — never ``None``. ``probe_owner`` names the caller in the owner file
    for the instant the probe holds it. Anything other than "busy" propagates.
    """

    try:
        with persona_chat_root_lease(root_session_id, owner_id=probe_owner, observer_kind="serve"):
            return None
    except PersonaChatBusyError as exc:
        return dict(exc.owner)


def chat_root_is_busy(root_session_id: str, *, probe_owner: str) -> bool:
    """Whether a turn holds the root's lease right now (:func:`chat_root_lease_holder`)."""

    return chat_root_lease_holder(root_session_id, probe_owner=probe_owner) is not None


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

    from ..mission_chat_turns.journal import mark_stale_inflight_turns_interrupted
    from ..mission_chat_turns.reads import inflight_chat_session_roots
    from ..chat_turn_reservations import repair_orphaned_chat_receipts

    repaired: list[str] = repair_orphaned_chat_receipts()
    for root in inflight_chat_session_roots():
        try:
            with persona_chat_root_lease(root, observer_kind="orphan_sweep"):
                flipped = mark_stale_inflight_turns_interrupted(
                    session_id=root,
                    active_client_message_id=None,
                )
                if flipped:
                    close_cut_off_transcript(root)
        except PersonaChatBusyError:
            continue
        except Exception:  # sweep must never block serve boot
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
        except Exception:  # the repair itself already landed
            pass
    return repaired


def close_cut_off_transcript(root_session_id: str) -> bool:
    """Close a cut-off turn in the chat's transcript, so the next message is a turn of its own.

    RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF (review w1118a.58 D9). A serve
    stopped mid-turn leaves the turn's user message (and any tool rows) with no reply. The journal
    record is flipped ``interrupted`` above, but the transcript still ends on that user message, so
    the next message — a send queued behind the cut-off turn — reached the model merged into it by
    upstream's alternation repair and was answered as the cut-off message. The sweep appends the
    row upstream itself appends when its own interrupt cuts a turn
    (``agent_runtime_helpers_placeholders.hidden_interrupt_placeholder_row``: hidden in transcripts,
    a neutral label on the wire), after a result for each tool call the turn left unanswered
    (:func:`_closing_rows`); upstream's repair is not touched.

    Called under the root's lease (no live executor), and only after a flip. A transcript that
    already ends on a reply is left as it is. Best-effort: ``False`` when nothing was
    written, never a raise into serve boot.
    """

    try:
        from agent.agent_runtime_helpers_placeholders import hidden_interrupt_placeholder_row

        from ..chat_session_scope import SessionDbAccess, open_chat_session_db, resolve_chat_session_scope
        from ..persona_chat_session import _persona_chat_native_tip

        db = open_chat_session_db(resolve_chat_session_scope(session_id=root_session_id), access=SessionDbAccess.WRITE)
    except Exception:
        logger.warning("cut-off turn on %s: transcript not opened", root_session_id, exc_info=True)
        return False
    if db is None:
        return False
    try:
        tip = _persona_chat_native_tip(db, root_session_id)
        rows = _closing_rows(db.get_messages(tip, limit=CUT_OFF_TAIL_ROWS, latest=True), hidden_interrupt_placeholder_row())
        for row in rows:
            db.append_message(tip, row.pop("role"), row.pop("content"), **row)
        return bool(rows)
    except Exception:
        logger.warning("cut-off turn on %s: transcript not closed", root_session_id, exc_info=True)
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass


#: How many of the transcript's newest rows the closing read looks at: the cut-off turn's tail
#: (its last assistant row and the tool results after it) is far shorter.
CUT_OFF_TAIL_ROWS = 64
#: The result a cut-off turn's unanswered tool call is closed with: a structural label, like
#: upstream's interrupt placeholder, never prose a model would echo.
CUT_OFF_TOOL_RESULT = "[interrupt: the runtime restarted before this tool returned]"


def _closing_rows(tail: list[dict], placeholder: dict) -> list[dict]:
    """The rows that close a transcript whose newest rows are ``tail`` (oldest first); ``[]`` when it is closed.

    Seen live 2026-11-20 (w1118a-hrun): a turn cut while its tool ran ends on an assistant row whose
    ``tool_calls`` no result answers; upstream's repair prunes the calls, drops the empty row, and
    the next user message merged into the cut-off one again. So each unanswered call gets a result
    first, then the hidden assistant row closes the turn. A tail that ends on a reply (an assistant
    row without calls) is closed already.
    """

    from agent.message_sanitization import coalesce_tool_call_id

    answered: set[str] = set()
    for row in reversed(tail):
        role = row.get("role")
        if role == "tool":
            answered.add(str(row.get("tool_call_id") or ""))
            continue
        if role != "assistant":
            break
        calls = row.get("tool_calls") or []
        if not calls and not answered:
            return []
        results = []
        for call in calls:
            call_id = coalesce_tool_call_id(call) or ""
            if call_id and call_id not in answered:
                name = ((call.get("function") or {}).get("name") if isinstance(call, dict) else None) or None
                results.append({"role": "tool", "content": CUT_OFF_TOOL_RESULT, "tool_call_id": call_id,
                                "tool_name": name})
        return [*results, dict(placeholder)]
    return [dict(placeholder)] if tail else []
