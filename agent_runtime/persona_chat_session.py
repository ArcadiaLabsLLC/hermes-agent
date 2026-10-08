"""The persona chat's session row: owner, chat model override, effective model, native history tip.

Separate because it is the one reader/writer of the session DB row a chat is
bound to; the actor prewarm reads the same helpers so its signature matches.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from agent_runtime.cli_format import emit_json
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    canonical_persona_instance_id,
    chat_session_owner_instance_id,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_continuity import native_history_revision
from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE

__layer__ = "stores"
__all__ = [
    "MODEL_SELECTION_RECEIPT",
    "TURN_MODEL_RECEIPT",
    "_chat_effective_model_payload",
    "_chat_model_override_from_config",
    "_resolve_turn_model_selection",
    "chat_model_source",
    "TURN_EFFORT_RECEIPT",
    "log_model_selection",
    "reasoning_effort_label",
    "_persona_chat_bound_owner",
    "_persona_chat_native_history",
    "_persona_chat_native_revision",
    "_persona_chat_native_tip",
    "_persona_chat_session_owner",
    "_resolve_chat_model_override",
    "_safe_chat_model_override_value",
    "_session_model_config",
]


# Session creation and durability belong to ``persona_chat_durability``.

_logger = logging.getLogger(__name__)

#: One INFO line per admitted chat turn: the model it runs and the cascade tier
#: that chose it (``override`` = this chat's session override, ``instance`` =
#: the agent's instance override, ``profile`` = the persona/profile default).
TURN_MODEL_RECEIPT = "chat_turn_model root=%s provider=%s model=%s source=%s"

#: One INFO line per model write verb, applied or refused: which verb, which
#: target, the scope asked for, the choice, and the store the choice landed in.
MODEL_SELECTION_RECEIPT = (
    "model_selection verb=%s target=%s scope=%s chosen=%s outcome=%s saved=%s"
)


_CHAT_MODEL_OVERRIDE_CONFIG_KEY = "mission_control_chat_model_override"


_CHAT_PROVIDER_MODEL_RE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,200}$")


def _safe_chat_model_override_value(value, *, field: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not _CHAT_PROVIDER_MODEL_RE.fullmatch(text):
        raise ValueError(
            f"{field} contains unsupported characters; only letters, numbers, '.', '_', '-', '+', '/', ':', and '@' are allowed"
        )
    return text


def _session_row(session_db, session_id: str | None) -> dict[str, object]:
    if session_db is None or not session_id:
        return {}
    try:
        raw = session_db.get_session(session_id)
    except Exception:
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _session_model_config(session_db, session_id: str | None) -> dict[str, object]:
    raw = _session_row(session_db, session_id)
    model_config = raw.get("model_config")
    if isinstance(model_config, dict):
        return dict(model_config)
    if isinstance(model_config, str) and model_config.strip():
        try:
            decoded = json.loads(model_config)
        except Exception:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _persona_chat_session_owner(session_db, session_id: str | None) -> str | None:
    """Resolve the immutable owner of a canonical persona-chat transcript.

    SessionDB's typed ``source`` column is the authority that makes a row a
    persona chat.  Older rows predate the duplicated ownership fields in
    ``model_config``; their server-minted id still carries the exact instance
    owner.  Requiring the duplicate field made those rows visible through the
    history projection but impossible to open or message.

    New rows persist both forms.  If both are present they must agree, so a
    corrupt metadata write cannot reassign another instance's transcript.
    """

    raw = _session_row(session_db, session_id)
    if safe_assignment_token(raw.get("source")) != PERSONA_CHAT_SESSION_SOURCE:
        return None
    config = _session_model_config(session_db, session_id)
    config_source = safe_assignment_token(config.get("source"))
    if config_source and config_source != PERSONA_CHAT_SESSION_SOURCE:
        return None

    metadata_owner = safe_assignment_token(config.get("persona_instance_id")) or None
    structural_owner = chat_session_owner_instance_id(session_id)
    if metadata_owner and structural_owner and metadata_owner != structural_owner:
        return None
    owner = metadata_owner or structural_owner
    if not owner:
        return None

    # Retired singleton/operator ids are recorded as durable aliases during
    # persona-instance reconciliation.  Resolve those aliases here so history,
    # open and send all name the same current instance authority.
    try:
        from agent_runtime.persona_instance_identity import load_persona_instance_aliases

        aliases = load_persona_instance_aliases()
    except Exception:
        aliases = {}
    seen: set[str] = set()
    while owner in aliases and owner not in seen:
        seen.add(owner)
        owner = aliases[owner]
    return canonical_persona_instance_id(owner) or owner


def _persona_chat_bound_owner(session_id: str | None) -> str | None:
    """Resolve a uniquely bound root when its canonical transcript is gone.

    This is deliberately narrower than trusting a caller-supplied instance id:
    the persisted instance binding itself must name the exact root, and an
    ambiguous binding is treated as unowned.  It preserves safe cleanup of a
    stale binding without permitting a foreign-root delete.
    """

    exact_session = safe_assignment_text(session_id, limit=240)
    if not exact_session:
        return None
    matches = []
    try:
        instances = PersonaInstanceStore().list_all()
    except Exception:
        return None
    for instance in instances:
        bound = safe_assignment_text(
            getattr(instance, "default_chat_session_id", None), limit=240
        ) or safe_assignment_text(getattr(instance, "session_id", None), limit=240)
        if bound == exact_session:
            matches.append(safe_assignment_token(getattr(instance, "id", None)))
    unique = {item for item in matches if item}
    return next(iter(unique)) if len(unique) == 1 else None


def _persist_chat_model_override(
    *,
    session_db,
    session_id: str | None,
    override: dict[str, object] | None,
) -> dict[str, object]:
    current = _session_model_config(session_db, session_id)
    if override is not None:
        if override.get("clear") is True:
            current.pop(_CHAT_MODEL_OVERRIDE_CONFIG_KEY, None)
        else:
            current[_CHAT_MODEL_OVERRIDE_CONFIG_KEY] = override
    if session_db is None or not session_id:
        return current
    try:
        session_db.update_session_meta(
            session_id,
            json.dumps(current, sort_keys=True, separators=(",", ":")),
            model=(override or {}).get("model") if override else None,
        )
    except AttributeError:
        if hasattr(session_db, "sessions"):
            session = session_db.sessions.setdefault(session_id, {})
            session["model_config"] = json.dumps(current, sort_keys=True, separators=(",", ":"))
            if override and override.get("model"):
                session["model"] = override.get("model")
    return current


def _chat_model_override_from_config(model_config: dict[str, object]) -> dict[str, object] | None:
    raw = model_config.get(_CHAT_MODEL_OVERRIDE_CONFIG_KEY)
    if not isinstance(raw, dict):
        return None
    provider = _safe_chat_model_override_value(raw.get("provider"), field="provider")
    model = _safe_chat_model_override_value(raw.get("model"), field="model")
    if not provider and not model:
        return None
    return {
        "schema_version": 1,
        "provider": provider,
        "model": model,
        "source": safe_assignment_text(raw.get("source"), limit=80) or "session",
        "scope": "mission_control_chat_session",
        "updated_at": safe_assignment_text(raw.get("updated_at"), limit=80) or None,
    }


def _resolve_chat_model_override(
    *,
    session_db,
    session_id: str | None,
    requested_override: dict[str, object] | None,
) -> dict[str, object] | None:
    model_config = _persist_chat_model_override(
        session_db=session_db,
        session_id=session_id,
        override=requested_override,
    )
    return _chat_model_override_from_config(model_config)


def _chat_effective_model_payload(
    *,
    persona,
    config,
    override: dict[str, object] | None,
    instance=None,
) -> dict[str, object]:
    """Effective-model cascade for one chat turn.

    Tiers (highest wins): chat-session override > instance override >
    persona default > agent_runtime config default. ``default_*`` stays the
    persona/config tier so the instance tier is reported honestly instead of
    being folded in silently; ``agent_*`` is what future turns/runs of THIS
    agent use when no chat override is active.
    """
    default_provider = getattr(persona, "provider", None) or getattr(config, "default_provider", None)
    default_model = getattr(persona, "model", None) or getattr(config, "default_model", None)
    from agent_runtime.profile_context import resolve_persona_profile, persona_profile_scope
    # An instance whose persona left the roster still gets a summary; it has no
    # profile to scope into, so only the instance and config tiers apply.
    binding = resolve_persona_profile(persona) if persona is not None else None
    effort = getattr(instance, "reasoning_effort", None)
    reasoning = None
    if binding is not None and binding.readiness == "ready":
        with persona_profile_scope(binding):
            if not default_model or not default_provider:
                from agent_runtime.config import load_agent_runtime_config
                profile_config = load_agent_runtime_config()
                default_model = default_model or profile_config.default_model
                default_provider = default_provider or profile_config.default_provider
            effective_model = ((override or {}).get("model") or getattr(instance, "model", None)
                               or default_model)
            reasoning = reasoning_config_for(effort, effective_model)
    elif effort:
        from hermes_constants import parse_reasoning_effort
        reasoning = parse_reasoning_effort(effort)
    instance_provider = getattr(instance, "provider", None) if instance is not None else None
    instance_model = getattr(instance, "model", None) if instance is not None else None
    agent_provider = instance_provider or default_provider
    agent_model = instance_model or default_model
    provider = (override or {}).get("provider") or agent_provider
    model = (override or {}).get("model") or agent_model
    return {
        "default_provider": default_provider,
        "default_model": default_model,
        "instance_provider": instance_provider,
        "instance_model": instance_model,
        "agent_provider": agent_provider,
        "agent_model": agent_model,
        "chat_provider": (override or {}).get("provider"),
        "chat_model": (override or {}).get("model"),
        "effective_provider": provider,
        "effective_model": model,
        "effective_reasoning_effort": reasoning_effort_label(reasoning),
        "reasoning_effort_source": "instance" if effort else ("profile" if reasoning else "default"),
        "model_is_default": not bool(override and ((override.get("provider") or "") or (override.get("model") or ""))),
        "model_is_instance_override": bool(instance_provider or instance_model),
        "scope": "mission_control_chat_session",
    }


def chat_model_source(selection: dict[str, object]) -> str:
    """The cascade tier that chose ``effective_model``: override | instance | profile."""

    if selection.get("chat_provider") or selection.get("chat_model"):
        return "override"
    if selection.get("instance_provider") or selection.get("instance_model"):
        return "instance"
    return "profile"


def _resolve_turn_model_selection(
    *,
    session_db,
    session_id: str | None,
    requested_override: dict[str, object] | None,
    persona,
    config,
    instance,
) -> dict[str, object]:
    """The model ONE chat turn runs: apply the turn's own override request, read
    the session's stored one, fold the cascade, and receipt the result."""

    override = _resolve_chat_model_override(
        session_db=session_db, session_id=session_id, requested_override=requested_override,
    )
    selection = _chat_effective_model_payload(
        persona=persona, config=config, override=override, instance=instance,
    )
    _logger.info(
        TURN_MODEL_RECEIPT, session_id or "-", selection.get("effective_provider") or "-",
        selection.get("effective_model") or "-", chat_model_source(selection),
    )
    return selection


