"""The profile worker behind ``runtime.conversation.*``, run inside this process.

Embedded-hermes plan Stage 2 step 8 (architecture §3). The desktop serves each
profile's conversations from a worker subprocess running the native gateway
(``tui_gateway``) over stdio. A phone may start no subprocess, so there the SAME
gateway dispatcher runs in-process behind the same peer seam: this class is a
:class:`~.native_peer.PeerCore` whose wire is ``tui_gateway``'s own in-process
door — ``server.dispatch(request, transport)``, the one the WebSocket sidecar
already uses — instead of a pipe. Same RPC, same sessions, same recovery; the
conversation service above it cannot tell the two apart.

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

import json
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


def _install_gateway_methods() -> None:
    """What the worker subprocess's entry point installs, once per process."""
    global _installed
    with _install_lock:
        if not _installed:
            from .worker_skills import install

            install()
            _installed = True


def _gateway_dispatch(request: dict, transport) -> dict | None:
    from tui_gateway import server

    return server.dispatch(request, transport)


def _admits_profile(method: str) -> bool:
    # The registry the profile selects: a phone reads the generated catalog, never pydantic.
    from tui_gateway.contract_seam import registry

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
        self.closed = False

    def write(self, obj: dict) -> bool:
        if self.closed:
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
        self.closed = True


def _log():
    import logging

    return logging.getLogger(__name__)


class InProcessPeer(PeerCore):
    def __init__(self, home: Path, *, receive: Callable[[dict], None], lost: Callable[[], None],
                 dispatch: Callable[[dict, object], dict | None] = _gateway_dispatch):
        super().__init__(receive=receive, lost=lost)
        self.home = Path(home)
        self.profile = _profile_for(self.home)
        self._dispatch = dispatch
        self._transport = _Transport(self._route)
        self._sessions: set[str] = set()
        self._openers: set[str] = set()
        self._unclosed: set[str] = set()
        self._close_lock = threading.Lock()
        self._disposed = False
        self.process_identity = in_process_identity(self)

    @property
    def alive(self) -> bool:
        with self._lock:
            return not self._closed

    @property
    def execution_possible(self) -> bool:
        """Alive, or a session it opened was not provably closed (the subprocess's exit, here)."""
        with self._lock:
            return not self._closed or bool(self._unclosed)

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
                self._openers.add(request["id"])
        response = self._dispatch(request, self._transport)
        if response is not None:
            self._transport.write(response)

    def _route(self, frame: dict) -> None:
        result = frame.get("result")
        with self._lock:
            opened = "method" not in frame and frame.get("id") in self._openers
            if opened:
                self._openers.discard(frame["id"])
                if isinstance(result, dict) and isinstance(result.get("session_id"), str):
                    self._sessions.add(result["session_id"])
        super()._route(frame)

    def close(self) -> None:
        """Explicit service shutdown only: close what this worker opened, then end it."""
        with self._close_lock:
            if self._disposed:
                return
            self._disposed = True
        with self._lock:
            self._closed = True
            self._unclosed = set(self._sessions)
        for session_id in sorted(self._unclosed):
            try:
                reply = self._dispatch({"jsonrpc": "2.0", "id": "close-" + session_id, "method": "session.close",
                                        "params": {"session_id": session_id}}, self._transport)
            except Exception:
                _log().warning("in-process worker could not close session %s", session_id, exc_info=True)
                continue
            if isinstance(reply, dict) and "result" in reply:
                with self._lock:
                    self._unclosed.discard(session_id)
        self._transport.close()
        self._ended()


def start_in_process_worker(home: Path, *, receive: Callable[[dict], None],
                            lost: Callable[[], None]) -> InProcessPeer:
    """``start_worker``'s in-process twin: same arguments, same handshake."""
    from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders

    ensure_lifecycle_placeholders()  # before the gateway imports the loop
    _install_gateway_methods()
    peer = InProcessPeer(home, receive=receive, lost=lost)
    try:
        peer.call("client.capabilities", {"server_requests": True})
    except Exception:
        peer.close()
        raise
    return peer
