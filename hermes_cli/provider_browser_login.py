"""Machine sign-in over Hermes's canonical account flows; no second OAuth engine."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
import sys
from typing import Callable


def _codex(verify: Callable[[str, str], None], flow: str) -> None:
    from hermes_cli.auth_codex import login_codex_account
    login_codex_account(verify, flow=flow)


def _xai(verify: Callable[[str, str], None], flow: str) -> None:
    from hermes_cli.auth_xai import login_xai_account
    login_xai_account(verify)


def _minimax(verify: Callable[[str, str], None], flow: str) -> None:
    from hermes_cli.auth_minimax import login_minimax_account
    login_minimax_account(verify)


def _nous(verify: Callable[[str, str], None], flow: str) -> None:
    from hermes_cli.auth_nous import login_nous_account
    login_nous_account(verify)


_DRIVERS = {"openai-codex": _codex, "xai-oauth": _xai, "minimax-oauth": _minimax, "nous": _nous}


def supports_browser_login(provider: str) -> bool:
    return provider in _DRIVERS


def browser_login_methods(provider: str) -> list[str]:
    if provider == "openai-codex":
        return ["browser", "device_code"]
    return ["device_code"] if supports_browser_login(provider) else []


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
    chosen = flow or "device_code"
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


def persist_provider_login(provider_id: str, state: Dict[str, Any]) -> Path:
    """Save a fresh login to the selected store without changing inference selection."""
    return _persist_provider_state_to_store(provider_id, state, _auth_file_path(), set_active=False)


def login_codex_account(on_verification, *, flow="device_code") -> None:
    """Connect an account in the selected store without choosing an inference route."""
    from hermes_cli.auth_codex_browser import _codex_browser_login
    state = (_codex_browser_login(open_browser=False, on_verification=on_verification)
             if flow == "browser" else _codex_device_code_login(on_verification=on_verification))
    _save_codex_tokens(state["tokens"], last_refresh=state["last_refresh"], set_active=False)


def login_minimax_account(on_verification) -> None:
    """Connect without changing the selected provider or model."""
    from hermes_cli.auth import persist_provider_login
    state = _minimax_oauth_login(open_browser=False, on_verification=on_verification, persist=False)
    persist_provider_login("minimax-oauth", state)
