"""The build's receipt facts: build roles and callers, the coalescing state, the
runtime-paths diagnostic and the chat-history frame a build carries.
"""

from __future__ import annotations

import threading
from typing import Any

from agent_runtime.redaction import TEXT_SECRET_ASSIGNMENT_RE

__all__ = [
    "BUILD_CALLER_UNKNOWN",
    "BUILD_ROLE_CACHE",
    "BUILD_ROLE_LED",
    "BUILD_ROLE_REUSED",
    "BUILD_ROLE_RODE",
    "BUILD_ROLE_SHARED_NEXT",
    "BUILD_SECTIONS_WAIT_THRESHOLD_MS",
    "_ARCHIVED_CONVERSATION_SECRET_RE",
    "_BUILD_COALESCE",
    "_build_coalesce_state",
    "_keyed",
    "_persona_chat_history_frame",
    "_runtime_paths_diagnostic",
    "_sections_top",
    "build_receipt_facts",
]


# S2 read-model — history out of the live frame (operator move 6).
# The persona-chat message tails are append-only HISTORY: read on demand at
# most, never advancing. They are evicted from the steady-state frame and served
# via a paged on-demand query (``harness persona chat history``).
# Archive-never-delete: eviction removes rows from the FRAME, never from disk.
#
# S7-B RULING-0 COMPAT STRIP (2026-07-16): the ``read_model.history_in_frame``
# kill-switch and its full-in-frame legacy branches were removed here — the
# evicted (pointer-stub) shape is the ONLY shape. Rollback = ``git revert``, not
# a flag flip. The helper below always evicts.
#
# S29: the sibling ``archived_tasks`` and ``incidents`` eviction helpers are
# gone. S9 removed both as frame sections and S27 removed the archived-task
# reader, so ``_open_incidents_frame`` had no list left to split and
# ``snapshot_section_bytes`` had no section left to weigh; both survived S27
# only as extra reachability roots seeded from a TEST pin, which is not a
# caller. See tests/agent_runtime/test_s29_snapshot_dead_local_removal.py (deleted 2026-09-24).


def _persona_chat_history_frame(rows: list) -> list:
    """The ``persona_chat_history`` frame rows: recency pointers only.

    Keeps every recency pointer (session id + last-message anchors + counts +
    timestamps) but drops the heavy ``messages`` tail, flagging each row so a
    consumer distinguishes an evicted tail from a genuinely empty chat. The tail
    is fetched per session via
    ``harness persona chat history --session-id <id> --json``."""

    pointers: list = []
    for row in rows:
        if not isinstance(row, dict):
            pointers.append(row)
            continue
        pointer = {key: value for key, value in row.items() if key != "messages"}
        pointer["messages"] = []
        pointer["messages_evicted"] = True
        pointers.append(pointer)
    return pointers


# S4 read-model — normalize (operator moves 4 + 5). The on-disk stores are
# already file-per-entity keyed by id; the fuser used to de-key them into lists
# every consumer re-keyed. S4 exposes the keyed shape directly: list sections
# whose rows carry a canonical id become ``{id -> row}`` maps. GOAL is the wire
# entity name (operator decision 2026-07-16): the goals/tasks dual projection
# collapses to ONE keyed ``goals`` map and the ``tasks`` wire section retires.
# This is a NAMING/projection change only — the internal ``TaskStore`` machinery
# keeps its Task names (the 45E store rename stays deferred). Emitted
# unconditionally (no kill-switch): the rollback story is ``git revert`` of the
# landing, not a runtime legacy-shape flag.
def _keyed(rows, id_key: str) -> dict:
    """A list of id-carrying rows -> an id-keyed ``{id -> row}`` map.

    One owner per fact: the frame exposes the store's existing keyed shape
    instead of a list every consumer re-keys. First occurrence wins on a
    duplicate id (a duplicate is a parity concern surfaced elsewhere, never a
    silent overwrite); a row missing the id is dropped rather than silently
    keyed under ``""`` (no silent-drop-without-accounting — a missing canonical
    id is itself a bug the parity envelope's warnings catch).
    """

    keyed: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get(id_key)
        key = str(raw) if raw is not None else ""
        if not key or key in keyed:
            continue
        keyed[key] = row
    return keyed


