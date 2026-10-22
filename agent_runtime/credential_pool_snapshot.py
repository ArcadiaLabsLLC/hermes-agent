"""A per-call credential-pool snapshot: inside the scope, ``load_pool(p)`` runs once per provider.

``agent.credential_pool.load_pool`` re-reads ``auth.json``, the pool, env and dotenv on every call;
the model picker calls it once per provider row (~94 per open, RT-PICKER-AUTH-REREAD). A caller that
builds one picker payload opens :func:`credential_pool_snapshot`; the seam in ``load_pool`` asks
:func:`snapshot_get` first and hands its result to :func:`snapshot_put`. Outside a scope both are
no-ops, so every other caller keeps upstream's read-every-time behaviour. The same scope memoises the
picker's two read-only ``auth.json`` probes (:func:`memo_auth_reader`, RT-PICKER-AUTH-DIRECT-READS).

The memo is keyed on the bound Hermes home as well as the provider, so a scope that spans a profile
switch never answers one profile's pool to another.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

__layer__ = "policy"

#: ``None`` outside a scope; the open scope's memo inside one (nested scopes share the outer dict).
_snapshot: ContextVar[dict[tuple[str, ...], Any] | None] = ContextVar(
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


def memo_auth_reader(read: Callable[[], Any]) -> Callable[[], Any]:
    """``read`` (``auth._load_auth_store``), answered once per (home) inside an open scope.

    For the picker's read-only probes only (``model_switch_providers._auth_store_has_provider`` /
    ``_raw_pool_usable`` bind it locally): the memoised dict is shared, so a caller that mutates the
    store must keep calling ``_load_auth_store`` itself. Outside a scope it is ``read``.
    """
    def reader() -> Any:
        memo = _snapshot.get()
        if memo is None:
            return read()
        from hermes_constants import get_hermes_home

        key = (str(get_hermes_home()), "", "auth.json")
        if key not in memo:
            memo[key] = read()
        return memo[key]

    return reader
