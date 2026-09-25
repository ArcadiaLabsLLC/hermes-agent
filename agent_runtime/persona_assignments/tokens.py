"""The token/text sanitizers every summary and store field passes through
(``safe_assignment_token``, ``safe_optional_token``, ``safe_assignment_text``)
and the skill-override list normalizer.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.serde import safe_text

__layer__ = "policy"

__all__ = [
    "safe_assignment_text",
    "safe_assignment_token",
    "safe_optional_token",
    "_dedupe_tokens",
    "_safe_skill_overrides",
]


# S70 removed ``assignment_evidence_kind`` / ``assignment_archive_scope`` /
# ``assignment_signal_hash`` / ``assignment_signal_hash_from_parts`` with the
# assignment mint side. They were derivation inputs to ``create_or_resume``
# only; the ``evidence_kind`` / ``archive_scope`` / ``signal_hash`` FIELDS stay
# on the model and the wire summary because residual rows still carry them.


def safe_assignment_token(value: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value or "").strip())
    return text.strip("._-")[:120]


def safe_optional_token(value: Any) -> str | None:
    token = safe_assignment_token(value)
    return token or None


def _dedupe_tokens(values: list[str] | None) -> list[str]:
    """Normalize + de-duplicate a parent-id list, preserving first-seen order.

    The first surviving token is treated as the PRIMARY parent everywhere
    (the ``spawned_by`` mirror, the projection's home owner), so order matters.
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        token = safe_optional_token(value)
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


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


def safe_assignment_text(value: Any, *, limit: int) -> str:
    """:func:`agent_runtime.serde.safe_text`, spelled ``""`` for an empty value (store rows persist ``""``)."""
    return safe_text(value, limit=limit) or ""
