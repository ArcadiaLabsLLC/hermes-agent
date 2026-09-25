"""The doctor's runner: ``run_harness_doctor`` spends ``DOCTOR_SECTIONS``, THE table, and publishes the payload.

Map: ``agent_runtime/harness_doctor/__init__.py``.
"""

from __future__ import annotations

from typing import Any, Callable

from hermes_time import now

from ..events import EventLog
from ..snapshot.build import build_snapshot
from .census import _placement_census_report
from .model import (
    DEFAULT_WORKTREE_MIN_AGE_SECONDS,
    HEALTH_DEFECT,
    HEALTH_UNKNOWN,
    DoctorSection,
    _DoctorProbeContext,
)
from .probes import (
    _event_log_report,
    _model_authority_report,
    _persona_binding_report,
    _root_config_misplacement_report,
    _snapshot_null_id_report,
    _worktree_report,
)

__layer__ = "lanes"


def _payload_at(payload: dict[str, Any], path: str) -> Any:
    head, _, tail = path.partition(".")
    value = payload.get(head)
    if not tail:
        return value
    return value.get(tail) if isinstance(value, dict) else None


def _publish_at(payload: dict[str, Any], path: str, value: Any) -> None:
    head, _, tail = path.partition(".")
    if not tail:
        payload[head] = value
        return
    nested = payload.setdefault(head, {})
    if not isinstance(nested, dict):  # pragma: no cover - the table names dicts
        raise TypeError(f"cannot publish {path}: {head} is not a mapping")
    nested[tail] = value


def doctor_detail_sources(report: dict[str, Any]) -> dict[str, Any]:
    """Where each section keeps its own error text, keyed by section name.

    The CLI's fourth roster, derived rather than re-typed: a section added to
    the table renders its detail line the day it is added, and a section that
    keeps its error somewhere unusual says so once, in the table.
    """

    return {
        section.name: _payload_at(report, section.detail_source)
        for section in DOCTOR_SECTIONS
    }


