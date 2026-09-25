"""The patch lane's vocabulary: ops, entities, the size budget, the store→wire
field table and the correlation-id grammar (a vocabulary/table module — floor-exempt).

The entity words are plain module constants and are never enum-ized: they are
spelled fork-wide (``patch_coverage``, ``serve_office_subscriptions``) and by the
launcher's ``_entitySection`` table.
"""

from __future__ import annotations

import re

from ..events import EVENT_PAYLOAD_LIMIT_BYTES

__layer__ = "models"


#: Sentinel for "this config object carried no ``delta_patches`` at all", which
#: must not collapse into the same answer as an operator's explicit ``False``.
_UNRESOLVED = object()

STATE_PATCHED_EVENT_TYPE = "state.patched"

#: Wire ops (plan §S7-A). ``upsert`` carries projected wire fields to merge;
#: ``remove`` deletes the keyed row; ``refresh`` is the accounted oversize/too-big
#: degrade → the launcher re-fetches that actor from a checkpoint.
PATCH_OP_UPSERT = "upsert"
PATCH_OP_REMOVE = "remove"
PATCH_OP_REFRESH = "refresh"

#: Ops the launcher can fold in place (a covered batch may contain only these).
#: ``refresh`` is NOT foldable — it forces a full core / checkpoint refetch.
FOLDABLE_PATCH_OPS: frozenset[str] = frozenset({PATCH_OP_UPSERT, PATCH_OP_REMOVE})

#: The persona-instance entity class, hoisted beside :data:`OFFICE_ACTOR_ENTITY`
#: so the emitters, the coverage gate and the launcher's ``_entitySection`` table
#: all name it from one place. It was three string literals until D3 gave the
#: entity a THIRD reader (the create gate in ``patch_coverage``), which is the
#: point at which a literal starts drifting silently.
PERSONA_INSTANCE_ENTITY = "persona_instance"

#: The ACTIVE-SCOPE entity (WS1, instant-workspace-switching plan §1.1) — the
#: runtime's two pointers, ``active_workspace_id`` and ``active_realm_id``, as a
#: foldable row.
#:
#: It is the only entity here that is not a keyed table row: the core carries the
#: pointers as two TOP-LEVEL scalars (``snapshot.py``'s ``active_workspace_id`` /
#: ``active_realm_id``), and every per-row ``active`` flag the launcher renders is
#: DERIVED from them at parse time, not sent. So the fold's job is to write the
#: two scalars and let the client re-run its own derivation — one derivation, two
#: callers, which is why a patch and a core cannot disagree about what ``active``
#: means.
#:
#: The row therefore has exactly one instance, and :data:`SCOPE_PATCH_ID` names
#: it. A singleton id is not decoration: the wire shape is
#: ``{entity, id, op, changed}`` and a fold keyed on ``id`` needs a stable one, or
#: two switches in one batch would look like two different rows.
SCOPE_ENTITY = "scope"

#: The singleton id of the :data:`SCOPE_ENTITY` row. ``runtime`` rather than a
#: workspace id: the row IS the runtime's pointer pair, and keying it by the value
#: it carries would make every switch look like a create of a new row.
SCOPE_PATCH_ID = "runtime"

#: Exactly the keys a ``scope`` patch carries — both pointers, ALWAYS, even when
#: only one of them moved.
#:
#: Why both and not just the one that changed: a realm activate can move the
#: workspace pointer too, so two half-patches would be two chances for a client to
#: hold a pair that never existed on the server. The payload is two scalars; there
#: is no size argument for splitting it, and the entity exists precisely because
#: the pair is ONE fact.
SCOPE_PATCH_FIELDS: tuple[str, ...] = ("active_workspace_id", "active_realm_id")

# Headroom reserved for the ``{entity, id, op, changed:{...}}`` scaffold plus the
# field keys, so a patch assembled from within-budget values still clears the
# hard 4096-byte payload cap. A single field value that serializes larger than
# this per-value budget is replaced by an accounted oversize marker.
PATCH_ENVELOPE_HEADROOM_BYTES = 512
PATCH_VALUE_BUDGET_BYTES = EVENT_PAYLOAD_LIMIT_BYTES - PATCH_ENVELOPE_HEADROOM_BYTES

