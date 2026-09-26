"""SessionDB reads for the roster: the session list, one session's row, and the fields it projects.

Separate because it is the package's one SessionDB reader for session rows
(the transcript itself is read through ``curation``).
"""

from __future__ import annotations

import json
from typing import Any

from ..clock import iso_timestamp
from ..models import PersonaInstance
from ..persona_assignments import (
    persona_instance_id_for,
    safe_assignment_text,
    safe_assignment_token,
)
from ..serde import positive_int
from .curation import _safe_curated_messages
from .text import _INTERNAL_SCAFFOLDING_MARKERS, _safe_display_text
from .trace_rows import _bounded_message_tail
from .vocabulary import (
    CHAT_REDACTION_UNKNOWN,
    DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    _CHAT_MODEL_OVERRIDE_CONFIG_KEY,
    canonical_chat_persona_id,
)

__layer__ = "stores"
__all__ = [
    "_list_sessions",
    "_get_session_row",
    "_default_session_db",
    "_mission_assignment_for",
    "_history_row",
    "_model_config",
    "_persisted_persona_instance_id",
    "_persona_chat_candidate_sort_key",
    "_infer_persona_id",
]


def _list_sessions(
    db: Any,
    *,
    limit: int,
    include_children: bool,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        return list(
            db.list_sessions_rich(
                source=source,
                exclude_sources=exclude_sources,
                limit=limit,
                include_children=include_children,
                min_message_count=0,
                # Chat History is a conversation directory, not an inbox.
                # Creation order is immutable; activity must not reshuffle it.
                order_by_last_active=False,
                include_archived=True,
            )
            or []
        )
    except TypeError:
        # Some tests/fakes may implement an older subset of the signature.
        try:
            rows = list(db.list_sessions_rich(limit=limit) or [])
        except Exception:
            return []
        if source:
            rows = [row for row in rows if isinstance(row, dict) and row.get("source") == source]
        if exclude_sources:
            blocked = set(exclude_sources)
            rows = [row for row in rows if isinstance(row, dict) and row.get("source") not in blocked]
        return rows
    except Exception:
        return []


def _get_session_row(db: Any, session_id: str) -> dict[str, Any] | None:
    try:
        raw = db.get_session(session_id)
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _default_session_db() -> Any | None:
    # History pointers, on-demand message tails, open/send validation and
    # transcript writes must all resolve the same operator-visible database.
    # A Launcher-selected profile changes HERMES_HOME, but not the chat scope:
    # ``chat_session_scope`` is the ONE place that decides which database that
    # is (relay context > HERMES_HEAD_HOME > the shared runtime root's recorded
    # head pointer > the degraded ambient home).
    from ..chat_session_scope import open_chat_session_db

    return open_chat_session_db()


def _mission_assignment_for(
    instance: Any,
    assignments_by_id: dict[str, Any],
    assignment_rows: list[Any],
    *,
    task_id: str,
) -> Any | None:
    """Resolve the assignment record a task-bound instance is running under.

    Primary join is ``instance.current_assignment_id``; when that is unset the
    newest assignment matching ``(persona_instance_id, task_id)`` vouches. Both
    lookups stay inside the caller-provided list — no store scan.
    """

    assignment_id = safe_assignment_text(getattr(instance, "current_assignment_id", None), limit=160)
    if assignment_id and assignment_id in assignments_by_id:
        return assignments_by_id[assignment_id]
    instance_id = safe_assignment_text(getattr(instance, "id", None), limit=160)
    if not instance_id:
        return None
    candidates = [
        item
        for item in assignment_rows
        if safe_assignment_text(getattr(item, "persona_instance_id", None), limit=160) == instance_id
        and safe_assignment_text(getattr(item, "task_id", None), limit=160) == task_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: iso_timestamp(getattr(item, "created_at", None)) or "")


def _history_row(
    raw: dict[str, Any],
    instance: PersonaInstance,
    *,
    session_id: str,
    session_db: Any | None = None,
    message_tail: int = DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    kind: str = "chat",
) -> dict[str, Any]:
    persona_id = canonical_chat_persona_id(getattr(instance, "persona_id", None)) or "unknown"
    raw_title = safe_assignment_text(raw.get("title"), limit=120)
    title_fallback = "Untitled persona chat" if raw_title else _fallback_title(raw, persona_id=persona_id)
    title, title_status = _safe_display_text(raw.get("title"), fallback=title_fallback, limit=120)
    preview, preview_status = _safe_display_text(
        raw.get("preview"),
        fallback="No messages yet.",
        redacted_fallback="Preview hidden by redaction boundary",
        limit=180,
    )
    messages, messages_status, messages_unread = _safe_recent_messages(
        session_db, session_id=session_id, limit=message_tail
    )
    active_session_id = session_id
    try:
        active_session_id = session_db.resolve_resume_session_id(session_id)
    except Exception:
        pass
    try:
        from ..persona_chat_continuity import (
            native_lineage_summary,
            persona_chat_runtime_registry,
        )

        registry = persona_chat_runtime_registry()
        lineage = native_lineage_summary(session_db, session_id)
        runtime = (
            registry.observation(session_id, owning_process=True)
            if registry is not None
            else {
                "runtime_state": "unknown",
                "runtime_observer_id": "external_cli",
            }
        )
    except Exception:
        lineage = {"active_session_id": active_session_id, "continuation_depth": 0}
        runtime = {
            "runtime_state": "unknown",
            "runtime_observer_id": "external_cli",
        }
    lineage_aggregate = _lineage_aggregate(
        session_db,
        root_session_id=session_id,
        active_session_id=lineage["active_session_id"],
    )
    _statuses = {title_status, preview_status, messages_status}
    redaction_status = (
        "would_redact"
        if "would_redact" in _statuses
        else "redacted"
        if "redacted" in _statuses
        # An unread transcript cannot be certified safe. Without this branch the
        # fold fell through to "safe" — a redaction verdict over content that
        # was never loaded. Launcher readers test for exactly 'redacted' /
        # 'unsafe' with a safe fallback, so this value degrades to "render
        # normally" (over an empty body) rather than misrendering anything.
        else CHAT_REDACTION_UNKNOWN
        if CHAT_REDACTION_UNKNOWN in _statuses
        else "safe"
    )
    would_redact = {
        label: status
        for label, status in {
            "title": title_status,
            "preview": preview_status,
            "messages": messages_status,
        }.items()
        if status == "would_redact"
    }
    return {
        "session_id": session_id,
        "persona_id": persona_id,
        "persona_instance_id": safe_assignment_text(
            getattr(instance, "id", None) or persona_instance_id_for(persona_id),
            limit=160,
        ),
        "kind": "mission" if kind == "mission" or bool(raw.get("live_mission")) else "chat",
        "live_mission": bool(kind == "mission" or raw.get("live_mission")),
        "title": title,
        "last_message_preview": preview,
        "message_count": lineage_aggregate.get(
            "message_count", positive_int(raw.get("message_count"), default=0)
        ),
        "created_at": iso_timestamp(raw.get("started_at")),
        "updated_at": iso_timestamp(
            lineage_aggregate.get("last_active")
            or raw.get("last_active")
            or raw.get("ended_at")
            or raw.get("started_at")
        ),
        "state": "archived" if bool(raw.get("archived")) else "open",
        "redaction_status": redaction_status,
        **({"would_redact": would_redact} if would_redact else {}),
        # Additive, and present ONLY when the tail could not be read. Its
        # absence is the healthy path, byte-for-byte as before; its presence is
        # what stops an empty ``messages`` list reading as an empty chat.
        **({"messages_unavailable": messages_unread} if messages_unread else {}),
        **_token_usage_fields({**raw, **lineage_aggregate}),
        **_chat_model_fields(raw),
        **_cache_policy_fields(raw),
        "messages": messages,
        "root_chat_session_id": session_id,
        "active_session_id": lineage["active_session_id"],
        "runtime_state": runtime.get("runtime_state", "unknown"),
        "last_runtime_transition": runtime.get("last_runtime_transition"),
        "runtime_observer_id": runtime.get("runtime_observer_id"),
        "runtime_observed_at": runtime.get("runtime_observed_at"),
        "continuation_depth": lineage["continuation_depth"],
        "last_resumed_at": runtime.get("last_resumed_at"),
    }


def _lineage_aggregate(
    session_db: Any | None,
    *,
    root_session_id: str,
    active_session_id: str,
) -> dict[str, Any]:
    """Aggregate usage/activity exactly once across root→compression tip."""

    if session_db is None:
        return {}
    current = active_session_id
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    while current and current not in seen:
        seen.add(current)
        try:
            row = session_db.get_session(current)
        except Exception:
            return {}
        if not isinstance(row, dict):
            return {}
        rows.append(row)
        if current == root_session_id:
            break
        current = safe_assignment_text(row.get("parent_session_id"), limit=240)
    if not rows or current != root_session_id:
        return {}
    result: dict[str, Any] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "message_count",
    ):
        result[key] = sum(positive_int(row.get(key), default=0) for row in rows)
    activity = [
        iso_timestamp(
            row.get("last_active") or row.get("ended_at") or row.get("started_at")
        )
        for row in rows
    ]
    # Some SessionDB implementations omit computed activity fields from
    # ``get_session``. Only in that case derive a fallback from durable message
    # timestamps; an explicit session activity value remains authoritative.
    if not any(row.get("last_active") or row.get("ended_at") for row in rows):
        try:
            lineage_loader = getattr(session_db, "get_messages_as_conversation", None)
            native_messages = (
                lineage_loader(active_session_id, include_ancestors=True)
                if callable(lineage_loader)
                else session_db.get_messages(root_session_id)
            )
        except Exception:
            native_messages = []
        activity.extend(
            iso_timestamp(
                message.get("created_at")
                or message.get("timestamp")
                or message.get("time")
                or message.get("updated_at")
            )
            for message in native_messages or []
            if isinstance(message, dict)
        )
    result["last_active"] = max((item for item in activity if item), default=None)
    return result