def run_harness_doctor(
    *,
    fix: bool = False,
    dry_run: bool = False,
    worktree_min_age_seconds: int = DEFAULT_WORKTREE_MIN_AGE_SECONDS,
    include_worktrees: bool = True,
    event_log: EventLog | None = None,
    snapshot_builder: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Report surviving chat-runtime health without reviving mission records.

    Checks: orphan worktrees, snapshot null-id rows, event-log health, model
    authority, persona/profile binding, root-only config misplacement, and the
    roster/office placement census. The mission-era threshold/store parameters
    and the event-compaction switch were removed with the mission lane (doc 16);
    the CLI stopped passing them in 126976088.

    **The verdict spans every section.** ``ok`` was a hardcoded ``True`` on every
    path and ``needs_fix`` was derived from two of the five sections, so a report
    documenting a broken event log, an unreadable model-authority config, or
    diverged persona bindings still announced ``ok: true, needs_fix: false``.
    That is the worst shape in this class: the doctor is the TRIAGE tool, so a
    false all-clear here terminates the investigation that would have found the
    real defect. Both flags are now derived from ``summary.section_health``:

    * ``needs_fix`` — some section observed an actionable defect.
    * ``ok`` — every section was examined AND none observed a defect. A section
      whose probe raised reports ``health: unknown`` with its error, which
      clears ``ok`` without claiming a defect it never saw.

    ``notice`` sections (stale/duplicate model pins) are informational by
    design and move neither flag.

    **Every roster here is derived from :data:`DOCTOR_SECTIONS`.** Which
    sections exist, what each contributes to ``finding_counts``, and where each
    report lands in the payload are declared once in that table; this function
    only spends it.
    """

    ref = now()
    context = _DoctorProbeContext(
        fix=bool(fix),
        dry_run=bool(dry_run),
        worktree_min_age_seconds=max(0, int(worktree_min_age_seconds or 0)),
        include_worktrees=bool(include_worktrees),
        event_log=event_log or EventLog(),
        snapshot_builder=snapshot_builder or build_snapshot,
    )

    reports = {section.name: section.probe(context) for section in DOCTOR_SECTIONS}
    section_health = {
        section.name: reports[section.name].get("health", HEALTH_UNKNOWN)
        for section in DOCTOR_SECTIONS
    }
    # A count is an OBSERVATION. When the probe for a class did not run, the
    # honest count is ``None`` ("not observed"), never ``0`` ("observed none") —
    # a zero here is what sends an investigator hunting a defect class the
    # doctor never actually looked at. The rule is applied HERE, once, for every
    # count in the table: it used to be re-typed per entry, which is a rule
    # copied six times and free to be forgotten on the seventh.
    finding_counts: dict[str, Any] = {}
    for section in DOCTOR_SECTIONS:
        unexamined_section = section_health[section.name] == HEALTH_UNKNOWN
        for count_name, list_key in section.counts:
            finding_counts[count_name] = (
                None
                if unexamined_section
                else len(reports[section.name].get(list_key) or [])
            )
    defective = sorted(k for k, v in section_health.items() if v == HEALTH_DEFECT)
    unexamined = sorted(k for k, v in section_health.items() if v == HEALTH_UNKNOWN)
    worktrees = reports["orphan_worktrees"]
    repairs = {
        "worktrees_reaped": (
            [item.get("worktree") for item in (worktrees.get("reaped") or []) if item.get("worktree")]
            if fix and not dry_run
            else []
        ),
        "dry_run": bool(dry_run),
    }
    payload: dict[str, Any] = {
        "schema_version": 10,
        "generated_at": ref,
        "ok": not defective and not unexamined,
        "mode": {"fix": bool(fix), "dry_run": bool(dry_run)},
        "thresholds": {
            "worktree_min_age_seconds": int(worktree_min_age_seconds),
            "include_worktrees": bool(include_worktrees),
        },
        "summary": {
            "finding_counts": finding_counts,
            "section_health": section_health,
            "defective_sections": defective,
            "unexamined_sections": unexamined,
            "needs_fix": bool(defective),
            "repairs_applied": bool(fix and not dry_run),
            "preserved_evidence": True,
            "product_repos_modified": False,
        },
        # Seeded empty and filled from the table below, so the sections that
        # publish here need no second listing.
        "findings": {},
    }
    for section in DOCTOR_SECTIONS:
        report = reports[section.name]
        for destination, key in section.publish:
            _publish_at(payload, destination, report if key is None else report.get(key))
    payload["repairs"] = repairs
    return payload


# ── THE table ─────────────────────────────────────────────────────────────────
#
# Adding a section is one row here and nothing else: ``summary.section_health``,
# ``summary.finding_counts``, the payload placement, and the CLI's per-section
# detail line are all derived from it (see :class:`DoctorSection`). Order is the
# operator-facing order of ``finding_counts``, so keep a new section where its
# findings read naturally rather than appending by habit.
DOCTOR_SECTIONS: tuple[DoctorSection, ...] = (
    DoctorSection(
        name="orphan_worktrees",
        probe=_worktree_report,
        publish=(("findings.orphan_worktrees", None),),
        detail_source="findings.orphan_worktrees",
        counts=(("orphan_worktrees", "reaped"),),
    ),
    DoctorSection(
        name="snapshot_null_id_rows",
        probe=_snapshot_null_id_report,
        publish=(
            ("findings.snapshot_null_id_rows", "rows"),
            ("findings.snapshot_build", "build"),
        ),
        # A bare list of rows carries no error text; the build outcome does.
        detail_source="findings.snapshot_build",
        counts=(("snapshot_null_id_rows", "rows"),),
    ),
    DoctorSection(
        name="event_log",
        probe=_event_log_report,
        publish=(("findings.event_log", None),),
        detail_source="findings.event_log",
    ),
    # ``model_authority`` and ``persona_binding`` publish at the payload ROOT
    # rather than under ``findings``. That predates the derived verdict and is
    # kept because both are read by name off the JSON by operator tooling; the
    # table is where the exception is stated instead of being a thing you had to
    # already know.
    DoctorSection(
        name="model_authority",
        probe=_model_authority_report,
        publish=(("model_authority", None),),
        detail_source="model_authority",
    ),
    DoctorSection(
        name="persona_binding",
        probe=_persona_binding_report,
        publish=(("persona_binding", None),),
        detail_source="persona_binding",
    ),
    DoctorSection(
        name="root_config_misplacement",
        probe=_root_config_misplacement_report,
        publish=(("findings.root_config_misplacement", None),),
        detail_source="findings.root_config_misplacement",
        counts=(("misplaced_root_only_keys", "misplaced"),),
    ),
    # The census contributes THREE counts because they are three different
    # verdicts: an orphan actor is a defect, an unplaced row is a legal state of
    # a supported door, and a duplicate placement is two live actors claiming
    # one item id. Folding them into one number would make the doctor's headline
    # count climb every time the roster-only recovery door is used correctly.
    # A fourth, ``desk_litter``, left on 2026-09-18 with the pairing it counted.
    DoctorSection(
        name="placement_census",
        probe=_placement_census_report,
        publish=(("findings.placement_census", None),),
        detail_source="findings.placement_census",
        counts=(
            ("orphan_actors", "orphan_actors"),
            ("unplaced_rows", "unplaced_rows"),
            ("duplicate_placements", "duplicate_placements"),
        ),
    ),
)
