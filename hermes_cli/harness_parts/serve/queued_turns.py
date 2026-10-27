"""The serve's half of the busy-root send queue: stream a queued turn like a sent one.

A directly sent turn streams on its own request: every line the handler prints —
the protocol-v2 chat frames, then ``chat.final`` — reaches the requester as
``{"id": <rid>, "event": "line", "line": ...}``, and the request ends with
``{"id": <rid>, "event": "exit", "code": ...}``. A queued turn
(``agent_runtime.chat_root_send_runner``) has no request left: its own ended with
the "queued" answer. So it runs under a request id of its own,
``queued:<client_message_id>``, and its frames — the same frames, through the
same stdout proxy — go out on the CONTROL channel the settle push uses (the stdio
frame writer when a launcher reads it, and a broadcast to every authenticated
loopback connection). The chat frames carry ``client_message_id`` / ``turn_id``,
which is what ties them to the message the launcher shows as queued.
Contract: ``docs/agent-runtime-harness/archive/busy-root-queue-2026-10-10.md``.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

from hermes_cli.harness_parts.serve.frames import _request_id, _request_sink

__layer__ = "lanes"

__all__ = ["QueuedTurnStream", "queued_turn_runner_policy", "start_serve_scheduler", "start_serve_work_engine"]


class _ControlSink:
    """A request sink whose frames go out on the serve's control channel, and to the
    paired device that sent the send (``queued_turn_origin.queued_turn_peer``)."""

    __slots__ = ("_peer", "_session")

    def __init__(self, session: Any, peer: Any = None) -> None:
        self._session = session
        self._peer = peer

    def emit(self, frame: dict[str, Any]) -> None:
        self._session._deliver_control_frame(frame)
        if self._peer is not None:
            self._peer.emit(frame)


class QueuedTurnStream:
    """One queued turn's stream: its request id, its sink, its terminal frames."""

    def __init__(self, session: Any, rid: str, peer: Any = None) -> None:
        self.session = session
        self.rid = rid
        self.sink = _ControlSink(session, peer)

    def finish(self, exit_code: int, payload: dict | None) -> None:
        # The handler hands its terminal payload to the door's sink instead of
        # printing it, so ``chat.final`` is printed here — through the same
        # proxy, in this request's context — exactly once.
        if isinstance(payload, dict):
            from hermes_cli.harness_parts.persona.chat_events import _emit_chat_final

            _emit_chat_final(payload)
        self.session.stdout_proxy.flush_request(self.rid)
        self.session.stderr_proxy.flush_request(self.rid)
        self.sink.emit({"id": self.rid, "event": "exit", "code": int(exit_code)})


@contextlib.contextmanager
def _queued_turn_stream(session: Any, entry: Any) -> Iterator[QueuedTurnStream]:
    from agent_runtime.chat_root_send_runner import queued_request_id
    from agent_runtime.launcher_app_functions import bind_launcher_link, reset_launcher_link
    from hermes_cli.harness_parts.serve.queued_turn_origin import queued_turn_link, queued_turn_peer

    rid = queued_request_id(entry.client_message_id)
    stream = QueuedTurnStream(session, rid, queued_turn_peer(session, entry, rid))
    rid_token = _request_id.set(stream.rid)
    sink_token = _request_sink.set(stream.sink)
    link_token = bind_launcher_link(queued_turn_link(session, entry))
    try:
        yield stream
    finally:
        reset_launcher_link(link_token)
        _request_sink.reset(sink_token)
        _request_id.reset(rid_token)


def _work_settled(session: Any, entry: Any, exit_code: int, payload: dict | None) -> None:
    executor = getattr(session, "work_executor", None)
    if executor is not None:
        executor.settled(entry, exit_code, payload)


def queued_turn_runner_policy(session: Any) -> Any:
    """The runner policy a serve starts its queued-send runner with.

    ``on_settle`` hands every terminal settle to the serve's Work executor when one was built
    (:func:`start_serve_work_engine`); it reads ``session.work_executor`` at settle time.
    """

    from agent_runtime.chat_root_send_runner import RunnerPolicy

    return RunnerPolicy(
        stream=lambda entry: _queued_turn_stream(session, entry),
        on_settle=lambda entry, exit_code, payload: _work_settled(session, entry, exit_code, payload),
    )


