"""The shared dispatcher: ONE op table, N transports.

``sink`` is where a message's answers go (stdout for stdio, the originating
connection for a socket client) and ``connection`` is None on stdio. On stdio
``sink is frames`` and ``connection is None``, so the frames, their order and
the exit codes are the ones the stdio reader loop always produced.

Routing is data (program rule 12): :data:`OP_HANDLERS` maps every op in
:data:`~hermes_cli.harness_parts.serve.constants.OPS` (plus the handshake word
``hello``) to one ``_op_*`` method, and a frame naming no known op falls through
to the method lane and then the argv lane — the one boundary left as code.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from functools import partial
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest
from hermes_cli.harness_parts.serve.constants import (
    _DRAIN_DEADLINE_FLOOR_SECONDS,
    DRAINING_EXIT_CODE,
    HELLO_OP,
    OPS,
    READER_STOP,
    SERVE_SCHEMA_VERSION,
)
from hermes_cli.harness_parts.serve.drain import _drain_deadline_seconds, _DrainState
from hermes_cli.harness_parts.serve.manifest import _is_gateway, _pairing_block, ops_manifest

__layer__ = "lanes"

__all__ = [
    "OP_HANDLERS",
    "MessageHandling",
    "SubscribeOptions",
    "parse_subscribe_options",
]


class SubscribeOptions:
    """A subscribe frame's two optional declarations, validated once.

    ``declared`` is the patch-fold capability set (``None`` = the client said
    nothing, which is NOT the empty set); ``resume_requested`` /
    ``resume_offset`` are the watermark resume.
    """

    __slots__ = ("declared", "resume_offset", "resume_requested")

    def __init__(self, declared: Any, resume_requested: bool, resume_offset: Any) -> None:
        self.declared = declared
        self.resume_requested = resume_requested
        self.resume_offset = resume_offset


def parse_subscribe_options(message: dict[str, Any]) -> tuple[SubscribeOptions | None, str | None]:
    """``(options, None)``, or ``(None, refusal_reason)`` for a malformed option.

    Optional patch-fold capability declaration. ABSENT means the client said
    nothing — the historical {persona_instance, incident} — which is what every
    client in the field sends and is exactly today's wire. Present-but-malformed
    is REFUSED rather than quietly read as absent: a client that meant to narrow
    the set and was silently widened back to the historical one would get
    patches it cannot fold, which is the precise failure this negotiation exists
    to prevent.

    Optional watermark RESUME. Same discipline: absent means the client asked
    for nothing (and gets the hydrate it always got, with no ``resume`` key
    anywhere on the ack, so a subscribe that predates this parameter is answered
    byte-identically); present-but-malformed is REFUSED rather than read as
    absent, because a client that meant to resume and was silently re-baselined
    would pay the megabyte it asked not to and have nothing to grep for.
    """

    declared_raw = message.get("fold_entities")
    declared: Any = None
    if declared_raw is not None:
        if not isinstance(declared_raw, list) or not all(
            isinstance(name, str) and name.strip() for name in declared_raw
        ):
            return None, "invalid_fold_entities"
        declared = frozenset(name.strip() for name in declared_raw)
    resume_raw = message.get("resume")
    resume_offset: Any = None
    if resume_raw is not None:
        if not isinstance(resume_raw, dict):
            return None, "invalid_resume"
        resume_offset = resume_raw.get("event_offset")
    return SubscribeOptions(declared, resume_raw is not None, resume_offset), None


class MessageHandling:
    """The dispatcher half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`."""

    def _handle_line(self, line: str, sink: Any, *, connection: Any = None) -> str | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sink.emit(
                {
                    "id": None,
                    "event": "error",
                    "error": "invalid_request",
                    "detail": "request line is not valid JSON",
                }
            )
            return None
        if not isinstance(message, dict):
            sink.emit(
                {
                    "id": None,
                    "event": "error",
                    "error": "invalid_request",
                    "detail": "request must be a JSON object",
                }
            )
            return None
        return self._handle_message(message, sink, connection=connection)

    def _handle_message(
        self, message: dict[str, Any], sink: Any, *, connection: Any = None
    ) -> str | None:
        """Answer one frame. Returns :data:`READER_STOP` to stop the stdio reader.

        Validate-then-dispatch: an op the table knows is answered by its method;
        anything else (no op, or an op this runtime does not carry) is a METHOD
        lane frame or an argv request.
        """

        op = message.get("op")
        handler = OP_HANDLERS.get(op) if isinstance(op, str) else None
        if handler is None:
            return self._handle_request(message, sink, connection)
        return handler(self, message, sink, connection)

    def _op_ping(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        sink.emit(self._busy_frame())
        return None

    def _op_hello(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        # The socket lane authenticates BEFORE this dispatcher ever
        # sees a line, so a hello arriving here is a second one (or a
        # stdio client speaking the socket handshake at a pipe that
        # needs no handshake). Typed, and never a second auth path.
        sink.emit(
            {
                "event": "error",
                "error": "unexpected_hello",
                "detail": (
                    "this connection is already established; hello is the "
                    "first line of a SOCKET connection only"
                ),
            }
        )
        return None

    def _op_version(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        from agent_runtime.serve_rpc import registry as serve_rpc

        # Re-askable at any time, and deliberately NOT re-measured:
        # the answer is what code THIS interpreter loaded, which
        # cannot change while it lives. A client comparing against
        # its own install is how "the service is stale" becomes a
        # measurement instead of a theory.
        try:
            from agent_runtime.build_stamp import build_stamp

            version_build = build_stamp().payload()
        except Exception as exc:
            version_build = {
                "commit": None,
                "dirty": None,
                "source": "unknown",
                "reason": f"stamp_failed:{type(exc).__name__}",
                "code_tree": None,
                "code_tree_rule": None,
                "code_tree_reason": f"stamp_failed:{type(exc).__name__}",
            }
        sink.emit(
            {
                "event": "version",
                "schema_version": SERVE_SCHEMA_VERSION,
                "pid": os.getpid(),
                "boot_id": self.boot_id,
                # The transport THIS reply came over — honest per
                # connection, and unchanged for every stdio consumer.
                "transport": (
                    "stdio" if connection is None else connection.transport
                ),
                "runtime_root": self.runtime_root,
                # L-h item 3, re-askable like everything else on this
                # reply: a client that attached hours ago must be able
                # to re-read what it is attached to without a restart it
                # cannot cause.
                "service": self.service,
                "starter_pid": self.starter_pid,
                "build": version_build,
                "auth": self.auth_block,
                # Re-askable like the two blocks above it. Resolved ONCE
                # at boot and echoed, not re-read: an operator rename
                # (``harness gateway id --set-name``) writes the file,
                # but the identity this SESSION greeted with is the one
                # its clients correlate against, and re-reading here
                # would let a frame disagree with the greeting that
                # opened the connection.
                "install": self.install_block,
                "draining": self.drain_state is not None,
                # Additive: what else is attached to this runtime, on
                # the reply a client already asks for.
                "socket": self.socket_block,
                # Re-askable like the socket block above it: a client
                # that reconnects after an operator turned the lane on
                # (or after it failed to come up) must be able to learn
                # that without a restart it cannot cause.
                "gateway": self.gateway_block,
                "connections": self._connections_frame(),
                # Re-askable, like the build stamp beside it and for the
                # same reason: a durable service outlives the install it
                # was started from, so "which methods does the thing I
                # am attached to actually have" must be answerable at
                # any time, not only at the greeting a client may have
                # read hours ago.
                "rpc": serve_rpc.manifest(),
                # Re-askable for the same reason, and honest about the
                # transport it just came over: ``shutdown`` is in the
                # stdio answer and out of the socket one.
                "ops": ops_manifest(
                    transport=(
                        "stdio" if connection is None else connection.transport
                    ),
                    service=self.service,
                ),
            }
        )
        return None

    def _op_connections(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        sink.emit(self._connections_frame())
        return None

    def _op_subscribe(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        lane = message.get("lane", "stream")
        if lane != "stream":
            self._deny_subscribe(sink, connection, lane, "unsupported_lane")
            return None
        if self.drain_state is not None:
            self._deny_subscribe(sink, connection, "stream", "draining")
            return None
        options, refusal = parse_subscribe_options(message)
        if options is None:
            self._deny_subscribe(sink, connection, "stream", refusal)
            return None
        declared_fold_entities = options.declared
        key = self._owner_of(connection)
        hub = self._ensure_stream_hub()
        if hub.has(key):
            # ``at`` separates the two branches that share this reason,
            # and they are different diagnoses: HERE the key was already
            # attached before this frame arrived (a resubscribe, or a
            # subscription the last generation never released), while the
            # ``hub_join`` one below lost a race to a concurrent
            # subscribe. The frame cannot tell them apart — the launcher
            # switches on ``reason`` and that contract is fixed — so the
            # log is the only place the difference can live.
            self._deny_subscribe(
                sink, connection, "stream", "already_subscribed", at="precheck"
            )
            return None
        # Recorded BEFORE ``hub.subscribe``: that call starts the new
        # producer generation, which reads this table to decide what it
        # may promote. Recorded after, this subscriber's declaration
        # would not reach the very producer its own subscribe created.
        with self.lane_lock:
            self.stream_fold_entities[key] = declared_fold_entities
        # THIS subscriber's own answer, not the room's. Per-subscriber
        # promotion made the room's intersection the wrong thing to echo
        # on a PER-CONNECTION ack: what this client will actually be
        # handed a patch for is its own declaration, because the fan-out
        # resolves each envelope against it. The room's floor is still
        # echoed — on the hydrate, which is one frame fanned to everyone
        # and can only honestly carry a value true for all of them.
        #
        # For a single subscriber the two are the same set, which is why
        # the byte-pinned `subscribed.json` capture does not move.
        from agent_runtime.patch_coverage import normalize_fold_entities

        accepted_entities = sorted(
            normalize_fold_entities(declared_fold_entities)
        )
        # The resume decision, taken AFTER this connection's declaration
        # is recorded and BEFORE the hub join, which is the only window
        # where both facts are true: the span is judged against what this
        # client says it folds, and the producer that will feed it can
        # already see the narrowed room (`stream_frames` re-reads the
        # room per drain pass — see `_room` there, which is what makes a
        # restart-free join safe at all).
        resume = self._resolve_resume(options)
        self._join_stream(sink, connection, key, hub, options, accepted_entities, resume)
        return None

    @staticmethod
    def _resolve_resume(options: SubscribeOptions) -> Any:
        """The resume span for a subscribe that asked for one; None otherwise."""

        if not options.resume_requested:
            return None
        from agent_runtime.stream_resume import resolve_stream_resume

        try:
            return resolve_stream_resume(
                options.resume_offset, fold_entities=options.declared
            )
        except Exception as exc:  # noqa: BLE001 - never fatal
            # A resume that cannot be COMPUTED must still leave the
            # client subscribed. The hydrate is the answer to every
            # question this path could have answered more cheaply, so
            # a failure here costs bytes and never a lane.
            from agent_runtime.stream_resume import StreamResume

            return StreamResume(
                honored=False,
                reason=f"resume_failed:{type(exc).__name__}",
            )

    def _on_stream_drop(
        self, sink: Any, connection: Any, key: str, reason: str, stats: dict[str, Any]
    ) -> None:
        # Typed, never silent: an unsubscribed client that was told
        # nothing would keep folding a stream that stopped arriving
        # and believe itself current.
        #
        # The buffer is bounded TWICE — by frame count and by bytes
        # — so the drop has to say WHICH bound tripped and carry
        # both sets of numbers. The hub measures all of this and
        # this frame used to throw it away, reporting a count
        # against a `buffer_limit` read from the CONFIG rather than
        # from the hub (None whenever it was left at the default).
        # A client told only `backpressure` cannot tell one that
        # fell 256 heartbeats behind from one that pinned 32 MiB,
        # which is the difference between resubscribing and fixing
        # its reader.
        self._emit_safely(
            sink,
            {
                "event": "subscription_dropped",
                "lane": "stream",
                "reason": reason,
                "bound": stats.get("drop_bound"),
                "frames_delivered": stats.get("frames_delivered"),
                "frames_discarded": stats.get("frames_discarded"),
                "bytes_discarded": stats.get("bytes_discarded"),
                "buffer_limit": stats.get("frame_limit"),
                "byte_limit": stats.get("byte_limit"),
            },
        )
        self._release_subscription(connection)
        self._service_log(
            {
                "event": "serve_stream_subscription_dropped",
                "boot_id": self.boot_id,
                "connection": key,
                "client": getattr(connection, "client", None),
                "reason": reason,
                "bound": stats.get("drop_bound"),
                "frames_discarded": stats.get("frames_discarded"),
                "bytes_discarded": stats.get("bytes_discarded"),
            }
        )

    def _join_stream(
        self,
        sink: Any,
        connection: Any,
        key: str,
        hub: Any,
        options: SubscribeOptions,
        accepted_entities: list[str],
        resume: Any,
    ) -> None:
        raw_sink = connection.emit if connection is not None else self.frames.emit
        # ONE line per attachment, in the serve child's OWN log. The
        # subscriber census of the 2026-08-17 boot had to be
        # reconstructed from timestamps and still left one rider
        # unidentified, because nothing on any attach path said so —
        # every line in the window described a BUILD, and the builds
        # were what the census was trying to explain (plan EG-2.1).
        from agent_runtime.stream import log_stream_attach

        log_stream_attach(
            op="subscribe",
            purpose="stream_lane",
            connection=key,
            client=getattr(connection, "client", None),
            fold_entities=",".join(accepted_entities) or "-",
        )
        # The ACK precedes the subscription, deliberately. The producer
        # starts pushing the moment ``subscribe`` returns, so acking
        # afterwards would let the hydrate overtake the ack — and a
        # client reading "everything up to my ack is a reply to
        # something else" would discard its own baseline.
        if connection is not None:
            connection.subscribed = True
        ack: dict[str, Any] = {
            "event": "subscribed",
            "lane": "stream",
            "connection": key,
            "buffer_limit": hub.stats().get("buffer_limit"),
            # What the producer will actually promote FOR THIS
            # CLIENT. It used to be able to come back narrower than
            # asked because another subscriber folded less; per
            # subscriber promotion retired that — a room that
            # disagrees now ships both halves and each pump takes
            # its own. So this is the client's own declaration,
            # normalized (an absent one resolving to the historical
            # set, which is the answer it always got).
            "fold_entities": accepted_entities,
        }
        # Present ONLY when a resume was asked for, so the ack a client
        # that asked for nothing receives is byte-for-byte the one it
        # received before this lane existed — which is what keeps the
        # launcher's `subscribed.json` capture from moving.
        if resume is not None:
            ack["resume"] = resume.payload()
        sink.emit(ack)
        honored = resume is not None and resume.honored
        # The catch-up span, on THIS connection's own sink, between the
        # ack and the join. Both edges matter: after the ack, because a
        # client reads everything before its ack as a reply to something
        # else; before the join, because the hub's first frame has to be
        # able to CHAIN onto the last of these.
        #
        # A honoured resume with zero frames is the whole feature working
        # — the client was already current and is sent nothing at all,
        # where it used to be sent the core.
        for frame in resume.frames if honored else ():
            self._emit_safely(sink, frame)
        if not hub.subscribe(
            key,
            sink=raw_sink,
            on_drop=partial(self._on_stream_drop, sink, connection, key),
            # A honoured resume attaches to the RUNNING producer instead
            # of restarting it, and that is the half that actually saves
            # the megabyte: a restart re-baselines the room, so a resume
            # that restarted would hand this client the very hydrate it
            # just proved it did not need — and charge every other
            # subscriber a fresh full core for the privilege.
            #
            # Safe because `stream_frames` re-reads the room per drain
            # pass: a producer that has not been restarted still NOTICES
            # this subscriber's declaration and splits for it. The hub's
            # own floor still starts a producer when none is running, so
            # a resume into an empty room is not a subscription attached
            # to nothing.
            restart_producer=not honored,
            # What this pump resolves a split frame against. Passing the
            # RAW declaration rather than the normalized one keeps
            # "said nothing" distinguishable all the way down, exactly
            # as `parse_fold_entities_option` argues at the other end.
            declared=options.declared,
        ):
            # Lost a race with another subscribe for the same key. Say
            # so rather than leave a client believing it is attached.
            if connection is not None:
                connection.subscribed = False
            # The declaration is deliberately LEFT in place. This branch
            # means another subscribe for the same key won the race, so
            # that key IS attached — dropping its declaration here could
            # only WIDEN the lane under a subscriber that never asked
            # for the wider set, which is the failure direction. A stale
            # entry can only ever narrow, and ``_release_subscription``
            # (or the lane close) clears it.
            self._deny_subscribe(
                sink, connection, "stream", "already_subscribed", at="hub_join"
            )

    def _op_unsubscribe(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        key = self._owner_of(connection)
        with self.lane_lock:
            hub = self.stream_hub
        was_subscribed = hub is not None and hub.has(key)
        self._release_subscription(connection)
        sink.emit(
            {
                "event": "unsubscribed",
                "lane": "stream",
                "connection": key,
                "was_subscribed": was_subscribed,
            }
        )
        return None

    def _op_drain(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        if _is_gateway(connection):
            # A paired device does not get to end a runtime other
            # clients are using — not even at `console` tier, because
            # `drain` is not a level mutation the tier speaks about: it
            # is the lifecycle verb, and its effect is that this process
            # stops and every other attached client is disconnected. A
            # phone deciding that for the desktop it is a guest on is
            # the wrong default, and "restart the runtime from my phone"
            # is a verb somebody can add on purpose later. The refusal
            # mirrors `shutdown`'s rather than inventing a shape, and
            # `ops_manifest(transport="gateway")` already said so, so a
            # well-behaved client never reaches this line.
            sink.emit(
                {
                    "event": "error",
                    "error": "op_not_available_on_gateway",
                    "detail": (
                        "drain ends this runtime for every attached "
                        "client; it is the local console's verb"
                    ),
                }
            )
            return None
        if connection is not None and message.get("force") is not True:
            # The socket lane's second key. `shutdown` is refused there
            # outright because a client does not get to kill a service
            # other clients are using; `drain` is the safe replacement
            # verb, but it still ENDS this process, and any local
            # process holding the root's secret can ask. One explicit
            # field is a trivial cost for an operator and a real
            # barrier against an automated or accidental restart.
            sink.emit(
                {
                    "event": "error",
                    "error": "drain_requires_force",
                    "transport": "socket",
                    "detail": (
                        "drain over the socket ends the service for every "
                        'attached client; resend as {"op":"drain","force":true}'
                    ),
                }
            )
            return None
        # The EFFECTIVE deadline is decided here, server-side, from the
        # client's ask floored by the minimum for the TRANSPORT it came
        # in on. Over stdio the asker owns this process outright and the
        # ask stands as given (the pre-socket contract, untouched); over
        # the socket it is floored, because that asker is any local
        # process holding the root's secret and it is shortening a
        # promise made to work it cannot see.
        effective_minimum = (
            self.drain_socket_minimum_deadline_seconds
            if connection is not None
            else _DRAIN_DEADLINE_FLOOR_SECONDS
        )
        effective_deadline = _drain_deadline_seconds(
            message.get("deadline_seconds"),
            self.drain_deadline_seconds,
            minimum=effective_minimum,
        )
        # ONE critical section for the whole transition. The guard and
        # the install used to be a bare read-modify-write on a closure
        # variable, which was harmless while the only caller was the
        # single stdio reader and became a genuine race the moment N
        # connection threads could ask: two of them could both observe
        # ``None``, both install a ``_DrainState``, and the process
        # would then run two monitors, publish two terminal frames, and
        # split its counters across two objects. The "already draining"
        # answer is decided INSIDE the section that would have
        # installed it, so it cannot be decided against a state a
        # sibling thread is mid-way through replacing.
        with self.inflight_lock:
            existing = self.drain_state
            if existing is None:
                self.drain_state = _DrainState(effective_deadline)
                started = self.drain_state
                pending_at_start = sorted(self.inflight)
        if existing is not None:
            sink.emit(
                {
                    "event": "drain_in_progress",
                    "drain_ms": existing.elapsed_ms(),
                    **existing.counters(),
                }
            )
            return None
        # Stop the delivery drain (and with it the busy pump) the
        # moment we stop accepting work: it forges completed
        # dispatches back into a sender's thread, and doing that to
        # a process on its way down is exactly what the shutdown
        # path already refuses to allow. `drain_progress` frames
        # take over the liveness duty for the rest of the wait.
        self.liveness_stop.set()
        draining_frame = {
            "event": "draining",
            "id": None,
            "pid": os.getpid(),
            "boot_id": self.boot_id,
            "pending": len(pending_at_start),
            "request_ids": pending_at_start,
            "deadline_seconds": started.deadline_seconds,
            # What was ASKED for, beside what was granted: a client
            # that requested 0.05s and got 30 must be able to see that
            # its ask was floored rather than honoured.
            "requested_deadline_seconds": message.get("deadline_seconds"),
            "minimum_deadline_seconds": effective_minimum,
        }
        self.frames.emit(draining_frame)
        # RS-3, and it has to be BEFORE the listeners close: from the
        # next line on this lane refuses new connections, and a
        # contender that read the sidecar in that window used to see a
        # live pid and a port and conclude "serving". The stamp is what
        # lets it conclude "leaving" instead and wait the drain out
        # (``SocketOwnerLock.acquire``) rather than degrade to stdio for
        # the rest of the session — the operator's 2026-09-07 restart.
        if self.socket_lock is not None:
            try:
                self.socket_lock.mark_draining()
            except Exception:
                pass
        # New connections are refused from here on BOTH doors (existing
        # ones stay up to be told how it ends), and every attached
        # client hears it at the same moment the stdio supervisor does.
        for _lane in (self.socket_server, self.gateway_server):
            if _lane is None:
                continue
            try:
                _lane.begin_drain()
            except Exception:
                pass
        self._broadcast_lanes(draining_frame)
        threading.Thread(
            target=self._drain_monitor,
            args=(started,),
            name="harness-serve-drain",
            daemon=True,
        ).start()
        return None

    def _op_stacks(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        # Operator diagnostic: dump every thread's stack as
        # stderr frames (hung-request forensics without py-spy).
        import traceback

        for thread_id, frame in sys._current_frames().items():
            sink.emit(
                {
                    "id": None,
                    "event": "stderr",
                    "line": f"--- thread {thread_id} ---",
                }
            )
            for entry in traceback.format_stack(frame):
                for line in entry.rstrip().splitlines():
                    sink.emit(
                        {"id": None, "event": "stderr", "line": line}
                    )
        sink.emit({"event": "stacks_dumped"})
        return None

    def _op_shutdown(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        if connection is not None:
            # A socket client does NOT get to kill a service other
            # clients are using. `drain` is the multi-client lifecycle
            # verb — it refuses new work, lets in-flight work land, and
            # accounts for both — and `shutdown` stays what it has
            # always been: the verb of the process that owns the pipe.
            sink.emit(
                {
                    "event": "error",
                    "error": "op_not_available_on_socket",
                    "detail": (
                        "shutdown is the stdio owner's verb; use "
                        '{"op":"drain"} to replace the service safely'
                    ),
                }
            )
            return None
        return READER_STOP

    def _op_cancel(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        cancel_id = message.get("id")
        cancel_id = cancel_id.strip() if isinstance(cancel_id, str) else ""
        if not cancel_id:
            sink.emit(
                {
                    "id": None,
                    "event": "error",
                    "error": "invalid_request",
                    "detail": 'cancel needs {"op": "cancel", "id": "<request id>"}',
                }
            )
            return None
        # Scoped to the asker's OWN work: the inflight table is keyed
        # per owner, so one client can neither cancel nor even observe
        # another's request id.
        owner = self._owner_of(connection)
        cancel_key = (
            cancel_id if owner == "stdio" else f"{owner}:{cancel_id}"
        )
        with self.inflight_lock:
            future = self.inflight_futures.get(cancel_key)
            running_request = self.inflight.get(cancel_key)
            known = running_request is not None
        if future is not None and future.cancel():
            with self.inflight_lock:
                self.inflight.pop(cancel_key, None)
                self.inflight_futures.pop(cancel_key, None)
            sink.emit(
                {
                    "id": cancel_id,
                    "event": "exit",
                    "code": 130,
                    "cancelled": True,
                }
            )
        elif running_request is not None and running_request.is_runtime_stream:
            # The state stream is read-only and infinite. Unlike a
            # mutation, it has a cooperative cancellation seam and
            # MUST release its worker when the Launcher reconnects;
            # otherwise four watchdog cycles exhaust the entire
            # serve pool with abandoned streams.
            running_request.cancel_event.set()
            sink.emit(
                {
                    "id": cancel_id,
                    "event": "cancel_accepted",
                    "state": "running",
                }
            )
        else:
            # Already running (uninterruptible) or unknown — the
            # side effect may still land; mutation verbs' own
            # --issued-at replay guard is what makes that safe.
            sink.emit(
                {
                    "id": cancel_id,
                    "event": "cancel_denied",
                    "state": "running" if known else "unknown",
                }
            )
        return None

    def _handle_request(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        """A frame no op claims: the METHOD lane if it is JSON-RPC, else argv."""

        from agent_runtime.serve_rpc.dispatch import is_rpc_frame

        if is_rpc_frame(message):
            self._dispatch_rpc(message, sink, connection)
        else:
            self._dispatch_argv_request(message, sink, connection)
        return None

    def _dispatch_rpc(self, message: dict[str, Any], sink: Any, connection: Any) -> None:
        # ── the METHOD lane ─────────────────────────────────────────────
        #
        # Named JSON-RPC 2.0 methods, BESIDE the argv lane rather than
        # instead of it (decision doc §3 / launcher `fa2226750`). The argv
        # lane below is unchanged and stays the fallback: it has never sent
        # `jsonrpc` or `method`, so nothing that used to reach it can be
        # captured here, and nothing about its frames or exit codes moves.
        #
        # Answered INLINE, like `ping` / `version` / `connections` and
        # unlike an argv request. The pool exists for handlers that block —
        # chat turns, streams — and these methods touch a handful of small
        # JSON files under the office lock and are done in microseconds.
        #
        # It is also why the lane is not refused while draining, and the
        # test that matters here is NOT "is it a read": `runtime.office.
        # upsert` mutates and is still answered. A drain refuses new WORK so
        # in-flight work can land, and the work it is protecting is the kind
        # that can be CUT OFF HALF-DONE — a chat turn whose frames stop
        # mid-stream when the process exits. An inline handler cannot be:
        # `OfficeStore` has written the actor file atomically and released
        # the lock before the ack is emitted, and the replacement runtime
        # reads that same file. Refusing it would fail an operator's drag
        # during a restart to protect against a loss that cannot occur.
        # `version` and `ping` are answered throughout for the same reason.
        # (Pinned by `test_a_write_during_a_drain_lands_because_it_cannot_be
        # _cut_off_half_done` in tests/agent_runtime/test_serve_rpc_office_
        # upsert.py — this is a decision, not an oversight.)
        #
        # The handler is told WHO asked, not just what. All of it comes
        # from this frame's own dispatch — ``sink`` is the stable
        # per-connection writer ``_sink_for`` hands out, and ``connection``
        # is None exactly on stdio. Nothing here is office-specific: it is
        # the argument a method needs before it can push to its caller
        # LATER, which request/response methods simply ignore.
        #
        # ``caller`` is the AUTHORIZATION half (chokepoint plan, Stage A2),
        # and this is the ONE place a live connection becomes one. It is
        # derived from the connection object the transport handed us — never
        # from ``message`` — so no field a client can type reaches the front
        # door's predicate. ``caller_for_connection`` reads the connection's
        # own ``authenticated`` flag, which is set only after
        # ``verify_hello_proof``, so the socket lane's identity is proven
        # here rather than assumed, and stdio's is the process owner's.
        #
        # ``spawn_chat_turn`` and ``spawn_reply`` are the two seams onto the
        # pool (``lanes.ArgvLanes``); each is bound to THIS frame's sink and
        # connection, which is what the closures they replaced captured.
        from agent_runtime.call_authorization import caller_for_connection
        from agent_runtime.serve_rpc.dispatch import handle_request
        from agent_runtime.serve_rpc.protocol import RpcContext, is_deferred

        rpc_frame = handle_request(
            message,
            RpcContext(
                connection_key=getattr(connection, "key", None),
                transport=getattr(connection, "transport", "stdio"),
                emit=sink.emit,
                caller=caller_for_connection(connection),
                spawn_chat_turn=partial(self._spawn_chat_turn, sink, connection),
                spawn_reply=partial(self._spawn_reply, sink),
            ),
        )
        # The ONE frame this lane does not write: the handler took the
        # deferral and the worker owns the reply now. Compared by
        # identity, so no result a handler builds can land here.
        if not is_deferred(rpc_frame):
            sink.emit(rpc_frame)

    def _dispatch_argv_request(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> None:
        if _is_gateway(connection):
            # THE ARGV LANE IS NOT REACHABLE FROM A DEVICE, and this is the
            # load-bearing refusal of the whole stage. The front-door tier
            # gate (`authorize_call`) sits on the METHOD lane; the argv lane
            # runs `harness <anything>` through the CLI dispatcher, where a
            # tier declaration does not exist and every verb is the local
            # operator's. Without this line a `read`-tier device refused
            # `runtime.agent.retire` on the method lane could simply send
            # `{"argv": ["harness", "agent", "retire", ...]}` and be obeyed —
            # the gate would be real and bypassable in one frame.
            #
            # This is a refusal rather than a second gate on purpose. Gating
            # argv would mean deciding a tier for every CLI verb this repo
            # has and keeping that map correct forever, which is the
            # duplicated-authority shape this stack keeps retiring. A device
            # has the method lane, whose tiers ride the manifest it already
            # reads.
            sink.emit(
                {
                    "id": message.get("id") if isinstance(message.get("id"), str) else None,
                    "event": "error",
                    "error": "argv_lane_unavailable",
                    "detail": (
                        "the argv lane is the local console's; a paired "
                        "device calls JSON-RPC methods, whose tiers ride "
                        "the rpc manifest on hello_ok"
                    ),
                }
            )
            return
        rid = message.get("id")
        argv = message.get("argv")
        if (
            not isinstance(rid, str)
            or not rid.strip()
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) for item in argv)
        ):
            sink.emit(
                {
                    "id": rid if isinstance(rid, str) else None,
                    "event": "error",
                    "error": "invalid_request",
                    "detail": 'request needs {"id": "<non-empty>", "argv": ["harness", …]}',
                }
            )
            return
        if self.drain_state is not None:
            self._refuse_while_draining(rid.strip(), sink)
            return
        self._submit_request(
            _ArgvRequest(
                rid.strip(),
                [str(item) for item in argv],
                owner=self._owner_of(connection),
                sink=None if connection is None else sink,
            ),
            sink,
        )

    def _refuse_while_draining(self, rid: str, sink: Any) -> None:
        # Refused, and ACCOUNTED: the count lands on the terminal
        # drain frame, so "the restart dropped work" is a number an
        # operator can read rather than an inference.
        self.drain_state.note_refused()
        sink.emit(
            {
                "id": rid,
                "event": "draining",
                "detail": (
                    "serve is draining and is not accepting new requests; "
                    "reconnect to the replacement runtime"
                ),
                "drain_ms": self.drain_state.elapsed_ms(),
            }
        )
        # Terminal frame too: a client that predates the `draining`
        # event is waiting for an `exit` and would otherwise hang
        # for the life of its request.
        sink.emit(
            {
                "id": rid,
                "event": "exit",
                "code": DRAINING_EXIT_CODE,
                "draining": True,
            }
        )

    def _submit_request(self, request: _ArgvRequest, sink: Any) -> None:
        with self.inflight_lock:
            if request.key in self.inflight:
                sink.emit(
                    {
                        "id": request.rid,
                        "event": "error",
                        "error": "duplicate_request_id",
                        "detail": "a request with this id is still in flight",
                    }
                )
                return
            self.inflight[request.key] = request
        future = self.pool.submit(self._run, request)
        with self.inflight_lock:
            # _run may already have finished and popped the request;
            # only track the future while the request is in flight so
            # the registry cannot leak completed entries.
            if request.key in self.inflight:
                self.inflight_futures[request.key] = future

    def _build_mismatch(self, client_build: Any) -> bool | None:
        """Does the client's build disagree with the code answering it?

        None means NOT COMPARABLE — the client named no build, or this
        runtime could not measure its own. A fabricated ``false`` there
        would answer "you are current" for a runtime that does not know,
        which is exactly the false-all-clear the build stamp exists to
        retire. Prefix comparison so a short hash and a full one agree.
        """

        serve_commit = self.build_block.get("commit")
        if not isinstance(serve_commit, str) or not serve_commit:
            return None
        if not isinstance(client_build, str) or len(client_build.strip()) < 7:
            return None
        claimed = client_build.strip().lower()
        actual = serve_commit.lower()
        return not (
            actual.startswith(claimed) or claimed.startswith(actual)
        )

    def _hello_ok_frame(self, message: dict[str, Any], connection: Any) -> dict[str, Any]:
        """The version handshake, enforced end to end at the door."""
        from agent_runtime.serve_rpc import registry as serve_rpc

        from agent_runtime.serve_socket import HELLO_CONTRACT_VERSION

        return {
            "event": "hello_ok",
            "pid": os.getpid(),
            "boot_id": self.boot_id,
            # L-h item 3. The socket greeting is the ONLY frame an
            # attach-first client reads, so this is where it learns that
            # what it just attached to is a durable service rather than
            # somebody else's stdio child.
            "service": self.service,
            "starter_pid": self.starter_pid,
            # The frame-protocol contract this service speaks. A client that
            # does not recognise it must not proceed on hope.
            "contract": SERVE_SCHEMA_VERSION,
            # Restated from ``server_hello`` so a client that reconnects and
            # reads only the reply still learns which handshake it just
            # completed.
            "hello_contract": HELLO_CONTRACT_VERSION,
            "schema_version": SERVE_SCHEMA_VERSION,
            # Which DOOR this client came through, read off the connection
            # rather than written as a constant. It was "socket" when there
            # was one listener; a device reading "socket" here would be told
            # it is on the local lane, and `ops` below would then advertise
            # a verb this connection is refused.
            "transport": connection.transport,
            "connection": connection.key,
            # D12 — the address this client actually REACHED, read off the
            # accepting socket's own ``getsockname()`` rather than off any
            # candidate list. Every other address this install offers is an
            # inference; this one is a measurement, and it is the only one
            # that already proved a packet got through. Absent when the
            # socket could not answer or the bind is not a dialable
            # address — never a fabricated `0.0.0.0`, which is the thing
            # R-D1 spent a wave removing from every payload.
            **(
                {"reached_at": dict(connection.reached_at)}
                if isinstance(getattr(connection, "reached_at", None), dict)
                else {}
            ),
            "runtime_root": self.runtime_root,
            "build": self.build_block,
            # The socket greeting's half of the install identity. A socket
            # client never reads ``ready``, and from Stage 1 a REMOTE client
            # reads nothing else — which install it just reached has to be
            # answerable from the handshake it already performs, not from a
            # ``runtime_root`` path that means nothing on another machine.
            "install": self.install_block,
            # Visible, never fatal: a client on other code still gets to
            # work, and now KNOWS it is talking to a different build.
            "build_mismatch": self._build_mismatch(connection.client_build),
            "draining": self.drain_state is not None,
            # The socket's half of the method-lane advertisement. A socket
            # client never reads ``ready`` (that frame goes to the stdio
            # owner), so without this it could only learn the method set by
            # asking ``version`` — one extra round trip on every connect,
            # for something the handshake it already performs can carry.
            "rpc": serve_rpc.manifest(),
            # Same argument, the OP lane's half — and the place the
            # advertisements differ per door: ``shutdown`` is refused on
            # both sockets, and ``drain`` additionally on the gateway one.
            # A device learns what it may ask by MEMBERSHIP rather than by
            # trying and reading an error.
            "ops": ops_manifest(
                transport=connection.transport, service=self.service
            ),
            # What the SECOND door is doing, on the greeting a client
            # already reads. For a device this is the lane it is standing
            # on; for the local launcher it is the answer to "is this
            # install reachable from my phone", which nothing else on this
            # frame can give it.
            "gateway": self.gateway_block,
            # The ONE frame in this lane that ever carries a secret, and it
            # carries it exactly once: the credential a pairing code was
            # just redeemed for. Read-and-CLEAR, so the value is gone from
            # the connection before this function returns and cannot reach
            # `payload()`, a log line, or a second reply. Absent on every
            # other handshake, which is every handshake after the first.
            **_pairing_block(connection),
        }

    def _connections_frame(self) -> dict[str, Any]:
        # S2c (R-S2-8). One stat on a read this frame was making anyway.
        # The serve is the process that NOTICES an external write because it
        # is the one that reads repeatedly; a fresh CLI process seeds on its
        # first read and emits nothing, having no baseline to claim a change
        # against.
        if self.store_root_path is not None:
            try:
                from agent_runtime.gateway_peers import note_peer_store_read

                note_peer_store_read(self.store_root_path)
            except Exception:
                pass
        payload: dict[str, Any] = {"event": "socket_connections", "boot_id": self.boot_id}
        with self.lane_lock:
            server = self.socket_server
        if server is None:
            payload["enabled"] = False
            payload["socket"] = self.socket_block
            payload["count"] = 0
            payload["connections"] = []
        else:
            payload["enabled"] = True
            payload.update(server.connections_payload())
        with self.lane_lock:
            gateway = self.gateway_server
        # The gateway lane gets its OWN sub-block rather than having its
        # rows merged into the list above, and the reason is that the
        # top-level keys are per-listener facts: `port`, `host`, `count`,
        # `max_connections`, `rejected_by_reason`. Merged, every one of them
        # would answer for two listeners at once and none of them would say
        # which. Additive and absent-when-off, so every existing consumer of
        # this frame reads exactly the shape it was written against.
        if gateway is not None:
            payload["gateway"] = {
                "enabled": True,
                **gateway.connections_payload(),
            }
        else:
            payload["gateway"] = {"enabled": False, "outcome": self.gateway_block.get("outcome")}
        with self.lane_lock:
            hub = self.stream_hub
        payload["subscriptions"] = (
            hub.stats() if hub is not None else {"subscribers": 0}
        )
        return payload

    def _handle_socket_line(self, line: str, connection: Any) -> None:
        """Every authenticated socket line enters the SHARED dispatcher."""

        self._handle_line(line, self._sink_for(connection), connection=connection)


