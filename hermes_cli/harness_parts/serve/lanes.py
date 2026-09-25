"""The pool lanes: one argv request run end to end, and the two seams the METHOD
lane uses to put work on the same pool (a whole chat turn; a deferred reply).

``_run`` is ADMIT (the running stamp and the request's contextvars), then
EXECUTE (the poll-cache replay or the dispatch, under the request's own home
and cancel scope), then REPLY (settle, flush, account, the exit frame). One
implementation for both lanes: an RPC chat turn is the same ``_ArgvRequest``
through the same ``_run``, so the drain ledger counts it exactly as it counts
a local one.
"""

from __future__ import annotations

import time
from typing import Any

from hermes_cli.harness_parts.serve.argv_lane import (
    ArgvRootUnsupported,
    HandlerExit,
    _ArgvRequest,
    _clean_argv_root,
    _system_exit_code,
)
from hermes_cli.harness_parts.serve.constants import _CACHEABLE_ARGV
from hermes_cli.harness_parts.serve.frames import (
    _emit_deferred_reply,
    _request_id,
    _request_sink,
)

__layer__ = "lanes"

__all__ = ["ArgvLanes"]


class _RunState:
    """One argv request's bookkeeping, carried from EXECUTE to REPLY."""

    __slots__ = (
        "cache_age_ms",
        "cache_key",
        "capturing",
        "code",
        "fingerprint",
        "served_from_cache",
        "sink",
    )

    def __init__(self, sink: Any, cache_key: Any) -> None:
        self.sink = sink
        self.cache_key = cache_key
        self.code = 1
        self.fingerprint: tuple | None = None
        self.served_from_cache = False
        self.cache_age_ms = 0
        self.capturing = False


