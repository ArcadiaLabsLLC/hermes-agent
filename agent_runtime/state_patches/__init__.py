"""The patch lane — op-based, WIRE-LEVEL ``state.patched`` log entries (the package map, rule 16).

Entry points (what calls in) and the modules to open, at most three:

* ``emit_office_*`` / ``emit_persona_instance_*`` — every store chokepoint →
  ``office`` or ``persona_instance`` → ``emit`` → ``payload`` (``models`` is the
  table they read).
* ``emit_scope_patch`` (``store.set_active``) → ``emit`` → ``payload``.
* ``normalize_correlation_id`` (``serve_rpc.params``) and ``office_patch_scope``
  (``serve_office_subscriptions``) → ``payload``.
* ``delta_patches_enabled`` (``stream``, ``patch_coverage``) → ``emit``.

Modules, lowest layer first (no module imports one above it — W0-G6):

================  ======  ======================================================
module            layer   owns
================  ======  ======================================================
models            models  ops, entities, the size budget, the store→wire field
                          table, the correlation-id grammar (vocabulary)
payload           policy  ``build_state_patch`` (the 4 KB shrink ladder),
                          ``normalize_correlation_id``, the office id scheme and
                          its inverse ``office_patch_scope``
emit              stores  the flag (``delta_patches_enabled`` + the ROOT-config
                          fault probe), ``emit_state_patch`` — the ONE
                          ``EventLog.append`` — and ``emit_scope_patch``
persona_instance  stores  the persona-instance projections + patch / create /
                          remove emitters
office            stores  the office projections + the six actor / conflict /
                          surface emitters
================  ======  ======================================================

``store`` lazily imports ``emit.emit_scope_patch`` while ``persona_instance`` and
``office`` lazily import ``store`` back; both stay lazy, and this map imports
nothing above ``config``, so no module in the package can close the loop.

The lane
========
S7-A producer: op-based, WIRE-LEVEL state-patch log entries (flagged, shipped on).

Read-model workstream Stage S7-A, producer half. When ``read_model.delta_patches``
is on, a store *chokepoint* that mutates a keyed entity emits a ``state.patched``
EventLog entry carrying a **wire-level op**::

    {"entity": "<class>", "id": "<actor_id>", "op": "upsert", "changed": {...}}
    {"entity": "<class>", "id": "<actor_id>", "op": "remove"}
    {"entity": "<class>", "id": "<actor_id>", "op": "refresh"}

The design move (plan §S7-A). S6 shipped RAW store-field patches
(``changed: {model: "x"}``) which the launcher could not fold with fidelity —
the wire rows carry hermes-PROJECTED derived fields (``effective_model``,
``model_is_override``, ``reasoning_supported``, ``skills``, the
``agent_profile_display_name`` mirror, …) that a raw field-merge would leave
stale. S7-A fixes it at the source: at emit time hermes projects the changed
entity **through the exact per-entity projection ``snapshot.py`` uses** and the
patch carries the projected WIRE fields (op ``upsert``) or a removal (op
``remove``). The launcher folds the projected fields verbatim — one authority
(hermes projects; the launcher never re-derives), fidelity trivial for every
covered field, no per-field allowlist.

* ``upsert`` — ``changed`` is the projected wire fields the mutation affected
  (the changed store fields' wire projections PLUS the derived wire fields that
  depend on them, recomputed). The launcher merges ``changed`` into
  ``Map<id, row>[id]`` (creating the row if absent).
* ``remove`` — the actor left the live frame (an open-only incident closed; a
  persona instance closed / task-terminal fan-out). The launcher deletes the row.
* ``refresh`` — the projected payload does not fit the 4 KB EventLog cap even
  after per-field oversize marking (a goal row is ~80 KB). An accounted degrade,
  never a silent drop: the launcher re-fetches that actor via checkpoint / rides
  the next full core.

  **The "~18 KB persona-instance row" this line used to name is gone**, and the
  correction is worth keeping because the stale figure cost a 6.5-second
  regression a full day's ownership. R2's residue slimming evicted the
  tool-detail payloads — ``tool_resolution`` / ``turn_tool_context`` /
  ``permission_state`` / ``blocked_tools``, ~97% of the row's bytes — behind a
  typed ``visibility_ref``. Measured against the operator's live roster
  (2026-08-16, 17 instances): the largest COMPLETE row is 3,012 bytes, the
  largest assembled ``{entity,id,op,changed,created}`` payload 3,133, and the
  largest single value 504 — comfortably inside the 4,096-byte cap and the
  3,584-byte per-value budget. That measurement is what unblocked D3 (the
  create-upsert below); it is re-taken by a test rather than trusted, because a
  field added to ``persona_instance_summary`` moves it.

The ``seq``/``ts`` come from the EventLog's own envelope (the stream assigns the
sequence; ``Event.ts`` is the timestamp) — the payload carries only the op.

Sizing. The payload must fit the hard ``EVENT_PAYLOAD_LIMIT_BYTES = 4096`` cap
``EventLog.append`` enforces. For an ``upsert`` a ``changed`` value whose
serialized size would overflow is first replaced by an **accounted**
``{"oversize": true, "bytes": N}`` marker; if the assembled payload STILL
overflows, the whole patch degrades to ``op: "refresh"`` (dropping ``changed``)
— accounted, never a partial merge the launcher cannot vouch for.

Inertness. With the flag off, :func:`emit_state_patch` and the per-entity
emitters return before any projection or append and never mutate the log — the
diff is provably inert, and the (moderate) projection cost is paid only when the
lane is live. Config-load failures also degrade to "off" (never take a store
mutation down), mirroring the observe-and-warn posture of the EventLog contract
validator — but they now WARN, because an unannounced off is the failure mode
this lane already lost its whole life to.

The flag SHIPS ON as of 2026-08-14
(:data:`agent_runtime.runtime_config.SHIPPED_DELTA_PATCHES`); off is now an
operator's explicit ROOT-config ``false``, or an accounted fault.

History
=======

What an office patch invalidated on disk (the retired ``snapshot.json`` boot-paint lane)
---------------------------------------------------------------------------------------

What an office patch INVALIDATES on disk: nothing — and that is a measured
fact about a lane NOBODY owns, not a choice this leg made.

The launcher used to paint from a disk-cached snapshot at boot before
authoritative truth arrived. That cache was ``paths.snapshot_path()``
(``snapshot.json`` in the store root), and the question "what happens to it
when a patch folds" had a flat answer: it is not touched, it cannot be touched
from here, and it was already going stale before this leg existed.

BOTH ENDS OF THAT LANE ARE NOW RETIRED — the launcher's reader at MC-7 / P11,
this repo's writer at Stage 6 (2026-08-22) — so the paragraphs below are kept
as the RECORD of a question that was asked and answered, not as a description
of live behaviour. They are worth keeping because the reasoning is what
retired the lane: a cache with a writer, no reader, and no staleness bound is
not a fast path, and the way that was established is by walking the writer set
rather than by trusting the config key that advertised it.

* There is NO writer at all any more, which is stronger than what this note
  used to claim and reached by the same reasoning. The only writer was
  :func:`snapshot.write_snapshot`, reached from exactly one production call
  site — ``read_model.resolve_snapshot_frame``, i.e. the ``harness snapshot``
  CLI verb. Stage 6 (2026-08-22) deleted both, because the CONSUMER had already
  left: the launcher's cold-paint reader was retired at MC-7 / P11. So the file
  is now a legacy artifact of stores written before that cut, and nothing in
  this repo produces it. The stream lane called ``build_snapshot()`` and never
  ``write_snapshot`` throughout, and EG-3.1 did not change that: the persisted
  core serve writes and reads lives somewhere else entirely (under
  ``<store_root>/serve_read_model/``, in a generation directory that
  ``agent_runtime.core_cache`` publishes through a pointer file — MCF-21. The
  filenames are deliberately not respelled here: ``core_cache.core_path`` and
  ``sidecar_path`` are their one authority, and a second copy of a layout is a
  thing that goes stale).
* The launcher has NO writer at all — it only reads the file — and a folded
  core never reaches it (``MissionReadModel.commitFold`` mutates memory only).
  The cache is also never used as a fold BASE, so it can neither corrupt nor
  be corrected by this lane.
* The launcher's cached-boot lane gates on CONTRACT SHAPE, not freshness: no
  TTL, no age check, no watermark comparison. A ``snapshot.json`` written
  weeks ago paints on boot if it parses.

So the staleness the office push leg is accused of creating is pre-existing
and lane-wide: every persona-instance patch since S7-A, and every full-core
stream delta too, has left that file untouched. This leg does not widen the
window; it makes reaching it cheaper, because cheap patches flow more often.

What this leg therefore does NOT do, deliberately: invalidate or rewrite
``snapshot.json`` from the office chokepoint. Doing so would put a
cross-process file mutation on a drag's hot path, and deleting it would take
the boot-paint fast path away from every surface to fix one section of it.

WHAT WAS OPEN HERE, and how it closed: the cached boot lane had no defined
staleness bound and no receipt saying which frame it painted. The two fixes
offered were (a) a freshness gate on the cached read — the file's
``generated_at`` is already in it — or (b) a boot receipt naming the cache's
age. Neither was taken, and neither is needed now: the lane itself was retired
from both ends rather than bounded, which is the third answer this note did not
list. Note the office is the one section where a client can already detect its
own staleness unaided: ``runtime.office.get`` puts the actor ``revision`` on
every item, so a cached canvas can be diffed against server truth for ~2.5 KB.

Removed emitters
----------------

S54 removed ``emit_task_refresh``: the task-refresh patch op, orphaned since
the ``Task`` record went at S8.

S66 removed ``emit_incident_remove`` for the same reason one wave later: its
only chokepoint was ``IncidentStore.close``, which S65 retired when the store
became a historical reader. The paired ``incident.closed`` domain event was
de-registered in that same wave, so nothing could produce either half. See
``patch_coverage.HISTORICAL_COVERED_DOMAIN_EVENT_TYPES``, which now names the
fold-classifier entries that outlived their producers instead of leaving them
indistinguishable from live ones.
"""