#: The op table (program rule 12): one method per op, frozen, read by
#: ``_handle_message`` and by nothing else. Its keys are :data:`OPS` — the
#: vocabulary ``ops_manifest`` advertises — plus :data:`HELLO_OP`, the handshake
#: word a socket consumes before this dispatcher exists and that is therefore
#: answered (``unexpected_hello``) but never advertised.
OP_HANDLERS: Final[Mapping[str, Callable[..., str | None]]] = MappingProxyType(
    {
        "cancel": MessageHandling._op_cancel,
        "connections": MessageHandling._op_connections,
        "drain": MessageHandling._op_drain,
        "hello": MessageHandling._op_hello,
        "ping": MessageHandling._op_ping,
        "shutdown": MessageHandling._op_shutdown,
        "stacks": MessageHandling._op_stacks,
        "subscribe": MessageHandling._op_subscribe,
        "unsubscribe": MessageHandling._op_unsubscribe,
        "version": MessageHandling._op_version,
    }
)


def _guard_op_vocabulary() -> None:
    """Fail at IMPORT when the table and the advertised vocabulary disagree."""

    expected = {*OPS, HELLO_OP}
    if set(OP_HANDLERS) != expected:
        raise RuntimeError(
            "serve op table and OPS vocabulary disagree: "
            f"missing={sorted(expected - set(OP_HANDLERS))} "
            f"extra={sorted(set(OP_HANDLERS) - expected)}"
        )


_guard_op_vocabulary()
