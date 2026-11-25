"""The native gateway (``tui_gateway``) run inside this process, behind the peer seam.

Embedded-hermes plan Stage 2 step 8 (architecture §3), and since
RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT the one engine every chat with an
agent runs on (``operator_gateway_turn``), on the desktop and the phone alike. This class is a
:class:`~.native_peer.PeerCore` whose wire is ``tui_gateway``'s own in-process door —
``server.dispatch(request, transport)``, the one the WebSocket sidecar already uses — instead of
a pipe: same RPC, same sessions, same recovery as the retired worker subprocess.

What the subprocess got from its own ``HERMES_HOME``, this peer gets from the
gateway's multi-profile hosting: every request whose contract admits ``profile``
names this worker's profile, so the gateway binds that profile's home, secrets
and session database. The home must be a canonical profile home (the name must
resolve back to it), or the worker refuses to start rather than serve another
profile's state.

Frames cross the seam as JSON, both ways and under the same size bound as the
pipe, so what a caller can send or receive is byte-for-byte what it could over
stdio. Closing the worker closes the sessions it opened, as the subprocess's
exit did; its evidence (``process_identity``) is this pid plus a per-worker
generation, answered by the worker itself (:mod:`.process_evidence`).
"""
from __future__ import annotations

import importlib
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from .model import ConversationError, Refusal
from .native_peer import MAX_FRAME_BYTES, PeerCore, encode_frame
from .process_evidence import in_process_identity

__layer__ = "lanes"

_SESSION_OPENERS = frozenset({"session.create", "session.resume"})
_install_lock = threading.Lock()
_installed = False
#: The in-process workers not yet closed. The gateway's compute host (``dashboard.turn_isolation``) is one
#: per process and serves them all, so the last one out stops it.
_open_peers: set[int] = set()
_open_lock = threading.Lock()


def stop_compute_host() -> None:
    """Stop the gateway's compute-host child, if this process made one (RT-NATIVE-PEER-RETIRE-ORPHANS-COMPUTE-HOST).

    What the retired worker child did on its way out (``worker_entry.stop_compute_host``), now that the
    workers run in this process: ``HostSupervisor.shutdown`` is the supervisor's own stop (a ``shutdown``
    frame, then terminate on timeout) and reaps the child. Reads the singleton without making one: a
    process that never isolated a turn has no child to stop.
    """
    import sys

    server = sys.modules.get("tui_gateway.server")  # never imported here: no server, no child
    supervisor = server.existing_compute_host_supervisor() if server is not None else None
    if supervisor is None:
        return
    try:
        supervisor.shutdown()
    except Exception:  # the child then exits on its stdin EOF
        _log().warning("in-process worker could not stop the compute host", exc_info=True)


def _install_gateway_methods() -> None:
    """What the worker subprocess's entry point installs, once per process."""
    global _installed
    with _install_lock:
        if not _installed:
            _import_gateway_keeping_stdout()
            from .worker_skills import install

            install()
            from .worker_app_functions import install as install_app_functions
            install_app_functions()
            _installed = True


def _import_gateway_keeping_stdout() -> None:
    """Import ``tui_gateway.server`` without its stdio guard taking the process's stdout.

    The gateway's import reserves the real stdout for its stdio JSON-RPC (``sys.stdout = sys.stderr``).
    An in-process peer speaks no stdio, and the serve that hosts it answers every request on stdout
    (``harness_parts.serve.frames``): left in place, the swap turns each later reply line into a stderr
    frame (a Mission Control reply printed after the first conversation opened never reached the client).

    The import runs under the PROCESS's own home, never the profile a turn is scoped to: the gateway
    captures its launch home at import (``server._hermes_home``), and a named profile whose home equals it
    is read as the launch profile, whose sessions are the launch store's. On a phone the first import
    is the first chat turn, under the agent's own profile (``neko``), so the gateway took ``neko`` for
    its launch home, read the agent's chats from the serve root's store and refused every resume
    "session not found" (RT-FU-A-PHONE-AGENT-WITH-ITS-OWN-PROFILE-SENDS-WITHOUT-PYDANTIC).
    MUTATION: import without the scope and test_operator_gateway_turn's
    ``test_the_gateway_is_imported_under_the_process_home_not_the_turns_profile`` reddens.
    """
    if "tui_gateway.server" in sys.modules:
        return
    from hermes_constants import (
        get_routing_process_hermes_home, reset_hermes_home_override, set_hermes_home_override,
    )

    held = sys.stdout
    token = set_hermes_home_override(get_routing_process_hermes_home())
    try:
        _import_module("tui_gateway.server")
    finally:
        reset_hermes_home_override(token)
    if sys.stdout is not held:
        sys.stdout = held


