"""Which chat and turn a background-review skill change came from, and a skill's change history (RT-SKILL-CHANGE-RECORD).

The post-turn skill review (``agent/background_review.py``, upstream) changes skills 30 s or more after
the turn it reviewed, and nothing tied the change back to that turn: upstream's skill audit ledger
(``tools/skill_ledger.py``) records every applied mutation with its before/after blobs but only the
NATIVE session id, and a staged shared write (:mod:`agent_runtime.review_skill_gate`) records neither.
So the owner learned that Neko's trial turn re-wrote a skill only by asking (launcher
``MC-SKILL-CHANGE-VISIBLE``).

This module is the fork's record beside upstream's ledger, one JSONL file per profile home
(:data:`CHANGES_FILE`):

* ``applied`` — written by the eternia-harness ``post_tool_call`` hook (:func:`on_post_tool_call`) after a
  successful ``skill_manage`` under the ``background_review`` write origin. It names the persona chat and
  turn (:func:`agent_runtime.persona_turn_binding.current_turn_origin` — snapshotted when the turn bound,
  so a later turn on the same agent cannot relabel it) and the ledger entries the call appended (same
  skill, same native session, inside the call's measured window).
* ``staged`` — written by the gate when it stages a shared-skill write, keyed by the pending id;
  ``approved`` / ``rejected`` by :mod:`agent_runtime.review_skill_pending` when the owner acts.

Each ``applied`` / ``staged`` record is announced on the stream as one ``persona_chat.skill_changed``
event per skill (:func:`_announce`, RT-SKILL-CHANGE-EVENT) — ``{profile, skill, action, change, turn,
staged_id?}`` — so the launcher re-reads on the event rather than polling after a turn settles.

:func:`list_changes` is the read (``runtime.skills.changes.list``): a skill's applied changes from the
ledger with their unified diffs and, where the review made them, the chat and turn; or one chat's / one
turn's review changes; plus the staged writes with their turn and status. A deferred review (the idle
queue) runs outside the turn's context and records ``turn: null`` — said, never guessed.
"""

from __future__ import annotations

import difflib
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

__layer__ = "lanes"
__all__ = [
    "CHANGES_FILE",
    "DIFF_LIMIT",
    "list_changes",
    "on_post_tool_call",
    "record_staged",
    "record_staged_outcome",
    "turn_of_pending",
]

logger = logging.getLogger(__name__)

#: The fork's record, in each profile home (beside upstream's ``skills/.curator_ledger.jsonl``).
CHANGES_FILE = "eternia_review_skill_changes.jsonl"
#: Bound on one change's rendered diff (characters), as ``runtime.skills.pending.list``'s.
DIFF_LIMIT = 20000
#: Bound on the rows one read returns.
LIMIT_MAX = 200
_FILE_MAX_BYTES = 2 * 1024 * 1024
#: Slack around a call's measured window when matching the ledger entries it appended (seconds).
_WINDOW_SLACK = 2.0


def _changes_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / CHANGES_FILE


