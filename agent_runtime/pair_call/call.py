"""One call between the engines of two of your devices: one socket, many lanes, both directions.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST`` (owner
2026-11-23: "in regards to using ones connection i meant the call" / "they should both be able to confirm
that requests are applied"). A :class:`PairCall` owns the TLS socket after the call's hello. Every frame
on it is addressed (:mod:`.envelope`) and belongs to a LANE: one caller using the far engine. Either side
opens a lane (``{"ctl": "lane_open"}``); the far side then admits it as an ordinary connection, which
runs its own hello and is answered as itself. A lane is either

* **bridged** (:meth:`PairCall.bridge`): a local socket's lines ride the lane and the lane's lines are
  written back to it, unread — the admitter's end of a socket pair, or the machine owner's Eternia
  attached over loopback; or
* **a client** (:meth:`PairCall.client`): this engine's own requests, each answered BY ID on the lane it
  went out on, from the address the call proved. An answer on another lane is never delivered.

On a drop every request still waiting fails ``link_closed`` with ``dispatched: true`` and
``confirmed: false`` (owner 2026-11-24: "1 yes not confirmed"): it may have been applied, so it is never
reported done, and the caller re-reads state once a call is up again. Nothing is re-sent here.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable

from ..serve_socket.vocabulary import MAX_SERVE_FRAME_BYTES
from ..serve_socket.wire import _LineReader, _LineTooLong
from .envelope import ID_PATTERN, Endpoint, address_refusal, mint_id, wrap

__layer__ = "lanes"

__all__ = ["LINK_CLOSED", "LaneClient", "PairCall", "not_confirmed"]

LINK_CLOSED = "link_closed"
#: A frame carries one line of the lane (a serve frame), so it may be a little longer than one.
_MAX_CALL_FRAME = MAX_SERVE_FRAME_BYTES + (1 << 16)
_LOCAL_LINE_LIMIT = MAX_SERVE_FRAME_BYTES


def not_confirmed(reason: str = LINK_CLOSED) -> dict[str, Any]:
    """A request whose answer never came: maybe applied, never reported done."""

    return {"ok": False, "reason": reason, "dispatched": True, "confirmed": False}


class _Lane:
    __slots__ = ("lane_id", "purpose", "opened_here", "sock", "client")

    def __init__(self, lane_id: str, purpose: str, opened_here: bool) -> None:
        self.lane_id = lane_id
        self.purpose = purpose
        self.opened_here = opened_here
        self.sock: Any = None
        self.client: LaneClient | None = None


class PairCall:
    """One call: its socket, its proven ends, its lanes and this engine's waiting requests."""

    def __init__(self, sock: Any, *, call_id: str, dialer_install: str, own: Endpoint, far: Endpoint,
                 outbound: bool, initial: bytes = b"",
                 on_lane_open: Callable[[PairCall, str, str], None] | None = None,
                 log: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.call_id = call_id
        #: The install id of the side that dialled: the dedupe rule's key, the same on both sides.
        self.dialer_install = dialer_install
        self.own = own
        self.far = far
        self.outbound = outbound
        #: The far device's id on this install, when the far side dialled as a device paired here.
        self.far_device_id: str | None = None
        self._sock = sock
        self._reader = _LineReader(sock, max_line_bytes=_MAX_CALL_FRAME, initial=initial)
        self._on_lane_open = on_lane_open
        self._log = log
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._lanes: dict[str, _Lane] = {}
        #: This engine's waiting requests, keyed by (lane id, request id).
        self._pending: dict[tuple[str, Any], _Waiter] = {}
        self._closed = threading.Event()
        self.closed_reason: str | None = None
        self._close_listeners: list[Callable[[PairCall], None]] = []
        self._thread = threading.Thread(target=self._read_loop, name="pair-call-reader", daemon=True)

    # ── life ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        try:
            self._sock.settimeout(None)
        except OSError:
            pass
        self._thread.start()

    @property
    def is_open(self) -> bool:
        return not self._closed.is_set()

    def on_close(self, listener: Callable[[PairCall], None]) -> None:
        with self._lock:
            if not self._closed.is_set():
                self._close_listeners.append(listener)
                return
        listener(self)

    def wait_closed(self, timeout: float | None = None) -> bool:
        return self._closed.wait(timeout)

    def close(self, reason: str = "hung_up") -> None:
        with self._lock:
            if self._closed.is_set():
                return
            self.closed_reason = reason
            self._closed.set()
            lanes = list(self._lanes.values())
            self._lanes.clear()
            waiting = list(self._pending.values())
            self._pending.clear()
            listeners, self._close_listeners = self._close_listeners, []
        _close_quietly(self._sock)
        for lane in lanes:
            if lane.sock is not None:
                _close_quietly(lane.sock)
            if lane.client is not None:
                lane.client.wake()
        for waiter in waiting:
            waiter.fail(not_confirmed())
        self._emit({"event": "pair_call_closed", "call": self.call_id, "far_install": self.far.install_id,
                    "reason": reason})
        for listener in listeners:
            try:
                listener(self)
            except Exception:
                pass

    def describe(self) -> dict[str, Any]:
        with self._lock:
            lanes = [{"lane": lane.lane_id, "purpose": lane.purpose, "opened_here": lane.opened_here}
                     for lane in self._lanes.values()]
        return {"call": self.call_id, "dialer_install": self.dialer_install, "outbound": self.outbound,
                "far": self.far.describe(), "open": self.is_open, "lanes": lanes}

    # ── lanes ───────────────────────────────────────────────────────────────

    def open_lane(self, purpose: str = "client") -> str:
        """Open a lane to the far engine, which admits it as one more caller. Returns its id."""

        lane_id = mint_id()
        with self._lock:
            if self._closed.is_set():
                raise ConnectionError(LINK_CLOSED)
            self._lanes[lane_id] = _Lane(lane_id, purpose, opened_here=True)
        self._send(lane_id, {"ctl": "lane_open", "purpose": purpose})
        return lane_id

    def close_lane(self, lane_id: str) -> None:
        with self._lock:
            lane = self._lanes.pop(lane_id, None)
            for key in [k for k in self._pending if k[0] == lane_id]:
                self._pending.pop(key).fail(not_confirmed())
        if lane is None:
            return
        if lane.sock is not None:
            _close_quietly(lane.sock)
        try:
            self._send(lane_id, {"ctl": "lane_close"})
        except ConnectionError:
            pass

    def bridge(self, lane_id: str, sock: Any, ahead: bytes = b"") -> None:
        """Carry *sock*'s lines on *lane_id* and write the lane's lines back to it, on its own thread."""

        with self._lock:
            lane = self._lanes.get(lane_id)
            if lane is None or self._closed.is_set():
                _close_quietly(sock)
                return
            lane.sock = sock
        threading.Thread(target=self._pump_local, args=(lane_id, sock, ahead),
                         name="pair-call-lane", daemon=True).start()

    def client(self, lane_id: str) -> LaneClient:
        with self._lock:
            lane = self._lanes.get(lane_id)
            if lane is None:
                raise ConnectionError(LINK_CLOSED)
            if lane.client is None:
                lane.client = LaneClient(self, lane_id)
            return lane.client

    def send_line(self, lane_id: str, line: str) -> None:
        self._send(lane_id, {"line": line})

    # ── the wire ────────────────────────────────────────────────────────────

    def _send(self, lane_id: str, body: dict[str, Any]) -> None:
        data = (json.dumps(wrap(lane_id, self.far, body), separators=(",", ":")) + "\n").encode("utf-8")
        with self._send_lock:
            if self._closed.is_set():
                raise ConnectionError(LINK_CLOSED)
            try:
                self._sock.sendall(data)
            except OSError:
                pass
            else:
                return
        self.close("write_failed")
        raise ConnectionError(LINK_CLOSED)

    def _read_loop(self) -> None:
        reason = "far_closed"
        try:
            while not self._closed.is_set():
                try:
                    line = self._reader.read_line(deadline_seconds=None)
                except _LineTooLong:
                    reason = "frame_too_long"
                    break
                except (OSError, ValueError):
                    break
                if line is None:
                    break
                if line.strip():
                    self._on_frame(line)
        finally:
            self.close(reason)

    def _on_frame(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        refusal = address_refusal(frame, self.own)
        if refusal is not None:
            self._emit({"event": "pair_call_address_mismatch", "call": self.call_id, "reason": refusal})
            return
        lane_id = frame.get("lane")
        if not isinstance(lane_id, str) or not ID_PATTERN.match(lane_id):
            return
        ctl = frame.get("ctl")
        if ctl == "lane_open":
            self._far_opened(lane_id, str(frame.get("purpose") or "client"))
        elif ctl == "lane_close":
            with self._lock:
                lane = self._lanes.pop(lane_id, None)
            if lane is not None and lane.sock is not None:
                _close_quietly(lane.sock)
        elif isinstance(frame.get("line"), str):
            self._deliver(lane_id, frame["line"])

    def _far_opened(self, lane_id: str, purpose: str) -> None:
        with self._lock:
            if lane_id in self._lanes:
                return
            self._lanes[lane_id] = _Lane(lane_id, purpose, opened_here=False)
        if self._on_lane_open is None:
            self.close_lane(lane_id)
            return
        try:
            self._on_lane_open(self, lane_id, purpose)
        except Exception:
            self.close_lane(lane_id)

    def _deliver(self, lane_id: str, line: str) -> None:
        with self._lock:
            lane = self._lanes.get(lane_id)
        if lane is None:
            return
        if lane.sock is not None:
            try:
                lane.sock.sendall(line.encode("utf-8") + b"\n")
            except OSError:
                self.close_lane(lane_id)
            return
        if lane.client is not None:
            lane.client.receive(line)

    def _answer_for(self, lane_id: str, request_id: Any) -> _Waiter | None:
        """The waiter an answer on *lane_id* settles: the request that went out on THAT lane."""

        with self._lock:
            # MUTATION: key by the request id alone (drop ``lane_id``) and test_pair_call's
            # test_an_answer_on_another_lane_is_not_delivered settles a request with another lane's answer.
            return self._pending.pop((lane_id, request_id), None)

    def _await(self, lane_id: str, request_id: Any) -> _Waiter:
        waiter = _Waiter()
        with self._lock:
            if self._closed.is_set():
                waiter.fail(not_confirmed())
            else:
                self._pending[(lane_id, request_id)] = waiter
        return waiter

    def _pump_local(self, lane_id: str, sock: Any, ahead: bytes) -> None:
        reader = _LineReader(sock, max_line_bytes=_LOCAL_LINE_LIMIT, initial=ahead)
        try:
            sock.settimeout(None)
        except OSError:
            pass
        try:
            while True:
                try:
                    line = reader.read_line(deadline_seconds=None)
                except (_LineTooLong, OSError, ValueError):
                    break
                if line is None:
                    break
                self.send_line(lane_id, line)
        except ConnectionError:
            pass
        finally:
            self.close_lane(lane_id)

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._log is not None:
            try:
                self._log(payload)
            except Exception:
                pass


class _Waiter:
    __slots__ = ("_event", "value")

    def __init__(self) -> None:
        self._event = threading.Event()
        self.value: dict[str, Any] | None = None

    def settle(self, value: dict[str, Any]) -> None:
        if not self._event.is_set():
            self.value = value
            self._event.set()

    fail = settle

    def wait(self, timeout: float) -> dict[str, Any] | None:
        return self.value if self._event.wait(timeout) else None


class LaneClient:
    """This engine as a caller on one lane: lines out, answers matched by id on this lane only."""

    def __init__(self, call: PairCall, lane_id: str) -> None:
        self._call = call
        self.lane_id = lane_id
        self._ids = 0
        self._lock = threading.Lock()
        self._frames: list[dict[str, Any]] = []
        self._frame_ready = threading.Condition()

    def send(self, frame: dict[str, Any]) -> None:
        self._call.send_line(self.lane_id, json.dumps(frame, separators=(",", ":")))

    def next_frame(self, timeout: float) -> dict[str, Any] | None:
        """The next frame on this lane that answers no request (the hello's frames, events)."""

        with self._frame_ready:
            if not self._frames:
                self._frame_ready.wait_for(lambda: bool(self._frames) or not self._call.is_open, timeout)
            return self._frames.pop(0) if self._frames else None

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0,
                request_id: Any = None) -> dict[str, Any]:
        """One JSON-RPC request; its answer, or :func:`not_confirmed` when the call dropped first.

        A request still waiting at *timeout* is not confirmed either: no answer is never applied.
        """

        if request_id is None:
            with self._lock:
                self._ids += 1
                request_id = f"pc-{self._ids}"
        waiter = self._call._await(self.lane_id, request_id)
        try:
            self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        except ConnectionError:
            waiter.fail(not_confirmed())
        answer = waiter.wait(timeout)
        if answer is None:
            self._call._answer_for(self.lane_id, request_id)
            return not_confirmed("no_answer")
        return answer

    def wake(self) -> None:
        with self._frame_ready:
            self._frame_ready.notify_all()

    def receive(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        if "id" in frame and ("result" in frame or "error" in frame):
            waiter = self._call._answer_for(self.lane_id, frame.get("id"))
            if waiter is not None:
                waiter.settle(frame)
            return
        with self._frame_ready:
            self._frames.append(frame)
            self._frame_ready.notify_all()


def _close_quietly(sock: Any) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass
