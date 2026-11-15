"""Fork-owned: the update receipt's reading of a multiplexer's published roster.

RT-UPDATE-FLEET-ROSTER-DROPPED. ``hermes_cli.update_receipt._fleet_row`` (upstream) calls
``roster_names`` before its own well-formed-names check, so both roster shapes a live gateway
publishes discharge the same restart obligations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


def roster_names(served: Any) -> Optional[list[str]]:
    """The profile names a published roster spells, or None when any entry is unusable.

    Runtime status publishes bare names; the unified runtime's ``identify`` publishes each served
    profile as ``{"profile_id", "home"}`` (both a home path). Both shapes are one roster. A home
    entry counts only when it is one of this host's own profile homes (``_profile_homes``), and its
    two fields must agree: an unknown or foreign home must never discharge a restart obligation, so
    one bad entry drops the whole roster.
    """
    if not isinstance(served, list) or not served:
        return None
    by_home: Optional[dict[str, str]] = None
    names: list[str] = []
    for entry in served:
        if isinstance(entry, str) and entry:
            names.append(entry)
            continue
        if not isinstance(entry, dict):
            return None
        homes = {entry[key] for key in ("home", "profile_id") if isinstance(entry.get(key), str) and entry[key]}
        if by_home is None:
            try:
                from hermes_cli.update_receipt import _profile_homes

                by_home = {_home_key(home): profile for profile, home in _profile_homes()}
            except Exception:
                return None
        resolved = {by_home.get(_home_key(Path(home))) for home in homes}
        if len(resolved) != 1 or None in resolved:
            return None
        names.append(resolved.pop())
    return list(dict.fromkeys(names))


def _home_key(home: Path) -> str:
    try:
        return os.path.normcase(str(Path(home).expanduser().resolve(strict=False)))
    except Exception:
        return os.path.normcase(str(home))
