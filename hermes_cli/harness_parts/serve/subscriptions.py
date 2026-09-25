"""The stream hub and the socket lanes' plumbing.

Everything here is inert on a stdio-only serve: ``socket_server`` is None, no
connection ever exists, and the stdio path never reaches a branch that touches
it. The ONE stream producer (``_stream_source``) feeds every subscriber on both
lanes; the fold-room derivations decide what that shared producer may promote.
"""

from __future__ import annotations

import threading
from typing import Any

from hermes_cli.harness_parts.serve.frames import _SafeSink

__layer__ = "lanes"

__all__ = ["SubscriptionLanes"]


class SubscriptionLanes:
    """The subscription half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`."""

    def _emit_safely(self, sink: Any, frame: dict[str, Any]) -> None:
        try:
            sink.emit(frame)
        except Exception:
            pass

    def _sink_for(self, connection: Any) -> Any:
        """The STABLE per-connection request sink.

        Stable matters twice: the partial-line buffers in
        ``_LineFrameProxy`` are keyed on the sink's identity, and a sink
        rebuilt per line would split one handler's output across two
        buffers mid-line.
        """

        if connection is None:
            return self.frames
        with self.connection_sinks_lock:
            sink = self.connection_sinks.get(connection.key)
            if sink is None:
                sink = _SafeSink(connection)
                self.connection_sinks[connection.key] = sink
            return sink

    def _owner_of(self, connection: Any) -> str:
        return "stdio" if connection is None else str(connection.key)

    def _deny_subscribe(
        self,
        sink: Any,
        connection: Any,
        lane: Any,
        reason: str,
        **extra: Any,
    ) -> None:
        """Refuse a subscribe: the LINE the operator reads and the FRAME the
        client reads, in that order, from one place.

        Six branches refuse a subscribe and every one of them used to emit
        the frame inline and log nothing. On 2026-09-04 the Windows cockpit's
        stream to the Mac died 7 ms after its subscribe and neither machine
        could say which refusal it was: the reason lived only in the
        launcher's memory and went out with the connection
        (dialable-addresses §8, R-D26). Single-homing both halves is what
        stops a seventh branch from growing the frame and forgetting the
        line — the failure this helper exists to make impossible rather than
        merely unlikely.

        The log goes FIRST, deliberately. The refusals worth reconstructing
        are the ones on a connection that is already going away, and a client
        that never reads its frame is exactly the case the operator has only
        this serve's own log for.

        The frame is unchanged, key for key and in order: the launcher's
        connector switches on ``event``/``reason``, and the stream-lane
        parity and socket-lane tests pin the shape.
        """

        from agent_runtime.stream import log_stream_denied

        log_stream_denied(
            reason=reason,
            lane=lane,
            connection=self._owner_of(connection),
            # The attach line's own additive field, and for its reason: a
            # census of who attached is a census of names, not keys.
            client=getattr(connection, "client", None),
            # WHICH DOOR the refusal came through — the question the field
            # gap was actually about, because a denial on the gateway lane is
            # another machine's cockpit and a denial on the loopback lane is
            # this one's. The tier rides beside it because a paired device
            # has one and nothing else does. Neither names the device: the
            # connection key identifies the connection to a reader of THIS
            # process's log and to nobody else, which is the whole of what
            # this line needs.
            transport=(
                "stdio"
                if connection is None
                else getattr(connection, "transport", None)
            ),
            tier=getattr(connection, "device_tier", None),
            **extra,
        )
        sink.emit(
            {
                "event": "subscribe_denied",
                "lane": lane,
                "reason": reason,
            }
        )

    def _accepted_fold_entities(self) -> Any:
        """What the SHARED producer may promote: the intersection of every
        attached subscriber's declaration.

        One producer feeds N subscribers (``serve_stream_hub``), so a patch
        frame promoted for a client that declared ``office_actor`` would ALSO
        be fanned out to whoever sits next to it, and a subscriber that
        cannot fold that entity answers with a full re-hydrate. Intersection
        is the only rule under which a promotion is safe for everyone in the
        room; a client that declared nothing contributes the historical set,
        so a room of only today's clients accepts exactly today's set.

        The room is BOTH LANES. ``stream_fold_entities`` holds the socket
        stream lane's declarations, but an RPC office subscriber
        (``serve_office_subscriptions``) registers against this same hub and
        is fanned exactly the same frames — it is an attached subscriber in
        every sense that matters here. Reading only the stream table is how
        ``office_actor`` was never once promoted in production: an
        office-only room resolved to the historical default, every office
        write demoted to a full core, and the push lane could emit nothing
        but resync. Both tables are read, so the intersection is taken over
        everyone actually attached.

        **Read LIVE, once per drain pass, not once per producer.** It used to
        be producer-build-time, and the note here said a LEAVE deliberately
        does not re-widen the running producer because re-widening would mean
        RESTARTING it — charging every remaining subscriber a fresh full core
        to buy back a promotion they were living without. That trade is gone:
        ``stream_frames`` takes this derivation as ``fold_room`` and re-reads
        it between drains, so a leave re-widens for free and a JOIN is
        noticed by a producer nobody restarted.

        The second half is what makes a restart-free join safe at all. A
        joiner that folds LESS than the frozen floor would otherwise be
        handed bare patches inside that floor and answer them with
        re-hydrates — the promotion regression this negotiation exists to
        prevent, arriving through the door built to avoid a restart. Read
        live, the next pass sees the narrowed floor and splits instead.

        The window that remains is one drain pass wide: a batch already
        GATED when a declaration lands can still go out bare. It costs the
        joiner one resync and cannot lose an event — the client's
        ``base_offset`` gate refuses a patch it cannot chain — and it is
        named here rather than left for a reader to find.
        """

        from agent_runtime.patch_coverage import accepted_fold_entities

        return accepted_fold_entities(self._room_fold_declarations())

    def _room_fold_declarations(self) -> list[Any]:
        """Every attached subscriber's declaration, both lanes, once.

        Was inline in ``_accepted_fold_entities``; lifted out when a SECOND
        operator over the same room arrived (``_promoted_fold_entities``'s
        union). Two readers assembling the same list from the same two tables
        is how one of them quietly stops reading the office registry, which is
        the bug the intersection already shipped once.
        """

        from agent_runtime.serve_office_subscriptions import OFFICE_SUBSCRIPTIONS

        with self.lane_lock:
            declarations = list(self.stream_fold_entities.values())
        # Taken OUTSIDE ``lane_lock``: the registry holds a lock of its own,
        # and the two are never nested in the opposite order anywhere.
        declarations.extend(OFFICE_SUBSCRIPTIONS.declarations())
        return declarations

    def _promoted_fold_entities(self) -> Any:
        """What the shared producer may promote for SOMEBODY: the UNION.

        R10's assigned consequence, closed here. The intersection above is
        the only safe rule while a fan-out can deliver exactly one shape of a
        frame, and it has a cost the drop-latency tables did not price: a
        Stage 5 phone declaring a narrow chat-first fold DEMOTES the desktop
        beside it to a full ~1 MB core on every office write. Correct, and
        paid by the client that did nothing.

        Now a batch can go out as a ``fold_variants`` envelope — the promoted
        patch and the demoted core together — and each subscriber's pump
        resolves it against its own declaration
        (:func:`agent_runtime.stream.resolve_fold_variant`). So the producer
        promotes whenever ANYBODY can fold, and the demotion is per
        subscriber. The intersection is still derived and still shipped, as
        the ROOM'S FLOOR on the hydrate's echo — a value true for every
        recipient of a frame that is fanned to all of them.

        **With one subscriber these two functions return the same set**, the
        envelope is never built, and the wire does not move by a byte. That
        is not a convention: ``_batch_frames_with_liveness`` takes the
        promoted branch only when the floor REFUSED a batch the union
        accepts, which an equal pair cannot produce.
        """

        from agent_runtime.patch_coverage import union_fold_entities

        return union_fold_entities(self._room_fold_declarations())

    def _room_wants_stale_first(self) -> bool:
        """Does anybody attached to the shared producer PAINT a whole core?

        Same room as ``_accepted_fold_entities`` above — both lanes, read at
        producer-build time — and deliberately the OPPOSITE operator, which
        is the sentence worth keeping. Intersection is right there because a
        PROMOTION must be safe for everyone fanned the frame: one subscriber
        that cannot fold ``office_actor`` makes the promotion wrong for the
        room. Union is right here because the stale-first hydrate is an EXTRA
        frame that a non-painting subscriber merely ignores: the office sink
        discards every row that is not an ``office_actor`` under its own
        workspace, so a stale core costs it a discard and costs the painting
        subscriber beside it the whole point of EG-3.1. One painter is enough;
        a room of office-only sinks answers False, and the boot's single
        stale core stays available for the argv lane the launcher is actually
        on (measured 2026-08-18: the office subscribe attaches 0.1–0.2s
        first, and under the old process-global one-shot it won two boots in
        three and threw the paint away).

        The predicate is membership in ``stream_fold_entities``, not its
        values: that table is the socket STREAM lane's, one entry per
        subscribed connection, and a stream subscriber is by construction a
        consumer of whole hydrate/delta frames. The office registry's
        subscribers contribute False — the union over an empty set of
        painters is False — which is why they are not read here at all.
        """

        with self.lane_lock:
            return bool(self.stream_fold_entities)

    def _stream_source(self, stop: Any = None) -> Any:
        """The shared subscription producer. One per serve, never per client.

        Takes the hub's per-GENERATION stop event (the hub probes for it by
        signature — ``serve_stream_hub._accepts_stop_argument``) and hands it
        to the runtime's own cancellation seam, which is what makes an
        abandoned generation stop before its next frame instead of after it.

        WHY THE SEAM AND NOT A CHECK BETWEEN FRAMES. Checking ``stop`` around
        the ``yield`` here buys NOTHING, and measuring it is the only way to
        know that: ``StreamHub._produce`` already tests ``_should_stop``
        immediately after every ``next()``, so a wrapper that tested the same
        flag at the same moment would be a second copy of a check that had
        already been made. Measured on the real producer at production
        cadences, both spellings left the producer thread alive for 3.08s past
        ``hub.stop(join_timeout=2.0)`` — identical to no fix at all. A fence
        that changes nothing while looking staffed is worse than an absent
        one.

        The park is INSIDE ``next()``: ``stream_frames`` polls its event tail
        every 250ms and only YIELDS on a frame, so a quiet lane surfaces once
        per 5s heartbeat and nothing outside can interrupt the gap. The one
        thing that can is ``request_control``, the seam that module exists for
        — "the read-only ``harness stream`` handler is infinite and must
        release its worker when its consumer disconnects", which is this
        situation exactly, one caller over. Bound to the stop event, every
        ``request_cancelled()`` probe inside the tail loop (its bounded sleep
        slices at 100ms, and the snapshot-build wait beside it) becomes a
        probe of THIS generation's liveness, and the generator returns
        cooperatively at its own next safe point. Same measurement,
        afterwards: ``hub.stop()`` returns with zero producers alive.

        The ``stop`` default keeps the factory callable with no argument (a
        direct caller, and the hub itself if the probe ever stops matching),
        in which case the scope is bound to an event nobody sets and the
        behaviour is exactly what it was.

        An INJECTED ``stream_source_factory`` is deliberately not handed the
        event: its arity contract is the fold-set one negotiated above, and a
        test fake owns its own lifecycle by construction.
        """

        fold_entities = self._accepted_fold_entities()
        # The union, derived beside the floor and with the same lifetime, so
        # a join that widens the room re-derives both together. An INJECTED
        # factory is deliberately not handed it: its arity contract is the
        # one-set one negotiated above, and a test fake that wanted the split
        # lane would be testing the hub rather than itself.
        promote_entities = self._promoted_fold_entities()
        # Derived HERE, beside the fold set, for the same reason and with the
        # same lifetime: ``StreamHub.subscribe`` restarts the producer, so
        # every join re-derives it. That restart is what makes the boot work
        # under the office-first ordering — the first generation is built for
        # an office-only room and takes nothing, and the painting subscriber's
        # own join builds the generation that does take it.
        wants_stale_first = self._room_wants_stale_first()
        if self.stream_source_factory is not None:
            return (
                self.stream_source_factory(fold_entities)
                if self.stream_factory_takes_fold_entities
                else self.stream_source_factory()
            )
        from agent_runtime.request_control import request_cancel_scope
        from agent_runtime.serde import to_jsonable
        from agent_runtime.stream import stream_frames

        # Never-set stand-in for the no-argument call, so the body below has
        # ONE shape rather than a scoped and an unscoped variant to keep in
        # step.
        generation_stop = stop if stop is not None else threading.Event()

        def _generate():
            # The scope is entered on the PRODUCER thread — this body runs
            # there, and a fresh thread starts with an empty context, so
            # nothing of serve's own dispatch is being overwritten and the
            # reset on close lands in the same context that set it.
            with request_cancel_scope(generation_stop):
                # ``caller="hub"``: every build this producer pays for is
                # attributed to the SHARED lane rather than to whichever
                # subscriber happened to trigger the restart — the serve hub
                # is one producer for N subscribers by construction, and a
                # build line naming a subscriber would be a lie about who
                # pays.
                for frame in stream_frames(
                    fold_entities=fold_entities,
                    promote_fold_entities=promote_entities,
                    # The LIVE room, re-read by the producer once per drain
                    # pass. The two sets above still seed the hydrate's echo
                    # (resolved once, so a client's ack and its baseline
                    # cannot disagree); this is what a batch is promoted
                    # against, and it is what lets a restart-free join —
                    # the office lane's, and a watermark resume's — be
                    # noticed by a producer nobody restarted.
                    fold_room=lambda: (
                        self._accepted_fold_entities(),
                        self._promoted_fold_entities(),
                    ),
                    caller="hub",
                    wants_stale_first=wants_stale_first,
                ):
                    # Byte-for-byte the frames ``harness stream`` writes: a
                    # subscriber folds the same hydrate/delta/patch/heartbeat
                    # shapes it already folds, so the socket lane introduces
                    # no second stream contract to keep in sync.
                    yield to_jsonable(frame)

        return _generate()

    def _ensure_stream_hub(self) -> Any:
        with self.lane_lock:
            if self.stream_hub is None:
                from agent_runtime.serve_stream_hub import (
                    DEFAULT_BUFFER_LIMIT,
                    DEFAULT_BYTE_LIMIT,
                    StreamHub,
                )

                self.stream_hub = StreamHub(
                    self._stream_source,
                    buffer_limit=int(self.stream_buffer_limit or DEFAULT_BUFFER_LIMIT),
                    byte_limit=int(self.stream_byte_limit or DEFAULT_BYTE_LIMIT),
                    log=self._service_log,
                )
            return self.stream_hub

    def _release_subscription(self, connection: Any) -> None:
        """A client left. Unsubscribe it, and do NOTHING else.

        Not a cancellation, not a shutdown, not a state change: the runtime
        outliving its clients is the entire point of the durable service,
        and a disconnect that touched backend state would reintroduce the
        per-client lifecycle ownership this workstream exists to retire.
        """

        key = self._owner_of(connection)
        with self.lane_lock:
            hub = self.stream_hub
            # A departed client's fold declaration must not keep narrowing
            # the lane for the clients that remain — the next subscribe
            # re-derives the accepted set from whoever is actually here.
            self.stream_fold_entities.pop(key, None)
        if hub is not None:
            try:
                hub.unsubscribe(key)
            except Exception:
                pass
        # The office lane's keys are NAMESPACED away from `key` (which the
        # stream lane owns), so the unsubscribe above cannot reach them and
        # a departing connection would otherwise leak a subscriber — which
        # would in turn keep a producer alive for nobody.
        from agent_runtime.serve_office_subscriptions import (
            OFFICE_SUBSCRIPTIONS as _office_subs,
        )

        _office_subs.release(key)
        # S2d's lane is namespaced away from both of the above for the same
        # reason the office lane is, so a departing connection would
        # otherwise leave a sink the fan-out keeps writing to — which is how
        # a push registry starts holding a dead socket open.
        from agent_runtime.serve_gateway_peers_rpc import (
            PEER_DIRECTORY_SUBSCRIPTIONS as _peer_dir_subs,
        )

        _peer_dir_subs.release(key)
        if connection is not None:
            connection.subscribed = False
            with self.connection_sinks_lock:
                self.connection_sinks.pop(connection.key, None)

    def _reclaim_abandoned_streams(self, connection: Any) -> int:
        """Cancel the departed connection's infinite ``harness stream``.

        THE POOL IS FOUR WORKERS WIDE and ``harness stream`` is an argv
        request that never returns, so every abandoned one is a worker
        permanently gone. The ``cancel`` op's own comment says what that
        costs — "otherwise four watchdog cycles exhaust the entire serve
        pool with abandoned streams" — and until now the ONLY thing that
        set the event was that op, sent by a launcher that came BACK. A
        client that simply died, or a socket session that closed, left its
        stream running forever, and the next argv request queued behind a
        pool with no free worker and emitted nothing at all. That is the
        measured 2026-08-27 shape: >120s of zero frames for a ``characters
        list``, the identical argv answered in ~6s on a later connection.
        ``agent_runtime.request_control`` already states this as the
        contract — the stream handler "must release its worker when its
        consumer disconnects" — and nothing implemented the disconnect half.

        Deliberately narrower than ``_release_subscription``'s "do NOTHING
        else", and not a softening of it: that rule is about BACKEND state
        surviving its clients, which is the whole durable-service premise.
        This touches no backend state. It reclaims a worker that is
        producing frames for a socket nobody is reading, and it reclaims it
        for exactly the one request shape the cancel path already calls the
        sole safe cooperative exception — read-only, infinite, with a
        polled seam. Chat turns and every mutation are untouched: they stay
        uninterruptible, because a half-applied mutation is worse than a
        held worker and a killed turn is lost recording.
        """

        if connection is None:
            return 0
        owner = self._owner_of(connection)
        with self.inflight_lock:
            abandoned = [
                request
                for request in self.inflight.values()
                if request.is_runtime_stream and request.owner == owner
            ]
        for request in abandoned:
            request.cancel_event.set()
        if abandoned:
            self._service_log(
                {
                    "event": "serve_stream_worker_reclaimed",
                    "boot_id": self.boot_id,
                    "connection": owner,
                    "client": getattr(connection, "client", None),
                    "request_ids": sorted(item.rid for item in abandoned),
                }
            )
        return len(abandoned)

    def _on_connection_closed(self, connection: Any) -> None:
        """The ONE disconnect path: unsubscribe, then reclaim the worker.

        Both doors call this rather than ``_release_subscription`` on its
        own, so a lane added later cannot get one half and not the other —
        the same reasoning ``_broadcast_lanes`` is written down with.
        """

        self._release_subscription(connection)
        self._reclaim_abandoned_streams(connection)

    def _broadcast_lanes(self, frame: dict[str, Any]) -> None:
        """Tell every attached client, on whichever door it came through.

        One call site per announcement rather than two, because the failure
        mode of two is silent and asymmetric: a drain that reached the
        loopback launcher and not the paired phone leaves the phone waiting
        on a runtime that has gone, and nothing anywhere says so. Every
        broadcast in this loop goes through here, so a lane added later is
        added once.
        """

        for server in (self.socket_server, self.gateway_server):
            if server is None:
                continue
            try:
                server.broadcast(frame)
            except Exception:
                pass

    def _close_socket_lane(self, reason: str) -> None:
        """Stop the hub, close every connection, release the ownership lock.

        Idempotent and never raises: it runs on the drain path, the
        shutdown path, and the EOF path, and any of them may be second.
        """

        # Unbound FIRST, so a subscribe racing the drain is refused with a
        # typed `push_lane_unavailable` instead of registering against a hub
        # that is about to be stopped. The registry is process-global and
        # outlives this loop, so leaving it bound would also hand the next
        # serve_loop in the same process a factory closed over a dead lane —
        # which is a test-suite failure mode, not only a production one.
        from agent_runtime.serve_office_subscriptions import (
            OFFICE_SUBSCRIPTIONS as _office_subs,
        )

        _office_subs.bind(None)
        # The three swaps happen together, under the lock, and NOTHING
        # slow happens while it is held: whoever takes a handle owns
        # closing it, and a second caller gets None and does nothing.
        with self.lane_lock:
            hub, self.stream_hub = self.stream_hub, None
            server, self.socket_server = self.socket_server, None
            # The gateway listener is swapped under the SAME lock and by the
            # same closer. It has no lock and no registry entry of its own —
            # it is the loopback lane's dispatcher answering on a second
            # door — so a teardown that closed one and not the other would
            # leave a runtime that has drained still accepting devices.
            gateway, self.gateway_server = self.gateway_server, None
            lock, self.socket_lock = self.socket_lock, None
            self.stream_fold_entities.clear()
        if gateway is not None:
            try:
                gateway.close(reason=reason)
            except Exception:
                pass
        if hub is not None:
            try:
                # One TOTAL budget for the hub, not one per subscriber
                # join: the drain's exit watchdog is already armed, and a
                # teardown that can outlast it is how a drained runtime
                # kept running.
                hub.stop()
            except Exception:
                pass
        if server is not None:
            try:
                server.close(reason=reason)
            except Exception:
                pass
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass
