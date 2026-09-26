"""The ``agent_runtime.*`` section parsers and the coercers they share.

Map: ``agent_runtime/config/__init__.py``.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from agent_runtime import yaml_io

from ..dispatch_session_policy import normalize_dispatch_session_policy
from ..permission_modes import (
    FALLBACK_DEFAULT_PERMISSION_MODE,
    SHIPPED_DEFAULT_PERMISSION_MODE,
    SUPPORTED_PERMISSION_MODES,
    normalize_permission_mode,
)
from ..serde import positive_float, positive_int
from ..runtime_config import CoordinatorPermissionConfig, EventLogConfig, McpAdmissionConfig, MissionChatConfig, PersonaChatConfig, ReadModelConfig, SupervisionConfig, TerminalEnvelopeConfig, ToolPermissionConfig
from .schema import (
    MCP_ADMISSION_MAX_TOOL_CALLS_CEILING,
    MISSION_CHAT_MAX_COMPACTION_TOKENS,
    MISSION_CHAT_MAX_MAX_SECONDS,
    MISSION_CHAT_MIN_COMPACTION_TOKENS,
    MISSION_CHAT_MIN_MAX_SECONDS,
    TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN,
)

__layer__ = "policy"


def _mapping(raw: Any) -> dict[str, Any]:
    """A section's mapping, or ``{}`` for any other YAML shape (a malformed block is an absent one)."""

    return raw if isinstance(raw, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                decoded = yaml_io.load(text)
            except yaml_io.YAMLError:
                decoded = None
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
        return [text]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _read_model_config(raw: dict[str, Any]) -> ReadModelConfig:
    # UNKNOWN KEYS ARE IGNORED, not rejected — every field is read through
    # ``raw.get(key, default)``, the same property the top-level loader states at
    # ``load_agent_runtime_config``. That is load-bearing for Stage 6: the live
    # operator root still carries ``read_model.enabled: true``, and a config that
    # sets a key the runtime no longer implements must load and be ignored rather
    # than fault the whole runtime out of a boot.
    raw = _mapping(raw)
    defaults = ReadModelConfig()
    filename = str(raw.get("db_filename", defaults.db_filename) or defaults.db_filename).strip()
    if not filename or "/" in filename or "\\" in filename:
        filename = defaults.db_filename
    return ReadModelConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        serve_snapshot_from_db=bool(raw.get("serve_snapshot_from_db", defaults.serve_snapshot_from_db)),
        db_filename=filename,
        delta_patches=bool(raw.get("delta_patches", defaults.delta_patches)),
    )


def _persona_chat_config(raw: dict[str, Any]) -> PersonaChatConfig:
    raw = _mapping(raw)
    defaults = PersonaChatConfig()
    return PersonaChatConfig(
        hot_sessions_enabled=bool(
            raw.get("hot_sessions_enabled", defaults.hot_sessions_enabled)
        ),
        max_hot_sessions=_clamped_positive_int(
            raw.get("max_hot_sessions"),
            defaults.max_hot_sessions,
            minimum=1,
            maximum=64,
        ),
        idle_ttl_seconds=_clamped_positive_int(
            raw.get("idle_ttl_seconds"),
            defaults.idle_ttl_seconds,
            minimum=30,
            maximum=86_400,
        ),
    )


def _mission_chat_config(raw: dict[str, Any]) -> MissionChatConfig:
    """Parse ``agent_runtime.mission_chat`` (see :class:`MissionChatConfig`).

    An absent / malformed value keeps the historical 240 s CLI default, and a
    present one is clamped to a window that can actually host a turn — the
    checkpoint reserve eats the whole budget below ~30 s, and above a day a
    single turn outlives the mission deadline. Clamping (rather than rejecting)
    keeps a fat-fingered stanza from failing every turn on the lane."""

    raw = _mapping(raw)
    defaults = MissionChatConfig()
    return MissionChatConfig(
        default_max_seconds=_clamped_positive_float(
            raw.get("default_max_seconds"),
            defaults.default_max_seconds,
            minimum=MISSION_CHAT_MIN_MAX_SECONDS,
            maximum=MISSION_CHAT_MAX_MAX_SECONDS,
        ),
        dispatch_session_policy=normalize_dispatch_session_policy(
            raw.get("dispatch_session_policy"),
            defaults.dispatch_session_policy,
        ),
        clarify_token_binding=bool(
            raw.get("clarify_token_binding", defaults.clarify_token_binding)
        ),
        # Same clamp window as ``default_max_seconds``, and for the same reasons
        # (below 30 s the checkpoint reserve leaves no working window; above a
        # day one turn outlives the mission clock) — a detached dispatch is a
        # LONGER turn, not a differently-bounded one.
        dispatch_max_seconds=_clamped_positive_float(
            raw.get("dispatch_max_seconds"),
            defaults.dispatch_max_seconds,
            minimum=MISSION_CHAT_MIN_MAX_SECONDS,
            maximum=MISSION_CHAT_MAX_MAX_SECONDS,
        ),
        dispatch_max_concurrent=_clamped_positive_int(
            raw.get("dispatch_max_concurrent"),
            defaults.dispatch_max_concurrent,
            minimum=1,
            maximum=32,
        ),
        compaction_threshold_tokens=_compaction_threshold_tokens(
            raw.get("compaction_threshold_tokens"), defaults.compaction_threshold_tokens
        ),
    )


