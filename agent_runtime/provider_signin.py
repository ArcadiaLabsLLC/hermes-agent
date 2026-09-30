"""Provider sign-in as a pollable session over the one machine sign-in child.

``runtime.provider.signin.*`` never runs OAuth itself. Each session is one
``hermes auth login <provider> --json`` child — ``hermes_cli.provider_browser_login``,
whose driver table wraps upstream's flows and whose NDJSON wire already
discards helper output, disables logging and never serializes an exception.
This module turns that stream into state a client can poll:

``starting`` -> ``awaiting_user`` (open the link, enter the code) or
``awaiting_code`` (open the link, paste the code back through ``complete``) ->
``completing`` -> ``succeeded`` | ``failed`` | ``cancelled``.

A session holds the verification link and user code the driver's
``on_verification`` callback surfaced, never a token: the tokens stay inside
the child and land in the store upstream's own save path picks. The child is
the isolation boundary on purpose — a driver's prints and a provider's error
bodies die with its stdout, so nothing here has to redact them.

The spawner is injectable (:class:`ProviderSignIns`) so tests drive fakes, and
a profile with no subprocess (``auth.subprocess_signin: false``, the phone)
binds :func:`run_login_in_process` — the same sign-in on a thread, same events.
"""

from __future__ import annotations

import contextvars
import json
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol

__layer__ = "stores"

__all__ = [
    "LOGIN_TTL_SECONDS",
    "LoginChild",
    "ProviderSignIns",
    "SignInRefused",
    "registry",
    "run_login_in_process",
    "select_login_runner",
    "spawn_login_child",
]


#: A session that has not finished by then is killed and reads ``expired``.
LOGIN_TTL_SECONDS = 15 * 60
#: Finished sessions stay pollable this long, so a client that missed the last
#: poll still learns the outcome.
FINISHED_RETENTION_SECONDS = 10 * 60

ACTIVE_STATES = frozenset({"starting", "awaiting_user", "awaiting_code", "completing"})
#: Error codes a child's terminal ``error`` event may carry; anything else is
#: folded to ``login_failed`` so a client branches on a closed set.
CHILD_ERROR_CODES = frozenset(
    {"browser_busy", "expired", "denied", "cancelled", "login_failed", "unsupported_flow", "unknown_provider"}
)


class LoginChild(Protocol):
    """The running sign-in: NDJSON lines out, one line in, killable."""

    def lines(self) -> Iterable[str]: ...

    def write_line(self, text: str) -> None: ...

    def terminate(self) -> None: ...


