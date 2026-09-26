"""One native session's live evidence. The native engine owns its execution."""
from __future__ import annotations

import threading
import uuid

from .events import ConversationEvents
from .model import TurnState
from .questions import SUPPORTED, validate_answer
from .projection import event_frames
import json

__layer__ = "lanes"

_OUTCOMES = {"complete": TurnState.COMPLETED, "interrupted": TurnState.STOPPED,
             "error": TurnState.FAILED}


class LiveConversation:
    def __init__(self, route, native_id: str, peer, store):
        self.route, self.native_id, self.peer, self.store = route, native_id, peer, store
        self.events = ConversationEvents()
        self.turn_id: str | None = None
        self._stop_requested = False
        self.questions: dict[str, dict] = {}
        self._lock = threading.RLock()
        # Serializes caller mutations only. The reader never takes this lock.
        self.operations = threading.Lock()

    def start(self, turn_id: str) -> None:
        with self._lock:
            self.turn_id = turn_id
            self._stop_requested = False

    def stop(self, turn_id: str) -> None:
        from .model import ConversationError, Refusal

        with self._lock:
            if self.turn_id != turn_id:
                raise ConversationError(Refusal.WRONG_OWNER)
            self._stop_requested = True
            self._interrupt()

    def dispatched(self, turn_id: str) -> None:
        with self._lock:
            if self.turn_id == turn_id and self._stop_requested:
                # Stop may arrive between durable admission and native submit.
                self._interrupt()

    def _interrupt(self) -> None:
        # This is a request, not a stopped receipt. Completion supplies the proof.
        self.peer.write({"jsonrpc": "2.0", "id": uuid.uuid4().hex,
                         "method": "session.interrupt", "params": {"session_id": self.native_id}})

    def receive(self, frame: dict) -> None:
        with self._lock:
            turn = self.turn_id
            params = frame.get("params") or {}
            if frame.get("method") == "event":
                self._event(params, turn)
                for projected in event_frames(frame):
                    self.events.append(turn, projected)
                return
            elif isinstance(frame.get("id"), str):
                if frame.get("method") not in SUPPORTED:
                    self.peer.write({"jsonrpc": "2.0", "id": frame["id"], "error": {
                        "code": -32601, "message": "This client does not support this request."}})
                    self.events.append(turn, {"method": "request.unsupported", "params": {}})
                    return
                if len(self.questions) >= 8 or len(json.dumps(frame, ensure_ascii=True)) > 64 * 1024:
                    self.peer.write({"jsonrpc": "2.0", "id": frame["id"], "error": {
                        "code": -32602, "message": "The question exceeds this client's presentation limits."}})
                    self.events.append(turn, {"method": "request.unsupported", "params": {}})
                    return
                self.questions[frame["id"]] = frame
            self.events.append(turn, frame)

    def _event(self, params: dict, turn: str | None) -> None:
        kind, payload = params.get("type"), params.get("payload") or {}
        if kind == "request.cancel":
            self.questions.pop(payload.get("id") or payload.get("request_id"), None)
        if kind != "message.complete" or turn is None:
            return
        state = _OUTCOMES.get(payload.get("status"))
        # Missing/unknown terminal vocabulary is not proof of completion.
        if state is not None:
            self.store.settle(self.route.id, turn, state)
            self.turn_id = None
            self._stop_requested = False
            self.questions.clear()

    def lost(self) -> None:
        with self._lock:
            if self.turn_id is not None:
                self.store.settle(self.route.id, self.turn_id, TurnState.UNKNOWN)
            self.events.append(self.turn_id, {"method": "worker.lost", "params": {}})

    def answer(self, request_id: str, result: dict) -> None:
        from .model import ConversationError, Refusal

        with self._lock:
            if request_id not in self.questions:
                raise ConversationError(Refusal.UNAVAILABLE)
            validate_answer(self.questions[request_id], result)
            self.peer.write({"jsonrpc": "2.0", "id": request_id, "result": result})
            self.questions.pop(request_id)

    def snapshot(self, cursor: int, turn_id: str | None = None) -> dict:
        with self._lock:
            result = {**self.events.since(cursor), "connected": self.peer.alive}
            if turn_id is not None:
                result["turn"] = {"turn_id": turn_id,
                                  "state": self.store.turn(self.route, turn_id).state}
            return result