# Single-homed in ``agent_runtime.redaction`` — see the header there for the
# JSON blind spot every local spelling shared. This is the same rule as
# ``persona_chat_history._SECRET_RE`` (also imported into this module); both now
# resolve to the one shared object. group(1) is still the key, so the
# ``f"{m.group(1)}: [redacted]"`` rebuild below is unchanged.
_ARCHIVED_CONVERSATION_SECRET_RE = TEXT_SECRET_ASSIGNMENT_RE


def _runtime_paths_diagnostic(available_personas: list) -> dict:
    """TEMP diagnostic: report the paths/env this process actually resolved,
    so the Launcher can see why available_personas came back empty."""
    import os as _os

    out: dict = {"available_personas_count": len(available_personas or [])}
    try:
        from hermes_constants import get_hermes_home, get_default_hermes_root

        out["env_HERMES_HOME"] = _os.environ.get("HERMES_HOME", "<unset>")
        out["env_HERMES_AGENT_RUNTIME_ROOT"] = _os.environ.get("HERMES_AGENT_RUNTIME_ROOT", "<unset>")
        out["env_LOCALAPPDATA"] = _os.environ.get("LOCALAPPDATA", "<unset>")
        out["resolved_hermes_home"] = str(get_hermes_home())
        out["resolved_default_root"] = str(get_default_hermes_root())
    except Exception as exc:  # pragma: no cover - diagnostic only
        out["error"] = repr(exc)
    try:
        from .._upstream_doors import profiles_root

        root = profiles_root()
        out["profiles_root"] = str(root)
        out["profiles_root_exists"] = root.is_dir()
        out["profiles_root_entries"] = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    except Exception as exc:  # pragma: no cover - diagnostic only
        out["profiles_error"] = repr(exc)
    return out


# Concurrent core builds are strictly additive under the GIL — measured
# 2026-07-09 on the live store: one warm build 3.3s, three concurrent builds
# 8.8s EACH (the launcher's "snapshot build 9050ms" chip). Mission Control
# boot fires hydrate + status polls together, so without coalescing every
# boot request pays the whole storm. Builds on the default-store path are
# therefore serialized and coalesced: a caller arriving while a build runs
# waits and shares the NEXT build (never the in-flight one — its state may
# predate the caller's arrival), so N concurrent requests cost at most two
# sequential fast builds. Sharing copies via copy.deepcopy, NOT a JSON
# round-trip: the core carries datetime objects, and a json.dumps here
# raised TypeError and silently disabled sharing on the live store (found
# 2026-07-09 — the unit fakes were JSON-safe). The builder deep-copies once
# into the share slot and every waiter deep-copies out, so no two callers
# ever alias one snapshot dict.
_BUILD_COALESCE = threading.Condition()


_build_coalesce_state: dict = {
    "running": False,
    "started": 0,
    "done": 0,
    "result": None,
    "waiters": 0,
}


#: The three roles a caller of :func:`build_snapshot` can leave in with, and the
#: exact tokens both this module's receipt line and
#: ``agent_runtime.stream``'s wait line print. ONE vocabulary, because the whole
#: point of the attribution is that three log lines stop looking like three
#: builds: ``led`` ran a build, ``rode`` shared the build that was ALREADY
#: running (``accept_inflight``), ``shared_next`` waited and got the deep copy of
#: the next build somebody else led. A boot's build COUNT is therefore the count
#: of ``led`` lines — never the count of lines.
BUILD_ROLE_LED = "led"


BUILD_ROLE_RODE = "rode"


BUILD_ROLE_SHARED_NEXT = "shared_next"