def _compaction_threshold_tokens(value: Any, default: int) -> int:
    """Coerce the chat-lane compaction cap. ``0`` means "no lane cap".

    Deliberately NOT ``_clamped_positive_int``: that helper maps every
    non-positive value onto the default, which would make the documented
    rollback spelling (``compaction_threshold_tokens: 0``) silently re-enable
    the very cap it asks to remove. An operator who writes a disable must get a
    disable. Absent / unparseable still falls back to the shipped default —
    that is a missing opinion, not a stated one.
    """

    if value is None or isinstance(value, bool):
        return int(default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    if number <= 0:
        return 0
    return max(
        MISSION_CHAT_MIN_COMPACTION_TOKENS,
        min(MISSION_CHAT_MAX_COMPACTION_TOKENS, number),
    )


def _event_log_config(raw: dict[str, Any]) -> EventLogConfig:
    raw = _mapping(raw)
    defaults = EventLogConfig()
    cap = raw.get("rotation_cap_bytes", defaults.rotation_cap_bytes)
    try:
        cap_int = int(cap)
    except (TypeError, ValueError):
        cap_int = defaults.rotation_cap_bytes
    # Negative is meaningless; clamp to 0 (rotation disabled). 0 is a valid
    # explicit "never rotate" (legacy unbounded live file).
    if cap_int < 0:
        cap_int = 0
    return EventLogConfig(rotation_cap_bytes=cap_int)


def _supervision_config(raw: dict[str, Any]) -> SupervisionConfig:
    raw = _mapping(raw)
    defaults = SupervisionConfig()
    return SupervisionConfig(
        child_events_enabled=bool(raw.get("child_events_enabled", defaults.child_events_enabled)),
    )


def _coordinator_permission_config(raw: dict[str, Any]) -> CoordinatorPermissionConfig:
    return CoordinatorPermissionConfig(
        max_spawns=max(0, int(raw.get("max_spawns", 0))),
        may_kill_own=bool(raw.get("may_kill_own", True)),
        may_kill_others=bool(raw.get("may_kill_others", False)),
    )


def _mcp_admission_config(raw: dict[str, Any]) -> McpAdmissionConfig:
    """Parse the root MCP-admission controls.

    Server authority lives in each persona profile.  Unknown keys, including
    the retired ``roles`` policy table, are ignored like other removed config
    fields.  The connect budget is clamped so a config typo cannot park a chat
    turn behind a capability probe (or make the probe useless by rounding to
    zero).

    ``max_tool_calls_per_run`` is clamped the same way and for the same reason,
    with one extra property: there is no way to spell "unlimited". A missing,
    zero, negative or unparseable value falls back to the default, and the upper
    clamp refuses a fat-fingered ``1000000`` — an admitted MCP surface with no
    call bound is precisely the failure the budget exists to prevent, so it must
    not be reachable by a config typo either.
    """

    raw = _mapping(raw)
    defaults = McpAdmissionConfig()
    timeout = positive_float(raw.get("connect_timeout_seconds"))
    if timeout is None or timeout <= 0:
        timeout = defaults.connect_timeout_seconds
    return McpAdmissionConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        connect_timeout_seconds=min(120.0, max(1.0, float(timeout))),
        max_tool_calls_per_run=_clamped_positive_int(
            raw.get("max_tool_calls_per_run"),
            defaults.max_tool_calls_per_run,
            minimum=1,
            maximum=MCP_ADMISSION_MAX_TOOL_CALLS_CEILING,
        ),
    )