_import_module = importlib.import_module


def _gateway_dispatch(request: dict, transport) -> dict | None:
    from tui_gateway import server

    return server.dispatch(request, transport)


def _admits_profile(method: str) -> bool:
    # The registry the profile selects: a phone reads the generated catalog, never pydantic.
    from agent_runtime.gateway.contract_seam import registry

    contract = registry.METHODS.get(method)
    return contract is not None and "profile" in getattr(contract.params, "model_fields", {})


def _profile_for(home: Path) -> str:
    from hermes_cli.profiles import get_profile_dir
    from hermes_constants import profile_name_for_home

    name = profile_name_for_home(home)
    if not name or get_profile_dir(name).resolve() != home.resolve():
        raise ConversationError(Refusal.WRONG_OWNER)
    return name


class _Transport:
    """The gateway's side of the seam: every frame it writes becomes one routed frame."""

    def __init__(self, deliver: Callable[[dict], None]) -> None:
        self._deliver = deliver
        self._closed = False

    def write(self, obj: dict) -> bool:
        if self._closed:
            if "id" in obj and "method" not in obj:
                self._deliver(obj)  # an admitted open can finish after disconnect
            return False
        from tui_gateway.transport import serialize_frame

        line = serialize_frame(obj, "in-process-worker", _log())
        if len(line.encode("utf-8", errors="surrogatepass")) + 1 > MAX_FRAME_BYTES:
            # The pipe's reader omits an oversized frame; recovery replays it from the checkpoint.
            _log().warning("Oversized native frame omitted; recover through the native checkpoint")
            return True
        self._deliver(json.loads(line))
        return True

    def close(self) -> None:
        self._closed = True


def _log():
    import logging

    return logging.getLogger(__name__)


