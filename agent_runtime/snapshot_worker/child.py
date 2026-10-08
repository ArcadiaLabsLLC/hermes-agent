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

**Turn sections (lane h-overlay-worker).** ``snapshot.turn_section`` answers one
chat root's ``persona_chat_turn`` sections (:func:`agent_runtime.turn_section_read.read_turn_sections`).
Each request runs on its own thread: builds take one lock and turn sections
another, so an overlay never queues behind a 2-16 s core (they share THIS
process's interpreter, never the serve's). Both kinds read history rows through
the serve's chat-runtime export (``runtime``), never this process's empty registry.

**Liveness (lane h-pool-starve).** Once its builder is imported the worker says
``snapshot.ready``, then ``snapshot.beat`` every :data:`~.peer.BEAT_SECONDS` with,
per request in flight, how long its thread has burned no CPU (``idle_s``). The
serve reads a missing ready, a missing beat, or a request idle past its bound as
a silent worker and builds in process at once (``peer.SnapshotPeer``). A handler
that raised anything -- ``SystemExit`` included -- still answers.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
from contextlib import nullcontext
from pathlib import Path
from typing import Any, BinaryIO

from agent_runtime.conversations.model import ConversationError
from agent_runtime.conversations.native_peer import MAX_FRAME_BYTES, encode_frame

from .peer import BEAT_METHOD, BEAT_SECONDS, BUILD_METHOD, READY_METHOD, TURN_SECTION_METHOD

__layer__ = "lanes"

#: Loggers whose INFO records are receipts; any other logger forwards WARNING and up.
_RECEIPT_LOGGER_PREFIXES = ("agent_runtime", "hermes", "agent", "tools", "plugins")
#: Bound on the records one reply carries (a build emits a handful).
MAX_RECEIPTS = 200
#: JSON-RPC error codes the serve's peer maps (4130 = the frame is over the bound).
_BUILD_FAILED = -32000
_TOO_LARGE = 4130
_UNKNOWN_METHOD = -32601


#: The thread-name prefix of a turn-section request: a build's capture skips its
#: records, and a turn section's capture keeps only its own thread's.
_TURN_SECTION_THREAD = "snapshot-worker-turn-section"


class _ReceiptCapture(logging.Handler):
    def __init__(self, *, only_thread: int | None = None) -> None:
        super().__init__(level=logging.INFO)
        self.rows: list[dict[str, Any]] = []
        self.dropped = 0
        self.only_thread = only_thread

    def emit(self, record: logging.LogRecord) -> None:
        if self.only_thread is not None:
            if record.thread != self.only_thread:
                return
        elif str(record.threadName or "").startswith(_TURN_SECTION_THREAD):
            return
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


def _captured(capture: _ReceiptCapture) -> list[dict[str, Any]]:
    receipts = capture.rows
    if capture.dropped:
        receipts.append({"logger": __name__, "level": logging.WARNING,
                         "message": f"snapshot_worker receipts_dropped={capture.dropped}"})
    return receipts


def _serve_pid(params: dict) -> None:
    from agent_runtime.snapshot.build_log import set_receipt_pid

    serve_pid = params.get("serve_pid")
    set_receipt_pid(serve_pid if isinstance(serve_pid, int) else None)


_BUILD_LOCK = threading.Lock()
_TURN_SECTION_LOCK = threading.Lock()


class SnapshotBuildFailed(RuntimeError):
    def __init__(self, error: BaseException, receipts: list[dict]) -> None:
        import traceback
        self.diagnostics = {
            "error_type": type(error).__name__,
            "frames": [f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                       for frame in traceback.extract_tb(error.__traceback__)[-8:]],
            "receipts": receipts,
        }
        super().__init__(type(error).__name__)


def handle_build(params: dict) -> dict:
    """One build, its receipts, and this process's pid."""

    from agent_runtime.persona_chat_continuity.runtime_registry import recorded_runtime_registry
    from agent_runtime.serde import to_jsonable
    from agent_runtime.snapshot.build import _build_snapshot_uncoalesced
    from agent_runtime.snapshot.context import snapshot_build_context_scope
    from agent_runtime.snapshot.sections import precomputed_running_work

    capture = _ReceiptCapture()
    root = logging.getLogger()
    with _BUILD_LOCK:
        _serve_pid(params)
        root.addHandler(capture)
        try:
            with _resolution_scope(params.get("resolution")), snapshot_build_context_scope(_build_context()),                     precomputed_running_work(params.get("running_work")),                     recorded_runtime_registry(params.get("runtime")):
                core = _build_snapshot_uncoalesced()
        except BaseException as exc:
            raise SnapshotBuildFailed(exc, _captured(capture)) from exc
        finally:
            root.removeHandler(capture)
    return {"core": to_jsonable(core), "receipts": _captured(capture), "worker_pid": os.getpid()}


def handle_turn_section(params: dict) -> dict:
    """One chat root's ``persona_chat_turn`` sections (no ``running_work``) and the read's timings."""

    from agent_runtime.persona_chat_continuity.runtime_registry import recorded_runtime_registry
    from agent_runtime.turn_section_read import read_turn_sections

    capture = _ReceiptCapture(only_thread=threading.get_ident())
    root = logging.getLogger()
    with _TURN_SECTION_LOCK:
        root.addHandler(capture)
        try:
            with _resolution_scope(params.get("resolution")), recorded_runtime_registry(params.get("runtime")):
                sections, timings = read_turn_sections(
                    str(params.get("root") or ""),
                    named=tuple(str(item) for item in params.get("named") or ()),
                    evict=int(params.get("evict") or 0),
                )
        finally:
            root.removeHandler(capture)
    return {"sections": sections, "timings": timings, "receipts": _captured(capture),
            "worker_pid": os.getpid()}


