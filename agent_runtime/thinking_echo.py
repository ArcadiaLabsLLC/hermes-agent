"""The reply-echo marker: the thinking text being relayed right now IS the reply, not reasoning.

Upstream ``agent/turn_response_intake.py::_relay_thinking`` relays a turn's reply as
``reasoning.available`` when the provider surfaced no reasoning of its own; native and relayed
thinking reach a progress callback with identical arguments. The fork's intake hunk marks that
relay with :func:`begin_reply_echo` / :func:`end_reply_echo`, and
``agent_runtime/profile_runner/progress.py`` drops a ``reasoning.available`` callback made under
it, so Mission Control shows no Thinking row that only repeats the reply. Other callback owners (CLI, TUI) are untouched: they never read it.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

__layer__ = "models"

__all__ = ["begin_reply_echo", "end_reply_echo", "is_reply_echo"]

_REPLY_ECHO: ContextVar[bool] = ContextVar("thinking_reply_echo", default=False)


def begin_reply_echo() -> Token[bool]:
    """Mark the callbacks that follow as the reply echoed as thinking; pass the token to :func:`end_reply_echo`.

    The intake's upstream relay call stays a bare line (no ``with`` block re-indenting it), so the
    mark is a begin/end pair there; ``_relay_thinking`` swallows its callback's errors itself.
    """
    return _REPLY_ECHO.set(True)


def end_reply_echo(token: Token[bool]) -> None:
    _REPLY_ECHO.reset(token)


def is_reply_echo() -> bool:
    """Whether the current callback is the reply echoed as thinking."""
    return _REPLY_ECHO.get()
