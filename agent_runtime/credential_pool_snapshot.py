"""A per-call credential-pool snapshot: inside the scope, ``load_pool(p)`` runs once per provider.

``agent.credential_pool.load_pool`` re-reads ``auth.json``, the pool, env and dotenv on every call;
the model picker calls it once per provider row (~94 per open, RT-PICKER-AUTH-REREAD). A caller that
builds one picker payload opens :func:`credential_pool_snapshot`; the seam in ``load_pool`` asks
:func:`snapshot_get` first and hands its result to :func:`snapshot_put`. Outside a scope both are
no-ops, so every other caller keeps upstream's read-every-time behaviour.

The memo is keyed on the bound Hermes home as well as the provider, so a scope that spans a profile
switch never answers one profile's pool to another.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

__layer__ = "policy"

#: ``None`` outside a scope; the open scope's memo inside one (nested scopes share the outer dict).
_snapshot: ContextVar[dict[tuple[str, str], Any] | None] = ContextVar(
    "hermes_credential_pool_snapshot", default=None)


def _key(provider: str) -> tuple[str, str]:
    from hermes_constants import get_hermes_home

    return str(get_hermes_home()), (provider or "").strip().lower()


@contextmanager
def credential_pool_snapshot() -> Iterator[None]:
    """Memoise ``load_pool`` per (home, provider) for the duration of the block."""
    if _snapshot.get() is not None:
        yield
        return
    token = _snapshot.set({})
    try:
        yield
    finally:
        _snapshot.reset(token)


def snapshot_get(provider: str) -> Any | None:
    """The pool memoised for ``provider`` in the open scope, or ``None``."""
    memo = _snapshot.get()
    return None if memo is None else memo.get(_key(provider))


def snapshot_put(provider: str, pool: Any) -> Any:
    """Remember ``pool`` for ``provider`` in the open scope; returns ``pool`` unchanged."""
    memo = _snapshot.get()
    if memo is not None:
        memo[_key(provider)] = pool
    return pool
