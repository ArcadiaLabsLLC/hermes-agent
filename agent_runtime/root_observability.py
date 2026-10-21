"""Stamp WHICH runtime root a ``--json`` envelope was answered from.

The property that makes root bugs survive investigation: a wrong root returns
a well-formed EMPTY answer — ``ok: true, count: 0`` — indistinguishable from
genuinely-empty data. Any diagnostic that resolves its own root cannot detect
a root bug; it always confirms health (the 2026-08-12 ambient chat-history
incident: the platform-default SHADOW runtime answered every probe cleanly).

So the envelope itself must carry the answer's frame of reference. This module
is the one attach point:

* ``resolution`` — :func:`agent_runtime.resolution.resolution_payload`:
  the resolved store root, which ladder rung won, and the trace.
* ``chat_scope`` (chat lanes only) —
  :meth:`agent_runtime.chat_session_scope.ChatSessionScope.payload`: which
  chat ``state.db`` the answer read, and how that head was named.
  ``source: "ambient_home"`` beside an empty result is the tell the incident
  lacked entirely.

Both blocks are DIAGNOSTIC and additive: a consumer renders them, never
branches on them, and attaching must never be able to take a verb down — a
failed resolution is reported as a typed ``error_kind`` value, not raised.

Enforced structurally by
``tests/hermes_cli/test_harness_json_root_observability.py``: a new
``--json``-emitting ``_cmd_*`` handler that ships without this block (and
without a written ledger reason) fails CI.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

__layer__ = "stores"

__all__ = ["CharactersHomeSource", "attach_characters_home", "attach_root_observability"]


def attach_root_observability(
    payload: dict[str, Any],
    *,
    chat_scope: bool = False,
    resolution: Any = None,
) -> dict[str, Any]:
    """Additively stamp ``resolution`` (and optionally ``chat_scope``).

    Mutates and returns *payload*. Existing keys are never overwritten — a
    producer that already carries its own resolution block keeps it. Never
    raises: an unresolvable block is attached as a typed error marker, because
    "this envelope cannot say which root answered" is itself the finding.

    ``resolution`` lets a handler that already resolved the runtime (e.g.
    ``doctor``) stamp from its OWN resolution object instead of deriving a
    second one for the same envelope.
    """

    if not isinstance(payload, dict):
        return payload
    if "resolution" not in payload:
        try:
            from .resolution import resolution_payload

            payload["resolution"] = resolution_payload(resolution)
        except Exception as exc:  # accounted, never raised
            payload["resolution"] = {
                "error_kind": "resolution_unavailable",
                "error": type(exc).__name__,
            }
    if chat_scope and "chat_scope" not in payload:
        try:
            from .chat_session_scope import resolve_process_chat_scope

            # The PROCESS frame of reference. A per-conversation stamp
            # would be a different fact, and lanes that own one (e.g.
            # persona-chat history) stamp it themselves — this never
            # overwrites an existing block.
            payload["chat_scope"] = resolve_process_chat_scope().payload()
        except Exception as exc:  # accounted, never raised
            payload["chat_scope"] = {
                "error_kind": "chat_scope_unavailable",
                "error": type(exc).__name__,
            }
    return payload


class CharactersHomeSource(str, Enum):
    """Which rung named the character library a charsheet envelope answered from."""

    SHARED_CHARACTERS_ENV = "shared_characters_env"  # HERMES_SHARED_CHARACTERS names it outright
    HOME_OVERRIDE = "home_override"  # a context-local home override (a scoped persona turn)
    HERMES_HOME_ENV = "hermes_home_env"
    PLATFORM_DEFAULT = "platform_default"


def _characters_home_source() -> CharactersHomeSource:
    from hermes_constants import get_hermes_home_override

    from .profile_home import configured_hermes_home

    if os.getenv("HERMES_SHARED_CHARACTERS", "").strip():
        return CharactersHomeSource.SHARED_CHARACTERS_ENV
    if get_hermes_home_override():
        return CharactersHomeSource.HOME_OVERRIDE
    if configured_hermes_home():
        return CharactersHomeSource.HERMES_HOME_ENV
    return CharactersHomeSource.PLATFORM_DEFAULT


def attach_characters_home(payload: dict[str, Any]) -> dict[str, Any]:
    """Additively stamp ``home``: the Hermes home and the character library a charsheet verb read.

    The charsheet family answers from the install-wide library under the HERMES home
    (``agent_runtime.profile_home.get_shared_characters_dir``), not from the store root, so
    ``resolution`` would name the wrong root for it; an empty ``characters`` list from a wrong
    home is the same well-formed empty answer this module exists to expose. Same rules as
    :func:`attach_root_observability`: never overwrites, never raises, never creates the
    directory it names.
    """
    if not isinstance(payload, dict) or "home" in payload:
        return payload
    try:
        from hermes_constants import get_hermes_home
        from .profile_home import get_shared_characters_dir

        payload["home"] = {
            "hermes_home": str(get_hermes_home()),
            "characters_dir": str(get_shared_characters_dir()),
            "source": _characters_home_source().value,
        }
    except Exception as exc:  # accounted, never raised
        payload["home"] = {"error_kind": "home_unavailable", "error": type(exc).__name__}
    return payload
