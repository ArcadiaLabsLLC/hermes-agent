"""The owner's door onto staged skill writes, across every profile of the namespace (RT-REVIEW-STAGED-SKILL-DOOR).

:mod:`agent_runtime.review_skill_gate` stages a background review's write to a SHARED skill in
the AGENT PROFILE's ``pending/skills/`` (upstream's write-approval store,
``tools.write_approval``). Upstream's only door onto it is the interactive ``/skills
pending|diff|approve|reject`` run under that profile's home, so the owner could not see or
act on a staged write from Mission Control. This module is that door, one level up:

* :func:`list_staged` walks the default home and every ``profiles/<name>`` home and returns
  each staged skill write with its profile, id, summary, origin, action, skill name, time and
  the unified diff upstream's ``/skills diff`` would print (bounded);
* :func:`approve_staged` replays one record through ``tools.skill_manager_tool.apply_skill_pending``
  under that profile's home — upstream's own replay, the same one ``/skills approve`` runs — and
  drops the record only when the replay succeeded;
* :func:`reject_staged` drops one record unapplied.

Each read and write runs inside :func:`agent_runtime.profile_context.process_home_scope` for the
record's profile, so it resolves the store (and the skill a replay writes) exactly as the turn that
staged it did. The method lane is ``runtime.skills.pending.*`` (``serve_rpc/skills_pending.py``);
the argv twin is ``hermes harness skills pending list|approve|reject``.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

__layer__ = "lanes"
__all__ = [
    "DIFF_LIMIT",
    "SkillPendingError",
    "SkillPendingRefusal",
    "approve_staged",
    "list_staged",
    "reject_staged",
]

#: The default home's profile name, as ``hermes_cli.profiles`` spells it.
DEFAULT_PROFILE = "default"
#: Bound on one record's diff in a listing (characters).
DIFF_LIMIT = 20000
_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PENDING_ID_RE = re.compile(r"^[0-9a-f]{8}$")


class SkillPendingRefusal(StrEnum):
    UNKNOWN_PROFILE = "unknown_profile"
    INVALID_ID = "invalid_id"
    NOT_FOUND = "not_found"
    APPLY_FAILED = "apply_failed"


class SkillPendingError(ValueError):
    def __init__(self, code: SkillPendingRefusal, detail: str = "") -> None:
        super().__init__(code.value)
        self.code = code
        self.detail = detail


def _profile_homes() -> list[tuple[str, Path]]:
    """``(profile, home)`` for the default home and every ``profiles/<name>`` directory, by name."""

    from agent_runtime._upstream_doors import default_hermes_home, profiles_root

    homes: list[tuple[str, Path]] = []
    default = default_hermes_home()
    if default.is_dir():
        homes.append((DEFAULT_PROFILE, default))
    root = profiles_root()
    if root.is_dir():
        homes.extend((child.name, child) for child in sorted(root.iterdir())
                     if child.is_dir() and _PROFILE_RE.match(child.name))
    return homes


def _home_of(profile: Any) -> tuple[str, Path]:
    name = str(profile or "").strip()
    for candidate, home in _profile_homes():
        if candidate == name:
            return candidate, home
    raise SkillPendingError(SkillPendingRefusal.UNKNOWN_PROFILE, "no such profile in this namespace")


def _checked_id(pending_id: Any) -> str:
    text = str(pending_id or "").strip()
    if not _PENDING_ID_RE.match(text):
        raise SkillPendingError(SkillPendingRefusal.INVALID_ID, "a pending id is 8 hex characters")
    return text


def _row(profile: str, record: dict[str, Any]) -> dict[str, Any]:
    from tools import write_approval as wa

    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    try:
        diff = wa.skill_pending_diff(record)
    except Exception:  # a diff is a convenience; the record still lists
        diff = ""
    return {
        "profile": profile,
        "id": str(record.get("id") or ""),
        "summary": str(record.get("summary") or ""),
        "origin": str(record.get("origin") or ""),
        "action": str(record.get("action") or payload.get("action") or ""),
        "skill": str(payload.get("name") or ""),
        "created_at": record.get("created_at"),
        "diff": diff[:DIFF_LIMIT],
        "diff_truncated": len(diff) > DIFF_LIMIT,
    }


def list_staged(*, profile: str | None = None) -> dict[str, Any]:
    """Every staged skill write in the namespace (or one profile's), oldest first per profile."""

    from agent_runtime.profile_context import process_home_scope
    from tools import write_approval as wa

    homes = [_home_of(profile)] if profile else _profile_homes()
    rows: list[dict[str, Any]] = []
    for name, home in homes:
        with process_home_scope(home):
            rows.extend(_row(name, record) for record in wa.list_pending(wa.SKILLS))
    return {"pending": rows, "count": len(rows), "profiles_scanned": [name for name, _home in homes]}


def approve_staged(*, profile: str, pending_id: str) -> dict[str, Any]:
    """Replay one staged write under its profile's home; drop the record only when it applied."""

    from agent_runtime.profile_context import process_home_scope
    from tools import write_approval as wa

    name, home = _home_of(profile)
    record_id = _checked_id(pending_id)
    with process_home_scope(home):
        record = wa.get_pending(wa.SKILLS, record_id)
        if record is None:
            raise SkillPendingError(SkillPendingRefusal.NOT_FOUND, "no staged skill write with that id")
        from tools.skill_manager_tool import apply_skill_pending

        try:
            result = json.loads(apply_skill_pending(record.get("payload") or {}))
        except Exception as exc:
            raise SkillPendingError(SkillPendingRefusal.APPLY_FAILED, type(exc).__name__) from exc
        if not isinstance(result, dict) or not result.get("success"):
            error = result.get("error") if isinstance(result, dict) else ""
            raise SkillPendingError(SkillPendingRefusal.APPLY_FAILED, str(error or "the replay did not succeed"))
        wa.discard_pending(wa.SKILLS, record_id)
    return {"profile": name, "id": record_id, "applied": True, "result": result}


def reject_staged(*, profile: str, pending_id: str) -> dict[str, Any]:
    """Drop one staged write unapplied."""

    from agent_runtime.profile_context import process_home_scope
    from tools import write_approval as wa

    name, home = _home_of(profile)
    record_id = _checked_id(pending_id)
    with process_home_scope(home):
        if not wa.discard_pending(wa.SKILLS, record_id):
            raise SkillPendingError(SkillPendingRefusal.NOT_FOUND, "no staged skill write with that id")
    return {"profile": name, "id": record_id, "rejected": True}
