"""The persona-instance sync contract: the three key sets, the projection constants, the refusal codes, the pull summary.

Map: ``agent_runtime/persona_instance_sync/__init__.py``.
"""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from typing import Any

from ..models import PersonaInstance

__layer__ = "models"


# --- projection contract ---------------------------------------------------

PROJECTION_KIND = "realm_persona_instances"
PROJECTION_SCHEMA_VERSION = 1

#: Published relative path of the synthesized projection inside a realm subtree.
#:
#: Unknown to every older hermes: ``_destination_for_sync_path`` returns ``None``
#: for it through the final fallthrough, so an older member SKIPS the artifact
#: rather than writing it somewhere wrong. Degrading to "no instance
#: replication" is the whole version-skew story on the pull side, and it is what
#: the launcher's L1/L2 stages key their badge demotion on.
PROJECTION_RELATIVE_PATH = "store/persona_instances.yaml"

#: The ONLY persona-instance fields that may leave this machine (plan §1.1).
#:
#: Opt-in, never opt-out: a key outside this set is DROPPED with accounting on
#: publish and REFUSED at the pull door (``unexpected_key``). Every entry earns
#: its place, and the four that look like runtime state but are not:
#:
#: - ``mode`` is the instance's LANE (``configured`` / ``free_floating``), read
#:   by ``operator_channels`` / ``persona_chat_history`` /
#:   ``persona_instance_identity``. Definitional, not live.
#: - ``spawned_by`` is a PROVENANCE scalar, not a steering edge —
#:   ``PersonaInstance.__post_init__`` already guards it from being read as one.
#: - ``realm_id`` / ``workspace_id`` are scope-provenance and are realm-wide by
#:   construction. The launcher's scope policy REFUSES on their absence
#:   (``realmOnly`` / ``foreignWorkspace``), so a mint without them would swap
#:   one badge for another rather than link the desk.
#: - ``model_override_issued_at`` is a supersession CLOCK and travels WITH the
#:   four override fields it orders, or a stale local write silently wins on the
#:   receiver (``StaleModelOverrideWrite``).
PERSONA_INSTANCE_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "api_mode",
        "display_name",
        "id",
        "mode",
        "model",
        "model_override_issued_at",
        "persona_id",
        "provider",
        "realm_id",
        "reasoning_effort",
        "skill_overrides",
        "spawned_by",
        "steered_by",
        "workspace_id",
    }
)

#: Never travels, and RE-DERIVED locally by the mint (plan §1.3).
#:
#: Distinct from :data:`PERSONA_INSTANCE_LOCAL_ONLY_KEYS` because these six are
#: not merely withheld — a replica that left them empty would not be a working
#: agent. ``role`` and ``profile_id`` are derived rather than carried on purpose:
#: travelling either would let a stale copy shadow the persona definition that
#: arrived in the SAME pull.
PERSONA_INSTANCE_DERIVED_KEYS: frozenset[str] = frozenset(
    {
        "default_chat_session_id",
        "profile_id",
        "role",
        "runtime_root",
        "state",
        "updated_at",
    }
)

#: Never travels and never re-derived: born at the dataclass default (plan §1.2).
#:
#: Live execution bindings (``active_run_id`` and its four siblings) are the
#: sharp ones — ``_has_live_binding`` reads them to refuse retiring a working
#: agent, so importing a peer's binding would make a replica look busy with a
#: run this machine has never heard of. ``current_chat_goal`` is here by the
#: 2026-08-31 ruling (`[AUDIT]` in the plan): it is conversation-adjacent like
#: ``chat_head_home``, and a wrong "travels" is a clobber where a wrong "never"
#: is only an absence.
PERSONA_INSTANCE_LOCAL_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "active_run_id",
        "chat_head_home",
        "current_assignment_id",
        "current_chat_goal",
        "current_task_id",
        "goal_id",
        "last_heartbeat_at",
        "returned_to",
        "schema_version",
        "session_id",
        "skill_manifest_hash",
        "token_budget_used",
    }
)

#: Everything that does not travel — the union of the two sets above.
PERSONA_INSTANCE_NEVER_TRAVELS_KEYS: frozenset[str] = (
    PERSONA_INSTANCE_DERIVED_KEYS | PERSONA_INSTANCE_LOCAL_ONLY_KEYS
)