#: Per persona-instance STORE field → the WIRE fields it projects to. A steer or
#: profile mutation names the store attributes it wrote; this maps each to the
#: projected wire fields (itself + every derived dependent) so the ``upsert``
#: carries the recomputed derived values, not just the raw field. Kept beside the
#: producer because it MUST track ``persona_instance_summary`` — the projection it
#: selects from — and the launcher folds whatever wire fields arrive (no allowlist).
_PERSONA_INSTANCE_STORE_TO_WIRE: dict[str, tuple[str, ...]] = {
    "steered_by": ("steered_by",),
    "spawned_by": ("spawned_by",),
    "goal_id": ("goal_id",),
    "mode": ("mode", "lifecycle_mode"),
    # S70 (contract 54) dropped the ``attached_task_id`` alias from the full
    # snapshot row; it leaves the patch lane in the same wave. A patch that kept
    # projecting it would ADD a key the full rebuild no longer has — the launcher
    # folds whatever wire fields arrive with no allowlist, so the two lanes would
    # disagree about the row's shape after the first incremental update.
    "current_task_id": ("current_task_id",),
    "display_name": ("display_name", "agent_profile_display_name"),
    "current_chat_goal": ("current_chat_goal",),
    "skill_overrides": ("skill_overrides", "skills"),
    "model": ("model", "effective_model", "model_is_override", "reasoning_supported"),
    "provider": ("provider", "effective_provider", "model_is_override"),
    "api_mode": ("api_mode",),
    "reasoning_effort": ("reasoning_effort", "model_is_override", "reasoning_supported"),
    # ── the ``open_chat`` half (office fold-promotion plan §V2, 2026-08-16) ──
    # ``persona_instance.chat_opened`` was covered with NO paired producer: the
    # bind writes real wire-visible state and emitted no ``state.patched`` at
    # all, so covering the event without these rows would silently drop every
    # field below from a connected client for the rest of its session. Each maps
    # exactly as ``persona_instance_summary`` derives it (the golden in
    # ``test_state_patches.py`` is the drift fence).
    "workspace_id": ("workspace_id",),
    "realm_id": ("realm_id",),
    # One store field, three wire names: the summary projects ``profile_id`` (or
    # the visibility persona's ``hermes_profile``) into all three.
    "profile_id": ("profile_id", "backing_profile", "source_profile_id"),
    # ``default_chat_session_id`` is the SOLE authority; ``chat_session_id`` and
    # ``session_id`` are its read-compatible mirrors on the wire row. The store's
    # own ``session_id`` mirror maps to the same trio, so whichever field name a
    # chokepoint names in its diff, the client folds all three consistently — a
    # patch that moved one and not the others would leave a v1 consumer reading a
    # session the row no longer points at.
    #
    # STATED AFTER MUTATION, because the pair is deliberately redundant and a
    # reader should not mistake that for coverage: ``open_chat`` always writes
    # BOTH store fields from the same value, so collapsing EITHER entry to its
    # own name alone stays green — the sibling entry still carries the trio.
    # Neither is dead; each is the one that answers when the other's store field
    # did not move, and a future chokepoint that writes only one is exactly the
    # case this shape exists for.
    "default_chat_session_id": ("default_chat_session_id", "chat_session_id", "session_id"),
    "session_id": ("default_chat_session_id", "chat_session_id", "session_id"),
    # Always diffable, and that is load-bearing rather than cosmetic: a bind that
    # moved only ``chat_head_home`` (which has no wire field) would otherwise
    # project an EMPTY ``changed`` → no patch → a covered ``chat_opened`` event
    # riding alone in an otherwise-coverable batch, i.e. a promoted frame whose
    # patches list omits the row that moved.
    "updated_at": ("updated_at",),
}


