"""The per-turn ROOT-config readers: the chat-lane restore list, the workdir, the ``mission_chat_*`` knobs.

Map: ``agent_runtime/config/__init__.py``.
"""

from __future__ import annotations

import logging

from ..dispatch_session_policy import normalize_dispatch_session_policy
from ..runtime_config import MissionChatConfig
from typing import Any, Callable

from ..personas import persona_id_aliases
from ..serde import optional_str
from .loader import harness_root_config_path, load_agent_runtime_config, load_root_runtime_config
from .persona_records import _expand_machine_root_tokens
from .schema import AgentRuntimeConfig
from .sections import _compaction_threshold_tokens, _string_list

logger = logging.getLogger(__name__)

__layer__ = "policy"


def _root_knob(cfg: AgentRuntimeConfig | None, name: str, coerce: Callable[[Any], Any]) -> Any:
    """One ``mission_chat.<name>`` knob: from ``cfg`` when one is given, else from
    the ROOT config (harness-wide policy — see :func:`harness_root_config_path`).

    The six ``mission_chat_*`` readers below are this one shape; a root-config
    fault degrades to the built-in default rather than failing the turn.
    """

    default = getattr(MissionChatConfig(), name)
    if cfg is not None:
        return coerce(getattr(cfg.mission_chat, name, default))
    try:
        return coerce(getattr(load_root_runtime_config().mission_chat, name))
    except Exception:  # pragma: no cover - defensive; a config fault must not kill a turn
        logger.debug("mission_chat %s load failed; using the built-in default", name, exc_info=True)
        return default


def _compaction_knob(value: Any) -> int:
    return _compaction_threshold_tokens(value, MissionChatConfig().compaction_threshold_tokens)


def _dispatch_policy_knob(value: Any) -> str:
    return normalize_dispatch_session_policy(value, MissionChatConfig().dispatch_session_policy)


def chat_lane_restore_toolsets(persona_id: str, cfg: AgentRuntimeConfig | None = None) -> list[str]:
    """Per-persona operator override for the chat-lane toolset cost policy.

    Read from ``agent_runtime.personas.<id>.chat_lane_restore_toolsets`` in
    the ROOT ``config.yaml`` (see :func:`harness_root_config_path` — this is
    harness-global operator policy, and an active profile's own config must
    not shadow it): a list of toolsets to RESTORE onto that persona's
    operator / mission chat lane after the default policy
    (``chat_lane_toolsets.DEFAULT_CHAT_LANE_EXCLUDED_TOOLSETS``) would exclude
    them (browser / vision / heavy-dev). Restore is un-exclusion, not a grant —
    a restored toolset is only kept if the persona's own DECLARED toolsets
    already resolved it into the lane. There is no role backstop behind that:
    S61/S64 made profile/persona declarations the sole capability authority and
    ``personas.validate_toolsets`` carries no role ceiling, so the intersection
    IS the whole guarantee. See ``chat_lane_toolsets``' module docstring.

    Honors the legacy ``alice_supervisor`` ⇄ ``neko_supervisor`` alias so an
    older config keyed on either name is respected. Absent / malformed → ``[]``
    (the default policy applies unchanged)."""

    persona_id = str(persona_id or "").strip()
    if not persona_id:
        return []
    cfg = cfg or load_agent_runtime_config(harness_root_config_path())
    personas = cfg.personas if isinstance(getattr(cfg, "personas", None), dict) else {}
    keys = [persona_id, *persona_id_aliases(persona_id)]
    for key in keys:
        raw = personas.get(key)
        if isinstance(raw, dict) and "chat_lane_restore_toolsets" in raw:
            return _string_list(raw.get("chat_lane_restore_toolsets"))
    return []


def mission_chat_compaction_threshold_tokens(cfg: AgentRuntimeConfig | None = None) -> int:
    """The chat-lane compaction cap in tokens; ``0`` ⇒ no lane cap.

    Harness-wide operator policy, so it loads through
    :func:`load_root_runtime_config` for exactly the reason
    :func:`mission_chat_default_max_seconds` documents — one sticky-active
    profile's own ``config.yaml`` must not decide when every OTHER profile's
    threads compact. A config fault degrades to the shipped default rather than
    failing the turn.
    """

    return _root_knob(cfg, "compaction_threshold_tokens", _compaction_knob)


def mission_chat_clarify_token_binding(cfg: AgentRuntimeConfig | None = None) -> bool:
    """Whether a clarify answer is bound to its question's thread by token.

    Mirrors :func:`mission_chat_dispatch_session_policy` exactly, and for the
    same reason: this decides how EVERY profile's clarify round-trips thread, so
    it is harness-wide operator policy read from the ROOT config, and a config
    fault degrades to the built-in default (``True``) rather than failing the
    turn. The gate is checked at the two seams that matter — minting a ticket
    when a turn asks a question, and resolving an echoed token when a turn
    answers one — so flipping it off returns the lane to today's precedence with
    no migration and nothing to unwind."""

    return _root_knob(cfg, "clarify_token_binding", bool)


