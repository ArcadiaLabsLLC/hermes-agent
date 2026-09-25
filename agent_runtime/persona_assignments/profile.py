"""Model-override and reasoning-effort validation for ``update_profile``: the
override text sanitizer and the effort normalizer, plus ``_as_utc``.
"""

from __future__ import annotations

from datetime import datetime, timezone

__layer__ = "policy"

__all__ = [
    "_as_utc",
    "_model_supports_reasoning_effort",
    "_normalize_reasoning_effort_override",
    "_safe_model_override_text",
]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _safe_model_override_text(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    if len(text) > 200:
        raise ValueError(f"{field_name} exceeds 200 characters")
    if any(ord(ch) < 0x20 for ch in text):
        raise ValueError(f"{field_name} contains control characters")
    return text


def _model_supports_reasoning_effort(model_id: str | None) -> bool:
    """True when the model exposes reasoning-effort control (offline id-heuristic).

    Reuses the canonical Copilot/GPT-5/o-series id heuristic with no catalog or
    api_key so this stays a cheap, network-free check safe to run for every
    instance in a snapshot. A resolution failure degrades to ``False`` (control
    hidden) rather than raising inside the projection.
    """
    if not str(model_id or "").strip():
        return False
    try:
        from hermes_cli.models import github_model_reasoning_efforts

        return bool(github_model_reasoning_efforts(model_id))
    except Exception:
        return False


def _normalize_reasoning_effort_override(value: str) -> str | None:
    """Normalize a reasoning-effort override to a stored value or ``None``.

    Empty clears the override (inherit the runtime default). ``"none"`` (thinking
    off) and every level in ``hermes_constants.VALID_REASONING_EFFORTS`` are
    accepted; anything else raises ``ValueError``.
    """
    from hermes_constants import VALID_REASONING_EFFORTS

    text = str(value or "").strip().lower()
    if not text:
        return None
    if text == "none" or text in VALID_REASONING_EFFORTS:
        return text
    raise ValueError(
        f"invalid reasoning_effort: {value!r} (expected one of none, "
        f"{', '.join(VALID_REASONING_EFFORTS)})"
    )