class ArgvLanes:
    """The pool half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`."""

    def _run(self, request: _ArgvRequest) -> None:
        # FIRST act of the worker, before any import or any handler code: from
        # here on the request is RUNNING, and the liveness pump says so instead
        # of reporting it as queued. A stamp taken later would describe a
        # request that is inside its handler as still waiting for a worker,
        # which is the exact confusion this field exists to end.
        request.started_monotonic = time.monotonic()
        token = _request_id.set(request.rid)
        # Answers go back to whoever asked. ``request.sink`` is None on stdio,
        # which leaves the contextvar unset and the proxy on stdout — the
        # pre-socket path, unchanged.
        sink_token = _request_sink.set(request.sink)
        state = _RunState(
            request.sink if request.sink is not None else self.frames,
            _CACHEABLE_ARGV.get(tuple(request.argv)),
        )
        try:
            self._execute_request(request, state)
        finally:
            self._reply_exit(request, state, token, sink_token)

    def _execute_request(self, request: _ArgvRequest, state: _RunState) -> None:
        cached = None
        if state.cache_key is not None:
            state.fingerprint = self.fingerprint()
            cached = self.read_cache.get(
                state.cache_key, state.fingerprint, time.monotonic()
            )
        if cached is not None:
            state.served_from_cache = True
            state.cache_age_ms = int(
                (time.monotonic() - cached.built_monotonic) * 1000
            )
            state.code = cached.code
            for line in cached.lines:
                state.sink.emit({"id": request.rid, "event": "line", "line": line})
            return
        if state.cache_key is not None and state.fingerprint is not None:
            self.stdout_proxy.begin_capture(request.rid)
            state.capturing = True
        self._dispatch_guarded(request, state)

    def _dispatch_guarded(self, request: _ArgvRequest, state: _RunState) -> None:
        from agent_runtime.profile_context import process_home_scope
        from agent_runtime.request_control import request_cancel_scope

        try:
            # THE REQUEST'S OWN HOME, pinned for the width of the dispatch.
            #
            # A ContextVar, so it is per-worker and out-ranks
            # ``os.environ["HERMES_HOME"]`` in ``get_hermes_home()``'s
            # ladder — which is exactly the asymmetry the fix needs. A
            # persona lane that mirrors the env keeps the global channel it
            # genuinely requires (spawns, raw-env plugins), and this lane
            # stops being a passenger on it. See
            # ``profile_context.process_home_scope`` for the measured
            # incident and for what the scope deliberately does not cover.
            #
            # Placed OUTSIDE ``request_cancel_scope`` and around the whole
            # dispatch, not around a resolver: the bled reader was
            # ``agent.charsheet.draft.drafts_dir()``, four call frames deep
            # inside a ``_cmd_*`` handler, and there is no list of such
            # readers worth maintaining — every handler that resolves a home
            # is one. Binding at the seam covers all of them, including the
            # ones added tomorrow.
            #
            # Chat turns arrive here too, on both lanes (the RPC
            # ``spawn_chat_turn`` builds an ``_ArgvRequest`` and submits it
            # to this same ``_run``). This does not disturb them: a turn's
            # own ``persona_profile_context`` binds INSIDE this scope and
            # its ContextVar override nests over this one, so the persona
            # still gets its profile home. What changes is only the turn's
            # STARTING home, which is now this serve's rather than whatever
            # another lane last left in the environment.
            with process_home_scope(self.serve_request_home), request_cancel_scope(
                request.cancel_event
            ):
                if state.cache_key is not None:
                    from agent_runtime.snapshot.context import snapshot_build_context_scope

                    with snapshot_build_context_scope(self.read_build_context):
                        state.code = self.dispatch(list(request.argv))
                else:
                    state.code = self.dispatch(list(request.argv))
        except ArgvRootUnsupported as exc:
            # RL-24, refused before a parser existed. Ordered ABOVE the
            # generic ``SystemExit`` arm because both of RL-24's new types
            # are ``SystemExit`` subclasses — which is what keeps every
            # non-serve caller of ``dispatch_argv`` behaving as it did.
            state.code = _system_exit_code(exc)
            state.sink.emit(
                {
                    "id": request.rid,
                    "event": "error",
                    "error": "argv_root_unsupported",
                    "root": _clean_argv_root(exc.root),
                    "detail": (
                        "the serve argv lane owns the 'harness' parser only; "
                        "this root is a CLI verb the caller runs itself"
                    ),
                }
            )
        except HandlerExit as exc:
            # The handler ran and then exited. Its effect, whatever it was,
            # has already happened — so this frame carries the code and NOT
            # the parser's word, and the launcher treats it as terminal for
            # the attempt rather than as a stale child to replay.
            state.code = exc.handler_code
            state.sink.emit(
                {
                    "id": request.rid,
                    "event": "error",
                    "error": "handler_exit",
                    "code": state.code,
                    "detail": (
                        "the request handler exited; any effect it had "
                        "already happened and must not be replayed"
                    ),
                }
            )
        except SystemExit as exc:  # argparse usage errors land here
            state.code = _system_exit_code(exc)
            if state.code != 0:
                state.sink.emit(
                    {
                        "id": request.rid,
                        "event": "error",
                        "error": "argv_parse_failed",
                        "detail": "argparse rejected the request argv; usage was forwarded as stderr frames",
                    }
                )
        except BaseException as exc:  # dispatch() already enveloped harness errors
            state.sink.emit(
                {
                    "id": request.rid,
                    "event": "error",
                    "error": "dispatch_failed",
                    "detail": f"{type(exc).__name__}",
                }
            )

    def _reply_exit(
        self, request: _ArgvRequest, state: _RunState, token: Any, sink_token: Any
    ) -> None:
        if request.turn_request_id:
            # Gateway Stage 3. The accept receipt learns its worker ended,
            # and the code goes on it.
            #
            # Placed FIRST in the finally, and that position was found by a
            # test rather than reasoned to. It has to be before the exit
            # frame, or a client that reads the exit and immediately retries
            # the same ``turn_request_id`` can observe a receipt still
            # saying ``accepted``. But putting it between the inflight POP
            # and the frame is worse than either: the drain monitor polls
            # the pending set, so a request that is out of ``inflight`` and
            # not yet emitted is a window in which the drain can complete
            # and close the lane UNDER the exit frame — reproduced, as a
            # lost exit, the first time this was written that way. Before
            # the pop, the monitor still counts this request and the window
            # does not exist.
            #
            # Best-effort by contract (``settle_chat_turn`` never raises):
            # the ack it settles is long since on the wire, the receipt's
            # REPLAY answer does not depend on the exit code, and a
            # bookkeeping failure must never take the place of a turn's own
            # exit frame.
            from agent_runtime.chat_turn_reservations import settle_chat_turn

            settle_chat_turn(
                turn_request_id=request.turn_request_id, exit_code=state.code
            )
        self.stdout_proxy.flush_request(request.rid)
        self.stderr_proxy.flush_request(request.rid)
        if state.capturing:
            self.read_cache.put(
                state.cache_key,
                state.fingerprint,
                self.stdout_proxy.end_capture(request.rid),
                state.code,
                time.monotonic(),
            )
        _request_id.reset(token)
        _request_sink.reset(sink_token)
        with self.inflight_lock:
            self.inflight.pop(request.key, None)
            self.inflight_futures.pop(request.key, None)
            # Accounted here rather than by the monitor's before/after
            # arithmetic: the monitor only ever sees the pending SET, so a
            # request that both started and finished during the drain would
            # be invisible to it.
            #
            # And accounted INSIDE the same critical section as the pop,
            # which it did not used to be. With the increment outside, a
            # request sat in a window where it was gone from ``inflight``
            # and not yet in ``completed`` — the monitor could observe an
            # empty pending set and publish ``drain_complete`` with a
            # completion count LOWER than the number of exits it had
            # actually let land (reproduced: 5 reported for 8 exits). The
            # counters are the drain's only evidence, so an under-count
            # reads to an operator as work the restart dropped.
            #
            # Lock order is inflight_lock → _DrainState.lock, and it is the
            # only nesting of the two: every other site takes them one after
            # the other, never one inside the other.
            if self.drain_state is not None:
                self.drain_state.note_completed()
        exit_frame: dict[str, Any] = {
            "id": request.rid,
            "event": "exit",
            "code": state.code,
        }
        if state.served_from_cache:
            exit_frame["served_from_cache"] = True
            exit_frame["cache_age_ms"] = state.cache_age_ms
        state.sink.emit(exit_frame)

    def _spawn_chat_turn(
        self,
        sink: Any,
        connection: Any,
        request_id: str,
        argv: list[str],
        turn_request_id: str,
    ) -> None:
        """The METHOD lane's chat-turn seam, bound per frame to its sink and connection.

        ``spawn_chat_turn`` is the ONE exception to "answered inline", and it
        proves the rule rather than breaking it: the chat methods do not run
        their turn on the dispatcher, they put it on the pool through this seam
        and ack. Everything the argv lane does for a chat turn happens here too —
        the same ``_ArgvRequest``, so ``is_chat_turn`` is derived from the same
        ``_CHAT_TURN_COMMANDS`` shapes and the drain ledger counts an RPC turn
        exactly as it counts a local one; the same inflight table, so
        ``connections`` and cancel see it; the same ``_run``, so the frames, the
        exit code and the completion accounting are one implementation. A serve
        that recycled mid-turn because the turn arrived on the other lane is the
        exact defect ``held_by_chat_turns`` exists to prevent.
        """

        from agent_runtime.chat_turn import ChatTurnSpawnRefused

        if self.drain_state is not None:
            # And ACCOUNTED, exactly as an argv refusal is: a drain that
            # turned a remote turn away is a number on the terminal
            # frame rather than an inference. The method lane keeps
            # answering during a drain for handlers that cannot be cut
            # off half-done; a chat turn is the work that CAN be, which
            # is what the drain is for.
            self.drain_state.note_refused()
            raise ChatTurnSpawnRefused(
                "draining",
                "serve is draining and is not accepting new chat turns; "
                "reconnect to the replacement runtime and retry with the "
                "same turn_request_id",
            )
        chat_request = _ArgvRequest(
            request_id,
            [str(item) for item in argv],
            owner=self._owner_of(connection),
            sink=None if connection is None else sink,
            turn_request_id=turn_request_id,
        )
        with self.inflight_lock:
            # The id is server-minted and random, so a collision here is
            # not a client behaviour — it is a bug, and it refuses
            # rather than silently replacing a live request's entry.
            if chat_request.key in self.inflight:
                raise ChatTurnSpawnRefused(
                    "request_id_collision",
                    "a request with this server-minted id is already in flight",
                )
            self.inflight[chat_request.key] = chat_request
        chat_future = self.pool.submit(self._run, chat_request)
        with self.inflight_lock:
            if chat_request.key in self.inflight:
                self.inflight_futures[chat_request.key] = chat_future

    def _spawn_reply(self, sink: Any, build: Any) -> bool:
        """The SECOND seam onto the pool, and the general one.

        A chat turn is a whole request handed over and acked; this is the TAIL
        of one request handed over — a callable that returns the very frame the
        handler would have returned — so the method lane keeps its
        request/response shape and only the thread that finishes the work moves.
        ``runtime.media.get``'s proxy arm is the first caller: it dials another
        machine, and a machine that is switched off parked the dispatcher for
        the dial's whole timeout with every other request from that client
        queued behind it.

        Refused while DRAINING, which puts the deferral on the same side of the
        drain as the pool it uses: a drain is waiting for the pool to empty, and
        handing it new work is the opposite of that. The handler answers inline
        instead — the pre-existing behaviour, for the seconds a drain lasts.
        """

        if self.drain_state is not None:
            return False
        try:
            self.pool.submit(_emit_deferred_reply, build, sink)
        except RuntimeError:
            # The pool is already shutting down. False, so the handler
            # answers on this thread rather than a client waiting for a
            # frame no worker will ever write.
            return False
        return True