from __future__ import annotations

from agent_runtime.state_patches.models import (  # noqa: F401 — the package's export floor
    CORRELATION_ID_KEY,
    CORRELATION_ID_MAX_LEN,
    FOLDABLE_PATCH_OPS,
    OFFICE_ACTOR_ENTITY,
    OFFICE_CONFLICT_ENTITY,
    OFFICE_SURFACE_ENTITY,
    OFFICE_SURFACE_PATCH_FIELDS,
    PATCH_ENVELOPE_HEADROOM_BYTES,
    PATCH_OP_REFRESH,
    PATCH_OP_REMOVE,
    PATCH_OP_UPSERT,
    PATCH_VALUE_BUDGET_BYTES,
    PERSONA_INSTANCE_ENTITY,
    SCOPE_ENTITY,
    SCOPE_PATCH_FIELDS,
    SCOPE_PATCH_ID,
    STATE_PATCHED_EVENT_TYPE,
    _CORRELATION_ID_RE,
    _PERSONA_INSTANCE_STORE_TO_WIRE,
    _UNRESOLVED,
)
from agent_runtime.state_patches.payload import (  # noqa: F401 — the package's export floor
    _assemble,
    _is_oversize_marker,
    _oversize_marker,
    build_state_patch,
    normalize_correlation_id,
    office_actor_patch_id,
    office_patch_scope,
)
from agent_runtime.state_patches.emit import (  # noqa: F401 — the package's export floor
    _root_config_fault,
    delta_patches_enabled,
    emit_scope_patch,
    emit_state_patch,
)
from agent_runtime.state_patches.persona_instance import (  # noqa: F401 — the package's export floor
    _persona_instance_wire_row,
    _resolve_persona_for,
    emit_persona_instance_create,
    emit_persona_instance_patch,
    emit_persona_instance_remove,
    project_persona_instance_full_wire_row,
    project_persona_instance_wire_fields,
)
from agent_runtime.state_patches.office import (  # noqa: F401 — the package's export floor
    _office_actor_unpublished,
    emit_office_actor_patch,
    emit_office_actor_refresh,
    emit_office_actor_remove,
    emit_office_conflict_resolved_patch,
    emit_office_surface_patch,
    emit_office_surface_refresh,
    project_office_actor_wire_row,
)

__layer__ = "stores"
