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

#: The one method the worker answers.
BUILD_METHOD = "snapshot.build"


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
    """A :class:`NativePeer` whose one call is :meth:`build`."""

    def build(self, params: dict, *, timeout: float) -> dict:
        try:
            result = self.call(BUILD_METHOD, params, timeout=timeout)
        except ConversationError as exc:
            raise WorkerLost(_LOSS_BY_REFUSAL.get(exc.reason, WorkerLoss.BAD_REPLY)) from exc
        if not isinstance(result.get("core"), dict) or not isinstance(result.get("receipts"), list):
            raise WorkerLost(WorkerLoss.BAD_REPLY)
        return result

    @property
    def pid(self) -> int:
        return int(self.process.pid)