#: The fourth role, added by EG-3.1: this caller ran no build and rode no
#: build — the persisted core's fingerprint matched, so the projection was
#: LOADED. It is a role rather than a silence for the same reason the other
#: three are: the boot's build count is the count of ``led`` lines, and a cache
#: hit that printed ``led`` would put the log straight back into the state where
#: a wait and a build are indistinguishable. See
#: :func:`agent_runtime.core_cache.first_core` for the receipt it emits instead.
BUILD_ROLE_CACHE = "cache"


#: The fifth role (W3-H2): this caller ran no build, rode no build and consulted
#: no persisted pair — the core of the PREVIOUS demote build at this same event
#: offset was still valid and was handed back
#: (:mod:`agent_runtime.demote_core_reuse`). Never produced by this module: the
#: reuse happens one layer out, in the stream's demote lane, and the token lives
#: here so the role vocabulary stays single. It exists for the same reason
#: ``cache`` does — the build COUNT is the count of ``led`` lines, and a reuse
#: printing ``led`` would put the log straight back into the state where a
#: rebuild and a hand-back are indistinguishable, which is the state the three
#: identical builds at offset 89961793 were found in.
BUILD_ROLE_REUSED = "reused"


#: A caller that named itself nothing. Kept as a token rather than an empty
#: value so the receipt line's key is never absent — a parser reading
#: ``caller=`` off the line must not have to tell "no such key" apart from
#: "nobody said".
BUILD_CALLER_UNKNOWN = "unknown"


#: Sections are printed on a WAIT line only when the underlying build was slow
#: enough for the split to be the question being asked (HC-0). The leader's own
#: receipt always carries them: a build that took 900 ms still answers "of
#: what?" for free, and it is one line per build, not one per caller.
BUILD_SECTIONS_WAIT_THRESHOLD_MS = 5000


def build_receipt_facts(snapshot: Any) -> dict[str, Any]:
    """The attribution facts a build's receipt line carries, read off the core.

    ``build_ms``, ``sections_ms`` and ``watermark.event_offset`` are already
    computed by the build itself and shipped on the parity envelope. This reads
    them; it does not measure anything. A second measurement of the same span
    would be a second authority on it, and the two would drift — which is the
    exact defect the heartbeat's mid-build ``elapsed_ms`` sample already is
    (see ``agent_runtime.stream._log_snapshot_build``).

    Single-homed here because two log lines print these facts — the leader's
    ``snapshot_build_core`` below and the waiter's ``snapshot_build`` in the
    stream — and a launcher-side parser reads both. Defensive by construction:
    a caller may hold a fake or partially-built core (every unit fake does), and
    an instrument must never be the reason a build fails.
    """

    parity = snapshot.get("parity") if isinstance(snapshot, dict) else None
    if not isinstance(parity, dict):
        parity = {}
    watermark = parity.get("watermark")
    if not isinstance(watermark, dict):
        watermark = {}
    raw_build_ms = parity.get("build_ms")
    raw_offset = watermark.get("event_offset")
    return {
        "build_ms": int(raw_build_ms) if isinstance(raw_build_ms, (int, float)) else None,
        "offset": int(raw_offset) if isinstance(raw_offset, (int, float)) else None,
        "sections_top": _sections_top(parity.get("sections_ms")),
    }


def _sections_top(sections: Any, limit: int = 3) -> str:
    """The ``limit`` most expensive build sections, as ``name:ms,name:ms``.

    Sorted by cost descending, then by name, so consecutive boots of the same
    shape print the same string and a diff means the shape moved.
    """

    if not isinstance(sections, dict):
        return "-"
    rows = [
        (str(name), int(value))
        for name, value in sections.items()
        if isinstance(value, (int, float))
    ]
    if not rows:
        return "-"
    rows.sort(key=lambda row: (-row[1], row[0]))
    return ",".join(f"{name}:{value}" for name, value in rows[:limit])
