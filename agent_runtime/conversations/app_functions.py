"""Forward a native request through the turn's existing Launcher authority.

A request is dispatched once, on the connection that admitted this turn. Reopen
never replays it or retargets it to a different Launcher/account.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from agent_runtime.launcher_app_functions import ClientRequestFailed
from .worker_app_functions import METHOD

__layer__ = "lanes"
MAX_BYTES = 2 * 1024 * 1024


class AppFunctionPool:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="native-app-function")
        self._slots = threading.BoundedSemaphore(16)

    def submit(self, callback):
        if not self._slots.acquire(blocking=False):
            return False
        try:
            future = self._pool.submit(callback)
        except RuntimeError:
            self._slots.release()
            return False
        future.add_done_callback(lambda _: self._slots.release())
        return True

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


class NativeAppFunctions:
    def __init__(self, peer, pool, current):
        self.peer, self.pool, self.current = peer, pool, current
        self._lock = threading.Lock()
        self._execution = None
        self._request = None
        self._seen = set()

    def bind(self, execution, request):
        with self._lock:
            self._execution, self._request = execution, request
            self._seen.clear()

    def receive(self, frame):
        if frame.get("method") != METHOD:
            return False
        rid = frame.get("id")
        if not isinstance(rid, str):
            return True
        with self._lock:
            if rid in self._seen:
                return True
            self._seen.add(rid)
            execution, request = self._execution, self._request
        if request is None or self.pool is None or not self.pool.submit(
                lambda: self._forward(frame, execution, request)):
            self._reply(rid, {"error": {"code": -32000, "message": "Launcher unavailable or busy."}})
        return True

    def _forward(self, frame, execution, request):
        try:
            if not self.current(execution):
                raise ValueError("The requesting turn is no longer active.")
            payload = frame["params"]["request"]
            method, params = payload["method"], payload.get("params", {})
            if not isinstance(method, str) or not method.startswith("launcher.") or not isinstance(params, dict):
                raise ValueError("Invalid app-function request.")
            if len(json.dumps(payload, ensure_ascii=True)) > MAX_BYTES:
                raise ValueError("App-function request exceeds the document limit.")
            reply = {"result": request(method, params)}
        except ClientRequestFailed as error:
            reply = {"error": {"code": error.code, "message": error.message, "data": error.data}}
        except Exception:
            reply = {"error": {"code": -32000, "message": "The app function could not be completed. Inspect before retrying."}}
        self._reply(frame["id"], reply)

    def _reply(self, rid, reply):
        try:
            self.peer.write({"jsonrpc": "2.0", "id": rid, "result": {"reply": reply}})
        except Exception:
            pass  # Native recovery reports worker loss; never repeat the effect.
