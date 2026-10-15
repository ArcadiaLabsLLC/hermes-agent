"""Request-owned canonical chat writers; no process-wide owner or cache."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock

from .chat_session_scope import ChatSessionScope, prepare_chat_session_writer

__layer__ = "stores"


class ChatSessionWriterLease:
    """One public registry reference, tied to the acquired object generation."""

    def __init__(self, scope: ChatSessionScope, *, expected_db=None):
        import hermes_state_registry

        self.scope = scope
        self._lock = Lock()
        self.db = hermes_state_registry.acquire(scope.db_path)
        try:
            if expected_db is not None and self.db is not expected_db:
                raise RuntimeError("canonical chat writer generation changed before resident pin")
            prepare_chat_session_writer(self.db, scope)
        except BaseException:
            hermes_state_registry.release(self.db)
            raise
        self._released = False

    def close(self) -> None:
        import hermes_state_registry

        with self._lock:
            if self._released:
                return
            self._released = True
        hermes_state_registry.release(self.db)


class ChatSessionWriterOwner:
    """A turn owns its references until finally or explicit tail transfer."""

    def __init__(self):
        self._leases = {}
        self.closed = False

    def acquire(self, scope: ChatSessionScope):
        if self.closed:
            raise RuntimeError("chat writer owner is closed")
        key = scope.db_path.resolve()
        lease = self._leases.get(key)
        if lease is None:
            lease = self._leases[key] = ChatSessionWriterLease(scope)
        return lease.db

    def resident_pin(self, db):
        """Own the exact constructor generation independently of this request."""
        for lease in self._leases.values():
            if lease.db is db:
                return ChatSessionWriterLease(lease.scope, expected_db=db)
        raise RuntimeError("resident constructor writer has no request owner")

    def transfer_to(self, deferred, db) -> bool:
        for key, lease in self._leases.items():
            if lease.db is db and deferred.attach_cleanup(lease.close):
                del self._leases[key]
                return True
        return False

    def close(self) -> None:
        self.closed = True
        leases, self._leases = self._leases, {}
        failure = None
        for lease in leases.values():
            try:
                lease.close()
            except BaseException as exc:
                failure = failure or exc
        if failure is not None:
            raise failure



_writer_owner: ContextVar[ChatSessionWriterOwner | None] = ContextVar(
    "chat_session_writer_owner", default=None
)


def current_chat_session_writer_owner() -> ChatSessionWriterOwner | None:
    owner = _writer_owner.get()
    return owner if owner is not None and not owner.closed else None


@contextmanager
def chat_session_writer_owner():
    owner = ChatSessionWriterOwner()
    token = _writer_owner.set(owner)
    try:
        yield owner
    finally:
        _writer_owner.reset(token)
        owner.close()


def with_chat_session_writer_owner(function):
    """Wrap all command returns/errors without changing its admission boundary."""
    @wraps(function)
    def owned(*args, **kwargs):
        with chat_session_writer_owner():
            return function(*args, **kwargs)
    return owned
