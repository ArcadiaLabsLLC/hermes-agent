"""Connection-bound app functions for admitted discussion runs."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock

from agent_runtime.launcher_app_functions import (
    LauncherLink, ORIGIN_LOCAL, bind_launcher_link, reset_launcher_link,
    refresh_app_function_tools, resolve_response,
)
from agent_runtime.launcher_invocation import launcher_invocation

__layer__ = "stores"
_request = ContextVar("discussion_launcher_request", default=None)


@contextmanager
def requesting_launcher(request):
    token = _request.set(request)
    try:
        yield
    finally:
        _request.reset(token)


class DiscussionAppFunctions:
    def __init__(self):
        self._requests = {}
        self._pending = {}
        self._lock = RLock()

    def bind(self, run_id, *, client_scope=None):
        request = _request.get()
        if request is not None:
            with self._lock:
                self._requests.setdefault(run_id, (request, client_scope))

    def admit(self, run_id, command_key, *, client_scope=None):
        with self._lock:
            self._pending[(run_id, command_key)] = (_request.get(), client_scope)

    def activate(self, run_id, command_key):
        # RoomCommands calls this only after earlier tasks have settled. Queued
        # messages retain their admitting connection; reads/replays never rebind.
        with self._lock:
            binding = self._pending.pop((run_id, command_key), None)
            if binding is not None:
                self._requests[run_id] = binding

    def forget(self, run_id):
        with self._lock:
            self._requests.pop(run_id, None)
            self._pending = {key: value for key, value in self._pending.items() if key[0] != run_id}

    def request_for(self, run_id, task_id):
        with self._lock:
            binding = self._requests.get(run_id)
        if binding is None or binding[0] is None:
            return None
        request, client_scope = binding

        def call(method, params):
            with launcher_invocation("discussion", run_id, task_id, client_scope=client_scope):
                return request(method, params)
        return call

    def close(self):
        with self._lock:
            self._requests.clear()
            self._pending.clear()


class _Sink:
    def __init__(self, request):
        self.request = request

    def emit(self, frame):
        try:
            reply = {"result": self.request(frame["method"], frame["params"])}
        except Exception:
            reply = {"error": {"code": -32000, "message": "The discussion's Launcher is unavailable."}}
        resolve_response({**reply, "id": frame["id"]}, self)


@contextmanager
def discussion_launcher(request):
    link = LauncherLink(_Sink(request), ORIGIN_LOCAL) if request is not None else None
    token = bind_launcher_link(link)
    try:
        if link is not None:
            refresh_app_function_tools(link)
        yield
    finally:
        reset_launcher_link(token)
