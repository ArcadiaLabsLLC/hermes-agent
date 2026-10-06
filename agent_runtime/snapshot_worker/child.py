"""The worker's side: answer ``snapshot.build`` with the core and the build's receipts.

The child builds exactly what the serve would have built in process:
``_build_snapshot_uncoalesced()`` under the SERVE's runtime resolution (sent with
each request, so the child projects the store the serve resolved, whatever its
own environment says), inside one long-lived ``SnapshotBuildContext`` (the serve
lane's reusable caches, now per process). Its own ``SessionDB`` is opened and
closed by that function (MCF-27), and ``events_position()`` is captured inside the
build, before the first section, as it always was. The one section built in the
SERVE is ``running_work`` (its live lanes read the serve's in-memory registries);
it rides the request (``sections.running_work_for_worker``).

**Receipts (ruling R5).** The child writes no log file. Every record a build emits
at INFO from a Hermes logger, and at WARNING from any logger, is returned in the
reply and written by the serve under the serve's logger names; the build-time
receipts that carry a ``pid=`` print the serve's (``build_log.receipt_pid``) so
they join the serve's ``snapshot_build_core`` exactly as an in-process build's do.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from contextlib import nullcontext
from pathlib import Path
from typing import Any, BinaryIO

from agent_runtime.conversations.model import ConversationError
from agent_runtime.conversations.native_peer import MAX_FRAME_BYTES, encode_frame

from .peer import BUILD_METHOD

__layer__ = "lanes"

#: Loggers whose INFO records are receipts; any other logger forwards WARNING and up.
_RECEIPT_LOGGER_PREFIXES = ("agent_runtime", "hermes", "agent", "tools", "plugins")
#: Bound on the records one reply carries (a build emits a handful).
MAX_RECEIPTS = 200
#: JSON-RPC error codes the serve's peer maps (4130 = the frame is over the bound).
_BUILD_FAILED = -32000
_TOO_LARGE = 4130
_UNKNOWN_METHOD = -32601


class _ReceiptCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.rows: list[dict[str, Any]] = []
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        name = record.name or ""
        if record.levelno < logging.WARNING and not name.startswith(_RECEIPT_LOGGER_PREFIXES):
            return
        if len(self.rows) >= MAX_RECEIPTS:
            self.dropped += 1
            return
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        except Exception:
            message = str(record.msg)
        self.rows.append({"logger": name, "level": int(record.levelno), "message": message})


_BUILD_CONTEXT = None


def _build_context():
    global _BUILD_CONTEXT
    if _BUILD_CONTEXT is None:
        from agent_runtime.snapshot.context import SnapshotBuildContext

        _BUILD_CONTEXT = SnapshotBuildContext()
    return _BUILD_CONTEXT


def _resolution_scope(raw: Any):
    """The serve's resolution, re-bound here; no resolution -> this process resolves its own."""

    if not isinstance(raw, dict) or not raw.get("store_root"):
        return nullcontext()
    from agent_runtime.resolution import RuntimeResolution, runtime_resolution_scope

    return runtime_resolution_scope(RuntimeResolution(
        store_root=Path(str(raw["store_root"])),
        layer=str(raw.get("layer") or ""),
        hermes_home=None if raw.get("hermes_home") is None else str(raw["hermes_home"]),
        config_path=str(raw.get("config_path") or ""),
        trace=tuple(str(line) for line in raw.get("trace") or ()),
    ))


def handle_build(params: dict) -> dict:
    """One build, its receipts, and this process's pid."""

    from agent_runtime.serde import to_jsonable
    from agent_runtime.snapshot.build import _build_snapshot_uncoalesced
    from agent_runtime.snapshot.build_log import set_receipt_pid
    from agent_runtime.snapshot.context import snapshot_build_context_scope
    from agent_runtime.snapshot.sections import precomputed_running_work

    serve_pid = params.get("serve_pid")
    set_receipt_pid(serve_pid if isinstance(serve_pid, int) else None)
    capture = _ReceiptCapture()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        with _resolution_scope(params.get("resolution")), snapshot_build_context_scope(_build_context()),                 precomputed_running_work(params.get("running_work")):
            core = _build_snapshot_uncoalesced()
    finally:
        root.removeHandler(capture)
    receipts = capture.rows
    if capture.dropped:
        receipts.append({"logger": __name__, "level": logging.WARNING,
                         "message": f"snapshot_worker receipts_dropped={capture.dropped}"})
    return {"core": to_jsonable(core), "receipts": receipts, "worker_pid": os.getpid()}


def _reply(rid: Any, *, result: dict | None = None, code: int | None = None, message: str = "") -> bytes:
    frame: dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
    if code is None:
        frame["result"] = result
    else:
        frame["error"] = {"code": code, "message": message}
    try:
        return encode_frame(frame)
    except ConversationError:
        return encode_frame({"jsonrpc": "2.0", "id": rid,
                             "error": {"code": _TOO_LARGE, "message": "core over MAX_FRAME_BYTES"}})


def serve(requests: BinaryIO, replies: BinaryIO) -> None:
    """Answer requests one at a time until the serve closes the pipe."""

    logging.getLogger().setLevel(logging.INFO)
    while raw := requests.readline(MAX_FRAME_BYTES + 1):
        try:
            frame = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(frame, dict) or "id" not in frame:
            continue
        rid = frame["id"]
        if frame.get("method") != BUILD_METHOD:
            encoded = _reply(rid, code=_UNKNOWN_METHOD, message="unknown method")
        else:
            try:
                encoded = _reply(rid, result=handle_build(frame.get("params") or {}))
            except Exception as exc:
                encoded = _reply(rid, code=_BUILD_FAILED, message=type(exc).__name__)
        replies.write(encoded)
        replies.flush()
