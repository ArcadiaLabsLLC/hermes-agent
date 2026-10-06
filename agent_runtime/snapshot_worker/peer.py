"""The serve's end of the snapshot worker's pipe.

One JSON object per line on the ``native_peer`` codec (``MAX_FRAME_BYTES`` 8 MiB,
ruling R4): a ~570 KB core decodes in ~8 ms on the peer's reader thread, and the
serve thread that asked waits on a future, holding no GIL.
"""

from __future__ import annotations

from enum import StrEnum

from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.conversations.native_peer import NativePeer

__layer__ = "lanes"

#: The worker's methods: a full core, and one chat root's ``persona_chat_turn`` sections.
BUILD_METHOD = "snapshot.build"
TURN_SECTION_METHOD = "snapshot.turn_section"


class WorkerLoss(StrEnum):
    """Why a worker build did not come back -- the ``reason=`` of ``snapshot_worker op=lost``."""

    EXITED = "exited"            # the child is gone (killed, crashed, pipe closed)
    TIMEOUT = "timeout"          # no reply inside the bound: treated as hung and killed
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

    def __init__(self, loss: WorkerLoss):
        self.loss = loss
        super().__init__(loss.value)


class SnapshotPeer(NativePeer):
    """A :class:`NativePeer` whose calls are :meth:`build` and :meth:`turn_section`."""

    def _call(self, method: str, params: dict, timeout: float, body: str) -> dict:
        try:
            result = self.call(method, params, timeout=timeout)
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
    def pid(self) -> int:
        return int(self.process.pid)
