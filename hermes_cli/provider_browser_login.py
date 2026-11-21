"""Machine sign-in over Hermes's canonical account flows; no second OAuth engine."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager, redirect_stderr, redirect_stdout
from contextvars import ContextVar
import io
import json
import logging
import re
import sys
import threading
from types import SimpleNamespace
from typing import Callable, Iterator


def _persist(provider_id: str, state: dict) -> None:
    """Save a fresh login to the selected store without changing inference selection."""
    from hermes_cli.auth import _auth_file_path, _persist_provider_state_to_store
    _persist_provider_state_to_store(provider_id, state, _auth_file_path(), set_active=False)


def _codex(verify: Callable[[str, str], None], flow: str, expiry=None) -> None:
    """Connect an account in the selected store without choosing an inference route."""
    from hermes_cli.auth_codex import _codex_device_code_login, _save_codex_tokens
    from hermes_cli.auth_codex_browser import _codex_browser_login
    state = (_codex_browser_login(open_browser=False, on_verification=verify, on_expiry=expiry)
             if flow == "browser" else _codex_device_code_login(on_verification=verify, on_expiry=expiry))
    _save_codex_tokens(state["tokens"], last_refresh=state["last_refresh"], set_active=False)


def _xai(verify: Callable[[str, str], None], flow: str, expiry=None) -> None:
    """A fresh grant belongs to this profile, never the account it previously borrowed."""
    from hermes_cli.auth_xai import _xai_oauth_device_code_login
    state = _xai_oauth_device_code_login(open_browser=False, on_verification=verify, on_expiry=expiry)
    _persist("xai-oauth", {**state, "auth_mode": "oauth_device_code"})


def _minimax(verify: Callable[[str, str], None], flow: str, expiry=None) -> None:
    """Connect without changing the selected provider or model."""
    from hermes_cli.auth_minimax import _minimax_oauth_login
    state = _minimax_oauth_login(open_browser=False, on_verification=verify, persist=False, on_expiry=expiry)
    _persist("minimax-oauth", state)


def _nous(verify: Callable[[str, str], None], flow: str, expiry=None) -> None:
    """Preserve free-tier connectors, or connect a fresh account to this profile."""
    from hermes_cli import anon_auth
    from hermes_cli.auth_nous import _nous_device_code_login, _sync_nous_pool_from_auth_store

    current = anon_auth.current_nous_state()
    if current and anon_auth.is_guest_state(current):
        for state in anon_auth.run_sign_in():
            if isinstance(state, anon_auth.Code):
                verify(state.link, state.code)
            if state.terminal:
                if not state.ok:
                    raise RuntimeError("Nous sign-in did not finish")
                return
        raise RuntimeError("Nous sign-in ended without confirmation")
    state = _nous_device_code_login(open_browser=False, on_verification=verify, on_expiry=expiry)
    _persist("nous", state)
    _sync_nous_pool_from_auth_store()


#: Anthropic's PKCE page shows the operator a ``code#state`` string to paste back.
_ANTHROPIC_AUTHORIZE_URL = re.compile(r"https://claude\.ai/oauth/authorize\?\S+")


class _SignInStepFailed(RuntimeError):
    """A driver step that failed with a closed wire code (``run_browser_login`` reads ``.code``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _paste_refusal(line: str, expected_state: str) -> str | None:
    """Why a pasted Anthropic line cannot be the code for this link, or None when it can.

    The state is split exactly as upstream's ``run_hermes_oauth_login_pure`` splits it, so a
    line this passes is one upstream's CSRF guard passes too, and a line it refuses is one
    upstream would have ended the whole sign-in on.
    """
    if not line:
        return "code_empty"
    parts = line.split("#")
    return None if (parts[1] if len(parts) > 1 else "") == expected_state else "code_mismatch"


def _anthropic(verify: Callable[[str, str], None], flow: str, expiry=None) -> None:
    """Upstream's own ``hermes auth add anthropic --type oauth``, with its terminal routed.

    ``run_hermes_oauth_login_pure`` prints the authorize link and ``input()``s the pasted code.
    For this sign-in's context only (:func:`_route`), its ``print`` hands the link to ``verify``
    and its ``input`` reads the pasted-line reader — the command's stdin, or the serve's
    in-process runner's queue, which ``runtime.provider.signin.complete`` writes. Every other
    caller of those names, on any other thread, gets the real builtins: nothing is swapped
    process-wide (RT-PROVIDER-SIGN-IN-RUNS-INSIDE-THE-RUNNING-HERMES). PKCE, the state check,
    the exchange and the pool write stay upstream's. The browser is not auto-opened, matching
    every other driver's ``open_browser=False``.

    A pasted line that is empty or whose ``#state`` is not the shown link's would end
    upstream's whole sign-in; it is refused here instead (a ``code_rejected`` event with
    ``code_empty`` / ``code_mismatch``) and the next pasted line is read. A matching code
    that upstream then cannot exchange ends as ``exchange_failed``, not ``login_failed``.
    """
    from urllib.parse import parse_qs, urlsplit

    from agent import anthropic_credentials as anthropic_mod
    from hermes_cli import auth as auth_mod
    from hermes_cli.auth_commands import auth_add_command

    seen: list[str] = []
    handed: list[bool] = []

    def shown(*values, **_kwargs) -> None:
        for match in _ANTHROPIC_AUTHORIZE_URL.finditer(" ".join(str(v) for v in values)):
            if not seen:
                seen.append(match.group(0))
                verify(match.group(0), "")

    def pasted(_prompt: str = "") -> str:
        if not seen:
            raise RuntimeError("anthropic_authorize_url_missing")
        expected = parse_qs(urlsplit(seen[0]).query).get("state", [""])[0]
        while True:
            raw = _read_pasted_line()
            if not raw:
                raise EOFError
            line = raw.strip()
            refusal = _paste_refusal(line, expected)
            if refusal is None:
                handed.append(True)
                return line
            _emit_event({"event": "code_rejected", "code": refusal})

    login = _route(anthropic_mod, "run_hermes_oauth_login_pure")

    def login_or_closed_failure():
        creds = login()
        if not creds and handed:
            # Past the state check upstream returns None only when the exchange failed
            # or answered no access token: both are the exchange, never the paste.
            raise _SignInStepFailed("exchange_failed")
        return creds

    routes = {_route_key(anthropic_mod, "print"): shown, _route_key(anthropic_mod, "input"): pasted,
              _route_key(anthropic_mod, "run_hermes_oauth_login_pure"): login_or_closed_failure,
              _route_key(auth_mod, "_can_open_graphical_browser"): lambda: False}
    for module, name in ((anthropic_mod, "print"), (anthropic_mod, "input"), (auth_mod, "_can_open_graphical_browser")):
        _route(module, name)
    bound = _ROUTES.set({**(_ROUTES.get() or {}), **routes})
    try:
        auth_add_command(SimpleNamespace(provider="anthropic", auth_type="oauth", label=None, priority=None))
    finally:
        _ROUTES.reset(bound)


#: The running sign-in's routes for names :func:`_route` stood in for, keyed by :func:`_route_key`.
_ROUTES: ContextVar[dict | None] = ContextVar("provider_login_routes", default=None)
_ROUTE_LOCK = threading.Lock()


def _route_key(module, name: str) -> str:
    return f"{module.__name__}.{name}"


def _route(module, name: str) -> Callable:
    """Stand in for ``module.<name>`` with a callable that runs this context's route, else the original.

    Installed once and kept (re-installed if something replaced it): outside a sign-in's context
    it calls what was there — a module global, or the builtin of that name when the module had
    none — so no other caller sees a change. Returns the original it delegates to.
    """
    import builtins

    key = _route_key(module, name)
    with _ROUTE_LOCK:
        current = module.__dict__.get(name, _ABSENT)
        if getattr(current, "_provider_login_route", None) == key:
            return current.__wrapped__
        original = current

        def routed(*args, **kwargs):
            route = (_ROUTES.get() or {}).get(key)
            if route is None:
                route = getattr(builtins, name) if original is _ABSENT else original
            return route(*args, **kwargs)

        routed._provider_login_route = key
        routed.__wrapped__ = (lambda *a, **kw: getattr(builtins, name)(*a, **kw)) if original is _ABSENT else original
        setattr(module, name, routed)
        return routed.__wrapped__


_ABSENT = object()

_DRIVERS = {"openai-codex": _codex, "xai-oauth": _xai, "minimax-oauth": _minimax, "nous": _nous,
            "anthropic": _anthropic}


def supports_browser_login(provider: str) -> bool:
    return provider in _DRIVERS


def sign_in_providers() -> tuple[str, ...]:
    """Every provider this driver table can sign in, in table order."""
    return tuple(_DRIVERS)


def browser_login_methods(provider: str) -> list[str]:
    if provider == "openai-codex":
        return ["browser", "device_code"]
    if provider == "anthropic":
        return ["paste_code"]
    return ["device_code"] if supports_browser_login(provider) else []


def default_login_method(provider: str) -> str:
    """``device_code`` where offered, else the provider's only method."""
    methods = browser_login_methods(provider)
    return "device_code" if "device_code" in methods or not methods else methods[0]


class _Discard(io.TextIOBase):
    """Do not retain printed token-bearing exceptions, even in a memory buffer."""
    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        pass


#: Where a paste-code driver reads the pasted line; unset, this child's stdin.
_READ_LINE: ContextVar[Callable[[], str] | None] = ContextVar("provider_login_read_line", default=None)


def _read_pasted_line() -> str:
    reader = _READ_LINE.get()
    return reader() if reader is not None else sys.stdin.readline()


#: The running sign-in's event sink, for a driver event that is not its terminal one.
_EMIT: ContextVar[Callable[[dict], None] | None] = ContextVar("provider_login_emit", default=None)


def _emit_event(event: dict) -> None:
    sink = _EMIT.get()
    if sink is not None:
        sink(event)


@contextmanager
def _process_quiet() -> Iterator[None]:
    """The sign-in child owns its process: silence all of its output and logging."""
    previous_logging = logging.root.manager.disable
    try:
        # Canonical CLI helpers retain their terminal UX. It is not this wire protocol.
        logging.disable(logging.CRITICAL)
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
            yield
    finally:
        logging.disable(previous_logging)


_QUIET_THREADS: set[int] = set()
_QUIET_LOCK = threading.Lock()


class _QuietThreadStream(io.TextIOBase):
    """``sys.stdout``/``sys.stderr`` stand-in: a quiet thread's writes vanish, others pass."""

    def __init__(self, target) -> None:
        self.target = target

    def write(self, value: str) -> int:
        return len(value) if threading.get_ident() in _QUIET_THREADS else self.target.write(value)

    def flush(self) -> None:
        if threading.get_ident() not in _QUIET_THREADS:
            self.target.flush()

    def __getattr__(self, name: str):
        return getattr(self.target, name)


class _QuietThreadFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.thread not in _QUIET_THREADS


_QUIET_FILTER = _QuietThreadFilter()


def _quiet_install(quiet: bool) -> None:
    """Wrap (first thread in) or unwrap (last thread out) the process streams and root handlers."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if quiet and not isinstance(stream, _QuietThreadStream):
            setattr(sys, name, _QuietThreadStream(stream))
        elif not quiet and isinstance(stream, _QuietThreadStream):
            setattr(sys, name, stream.target)
    for handler in logging.root.handlers:
        (handler.addFilter if quiet else handler.removeFilter)(_QUIET_FILTER)


@contextmanager
def quiet_current_thread() -> Iterator[None]:
    """:func:`_process_quiet` for a sign-in that shares its process (no subprocess allowed).

    Only THIS thread's prints and root-handled log records are dropped, so the host keeps
    its own output while a driver's token-bearing prints and errors still die unseen. A
    thread the driver itself starts is not covered — the drivers print from the calling
    thread, and the wire (the ``emit`` callback) never carries their output either way.
    """
    ident = threading.get_ident()
    with _QUIET_LOCK:
        if not _QUIET_THREADS:
            _quiet_install(True)
        _QUIET_THREADS.add(ident)
    try:
        yield
    finally:
        with _QUIET_LOCK:
            _QUIET_THREADS.discard(ident)
            if not _QUIET_THREADS:
                _quiet_install(False)


def run_browser_login(
    provider: str, *, home: str, flow: str | None, emit: Callable[[dict], None],
    read_line: Callable[[], str] | None = None,
    quiet: Callable[[], AbstractContextManager[None]] = _process_quiet,
) -> int:
    """One sign-in, one selected home, one terminal event through ``emit``.

    The sign-in child (:func:`browser_login_command`) binds ``emit`` to its stdout
    and reads a pasted code from its stdin; an in-process runner binds both to
    queues and ``quiet`` to :func:`quiet_current_thread`. The drivers are the same.
    """
    def send(event: dict) -> None:
        emit({**event, "home": home})

    def verify(url: str, code: str) -> None:
        send({"event": "code", "verification_uri": url, "user_code": code})
        send({"event": "pending"})

    def expiry(started_at: float, expires_at: float) -> None:
        send({"event": "expiry", "provider_started_at": started_at, "provider_expires_at": expires_at})

    methods = browser_login_methods(provider)
    chosen = flow or default_login_method(provider)
    if chosen not in methods:
        send({"event": "error", "ok": False, "code": "unsupported_flow"})
        return 1
    reader = _READ_LINE.set(read_line)
    sink = _EMIT.set(send)
    try:
        with quiet():
            _DRIVERS[provider](verify, chosen, expiry)
    except (Exception, SystemExit, KeyboardInterrupt) as error:
        # Never serialize the exception message, response body, or token payload.
        codes = {"codex_browser_port_busy": "browser_busy",
                 "codex_browser_callback_timeout": "expired",
                 "codex_browser_auth_denied": "denied", "access_denied": "denied",
                 "expired_token": "expired", "exchange_failed": "exchange_failed"}
        code = "cancelled" if isinstance(error, KeyboardInterrupt) else codes.get(getattr(error, "code", None), "login_failed")
        send({"event": "error", "ok": False, "code": code, "reason": "Sign-in did not finish."})
        return 1
    finally:
        _EMIT.reset(sink)
        _READ_LINE.reset(reader)
    send({"event": "done", "ok": True})
    return 0


def browser_login_command(provider: str, *, home: str, flow: str | None = None) -> int:
    """One owned child, one selected home, one terminal NDJSON event."""
    output = sys.stdout

    def emit(event: dict) -> None:
        output.write(json.dumps(event) + "\n")
        output.flush()

    return run_browser_login(provider, home=home, flow=flow, emit=emit)
