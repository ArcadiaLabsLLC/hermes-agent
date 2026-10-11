"""Refusing params readers: one validation body, each lane's own exception (D1.08).

``refuse(key, sentence)`` builds the exception a malformed value raises and the
reader raises what it is handed, so every lane keeps its error envelope — the
realm verbs' ``_Refused("invalid_request")``, chat-turn's ``ChatTurnInvalid``,
the console operations' ``ValueError`` — while the validation lives here once.
A lane supplies its constructor once, at module top.

A leaf (stdlib only) rather than a member of ``serve_rpc.params``: ``chat_turn``
reads params at module scope of its normalisers and must not import the
``serve_rpc`` package (its ``__init__`` imports every verb module, one of which
imports ``chat_turn``). The lenient ``serve_rpc.params._text_param`` (``None`` on
anything malformed) is a different contract and stays where it is.
"""

from __future__ import annotations

from typing import Callable

__layer__ = "models"

__all__ = ["Refuse", "read_flag", "read_strings", "read_text"]

#: ``(key, sentence) -> exception`` — the one shape every refusing reader takes.
Refuse = Callable[[str, str], BaseException]


def read_text(
    params: dict,
    key: str,
    *,
    refuse: Refuse,
    required: bool = False,
    limit: int | None = None,
    empty_ok: bool = True,
) -> str | None:
    """``params[key]`` stripped; ``None`` when absent (or null) and optional.

    Refused: a present non-string; an absent or blank value when ``required``; a
    blank value when ``empty_ok`` is False; a value over ``limit`` characters. A
    blank optional value is ``""`` when ``empty_ok``.
    """

    raw = params.get(key)
    if raw is None and not required:
        return None
    strict = required or not empty_ok
    if not isinstance(raw, str) or (strict and not raw.strip()):
        raise refuse(key, f"{key} must be a non-empty string" if strict else f"{key} must be a string when sent")
    value = raw.strip()
    if limit is not None and len(value) > limit:
        raise refuse(key, f"{key} must be {limit} characters or fewer")
    return value


def read_flag(params: dict, key: str, *, refuse: Refuse, default: bool = False) -> bool:
    """``params[key]`` as a bool; ``default`` when absent or null; any other type refused."""

    raw = params.get(key)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise refuse(key, f"{key} must be a boolean when sent")
    return raw


def read_strings(params: dict, key: str, *, refuse: Refuse) -> list[str] | None:
    """``params[key]`` as a list of strings; ``None`` when absent or null; anything else refused."""

    raw = params.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise refuse(key, f"{key} must be a list of strings")
    return raw
