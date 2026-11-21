"""``ServeSocketServer`` — bind and accept; each accepted socket goes to the admitter.

Moved whole in the MOVE commit (ruling Q8: a class moved whole may cross the
ceiling for exactly one commit); the CHANGE lifted the handshake methods into
``handshake``. The admit, dispatch and drain half then moved into ``admit``
(``ConnectionAdmitter``, review w1118a.79), so a phone, which runs no listener,
admits the lane it dialled out through the same code; this file keeps what only a
listener has: the bind, the accept loop, its wakeup and its counters.
"""

from __future__ import annotations

import select
import socket
import threading
import time
from pathlib import Path
from typing import Any

from agent_runtime.clock import now_iso
from agent_runtime.serve_socket.vocabulary import SOCKET_HOST
from agent_runtime.serve_socket.admit import ConnectionAdmitter, _disable_nagle
from agent_runtime.serve_socket.wire import _is_fatal_accept_error

__layer__ = "lanes"

__all__ = [
    "ServeSocketServer",
    "_disable_nagle",
]


# ── the server ───────────────────────────────────────────────────────────────


class ServeSocketServer(ConnectionAdmitter):
    """Bind, accept, and hand each accepted socket to the admitter.

    Two-phase start on purpose. :meth:`bind` happens EARLY — before the serve
    registry entry and the ready frame, so both can carry the real port — while
    :meth:`start_accepting` happens after the request pool exists. A client that
    connects in between waits in the listen backlog, which is exactly what a
    backlog is for; dispatching a request into a pool that does not exist yet is
    not.
    """

    def __init__(
        self,
        store_root: Path | str,
        *,
        host: str = SOCKET_HOST,
        port: int = 0,
        **admitter: Any,
    ) -> None:
        super().__init__(store_root, **admitter)
        self._host = host
        #: 0 = ephemeral, which is what the loopback lane has always done and
        #: what every existing caller gets by omission. A FIXED port exists for
        #: the gateway lane, where an operator has to write a firewall rule and
        #: a phone has to be told a number that survives a restart.
        self._bind_port = max(0, int(port))
        self._listener: socket.socket | None = None
        #: The accept loop's wakeup, and the reason it exists: closing a
        #: listening socket from another thread aborts a pending ``accept()``
        #: on Windows and does NOT wake one on Linux. A loop parked in
        #: ``accept()`` therefore outlived ``close()`` on every POSIX host and
        #: ``accept_loop_exited`` — the field whose whole purpose is "the loop
        #: never stops quietly" — was stamped by whichever platform happened to
        #: be kind. The loop waits on this pair BESIDE the listener, so the
        #: ending is the same everywhere and is caused, not raced for. The
        #: write end is closed by ``_close_listener``; the read end is closed
        #: by the only thread that ever selects on it.
        self._wake_read: socket.socket | None = None
        self._wake_write: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        #: Every way the accept loop can fail, counted and SURFACED. The loop
        #: dying used to be invisible while the port stayed advertised — a
        #: service that answers its discovery record and nothing else.
        self._accept_errors = 0
        self._accept_loop_exited: str | None = None
        self._started_at: str | None = None

    # ── lifecycle ───────────────────────────────────────────────────────────

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def started_at(self) -> str | None:
        return self._started_at

    def bind(self) -> int:
        """Bind this listener's host/port and listen. Returns the port.

        Ephemeral by default, which is the loopback lane's unchanged behaviour;
        a non-zero ``port`` constructor argument pins it. Still no
        ``SO_REUSEADDR``, and that matters MORE with a fixed port than it ever
        did with an ephemeral one: on Windows it permits a second process to
        bind a port already in use, so on a pinned port it would turn "the
        address is taken" into a silent hijack of a listener a phone is about to
        dial. A bind that cannot have the port RAISES, and the caller reports a
        typed outcome rather than serving from somewhere else.
        """

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # No SO_REUSEADDR — see the module docstring.
        listener.bind((self._host, self._bind_port))
        listener.listen(max(8, self._max_connections))
        # Non-blocking, because the accept loop now decides readiness with
        # ``select`` and must never park in ``accept()`` — that is the one
        # place ``close()`` cannot reach it on a POSIX host. The socket handed
        # back by ``accept()`` gets its own explicit timeout in
        # ``_serve_connection``, so nothing downstream inherits this.
        listener.setblocking(False)
        self._wake_read, self._wake_write = socket.socketpair()
        self._wake_read.setblocking(False)
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        self._started_at = now_iso()
        return self._port

    def start_accepting(self) -> None:
        if self._listener is None:
            raise RuntimeError("bind() must run before start_accepting()")
        if self._accept_thread is not None:
            return
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="harness-serve-socket-accept", daemon=True
        )
        self._accept_thread.start()

    def begin_drain(self) -> None:
        """Stop accepting NEW connections; existing ones stay up to be told."""

        with self._lock:
            draining = self._draining
        super().begin_drain()
        if not draining:
            self._close_listener()

    def close(self, reason: str = "shutdown") -> None:
        """Stop accepting, close every connection, and release nothing else.

        The LOCK is not released here: its owner is the serve loop, which holds
        it for the process's lifetime and drops it as the last act of the drain.
        """

        self._stop.set()
        self._close_listener()
        super().close(reason)
        thread = self._accept_thread
        if thread is None:
            # Bound but never accepted: nobody is selecting on the read end, so
            # nobody else will ever close it.
            self._close_wake_read()
        elif thread.is_alive():
            thread.join(2.0)

    def connections_payload(self) -> dict[str, Any]:
        payload = super().connections_payload()
        with self._lock:
            accept_errors = self._accept_errors
            accept_loop_exited = self._accept_loop_exited
        return {
            "port": self._port,
            "host": self._host,
            **payload,
            # An accept loop that stopped while the port stayed advertised is
            # the one failure a client cannot detect by connecting; both the
            # error count and the loop's exit reason are stated, always.
            "accept_errors": accept_errors,
            "accept_loop_exited": accept_loop_exited,
        }

    # ── accept loop ─────────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """Accept until stopped, and ANNOUNCE the ending whatever it is.

        Nothing in here may terminate the loop quietly. The listener stays
        bound and the discovery record stays published for as long as this
        process lives, so a loop that stopped without a word leaves a service
        that answers "connect to me" and then never answers anything — the
        exact false-all-clear shape this workstream exists to retire. Every
        exit therefore records ``accept_loop_exited`` (readable in the
        ``connections`` block) and emits a typed log line.
        """

        outcome = "stopped"
        try:
            while not self._stop.is_set():
                listener = self._listener
                if listener is None:
                    outcome = "listener_closed"
                    return
                try:
                    ready, _, _ = select.select([listener, self._wake_read], [], [])
                except ValueError:
                    # A closed socket answers ``fileno() == -1``, which select
                    # refuses. That IS the listener being gone.
                    outcome = "listener_closed"
                    return
                except OSError as exc:
                    if self._stop.is_set() or self._listener is None:
                        outcome = "listener_closed"
                        return
                    with self._lock:
                        self._accept_errors += 1
                    self._emit_log(
                        {
                            "event": "serve_socket_accept_error",
                            "phase": "wait",
                            "reason": type(exc).__name__,
                        }
                    )
                    if _is_fatal_accept_error(exc):
                        outcome = f"fatal_accept_error:{type(exc).__name__}"
                        return
                    time.sleep(0.05)
                    continue
                if self._stop.is_set() or self._listener is None:
                    outcome = "listener_closed"
                    return
                if listener not in ready:
                    # Only the wakeup spoke, and the check above already said
                    # the lane is still open. Nothing was dialled; go back to
                    # waiting rather than inventing an ending.
                    continue
                try:
                    sock, peer = listener.accept()
                except BlockingIOError:
                    # ``select`` promised a peer and the kernel no longer has
                    # one (a connection aborted between the two calls). Not an
                    # error, and — because the listener is non-blocking — not a
                    # park either.
                    continue
                except OSError as exc:
                    if self._stop.is_set() or self._listener is None:
                        outcome = "listener_closed"
                        return
                    # A typed line, never process death: an accept that fails on
                    # a transient OS condition must not take the runtime with it.
                    with self._lock:
                        self._accept_errors += 1
                    self._emit_log(
                        {
                            "event": "serve_socket_accept_error",
                            "phase": "accept",
                            "reason": type(exc).__name__,
                        }
                    )
                    if _is_fatal_accept_error(exc):
                        outcome = f"fatal_accept_error:{type(exc).__name__}"
                        return
                    time.sleep(0.05)
                    continue
                # INSIDE the loop's error handling, deliberately. A thread
                # spawn that fails (the interpreter is out of threads — which
                # is precisely what an unbounded pre-auth flood produces) used
                # to propagate out of the accept loop and kill it, silently,
                # while the port stayed advertised. It is now one accounted
                # rejection of one peer, and the lane keeps serving everybody
                # else.
                self._admit_socket(sock, peer)
        except BaseException as exc:  # reported, never raised out
            outcome = f"error:{type(exc).__name__}"
            with self._lock:
                self._accept_errors += 1
        finally:
            # This thread is the only one that ever selects on the read end, so
            # it is the only one that may close it: closing it from ``close()``
            # would free a descriptor out from under a live ``select``.
            self._close_wake_read()
            with self._lock:
                self._accept_loop_exited = outcome
            self._emit_log(
                {"event": "serve_socket_accept_loop_exit", "outcome": outcome}
            )

    def _admit_socket(self, sock: socket.socket, peer: Any) -> None:
        """Hand one accepted socket to its own thread, or account the refusal.

        Lifted out of :meth:`_accept_loop` so the loop's nesting has room; the
        comment above the call site says why a failed spawn is one accounted
        rejection and not the loop's death.
        """

        try:
            threading.Thread(
                target=self._serve_connection,
                args=(sock, peer),
                name="harness-serve-socket-conn",
                daemon=True,
            ).start()
        except BaseException as exc:  # reported, never raised out
            with self._lock:
                self._accept_errors += 1
            self._emit_log(
                {
                    "event": "serve_socket_accept_error",
                    "phase": "spawn",
                    "reason": type(exc).__name__,
                }
            )
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(0.05)

    def _serve_connection(self, sock: socket.socket, peer: Any) -> None:
        self.admit(sock, peer, binding=self._port or 0)

    # ── the listener's teardown ─────────────────────────────────────────────

    def _close_listener(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        # WAKE FIRST, then close. The wakeup is what actually ends the accept
        # loop; ``listener.close()`` is only what stops the port answering.
        # Ordering them the other way would leave a window where the loop woke
        # on a listener it could still read ``self._listener`` as live.
        self._signal_wakeup()
        try:
            listener.close()
        except OSError:
            pass

    def _signal_wakeup(self) -> None:
        """Tell the accept loop to look again, then hand it a permanent EOF.

        One byte covers the loop already waiting; closing the write end covers
        the loop that has not reached ``select`` yet, because a read end at EOF
        stays readable forever. Both halves matter: without the second, a loop
        that woke, read the byte and looped would park again.
        """

        wake, self._wake_write = self._wake_write, None
        if wake is None:
            return
        try:
            wake.send(b"\x00")
        except OSError:
            pass
        try:
            wake.close()
        except OSError:
            pass

    def _close_wake_read(self) -> None:
        wake, self._wake_read = self._wake_read, None
        if wake is None:
            return
        try:
            wake.close()
        except OSError:
            pass