_HANDLERS = {BUILD_METHOD: handle_build, TURN_SECTION_METHOD: handle_turn_section}


def _reply_frame(rid: Any, *, result: dict | None = None, code: int | None = None, message: str = "", data: dict | None = None) -> bytes:
    frame: dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
    if code is None:
        frame["result"] = result
    else:
        frame["error"] = {"code": code, "message": message, **({"data": data} if data else {})}
    try:
        return encode_frame(frame)
    except ConversationError:
        return encode_frame({"jsonrpc": "2.0", "id": rid,
                             "error": {"code": _TOO_LARGE, "message": "core over MAX_FRAME_BYTES"}})


def _thread_cpu_reader():
    """``native thread id -> CPU seconds`` for another thread of this process, or ``None``.

    The worker's one progress signal: a thread that is working (Python or a
    syscall) burns CPU; one parked on a grandchild, a lock or a pipe does not.
    """

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetThreadTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

        def read(native_id: int) -> float | None:
            handle = kernel32.OpenThread(0x0800, False, native_id)  # THREAD_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel32.GetThreadTimes(handle, *(ctypes.byref(item) for item in times)):
                    return None
                return sum((item.dwHighDateTime << 32 | item.dwLowDateTime) for item in times[2:]) / 1e7
            finally:
                kernel32.CloseHandle(handle)

        return read
    clock_of = getattr(time, "pthread_getcpuclockid", None)
    if clock_of is None:
        return None
    by_native: dict[int, int] = {}

    def read_posix(native_id: int) -> float | None:
        ident = by_native.get(native_id)
        if ident is None:
            return None
        try:
            return time.clock_gettime(clock_of(ident))
        except (OSError, ValueError):
            return None

    read_posix.by_native = by_native  # type: ignore[attr-defined]
    return read_posix


#: CPU a request thread must burn between two beats to count as working.
_WORKING_CPU_SECONDS = 0.005


def serve(requests: BinaryIO, replies: BinaryIO) -> None:
    """Say ready, beat, and answer requests until the serve closes the pipe, each on its own thread."""

    logging.getLogger().setLevel(logging.INFO)
    write_lock = threading.Lock()
    active: dict[Any, int] = {}
    active_lock = threading.Lock()

    def send(encoded: bytes) -> None:
        with write_lock:
            replies.write(encoded)
            replies.flush()

    def answer(rid: Any, method: Any, params: dict) -> None:
        native_id = threading.get_native_id()
        by_native = getattr(cpu_of, "by_native", None)
        if by_native is not None:
            by_native[native_id] = threading.get_ident()
        with active_lock:
            active[rid] = native_id
        try:
            handler = _HANDLERS.get(method)
            if handler is None:
                encoded = _reply_frame(rid, code=_UNKNOWN_METHOD, message="unknown method")
            else:
                try:
                    encoded = _reply_frame(rid, result=handler(params))
                except BaseException as exc:  # a SystemExit in a handler must still answer
                    encoded = _reply_frame(rid, code=_BUILD_FAILED, message=type(exc).__name__,
                                           data=getattr(exc, "diagnostics", None))
        finally:
            with active_lock:
                active.pop(rid, None)
            if by_native is not None:
                by_native.pop(native_id, None)
        try:
            send(encoded)
        except (OSError, ValueError):  # the serve closed the pipe: nobody is waiting
            pass

    def beat() -> None:
        idle_since: dict[Any, tuple[float, float]] = {}
        while True:
            time.sleep(BEAT_SECONDS)
            now = time.monotonic()
            with active_lock:
                current = dict(active)
            idle: dict[str, float] = {}
            for rid, native_id in current.items():
                cpu = None if cpu_of is None else cpu_of(native_id)
                last = idle_since.get(rid)
                if cpu is None or last is None or cpu - last[1] > _WORKING_CPU_SECONDS:
                    idle_since[rid] = (now, -1.0 if cpu is None else cpu)
                    idle[str(rid)] = 0.0
                else:
                    idle[str(rid)] = round(now - last[0], 1)
            for rid in [rid for rid in idle_since if rid not in current]:
                idle_since.pop(rid, None)
            try:
                send(encode_frame({"jsonrpc": "2.0", "method": BEAT_METHOD, "params": {"idle_s": idle}}))
            except Exception:
                return

    cpu_of = _thread_cpu_reader()
    # The handshake means "a build can start now": the builder's imports are paid.
    import agent_runtime.snapshot.build  # noqa: F401

    from agent_runtime.conversations.process_evidence import worker_ready_frame

    ready = worker_ready_frame()
    ready["method"] = READY_METHOD
    send(encode_frame(ready))
    threading.Thread(target=beat, name="snapshot-worker-beat", daemon=True).start()
    while raw := requests.readline(MAX_FRAME_BYTES + 1):
        try:
            frame = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(frame, dict) or "id" not in frame:
            continue
        method = frame.get("method")
        name = _TURN_SECTION_THREAD if method == TURN_SECTION_METHOD else "snapshot-worker-build"
        threading.Thread(target=answer, args=(frame["id"], method, frame.get("params") or {}),
                         name=name, daemon=True).start()
