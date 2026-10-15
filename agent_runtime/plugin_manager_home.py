"""Reuse the registry home identity for warm plugin-manager lookups.

Provider/auth lookups re-enter plugin discovery many times in one request. The
manager is already cached per home; resolving its directory again does not make
plugin discovery fresher. Share hermes_home_key's existing identity contract:
resolve existing homes once, follow the active home on every call, and retry
missing homes until creation. No provider, config or credential result is cached.
"""
from __future__ import annotations

from pathlib import Path

from hermes_constants import hermes_home_key

__layer__ = "policy"


def cached_plugin_home_key(home: Path) -> Path | None:
    """Canonical manager key, or None to retain upstream's resolution fallback."""
    try:
        return Path(hermes_home_key(home))
    except Exception:
        return None
