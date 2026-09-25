"""Unified ``running_work`` projection — what background work is running RIGHT NOW.

One aggregator, five lanes (terminal background processes, background subagent
delegations, in-flight mission-chat turns, detached agent-to-agent dispatches,
and cron jobs), producing ONE row vocabulary so an operator surface never has
to know which subsystem spawned a piece of work.

Connected MCP transports are deliberately NOT a lane. A warm connection is
capability infrastructure, not work: it can outlive the agent turn that admitted
it, can be reused by several persona instances, and has no single truthful
owner. Active MCP calls already travel with the owning chat turn's tool trace;
counting the connection itself made an idle runtime claim background motion.

Durable-first, and that is the whole architecture
-------------------------------------------------
The CLI snapshot lane, the serve process, and the stream are SEPARATE
PROCESSES. Every in-memory registry in this runtime (``process_registry``,
``async_delegation._records``, the cron scheduler's running-id set) lives only
inside the process that spawned the work. A
projection built from those registries alone would report an empty HUD from any
other lane and call it "nothing running" — the exact silent-lie class this
module exists to retire.

So each lane declares a DURABLE view (readable from anywhere: the
``processes.json`` checkpoint, the ``async_delegations`` table, the mission-chat
turn journal) and an optional LIVE enrichment.

Residency is not ownership — this cost a design iteration and is worth stating
plainly. The obvious liveness test, "is ``tools.process_registry`` in
``sys.modules``?", is WRONG here: ``agent_runtime.mission_chat_turns`` already
drags ``tools.process_registry``, ``tools.async_delegation`` and
``cron.scheduler`` into any process that reads the turn journal, so residency is
true almost everywhere and proves nothing about who owns the work. What each
registry can honestly report is therefore split in two:

* **Durable-backed lanes** (terminal, delegation) merge live rows when the
  registry HAS any. A registry in a non-owning process returns an empty list,
  which enriches nothing and drops nothing, and the lane keeps reporting
  ``durable`` — it only claims ``live`` once live rows were actually observed.
* **Live-only lanes** (cron jobs) have no durable record at all, so they apply
  the rule *presence proves, absence proves nothing*: this process is the owner
  only if it holds cron pool/running-id state. Without that proof the lane
  reports ``unavailable``, because an empty
  ``get_running_job_ids()`` in a non-scheduler process is indistinguishable from
  "no cron jobs are running anywhere" and rendering it as the latter is exactly
  the silent lie this projection exists to retire.

``sys.modules.get(...)`` is still used as the cheap first gate — never
``import_module`` — so that a lane this process genuinely knows nothing about
costs nothing to skip, and so a read-only projection never constructs a tool
singleton as a side effect of being asked a question.

Five honesty rules, all prior operator rulings — do not relax
------------------------------------------------------------
1. **Fail-closed per source.** Every lane contributes a ``sources`` entry
   (``ok`` / ``unavailable`` + reason). A lane that cannot be read is REPORTED
   unavailable; it never degrades into a silently empty row list, because
   "nothing is running" and "I could not look" are different facts and an
   operator must be able to tell them apart.
2. **PID honesty.** A stored PID is not proof of life: the kernel recycles PID
   numbers, and this repo has already been bitten by a recycled number landing
   on an unrelated desktop process. Identity is verified against the
   ``host_start_time`` captured at spawn (the same guard
   ``process_registry._host_pid_is_ours`` applies before it will signal
   anything). A row whose identity cannot be PROVEN carries
   ``pid_verified: false`` and status ``unknown`` — never ``running``. A row
   whose identity is actively DISPROVEN (dead PID, or a recycled number) is not
   running work at all and is dropped through the accountant, never silently.
3. **Liveness honesty.** ``running`` means progress was observed, not that a
   record exists. Delegations carry the stale monitor's progress token, so a
   wedged child surfaces as ``stalled`` even before the 30s monitor sweep
   notices. Where no progress signal is readable (durable lane), ``progress``
   declares itself ``unavailable`` rather than reporting zeros that read as
   "idle".
4. **Bounded previews by design.** ``tail_preview`` is capped at
   :data:`TAIL_PREVIEW_LIMIT` characters and the truncation is declared
   ``by_design`` in the parity accounting, so a deliberate bound never trips the
   amber "lost data" pill.
5. **Owner honesty.** Every lane that can name a session resolves its owner
   through :func:`_owner_of` — one authority, shared with the dispatch-delivery
   lane — and NEVER derives one itself. A session that resolves to no persona
   instance ships an EMPTY owner block; it is never filled in with the parent's
   persona, the active instance, or any other plausible-looking stand-in.
   Consumers group by owner, so this rule cuts both ways and both halves are
   load-bearing: omitting a resolvable owner makes real work invisible (which is
   what a background ``delegate_task`` did on Mission Control's Activity
   surface — never appearing, not appearing late), and inventing an
   unresolvable one attributes work to an agent that is not doing it. A blank is
   renderable as "no owning agent"; a wrong name is not un-believable.

Path resolution and the HERMES_HOME flip
----------------------------------------
``persona_profile_context`` flips ``HERMES_HOME`` PROCESS-GLOBALLY for the
duration of a persona turn, and persona turns run inside the serve process —
the same process that builds snapshots on another thread. Resolving
``processes.json`` / ``state.db`` through ambient ``get_hermes_home()`` would
therefore read a different profile's files depending on what was mid-turn at
the instant the projection ran. Both durable stores resolve through the
head-home scope (:func:`agent_runtime.chat_session_scope.resolve_chat_session_scope`),
the same durable pointer the chat lane uses, with ambient home as a declared
fallback only when that resolver itself fails.

Contract is wire; ambient is context — and they never share a string
--------------------------------------------------------------------
A source entry's ``status`` / ``lane`` / ``reason`` are CONTRACT: a consumer
branches on them, and this module owes them a stable vocabulary. Everything
else a lane could say about itself is AMBIENT — which directory the projection
resolved, what the filesystem under it happens to contain — machine-local
context, not a fact about work.

The first implementation concatenated the two into one ``detail`` prose string
(``"head_home=base; no state.db"``), and that mixing did not merely read badly:
it made the producer NON-DETERMINISTIC. Concretely, ``_collect_delegations``
runs before ``_collect_chat_turns`` and reported whether ``state.db`` existed;
the chat-turn lane's lazy ``from . import mission_chat_turns`` drags
``model_tools`` → ``tools.registry.discover_builtin_tools()`` →
``tools.process_registry``'s module-scope singleton — whose constructor, at
the time, ran ``async_delegation.restore_undelivered_completions()`` and
CREATED that very ``state.db`` (retired since; see the end of this
docstring). So the FIRST build in a process said ``"; no state.db"`` and every
later build did not, for identical work and an identical contract — and under
pytest which answer you got was decided by whether some other test module had
already dragged that import chain in. A producer whose output depends on hidden
import state cannot be pinned honestly by anyone, which is why the mixing is the
bug rather than the prose.

The split this module now keeps:

* **Contract, on each source entry.** ``status``, ``lane``, ``reason``, the
  bounded ``detail`` an UNAVAILABLE lane attaches (already a bare machine token
  — an exception class name — never prose), and ``live_enrichment_error``: the
  typed exception class name recorded when a live enrichment raised while the
  durable answer survived. Absence of the last is unambiguous — the enrichment
  did not raise — which is why it is a bare token rather than a nullable block.
* **Ambient, in ONE clearly-named block.** :func:`_ambient_context`, published
  as ``ambient`` beside ``rows`` / ``sources`` / ``counts``. It names the
  resolved background-work home — provenance plus BASENAME only, because the
  error contract forbids absolute paths in operator messages — so "0 processes"
  can still be told apart from "0 processes *in the home I happened to
  resolve*", the diagnostic the writer/reader divergence above cost an entire
  build to learn. **No consumer is expected to depend on it, and nothing in
  this module branches on it.**
* **Off the wire entirely: store PRESENCE.** ``"no checkpoint file"``,
  ``"no state.db"`` and ``"no async_delegations table"`` were observations about
  storage LAYOUT, not about work — a durable lane answering ``ok`` with zero
  rows out of a named home is already the complete honest answer — and two of
  the three were perturbed by the import chain above, so they could never have
  been reported honestly at all.

This module is READ-ONLY with respect to every store it touches: it opens no
database it would have to create, marks no output consumed, and takes no lock a
writer could be waiting on. That invariant used to hold only for the stores
this file reads DIRECTLY: ``_collect_chat_turns``'s import chain reached a
tool singleton whose CONSTRUCTOR ran delegation recovery — creating
``state.db`` and reclassifying owner-dead delegations as an import side
effect. That constructor I/O is retired: the restore now runs only through
``process_registry.restore_durable_completions()``, called explicitly by the
entry points that own a completion drain, so the invariant holds for the
whole build in a cold process. It is pinned behaviourally (fresh-interpreter
subprocess: no ``state.db`` appears, and a seeded ownerless ``running``
delegation is not reclassified) in ``tests/agent_runtime/test_running_work.py``.
``model_tools``' module-scope ``discover_builtin_tools()`` call itself remains
eager — still an import-cost weakness, filed with measurements and a lazy-
discovery plan in
``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/eager-tool-discovery-audit-2026-08-09.md``.

The package map (program rule 16; layout sheet ``running_work.md`` §1)
----------------------------------------------------------------------

Modules, lowest layer first; no module imports one above it (W0-G6)::

    agent_runtime/running_work/
      __init__.py       wiring  this docstring + map; re-exports the importers' and the tests' names
      vocabulary.py     models  PROJECTION, the limits, KIND_* / RUNNING_WORK_KINDS / _SOURCES, STATUS_*,
                                SOURCE_*, LANE_*, REASON_NOT_IN_PROCESS, the stale fallbacks, the two
                                store filenames, PID_* (a vocabulary module: exempt from the floor)
      rows.py           policy  the row and source shape every lane emits: bounded text, ISO stamps,
                                progress, the row, the preview, the source entry, the per-lane cap
      ownership.py      stores  the head home, running_work_store_paths (the ONE authority), PID
                                identity (rule 2), the session owner (rule 5), the ambient block
      lanes_process.py  lanes   liveness is a PROCESS this runtime owns: terminal, cron
      lanes_chat.py     wiring  keyed on a chat session's durable store: delegations, chat turns,
                                dispatches
      surface.py        wiring  _COLLECTORS (the table over the five lanes), build_running_work,
                                find_work_row, split_work_id, peek_work, cancel_work

    entry point                                  opens
    build_running_work (snapshot, work list)     surface -> lanes_process -> lanes_chat
    any one collector, followed on its own       its lane module -> rows -> ownership
    cancel_work (harness work cancel)            surface -> lanes_process -> ownership
    peek_work                                    surface -> rows
    running_work_store_paths (core cache,        ownership
      stream, serve boot)

``lanes_chat`` is ``wiring`` only because its chat-turn lane imports the
``mission_chat_turns`` package map (itself ``wiring``); ``surface`` follows it.

A monkeypatch lands where a name is BOUND: ``_head_home`` / ``_module`` are
read by every lane module that imported them, so a stub on this package's
attribute reaches none of them — patch the binding module.
"""

