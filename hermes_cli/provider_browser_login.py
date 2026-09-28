"""Machine sign-in over Hermes's canonical account flows; no second OAuth engine."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
import re
import sys
from types import SimpleNamespace
from typing import Callable


def _persist(provider_id: str, state: dict) -> None:
    """Save a fresh login to the selected store without changing inference selection."""
    from hermes_cli.auth import _auth_file_path, _persist_provider_state_to_store
    _persist_provider_state_to_store(provider_id, state, _auth_file_path(), set_active=False)


def _codex(verify: Callable[[str, str], None], flow: str) -> None:
    """Connect an account in the selected store without choosing an inference route."""
    from hermes_cli.auth_codex import _codex_device_code_login, _save_codex_tokens
    from hermes_cli.auth_codex_browser import _codex_browser_login
    state = (_codex_browser_login(open_browser=False, on_verification=verify)
             if flow == "browser" else _codex_device_code_login(on_verification=verify))
    _save_codex_tokens(state["tokens"], last_refresh=state["last_refresh"], set_active=False)


def _xai(verify: Callable[[str, str], None], flow: str) -> None:
    """A fresh grant belongs to this profile, never the account it previously borrowed."""
    from hermes_cli.auth_xai import _xai_oauth_device_code_login
    state = _xai_oauth_device_code_login(open_browser=False, on_verification=verify)
    _persist("xai-oauth", {**state, "auth_mode": "oauth_device_code"})


def _minimax(verify: Callable[[str, str], None], flow: str) -> None:
    """Connect without changing the selected provider or model."""
    from hermes_cli.auth_minimax import _minimax_oauth_login
    state = _minimax_oauth_login(open_browser=False, on_verification=verify, persist=False)
    _persist("minimax-oauth", state)


def _nous(verify: Callable[[str, str], None], flow: str) -> None:
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
    state = _nous_device_code_login(open_browser=False, on_verification=verify)
    _persist("nous", state)
    _sync_nous_pool_from_auth_store()


#: Anthropic's PKCE page shows the operator a ``code#state`` string to paste back.
_ANTHROPIC_AUTHORIZE_URL = re.compile(r"https://claude\.ai/oauth/authorize\?\S+")


def _anthropic(verify: Callable[[str, str], None], flow: str) -> None:
    """Upstream's own ``hermes auth add anthropic --type oauth``, with its terminal swapped.

    ``run_hermes_oauth_login_pure`` prints the authorize link and ``input()``s the
    pasted code; both names are shadowed on that one module for this one call,
    so the link reaches ``verify`` and the code comes from this child's stdin
    (``runtime.provider.signin.complete`` writes it). PKCE, the state check, the
    exchange and the pool write stay upstream's. The browser is not auto-opened,
    matching every other driver's ``open_browser=False``.
    """
    from agent import anthropic_credentials as anthropic_mod
    from hermes_cli import auth as auth_mod
    from hermes_cli.auth_commands import auth_add_command

    seen: list[str] = []

    def shown(*values, **_kwargs) -> None:
        for match in _ANTHROPIC_AUTHORIZE_URL.finditer(" ".join(str(v) for v in values)):
            if not seen:
                seen.append(match.group(0))
                verify(match.group(0), "")

    def pasted(_prompt: str = "") -> str:
        if not seen:
            raise RuntimeError("anthropic_authorize_url_missing")
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line

    swaps = {(anthropic_mod, "print"): shown, (anthropic_mod, "input"): pasted,
             (auth_mod, "_can_open_graphical_browser"): lambda: False}
    saved = {key: key[0].__dict__.get(key[1], _ABSENT) for key in swaps}
    try:
        for (module, name), value in swaps.items():
            setattr(module, name, value)
        auth_add_command(SimpleNamespace(provider="anthropic", auth_type="oauth", label=None, priority=None))
    finally:
        for (module, name), value in saved.items():
            if value is _ABSENT:
                delattr(module, name)
            else:
                setattr(module, name, value)


_ABSENT = object()

_DRIVERS = {"openai-codex": _codex, "xai-oauth": _xai, "minimax-oauth": _minimax, "nous": _nous,
            "anthropic": _anthropic}


def supports_browser_login(provider: str) -> bool:
    return provider in _DRIVERS


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


def browser_login_command(provider: str, *, home: str, flow: str | None = None) -> int:
    """One owned child, one selected home, one terminal NDJSON event."""
    output = sys.stdout

    def emit(event: dict) -> None:
        output.write(json.dumps({**event, "home": home}) + "\n")
        output.flush()

    def verify(url: str, code: str) -> None:
        emit({"event": "code", "verification_uri": url, "user_code": code})
        emit({"event": "pending"})

    methods = browser_login_methods(provider)
    chosen = flow or default_login_method(provider)
    if chosen not in methods:
        emit({"event": "error", "ok": False, "code": "unsupported_flow"})
        return 1
    previous_logging = logging.root.manager.disable
    try:
        # Canonical CLI helpers retain their terminal UX. It is not this wire protocol.
        logging.disable(logging.CRITICAL)
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
            _DRIVERS[provider](verify, chosen)
    except (Exception, SystemExit, KeyboardInterrupt) as error:
        # Never serialize the exception message, response body, or token payload.
        codes = {"codex_browser_port_busy": "browser_busy",
                 "codex_browser_callback_timeout": "expired",
                 "codex_browser_auth_denied": "denied", "access_denied": "denied",
                 "expired_token": "expired"}
        code = "cancelled" if isinstance(error, KeyboardInterrupt) else codes.get(getattr(error, "code", None), "login_failed")
        emit({"event": "error", "ok": False, "code": code, "reason": "Sign-in did not finish."})
        return 1
    finally:
        logging.disable(previous_logging)
    emit({"event": "done", "ok": True})
    return 0