#: The end-to-end correlation key (Plan D / EG-2.3). ONE name, reused from the
#: slot ``stream._delta_entity`` already surfaces — so a producer that places it
#: into an event payload rides BOTH frame kinds with zero wire changes: the delta
#: lane lifts it to ``entity.correlation_id`` (``stream.py:319``) and the patch
#: lane spreads the whole payload into the row (``stream.py:436``).
CORRELATION_ID_KEY = "correlation_id"

#: Boundary cap, mirroring the idempotency-key cap discipline
#: (``persona_chat_mints``). A correlation id is a GENERATED token, never
#: operator text, so 64 characters is generous rather than tight.
CORRELATION_ID_MAX_LEN = 64

#: The token charset. Deliberately narrow — the id is minted by a client
#: (`g-<lane>-<micros>-<rand4>`), so anything outside this is either a bug or an
#: attempt to smuggle free text through a diagnostic field. Refused at the RPC
#: boundary and dropped here; never sanitized into a different token, because a
#: repaired id would print a value neither side used.
_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]+$")


OFFICE_ACTOR_ENTITY = "office_actor"


OFFICE_SURFACE_ENTITY = "office_surface"

#: The office row's CONFLICT LEDGER, as an entity of its own (w12/l3, 2026-09-04).
#:
#: The office row carries two key ledgers the actor rows cannot express:
#: ``archived_actor_keys``, which the §V1 audit showed a client can DERIVE from
#: the ``office_actor`` ``remove`` it already folds, and ``conflict_actor_keys``,
#: which it cannot — those keys come from sidecar FILES under
#: ``office/<ws>/conflicts/`` (``OfficeStore.scan_conflicts`` →
#: ``snapshot.office_summary_row``), and no actor write creates or archives one.
#: ``resolve_conflict`` archives a sidecar on EVERY arm, ``take="local"``
#: included, and that arm writes no actor row at all.
#:
#: That is why ``office.actor.conflict_resolved`` sat on ``patch_coverage``'s
#: must-stay-absent list: a covered batch would fold the resolved desk and leave
#: the sync strip's conflict pill lit for the rest of the session — a conflict
#: rendered on the row whose conflict the gesture just resolved.
#:
#: **Why a new entity rather than a widened office row.** The alternative the
#: queue row named was to let some patch move ``conflict_actor_keys`` on the
#: office row itself, behind a capability token on the
#: :data:`~agent_runtime.patch_coverage.OFFICE_SURFACE_FOLD_CAPABILITY` pattern.
#: Rejected: the launcher's ``_officeSurfaceFields`` doc comment names the
#: office-row keys no patch may move, and widening that set would put a SECOND
#: writer on the row :data:`OFFICE_SURFACE_PATCH_FIELDS` exists to keep to one —
#: two producers for one row, which is the shape this lane keeps retiring.
#:
#: **Why no capability string of its own.** The WS1 ``scope`` argument, verbatim:
#: this is a brand-new entity with exactly ONE op, so "can you fold the paired
#: row" and "may the paired event free-ride" are the SAME question, and the
#: entity name already answers it. A separate token could only ever agree with
#: the entity declaration — a second thing to get wrong for no compatibility
#: gained. So it stands as its own token in
#: :data:`~agent_runtime.patch_coverage.TOKEN_GATED_DOMAIN_EVENT_TYPES`, beside
#: ``workspace.activated`` and ``realm.activated``.
OFFICE_CONFLICT_ENTITY = "office_conflict"


#: EXACTLY the office-row fields ``update_surface`` moves — the whole content of
#: an ``office_surface`` patch, and the client's merge allowlist.
#:
#: Named here rather than written inline so the producer and the derivability
#: argument in :func:`emit_office_surface_patch` cannot drift apart, and so a
#: future field addition is a visible edit to a constant rather than a quiet
#: extra key in a dict literal. The launcher mirrors this set and RESYNCS on
#: anything outside it, which is what makes widening it a cross-stack change
#: needing its own capability token.
OFFICE_SURFACE_PATCH_FIELDS: tuple[str, ...] = ("folders", "revision", "updated_at")
