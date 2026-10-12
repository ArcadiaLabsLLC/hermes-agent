"""Profile-override validation for ``update_profile``: the model-override text
sanitizer, the reasoning-effort normalizer, the skill-override list normalizer,
and ``_as_utc``. Pure; the write side is ``profile_writes``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_runtime.serde import safe_assignment_token

__layer__ = "policy"

__all__ = [
    "_as_utc",
    "_normalize_reasoning_effort_override",
    "_safe_model_override_text",
    "_safe_skill_overrides",
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


def _safe_skill_overrides(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        skill = safe_assignment_token(value)
        if not skill or skill in seen:
            continue
        seen.add(skill)
        result.append(skill)
    return result[:40]