class SignInRefused(Exception):
    """A refusal with a closed ``reason``; ``code`` is the JSON-RPC family."""

    def __init__(self, reason: str, code: str, **data: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code
        self.data = data


@dataclass
class _Session:
    login_id: str
    provider: str
    flow: str
    child: LoginChild
    started_at: float
    state: str = "starting"
    verification_uri: str | None = None
    user_code: str | None = None
    error_code: str | None = None
    updated_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def view(self) -> dict:
        row: dict[str, Any] = {
            "login_id": self.login_id,
            "provider": self.provider,
            "flow": self.flow,
            "state": self.state,
            "needs_code": self.state == "awaiting_code",
            "started_at": self.started_at,
            "updated_at": self.updated_at or self.started_at,
        }
        if self.verification_uri is not None:
            row["verification_uri"] = self.verification_uri
            row["user_code"] = self.user_code or ""
        if self.error_code is not None:
            row["error_code"] = self.error_code
        return row


def spawn_login_child(provider: str, flow: str, profile: str | None) -> LoginChild:
    """Start ``hermes auth login <provider> --json --flow <flow>`` under this home.

    The spawn lives in :mod:`agent_runtime.provider_signin_child`, imported only here: a
    profile that starts no subprocess (``auth.subprocess_signin: false``, the phone) never
    selects this runner (:func:`select_login_runner`) and leaves that module out.
    """
    from .provider_signin_child import spawn_login_child as spawn

    return spawn(provider, flow, profile)


class _ThreadChild:
    """The in-process :class:`LoginChild`: the same sign-in, on a thread, over queues.

    A profile that may start no subprocess (the phone) runs
    ``hermes_cli.provider_browser_login.run_browser_login`` — what
    ``hermes auth login --json`` runs — on a daemon thread in the caller's context,
    its NDJSON events on one queue and the pasted code on another. The child's
    isolation is kept by ``quiet_current_thread``: the driver's prints and log
    records are dropped for that thread only, and the queue carries nothing but
    the events. A thread cannot be killed: ``terminate`` ends the stream and fails
    a pending paste, while a device-code poll already in flight runs to the
    provider's own expiry, its outcome discarded (the session is already final).
    """

    _END = object()

    def __init__(self, provider: str, flow: str, profile: str | None) -> None:
        self._events: queue.Queue = queue.Queue()
        self._pasted: queue.Queue = queue.Queue()
        self._terminated = threading.Event()
        context = contextvars.copy_context()
        threading.Thread(target=context.run, args=(self._run, provider, flow, profile),
                         daemon=True, name="provider-signin-in-process").start()

    def _run(self, provider: str, flow: str, profile: str | None) -> None:
        from hermes_cli.auth_noninteractive import resolve_target_home
        from hermes_cli.provider_browser_login import quiet_current_thread, run_browser_login
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        try:
            home, applied_profile = resolve_target_home(profile)
            token = set_hermes_home_override(home) if applied_profile is not None else None
            try:
                run_browser_login(provider, home=home, flow=flow, emit=lambda e: self._events.put(json.dumps(e)),
                                  read_line=self._read_pasted, quiet=quiet_current_thread)
            finally:
                if token is not None:
                    reset_hermes_home_override(token)
        except Exception:  # noqa: BLE001 - a runner that cannot start is a silent exit: login_failed
            pass
        finally:
            self._events.put(self._END)

    def _read_pasted(self) -> str:
        line = self._pasted.get()
        return "" if line is None else line + "\n"

    def lines(self) -> Iterable[str]:
        while not self._terminated.is_set():
            line = self._events.get()
            if line is self._END:
                return
            yield line

    def write_line(self, text: str) -> None:
        self._pasted.put(text)

    def terminate(self) -> None:
        self._terminated.set()
        self._pasted.put(None)  # a pending paste reads EOF and the driver fails
        self._events.put(self._END)


def run_login_in_process(provider: str, flow: str, profile: str | None) -> LoginChild:
    """:func:`spawn_login_child`'s in-process twin: same arguments, same NDJSON."""
    return _ThreadChild(provider, flow, profile)


def subprocess_signin_enabled() -> bool:
    """``auth.subprocess_signin`` — off in a profile that may start no subprocess."""
    from hermes_cli.config import config_switch

    return config_switch("auth", "subprocess_signin", default=True)


def select_login_runner() -> Callable[[str, str, str | None], LoginChild]:
    return spawn_login_child if subprocess_signin_enabled() else run_login_in_process


def _advertised_methods(provider: str) -> list[str]:
    from hermes_cli.provider_browser_login import browser_login_methods

    return browser_login_methods(provider)


def _default_method(provider: str) -> str:
    from hermes_cli.provider_browser_login import default_login_method

    return default_login_method(provider)


class ProviderSignIns:
    """The live sign-in sessions of this serve — one registry, one writer per session."""

    def __init__(
        self,
        spawn: Callable[[str, str, str | None], LoginChild] = spawn_login_child,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._spawn = spawn
        self._clock = clock
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def begin(self, provider: str, flow: str | None = None, profile: str | None = None) -> dict:
        from hermes_cli.provider_login_catalog import provider_disabled

        if provider_disabled(provider):
            raise SignInRefused("provider_disabled", "invalid_params", provider=provider)
        methods = _advertised_methods(provider)
        if not methods:
            raise SignInRefused("provider_unsupported", "invalid_params", provider=provider)
        chosen = flow or _default_method(provider)
        if chosen not in methods:
            raise SignInRefused("flow_unsupported", "invalid_params", provider=provider, flows=methods)
        with self._lock:
            self._prune()
            for session in self._sessions.values():
                if session.provider == provider and session.state in ACTIVE_STATES:
                    raise SignInRefused("login_in_progress", "conflict", login_id=session.login_id)
            child = self._spawn(provider, chosen, profile)
            session = _Session(
                login_id=f"login_{secrets.token_hex(8)}", provider=provider, flow=chosen,
                child=child, started_at=self._clock(),
            )
            self._sessions[session.login_id] = session
        threading.Thread(target=self._pump, args=(session,), daemon=True, name="provider-signin").start()
        return session.view()

    def poll(self, login_id: str) -> dict:
        session = self._get(login_id)
        with session.lock:
            if session.state in ACTIVE_STATES and self._clock() - session.started_at > LOGIN_TTL_SECONDS:
                self._finish(session, "failed", "expired")
                session.child.terminate()
            return session.view()

    def complete(self, login_id: str, code: str) -> dict:
        session = self._get(login_id)
        with session.lock:
            if session.state != "awaiting_code":
                raise SignInRefused("login_not_awaiting_code", "conflict", state=session.state)
            session.state = "completing"
            session.updated_at = self._clock()
            session.child.write_line(code)
            return session.view()

    def cancel(self, login_id: str) -> dict:
        session = self._get(login_id)
        with session.lock:
            if session.state in ACTIVE_STATES:
                self._finish(session, "cancelled", "cancelled")
                session.child.terminate()
            return session.view()

    def _get(self, login_id: str) -> _Session:
        with self._lock:
            self._prune()
            session = self._sessions.get(login_id)
        if session is None:
            raise SignInRefused("login_not_found", "not_found", login_id=login_id)
        return session

    def _prune(self) -> None:
        now = self._clock()
        for key, session in list(self._sessions.items()):
            if session.state not in ACTIVE_STATES and now - session.updated_at > FINISHED_RETENTION_SECONDS:
                del self._sessions[key]

    def _finish(self, session: _Session, state: str, error_code: str | None) -> None:
        session.state = state
        session.error_code = error_code
        session.updated_at = self._clock()

    def _pump(self, session: _Session) -> None:
        """Fold the child's NDJSON into the session; a silent exit is a failure."""
        try:
            for line in session.child.lines():
                self._apply(session, line)
        except Exception:  # noqa: BLE001 - a broken pipe is an ended login, never a crash
            pass
        with session.lock:
            if session.state in ACTIVE_STATES:
                self._finish(session, "failed", "login_failed")

    def _apply(self, session: _Session, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        handler = self._EVENT_HANDLERS.get(event.get("event"))
        if handler is None:
            return
        with session.lock:
            if session.state in ACTIVE_STATES:
                handler(self, session, event)

    def _on_code(self, session: _Session, event: dict) -> None:
        session.verification_uri = str(event.get("verification_uri") or "")
        session.user_code = str(event.get("user_code") or "")
        session.state = "awaiting_code" if session.flow == "paste_code" else "awaiting_user"
        session.updated_at = self._clock()

    def _on_done(self, session: _Session, event: dict) -> None:
        if event.get("ok") is True:
            self._finish(session, "succeeded", None)

    def _on_error(self, session: _Session, event: dict) -> None:
        code = event.get("code")
        self._finish(session, "failed", code if code in CHILD_ERROR_CODES else "login_failed")

    # The child's event vocabulary, one handler per kind; unknown kinds are ignored.
    _EVENT_HANDLERS = {"code": _on_code, "done": _on_done, "error": _on_error}


_REGISTRY: ProviderSignIns | None = None
_REGISTRY_LOCK = threading.Lock()


def registry() -> ProviderSignIns:
    """This process's one sign-in registry."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = ProviderSignIns(spawn=select_login_runner())
        return _REGISTRY