class InProcessPeer(PeerCore):
    def __init__(self, home: Path, *, receive: Callable[[dict], None], lost: Callable[[], None],
                 dispatch: Callable[[dict, object], dict | None] = _gateway_dispatch,
                 auth_home: Path | None = None):
        super().__init__(receive=receive, lost=lost)
        self.home = Path(home)
        self.auth_home = auth_home
        self.profile = _profile_for(self.home)
        self._dispatch = dispatch
        self._transport = _Transport(self._route)
        # Receipts for process-liveness evidence. Only the gateway decides which attachments to release.
        self._sessions: set[str] = set()
        self._openers: set[str] = set()
        self._release_finished = False
        self._release_uncertain = False
        self._close_lock = threading.Lock()
        self._disposed = False
        self.process_identity = in_process_identity(self)
        with _open_lock:
            _open_peers.add(id(self))

    @property
    def alive(self) -> bool:
        with self._lock:
            return not self._closed

    @property
    def execution_possible(self) -> bool:
        """A turn can outlive its departing peer while another client remains attached."""
        with self._lock:
            if not self._release_finished or self._openers or self._release_uncertain:
                return True
            observed = tuple(self._sessions)
        if not observed:
            return False
        from tui_gateway import server

        with server._sessions_lock:
            return any(sid in server._sessions for sid in observed)

    def write(self, frame: dict) -> None:
        # No write lock: the gateway admits concurrent requests (the WebSocket door does), and a
        # handler may emit a question whose answer is written back from inside this very call.
        encoded = encode_frame(frame)
        if not self.alive:
            raise ConversationError(Refusal.WORKER_LOST)
        self._send(frame, encoded)

    def _send(self, frame: dict, encoded: bytes) -> None:
        request = json.loads(encoded)
        method = request.get("method")
        params = request.get("params")
        if isinstance(method, str) and isinstance(params, dict) and "profile" not in params \
                and _admits_profile(method):
            params["profile"] = self.profile
        if method in _SESSION_OPENERS and isinstance(request.get("id"), str):
            with self._lock:
                if self._closed:
                    raise ConversationError(Refusal.WORKER_LOST)
                self._openers.add(request["id"])
            params.setdefault("close_on_disconnect", True)
        try:
            response = self._dispatch_scoped(request)
        except Exception as exc:
            # An inline handler that raises is answered as the stdio door answers it
            # (tui_gateway/entry.py) and the pool answers a long one: -32000, never a raise into
            # the caller. On the phone this is how a switched-off feature's RPC (vault.*) answers.
            if "method" not in request:
                raise
            _log().exception("in-process gateway handler failed for method=%r", method)
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32000, "message": f"handler error: {exc}"}}
        if response is not None:
            self._transport.write(response)

    def _dispatch_scoped(self, request: dict):
        from agent_runtime.gateway.recovery_history import serving_worker
        from agent_runtime.profile_home import (
            reset_hermes_auth_home_override, set_hermes_auth_home_override,
        )
        token = set_hermes_auth_home_override(self.auth_home)
        try:
            with serving_worker(repr(self.process_identity[1])):
                return self._dispatch(request, self._transport)
        finally:
            reset_hermes_auth_home_override(token)

    def _route(self, frame: dict) -> None:
        with self._lock:
            opener = "method" not in frame and frame.get("id") in self._openers
            closed = self._closed
            result = frame.get("result")
            sid = result.get("session_id") if opener and isinstance(result, dict) else None
            if isinstance(sid, str):
                self._sessions.add(sid)
        try:
            if closed:
                if isinstance(sid, str):
                    self.release_session(sid)
            else:
                super()._route(frame)
        finally:
            if opener:
                with self._lock:
                    self._openers.discard(frame["id"])

    def release_session(self, session_id: str | None = None) -> None:
        """Release this transport's attachments through the gateway's disconnect decision."""
        from tui_gateway import server

        try:
            server._close_sessions_for_transport(self._transport, session_id=session_id, end_reason="tui_close")
        except Exception:
            with self._lock:
                self._release_uncertain = True
            raise

    def close(self) -> None:
        """Detach this worker; sessions still serving another client stay live."""
        with self._close_lock:
            if self._disposed:
                return
            self._disposed = True
        with self._lock:
            self._closed = True
        self._transport.close()
        try:
            self.release_session()
            with self._lock:
                self._release_finished = True
        except Exception:
            _log().exception("in-process worker could not release its gateway attachments")
        with _open_lock:
            _open_peers.discard(id(self))
            last = not _open_peers
        if last:
            stop_compute_host()  # after its sessions closed: they may still talk to the child
        self._ended()


def start_in_process_worker(home: Path, *, receive: Callable[[dict], None],
                            lost: Callable[[], None], auth_home: Path | None = None) -> InProcessPeer:
    """``start_worker``'s in-process twin: same arguments, same handshake."""
    from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders

    ensure_lifecycle_placeholders()  # before the gateway imports the loop
    _install_gateway_methods()
    peer = InProcessPeer(home, receive=receive, lost=lost, auth_home=auth_home)
    try:
        peer.call("client.capabilities", {"server_requests": True})
    except Exception:
        peer.close()
        raise
    return peer
