"""The serve's queued-send runner: run each idle root's waiting send, record its settle.

Owner ruling 2026-10-10 (``docs/agent-runtime-harness/planned/busy-root-queue-2026-10-10.md``):
an operator send to a busy chat root is queued (``chat_root_send_queue``) and runs
after the current turn, in arrival order per root. This is the half that runs it:
a dispatcher thread in every serve hands the HEAD entry of each root whose
chat-root lease is free to a bounded worker pool — one turn at a time per root,
roots independent of each other — which runs it as a real mission-chat turn
through the door
(``mission_chat_door.run_mission_chat_turn``, the dispatch drain's forge path),
records the turn's settle in ``chat_turn_settles`` — the serve's pusher sends it as
``turn_settled`` — and deletes the entry. When the serve supplies a stream
(:attr:`RunnerPolicy.stream`), the turn runs STREAMED, so its frames reach the
launcher the way a directly sent turn's do.

A run that loses the lease to a newer turn comes back "queued" (the enqueue
converges on its own entry) and stays the head. An entry left ``running`` by a
serve that died is run again at the next boot: the turn journal dedupes the
``client_message_id`` (a replay of a committed reply, or ``outcome_unknown``), so
it is never a second turn.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, ContextManager, Protocol

from . import chat_root_send_queue as queue
from .chat_turn_settles import TurnOutcome, outcome_from_payload, record_settle
from .mission_chat_outcome import ChatErrorKind

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: How often the runner looks for a freed root when nothing woke it.
RUNNER_TICK_SECONDS = 1.0
#: A run that RAISES (never a refused or failed turn — those settle) is retried
#: this many times, then settled ``chat_turn_outcome_unknown`` and removed.
MAX_RUN_EXCEPTIONS = 3
#: The settle's ``request_id`` prefix, and the stream's request id: the turn was
#: not a serve request, so it is named after the message it runs.
SETTLE_REQUEST_PREFIX = "queued:"
#: Roots whose queued turns may run at the same time. One turn per root always.
MAX_CONCURRENT_ROOTS = 4

_wake = threading.Event()


def wake_queued_send_runner() -> None:
    """Ask the runner for a pass now (a send was queued, or a root was freed)."""

    _wake.set()


def _root_is_idle(root_session_id: str) -> bool:
    """Whether no turn holds the root's lease: a zero-wait acquire, released at once."""

    from .persona_chat_continuity import PersonaChatBusyError, persona_chat_root_lease

    try:
        with persona_chat_root_lease(
            root_session_id, owner_id="queued-send-probe", observer_kind="serve"
        ):
            return True
    except PersonaChatBusyError:
        return False


def _run_turn(args: Any) -> tuple[int, dict | None]:
    from .mission_chat_door import run_mission_chat_turn

    return run_mission_chat_turn(args)


class TurnStream(Protocol):
    """Where a streamed queued turn's frames go (the serve's control channel)."""

    def finish(self, exit_code: int, payload: dict | None) -> None:
        """Emit the turn's terminal frames: ``chat.final`` and the ``exit``."""


def queued_request_id(client_message_id: str) -> str:
    return f"{SETTLE_REQUEST_PREFIX}{client_message_id}"


@dataclass(frozen=True)
class RunnerPolicy:
    """The runner's seams, injected: is the root free, run one turn, and — when
    the host has a transport — the stream a turn's frames go to."""

    root_is_idle: Callable[[str], bool] = _root_is_idle
    run_turn: Callable[[Any], "tuple[int, dict | None]"] = _run_turn
    stream: "Callable[[queue.QueuedSend], ContextManager[TurnStream]] | None" = None


DEFAULT_RUNNER_POLICY = RunnerPolicy()


def run_queued_sends_once(policy: RunnerPolicy | None = None) -> dict[str, int]:
    """One pass: the head of every idle root, once. Never raises; returns a tally."""

    policy = policy or DEFAULT_RUNNER_POLICY
    tally = {"ran": 0, "busy": 0, "requeued": 0, "failed": 0}
    try:
        roots = queue.roots_with_entries()
    except Exception:
        logger.warning("queued-send runner could not read the queue", exc_info=True)
        return tally
    for root in roots:
        try:
            entry = queue.head(root)
            if entry is None:
                continue
            if not policy.root_is_idle(root):
                tally["busy"] += 1
                continue
            tally[_run_entry(entry, policy)] += 1
        except Exception:
            logger.warning("queued send on root %s could not run", root, exc_info=True)
            tally["failed"] += 1
    return tally


def _run_entry(entry: queue.QueuedSend, policy: RunnerPolicy) -> str:
    root, cmid = entry.root_session_id, entry.client_message_id
    queue.mark(root, cmid, state=queue.STATE_RUNNING)
    try:
        exit_code, payload = _run_streamed(entry, policy)
    except Exception as exc:
        attempts = entry.attempts + 1
        logger.warning("queued send %s raised (attempt %d)", cmid, attempts, exc_info=True)
        if attempts < MAX_RUN_EXCEPTIONS:
            queue.mark(root, cmid, state=queue.STATE_QUEUED, attempts=attempts)
            return "failed"
        _settle(entry, 2, TurnOutcome(
            session_id=root,
            turn_id=cmid,
            refusal_class=str(ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN),
            summary=f"the queued turn raised {attempts} times: {type(exc).__name__}",
        ))
        queue.remove(root, cmid)
        return "failed"
    if (payload or {}).get("queued") is True:
        # A newer turn took the lease between the probe and the run; the enqueue
        # converged on this entry, which stays the head for the next pass.
        queue.mark(root, cmid, state=queue.STATE_QUEUED)
        return "requeued"
    _settle(entry, int(exit_code), outcome_from_payload(payload))
    queue.remove(root, cmid)
    return "ran"