from __future__ import annotations

from . import lanes_chat, lanes_process, ownership, rows, surface, vocabulary
from .lanes_chat import (
    _collect_chat_turns,
    _delegation_status,
)
from .lanes_process import (
    _cron_owned_here,
)
from .ownership import (
    _head_home,
    _owner_of,
    _pid_identity,
    running_work_store_paths,
)
from .rows import (
    _iso_from_naive_local,
    _module,
    _preview,
    _stale_thresholds,
)
from .surface import (
    _COLLECTORS,
    build_running_work,
    cancel_work,
    find_work_row,
    peek_work,
    split_work_id,
)
from .vocabulary import (
    KIND_CHAT_TURN,
    KIND_CRON_JOB,
    KIND_DELEGATION,
    KIND_DISPATCH,
    KIND_TERMINAL,
    LANE_DURABLE,
    LANE_LIVE,
    PEEK_TAIL_LIMIT,
    PID_DEAD,
    PID_NO_BASELINE,
    PID_RECYCLED,
    PID_START_TIME_UNREADABLE,
    PID_VERIFIED,
    PROJECTION,
    REASON_NOT_IN_PROCESS,
    RUNNING_WORK_KINDS,
    RUNNING_WORK_SOURCES,
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_FINALIZING,
    STATUS_RUNNING,
    STATUS_STALLED,
    STATUS_STALLING,
    STATUS_UNKNOWN,
    STATUS_VALUES,
    TAIL_PREVIEW_LIMIT,
    _CHECKPOINT_FILENAME,
    _MAX_ROWS_PER_SOURCE,
    _STATE_DB_FILENAME,
)

__layer__ = "wiring"

__all__ = [
    "KIND_CHAT_TURN",
    "KIND_CRON_JOB",
    "KIND_DELEGATION",
    "KIND_DISPATCH",
    "KIND_TERMINAL",
    "PEEK_TAIL_LIMIT",
    "PROJECTION",
    "RUNNING_WORK_KINDS",
    "RUNNING_WORK_SOURCES",
    "STATUS_VALUES",
    "TAIL_PREVIEW_LIMIT",
    "build_running_work",
    "cancel_work",
    "find_work_row",
    "peek_work",
    "running_work_store_paths",
    "split_work_id",
]
