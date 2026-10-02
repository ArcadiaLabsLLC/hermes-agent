"""Runtime-owned placement identity for app-function results; never model input."""
from contextlib import contextmanager
from contextvars import ContextVar

__layer__ = "models"

_current = ContextVar("launcher_invocation", default=None)


def current_invocation():
    return _current.get()


@contextmanager
def launcher_invocation(channel, session_id, turn_id, *, client_scope=None,
                        persona_instance_id=None, profile=None):
    """Bind who is calling for the width of the block: the channel and its turn,
    and — when the lane knows them — the account scope, the persona instance and
    the hermes profile the turn runs as. The Launcher reads the first three and
    ``client_scope``; the rest travel for its placement record and are ignored
    by a Launcher that does not read them yet."""
    value = None
    if session_id and turn_id:
        value = {"channel": channel, "session_id": session_id, "turn_id": turn_id}
        for key, item in (("client_scope", client_scope),
                          ("persona_instance_id", persona_instance_id),
                          ("profile", profile)):
            if item is not None:
                value[key] = item
    token = _current.set(value)
    try:
        yield
    finally:
        _current.reset(token)
