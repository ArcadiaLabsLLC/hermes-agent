"""Bounded JSON-RPC peer for a runtime-owned native conversation worker.

Requests, server questions and events share one reader. No feature owns this
pipe, and disconnecting a Launcher connection never closes it.
"""
from __future__ import annotations

import json
import subprocess
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError
import psutil

from .model import ConversationError, Refusal

__layer__ = "lanes"
MAX_FRAME_BYTES = 8 * 1024 * 1024


class NativePeer:
    def __init__(self, process: subprocess.Popen, *, receive: Callable[[dict], None],
                 lost: Callable[[], None], containment=None):
        self.process, self.receive, self.lost = process, receive, lost
        self.containment = containment
        self.process_identity = (process.pid, psutil.Process(process.pid).create_time())
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, Future] = {}
        self._closed = False
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
        encoded = json.dumps(frame, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > MAX_FRAME_BYTES:
            raise ConversationError(Refusal.INVALID_REQUEST)
        with self._write_lock:
            if not self.alive:
                raise ConversationError(Refusal.WORKER_LOST)
            try:
                self.process.stdin.write(encoded)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise ConversationError(Refusal.WORKER_LOST) from exc

    def _read(self) -> None:
        try:
            while raw := self.process.stdout.readline(MAX_FRAME_BYTES + 1):
                if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
                    break
                try:
                    frame = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    # Native startup diagnostics do not become protocol frames.
                    continue
                if not isinstance(frame, dict):
                    continue
                with self._lock:
                    rid = frame.get("id")
                    pending = self._pending.get(rid) if isinstance(rid, str) and "method" not in frame else None
                if pending is not None:
                    if not pending.done():
                        pending.set_result(frame)
                elif "method" in frame:
                    self.receive(frame)
        finally:
            with self._lock:
                self._closed = True
                pending = list(self._pending.values())
            for request in pending:
                if not request.done():
                    request.set_exception(ConversationError(Refusal.WORKER_LOST))
            self.lost()

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
