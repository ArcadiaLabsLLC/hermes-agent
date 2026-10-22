"""The bundled edition's toolset refusal, held at the request seam, and the per-agent opt-in record.

Owner ruling 2026-10-21 (row RT-NAMESPACE-SHARED-CONFIG-SHELL-FAMILY): the bundled edition subtracts
its profile's ``toolsets.disabled`` at load time whatever the shared namespace ``config.yaml`` says; a
single agent opts back in only through an explicit approval record the bundled edition writes.
Plan: ``docs/agent-runtime-harness/planned/bundled-shell-family-opt-in-2026-10-21.md``.

:func:`bundled_disabled_toolsets` is what the chat lane's request carries as ``disabled_toolsets``.
Upstream unions config's own ``agent.disabled_toolsets`` INTO the request's list, so a config can add a
disable but never remove one the request carries. The Developer Edition answers ``()``.

The record is ``<persona's bound profile home>/approvals/toolsets.json`` — in the profile home the
bundled edition owns, never the shared namespace config the Developer Edition may write. It is read at
request-build time, cached by file mtime, so a grant takes effect on the next turn.
"""

from __future__ import annotations

import functools
import json
import logging
import sys
import threading
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

__layer__ = "stores"  # it writes the approval record

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DESKTOP_PROFILE = "bundled-desktop"
#: The record's place under a profile home.
RECORD_PARTS = ("approvals", "toolsets.json")
#: ``sys.platform`` of CPython's mobile builds: the embedded entry runs the phone profile there.
PHONE_PLATFORMS = frozenset({"android", "ios"})
#: Messaging-platform toolsets: their tools need a platform adapter, and a profile whose config sets
#: ``gateway.platform_adapters: false`` starts none, so an opt-in would enable tools with no platform.
PLATFORM_TOOLSETS = frozenset({"discord", "discord_admin", "yuanbao", "feishu_doc", "feishu_drive"})
REASON_MAX = 240


class Reason(StrEnum):
    EDITION_NOT_BUNDLED = "edition_not_bundled"
    TOOLSET_NOT_OPT_IN = "toolset_not_opt_in"
    TOOLSET_NO_PLATFORM = "toolset_no_platform"
    TOOLSET_NOT_SHIPPED = "toolset_not_shipped"


