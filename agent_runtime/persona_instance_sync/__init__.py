"""Portable persona-INSTANCE projection for realm sync — the record split.

A realm pull already delivers the desk (``office_sync``), the persona definition
(``persona_config_sync``), the profile home and its files
(``profile_artifact_sync``) and the skills the persona names. It does not
deliver the **agent**: ``grep persona_instance agent_runtime/realm_sync.py``
returned nothing before this module existed, so a pulled placement landed on a
receiving machine with no runtime instance behind it and the launcher badged the
desk "Not linked here — this machine has no runtime instance for it".

The operator's ruling (2026-08-31, plan
``docs/mission_control/archive/instance-replication.md`` §0):

    Workspaces are SHARED live objects across realm members. Syncing one must
    bring working agents. A pulled desk whose instance is absent locally should
    mint/recreate the instance here — identity and definition travel; runtime
    state (sessions, worktrees, credentials, machine roots) is born fresh
    locally and never travels.

That sentence is a SPLIT of one 32-field record, and a category ("runtime
state") is exactly the kind of shorthand that lets one field drift to the wrong
side of a door. So the split is spelled per FIELD, three disjoint sets whose
union is every field of :class:`~agent_runtime.models.PersonaInstance`:

* :data:`PERSONA_INSTANCE_ALLOWED_KEYS` — 14 fields of realm-wide identity and
  authored definition. These and only these leave the machine.
* :data:`PERSONA_INSTANCE_DERIVED_KEYS` — 6 fields the MINT re-derives locally
  (this box's store root, the pulled definition's role, the profile the pull's
  own artifact lane materialized, a fresh idle state, a fresh durable chat root,
  now()).
* :data:`PERSONA_INSTANCE_LOCAL_ONLY_KEYS` — 12 fields that are neither carried
  nor re-derived: live execution bindings, writer-less telemetry, the
  conversation-adjacent steer text, the structural version.

:data:`PERSONA_INSTANCE_NEVER_TRAVELS_KEYS` is the union of the last two (18),
because "does this leave the machine" and "is this re-derived on arrival" are
two different questions about the same field and both have to be answerable.

``tests/agent_runtime/test_persona_instance_sync.py`` asserts the partition is
TOTAL over ``dataclasses.fields(PersonaInstance)``. A field added tomorrow
cannot compile green without somebody classifying it here — which is the whole
point of this stage, and the one guard that keeps the split from rotting the way
an English category would.

Everything in this module is pure with respect to its inputs (records are
injectable, nothing is read from disk, no git) so the allowlist, the projection,
the hash and the admission grammar are unit-testable without a store.

Where the projection is PUBLISHED and how it is merged on pull live in
``realm_sync`` (the publish scan) and ``persona_instance_pull`` semantics inside
``realm_sync.apply_persona_instance_pull`` — this module owns only the contract.

The package map (rule 16), lowest layer first — no module imports one above it
(W0-G6):

==========  ======  ===========================================================
module      layer   owns
==========  ======  ===========================================================
contract    models  the three key sets (+ NEVER_TRAVELS), ``cleared_travel_value``,
                    the projection document constants, the refusal codes,
                    ``PersonaInstancePullSummary`` (the typed pull accounting)
projection  policy  publish: ``PersonaInstanceProjection``, the def hash,
                    ``_wire_value``, ``project_persona_instance(s)``; pull
                    admission: ``instance_relative_path``,
                    ``valid_persona_instance_id``, ``refuse_persona_instance``,
                    ``read_projection_document``
sidecars    stores  the never-synced files — the baseline, the dropped-steering
                    ledger, the conflict parking,
                    ``update_persona_instance_baseline_after_publish`` — and
                    ``read_remote_persona_instances``
pull        stores  ``apply_persona_instance_pull``, the mint door, with its
                    per-row helpers
==========  ======  ===========================================================

Entry points: the pull (``realm_sync/pull.py``) → ``pull`` → ``sidecars`` and
``projection``; the publish (``realm_sync/persona_artifacts.py``) →
``projection.project_persona_instances`` → ``contract``; the baseline update
after publish (``realm_sync/publish.py``) → ``sidecars`` → ``projection``; the
drift/revert readers → ``sidecars`` / ``projection``.
"""

from __future__ import annotations

from agent_runtime.persona_instance_sync.contract import (  # noqa: F401 — the contract names
    PERSONA_INSTANCE_ALLOWED_KEYS,
    PERSONA_INSTANCE_DERIVED_KEYS,
    PERSONA_INSTANCE_LOCAL_ONLY_KEYS,
    PERSONA_INSTANCE_NEVER_TRAVELS_KEYS,
    PROJECTION_KIND,
    PROJECTION_RELATIVE_PATH,
    PROJECTION_SCHEMA_VERSION,
    REFUSAL_CANONICAL_CHANNEL,
    REFUSAL_INCOMPLETE,
    REFUSAL_INVALID_INSTANCE_ID,
    REFUSAL_STEERING_SHAPE,
    REFUSAL_UNEXPECTED_KEY,
    PersonaInstancePullSummary,
    cleared_travel_value,
)
from agent_runtime.persona_instance_sync.projection import (  # noqa: F401
    PersonaInstanceProjection,
    instance_relative_path,
    persona_instance_def_hash,
    project_persona_instance,
    project_persona_instances,
    read_projection_document,
    refuse_persona_instance,
    valid_persona_instance_id,
)
from agent_runtime.persona_instance_sync.sidecars import (  # noqa: F401
    instance_baseline_key,
    instance_conflict_path,
    read_dropped_steering_ledger,
    read_persona_instance_baseline,
    read_remote_persona_instances,
    update_persona_instance_baseline_after_publish,
    write_dropped_steering_ledger,
    write_persona_instance_baseline,
)
from agent_runtime.persona_instance_sync.pull import (  # noqa: F401 — the mint door + two test-pinned helpers
    _healable_dropped_parents,
    _remote_body_without_edges,
    apply_persona_instance_pull,
)

__layer__ = "stores"