def mission_chat_dispatch_session_policy(cfg: AgentRuntimeConfig | None = None) -> str:
    """Which thread a dispatch lands in when the caller names none.

    Harness-wide operator policy, so it loads through
    :func:`load_root_runtime_config` for the same reason the budget default
    does — a sticky-active profile's own ``config.yaml`` must not be able to
    change how every OTHER profile's dispatches thread. A config fault degrades
    to the built-in default rather than failing the turn.

    The precedence rule (explicit ``session_id`` / ``new_session`` always wins
    over this) is decided in one place:
    :func:`agent_runtime.dispatch_session_policy.resolve_dispatch_session_decision`."""

    return _root_knob(cfg, "dispatch_session_policy", _dispatch_policy_knob)


def mission_chat_default_max_seconds(cfg: AgentRuntimeConfig | None = None) -> float:
    """The wall budget a mission-chat turn gets when ``--max-seconds`` is absent.

    Harness-wide operator policy, so it loads through
    :func:`load_root_runtime_config` — a sticky-active profile's own
    ``config.yaml`` must not be able to shorten (or extend) every other
    profile's turns (the same shadowing bug :func:`harness_root_config_path`
    documents for ``chat_lane_restore_toolsets``). A config fault degrades to
    the historical default rather than failing the turn."""

    return _root_knob(cfg, "default_max_seconds", float)


def resolve_mission_chat_max_seconds(
    requested: float | None, cfg: AgentRuntimeConfig | None = None
) -> float:
    """The wall budget one mission-chat turn gets — the precedence chokepoint.

    An explicit request (the CLI's ``--max-seconds``, a relay hop's chosen
    window) ALWAYS wins, including a value outside the config clamp: the clamp
    guards a deployment-wide default from a fat-fingered stanza, it is not a cap
    on a caller who states a number. Only ``None`` — "no opinion" — falls through
    to :func:`mission_chat_default_max_seconds`.

    One function so the precedence is decided in one place; the parser default is
    ``None`` precisely so "absent" and "explicitly 240" remain distinguishable.
    """

    if requested is None:
        return mission_chat_default_max_seconds(cfg)
    try:
        value = float(requested)
    except (TypeError, ValueError):
        return mission_chat_default_max_seconds(cfg)
    return value if value > 0 else mission_chat_default_max_seconds(cfg)


def mission_chat_dispatch_max_seconds(cfg: AgentRuntimeConfig | None = None) -> float:
    """The wall budget a DETACHED dispatch's target turn gets.

    Loads through :func:`load_root_runtime_config` for exactly the reason
    :func:`mission_chat_default_max_seconds` documents — a sticky-active
    profile's own ``config.yaml`` must not be able to change how every other
    profile's background work is budgeted — and degrades to the built-in
    default rather than failing the dispatch."""

    return _root_knob(cfg, "dispatch_max_seconds", float)


def mission_chat_dispatch_max_concurrent(cfg: AgentRuntimeConfig | None = None) -> int:
    """How many detached dispatches may run at once (executor width)."""

    return _root_knob(cfg, "dispatch_max_concurrent", int)


def resolve_mission_chat_dispatch_max_seconds(
    requested: float | None, cfg: AgentRuntimeConfig | None = None
) -> float:
    """The DETACHED-dispatch budget precedence chokepoint.

    Mirrors :func:`resolve_mission_chat_max_seconds` exactly — an explicit
    caller-stated number always wins, ``None`` falls through to config — so the
    two lanes cannot drift into two different precedence rules. It is a separate
    function rather than a flag on the first because they resolve DIFFERENT
    config keys, and collapsing them behind a boolean is precisely the
    fragile-flag shape this repo's rulings forbid."""

    if requested is None:
        return mission_chat_dispatch_max_seconds(cfg)
    try:
        value = float(requested)
    except (TypeError, ValueError):
        return mission_chat_dispatch_max_seconds(cfg)
    return value if value > 0 else mission_chat_dispatch_max_seconds(cfg)


def mission_chat_workdir(persona_id: str, cfg: AgentRuntimeConfig | None = None) -> str | None:
    """Per-persona repo grounding for the mission-chat lane.

    Read from ``agent_runtime.personas.<id>.workdir`` in the ROOT
    ``config.yaml`` (see :func:`harness_root_config_path`): an absolute
    directory the persona's chat turns run in, so its ``terminal`` / ``file``
    tools resolve relative paths against a real repo instead of whatever cwd the
    serve process happens to hold (G6). ``${roots.…}`` machine tokens are
    expanded here, exactly like ``repo_scope``, so the stanza stays portable
    across machines; an unresolvable token is left literal and surfaces as a
    typed ``mission_chat_workdir_unresolved`` row rather than a fabricated path.

    Honors the legacy ``alice_supervisor`` ⇄ ``neko_supervisor`` alias.
    Absent / blank → ``None`` (the lane keeps the process cwd, unchanged).
    Resolution of the whole ladder (config → workspace pointer → repo_scope →
    cwd) lives in :mod:`agent_runtime.mission_chat_workdir`; this only reads the
    key."""

    persona_id = str(persona_id or "").strip()
    if not persona_id:
        return None
    cfg = cfg or load_agent_runtime_config(harness_root_config_path())
    personas = cfg.personas if isinstance(getattr(cfg, "personas", None), dict) else {}
    keys = [persona_id, *persona_id_aliases(persona_id)]
    for key in keys:
        raw = personas.get(key)
        if isinstance(raw, dict) and "workdir" in raw:
            value = optional_str(raw.get("workdir"))
            if value is None:
                return None
            return _expand_machine_root_tokens(
                value, field=f"agent_runtime.personas.{key}.workdir"
            )
    return None