#: One INFO line per run that holds an agent: the effort its next request
#: carries, read off the agent itself (so a reused or prewarmed actor whose
#: config disagrees with ``requested`` shows the disagreement).
def reasoning_config_for(effort: str | None, model: str | None) -> dict | None:
    """The instance's effort when given, else the ACTIVE profile's
    ``agent.reasoning_effort`` (per-model override first) — the chokepoint every
    upstream surface uses. Read inside the persona's profile scope, so
    ``load_config`` is that profile's. The resident actor's
    ``turn_reasoning_config`` and the effective-model payload both resolve here."""

    from hermes_constants import parse_reasoning_effort

    if effort:
        return parse_reasoning_effort(effort)
    try:
        from hermes_cli.config import load_config
        from hermes_constants import resolve_reasoning_config

        return resolve_reasoning_config(load_config() or {}, model or "")
    except Exception:
        _logger.debug("profile reasoning effort unreadable", exc_info=True)
        return None


TURN_EFFORT_RECEIPT = (
    "chat_turn_effort root=%s turn=%s model=%s requested=%s effort=%s source=%s actor=%s"
)


def reasoning_effort_label(config) -> str | None:
    """``{"enabled": .., "effort": ..}`` as the one word the wire carries; None = no config."""

    if not isinstance(config, dict):
        return None
    if config.get("enabled") is False:
        return "none"
    return str(config.get("effort") or "") or None


def log_model_selection(*, verb: str, target: str | None, scope: str, chosen: str | None,
                        outcome: str, saved: str | None) -> None:
    _logger.info(MODEL_SELECTION_RECEIPT, verb, target or "-", scope, chosen or "-",
                 outcome, saved or "-")


def _persona_chat_native_tip(session_db, root_session_id: str) -> str:
    resolver = getattr(session_db, "resolve_resume_session_id", None)
    return resolver(root_session_id) if callable(resolver) else root_session_id


def _persona_chat_native_history(session_db, active_session_id: str) -> list[dict]:
    loader = getattr(session_db, "get_messages_as_conversation", None)
    if callable(loader):
        return list(loader(active_session_id, include_ancestors=True) or [])
    legacy = getattr(session_db, "get_messages", None)
    return list(legacy(active_session_id) or []) if callable(legacy) else []


def _persona_chat_native_revision(session_db, root_session_id: str) -> str:
    try:
        return native_history_revision(session_db, root_session_id)
    except Exception:
        history = _persona_chat_native_history(
            session_db, _persona_chat_native_tip(session_db, root_session_id)
        )
        return f"{root_session_id}:{hashlib.sha256(emit_json(history).encode('utf-8')).hexdigest()[:16]}"