def _cache_policy_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Emit the session's prompt-cache policy so the Launcher can render an
    honest freshness/expiry indicator (see agent_runtime.cache_policy).

    Provider/model are resolved the same way the token label picks its effective
    identity: a chat-scoped model override wins over the session's own record.
    """
    from ..cache_policy import resolve_cache_policy

    model_fields = _chat_model_fields(raw)
    provider = model_fields.get("effective_provider") or safe_assignment_text(
        raw.get("provider"), limit=220
    ) or None
    model = model_fields.get("effective_model") or safe_assignment_text(
        raw.get("model"), limit=220
    ) or None
    policy = resolve_cache_policy(
        provider=provider,
        model=model,
        api_mode=safe_assignment_text(raw.get("api_mode"), limit=60) or None,
        base_url=safe_assignment_text(raw.get("base_url"), limit=400) or None,
    )
    return policy.as_snapshot_fields()


def _chat_model_fields(raw: dict[str, Any]) -> dict[str, Any]:
    model_config = _model_config(raw.get("model_config"))
    override = model_config.get(_CHAT_MODEL_OVERRIDE_CONFIG_KEY)
    if not isinstance(override, dict):
        override = {}
    provider = safe_assignment_text(override.get("provider"), limit=220) or None
    model = safe_assignment_text(override.get("model"), limit=220) or None
    fallback_provider = safe_assignment_text(raw.get("provider"), limit=220) or None
    fallback_model = safe_assignment_text(raw.get("model"), limit=220) or None
    if not (provider or model or fallback_provider or fallback_model):
        return {}
    return {
        "chat_provider": provider,
        "chat_model": model,
        "chat_model_scope": "mission_control_chat_session" if provider or model else None,
        "chat_model_is_default": not bool(provider or model),
        "effective_provider": provider or fallback_provider,
        "effective_model": model or fallback_model,
    }


def _model_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except Exception:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _persisted_persona_instance_id(raw: dict[str, Any]) -> str | None:
    """Read the session's authoritative owning instance binding.

    Modern Mission Control sessions persist this in ``model_config``. It must
    outrank persona inference from a display prompt or session-id shape: prompts
    legitimately contain the complete persona system prompt, and placement ids
    such as ``personainst_neko_supervisor_agent_f6f7a51b`` are intentionally not
    reducible to a bare persona id without the instance registry.
    """

    return safe_assignment_text(
        _model_config(raw.get("model_config")).get("persona_instance_id"),
        limit=160,
    )


def _persona_chat_candidate_sort_key(
    candidate: tuple[dict[str, Any], PersonaInstance, str, str, str | None]
) -> tuple[bool, str, str]:
    raw, _instance, session_id, _kind, _task_id = candidate
    created_at = iso_timestamp(raw.get("started_at"))
    return (created_at is not None, created_at or "", session_id)


def _token_usage_fields(raw: dict[str, Any]) -> dict[str, int]:
    input_tokens = positive_int(raw.get("input_tokens"), default=0)
    output_tokens = positive_int(raw.get("output_tokens"), default=0)
    total_tokens = positive_int(raw.get("total_tokens"), default=0)
    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    # Cache split (Launcher contract): ``input_tokens`` is already the UNCACHED,
    # full-price input (canonical usage subtracts cache reads/writes; see
    # agent/usage_pricing.CanonicalUsage). Forwarding the cache buckets lets the
    # Launcher show a cache hit % and a full-price count so operators can tell a
    # warm cache from a stale one that is being re-billed at full rate. The
    # session DB already accumulates these columns per API call — this projection
    # simply stops dropping them at the snapshot boundary.
    cache_read_tokens = positive_int(raw.get("cache_read_tokens"), default=0)
    cache_write_tokens = positive_int(raw.get("cache_write_tokens"), default=0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
    }


def _infer_persona_id(raw: dict[str, Any], *, session_id: str) -> str | None:
    system_prompt = safe_assignment_text(raw.get("system_prompt"), limit=240)
    marker = "Mission Control persona chat for "
    if marker in system_prompt:
        return canonical_chat_persona_id(system_prompt.split(marker, 1)[1])
    prefix = "persona_chat_personainst_"
    if session_id.startswith(prefix):
        return _persona_token_from_chat_session_tail(session_id[len(prefix) :])
    prefix = "persona_chat_"
    if session_id.startswith(prefix):
        value = session_id[len(prefix) :]
        if value.startswith("personainst_"):
            value = value[len("personainst_") :]
        return _persona_token_from_chat_session_tail(value)
    return None


def _persona_token_from_chat_session_tail(value: str) -> str | None:
    token = safe_assignment_token(value)
    if not token:
        return None
    parts = token.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 12 and all(ch in "0123456789abcdef" for ch in parts[1].lower()):
        token = parts[0]
    return canonical_chat_persona_id(token)


def _fallback_title(raw: dict[str, Any], *, persona_id: str) -> str:
    preview, status = _safe_display_text(raw.get("preview"), fallback="", limit=80)
    if status == "safe" and preview and not any(marker in preview for marker in _INTERNAL_SCAFFOLDING_MARKERS):
        return preview
    label = persona_id.replace("_", " ").strip().title() if persona_id else "Persona"
    return f"{label} chat"


def _safe_recent_messages(
    session_db: Any | None,
    *,
    session_id: str,
    limit: int = DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    rows, status, unread = _safe_curated_messages(session_db, session_id=session_id)
    return rows[-_bounded_message_tail(limit):], status, unread