def _append_change_row(row: dict[str, Any]) -> None:
    """One line; never raises (a record is telemetry, the skill write already happened)."""
    try:
        path = _changes_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if path.stat().st_size > _FILE_MAX_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            path.write_text("".join(lines[len(lines) // 2:]), encoding="utf-8")
    except Exception:
        logger.warning("review skill changes: could not record %s", row.get("kind"), exc_info=True)


def _records() -> list[dict[str, Any]]:
    try:
        raw = _changes_path().read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _turn() -> dict[str, Any] | None:
    from agent_runtime.persona_turn_binding import current_turn_origin

    return current_turn_origin()


def _row(kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": uuid.uuid4().hex[:12], "kind": kind, "recorded_at": time.time(), **fields}


def _current_profile() -> str:
    """This process's profile as :func:`list_changes` names it, so the event's ``profile`` reads back."""
    from hermes_constants import get_hermes_home

    from agent_runtime.profile_context import active_profile_name
    from agent_runtime.review_skill_pending import profile_homes

    home = get_hermes_home().resolve()
    for name, candidate in profile_homes():
        if candidate.resolve() == home:
            return name
    return active_profile_name()


def _announce(change: str, targets: list[tuple[str, str]], turn: dict[str, Any] | None,
              staged_id: str | None = None) -> None:
    """One ``persona_chat.skill_changed`` per (action, skill); never raises — the change already happened."""
    try:
        from agent_runtime.events import EventLog
        from agent_runtime.models import Event
        from hermes_time import now

        profile = _current_profile()
        log = EventLog()
        for action, skill in sorted(set(targets)):
            payload: dict[str, Any] = {"profile": profile, "skill": skill, "action": action, "change": change,
                                       "turn": turn}
            if staged_id:
                payload["staged_id"] = staged_id
            log.append(Event(type="persona_chat.skill_changed", task_id=None, run_id=None, persona_id=None,
                             ts=now(), payload=payload,
                             session_id=(turn or {}).get("chat_session_id") or None,
                             turn_id=(turn or {}).get("turn_id") or None))
    except Exception:
        logger.warning("review skill changes: could not announce %s", change, exc_info=True)


# ── writes ─────────────────────────────────────────────────────────────────


def _ledger_entries(skills: list[str], session_id: str, started: float, ended: float) -> list[str]:
    """The ids of the ledger entries this call appended: its skills, its native session, its window."""
    from tools import skill_ledger

    ids = []
    for entry in skill_ledger.list_entries(limit=64):
        if entry.get("skill") not in skills:
            continue
        evidence = entry.get("evidence") if isinstance(entry.get("evidence"), dict) else {}
        if session_id and evidence.get("session_id") not in (None, session_id):
            continue
        try:
            at = datetime.fromisoformat(str(entry.get("ts"))).timestamp()
        except ValueError:
            continue
        if started - _WINDOW_SLACK <= at <= ended + _WINDOW_SLACK:
            ids.append(str(entry.get("id")))
    return ids


def _succeeded(result: Any) -> bool:
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("success") is True


def on_post_tool_call(tool_name: Any = None, args: Any = None, result: Any = None, session_id: Any = None,
                      duration_ms: Any = None, **_context: Any) -> None:
    """``post_tool_call``: record a background review's successful ``skill_manage`` with its chat and turn."""
    if tool_name != "skill_manage" or not isinstance(args, dict) or not _succeeded(result):
        return
    from tools.skill_provenance import is_background_review

    if not is_background_review():
        return
    from agent_runtime.review_skill_gate import write_targets

    targets = [(action, name) for action, name in write_targets(args) if name]
    if not targets:
        return
    ended = time.time()
    started = ended - (float(duration_ms) / 1000 if type(duration_ms) in (int, float) and duration_ms >= 0 else 0)
    skills = sorted({name for _action, name in targets})
    try:
        entries = _ledger_entries(skills, str(session_id or ""), started, ended)
    except Exception:
        entries = []
    turn = _turn()
    _append_change_row(_row("applied", skills=skills, actions=sorted({action for action, _name in targets}),
                 native_session_id=str(session_id or "") or None, ledger_entries=entries, turn=turn))
    _announce("applied", targets, turn)


def record_staged(pending_id: str, skills: list[str], action: str) -> None:
    """The gate staged ``pending_id``: remember the chat and turn the review came from."""
    turn = _turn()
    _append_change_row(_row("staged", pending_id=pending_id, skills=sorted(skills), actions=[action], turn=turn))
    _announce("staged", [(action, skill) for skill in skills], turn, staged_id=pending_id)


def record_staged_outcome(pending_id: str, outcome: str) -> None:
    """The owner approved (``approved``) or rejected (``rejected``) a staged write."""
    _append_change_row(_row(outcome, pending_id=pending_id))


def turn_of_pending(pending_id: str) -> dict[str, Any] | None:
    """The chat and turn a staged write came from, read under the current profile home."""
    return next((row.get("turn") for row in reversed(_records())
                 if row.get("kind") == "staged" and row.get("pending_id") == pending_id), None)


# ── the read ───────────────────────────────────────────────────────────────


def _blob_text(sha: Any) -> str:
    from tools import skill_ledger

    data = skill_ledger.read_blob(str(sha)) if sha else None
    return data.decode("utf-8", "replace") if data is not None else ""


def _shown(path: str) -> str:
    """A ledger path as the owner reads it: relative to the profile's skills dir when under it."""
    from hermes_constants import get_hermes_home

    try:
        return Path(path).relative_to(get_hermes_home() / "skills").as_posix()
    except ValueError:
        return path


def _entry_diff(entry: dict[str, Any]) -> str:
    before = {str(item.get("path")): item.get("sha256") for item in entry.get("before") or [] if isinstance(item, dict)}
    after = {str(item.get("path")): item.get("sha256") for item in entry.get("after") or [] if isinstance(item, dict)}
    chunks = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        chunks.extend(difflib.unified_diff(
            _blob_text(before.get(path)).splitlines(keepends=True), _blob_text(after.get(path)).splitlines(keepends=True),
            fromfile=f"a/{_shown(path)}" if path in before else "/dev/null",
            tofile=f"b/{_shown(path)}" if path in after else "/dev/null"))
    return "".join(chunks)


def _matches(turn: Any, chat_session_id: str | None, turn_id: str | None) -> bool:
    if not chat_session_id and not turn_id:
        return True
    turn = turn if isinstance(turn, dict) else {}
    return ((not chat_session_id or turn.get("chat_session_id") == chat_session_id)
            and (not turn_id or turn.get("turn_id") == turn_id))


def _change_row(profile: str, entry: dict[str, Any], turn: Any) -> dict[str, Any]:
    try:
        diff = _entry_diff(entry)
    except Exception:  # a diff is a convenience; the change still lists
        diff = ""
    return {
        "profile": profile, "entry_id": str(entry.get("id") or ""), "skill": str(entry.get("skill") or ""),
        "action": str(entry.get("action") or ""), "actor": str(entry.get("actor") or ""), "at": entry.get("ts"),
        "review": turn is not False, "turn": turn or None,
        "files": sorted({_shown(str(item.get("path"))) for side in ("before", "after")
                         for item in entry.get(side) or [] if isinstance(item, dict)}),
        "diff": diff[:DIFF_LIMIT], "diff_truncated": len(diff) > DIFF_LIMIT,
    }


def _profile_changes(profile: str, *, skill: str | None, chat_session_id: str | None, turn_id: str | None,
                     limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from tools import skill_ledger, write_approval as wa

    records = _records()
    review_turn = {entry_id: row.get("turn") for row in records if row.get("kind") == "applied"
                     for entry_id in row.get("ledger_entries") or []}
    if skill:
        entries = skill_ledger.list_entries(skill=skill, limit=limit)
    else:
        entries = [entry for entry in skill_ledger.list_entries() if entry.get("id") in review_turn][:limit]
    changes = [_change_row(profile, entry, review_turn.get(entry.get("id"), False)) for entry in entries
               if _matches(review_turn.get(entry.get("id")), chat_session_id, turn_id)
               and (not (chat_session_id or turn_id) or entry.get("id") in review_turn)]
    outcomes = {row.get("pending_id"): row.get("kind") for row in records if row.get("kind") in ("approved", "rejected")}
    pending = {str(record.get("id")) for record in wa.list_pending(wa.SKILLS)}
    staged = [{
        "profile": profile, "pending_id": row.get("pending_id"), "skills": row.get("skills") or [],
        "action": (row.get("actions") or [""])[0], "at": row.get("recorded_at"), "turn": row.get("turn"),
        "status": "pending" if row.get("pending_id") in pending else outcomes.get(row.get("pending_id"), "gone"),
    } for row in reversed(records) if row.get("kind") == "staged"
        and (not skill or skill in (row.get("skills") or [])) and _matches(row.get("turn"), chat_session_id, turn_id)]
    return changes, staged[:limit]


def list_changes(*, profile: str | None = None, skill: str | None = None, chat_session_id: str | None = None,
                 turn_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Applied skill changes (newest first, with diffs and the review's chat and turn) and staged writes.

    ``skill`` lists that skill's whole ledger history (any actor; ``review`` says which the review made);
    ``chat_session_id`` / ``turn_id`` list only the review changes that chat or turn made.
    """
    from agent_runtime.profile_context import process_home_scope
    from agent_runtime.review_skill_pending import profile_homes

    count = LIMIT_MAX if limit is None else limit
    if type(count) is not int or not 1 <= count <= LIMIT_MAX:
        raise ValueError(f"limit is 1..{LIMIT_MAX}")
    homes = profile_homes(profile)
    changes: list[dict[str, Any]] = []
    staged: list[dict[str, Any]] = []
    for name, home in homes:
        with process_home_scope(home):
            rows, waiting = _profile_changes(name, skill=skill or None, chat_session_id=chat_session_id or None,
                                             turn_id=turn_id or None, limit=count)
        changes.extend(rows)
        staged.extend(waiting)
    changes.sort(key=lambda row: str(row.get("at") or ""), reverse=True)
    return {"changes": changes[:count], "staged": staged[:count], "truncated": len(changes) > count,
            "profiles_scanned": [name for name, _home in homes]}