#: The value an ADOPT writes into a travelling field the remote body omits.
#:
#: Adoption takes the remote's travelling SURFACE wholesale — a field the
#: publisher cleared must clear here too, or a locally-stale override would
#: outlive the write that removed it upstream. Defaults come from the dataclass
#: itself so this table cannot disagree with the record; ``display_name`` is the
#: one travelling field with no default (it is a bare ``str``), and its
#: structural empty is ``""``.
_TRAVEL_CLEARED_WITHOUT_DEFAULT: dict[str, Any] = {"display_name": ""}


def _dataclass_defaults() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in fields(PersonaInstance):
        if item.default is not MISSING:
            out[item.name] = item.default
        elif item.default_factory is not MISSING:  # type: ignore[misc]
            out[item.name] = item.default_factory()  # type: ignore[misc]
    return out


def cleared_travel_value(name: str) -> Any:
    """What an adopt writes for a travelling field the remote body omits.

    ``id`` and ``persona_id`` never reach here — an admitted body must carry
    both (:func:`refuse_persona_instance`), because they are the merge key and
    the definition pointer, not overrides that can be cleared.
    """

    defaults = _dataclass_defaults()
    if name in defaults:
        value = defaults[name]
        return list(value) if isinstance(value, list) else value
    return _TRAVEL_CLEARED_WITHOUT_DEFAULT[name]


# NO import-time assertion of the partition, deliberately. The totality gate is
# ``tests/agent_runtime/test_persona_instance_sync.py::
# test_every_persona_instance_field_is_classified``, and an assert here would
# pre-empt it: an unclassified field would surface as a COLLECTION error on
# every suite that imports this module rather than as one named failure saying
# which field nobody classified. The plan calls that test "the point of this
# stage"; a guard that steals its red makes the stage's own signal unreadable.


# --- refusal codes (plan §4) -------------------------------------------------

#: The id is not instance-shaped, or would be MANGLED into a different filename
#: by ``paths.safe_path_token`` — which is the same thing as the merge unit
#: being written under a key that is not the key the realm agreed on.
REFUSAL_INVALID_INSTANCE_ID = "invalid_instance_id"
#: A key outside :data:`PERSONA_INSTANCE_ALLOWED_KEYS`. The session/run family
#: (``default_chat_session_id``, ``session_id``, ``chat_head_home``,
#: ``active_run_id``, ``current_task_id``, ``current_assignment_id``,
#: ``goal_id``) lands here.
REFUSAL_UNEXPECTED_KEY = "unexpected_key"
#: A peer published a CANONICAL channel row. Canonical rows are derived locally
#: on every machine from a persona id that already travels, so a peer writing
#: one is either an older id scheme or an attack. Replication is scoped to
#: placement-backed rows (plan §2), which is what keeps the queued
#: global-singleton redesign un-blocking.
REFUSAL_CANONICAL_CHANNEL = "canonical_channel_not_replicable"
#: A ``steered_by`` entry that is not instance-shaped — the same guard
#: ``__post_init__`` spends to keep a principal from rendering as a parent edge.
REFUSAL_STEERING_SHAPE = "steering_parent_not_instance_shaped"
#: The body has no ``id``/``persona_id``, so there is nothing to key or build
#: from. Refused rather than accounted: unlike a persona definition, an instance
#: row with no persona pointer cannot be adopted at all.
REFUSAL_INCOMPLETE = "incomplete_instance"


# --- pull: the mint door (plan §3) -------------------------------------------