class Mode(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class ToolsetApprovalRefused(ValueError):
    def __init__(self, reason: Reason, toolset: str = "") -> None:
        super().__init__(f"{reason.value}: {toolset}" if toolset else reason.value)
        self.reason = reason
        self.toolset = toolset


def edition_bundled() -> bool:
    """The build stamp's answer (``namespace.install_stamp``), never a config value."""
    from .namespace import install_stamp

    return install_stamp().get("edition") == "bundled"


def profile_name() -> str:
    from .bundle_profiles.phone_hint import PHONE_PROFILE

    return PHONE_PROFILE if sys.platform in PHONE_PLATFORMS else DESKTOP_PROFILE


@functools.lru_cache(maxsize=4)
def _profile(name: str):
    from .bundle_profiles.manifest import load_profile

    return load_profile(name, validate=False)


def bundled_profile():
    return _profile(profile_name())


def _toolset_ships(toolset: str) -> bool:
    """True when the live registry holds a tool of ``toolset``: an unshipped module registers none."""
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    return bool(registry.get_tool_names_for_toolset(toolset))


def refusal(toolset: str, profile: Any, *, check_shipped: bool = True) -> Reason | None:
    """Why ``toolset`` may not be opted into under ``profile``, or ``None``."""
    if toolset not in profile.disabled_toolsets:
        return Reason.TOOLSET_NOT_OPT_IN
    if toolset in PLATFORM_TOOLSETS and profile.config.get("gateway.platform_adapters", True) is False:
        return Reason.TOOLSET_NO_PLATFORM
    if check_shipped and not _toolset_ships(toolset):
        return Reason.TOOLSET_NOT_SHIPPED
    return None


def record_path(home: Path) -> Path:
    return Path(home).joinpath(*RECORD_PARTS)


def persona_home(persona: Any) -> Path:
    """The persona's bound profile home; a persona bound to no profile uses the active home."""
    from hermes_constants import get_hermes_home

    from .profile_context import resolve_persona_profile

    return resolve_persona_profile(persona).profile_home or get_hermes_home()


_cache_lock = threading.Lock()
_cache: dict[str, tuple[tuple[int, int], tuple[dict, ...]]] = {}


def read_approvals(home: Path) -> tuple[dict, ...]:
    """The record's approval rows (``()`` when absent or unreadable), cached by mtime and size."""
    path = record_path(home)
    try:
        stat = path.stat()
    except OSError:
        return ()
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        hit = _cache.get(str(path))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = tuple(row for row in data.get("approvals") or () if isinstance(row, dict) and row.get("toolset"))
    except (OSError, ValueError, AttributeError):
        logger.warning("bundled_toolsets_record_unreadable path=%s", path)
        rows = ()
    with _cache_lock:
        _cache[str(path)] = (stamp, rows)
    return rows


def approved_toolsets(home: Path, profile: Any) -> tuple[str, ...]:
    """Granted toolsets the profile still lets an agent opt into (a hand-edited row is not trusted)."""
    return tuple(dict.fromkeys(
        str(row["toolset"]) for row in read_approvals(home)
        if refusal(str(row["toolset"]), profile, check_shipped=False) is None))


def toolset_offers(home: Path) -> tuple[dict, ...]:
    """The opt-in toolsets the bundled profile offers, each ``{toolset, granted}`` for ``home``'s record.

    A toolset the profile disables but an agent may not opt into (no platform, not shipped) is not
    offered; ``granted`` is :func:`approved_toolsets`' answer, so a hand-edited row reads as not granted."""
    profile = bundled_profile()
    granted = set(approved_toolsets(home, profile))
    return tuple({"toolset": name, "granted": name in granted}
                 for name in profile.disabled_toolsets if refusal(name, profile) is None)


def bundled_disabled_toolsets(persona: Any) -> tuple[str, ...]:
    """The request's ``disabled_toolsets``: the bundled profile's list minus the persona's opt-ins."""
    if not edition_bundled():
        return ()
    profile = bundled_profile()
    granted = set(approved_toolsets(persona_home(persona), profile))
    return tuple(name for name in profile.disabled_toolsets if name not in granted)


def write_approval(home: Path, toolset: str, *, mode: Mode | str, reason: str = "",
                   granted_by: str = "operator") -> dict:
    """Grant or revoke ``toolset`` in ``home``'s record (the bundled edition only); returns the record.

    ``granted_by`` is a field so a confirmed self-request can be added later without a schema bump;
    this cut writes ``operator`` only (the plan's open ruling on who may grant)."""
    mode = Mode(mode)
    if not edition_bundled():
        raise ToolsetApprovalRefused(Reason.EDITION_NOT_BUNDLED, toolset)
    profile = bundled_profile()
    if mode is Mode.GRANT and (why := refusal(toolset, profile)) is not None:
        raise ToolsetApprovalRefused(why, toolset)
    from utils import atomic_json_write

    from .build_stamp import build_stamp

    rows = [row for row in read_approvals(home) if row.get("toolset") != toolset]
    if mode is Mode.GRANT:
        rows.append({"toolset": toolset, "granted_at": datetime.now(timezone.utc).isoformat(),
                     "granted_by": granted_by, "edition": "bundled", "build": build_stamp().commit or "",
                     "reason": str(reason or "")[:REASON_MAX]})
    record = {"schema_version": SCHEMA_VERSION, "approvals": rows}
    path = record_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, record)
    with _cache_lock:
        _cache.pop(str(path), None)
    return record
