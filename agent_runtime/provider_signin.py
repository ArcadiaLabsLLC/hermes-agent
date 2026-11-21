"""Provider sign-in as a pollable session, run inside this Hermes.

``runtime.provider.signin.*`` never runs OAuth itself. Each session runs
``hermes_cli.provider_browser_login.run_browser_login`` — the driver table over upstream's
own flows, the same thing ``hermes harness auth login --json`` runs from a terminal — on a
thread of this process (:class:`_ThreadChild`), never in a second Hermes
(RT-PROVIDER-SIGN-IN-RUNS-INSIDE-THE-RUNNING-HERMES). Its events arrive on a queue as the
same NDJSON the command prints, and this module turns them into state a client can poll:

``starting`` -> ``awaiting_user`` (open the link, enter the code) or
``awaiting_code`` (open the link, paste the code back through ``complete``) ->
``completing`` -> ``succeeded`` | ``failed`` | ``cancelled``.

A session holds the verification link and user code the driver's ``on_verification``
callback surfaced, never a token: the tokens land in the store upstream's own save path
picks. The driver's prints and log records are dropped for its thread only
(``quiet_current_thread``), and the queue carries nothing but the events, so nothing here
has to redact them. A cancel or an expiry stops the driver's thread where it stands
(:meth:`_ThreadChild.terminate`), so a cancelled browser sign-in frees its loopback port and
a cancelled device-code poll never saves a grant afterwards.

The runner is injectable (:class:`ProviderSignIns`) so tests drive fakes.
"""

from __future__ import annotations

import contextlib
import contextvars
import ctypes
import json
import logging
import math
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Protocol

__layer__ = "stores"

logger = logging.getLogger(__name__)

__all__ = [
    "LOGIN_TTL_SECONDS",
    "LoginChild",
    "ProviderSignIns",
    "SignInCancelled",
    "SignInRefused",
    "registry",
    "run_login_in_process",
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
    {"browser_busy", "expired", "denied", "cancelled", "login_failed", "unsupported_flow", "unknown_provider",
     "exchange_failed"}
)
#: Why a pasted code was refused before any exchange (the child's ``code_rejected`` event);
#: the session goes back to ``awaiting_code`` and the view names it as ``code_refusal``.
CODE_REFUSAL_CODES = frozenset({"code_empty", "code_mismatch"})


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
    provider_started_at: float | None = None
    provider_expires_at: float | None = None
    error_code: str | None = None
    code_refusal: str | None = None
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
            "provider_started_at": self.provider_started_at,
            "provider_expires_at": self.provider_expires_at,
            "updated_at": self.updated_at or self.started_at,
        }
        if self.verification_uri is not None:
            row["verification_uri"] = self.verification_uri
            row["user_code"] = self.user_code or ""
        if self.error_code is not None:
            row["error_code"] = self.error_code
        if self.code_refusal is not None:
            row["code_refusal"] = self.code_refusal
        return row


class SignInCancelled(KeyboardInterrupt):
    """Raised inside a sign-in's thread when its session is cancelled or expires.

    A ``KeyboardInterrupt`` because that is how upstream's drivers are told to stop at a
    terminal: each one's own handler and ``finally`` run (the Codex browser flow shuts its
    loopback listener down), and a driver's ``except Exception`` cannot swallow it.
    """


def _raise_in_thread(ident: int, exc_type: type[BaseException]) -> bool:
    """Ask CPython to raise ``exc_type`` in thread ``ident`` at its next bytecode; True when queued.

    The thread's own ``except`` / ``finally`` blocks run; a blocking call (a ``sleep``, a socket
    read with its timeout) finishes first. False where the interpreter offers no such call.
    """
    try:
        setter = ctypes.pythonapi.PyThreadState_SetAsyncExc
    except AttributeError:
        return False
    return setter(ctypes.c_ulong(ident), ctypes.py_object(exc_type)) == 1