@dataclass(slots=True)
class PersonaInstancePullSummary:
    """Typed accounting for the persona-instance pull — the ONE contract seam
    between this repo and the launcher (plan §6), carried on a pull ack as
    ``result["persona_instance_sync"]``.

    Every outcome is a row of the §3.3 decision table, and nothing is silently
    written or silently skipped:

    - ``replicated`` — the desk arrived and the agent did not exist here. Minted
      through the store door, with the §1.3 fields derived locally.
    - ``adopted`` — the row was already here, unchanged since the last sync, and
      the realm moved its travelling surface forward. Only travelling fields are
      written; every §1.2 field is preserved by construction.
    - ``converged`` — local already equals remote (no write).
    - ``kept_local`` — this machine edited the row and the realm did not. Stays
      local and unpublished. The plan's table folds this into "not held"; it is
      named separately because the H4 drift lane reports exactly these rows.
    - ``held`` — BOTH sides moved. The local row is left untouched and the
      remote body is parked in a conflict sidecar. Divergent content is never
      clobbered.
    - ``upstream_absent`` — the realm's projection does not carry a row this
      baseline says it published. **NOT a delete** (plan §3.3, §5.2): absence is
      short-answer-shaped, and this subsystem has already paid for inferring
      deletion from a short answer. The baseline is KEPT so a repaired publish
      still converges.
    - ``refused`` — a row the admission door would not admit, or one whose local
      file will not decode. Per-entity isolation: the row is untouched, the
      refusal is named, the pull continues.
    - ``steering_dropped`` — phase-two edges naming a parent this machine does
      not have. Accounted, never silent, and re-accounted on every later pull
      for as long as the parent stays absent: a drop announced once and then
      silent reads as repaired.
    - ``steering_healed`` — edges an EARLIER pull dropped, re-applied here
      because the parent has since arrived and the local body was still exactly
      "remote minus the dropped edge". A row that healed is counted in
      ``adopted`` beside this, because a travelling field did move forward onto
      an existing row; a row whose local body diverged anywhere else is an
      operator re-steer and stays ``kept_local``, untouched.
    - ``retired`` / ``retire_held`` — §5.2's retire-follows-the-DESK arm, and
      the desks whose agent could not be archived (a live run binding above
      all). These are driven by the office lane's own ``remote_removed``
      archives, never by an instance's absence.

    ``source`` is ``None`` when the pulled subtree carries no instance
    projection at all — an older publisher. That is the version-skew fact the
    launcher's badge demotion keys on, and it is deliberately distinct from an
    EMPTY projection.
    """

    replicated: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    converged: list[str] = field(default_factory=list)
    kept_local: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    upstream_absent: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    steering_dropped: list[dict[str, str]] = field(default_factory=list)
    #: Edges a PREVIOUS pull dropped for an absent parent, re-applied now that
    #: the parent exists — ``{key, parent}``, the mirror of a
    #: ``steering_dropped`` row. Additive on the wire (2026-09-02) and the fact
    #: the launcher's ``AGENT LINKS DROPPED`` group needs before it can stop
    #: saying the edge "will not re-apply": it now does, on the pull after the
    #: parent arrives, and the row that healed says so by name.
    steering_healed: list[dict[str, str]] = field(default_factory=list)
    #: Replicas archived because their DESK left (plan §5.2). Never derived from
    #: an instance's absence — only from the office lane having ARCHIVED the
    #: actor for the same key in this same pull, which is authored intent that
    #: already propagated. Empty is the normal case.
    retired: list[str] = field(default_factory=list)
    #: Desks that left while their agent could NOT be archived — a live run
    #: binding above all (``instance_active``). Held, named, and re-decided on
    #: the next pull: a working agent is never archived out from under an
    #: operator, and the count says so rather than implying the retire happened.
    retire_held: list[dict[str, str]] = field(default_factory=list)
    #: The realm still publishes this agent, but its DESK is archived on this
    #: machine, so no replica is minted or revived. The office surface's
    #: ``archived_actor_keys`` ledger is the resurrection guard the office family
    #: already uses, and the actor key IS the instance id — so this lane asks the
    #: SAME ledger rather than growing a second one. Without it a retire-follows-
    #: the-desk in one pull would be undone by the very next pull, and a desk the
    #: operator deleted would keep coming back with an agent behind it.
    desk_archived: list[str] = field(default_factory=list)
    source: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.replicated or self.adopted or self.retired)

    def as_dict(self) -> dict[str, Any]:
        return {
            "replicated": sorted(set(self.replicated)),
            "adopted": sorted(set(self.adopted)),
            "converged": sorted(set(self.converged)),
            "kept_local": sorted(set(self.kept_local)),
            "held": sorted(set(self.held)),
            "upstream_absent": sorted(set(self.upstream_absent)),
            "refused": list(self.refused),
            "steering_dropped": list(self.steering_dropped),
            "steering_healed": list(self.steering_healed),
            "retired": sorted(set(self.retired)),
            "retire_held": list(self.retire_held),
            "desk_archived": sorted(set(self.desk_archived)),
            "source": self.source,
        }