def _tool_permission_config(raw: dict[str, Any]) -> ToolPermissionConfig:
    """Parse ``agent_runtime.tool_permissions`` — a fault can only NARROW.

    Absent / blank ⇒ the shipped default (``unbounded``, operator ruling
    2026-08-09). A value the runtime does not recognize is NOT silently ignored
    and is NOT read as the shipped default: it produces a typed issue row and
    falls back to ``profile_default``, because a config the runtime could not
    parse must never resolve to more capability than the operator wrote. That
    asymmetry (wide shipped default, narrow fault fallback) is deliberate and is
    the one place this block behaves like the deny-by-default policies beside it.
    """

    raw = _mapping(raw)
    if "default_mode" not in raw:
        return ToolPermissionConfig()
    text = normalize_permission_mode(raw.get("default_mode"))
    if not text:
        return ToolPermissionConfig()
    if text not in SUPPORTED_PERMISSION_MODES:
        issue = {
            "code": TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN,
            "subject": "agent_runtime.tool_permissions.default_mode",
            "summary": (
                f"'{raw.get('default_mode')}' is not a permission mode; the runtime default "
                f"falls back to '{FALLBACK_DEFAULT_PERMISSION_MODE}' (never to "
                f"'{SHIPPED_DEFAULT_PERMISSION_MODE}') so a config fault cannot widen access."
            ),
            "fix_hint": (
                "Valid modes: " + ", ".join(sorted(SUPPORTED_PERMISSION_MODES)) + "."
            ),
        }
        return ToolPermissionConfig(
            default_mode=FALLBACK_DEFAULT_PERMISSION_MODE, issues=(issue,)
        )
    return ToolPermissionConfig(default_mode=text)


def _terminal_envelope_config(raw: dict[str, Any]) -> TerminalEnvelopeConfig:
    """Parse ``agent_runtime.terminal_envelope`` — deny-by-default at every step.

    Structural parsing only: this keeps well-shaped ``<role>.<lane>: [classes]``
    entries and drops anything else. Whether a *named* class is a real class,
    and whether it is grantable at all, is decided by
    ``terminal_envelope.resolve_terminal_envelope_grants`` so an unknown or
    non-grantable class produces a TYPED config issue at decision time instead
    of vanishing silently here. A malformed block must never read as "allow": a
    non-mapping ``grants`` or a non-mapping lane map collapses to the empty
    grant table, and a non-list class list is carried through verbatim so the
    resolver can report the shape fault rather than leave the operator staring
    at a stanza that appears to be in force.
    """

    raw = _mapping(raw)
    grants: dict[str, dict[str, Any]] = {}
    raw_grants = raw.get("grants")
    if isinstance(raw_grants, dict):
        for role, lanes in raw_grants.items():
            if not isinstance(lanes, dict):
                continue
            parsed_lanes: dict[str, Any] = {}
            for lane, classes in lanes.items():
                if not isinstance(classes, (list, tuple, set, frozenset)):
                    parsed_lanes[str(lane)] = classes
                    continue
                names = _string_list(classes)
                if names:
                    parsed_lanes[str(lane)] = names
            if parsed_lanes:
                grants[str(role)] = parsed_lanes
    return TerminalEnvelopeConfig(grants=grants)


def _clamped_positive_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    number = positive_int(value, default=default)
    return max(minimum, min(maximum, number))


def _clamped_positive_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    number = positive_float(value)
    if number is None:
        number = default
    return max(minimum, min(maximum, float(number)))


#: THE section table (rule 12): one row per ``RuntimeConfig`` section, the key
#: its ``agent_runtime.<key>`` block and its dataclass field. The loader iterates
#: it; ``tests/agent_runtime/test_config.py`` pins its keys to the dataclass's
#: section fields, because a missing row is silent — the field keeps its default.
SECTION_PARSERS: Mapping[str, Callable[[Any], Any]] = {
    "read_model": _read_model_config,
    "persona_chat": _persona_chat_config,
    "event_log": _event_log_config,
    "supervision": _supervision_config,
    "coordinator_permissions": _coordinator_permission_config,
    "mission_chat": _mission_chat_config,
    "mcp_admission": _mcp_admission_config,
    "terminal_envelope": _terminal_envelope_config,
    "tool_permissions": _tool_permission_config,
}