class _ThreadChild:
    """One sign-in on a thread of this process: NDJSON events on one queue, the pasted code on another.

    Runs ``hermes_cli.provider_browser_login.run_browser_login`` — what
    ``hermes harness auth login --json`` runs — on a daemon thread in the caller's context. The
    driver's prints and log records are dropped for that thread only (``quiet_current_thread``).
    ``terminate`` ends the stream, fails a pending paste and raises :class:`SignInCancelled` in the
    driver's thread while the driver is running, so the flow stops where it stands instead of
    running to the provider's expiry.
    """

    _END = object()

    def __init__(self, provider: str, flow: str, profile: str | None) -> None:
        self._events: queue.Queue = queue.Queue()
        self._pasted: queue.Queue = queue.Queue()
        self._terminated = threading.Event()
        #: Held while the driver's thread may be stopped: ``terminate`` raises into it only then.
        self._driver_lock = threading.Lock()
        self._driver_ident: int | None = None
        context = contextvars.copy_context()
        self._thread = threading.Thread(target=context.run, args=(self._run, provider, flow, profile),
                                        daemon=True, name="provider-signin-in-process")
        self._thread.start()

    def _run(self, provider: str, flow: str, profile: str | None) -> None:
        try:
            self._drive(provider, flow, profile)
        except BaseException:  # a runner that cannot start, or a stop landing late, is a silent exit
            pass
        finally:
            self._events.put(self._END)

    def _drive(self, provider: str, flow: str, profile: str | None) -> None:
        from hermes_cli.auth_noninteractive import resolve_target_home
        from hermes_cli.provider_browser_login import quiet_current_thread, run_browser_login
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        home, applied_profile = resolve_target_home(profile)
        token = set_hermes_home_override(home) if applied_profile is not None else None
        try:
            run_browser_login(provider, home=home, flow=flow, emit=lambda e: self._events.put(json.dumps(e)),
                              read_line=self._read_pasted, quiet=lambda: self._stoppable(quiet_current_thread()))
        finally:
            if token is not None:
                reset_hermes_home_override(token)

    @contextlib.contextmanager
    def _stoppable(self, quiet: contextlib.AbstractContextManager[None]) -> Iterator[None]:
        """The driver's span, inside its quiet scope: the only span ``terminate`` raises into.

        Entered after the thread is silenced and left before it is unsilenced, so a stop never
        lands inside the quiet scope's own bookkeeping.
        """
        with quiet:
            with self._driver_lock:
                if self._terminated.is_set():
                    raise SignInCancelled()
                self._driver_ident = threading.get_ident()
            try:
                yield
            finally:
                with self._driver_lock:
                    self._driver_ident = None

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
        with self._driver_lock:
            first = not self._terminated.is_set()
            self._terminated.set()
            if first and self._driver_ident is not None:
                _raise_in_thread(self._driver_ident, SignInCancelled)
        self._pasted.put(None)  # a pending paste reads EOF and the driver fails
        self._events.put(self._END)

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the driver's thread; True when it has ended (tests, and a clean serve stop)."""
        self._thread.join(timeout)
        return not self._thread.is_alive()


def run_login_in_process(provider: str, flow: str, profile: str | None) -> LoginChild:
    """Start one sign-in on a thread of this Hermes (see :class:`_ThreadChild`)."""
    return _ThreadChild(provider, flow, profile)


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
        spawn: Callable[[str, str, str | None], LoginChild] = run_login_in_process,
        clock: Callable[[], float] = time.time,
        signed_in: Callable[[str], Any] | None = None,
    ) -> None:
        self._spawn = spawn
        self._clock = clock
        self._signed_in = signed_in or _seed_default_model
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
            session.code_refusal = None
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
        if state == "failed":
            # The closed code only, never the child's text: it is what says which failure an operator hit.
            logger.warning("provider sign-in %s (%s) failed: %s", session.login_id, session.provider, error_code)
        session.state = state
        session.error_code = error_code
        session.updated_at = self._clock()

    def _pump(self, session: _Session) -> None:
        """Fold the child's NDJSON into the session; a silent exit is a failure."""
        try:
            for line in session.child.lines():
                self._apply(session, line)
        except Exception:  # a broken pipe is an ended login, never a crash
            pass
        with session.lock:
            if session.state in ACTIVE_STATES:
                self._finish(session, "failed", "login_failed")
            succeeded = session.state == "succeeded"
        if succeeded:
            self._signed_in(session.provider)

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

    def _on_expiry(self, session: _Session, event: dict) -> None:
        start, end = event.get("provider_started_at"), event.get("provider_expires_at")
        if (not isinstance(start, (int, float)) or isinstance(start, bool)
                or not isinstance(end, (int, float)) or isinstance(end, bool)
                or not math.isfinite(start) or not math.isfinite(end) or start <= 0 or end <= start):
            return
        session.provider_started_at = float(start)
        session.provider_expires_at = float(end)
        session.updated_at = self._clock()

    def _on_done(self, session: _Session, event: dict) -> None:
        if event.get("ok") is True:
            self._finish(session, "succeeded", None)

    def _on_code_rejected(self, session: _Session, event: dict) -> None:
        """A pasted code the child refused before any exchange: ask for the code again."""
        if session.state != "completing":
            return
        code = event.get("code")
        session.code_refusal = code if code in CODE_REFUSAL_CODES else "code_mismatch"
        session.state = "awaiting_code"
        session.updated_at = self._clock()
        logger.info("provider sign-in %s (%s) code refused: %s", session.login_id, session.provider,
                    session.code_refusal)

    def _on_error(self, session: _Session, event: dict) -> None:
        code = event.get("code")
        self._finish(session, "failed", code if code in CHILD_ERROR_CODES else "login_failed")

    # The child's event vocabulary, one handler per kind; unknown kinds are ignored.
    _EVENT_HANDLERS = {"expiry": _on_expiry, "code": _on_code, "code_rejected": _on_code_rejected,
                       "done": _on_done, "error": _on_error}


def _seed_default_model(provider: str) -> None:
    """A signed-in provider gives an install with no default model upstream's recommended one
    (RT-FU-A-PHONE-SIGNED-IN-TO-ONE-PROVIDER-GIVES-ITS-AGENTS-NO-MODEL; never raises)."""
    from agent_runtime.runtime_default_model import seed_default_model_after_signin

    seed_default_model_after_signin(provider, requested_by="runtime.provider.signin")


_REGISTRY: ProviderSignIns | None = None
_REGISTRY_LOCK = threading.Lock()


def registry() -> ProviderSignIns:
    """This process's one sign-in registry."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = ProviderSignIns()
        return _REGISTRY
