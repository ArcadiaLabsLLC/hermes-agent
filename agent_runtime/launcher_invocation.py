"""Runtime-owned placement identity for app-function results; never model input."""
from contextlib import contextmanager
from contextvars import ContextVar

__layer__ = "models"

_current = ContextVar("launcher_invocation", default=None)


def current_invocation():
    return _current.get()


@contextmanager
def launcher_invocation(channel, session_id, turn_id, *, client_scope=None):
    value = None
    if session_id and turn_id:
        value = {"channel": channel, "session_id": session_id, "turn_id": turn_id}
        if client_scope is not None:
            value["client_scope"] = client_scope
    token = _current.set(value)
    try:
        yield
    finally:
        _current.reset(token)
