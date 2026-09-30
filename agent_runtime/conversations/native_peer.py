"""Bounded JSON-RPC peer for a runtime-owned native conversation worker.

Requests, server questions and events share one reader. No feature owns this
pipe, and disconnecting a Launcher connection never closes it.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError

from .model import ConversationError, Refusal

__layer__ = "lanes"
MAX_FRAME_BYTES = 8 * 1024 * 1024
_log = logging.getLogger(__name__)


def _frames(stream):
    while raw := stream.readline(MAX_FRAME_BYTES + 1):
        if len(raw) > MAX_FRAME_BYTES:
            # Replay's gap watermark redirects omitted events to native recovery.
            while raw and not raw.endswith(b"\n"):
                raw = stream.readline(64 * 1024)
            _log.warning("Oversized native frame omitted; recover through the native checkpoint")
            continue
        if not raw.endswith(b"\n"):
            return
        try:
            frame = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue  # Startup diagnostics are not protocol frames.
        if isinstance(frame, dict):
            yield frame


def encode_frame(frame: dict) -> bytes:
    """One wire line; a frame over the bound is refused before it is sent."""
    encoded = json.dumps(frame, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(encoded) > MAX_FRAME_BYTES:
        raise ConversationError(Refusal.INVALID_REQUEST)
    return encoded


class PeerCore:
    """The RPC half every worker peer shares: pending calls, replies, questions, events.

    A subclass provides ``alive``, ``execution_possible``, ``process_identity`` and
    ``_send(frame, encoded)``; it feeds each frame the worker emits to :meth:`_route`
    and calls :meth:`_ended` once, when the worker can emit no more.
    """

    def __init__(self, *, receive: Callable[[dict], None], lost: Callable[[], None]):
        self.receive, self.lost = receive, lost
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, Future] = {}
        self._closed = False

    def call(self, method: str, params: dict, *, timeout: float = 60) -> dict:
        rid = uuid.uuid4().hex
        future = Future()
        with self._lock:
            if not self.alive:
                raise ConversationError(Refusal.WORKER_LOST)
            self._pending[rid] = future
        try:
            self.write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            response = future.result(timeout=timeout)
            if "error" in response:
                code = response["error"].get("code")
                if code == 4130:
                    raise ConversationError(Refusal.RESPONSE_TOO_LARGE)
                raise ConversationError(Refusal.NATIVE_REFUSAL,
                                        native_code=code if type(code) is int else None)
            result = response.get("result")
            if not isinstance(result, dict):
                raise ConversationError(Refusal.NATIVE_REFUSAL)
            return result
        except TimeoutError as exc:
            # A missing reply is not evidence that the worker rejected the call.
            raise ConversationError(Refusal.UNKNOWN) from exc
        finally:
            with self._lock:
                self._pending.pop(rid, None)

    def write(self, frame: dict) -> None:
        encoded = encode_frame(frame)
        with self._write_lock:
            if not self.alive:
                raise ConversationError(Refusal.WORKER_LOST)
            self._send(frame, encoded)

    def _send(self, frame: dict, encoded: bytes) -> None:
        raise NotImplementedError

    def _route(self, frame: dict) -> None:
        with self._lock:
            rid = frame.get("id")
            pending = self._pending.get(rid) if isinstance(rid, str) and "method" not in frame else None
        if pending is not None:
            if not pending.done():
                pending.set_result(frame)
        elif "method" in frame:
            self.receive(frame)

    def _ended(self) -> None:
        with self._lock:
            self._closed = True
            pending = list(self._pending.values())
        for request in pending:
            if not request.done():
                request.set_exception(ConversationError(Refusal.WORKER_LOST))
        self.lost()


class NativePeer(PeerCore):
    def __init__(self, process: subprocess.Popen, *, receive: Callable[[dict], None],
                 lost: Callable[[], None], containment=None):
        try:
            import psutil
        except ImportError as exc:  # the phone omits psutil, and starts no worker process to identify
            raise RuntimeError("a native conversation peer needs psutil to stamp its worker process") from exc

        super().__init__(receive=receive, lost=lost)
        self.process = process
        self.containment = containment
        self.process_identity = (process.pid, psutil.Process(process.pid).create_time())
        self._close_lock = threading.Lock()
        self._disposed = False
        self._reader = threading.Thread(target=self._read, daemon=True,
                                        name="native-conversation-reader")
        self._reader.start()

    @property
    def alive(self) -> bool:
        with self._lock:
            return not self._closed and self.process.poll() is None

    @property
    def execution_possible(self) -> bool:
        return self.process.poll() is None

    def _send(self, frame: dict, encoded: bytes) -> None:
        try:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise ConversationError(Refusal.WORKER_LOST) from exc

    def _read(self) -> None:
        try:
            for frame in _frames(self.process.stdout):
                self._route(frame)
        finally:
            self._ended()

    def close(self) -> None:
        """Explicit service shutdown only; never invoked for view/socket loss."""
        with self._close_lock:
            if self._disposed:
                return
            self._dispose()
            self._disposed = True

    def _dispose(self) -> None:
        closer = threading.Thread(target=self._close_input, daemon=True,
                                  name="native-conversation-close")
        closer.start()
        try:
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self.containment is not None:
                self.containment.close()
        closer.join(timeout=1)
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=2)
        self.process.stdout.close()

    def _close_input(self) -> None:
        with self._write_lock:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
