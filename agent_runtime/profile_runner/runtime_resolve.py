"""The per-request runtime resolution and its short-lived memo (one memo, one
writer).
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
import time
from typing import Any

from hermes_cli.runtime_provider import resolve_runtime_provider

from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "stores"

__all__ = [
    "RUNTIME_RESOLVE_CACHE_TTL_SECONDS",
    "_RUNTIME_RESOLVE_CACHE",
    "_RUNTIME_RESOLVE_CACHE_LOCK",
    "_RUNTIME_RESOLVE_STAMPED_FILES",
    "_resolve_request_runtime",
    "_runtime_resolve_cache_key",
    "reset_runtime_resolve_cache",
]


#: T6 (2026-08-09): how long a resolved runtime may be reused for an unchanged
#: (profile, provider, model, config) tuple. 0.28-0.44 s of every send was spent
#: re-resolving an identical answer.
#:
#: THE TTL IS A SAFETY BOUND, NOT A TUNING KNOB, and it is why it is 30 s rather
#: than something generous. ``resolve_runtime_provider`` returns live OAuth
#: credentials and refreshes any token within
#: ``hermes_cli.auth.ACCESS_TOKEN_REFRESH_SKEW_SECONDS`` (120 s) of expiry. A
#: memo handed out T seconds after resolution therefore carries a token with at
#: least ``skew - T`` seconds of validity left: at 30 s that floor is 90 s,
#: comfortably longer than the turn that is about to use it. Raising this past
#: the skew would hand out expired credentials, so it must stay well under it —
#: the invariant is pinned by
#: ``tests/agent_runtime/test_send_path_runner_reuse.py`` (`:425-426`, which
#: asserts this constant is positive AND below half the refresh skew). This
#: line named ``test_runtime_resolve_cache.py``, a file that never existed;
#: repointed MCF-78 2026-08-20.
RUNTIME_RESOLVE_CACHE_TTL_SECONDS = 30.0


#: Files whose content can change what ``resolve_runtime_provider`` returns for
#: an otherwise identical request (default provider/model, base_url, a provider
#: flipped to ``enabled: false``, a rotated key). Their (mtime_ns, size) join the
#: cache key, so an operator edit invalidates the memo immediately instead of
#: waiting out the TTL.
_RUNTIME_RESOLVE_STAMPED_FILES = ("config.yaml", ".env")


_RUNTIME_RESOLVE_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}


_RUNTIME_RESOLVE_CACHE_LOCK = RLock()


def reset_runtime_resolve_cache() -> None:
    """Drop every memoized runtime resolution (tests; profile teardown)."""

    with _RUNTIME_RESOLVE_CACHE_LOCK:
        _RUNTIME_RESOLVE_CACHE.clear()


def _runtime_resolve_cache_key(request: AgentRunRequest) -> tuple:
    """Everything that can change the answer, and nothing that cannot.

    ``HERMES_HOME`` is in the key because this resolves INSIDE
    ``persona_profile_context`` — two personas bound to different profiles must
    never share a memo (the same reason profile-context memos key on it).
    """

    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    stamps = []
    for name in _RUNTIME_RESOLVE_STAMPED_FILES:
        try:
            stat = (home / name).stat()
            stamps.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            # An absent file is a stable fact about the config too; it becomes a
            # different key the moment one is created.
            stamps.append((name, None, None))
    return (
        str(home),
        str(request.provider or ""),
        str(request.model or ""),
        tuple(stamps),
    )


def _resolve_request_runtime(
    request: AgentRunRequest, timing: dict[str, Any] | None = None
) -> dict[str, Any]:
    from ..local_llama_adapter import PROVIDER_ID
    if request.provider == PROVIDER_ID:
        from ..local_llama_adapter.provider import resolve
        return resolve(request.model, root=request.runtime_root)
    if not request.provider:
        return {}
    key = _runtime_resolve_cache_key(request)
    now = time.monotonic()
    with _RUNTIME_RESOLVE_CACHE_LOCK:
        cached = _RUNTIME_RESOLVE_CACHE.get(key)
        if cached is not None and now - cached[0] <= RUNTIME_RESOLVE_CACHE_TTL_SECONDS:
            if timing is not None:
                timing["runtime_resolve_cached"] = 1
            return dict(cached[1])
    runtime = resolve_runtime_provider(requested=request.provider, target_model=request.model)
    resolved = {
        key_name: value
        for key_name, value in runtime.items()
        if key_name in {"provider", "model", "api_mode", "base_url", "api_key"} and value
    }
    with _RUNTIME_RESOLVE_CACHE_LOCK:
        # Bounded: one entry per live (profile, provider, model, config) tuple,
        # and the set of those is small. Evict the oldest wholesale rather than
        # keep an LRU — a cold re-resolve costs one turn 0.3 s, a leak costs the
        # process.
        if len(_RUNTIME_RESOLVE_CACHE) >= 64:
            _RUNTIME_RESOLVE_CACHE.clear()
        _RUNTIME_RESOLVE_CACHE[key] = (now, dict(resolved))
    if timing is not None:
        timing["runtime_resolve_cached"] = 0
    return resolved
