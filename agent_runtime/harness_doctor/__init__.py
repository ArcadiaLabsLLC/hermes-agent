"""``harness doctor`` — the chat runtime's health report (the package map, rule 16).

Entry points (what calls in):

* ``run_harness_doctor`` (``harness_parts/doctor_commands``) → ``run`` → the
  probe that answers a section (``probes`` or ``census``).
* ``doctor_detail_sources`` — the CLI printer's per-section detail line →
  ``run``.
* A test asking one section its question → ``probes`` / ``census`` directly
  (a probe takes a context or ``None``, which is why each stays a bare seam).

Modules, lowest layer first (no module imports one above it — W0-G6):

======  ======  ===============================================================
module  layer   owns
======  ======  ===============================================================
model   models  the ``HEALTH_*`` vocabulary, ``DEFAULT_WORKTREE_MIN_AGE_SECONDS``,
                the probe context, ``DoctorSection``, ``_error_text``
probes  lanes   the six one-question probes (worktrees, event log, persona
                binding, root-config misplacement, model authority, snapshot
                null ids)
census  lanes   the roster/office join: the orphan and duplicate classifiers,
                the per-workspace sweeps, ``_placement_census_report``
run     lanes   ``run_harness_doctor``, the payload publish helpers, and
                ``DOCTOR_SECTIONS`` — THE table (it names every probe, so it
                lives with the one module that imports them all)
======  ======  ===============================================================

Payload schema history
----------------------

``schema_version`` is stamped by ``run_harness_doctor``. This is a HISTORY of
the schema, not a description of the current one (it moved here from the
payload literal's comment, 2026-09-25):

    3: ``ok``/``needs_fix`` became derived, ``summary.section_health`` /
    ``defective_sections`` / ``unexamined_sections`` are new, a
    ``finding_counts`` value may now be ``None`` (class not observed), and
    ``findings.snapshot_build`` separates a snapshot CRASH from an
    observation of null-id rows.
    4: ``findings.root_config_misplacement`` is new — root-only keys an
    operator set in a PROFILE config, where the reader never looks. It is
    a DEFECT rather than a notice because the value is silently inert:
    the 2026-08-13 case left the S7-A patch producer dark for its whole
    life while ``harness status`` reported the flag as on.
    5: ``findings.placement_census`` is new — the roster/office join
    (plan D8), read-only, with ``summary.finding_counts`` gaining
    ``orphan_actors`` and ``unplaced_rows``.
    6: ``findings.placement_census.desk_litter`` is new (plan DL-H1) —
    the ITEM-level desk sweep the actor-level join is blind to, with
    ``summary.finding_counts`` gaining ``desk_litter``. No new section:
    the census's own health absorbs it, at ``notice``.
    (RETIRED at 10, below. Kept in this list because the list is a
    HISTORY of the schema, not a description of the current one.)
    7: ``findings.placement_census.duplicate_placements`` is new (H-H8) —
    item ids held by more than one live actor, with
    ``summary.finding_counts`` gaining ``duplicate_placements``. No new
    section again, and the census's health absorbs it at ``notice``
    EXCEPT for the ``same_instance`` reason, which is a defect.
    8: every ``findings.placement_census.orphan_actors`` row gains a
    ``reason`` (H-H4), one of the three ``ORPHAN_ACTOR_*`` tokens. No new
    section, no new count and no health change — the split the
    remediation string described in prose is now a field, and
    ``retire_incomplete`` is the standing detector for the "row archived,
    desk still live" half-state the retire ack alone used to witness.
    (7 and 8 were authored concurrently on two branches and BOTH claimed
    7; they are two independent schema-visible additions, so the merge
    numbered them in landing order rather than folding two contracts into
    one version an operator could not tell apart.)
    9: ``findings.root_config_misplacement`` gains ``remediation`` (the
    class's one cure, present even when the section is ``ok``) and
    ``scope`` (``profiles_examined`` / ``root_only_key_patterns`` — the
    denominator a misplacement COUNT has to be read against before two
    machines' numbers are compared). Additive only: no health change, no
    new section, no new count.
    10: ``findings.placement_census.desk_litter`` is REMOVED, and with it
    ``summary.finding_counts.desk_litter`` and the per-workspace key —
    the first REMOVAL this schema has made, which is why it moves the
    version rather than riding as an additive change. The census existed
    to pair a desk with the agent that "owned" it; the owner ruled on
    2026-09-18 that a desk is one generic furniture object every agent can
    use, addressed by its own synthetic id, so there is no pairing left to
    be broken and every one of the four ``DESK_LITTER_*`` reasons would
    have fired on every correctly-placed generic desk forever. A finding
    class that cannot be cleared is a finding class that stops being read.
    ``orphan_actors``, ``unplaced_rows`` and ``duplicate_placements`` are
    untouched — they are kind-agnostic and ask about ACTORS, not desks.
"""

from __future__ import annotations

from agent_runtime.harness_doctor.model import (  # noqa: F401 — the vocabulary
    DEFAULT_WORKTREE_MIN_AGE_SECONDS,
    HEALTH_DEFECT,
    HEALTH_NOTICE,
    HEALTH_OK,
    HEALTH_UNKNOWN,
    DoctorSection,
)
from agent_runtime.harness_doctor.probes import (  # noqa: F401 — bare seams tests call
    _event_log_report,
    _model_authority_report,
    _persona_binding_report,
    _root_config_misplacement_report,
    _snapshot_null_id_report,
    _worktree_report,
)
from agent_runtime.harness_doctor.census import (  # noqa: F401 — the census tokens + its test-pinned sweeps
    DUPLICATE_PLACEMENT_CROSS_INSTANCE,
    DUPLICATE_PLACEMENT_SAME_INSTANCE,
    DUPLICATE_PLACEMENT_UNBOUND_HOLDER,
    ORPHAN_ACTOR_INSTANCE_RETIRED,
    ORPHAN_ACTOR_INSTANCE_UNKNOWN,
    ORPHAN_ACTOR_REASONS,
    ORPHAN_ACTOR_RETIRE_INCOMPLETE,
    _census_duplicate_placements,
    _census_join_workspace,
    _census_live_actor_bindings,
    _duplicate_placement_reason,
    _orphan_actor_reason,
    _placement_census_report,
)
from agent_runtime.harness_doctor.run import (  # noqa: F401
    DOCTOR_SECTIONS,
    doctor_detail_sources,
    run_harness_doctor,
)

__layer__ = "lanes"
