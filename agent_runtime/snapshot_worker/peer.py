"""The serve's end of the snapshot worker's pipe.

One JSON object per line on the ``native_peer`` codec (``MAX_FRAME_BYTES`` 8 MiB,
ruling R4): a ~570 KB core decodes in ~8 ms on the peer's reader thread, and the
serve thread that asked waits on a future, holding no GIL.

**A silent worker is lost in seconds, not at the outer timeout (lane h-pool-starve).**
The serve thread waits in :data:`WATCH_SECONDS` slices and gives up -- the caller
builds in process -- as soon as the worker has not said ``snapshot.ready`` within
:data:`HANDSHAKE_SECONDS` of its spawn, has sent no frame for
:data:`SILENCE_SECONDS` since, or reports this request's thread idle (no CPU) for
:data:`IDLE_SECONDS`. The 2026-10-06 12:04 generation-1 build sat 120 s on a
grandchild that would never return; the idle bound ends that in 15 s.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import Future, TimeoutError
from enum import StrEnum

from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.conversations.native_peer import NativePeer

__layer__ = "lanes"

#: The worker's methods: a full core, and one chat root's ``persona_chat_turn`` sections.
BUILD_METHOD = "snapshot.build"
TURN_SECTION_METHOD = "snapshot.turn_section"
#: The worker's notifications: once its builder is imported, then every beat.
READY_METHOD = "snapshot.ready"
BEAT_METHOD = "snapshot.beat"

#: Seconds between the worker's beats.
BEAT_SECONDS = 1.0
#: Spawn to ``snapshot.ready``: the builder's imports measured 3.0-4.2 s.
HANDSHAKE_SECONDS = 20.0
#: After ready, the longest the worker may send nothing (five beats).
SILENCE_SECONDS = 5.0
#: The longest a request's thread may burn no CPU: parked on a grandchild, a lock or a pipe.
IDLE_SECONDS = 15.0
#: How often the waiting serve thread re-reads those three.
WATCH_SECONDS = 0.25


class WorkerLoss(StrEnum):
    """Why a worker build did not come back -- the ``reason=`` of ``snapshot_worker op=lost``."""

    EXITED = "exited"            # the child is gone (killed, crashed, pipe closed)
    TIMEOUT = "timeout"          # no reply inside the bound: treated as hung and killed
    SILENT = "silent"            # no ready, or no beat: the process is up and says nothing
    IDLE = "idle"                # beating, but this request's thread has burned no CPU for IDLE_SECONDS
    BUILD_ERROR = "build_error"  # the child's build raised; the child itself is fine
    BAD_REPLY = "bad_reply"      # a reply that is not a core (or a frame over the bound)
    SPAWN_FAILED = "spawn_failed"


_LOSS_BY_REFUSAL = {
    Refusal.WORKER_LOST: WorkerLoss.EXITED,
    Refusal.UNKNOWN: WorkerLoss.TIMEOUT,
    Refusal.NATIVE_REFUSAL: WorkerLoss.BUILD_ERROR,
}


class WorkerLost(RuntimeError):
    """A worker build that will not arrive; the caller builds in process instead."""

    def __init__(self, loss: WorkerLoss, *, diagnostics: dict | None = None):
        self.loss = loss
        self.diagnostics = diagnostics or {}
        super().__init__(loss.value)


class SnapshotPeer(NativePeer):
    """A :class:`NativePeer` whose calls are :meth:`build` and :meth:`turn_section`, watched."""

    def __init__(self, process, *, containment=None, clock=time.monotonic):
        self._clock = clock
        self.spawned_at = clock()
        self.worker_pid: int | None = None
        self.ready_at: float | None = None
        self.last_frame_at = self.spawned_at
        self.idle_s: dict[str, float] = {}
        super().__init__(process, receive=self._notice, lost=lambda: None, containment=containment)

    def _route(self, frame: dict) -> None:
        self.last_frame_at = self._clock()
        super()._route(frame)

    def _notice(self, frame: dict) -> None:
        method = frame.get("method")
        if method == READY_METHOD and self.ready_at is None:
            self.ready_at = self._clock()
            pid = (frame.get("params") or {}).get("worker_pid")
            if type(pid) is int and pid > 0:
                self.worker_pid = pid
        elif method == BEAT_METHOD:
            idle = (frame.get("params") or {}).get("idle_s")
            self.idle_s = dict(idle) if isinstance(idle, dict) else {}

    def silence(self, rid: str) -> WorkerLoss | None:
        """Why this worker is no longer worth waiting on for ``rid``, or ``None``."""

        now = self._clock()
        if self.ready_at is None:
            return WorkerLoss.SILENT if now - self.spawned_at > HANDSHAKE_SECONDS else None
        if now - self.last_frame_at > SILENCE_SECONDS:
            return WorkerLoss.SILENT
        idle = self.idle_s.get(rid)
        if isinstance(idle, (int, float)) and idle >= IDLE_SECONDS:
            return WorkerLoss.IDLE
        return None

    def _watched(self, method: str, params: dict, timeout: float) -> dict:
        """``PeerCore.call``, waited in slices that read :meth:`silence` between them."""

        rid = uuid.uuid4().hex
        future: Future = Future()
        with self._lock:
            if not self.alive:
                raise ConversationError(Refusal.WORKER_LOST)
            self._pending[rid] = future
        try:
            self.write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = self._clock() + timeout
            while True:
                try:
                    response = future.result(timeout=WATCH_SECONDS)
                    break
                except TimeoutError:
                    pass
                loss = self.silence(rid)
                if loss is not None:
                    raise WorkerLost(loss)
                if self._clock() >= deadline:
                    raise ConversationError(Refusal.UNKNOWN)
        finally:
            with self._lock:
                self._pending.pop(rid, None)
        if "error" in response:
            if response["error"].get("code") == 4130:
                raise ConversationError(Refusal.RESPONSE_TOO_LARGE)
            raise WorkerLost(WorkerLoss.BUILD_ERROR, diagnostics=response["error"].get("data"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise ConversationError(Refusal.NATIVE_REFUSAL)
        return result

    def _call(self, method: str, params: dict, timeout: float, body: str) -> dict:
        try:
            result = self._watched(method, params, timeout)
        except ConversationError as exc:
            raise WorkerLost(_LOSS_BY_REFUSAL.get(exc.reason, WorkerLoss.BAD_REPLY)) from exc
        if not isinstance(result.get(body), dict) or not isinstance(result.get("receipts"), list):
            raise WorkerLost(WorkerLoss.BAD_REPLY)
        return result

    def build(self, params: dict, *, timeout: float) -> dict:
        return self._call(BUILD_METHOD, params, timeout, "core")

    def turn_section(self, params: dict, *, timeout: float) -> dict:
        return self._call(TURN_SECTION_METHOD, params, timeout, "sections")

    @property
    def pid(self) -> int | None:
        return self.worker_pid

    @property
    def launcher_pid(self) -> int:
        return int(self.process.pid)
