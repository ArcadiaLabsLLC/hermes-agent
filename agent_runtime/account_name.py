"""The signed-in Eternia account's name, for the ``{user}`` placeholder in an agent's prompt text.

RT-BUNDLED-NEKO-USER-INJECTOR (owner 2026-11-18: "in the soul or profile md data we can put {user} and it will
take the eternia account profiles name instead of hardcoding Tony or a name"). Review w1118a.60 D1: the file
name and its key are a contract between two repositories, and THIS module owns both
(:data:`ACCOUNT_PROFILE_FILENAME`, :data:`DISPLAY_NAME_KEY`). Eternia's writer (EterniaLauncher row
``MC-AGENT-TEXT-KNOWS-THE-ACCOUNT-NAME``) reads them from a mirror generated out of this source
(EterniaLauncher ``tool/test_quality/hermes_mirrors.json``), never a hand copy.

Contract: Eternia writes ``<namespace root>/account_profile.json`` as ``{"display_name": "<name>"}`` while an
account's namespace is active and removes it on sign-out. The runtime only reads it, at turn time: the first
line of the value, trimmed and capped, else :data:`FALLBACK_NAME` (missing, empty, unreadable or malformed
file, or no namespace at all — the base root belongs to no account).

Every prompt-text reader fills through :func:`fill_user`; none reads the file itself. The stored text keeps
the literal ``{user}``: a SOUL published to a team repository carries the placeholder, never a name.

Security (D1): the file never leaves the machine. It sits at the namespace root, outside every profile home
realm and team sync read from, and ``hermes backup`` leaves it out (:data:`ACCOUNT_PROFILE_FILENAME` in
``hermes_cli/backup.py``'s root exclusions).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

__layer__ = "models"
__all__ = [
    "ACCOUNT_PROFILE_FILENAME",
    "DISPLAY_NAME_KEY",
    "FALLBACK_NAME",
    "MAX_NAME_CHARS",
    "USER_PLACEHOLDER",
    "account_display_name",
    "account_profile_path",
    "fill_user",
]

#: The file Eternia writes at the namespace root (mirrored to Eternia).
ACCOUNT_PROFILE_FILENAME = "account_profile.json"
#: Its one key (mirrored to Eternia).
DISPLAY_NAME_KEY = "display_name"
#: The exact token an agent's SOUL or profile text says.
USER_PLACEHOLDER = "{user}"
#: What ``{user}`` becomes when no account name is known.
FALLBACK_NAME = "the user"
#: A name is a name: a longer value is cut, so the file can never carry a prompt into the turn.
MAX_NAME_CHARS = 80


def account_profile_path(env: Mapping[str, str] | None = None) -> Path | None:
    """``<namespace root>/account_profile.json`` for this process, or None on the base root."""

    from hermes_cli._namespace_bootstrap import NamespaceRefused, layout, namespace_stamp

    source = os.environ if env is None else env
    ns_id = namespace_stamp(source)
    if not ns_id:
        return None
    try:
        return layout(ns_id, source, long_paths=True).root / ACCOUNT_PROFILE_FILENAME
    except NamespaceRefused:
        return None


def account_display_name(env: Mapping[str, str] | None = None) -> str:
    """The account's name: one trimmed line of ``display_name``, else :data:`FALLBACK_NAME`. Never raises."""

    try:
        path = account_profile_path(env)
        if path is None:
            return FALLBACK_NAME
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RuntimeError):
        return FALLBACK_NAME
    value = record.get(DISPLAY_NAME_KEY) if isinstance(record, dict) else None
    if not isinstance(value, str):
        return FALLBACK_NAME
    lines = value.strip().splitlines()
    name = lines[0].strip()[:MAX_NAME_CHARS].strip() if lines else ""
    return name or FALLBACK_NAME


def fill_user(text: str | None, env: Mapping[str, str] | None = None) -> str | None:
    """``text`` with every exact ``{user}`` replaced by the account's name; ``{users}`` / ``{ user }`` stay."""

    if not text or USER_PLACEHOLDER not in text:
        return text
    return text.replace(USER_PLACEHOLDER, account_display_name(env))
