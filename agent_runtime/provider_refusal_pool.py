"""A provider refusal marks the credential that was refused (RT-SINGLE-CREDENTIAL-REFUSAL-NOT-POOLED).

The credential pool learns a key is spent only through ``mark_exhausted_and_rotate``,
and only the in-run rotation callers (``agent/agent_runtime_helpers.py``,
``agent/auxiliary_client.py``) reach it. A provider whose pool holds ONE key has
nothing to rotate to, so the live 2026-10-30 HuggingFace ``usage_limit_reached``
refused the turn while ``hermes harness providers`` kept answering ``healthy``:
the probe reads the pool, and the pool was never told.

This module is the second writer the runtime was missing, at the one place every
profile run's refusal surfaces (``ProfileAgentRunner._run``, before it raises).
It reads the refusal through the SAME predicate the turn settle uses
(:func:`agent_runtime.mission_chat_outcome.provider_refusal`), so "this was a
refusal" has one authority, and it writes through the pool's PUBLIC door, so
cooldown sizing, DEAD-vs-EXHAUSTED and model-scoped benching stay the pool's.

Never raises: a refusal that cannot be recorded must not replace the turn's own
error, so every failure here is logged and answered ``None``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from agent_runtime.mission_chat_outcome import ProviderRefusal, provider_refusal

__layer__ = "stores"
__all__ = [
    "CREDENTIAL_REFUSAL_STATUS_CODES",
    "record_provider_refusal",
    "refused_entry",
]

logger = logging.getLogger(__name__)

#: The refusal statuses that are a fact about the KEY. 404 (model not found),
#: a classified 400 and the harness-authored 0 (``provider_unavailable``) are
#: facts about the model or the request, and marking a credential for them
#: would take a working key offline.
CREDENTIAL_REFUSAL_STATUS_CODES = frozenset({401, 402, 403, 429})


def refused_entry(pool: Any, api_key_hint: Optional[str]) -> Any:
    """The pool entry the refused request was sent with, or ``None`` when that is not provable.

    With the dispatched key known, the entry carrying it. Without it, the pool's
    only key, when every entry carries the same one (an explicit entry plus its
    ``model_config`` twin is still one key); several distinct keys and no hint
    is a guess, and a guess could bench a healthy sibling.
    """

    entries = list(pool.entries())
    if api_key_hint:
        for entry in entries:
            if entry.runtime_api_key == api_key_hint:
                return entry
        return None
    keys = {entry.runtime_api_key for entry in entries}
    if len(entries) and len(keys) == 1:
        return entries[0]
    return None


def _error_context(refusal: ProviderRefusal, *, now: float) -> dict[str, Any]:
    """The pool's error-context shape, with the refusal's reset made absolute.

    The provider's reset can arrive as an epoch, a delta in seconds or an ISO
    moment; the pool parses only absolute ones, so a delta read raw would land
    in 1970 and lift the cooldown at once.
    """

    context: dict[str, Any] = {}
    if refusal.reason:
        context["reason"] = refusal.reason
    if refusal.message:
        context["message"] = refusal.message
    resets_in = refusal.resets_in_seconds(now=now)
    if resets_in is not None:
        context["reset_at"] = now + resets_in
    return context


def _pool_for(provider: str, agent: Any) -> Any:
    pool = getattr(agent, "_credential_pool", None)
    if pool is not None and str(getattr(pool, "provider", "") or "").strip().lower() == provider.lower():
        return pool
    from agent.credential_pool import load_pool

    return load_pool(provider)


def record_provider_refusal(exc: BaseException, *, agent: Any = None, now: float | None = None) -> Optional[str]:
    """Mark the refused credential exhausted from ``exc``'s refusal; the marked entry's id, or ``None``.

    ``agent`` is the run's agent when one was built: its pool and its dispatched
    key (``agent.api_key``) name the exact entry. Must run inside the run's
    profile binding, because the pool it loads is the profile's.
    """

    refusal = provider_refusal(exc)
    if refusal is None or refusal.status_code not in CREDENTIAL_REFUSAL_STATUS_CODES:
        return None
    provider = refusal.provider
    if not provider:
        return None
    try:
        pool = _pool_for(provider, agent)
        hint = getattr(agent, "api_key", None) or None
        entry = refused_entry(pool, hint if isinstance(hint, str) else None)
        if entry is None:
            return None
        pool.mark_exhausted_and_rotate(
            status_code=refusal.status_code,
            error_context=_error_context(refusal, now=time.time() if now is None else now),
            credential_id=entry.id,
            failure_reason=refusal.failure_reason,
            model=refusal.model,
        )
        return entry.id
    except Exception:
        logger.warning("provider refusal on %s could not be recorded on its credential pool", provider, exc_info=True)
        return None
