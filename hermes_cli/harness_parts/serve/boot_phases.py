"""The boot steps between the stdio swap and ``ready``, in the order
``ServeSession._boot_and_serve`` calls them: the store root and the three
greeting blocks (build, auth, install), the loopback socket lane, the gateway
lane, the registry row, the service stderr log, the boot prunes, the end-reason
recorder, the pre-ready sweeps, and the ``ready`` frame itself.

Every step is best effort by contract except the socket lane's one exit (a
``--service`` that lost the ownership race serves nothing): bookkeeping must
never be the thing that fails a boot.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

from hermes_cli.harness_parts.serve.boot import _maybe_inject_boot_fault, _repoint_logging_root_stderr
from hermes_cli.harness_parts.serve.constants import SERVE_SCHEMA_VERSION
from hermes_cli.harness_parts.serve.end_reason import (
    _install_console_ctrl_reason_handler,
    _install_signal_reason_handlers,
    _ServeEndReason,
)
from hermes_cli.harness_parts.serve.gateway_listener import (
    gateway_block_when_no_listener,
    start_gateway_listener,
)
from hermes_cli.harness_parts.serve.manifest import ops_manifest

__layer__ = "lanes"

__all__ = ["BootPhases"]


class BootPhases:
    """The boot half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`."""

    def _boot_store_and_identity(self) -> None:
        self.store_root_path: Any = None
        try:
            from agent_runtime import paths as _paths

            self.store_root_path = _paths.store_root()
            self.runtime_root = str(self.store_root_path)
        except Exception:
            self.store_root_path = None
            self.runtime_root = None
        self.timeline.mark("store_root_ms")
        # ── Durable-service foundations (slice 2) ───────────────────────────
        #
        # These three run BEFORE ``ready`` because ``ready`` is the frame that
        # carries them: a client that has to ask a second question to learn
        # what code it just connected to has a window in which it does not
        # know, and windows like that are how a stale service serves a whole
        # session before anyone notices.
        #
        # 1. WHICH CODE. Today serve is a per-client child, so a launcher
        #    restart picks up landed fixes for free and nobody ever had to
        #    ask. A durable service silently pins last week's code instead —
        #    the shape of the dispatch dead-flag-proxy incident, which ran
        #    green for a week. Resolved once per process and cached.
        try:
            from agent_runtime.build_stamp import build_stamp

            self.build_block = build_stamp().frame_payload()
        except Exception as exc:  # an instrument must never take the boot down
            self.build_block = {
                "commit": None,
                "dirty": None,
                "source": "unknown",
                "resolved_at": None,
                "reason": f"stamp_failed:{type(exc).__name__}",
                # RS-6's keys are present on the failure arm too, and BOTH are
                # null: a reader that fell back to the commit comparison must
                # be able to tell "this hermes has no code tree" from "this
                # hermes predates the key", and an absent key says the second.
                # The rule is null because the module that owns it is exactly
                # what did not import.
                "code_tree": None,
                "code_tree_rule": None,
                "code_tree_reason": f"stamp_failed:{type(exc).__name__}",
            }
        # 2. THE SECRET. Unwired to any transport (stdio needs none), minted
        #    now so the socket slice starts with a lock already on the door
        #    rather than shipping open. The frame carries the POSTURE only —
        #    the token value must never appear in a frame, a log, or an event.
        self.auth_block: dict[str, Any] = {"token_file": "error:root_unresolved"}
        if self.store_root_path is not None:
            try:
                from agent_runtime.serve_auth import ensure_token

                self.auth_block = ensure_token(self.store_root_path).payload()
            except Exception as exc:
                self.auth_block = {"token_file": f"error:{type(exc).__name__}"}
        # 2b. WHICH INSTALL. The secret above says a caller MAY talk to this
        #     runtime; this says WHICH runtime it reached. Two facts, two
        #     mechanisms, deliberately — an id that both names and authorises is
        #     how "I know your install id" becomes "I am you", and the gateway
        #     plan's device/peer tiers (Stage 1/6) hang their credentials off the
        #     auth block, never off this one. Nothing here is secret: the id and
        #     the operator-set name travel in the clear on every greeting.
        #
        #     Mint-iff-absent, per root, and NOT the monitoring/telemetry
        #     ``install_id``s — those are rotatable and home/db-scoped, and the
        #     argument is written out in ``agent_runtime/gateway_identity.py``.
        self.install_block: dict[str, Any] = {
            "install_id": None,
            "display_name": None,
            "state": "error:root_unresolved",
        }
        if self.store_root_path is not None:
            try:
                from agent_runtime.gateway_identity import ensure_install_identity

                self.install_block = ensure_install_identity(self.store_root_path).frame_payload()
            except Exception as exc:
                self.install_block = {
                    "install_id": None,
                    "display_name": None,
                    "state": f"error:{type(exc).__name__}",
                }

    def _boot_socket_lane(self) -> int | None:
        """Bind the loopback lane when asked. Returns an exit code only when a
        ``--service`` starter lost the ownership race and must serve nothing."""

        # 3. THE TRANSPORT (slice 3). One serve per root owns the socket lane,
        #    decided by an OS-held exclusive lock rather than by who booted
        #    first: two serves against one root is a real, ordinary concurrency
        #    (a launcher restart overlaps its replacement), and "connect to the
        #    service for root X" must have exactly one answer. The loser keeps
        #    serving stdio and SAYS so on the ready frame — a socket that
        #    silently never came up is indistinguishable from one that is
        #    broken.
        #
        #    Bound here, BEFORE the registry entry and the ready frame, so both
        #    can carry the real port; accepting starts later, once the request
        #    pool exists (see ``start_accepting`` below). A client that connects
        #    in between waits in the listen backlog, which is what a backlog is
        #    for.
        self.socket_block: dict[str, Any] = {"outcome": "disabled"}
        self.socket_transport = "stdio"
        if not (self.socket_lane and self.store_root_path is not None):
            return None
        try:
            from agent_runtime.serve_socket.owner_lock import SocketOwnerLock

            # ``log`` is what makes R-L2's takeover an OPERATOR-visible
            # event rather than a field on a frame nobody kept: the
            # ``serve_socket_owner_takeover`` line lands on the same service
            # log as ``serve_instances_pruned``, correlatable by boot_id
            # against this boot's ready frame.
            self.socket_lock = SocketOwnerLock(self.store_root_path, log=self._service_log)
            lock_result = self.socket_lock.acquire()
            if lock_result.acquired:
                self._open_socket_lane(lock_result)
                return None
            self.socket_block = lock_result.payload()
            if self.service:
                return self._leave_as_losing_service(lock_result)
        except Exception as exc:
            # A transport that failed to come up must not take the runtime
            # with it: stdio still works, and the typed outcome is how an
            # operator learns the socket did not.
            try:
                if self.socket_lock is not None:
                    self.socket_lock.release()
            except Exception:
                pass
            self.socket_server = None
            self.socket_lock = None
            self.socket_block = {"outcome": f"error:{type(exc).__name__}"}
        return None

    def _open_socket_lane(self, lock_result: Any) -> None:
        """This serve won the per-root lock: bind the lane and advertise it."""

        from agent_runtime.config import harness_root_config_path
        from agent_runtime.local_llama_adapter.rpc import bind as bind_local_llama
        from agent_runtime.serve_auth import read_token as _read_serve_token
        from agent_runtime.serve_socket.vocabulary import SOCKET_HOST
        from agent_runtime.serve_socket.server import ServeSocketServer

        bind_local_llama(self.store_root_path, harness_root_config_path())
        self.local_llama_bound_root = self.store_root_path
        # A corrupt optional discussion store must not take the
        # ordinary native socket/chat lane down with it.
        try:
            from agent_runtime.discussions.service import bind as bind_discussions
            from agent_runtime.profile_home import get_hermes_head_home
            self.discussion_owner = bind_discussions(
                self.store_root_path, get_hermes_head_home(), self.install_block["install_id"])
        except Exception:
            import logging as _discussion_logging
            _discussion_logging.getLogger(__name__).warning(
                "discussion runtime unavailable; ordinary chat remains enabled",
                exc_info=True,
            )
        store_root_path = self.store_root_path
        self.socket_server = ServeSocketServer(
            store_root_path,
            boot_id=self.boot_id,
            # Bound methods of this session: the pool and the drain state they
            # need exist by the time the accept loop can call them, which is
            # after ``start_accepting`` — the same reason the closures these
            # replaced were safe to hand over late-bound.
            dispatch_line=self._handle_socket_line,
            hello_payload=self._hello_ok_frame,
            # THIS root's secret, read per handshake and used as an
            # HMAC key over a per-connection nonce. It is the key
            # and never the message, so nothing derived from it and
            # put on the wire discloses it — which is the whole
            # reason the hello stopped carrying the token at all.
            token_provider=lambda: _read_serve_token(store_root_path),
            frame_contract=SERVE_SCHEMA_VERSION,
            on_disconnect=self._on_connection_closed,
            log=self._service_log,
        )
        port = self.socket_server.bind()
        self.socket_lock.publish_owner(
            {
                "pid": os.getpid(),
                "boot_id": self.boot_id,
                "host": SOCKET_HOST,
                "port": port,
                "started_at": self.socket_server.started_at,
                "store_root": self.runtime_root,
            }
        )
        self.socket_transport = "stdio+socket"
        self.socket_block = {
            "outcome": "listening",
            "host": SOCKET_HOST,
            "port": port,
            "started_at": self.socket_server.started_at,
        }
        # R-L2. Present only when this boot inherited a PROVEN-dead
        # owner's lane, which makes it the receipt for a recovered
        # restart: a launcher that respawned a serve and sees
        # ``took_over_from`` naming the pid it killed knows the
        # replacement is the socket owner, rather than inferring it
        # from the absence of ``lock_held_by``.
        if lock_result.took_over_from is not None:
            self.socket_block["took_over_from"] = lock_result.took_over_from
            self.socket_block["owner_started_at"] = lock_result.owner_started_at

    def _leave_as_losing_service(self, lock_result: Any) -> int:
        """Name the winner and exit 0: a ``--service`` that lost the race serves NOTHING.

        L-h item 2, and F1's explicit requirement. A stdio serve that loses this
        lock has a job to do and keeps doing it — that is the pre-existing
        contract and it is untouched. A SERVICE that lost it does not: it was
        asked to be "the runtime for this root", there already is one, and the
        only thing it could do by carrying on is become a second execution
        process against the same store — an extra stdio executor nobody
        discovers, nobody drains, and nobody knows to stop. So it names the
        winner and leaves, before the request pool, the registry row and the
        ready frame exist, which is what "serves nothing" means literally.

        Exit code 0: losing this race is the ORDINARY outcome of two starters (a
        launcher that respawned, two launchers on one machine), and the caller's
        next act is to re-read the registry and attach to the winner — RL-4. A
        nonzero code would read as "the runtime failed to start" for a root that
        has a healthy runtime.

        Both a FRAME and a service-log line, because the two have different
        audiences and either can be the only one present: a launcher that
        spawned us over pipes reads the frame, and a launcher that spawned us
        DETACHED (which is the normal case — RL-2) has no stdout to read at all.
        """

        from agent_runtime.serve_socket.owner_lock import read_socket_owner

        try:
            owner_record = read_socket_owner(self.store_root_path)
        except Exception:
            owner_record = {}
        owner_port = owner_record.get("port")
        exists = {
            "event": "serve_owner_exists",
            # The WINNER's pid, from the sidecar — not ours.
            "pid": lock_result.pid,
            "port": owner_port if isinstance(owner_port, int) else None,
            "boot_id": self.boot_id,
            "starter_pid": self.starter_pid,
            "runtime_root": self.runtime_root,
            "owner_started_at": lock_result.owner_started_at,
            "socket": self.socket_block,
        }
        self._service_log(exists)
        self.frames.emit(exists)
        try:
            self.socket_lock.release()
        except Exception:
            pass
        return 0

    def _boot_gateway_lane(self) -> None:
        from agent_runtime.serve_socket.vocabulary import SOCKET_HOST
        # 3b. THE SECOND DOOR (remote-gateway Stage 1). Off unless an operator
        #     names an interface in `remote_gateway.listen`, and the block SAYS
        #     which of those it is either way — `disabled` is a different fact
        #     from `error:port_in_use`, and a listener that silently failed to
        #     come up while the config said it should is the false-all-clear
        #     shape the `socket` block beside it already exists to retire.
        #
        #     Three things differ from the lane above and nothing else does: the
        #     bind (an operator-chosen interface and usually a fixed port), the
        #     credential (per DEVICE — `serve_gateway_auth`, not the per-root
        #     token), and the link (TLS, R1). Same dispatcher, same ops, same
        #     stream hub, same drain.
        # R-IP16 / R-S2-1: the capability list rides EVERY outcome, including
        # ``disabled``. "Does this hermes know the verb" and "is the LAN door
        # open" are different questions, and S3's request loop asks the first
        # over loopback argv against a serve that may legitimately have the
        # second answered ``no``. Stamped in exactly two places — here, and on
        # the listener's own block below — so ``ready`` / ``hello_ok`` /
        # ``version`` are untouched and cannot disagree.
        #
        # R-L1: THE BLOCK IS NEVER SILENT AND NEVER GUESSES. The listener can
        # only be opened by the serve that owns the loopback lane (one process
        # per root binds the operator's port, or the second one loses that race
        # too), so every failure of the lane above is also a boot with no
        # listener — and until 2026-09-04 all of them said ``disabled``, the same
        # word as "the operator never asked". That is the sentence the launcher
        # could not read: it had just WRITTEN ``remote_gateway.listen`` and
        # respawned, and the greeting told it the feature was off.
        # ``gateway_block_when_no_listener`` splits those apart.
        from agent_runtime.gateway_capabilities import with_capabilities

        self.gateway_block: dict[str, Any]
        if self.socket_server is not None and self.store_root_path is not None:
            self.gateway_server, self.gateway_block = start_gateway_listener(
                self.store_root_path,
                boot_id=self.boot_id,
                display_name=self.install_block.get("display_name"),
                dispatch_line=lambda line, connection: self._handle_socket_line(
                    line, connection
                ),
                hello_payload=lambda message, connection: self._hello_ok_frame(
                    message, connection
                ),
                on_disconnect=lambda connection: self._on_connection_closed(connection),
                log=self._service_log,
                frame_contract=SERVE_SCHEMA_VERSION,
            )
            self.gateway_block = with_capabilities(self.gateway_block)
            if self.gateway_server is not None and self.socket_lock is not None:
                # RE-PUBLISH the ownership sidecar, now that the second door has
                # a real port. The first publish happens before this block on
                # purpose (the loopback port must be advertised as early as
                # possible, and the gateway lane must not be able to delay it),
                # so the gateway endpoint can only arrive in a second write.
                #
                # It has to arrive somewhere: `harness gateway pair` runs in the
                # operator's shell, not in this process, and the pairing payload
                # it prints has to name a port a phone can dial. With an
                # ephemeral port that number exists nowhere else — the registry
                # entry carries the LOOPBACK port, and the `ready` frame goes to
                # a launcher rather than to a terminal.
                self.socket_lock.publish_owner(
                    {
                        "pid": os.getpid(),
                        "boot_id": self.boot_id,
                        "host": SOCKET_HOST,
                        "port": self.socket_server.port,
                        "started_at": self.socket_server.started_at,
                        "store_root": self.runtime_root,
                        # Additive: a reader that predates this lane finds the
                        # keys it knows, unchanged and in the same places.
                        "gateway": {
                            "host": self.gateway_block.get("host"),
                            "port": self.gateway_block.get("port"),
                            "cert_fingerprint": self.gateway_block.get("cert_fingerprint"),
                        },
                    }
                )
        else:
            self.gateway_block = with_capabilities(
                gateway_block_when_no_listener(
                    self.socket_block, root_resolved=self.store_root_path is not None
                )
            )
        # S2c. ONE announce per boot, on a background thread, telling every
        # usable peer where this install is now reachable and what certificate
        # it presents. It is the push that makes a machine which changed
        # networks findable again without an operator re-running a ceremony they
        # had no reason to suspect was needed — the far side's cache endpoints
        # are tried before its pairing-time ones (`dial_peer`), so the new
        # address wins on the next call.
        #
        # Once per boot and never on a timer: this is news, and news that
        # repeats is a poll wearing a push's clothes. A peer that was off simply
        # rests `unreachable` in our cache until its own next hello refreshes
        # both sides.
        if self.gateway_block.get("outcome") == "listening" and self.store_root_path is not None:
            try:
                from agent_runtime.gateway_announce import announce_in_background
                from agent_runtime.gateway_endpoints import (
                    _candidate_endpoints,
                )

                announce_in_background(
                    self.store_root_path,
                    {
                        "endpoints": _candidate_endpoints(self.store_root_path),
                        "cert_fingerprint": self.gateway_block.get("cert_fingerprint"),
                        "display_name": self.install_block.get("display_name"),
                    },
                )
            except Exception:  # noqa: BLE001 — courtesy channel, never the boot
                pass

    def _boot_register_instance(self) -> None:

        # 4. DISCOVERY. Multiple runtime roots legitimately coexist on this
        #    machine (QA lanes, isolated worktree roots), and until now
        #    "how many serves are running against this root, on what code"
        #    had no answer at all. The entry is removed on every clean exit
        #    (shutdown AND drain); a crash leaves it, which is why liveness is
        #    proven at READ time and never trusted from the file.
        #
        #    The socket fields ride the SAME entry (additive): a client
        #    discovering "the service for root X" reads the port from the
        #    instance whose liveness the registry has just classified, rather
        #    than from a second file with its own staleness story.
        self.instance_block: dict[str, Any] = {"outcome": "error:root_unresolved"}
        if self.store_root_path is not None:
            try:
                from agent_runtime.serve_registry import register_serve_instance

                # WHICH HOME this child resolved (D-3). store_root answers a
                # DIFFERENT question — one root is shared by serves on
                # different profile homes — so from outside the process
                # nothing could say which home a running serve was on.
                # Resolved HERE, not in the registry: that module stays free
                # of hermes_constants and unit-testable against a string.
                # A resolution failure degrades to None (written as null);
                # bookkeeping must never be the thing that fails a boot.
                try:
                    from hermes_constants import get_hermes_home

                    resolved_home: str | None = str(get_hermes_home())
                except Exception:
                    resolved_home = None
                self.instance_block = register_serve_instance(
                    self.store_root_path,
                    transport=self.socket_transport,
                    build=self.build_block,
                    boot_id=self.boot_id,
                    port=self.socket_server.port if self.socket_server is not None else None,
                    socket_started_at=(
                        self.socket_server.started_at if self.socket_server is not None else None
                    ),
                    hermes_home=resolved_home,
                    # L-h item 3. The row is what an attach-first client reads
                    # BEFORE it dials anything, so "is this runtime going to
                    # outlive the launcher that started it" has to be answerable
                    # from the file — not only from a greeting you get after
                    # connecting.
                    service=self.service,
                    starter_pid=self.starter_pid,
                ).payload()
            except Exception as exc:
                self.instance_block = {"outcome": f"error:{type(exc).__name__}"}

    def _arm_service_stderr_log(self) -> None:
        # ── RL-19: the service runtime keeps its own stderr ─────────────────
        #
        # BEFORE the RL-16 block below, for two reasons that are both ordering:
        # the sidecar prune down there now floors this family too, and this
        # boot's own log has to exist by then so that it is the NEWEST of its
        # family and can never be the file the prune picks; and an arming that
        # happens after the recorder would miss nothing but is harder to read.
        #
        # And BEFORE the row prune below, which is RO-3's ordering: the prune
        # now says row by row what it removed and what it refused, and on a
        # ``--service`` runtime the only place that can be READ is this file.
        # Armed after it, the boot prune's verdicts would go to the DEVNULL
        # stderr RL-17 hands a service — which is the exact silence RO-3 exists
        # to end. It is safe this early for the same reason the prune is: the
        # log is not a registry row (``_NON_ROW_SUFFIXES``), so no scan and no
        # prune between here and there can see it.
        #
        # ``service`` only. A serve started the old way is a child whose parent
        # is holding its stderr pipe open and reading it as frames — moving that
        # output into a file would take it away from the process that asked for
        # it (pinned by the non-service arm of the child e2e).
        if self.service and self.store_root_path is not None:
            try:
                from agent_runtime.serve_registry import open_serve_stderr_log

                self.service_stderr_log = open_serve_stderr_log(
                    self.store_root_path, boot_id=self.boot_id, build=self.build_block
                )
            except Exception:  # pragma: no cover - the opener never raises
                self.service_stderr_log = None
            if self.service_stderr_log is not None:
                self.stderr_proxy.set_mirror(self.service_stderr_log)
                _repoint_logging_root_stderr(
                    self.service_stderr_log,
                    previous=(self.original_stderr, sys.__stderr__, self.stderr_proxy),
                )
                # What ``sys.stderr`` becomes again when this loop unwinds. The
                # mirror above covers the loop's own lifetime; this covers
                # everything written to stderr AFTER it — an interpreter-level
                # message, a late ``atexit`` hook, a warning during teardown.
                # Named as defence and not as the traceback's route: the
                # traceback is written explicitly by the uncaught arm below,
                # because nothing in this process prints one (see there).
                self.original_stderr = self.service_stderr_log

    def _prune_stale_records(self) -> None:
                # Never closed on purpose: the writes worth having are the ones
                # made on the way down, and the OS closes it when the process
                # ends. Line-buffered, so nothing is owed a flush.

        if self.store_root_path is not None:
            # ...and, having registered and armed the log, drop the records that
            # are provably wreckage. AFTER registration on purpose: this serve's
            # own entry then exists and classifies `live`, so the sweep can
            # never be the thing that removes it.
            #
            # WHY THIS DOES NOT CONTRADICT "listing never prunes"
            # ---------------------------------------------------
            # serve_registry's docstring argues, correctly, that a READ must not
            # destroy the evidence it is reporting: an operator asking "why do I
            # have four serves" must see the wreckage. A boot is not that
            # moment. It is a WRITE moment - the line above just created a file
            # in this directory - and, decisively, the evidence does not vanish:
            # prune_stale_serve_instances returns pid, boot_id, path,
            # classification and reason for every record, deleted and kept
            # alike, and that report goes onto the service log correlatable by
            # boot_id against this boot's ready frame. The wreckage moves from a
            # directory nobody reads into a log the operator already reads.
            #
            # It is needed because clean exit removes its own entry and the
            # crash path deliberately does not - and the launcher's boot hygiene
            # sweep taskkill /F's orphan serves, which is a crash by
            # construction: those serves are never given the chance to
            # unregister. Measured on the operator's runtime: 14 serve boots in
            # ~19 h left 2 records behind (13856, 35080), while a third (21440)
            # exited cleanly and removed its own.
            #
            # SCOPE, stated plainly: this is tidiness plus forensics, not a
            # correctness fix. The leftover records are already harmless -
            # resolve_socket_target returns only rows classified `live`, the
            # launcher never reads this directory, and it is excluded from every
            # freshness fingerprint (see the module docstring).
            #
            # What is pruned is NOT widened here: stale_dead_pid only, which is
            # the registry's own rule. stale_recycled_pid names a live process
            # this registry no longer understands, and `unknown` means a probe
            # could not answer - deleting on a failed probe is how a sweep
            # removes a RUNNING service's record, and this repo has already been
            # bitten once by a recycled pid killing an unrelated process.
            #
            # Silent when it found nothing to do: a line every boot saying it
            # deleted zero files is the kind of noise that trains an operator to
            # stop reading the channel this report needs to be seen on.
            #
            # RO-3 keeps that rule and adds the row-level story the aggregate
            # could not carry: ``emit=_service_log`` writes one
            # ``serve_registry_pruned`` line per row REMOVED or REFUSED, at the
            # instant it happens, on the same channel and joinable by the same
            # ``boot_id``. A live row — this boot's own entry, every time —
            # writes nothing, so a quiet machine's log stays quiet.
            try:
                from agent_runtime.serve_registry import (
                    prune_stale_serve_instances,
                )

                prune_report = prune_stale_serve_instances(
                    self.store_root_path, emit=self._service_log, boot_id=self.boot_id
                )
                if prune_report.get("deleted_count") or any(
                    "error" in row for row in prune_report.get("kept") or ()
                ):
                    self._service_log(
                        {
                            "event": "serve_instances_pruned",
                            "boot_id": self.boot_id,
                            "pid": os.getpid(),
                            **prune_report,
                        }
                    )
            except Exception:
                # Bookkeeping must never take a boot with it.
                pass

    def _arm_end_reason(self) -> None:

        # ── RL-16: arm the end-reason recorder ──────────────────────────────
        #
        # HERE, and not earlier, because the recorder writes into the directory
        # the row above just created — and not later, because from the ready
        # frame onward this runtime can be killed, and an ending it cannot
        # record is an ending nobody can explain. Everything below is best
        # effort by construction: a bookkeeping arm that could fail a boot would
        # be a worse defect than the one it exists to diagnose.
        if self.record_end_reason and self.store_root_path is not None:
            self.end_reason = _ServeEndReason(self.store_root_path, boot_id=self.boot_id)
            _install_console_ctrl_reason_handler(self.end_reason)
            _install_signal_reason_handlers(self.end_reason)
            try:
                import atexit as _atexit

                # The floor under every other mechanism: a route none of them
                # know about still leaves ``unknown_exit`` rather than silence,
                # and silence is reserved for the hard kill (see the registry
                # module's sidecar section — absence is a reading).
                _atexit.register(self.end_reason.write)
            except Exception:  # pragma: no cover - atexit is always importable
                pass
            # Retention, beside the row prune and for the mirror-image reason:
            # a row is removed when its runtime exits cleanly, but nothing ever
            # consumes a REASON, so without a floor this directory grows for the
            # life of the machine.
            try:
                from agent_runtime.serve_registry import prune_serve_ended

                prune_serve_ended(self.store_root_path)
            except Exception:
                pass

        # ── RL-23: the floor under credential supersession ──────────────────
        #
        # Beside the two sidecar prunes and for the third version of the same
        # reason: a redeem now REVOKES the rows it replaces rather than leaving
        # them live, and a revoked row nobody ever deletes is growth with a
        # different name. Thirty days is how long "why did my Mac stop
        # connecting" stays a question worth answering.
        #
        # NOT gated on ``record_end_reason``: that flag says this runtime is a
        # SERVICE and owes an end reason, while the device store is the root's
        # regardless of how the runtime that opened it was started. Deleting
        # only revoked rows past the retention is what makes running it on every
        # boot safe — a live credential is never a candidate at any age.
        #
        # Silent and swallowed, like its neighbours: bookkeeping must never be
        # the thing that fails a boot.
        if self.store_root_path is not None:
            try:
                from agent_runtime.serve_gateway_auth import prune_revoked_devices

                prune_revoked_devices(self.store_root_path)
            except Exception:
                pass
        self.timeline.mark("service_foundations_ms")

    def _boot_sweeps_and_ready_frame(self) -> None:
        from agent_runtime.serve_rpc import registry as serve_rpc
        # Orphaned-turn sweep BEFORE the ready frame: serve boot is the moment
        # a launcher restart replaces a dead runtime, and the first hydrate is
        # only requested after ready — so records a dead executor left frozen
        # in-flight (lease provably free) already project as typed
        # ``turn_interrupted`` markers in that hydrate instead of a console
        # stuck "running" forever. Bounded (≤50 session files) and fail-open.
        orphaned_repaired: list[str] = []
        try:
            from agent_runtime.persona_chat_continuity import repair_orphaned_chat_turns

            orphaned_repaired = repair_orphaned_chat_turns()
        except Exception:
            orphaned_repaired = []
        self.timeline.mark("orphaned_turn_sweep_ms")
        # Same moment, same reason, for detached dispatches: a row still marked
        # ``running`` whose owning process is provably gone can never finish, and
        # the sender is owed that answer too. Reclassifying it here — BEFORE the
        # drain starts — turns "the agent I dispatched went silent forever" into
        # a delivered "the outcome is unknown, re-send if you still need it".
        # Identity-verified (a recycled PID is not the old owner) and fail-open.
        dispatches_restored = 0
        try:
            from agent_runtime.dispatch_store import restore_undelivered_dispatches

            dispatches_restored = int(
                (restore_undelivered_dispatches() or {}).get("restored") or 0
            )
        except Exception:
            dispatches_restored = 0
        self.timeline.mark("dispatch_restore_ms")
        self.ready_frame: dict[str, Any] = {
            "event": "ready",
            "pid": os.getpid(),
            "schema_version": SERVE_SCHEMA_VERSION,
            "runtime_root": self.runtime_root,
            # Additive, always present (never conditional on success): a
            # missing block would read as "old runtime", while a block whose
            # own fields say `unknown`/`error:…` reads as what it is — the
            # measurement was attempted and this is what it found.
            "boot_id": self.boot_id,
            # L-h item 3, on all three greeting frames by the same rule as
            # ``boot_id`` above: always present, never inferred from absence. A
            # client reads ``service`` to know whether closing its end of this
            # pipe DETACHES from a runtime that keeps going or KILLS it, and
            # ``starter_pid`` to know whether the process it is looking at is
            # the one it started itself.
            "service": self.service,
            "starter_pid": self.starter_pid,
            "build": self.build_block,
            "auth": self.auth_block,
            # WHICH INSTALL this is, by the same "always present, states its own
            # outcome" rule as ``auth`` above — a picker with two installs in it
            # needs a stable id and a human name, and absence would be
            # indistinguishable from a runtime that predates the lane.
            "install": self.install_block,
            "instance": self.instance_block,
            # ``disabled`` (no socket lane asked for), ``listening`` with the
            # port, ``lock_held_by`` with the winner's pid, or ``error:<reason>``
            # — the outcome is stated either way, never inferred from absence.
            "socket": self.socket_block,
            # The SECOND door, by the same rule and for a sharper reason. An
            # operator who sets ``remote_gateway.listen`` and restarts has one
            # question — can my phone reach this install — and every way the
            # answer is no is quiet: the port was taken, the certificate could
            # not be minted, the socket lane never came up, the config key was
            # never read. ``disabled`` when nobody asked, ``listening`` with
            # host/port and the ``cert_fingerprint`` a client pins,
            # ``socket_unavailable`` (R-L1) with the ``reason`` / ``pid`` /
            # ``owner_started_at`` of the lane that is holding this one shut, or
            # ``error:<reason>``. Never absent, never inferred, and — since
            # R-L1 — never ``disabled`` for a listener the config asked for.
            "gateway": self.gateway_block,
            # The METHOD lane's capability manifest — ``{"contract":N,
            # "methods":[…]}``. This is stdio's greeting, so this is where a
            # stdio client learns the method set; the socket's equivalent is
            # ``hello_ok``, and both are restated on the re-askable ``version``
            # reply. Same shape of promise as ``hello_contract``: the server
            # advertises, the client asserts, and a runtime that predates the
            # lane carries no ``rpc`` key at all — which reads as "argv only"
            # rather than as a failure.
            "rpc": serve_rpc.manifest(),
            # The OP lane's half of the same promise (TC-1/C-1). ``ready`` is
            # stdio's greeting, so this is where a stdio client learns that
            # ``{"op":"subscribe","lane":"stream"}`` is carried here rather than
            # having to send one and read the answer's tea leaves.
            "ops": ops_manifest(transport="stdio", service=self.service),
        }
        if orphaned_repaired:
            self.ready_frame["orphaned_turns_repaired"] = len(orphaned_repaired)
        if dispatches_restored:
            self.ready_frame["dispatches_restored"] = dispatches_restored
        # Every phase this boot actually paid, on the frame the supervisor
        # already waits for — and the same line in agent.log, because the boot
        # worth attributing (the cold one) is the boot nobody is watching a
        # console for. Emission is defensive: a broken instrument must never be
        # the reason a runtime fails to come up.

    def _announce_ready(self) -> None:
        try:
            self.ready_frame["boot_timeline"] = self.timeline.stamps()
        except Exception:
            pass
        # Read-model warmup starts BEFORE ``ready`` is announced, unlike the
        # provider warmup below. The launcher's first request lands within
        # milliseconds of this frame, and only the build that STARTED FIRST can
        # be shared: if the request wins the race it leads its own build and
        # the warmup then queues a second, redundant one behind it. Starting a
        # daemon thread costs microseconds, so ``ready`` is not delayed.
        #
        # ONE thread, and the provider warmup runs on it AFTER the build (EG-3.2,
        # two independent investigations reaching the same fix: HY-H2 = HC-H3).
        # It used to be a second daemon thread started just after ``ready``, and
        # under the GIL its ~5-8s of CPU — OpenAI SDK import, SSL context, and
        # since BW-H3 the ``model_tools`` import plus the discovery/check_fn storm
        # — was subtracted from the build the launcher's canvas is waiting on.
        # Nothing it warms is consumable before that canvas is authoritative: its
        # purpose is the FIRST CHAT TURN's latency, which is after.
        #
        # The brief's one-line version of this fix — reorder the two
        # ``Thread.start()`` calls — was REFUSED as a no-op by both sources
        # independently: starts issued microseconds apart schedule nothing, and
        # the provider prewarm reached ``model_tools`` ~5s in either way.
        #
        # Named cost, carried rather than hidden: a chat turn sent inside the (now
        # shorter) boot window pays the cold SDK import inline, exactly as every
        # turn did before the prewarm existed — best effort by the prewarm's own
        # contract. If receipts show first-turn misses, the refinement is
        # "provider prewarm starts at first-request-enqueue OR build-completion,
        # whichever is first", not a revert.
        # Since 2026-08-23 a THIRD step rides the same thread, last: the
        # persona-chat actor prewarm (Stage 2 of `planned/chat-turn-prep-cost`).
        # Last on purpose — it queues agent constructions, and a construction
        # that runs after the provider warmup does not pay the SDK import it
        # would otherwise pay itself. It only QUEUES here; the constructions run
        # on that module's own worker, which stands down for any live turn.
        if (
            self.snapshot_prewarm is not None
            or self.provider_prewarm is not None
            or self.actor_prewarm is not None
        ):

            def _prewarm_worker() -> None:
                # Sequential, and each step isolated: a build that raised must
                # still leave the providers warm (HY-H2), and an injected fake
                # that raises must not silently cancel the step after it.
                for step in (self.snapshot_prewarm, self.provider_prewarm, self.actor_prewarm):
                    if step is None:
                        continue
                    try:
                        step()
                    except Exception:
                        try:
                            import logging as _logging

                            _logging.getLogger(__name__).debug(
                                "serve prewarm step did not complete", exc_info=True
                            )
                        except Exception:
                            pass

            threading.Thread(
                target=_prewarm_worker,
                name="harness-serve-prewarm",
                daemon=True,
            ).start()
        self.frames.emit(self.ready_frame)
        # RL-16's test seam, and the ONLY line it costs the production path.
        # AFTER ``ready`` because every arm that uses it needs a booted runtime
        # with its recorder armed and its registry row on disk — the state a
        # real death happens in. Inert without ``HERMES_SERVE_BOOT_FAULT``; see
        # :func:`_maybe_inject_boot_fault` for the three endings it buys.
        _maybe_inject_boot_fault()
        try:
            import logging as _logging

            _logging.getLogger(__name__).info(
                self.timeline.log_line("harness serve boot timeline:")
            )
        except Exception:
            pass
        # (Both warmups run on the single thread started just before the ready
        # frame above — the read-model build first, then the chat turn's one-time
        # costs. The invariant the two-thread arrangement was written to protect
        # is now provable rather than raced: the build cannot queue behind the
        # ~3s SDK import, because that import has not started yet.)
        # A busy serve must never look dead. The launcher's stream watchdog
        # keys on "no frames for N seconds", and when pool workers are deep in
        # chat-turn work the infinite `stream` request's generator can starve
        # past that budget — Mission Control then raised the loud "Runtime
        # offline" banner DURING healthy turns (live incident 2026-07-23,
        # two flaps inside one 4-minute Neko turn). This dedicated thread
        # emits the same typed `busy` frame the `ping` op returns whenever
        # requests are in flight: pure liveness telemetry on the shared
        # stdout, independent of every pool worker, so the launcher can
        # distinguish "busy running your turn" from "gone".