def _run_streamed(entry: queue.QueuedSend, policy: RunnerPolicy) -> tuple[int, dict | None]:
    if policy.stream is None:
        return policy.run_turn(_turn_args(entry, stream=False))
    with policy.stream(entry) as stream:
        exit_code, payload = policy.run_turn(_turn_args(entry, stream=True))
        if (payload or {}).get("queued") is not True:
            stream.finish(int(exit_code), payload)
        return exit_code, payload


def _turn_args(entry: queue.QueuedSend, *, stream: bool) -> SimpleNamespace:
    args = SimpleNamespace(**entry.args)
    args.session_id = entry.root_session_id
    args.client_message_id = entry.client_message_id
    # The root was resolved when the send was accepted; a queued turn never mints.
    args.new_session = False
    # Streamed exactly as a direct send is when the host gave it a stream; the
    # terminal payload still comes back through the door's sink for the settle.
    args.stream = stream
    args.json = True
    setattr(args, queue.QUEUED_RUN_ARG, True)
    return args


def _settle(entry: queue.QueuedSend, exit_code: int, outcome: TurnOutcome) -> None:
    record_settle(
        client_message_id=entry.client_message_id,
        session_id=entry.root_session_id,
        request_id=queued_request_id(entry.client_message_id),
        exit_code=exit_code,
        outcome=outcome,
    )


class QueuedSendRunner:
    """Dispatch each idle root's head to a bounded pool; roots never wait on each other.

    A root with a turn in a worker is skipped until that worker ends, so a root
    runs one queued turn at a time and in its arrival order, while a long turn
    on one root holds no other root back (up to ``max_workers`` roots at once).
    """

    def __init__(
        self,
        policy: RunnerPolicy | None = None,
        *,
        home: Path | str | None = None,
        max_workers: int = MAX_CONCURRENT_ROOTS,
    ) -> None:
        self.policy = policy or DEFAULT_RUNNER_POLICY
        self.home = home
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)), thread_name_prefix="harness-serve-queued-send"
        )
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def dispatch_once(self) -> dict[str, int]:
        """Hand every idle, unoccupied root's head to a worker. Never raises."""

        tally = {"dispatched": 0, "busy": 0, "occupied": 0}
        try:
            with self._home():
                roots = queue.roots_with_entries()
        except Exception:
            logger.warning("queued-send runner could not read the queue", exc_info=True)
            return tally
        for root in roots:
            with self._lock:
                if root in self._active:
                    tally["occupied"] += 1
                    continue
            try:
                with self._home():
                    entry = queue.head(root)
                    idle = entry is not None and self.policy.root_is_idle(root)
            except Exception:
                logger.warning("queued send on root %s could not be probed", root, exc_info=True)
                continue
            if entry is None:
                continue
            if not idle:
                tally["busy"] += 1
                continue
            with self._lock:
                self._active.add(root)
            self._pool.submit(self._work, entry)
            tally["dispatched"] += 1
        return tally

    def busy_roots(self) -> set[str]:
        with self._lock:
            return set(self._active)

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)

    def _work(self, entry: queue.QueuedSend) -> None:
        try:
            with self._home():
                _run_entry(entry, self.policy)
        except Exception:
            logger.warning("queued send %s could not run", entry.client_message_id, exc_info=True)
        finally:
            with self._lock:
                self._active.discard(entry.root_session_id)
            wake_queued_send_runner()  # the root is free: its next send may go

    def _home(self) -> ContextManager[None]:
        if self.home is None:
            return contextlib.nullcontext()
        from .profile_context import process_home_scope

        return process_home_scope(self.home)


def start_queued_send_runner(
    *,
    stop_event: threading.Event,
    home: Path | str | None = None,
    tick_seconds: float = RUNNER_TICK_SECONDS,
    policy: RunnerPolicy | None = None,
    max_workers: int = MAX_CONCURRENT_ROOTS,
) -> threading.Thread:
    """Run the dispatcher on a daemon thread until *stop_event* is set.

    *home* is the serve's request home, captured at boot and bound for every
    read and every worker, so the queue and the settle outbox are read and
    written where the serve's requests and its settle pusher look — never
    wherever a persona turn has mirrored ``HERMES_HOME`` to. *policy* carries
    the serve's stream, so queued turns stream on its control channel.
    """

    runner = QueuedSendRunner(policy, home=home, max_workers=max_workers)

    def _loop() -> None:
        try:
            while not stop_event.is_set():
                _wake.clear()  # before the pass, so a wake during it is not lost
                try:
                    runner.dispatch_once()
                except Exception:  # pragma: no cover - the dispatcher must never die
                    logger.warning("queued-send pass failed", exc_info=True)
                _wake.wait(tick_seconds)
        finally:
            runner.shutdown(wait=False)

    thread = threading.Thread(target=_loop, name="harness-serve-queued-sends", daemon=True)
    thread.start()
    return thread
