"""The persona chat's session row: owner, chat model override, effective model, native history tip.

Separate because it is the one reader/writer of the session DB row a chat is
bound to; the actor prewarm reads the same helpers so its signature matches.
"""

from __future__ import annotations

import hashlib
import json
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
from hermes_cli.harness_support import PERSONA_CHAT_SESSION_SOURCE

__layer__ = "stores"
__all__ = [
    "_chat_effective_model_payload",
    "_chat_model_override_from_config",
    "_persona_chat_bound_owner",
    "_persona_chat_native_history",
    "_persona_chat_native_revision",
    "_persona_chat_native_tip",
    "_persona_chat_session_owner",
    "_resolve_chat_model_override",
    "_safe_chat_model_override_value",
    "_session_model_config",
]


# ``PersonaChatPersistenceError``, ``_persona_chat_persistence_failed``,
# ``_default_persona_session_db`` and ``_ensure_persona_chat_session`` used to be
# defined HERE. They moved to ``agent_runtime.persona_chat_durability`` (imported
# at the top of this part under the same private names) because chat-root
# durability was a CLI-lane-only concern for as long as it lived in this file:
# every call site was an argv handler, so ``agent_runtime``'s one-call create
# lane — the one the launcher's drag-drop reaches over RPC — structurally could
# not reach it and minted phantom roots. See that module's docstring.


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
        "model_is_default": not bool(override and ((override.get("provider") or "") or (override.get("model") or ""))),
        "model_is_instance_override": bool(instance_provider or instance_model),
        "scope": "mission_control_chat_session",
    }


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
