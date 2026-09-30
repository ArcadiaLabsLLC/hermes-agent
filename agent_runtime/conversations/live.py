"""One route's native RPC binding; no second history or pending-request owner."""
from __future__ import annotations

import json
import threading

from .app_functions import METHOD, NativeAppFunctions, client_requests
from .model import UNSETTLED, ConversationError, Refusal, TurnState
from .questions import SUPPORTED, validate_answer

__layer__ = "lanes"
_OUTCOMES = {"complete": TurnState.COMPLETED, "interrupted": TurnState.STOPPED,
             "error": TurnState.FAILED, "running": TurnState.RUNNING, "unknown": TurnState.UNKNOWN}


class LiveConversation:
    def __init__(self, route, native_id, worker, store, *, app_pool=None):
        self.route, self.native_id, self.worker, self.store = route, native_id, worker, store
        self.peer = worker.peer
        self.operations = threading.Lock()
        self._cancel_ack = None
        self.retirement_pending = False
        self.app_functions = NativeAppFunctions(self.peer, app_pool, self._app_turn_current)

    def _app_turn_current(self, execution):
        receipt = self.store.latest(self.route)
        return bool(receipt and receipt.execution_id == execution and receipt.state in UNSETTLED
                    and not receipt.cancel_requested)

    def retire(self):
        receipt = self.store.latest(self.route)
        if receipt and receipt.state in UNSETTLED:
            self._checkpoint()
            receipt = self.store.latest(self.route)
        if receipt and receipt.state in UNSETTLED:
            return False
        self.retirement_pending = True
        result = self.peer.call("session.retire", {"session_id": self.native_id,
            "execution_id": receipt.execution_id if receipt else None})
        self.retirement_pending = False
        return result.get("status") == "retired"

    @property
    def turn_id(self):
        receipt = self.store.latest(self.route)
        return receipt.turn_id if receipt and receipt.state in UNSETTLED else None

    def stop(self, turn_id):
        receipt = self.store.request_cancel(self.route, turn_id)
        if receipt.state not in UNSETTLED:
            return
        if not receipt.execution_id:
            raise ConversationError(Refusal.UNKNOWN)
        answer = self.peer.call("session.interrupt", {"session_id": self.native_id,
            "expected_execution_id": receipt.execution_id})
        if answer.get("status") == "interrupted":
            self._cancel_ack = receipt.execution_id

    def dispatched(self, turn_id):
        if self.store.turn(self.route, turn_id).cancel_requested:
            self.stop(turn_id)

    def retry_stop(self):
        receipt = self.store.latest(self.route)
        if (receipt and receipt.cancel_requested and receipt.state in UNSETTLED
                and receipt.execution_id != self._cancel_ack):
            try:
                self.stop(receipt.turn_id)
            except ConversationError:
                pass  # Intent remains durable; only native completion settles it.

    def receive(self, frame):
        if self.app_functions.receive(frame):
            return
        params = frame.get("params") or {}
        if frame.get("method") == "event":
            if params.get("type") == "message.complete":
                self.reconcile({"id": params.get("execution_id"),
                                "status": (params.get("payload") or {}).get("status")})
            return
        if isinstance(frame.get("id"), str) and (
                frame.get("method") not in SUPPORTED or len(json.dumps(frame, ensure_ascii=True)) > 64 * 1024):
            self.peer.write({"jsonrpc": "2.0", "id": frame["id"], "error": {
                "code": -32601, "message": "This client cannot present this request."}})

    def reconcile(self, evidence):
        if not evidence or not evidence.get("id"):
            return
        receipt = self.store.execution(self.route, evidence["id"])
        state = _OUTCOMES.get(evidence.get("status"))
        if receipt is not None and state is not None:
            self.store.settle(self.route.id, receipt.turn_id, state, authoritative=True)

    def lost(self):
        receipt = self.store.latest(self.route)
        if receipt and receipt.state in UNSETTLED:
            self.store.settle(self.route.id, receipt.turn_id, TurnState.UNKNOWN)

    def answer(self, request_id, result):
        page = self.peer.call("session.events.since", {"session_id": self.native_id, "include_events": False})
        pending = next((q for q in page.get("open_requests", ()) if q["id"] == request_id), None)
        if pending is not None and pending.get("method") == METHOD:
            return False
        if pending is not None:
            validate_answer(pending, result)
        elif len(json.dumps(result, ensure_ascii=True)) > 64 * 1024:
            raise ConversationError(Refusal.INVALID_REQUEST)
        answer = self.peer.call("request.answer", {"session_id": self.native_id,
                                "id": request_id, "result": result})
        return answer.get("status") == "ok"

    def _checkpoint(self, turn_id=None):
        receipt = self.store.turn(self.route, turn_id) if turn_id else self.store.latest(self.route)
        native = self.peer.call("session.recover", {"session_id": self.native_id,
            **({"execution_id": receipt.execution_id} if receipt and receipt.execution_id else {})})
        self.reconcile(native.get("execution"))
        return {**native, "open_requests": client_requests(native.get("open_requests", []))}

    def recover(self, turn_id=None):
        native = self._checkpoint(turn_id)
        self.retry_stop()
        return {"recovery": native, "epoch": native["epoch"], "cursor": native["latest_seq"],
                "offset": 0, "events": [], "more": False, "truncated": False,
                "connected": self.peer.alive, **self.receipt(turn_id)}

    def receipt(self, turn_id=None):
        receipt = self.store.turn(self.route, turn_id) if turn_id else self.store.latest(self.route)
        if receipt is None:
            return {}
        return {"turn": {"turn_id": receipt.turn_id, "state": receipt.state,
                         "execution_id": receipt.execution_id, "cancel_requested": receipt.cancel_requested}}

    def snapshot(self, cursor, turn_id=None, *, epoch=None, offset=0):
        from .replay import read_page

        receipt = self.receipt(turn_id)
        self.retry_stop()
        page = self.peer.call("session.events.since", {"session_id": self.native_id, "last_seen": cursor})
        if page.get("truncated") or (epoch is not None and page["epoch"] != epoch):
            return self.recover()
        return {**read_page(self, page, cursor, offset), "connected": self.peer.alive, **receipt}
