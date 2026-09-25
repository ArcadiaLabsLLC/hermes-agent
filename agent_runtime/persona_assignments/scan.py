"""Whole-roster reads that must say what they could not read: the scan results
(``PersonaInstanceScan`` / ``PersonaAssignmentScan``), the typed refusal an arm
spends when rows are unreadable, the process-wide unreadable-row ledger, and the
session-presence probe the chat-binding repair reads.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, NamedTuple

from agent_runtime.models import PersonaAssignment, PersonaInstance
from agent_runtime.persona_assignments.vocabulary import PERSONA_ROWS_UNREADABLE

__layer__ = "stores"

__all__ = [
    "PersonaAssignmentScan",
    "PersonaInstanceScan",
    "PersonaScanRefusal",
    "reset_unreadable_instance_rows",
    "_note_unreadable_instance_row",
    "_session_presence_probe",
    "_unreadable_instance_lock",
    "_unreadable_instance_rows",
]


#: Which persona-instance ROWS this process has already re-minted for being
#: unreadable (IC-3). Process state, exactly like the read-model cache's own
#: convergence history, and for the same reason: "we already tried the repair
#: once" is a fact about this process, so a fresh process is entitled to try
#: again (the file may since have been fixed, or the disk unstuck).
#:
#: Keyed on the row's PATH so two stores — two profiles, two test roots — never
#: share an entry. It only ever grows within a process, by one entry per corrupt
#: row, which is bounded by the roster.
_unreadable_instance_rows: set[str] = set()
_unreadable_instance_lock = threading.Lock()


def _note_unreadable_instance_row(row_path: Path) -> bool:
    """Record an unreadable row; ``True`` the FIRST time this process sees it.

    The caller re-mints on ``True`` and reports on ``False``. One authority for
    "is this the first time", because a caller that re-derived the answer would
    be a second rule for the question the whole arm turns on.
    """

    key = str(row_path)
    with _unreadable_instance_lock:
        if key in _unreadable_instance_rows:
            return False
        _unreadable_instance_rows.add(key)
        return True


def reset_unreadable_instance_rows() -> None:
    """Forget the re-mint history, as a fresh process would. Tests only.

    Same shape and same reason as ``core_cache.reset_process_state``: a property
    of the PROCESS has to be resettable for a test to exercise a second
    process's behaviour without spawning one — and, here, so that one case's
    corrupt row cannot silence the next case's first legitimate repair when the
    two happen to resolve the same path.
    """

    with _unreadable_instance_lock:
        _unreadable_instance_rows.clear()


class PersonaInstanceScan(NamedTuple):
    """What a persona-instance scan FOUND, beside what it could not read.

    The second field is the whole point, and it is the same law
    :class:`~.office_store.ActorScan` states one subsystem over: the two facts
    have to travel TOGETHER, because any seam that carries only the rows
    re-opens the hole at that seam.

    ``PersonaInstanceStore.list_all`` has always skipped a file it could not
    decode and returned the rest, so every reader downstream received a SHORTER
    world that described itself as complete. For a projection that is a wrong
    number. For the arms that DECIDE on it, it is a delete: the steering repair
    computes ``live_ids`` from this list and strips every child edge pointing at
    a row that is merely unreadable, and the retire path's backlink release
    claims to have released EVERY child while never having seen one of them.
    """

    instances: list[PersonaInstance]
    #: How many ``*.json`` rows in the instances directory existed and did not
    #: decode. NEVER folded into ``instances`` and never silently zero.
    unreadable: int


class PersonaAssignmentScan(NamedTuple):
    """What a persona-assignment scan FOUND, beside what it could not read.

    The assignment twin of :class:`PersonaInstanceScan`. Its one reader that
    ACTED on the count — the retire guard — left with AX2; what remains reads
    the count to report it, so ``unreadable`` is display evidence rather than a
    write fence here.
    """

    assignments: list[PersonaAssignment]
    #: How many ``*.json`` rows in the assignments directory existed and did not
    #: decode. NEVER folded into ``assignments`` and never silently zero.
    unreadable: int


class PersonaScanRefusal(NamedTuple):
    """One persona-lane arm refusing rather than deciding on a short list.

    Returned (never raised) by the REPORT-shaped arms — the repair sweeps, whose
    contract is already "here is what I did and what I held". The raising arms
    carry the same fact as a typed error instead; both spell the reason with
    :data:`PERSONA_ROWS_UNREADABLE`, minted below, so the operator reads one
    word for one condition however it reached them.
    """

    scope: str
    unreadable: int
    reason: str = PERSONA_ROWS_UNREADABLE

    @classmethod
    def for_scan(cls, scope: str, unreadable: int) -> "PersonaScanRefusal | None":
        """THE mint. ``None`` means the world was fully readable — so an arm can
        neither report a refusal it did not earn nor default-construct one that
        swallows the count."""

        if not unreadable:
            return None
        return cls(scope=scope, unreadable=int(unreadable))

    def as_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "reason": self.reason, "unreadable": self.unreadable}


def _session_presence_probe(session_db: Any | None = None) -> tuple[Any | None, str | None]:
    """Return ``(probe, skip_reason)`` for chat-session existence checks.

    The probe answers ``"present" | "absent" | "unknown"`` — tri-state on
    purpose. ``get_session`` swallowing an error and returning ``None`` would
    make an unreadable database indistinguishable from a deleted chat, and a
    repair built on that would reap live pointers on a transient failure.

    Three preconditions must hold before ANY binding may be called stale, and
    all fail closed (probe ``None`` + a typed skip reason):

    * when the database is self-resolved, the head home must be EXPLICITLY
      named by this process — relay context or ``HERMES_HEAD_HOME``
      (``head_home_not_authoritative``). ``chat_session_scope`` otherwise falls
      back to the shared runtime root's recorded head pointer and, failing
      that, to the ambient ``HERMES_HOME``; both are fine for reading or
      minting a transcript and neither may decide that a live binding is
      stale. Without that rule a maintenance verb run under a profile home
      probes that profile's database and reads every operator chat as absent —
      a POPULATED wrong database sails straight past the empty-DB guard (live
      2026-07-25: a reconcile under the alice profile home cleared 10 live
      chat bindings on a false ``session_missing_from_session_db`` verdict).
      A caller that passes ``session_db`` explicitly owns its own routing;
    * a database must resolve at all (``session_db_unavailable``);
    * it must positively enumerate at least one session (``session_db_empty``).
      A zero-row database is indistinguishable from a fresh or misrouted
      ``HERMES_HOME``, and "the home moved" must never present as "every chat
      was deleted".
    """

    db = session_db
    if db is None:
        try:
            from ..chat_session_scope import resolve_process_chat_scope

            from ..persona_chat_history import _default_session_db

            # DESTRUCTIVE posture: a head RECORDED for the shared runtime root
            # is enough to read or mint a transcript, and deliberately NOT
            # enough to clear a live binding. This lane still requires that THIS
            # process named the head — byte-identical to the shipped 8c3942a21
            # guard. The acquisition itself stays on the shared
            # ``_default_session_db`` delegate, so there is still exactly one.
            # A PROCESS question — "did this process name a head" — not a
            # per-conversation one, so it resolves on the process ladder.
            if not resolve_process_chat_scope().explicitly_named:
                return None, "head_home_not_authoritative"
            db = _default_session_db()
        except Exception:
            db = None
    if db is None:
        return None, "session_db_unavailable"
    try:
        sample = db.list_sessions_rich(limit=1, include_archived=True)
    except Exception:
        return None, "session_db_unavailable"
    if not sample:
        return None, "session_db_empty"

    def probe(session_id: str) -> str:
        try:
            row = db.get_session(session_id)
        except Exception:
            return "unknown"
        return "present" if row else "absent"

    return probe, None
