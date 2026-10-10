"""A bounded cache under upstream's ``agent.skill_utils._load_raw_config`` (lane 1011-M1).

Upstream keeps ONE parsed ``config.yaml`` keyed on ``(path, file_signature)`` and empties the
cache before it stores a new key, so a process that alternates profiles (the serve runs several
personas, each with its own home) re-parses on every switch: 130-215 ms per parse for a 22 KB
persona config on this box (measured 2026-10-10). The key already names path and signature, so
keeping several entries is exactly as fresh as keeping one: a rewritten file has a new key.

:func:`install_bounded_skill_config_cache` rebinds the module's cache to a dict whose
``clear()`` (the one upstream calls before an insert) evicts the oldest entries down to room
for one more, and rebinds the test hook ``_raw_config_cache_clear`` to a real clear.
"""

from __future__ import annotations

from agent_runtime._upstream_doors import skill_utils_raw_config_cache

__layer__ = "stores"
__all__ = ["BoundedRawConfigCache", "install_bounded_skill_config_cache"]

#: Distinct (home, signature) entries kept: a few personas' homes plus the default home.
MAX_ENTRIES = 16


class BoundedRawConfigCache(dict):
    """Insertion-ordered; ``clear()`` makes room for one entry instead of emptying."""

    def __init__(self, bound: int = MAX_ENTRIES) -> None:
        super().__init__()
        self.bound = max(1, bound)

    def clear(self) -> None:  # upstream's pre-insert eviction
        while len(self) >= self.bound:
            del self[next(iter(self))]

    def get(self, key, default=None):  # a hit moves to the young end (LRU)
        if key in self:
            value = self.pop(key)
            self[key] = value
            return value
        return default

    def drop_all(self) -> None:
        dict.clear(self)


def install_bounded_skill_config_cache(bound: int = MAX_ENTRIES) -> BoundedRawConfigCache:
    """Rebind ``agent.skill_utils``'s raw-config cache once per process; returns the live cache."""
    module, cache_name, clear_name = skill_utils_raw_config_cache()
    current = getattr(module, cache_name)
    if isinstance(current, BoundedRawConfigCache):
        return current
    cache = BoundedRawConfigCache(bound)
    cache.update(current)
    setattr(module, cache_name, cache)
    setattr(module, clear_name, cache.drop_all)
    return cache