def _batch_hooks(session: Any) -> dict[str, Any]:
    """The batch dispatcher over the serve's executor (dispatcher plan §3, B2; lanes in worktrees, B5): its
    lane executor hears every settle of the serve's persona-turn executor and reports the batch's,
    the engine skips the rows a batch lane holds, and the engine's tick advances owned batches. Kept on
    ``session.batch_dispatcher`` for the scheduler's ``StartBatch`` door (:func:`_start_batch_door`)."""

    from agent_runtime.batch.dispatcher import default_dispatcher
    from agent_runtime.batch.manifest import held_refs

    dispatcher = session.batch_dispatcher = default_dispatcher(persona=session.work_executor)
    return {"held": held_refs, "after_tick": dispatcher.tick}


def _start_batch_door(session: Any) -> Any:
    """A ``StartBatch`` fire starts the plan through the serve's dispatcher as a SCHEDULED start (the
    dispatcher refuses ``automation_off`` below ``start``); None — ``door_unbound`` — without one."""

    dispatcher = getattr(session, "batch_dispatcher", None)
    if dispatcher is None:
        return None
    return lambda action: {"batch": dispatcher.start(action.workspace_id, action.plan_id, scheduled=True).wire()}


def start_serve_work_engine(session: Any) -> Any:
    """Build the serve's Work executor and engine and tick it beside the lens poller (work plan §6.3).

    Called BEFORE the queued-send runner starts, so the engine's boot read of its run records sees
    every run that ended while the serve was down before the runner can settle a resumed one. The
    messaging lane (``messaging.serve_lane``) starts last, on the same executor, where the package ships.
    A bundle that does not ship Work or git (the phone) builds nothing. Returns the engine or None.
    """

    from agent_runtime.loop_tool_lifecycles import shipped

    if not (shipped("agent_runtime.work") and shipped("agent_runtime.git_cmd")):
        return None
    from agent_runtime.work_store.engine import WorkEngine, home_scope, start_work_engine
    from agent_runtime.work_store.persona_turn import PersonaTurnExecutor

    home = getattr(session, "serve_request_home", None)
    with home_scope(home):
        session.work_executor = PersonaTurnExecutor(draining=lambda: session.drain_state is not None)
        hooks = _batch_hooks(session) if shipped("agent_runtime.batch") else {}
        session.work_engine = WorkEngine(executor=session.work_executor, **hooks)
    start_work_engine(stop_event=session.liveness_stop, engine=session.work_engine, home=home,
                      on_tick=session.work_executor.wake_parked)
    start_serve_scheduler(session)
    if shipped("agent_runtime.messaging"):  # both bundle manifests switch it off (p10-messaging §2.6)
        from agent_runtime.messaging.serve_lane import start_messaging_bridge

        start_messaging_bridge(session)
    return session.work_engine


def start_serve_scheduler(session: Any) -> Any:
    """Tick the serve's ``ServeTickScheduler`` (dispatcher plan §2.3, B4) on the Work executor.

    Started with the Work engine, so a fire queues through the same executor whose settles the runner
    reports; it fires nothing once the drain begins. Returns the scheduler.
    """

    from agent_runtime.work_store.engine import home_scope
    from agent_runtime.work_store.serve_scheduler import ServeTickScheduler, start_schedule_ticker

    home = getattr(session, "serve_request_home", None)
    with home_scope(home):
        session.scheduler = ServeTickScheduler(executor=session.work_executor,
                                               start_batch=_start_batch_door(session),
                                               start_assignment=getattr(getattr(session, "work_engine", None), "adopt", None),
                                               can_dispatch=lambda: session.drain_state is None)
    start_schedule_ticker(stop_event=session.liveness_stop, scheduler=session.scheduler, home=home)
    return session.scheduler
