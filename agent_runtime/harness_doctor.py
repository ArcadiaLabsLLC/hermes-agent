from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from hermes_time import now

from .delivery_directive import reap_orphan_worktrees
from .events import EventLog, event_log_health
from .snapshot import build_snapshot


DEFAULT_WORKTREE_MIN_AGE_SECONDS = 3600

# The health vocabulary every doctor section reports itself in. The verdict is
# DERIVED from these — no section may be examined without contributing one.
#
# ``unknown`` is the load-bearing member and follows the orphan-sweep precedent
# in ``cron/executions.py`` (``status='unknown'`` + "whether side effects ran is
# unknown"): a section whose probe RAISED did not observe health, so it reports
# what it knows — nothing — instead of a plausible default. A defaulted ``ok``
# here is worse than a missing check, because the doctor is the tool an operator
# runs to decide whether to keep investigating.
HEALTH_OK = "ok"
HEALTH_NOTICE = "notice"  # examined, informational only; never moves the verdict
HEALTH_DEFECT = "defect"  # examined, actionable defect observed
HEALTH_UNKNOWN = "unknown"  # NOT examined — the probe failed


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:320]


# ── the section table: ONE declaration, four derived rosters ─────────────────
#
# A doctor section used to be added by editing four hand-maintained lists of one
# set — ``finding_counts``, ``section_health`` and ``findings`` here, plus
# ``detail_sources`` in the CLI printer — with only ``section_health``'s key set
# pinned by a test. A section added to three of the four was therefore counted
# and verdicted while rendering NO operator line, and nothing failed. That is
# the same shape the derived-verdict rework already fixed once by hand (``ok``
# and ``needs_fix`` were computed from two of five sections), which is why this
# one is fixed structurally instead: every roster below is DERIVED from
# :data:`DOCTOR_SECTIONS`, so a new section is one table row and a missing one
# is unspellable.
#
# The table lives at the BOTTOM of this module, where the probes it names are
# defined. Read it first anyway — it is the index to everything above it.


@dataclass(frozen=True)
class _DoctorProbeContext:
    """Every input a probe may read, so all probes share ONE signature.

    A uniform signature is what lets the table hold the probe: a roster of
    sections that could not also name how to run them would be a fifth list to
    keep in step with the other four.
    """

    fix: bool
    dry_run: bool
    worktree_min_age_seconds: int
    include_worktrees: bool
    event_log: EventLog
    snapshot_builder: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class DoctorSection:
    """One doctor section, declared once.

    * ``name`` — its key in ``summary.section_health``, and the name an
      operator sees on the CLI's per-section line.
    * ``probe`` — the callable that observes it. It must return a dict carrying
      a ``health`` from the vocabulary above; a section whose probe answers
      without one reads ``unknown``, never ``ok``. A probe that reads NOTHING
      from the context declares it optional (``_context=None``), which says so
      in the signature and keeps the probe callable as a bare seam — several
      suites unit-test one section by calling its probe directly, and making
      them build a context to hand a function that ignores it would be
      ceremony, not clarity.
    * ``publish`` — where its report lands in the payload, as
      ``(dotted destination, key inside the report)``. ``None`` publishes the
      whole report dict; a key publishes that member, which is how
      ``snapshot_null_id_rows`` (the row list) and ``snapshot_build`` (whether
      the frame built at all) stay two payload keys from one probe.
    * ``counts`` — the ``summary.finding_counts`` entries it contributes, as
      ``(count name, list key inside the report)``. A count is an OBSERVATION:
      an unexamined section's counts are ``None``, never ``0`` — see
      :func:`run_harness_doctor`.
    * ``detail_source`` — the dotted payload path whose ``error`` the CLI
      prints beside a non-ok section. Usually the section's own report; the
      exception is ``snapshot_null_id_rows``, a bare list whose build outcome
      lives one key over.
    """

    name: str
    probe: Callable[[_DoctorProbeContext], dict[str, Any]]
    publish: tuple[tuple[str, str | None], ...]
    detail_source: str
    counts: tuple[tuple[str, str], ...] = field(default=())


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
        # 3: ``ok``/``needs_fix`` became derived, ``summary.section_health`` /
        # ``defective_sections`` / ``unexamined_sections`` are new, a
        # ``finding_counts`` value may now be ``None`` (class not observed), and
        # ``findings.snapshot_build`` separates a snapshot CRASH from an
        # observation of null-id rows.
        # 4: ``findings.root_config_misplacement`` is new — root-only keys an
        # operator set in a PROFILE config, where the reader never looks. It is
        # a DEFECT rather than a notice because the value is silently inert:
        # the 2026-08-13 case left the S7-A patch producer dark for its whole
        # life while ``harness status`` reported the flag as on.
        # 5: ``findings.placement_census`` is new — the roster/office join
        # (plan D8), read-only, with ``summary.finding_counts`` gaining
        # ``orphan_actors`` and ``unplaced_rows``.
        # 6: ``findings.placement_census.desk_litter`` is new (plan DL-H1) —
        # the ITEM-level desk sweep the actor-level join is blind to, with
        # ``summary.finding_counts`` gaining ``desk_litter``. No new section:
        # the census's own health absorbs it, at ``notice``.
        # (RETIRED at 10, below. Kept in this list because the list is a
        # HISTORY of the schema, not a description of the current one.)
        # 7: ``findings.placement_census.duplicate_placements`` is new (H-H8) —
        # item ids held by more than one live actor, with
        # ``summary.finding_counts`` gaining ``duplicate_placements``. No new
        # section again, and the census's health absorbs it at ``notice``
        # EXCEPT for the ``same_instance`` reason, which is a defect.
        # 8: every ``findings.placement_census.orphan_actors`` row gains a
        # ``reason`` (H-H4), one of the three ``ORPHAN_ACTOR_*`` tokens. No new
        # section, no new count and no health change — the split the
        # remediation string described in prose is now a field, and
        # ``retire_incomplete`` is the standing detector for the "row archived,
        # desk still live" half-state the retire ack alone used to witness.
        # (7 and 8 were authored concurrently on two branches and BOTH claimed
        # 7; they are two independent schema-visible additions, so the merge
        # numbered them in landing order rather than folding two contracts into
        # one version an operator could not tell apart.)
        # 9: ``findings.root_config_misplacement`` gains ``remediation`` (the
        # class's one cure, present even when the section is ``ok``) and
        # ``scope`` (``profiles_examined`` / ``root_only_key_patterns`` — the
        # denominator a misplacement COUNT has to be read against before two
        # machines' numbers are compared). Additive only: no health change, no
        # new section, no new count.
        # 10: ``findings.placement_census.desk_litter`` is REMOVED, and with it
        # ``summary.finding_counts.desk_litter`` and the per-workspace key —
        # the first REMOVAL this schema has made, which is why it moves the
        # version rather than riding as an additive change. The census existed
        # to pair a desk with the agent that "owned" it; the owner ruled on
        # 2026-09-18 that a desk is one generic furniture object every agent can
        # use, addressed by its own synthetic id, so there is no pairing left to
        # be broken and every one of the four ``DESK_LITTER_*`` reasons would
        # have fired on every correctly-placed generic desk forever. A finding
        # class that cannot be cleared is a finding class that stops being read.
        # ``orphan_actors``, ``unplaced_rows`` and ``duplicate_placements`` are
        # untouched — they are kind-agnostic and ask about ACTORS, not desks.
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


def _worktree_report(context: _DoctorProbeContext) -> dict[str, Any]:
    """Orphan-worktree sweep, with a failed sweep reported as unexamined.

    The sweep shells out to git across every registered worktree, so it is I/O
    that can fail (a deleted checkout, a locked index, a git that is not on
    PATH). It ran unguarded, which meant a failure either crashed the whole
    doctor or — worse, once wrapped naively — would have read as "no orphans".

    ``include_worktrees=False`` is the caller's own choice not to scan, so it
    reports ``ok`` + ``skipped`` rather than ``unknown``: nothing failed to be
    observed, the observation was declined.
    """

    if not context.include_worktrees:
        return {
            "reaped": [],
            "kept": [],
            "dry_run": True,
            "skipped": "worktree_scan_disabled",
            "health": HEALTH_OK,
        }
    dry_run = not context.fix or context.dry_run
    try:
        report = dict(
            reap_orphan_worktrees(
                min_age_seconds=context.worktree_min_age_seconds,
                event_log=context.event_log,
                dry_run=dry_run,
            )
        )
    except Exception as exc:
        return {
            "health": HEALTH_UNKNOWN,
            "error": _error_text(exc),
            # NOT ``[]`` — the sweep enumerated nothing, it did not find nothing.
            "reaped": None,
            "kept": None,
            "dry_run": bool(dry_run),
        }
    report["health"] = HEALTH_DEFECT if (report.get("reaped") or []) else HEALTH_OK
    return report


def _event_log_report(_context: _DoctorProbeContext | None = None) -> dict[str, Any]:
    """Event-log health, which rode the payload but never moved the verdict.

    ``event_log_health`` stats the live slice and the rotation manifest, so on
    this runtime's platform it can raise under AV/share-violation contention.
    Unguarded, that crashed the doctor outright; the section now reports what it
    could not read.
    """

    try:
        health = dict(event_log_health())
    except Exception as exc:
        return {"health": HEALTH_UNKNOWN, "error": _error_text(exc)}
    health["health"] = HEALTH_OK if health.get("index_health") == "ok" else HEALTH_DEFECT
    return health


def _persona_binding_report(_context: _DoctorProbeContext | None = None) -> dict[str, Any]:
    try:
        from .persona_profile_binding import binding_index

        index = binding_index()
    except Exception as exc:
        return {
            "ok": False,
            "health": HEALTH_UNKNOWN,
            "error": _error_text(exc),
            "diverged": [],
        }
    diverged = [binding.as_row() for binding in index.values() if binding.diverged]
    return {
        "ok": True,
        # Divergence carries a remediation string precisely because it happens,
        # which makes it actionable — so it moves the verdict.
        "health": HEALTH_DEFECT if diverged else HEALTH_OK,
        "resolved_by": "store_wins",
        "agent_count": len(index),
        "diverged_count": len(diverged),
        "diverged": sorted(diverged, key=lambda row: row["persona_id"]),
        "remediation": "harness agent set-profile <persona_id> --profile <name> (moves the store) or edit config.yaml (moves the declaration)",
    }


def _root_config_misplacement_report(_context: _DoctorProbeContext | None = None) -> dict[str, Any]:
    """Root-only config keys an operator set in a PROFILE, where nothing reads them.

    Four keys resolve through :func:`config.harness_root_config_path` and never
    consult the active profile (``read_model.delta_patches``, ``mcp_admission``,
    and the per-persona ``chat_lane_restore_toolsets`` / ``workdir``). YAML
    accepts them anywhere, and profile-aware surfaces like ``harness status``
    report them back, so a value written one layer below its reader looks
    applied and does nothing.

    Severity splits on whether the ROOT also carries the key:

    * ``defect`` — profile only. The operator's instruction is INERT. Measured
      cost of the 2026-08-13 instance: the S7-A patch producer stayed dark, so
      one field change shipped an 822,671-byte delta instead of a 486-byte
      patch, while ``harness status`` reported the flag on the whole time.
    * ``notice`` — set in both. The live value is correct; the profile copy is a
      redundant leftover worth deleting but not worth failing a health check
      over.

    Two keys added 2026-09-04 (w12/m5), because a two-store census read
    ``misplaced_root_only_keys`` 9 against 2 and had neither a cure nor a
    denominator to read that with:

    * ``remediation`` — the CLASS's one cure, stated whether or not anything is
      currently broken, the way ``_persona_binding_report`` has always stated
      its own. Inert values move to the root; redundant copies are deleted; and
      it says plainly that no automated repair exists, because rewriting an
      operator's ``config.yaml`` is not a write this doctor takes on its own.
    * ``scope`` — ``profiles_examined`` and ``root_only_key_patterns`` from the
      same walk the rows come from. A row is (profile x concrete key) and two of
      the four patterns are per-persona, so a raw count compares inventories
      across two machines, not health.
    """

    from .config import harness_root_config_path, scan_misplaced_root_only_keys

    try:
        scan = scan_misplaced_root_only_keys()
        rows = scan["rows"]
        scope = scan["scope"]
        root_config_path = str(harness_root_config_path())
    except Exception as exc:
        return {"available": False, "health": HEALTH_UNKNOWN, "error": _error_text(exc)}

    inert = [row for row in rows if not row.get("set_in_root")]
    redundant = [row for row in rows if row.get("set_in_root")]
    if inert:
        health = HEALTH_DEFECT
    elif redundant:
        health = HEALTH_NOTICE
    else:
        health = HEALTH_OK
    return {
        "available": True,
        "health": health,
        "misplaced": rows,
        "inert": inert,
        "redundant": redundant,
        "scope": scope,
        "remediation": (
            f"The root config {root_config_path} is the only reader of these keys. "
            "Move an inert value there (it is being ignored where it sits); "
            "delete a redundant profile copy (the root value is already live). "
            "There is no automated repair: rewriting an operator's config.yaml is "
            "a write the doctor does not take on its own."
        ),
        "notices": [
            f"{row['key']} set in profile '{row['profile']}' is ignored — "
            f"{row['read_only_by']} reads {row['root_config_path']}"
            for row in inert
        ]
        + [
            f"{row['key']} in profile '{row['profile']}' duplicates the root value and is unread"
            for row in redundant
        ],
    }


def _model_authority_report(_context: _DoctorProbeContext | None = None) -> dict[str, Any]:
    from .config import describe_runtime_default_authority

    try:
        authority = describe_runtime_default_authority()
    except Exception as exc:
        return {"available": False, "health": HEALTH_UNKNOWN, "error": _error_text(exc)}
    override = authority.get("harness_override", {})
    pins = authority.get("persona_pins", []) or []
    redundant_pins = [p for p in pins if p.get("matches_runtime_default") is True]
    provider_only_pins = [p for p in pins if p.get("provider_pinned_without_model")]
    notices: list[str] = []
    if override.get("model_state") == "shadowing":
        notices.append(
            f"agent_runtime.default_model ({override.get('model')}) shadows the runtime default from model.default"
        )
    elif override.get("model_state") == "redundant":
        notices.append("agent_runtime.default_model duplicates model.default and is unmaintained")
    if redundant_pins:
        notices.append(
            "persona pins duplicate the runtime default: "
            + ", ".join(sorted(p.get("persona_id", "?") for p in redundant_pins))
        )
    if provider_only_pins:
        notices.append(
            "persona provider pinned without a model: "
            + ", ".join(sorted(p.get("persona_id", "?") for p in provider_only_pins))
        )
    return {
        "available": True,
        # Stale/duplicate pins are informational by contract (a pin never turns
        # the doctor into a fix job), so notices are examined-but-not-actionable.
        "health": HEALTH_NOTICE if notices else HEALTH_OK,
        "resolved": authority.get("resolved", {}),
        "top_level": authority.get("top_level", {}),
        "harness_override": override,
        "persona_pins": pins,
        "divergent": override.get("model_state") == "shadowing",
        "notices": notices,
    }


def _snapshot_null_id_report(context: _DoctorProbeContext) -> dict[str, Any]:
    """Null-id rows observed in the frame, plus whether the frame built at all.

    A build CRASH used to be returned as one ``snapshot_null_id_rows`` defect —
    the counter naming a defect class nobody observed, sending an investigator
    hunting null-id rows in a frame that never existed. The two facts are now
    separate: the defect list only ever holds rows actually inspected, and the
    build outcome rides its own ``snapshot_build`` section as ``unknown`` + the
    error, which clears the report's ``ok`` without inventing a finding.

    They are two PAYLOAD keys from this one probe — ``rows`` and ``build`` —
    published by the table, which is why the section still contributes exactly
    one ``health`` and one count.
    """

    try:
        snapshot = context.snapshot_builder()
    except Exception as exc:
        build = {
            "health": HEALTH_UNKNOWN,
            "observed": False,
            "error": _error_text(exc),
        }
        return {"health": HEALTH_UNKNOWN, "rows": [], "build": build}
    expected = {
        "agents": "persona_id",
        "persona_instances": "persona_instance_id",
    }
    defects: list[dict[str, Any]] = []
    for collection, id_key in expected.items():
        rows = snapshot.get(collection)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if isinstance(row, dict) and not row.get(id_key):
                defects.append({"collection": collection, "index": index, "id_key": id_key})
    health = HEALTH_DEFECT if defects else HEALTH_OK
    return {
        "health": health,
        "rows": defects,
        "build": {"health": health, "observed": True},
    }


# -- the roster/office join, as a READ (plan D1/D8) ---------------------------
#
# Two stores answer two different questions and neither is folded into the
# other: the persona-instance row answers "does this agent exist" (the
# roster-only recovery door ``persona instance create --add-instance``
# legitimately mints rows that were never placed), and the instance-keyed
# office actor answers "is it on this level". Nothing had ever looked at the
# JOIN — ``harness doctor`` reported six sections and none of them was this
# one, and ``persona instance reconcile`` prunes orphan ROWS without ever
# opening the office. So a half-state (a retired instance whose actor survived,
# a placement whose compensation archived the row and not the desk) was
# representable, durable, and invisible to the tool an operator runs to find it.
#
# This section is a READ and only a read. The repairs already exist and are
# deliberate operator gestures — a retire for an orphan actor, a resumed create
# for an unplaced row — so a doctor that silently reconciled them would be
# choosing which of the two stores was wrong on the operator's behalf, on
# evidence it can only see one snapshot of.


def _census_instance_key(raw_id: Any, *, persona_id: Any = None) -> str:
    """The one spelling BOTH sides of the join are compared in.

    ``OfficeStore.upsert_actor`` stores ``persona_instance_id`` through
    ``canonical_persona_instance_id`` (via ``_canonical_actor_key``), so a
    roster row still carrying a legacy spelling would read as an orphan against
    its own actor if the two sides were compared raw. Routing BOTH sides through
    the single derivation authority is what keeps this census from inventing
    findings out of the id drift that ``persona instance reconcile`` exists to
    fold.

    **Both sides means both.** Until H-H11 only the roster side was routed
    through here, and the actor side was read raw off the file — which is not
    the same set of ids, because ``upsert_actor`` is not the only writer: the
    realm pull's ``adopt_remote_actor`` writes a PEER's row verbatim, legacy
    spelling and all, and that actor then reported as an ``orphan_actor``
    against a roster row it names correctly. A defect invented out of a
    spelling, in the section whose whole contract is not to do that.

    ``""`` for an id that is absent or unreadable — a class-keyed actor, which
    is out of the join by construction rather than by omission.
    """

    from .persona_assignments import canonical_persona_instance_id

    raw = str(raw_id or "").strip()
    if not raw:
        return ""
    canonical = canonical_persona_instance_id(raw, persona_id=persona_id)
    return canonical or raw


def _census_unknown(detail: str, *, unreadable: list[str] | None = None) -> dict[str, Any]:
    """The census as UNEXAMINED. Every count is ``None``, never ``0``/``[]``.

    A store this section could not read leaves it with no world to count, and an
    empty list here would read to an operator as "looked, found none" — the
    false all-clear the whole doctor is written against.

    A SHORT world takes this path too, and that is the subtle half. Both scans
    return the rows they could read beside a count of the ones they could not
    (``PersonaInstanceScan`` / ``ActorScan`` carry that count for exactly this
    reason). A census that partitioned the readable remainder would report a
    perfectly healthy placement as an ORPHAN — because the file that would not
    decode is its roster row — inventing a defect out of an outage and pointing
    the operator's remediation at the wrong store. So a partition is computed
    only over a world that was read in full.
    """

    report: dict[str, Any] = {
        "health": HEALTH_UNKNOWN,
        "error": detail,
        "observed": False,
        "placed": None,
        "unplaced_rows": None,
        "orphan_actors": None,
        # Same rule again, and for a reason of its own: "no OTHER live actor
        # holds this id" is the absence a duplicate sweep asserts, and a file
        # that would not open is one that might be holding it.
        "duplicate_placements": None,
        "workspaces": None,
    }
    if unreadable:
        report["unreadable"] = sorted(unreadable)
    return report


# The DESK-LITTER CENSUS stood here (plan DL-H1) — four ``DESK_LITTER_*``
# reasons, the pure ``_desk_litter_reason`` classifier that filed a live
# ``kind: "desk"`` item into one of them, and the ``_census_desk_litter`` /
# ``_census_agent_item_bindings`` sweeps below that fed it. All retired
# 2026-09-18 by owner ruling: *"i want desks to just be one type all agents can
# use, no more per persona desk, just one single desk object."*
#
# Every one of the four reasons was a statement about a desk's AGENT HALF —
# missing, scope-stale, persona-retired, or never a desk at all. A generic desk
# has no agent half by construction: its ``persona_id`` is its own synthetic id
# (``desk_<8 base36>``), so no ``kind: "agent"`` item will ever share it and
# ``agent_missing`` would have fired on every correctly-placed desk, forever. A
# notice an operator cannot clear is a notice they stop reading, which is the
# failure this whole doctor is written against — so the class goes rather than
# being re-keyed. The plan is
# ``EterniaLauncher/docs/mission_control/planned/generic-desk-and-inspector-tables.md``
# (slice 1).
#
# What KEPT its place, because none of it was about desks: ``orphan_actors``
# (an ACTOR whose instance is retired or missing — kind-agnostic),
# ``unplaced_rows``, and ``duplicate_placements`` (one item id held by two live
# actor rows, which is a claim about ROWS and fires on any kind).


#: The retire that archived this actor's roster row RECORDED that it could not
#: archive this actor (H-H5's receipt names the key). This is the "row archived,
#: desk still live" half-state the retire ack has reported since S5 and nothing
#: could see afterwards — the ack was the only witness and it expired with the
#: call. The repair is a re-retire (the replay sweeps live placements, D2) or
#: ``runtime.office.remove``.
ORPHAN_ACTOR_RETIRE_INCOMPLETE = "retire_incomplete"

#: This install holds a retirement tombstone for the instance and its receipt
#: does NOT name this actor — so the actor was placed after the retire, or the
#: receipt is from before H-H5 and cannot say. Softer than
#: ``retire_incomplete`` on purpose: an unreadable or absent receipt degrades to
#: here, and both reasons share a repair set.
ORPHAN_ACTOR_INSTANCE_RETIRED = "instance_retired"

#: No tombstone and no live row: this install has never held the instance. The
#: realm-pulled placement (office actors sync, persona instances are per-install
#: by ruling), for which `agent retire` is the refusal arm by construction and
#: ``runtime.office.remove`` is the only verb that works.
ORPHAN_ACTOR_INSTANCE_UNKNOWN = "instance_unknown"

ORPHAN_ACTOR_REASONS = (
    ORPHAN_ACTOR_RETIRE_INCOMPLETE,
    ORPHAN_ACTOR_INSTANCE_RETIRED,
    ORPHAN_ACTOR_INSTANCE_UNKNOWN,
)


def _orphan_actor_reason(
    *,
    actor_key: str,
    instance_id: str,
    retired: frozenset[str],
    receipt: dict[str, Any] | None,
) -> str:
    """Which of the three orphans this actor is (H-H4).

    Pure — the tombstone set and the receipt are both read by the caller, once
    each, so the partition is unit-testable without a filesystem fixture.

    The census has reported ``orphan_actors`` as one undifferentiated bucket
    since S6, and the doctor's remediation string has had to describe the split
    in PROSE ("an orphan actor whose instance this install still holds … one
    whose instance this install never held …") because there was no field to key
    it on. There is now, and it is keyed on facts the store holds — a tombstone,
    and a receipt naming this actor key — never on an id's shape.

    ``retire_incomplete`` first, because it is the narrowest: an actor named by
    its own retire's failure list is retired AND unarchived, and reporting it as
    merely ``instance_retired`` would lose the one fact that says a retry is the
    repair. A receipt that is absent or unreadable degrades to
    ``instance_retired``, which is the safe direction — same row, same count,
    the softer of two statements about the same absence.
    """

    if instance_id not in retired:
        return ORPHAN_ACTOR_INSTANCE_UNKNOWN
    failures = (receipt or {}).get("office_archive_failures") or []
    if isinstance(failures, list) and any(
        isinstance(failure, dict) and str(failure.get("actor_key") or "") == actor_key
        for failure in failures
    ):
        return ORPHAN_ACTOR_RETIRE_INCOMPLETE
    return ORPHAN_ACTOR_INSTANCE_RETIRED


# ── duplicate placements: one item id, two live actor rows (H-H8) ────────────
#
# The residual the two write fences left between them, stated in doc 06's
# write-verbs section: the class-key fence guards class-keyed payloads only (an
# instance-keyed write "IS the migration's shape"), and the desk fence counted
# DISTINCT desk ids per persona, so an instance-keyed write claiming an item id
# another live actor already held passed both. Nothing server-side could see it
# — the census joins on ``persona_instance_id`` and never opened
# ``actor.items``, so both holders counted as ``placed`` and the section
# reported ``ok``.
#
# One of those two fences is gone (2026-09-18) and THIS SWEEP IS UNCHANGED BY
# THAT, which is worth stating because the desk-litter census beside it had to
# be deleted on the same day. The difference is what each one asks. This asks
# whether two live actor ROWS claim one item id — a question with no kind in it,
# true of an agent, a desk, or whatever ``ITEM_KINDS`` grows next. The
# desk-litter census asked whether a desk's AGENT HALF was present, and a
# generic desk has none by construction.
#
# It is a READER and was never a fence: a census row moves no write path.

#: Every holder is bound to the SAME live-ish instance — one instance's
#: placement claimed by two live actor rows. A DEFECT: nothing legitimate mints
#: it, and it is the two-fences residual in the shape that actually costs
#: something (the realm-pulled actor file written under a peer's actor key, or a
#: legacy id spelling that canonicalizes onto a key already held).
DUPLICATE_PLACEMENT_SAME_INSTANCE = "same_instance"

#: The holders are different instances. Reported, never a defect: D6 rules that
#: "duplicate desks are fine and only a duplicate on the SAME INSTANCE is not —
#: it's an instantiated system", and item ids are minted persona-scoped
#: (``<persona>_<kind>``), so two instances of one persona each authoring a desk
#: produce exactly this. Calling it a defect would re-key this predicate to the
#: persona, which is the move the ruling forbids.
DUPLICATE_PLACEMENT_CROSS_INSTANCE = "cross_instance"

#: At least one holder is CLASS-KEYED (no instance binding). Reported, never a
#: defect: this is the class→instance re-key migration's own transient —
#: ``scripts/office_actor_rekey_to_instance.py::_apply`` mints the instance-keyed
#: actor with the class-keyed actor's items copied verbatim and only then
#: archives the old key, so both rows briefly claim every id. A census that
#: called it a defect would report the one operator script whose whole job is to
#: move a placement.
DUPLICATE_PLACEMENT_UNBOUND_HOLDER = "unbound_holder"

def _duplicate_placement_reason(bindings: tuple[str, ...]) -> str:
    """Which duplicate this is, from the holders' instance bindings alone.

    ``bindings`` is one entry per HOLDER, ``""`` for a class-keyed actor. Pure,
    total over its input, and — like the desk classifier — the part worth unit
    testing, so it must not be reachable only through a filesystem fixture.

    THE ORDER IS THE DESIGN: the unbound arm is asked first, because a
    class-keyed holder beside an instance-keyed one is also, trivially, a set of
    bindings that is not all-equal, so any other order would file the re-key
    migration's legal transient under ``cross_instance`` and lose the one
    distinction an operator acts on.
    """

    if any(not binding for binding in bindings):
        return DUPLICATE_PLACEMENT_UNBOUND_HOLDER
    if len(set(bindings)) == 1:
        return DUPLICATE_PLACEMENT_SAME_INSTANCE
    return DUPLICATE_PLACEMENT_CROSS_INSTANCE


# ── the census's per-workspace sweeps ────────────────────────────────────────
#
# THREE of them since 2026-09-18: the desk-litter sweep and the agent-item pass
# that fed it left with the desk-litter census (see the note above the orphan
# reasons). The extraction below is unchanged for the three that remain.
#
# Lifted out of :func:`_placement_census_report`, which read the two stores,
# gated them, and then ran several different questions over one workspace loop
# with a pure classifier beside each. The READ and the GATE stay where they are —
# they are the part that has to happen once, in order, for the whole census —
# and what moves is everything after them: each sweep now takes the already-
# gated world and answers with rows, so it can be asked a question directly
# instead of only through two live stores and a doctor section.
#
# They share ONE argument on purpose: ``bindings``, the ``(actor, instance_id)``
# pairs :func:`_census_live_actor_bindings` resolves once per workspace. Every
# sweep needs the actor side of its comparison spelled the way the roster side
# is, and three copies of that resolution is precisely how the two stores came
# to disagree about the same persona.


def _census_live_actor_bindings(scan: Any) -> list[tuple[Any, str]]:
    """The workspace's LIVE actors, each with its canonical instance binding.

    ONE canonical binding per live actor, resolved once here and read by every
    sweep below, so the actor side of every comparison in this workspace is
    spelled the way the roster side is. See :func:`_census_instance_key` for
    what a raw read cost.
    """

    return [
        (actor, _census_instance_key(actor.persona_instance_id, persona_id=actor.persona_id))
        for actor in scan.actors
        if actor.state != "archived"
    ]


def _census_join_workspace(
    workspace_id: str,
    bindings: list[tuple[Any, str]],
    *,
    live_rows: dict[str, Any],
    retired: frozenset[str],
    receipt_for: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """The roster/office join for one workspace: placed, orphans, referenced.

    ``receipt_for`` is a resolver rather than a store, and that is what keeps
    this a function of its arguments: the caller owns the per-census memo, so a
    clean store still reaches zero reads and a test can ask this the retire
    question without a retirement archive on disk. The third element is the set
    of instance ids this workspace REFERENCED, which the caller folds across
    workspaces to decide what is unplaced — returned rather than mutated
    through, because "which rows did this workspace claim" is an answer and not
    a side effect.
    """

    ws_placed: list[dict[str, Any]] = []
    ws_orphans: list[dict[str, Any]] = []
    referenced: set[str] = set()

    for actor, instance_id in bindings:
        if not instance_id:
            # A class-keyed actor answers no roster question: it is keyed on
            # the persona, not on an instance, so it is out of this join by
            # construction rather than by omission.
            continue
        referenced.add(instance_id)
        row = {
            "workspace_id": workspace_id,
            "actor_key": actor.actor_key,
            "persona_id": actor.persona_id,
            "persona_instance_id": instance_id,
        }
        if instance_id in live_rows:
            ws_placed.append(row)
        else:
            # H-H4: WHICH orphan, keyed on the two facts the store holds — a
            # retirement tombstone, and a retire receipt naming this actor key.
            row["reason"] = _orphan_actor_reason(
                actor_key=actor.actor_key,
                instance_id=instance_id,
                retired=retired,
                receipt=receipt_for(instance_id),
            )
            ws_orphans.append(row)
    return ws_placed, ws_orphans, referenced


def _census_duplicate_placements(
    workspace_id: str, bindings: list[tuple[Any, str]]
) -> list[dict[str, Any]]:
    """ITEM ids held by more than one live actor, every holder named (H-H8).

    Over the SAME live actors of the SAME fully-read world. This is the pass
    that opens ``actor.items`` for the JOIN's sake rather than the desk sweep's:
    the join is actor-level, so two live actors holding one item id were both
    counted ``placed`` and the section reported ``ok``.

    Distinct HOLDERS per id, which is the mirror of the write fence's "distinct
    ids per persona": one actor listing an id twice is one holder, because the
    fault named here is two ROWS claiming one placement.
    """

    holders: dict[str, list[dict[str, Any]]] = {}
    for actor, binding in bindings:
        seen_in_actor: set[str] = set()
        for item in actor.items or ():
            item_id = str(getattr(item, "item_id", "") or "").strip()
            if not item_id or item_id in seen_in_actor:
                continue
            seen_in_actor.add(item_id)
            holders.setdefault(item_id, []).append(
                {
                    "actor_key": actor.actor_key,
                    "persona_instance_id": binding or None,
                    "kind": str(getattr(item, "kind", "") or ""),
                }
            )

    ws_duplicates: list[dict[str, Any]] = []
    for item_id, rows in sorted(holders.items()):
        if len(rows) < 2:
            continue
        ws_duplicates.append(
            {
                "workspace_id": workspace_id,
                "item_id": item_id,
                "kinds": sorted({row["kind"] for row in rows if row["kind"]}),
                "holders": rows,
                "reason": _duplicate_placement_reason(
                    tuple(str(row["persona_instance_id"] or "") for row in rows)
                ),
            }
        )
    return ws_duplicates


def _placement_census_report(_context: _DoctorProbeContext | None = None) -> dict[str, Any]:
    """Per-workspace roster/office join: placed, unplaced rows, orphan actors.

    The definitions are the plan's (D1), stated once here because three
    different readings of "placed" is how the two stores drifted in the first
    place:

    * ``placed`` — a LIVE instance-keyed actor whose ``persona_instance_id``
      names a LIVE roster row. Both halves present is the only whole shape.
    * ``unplaced_rows`` — a live placement-backed row (i.e. NOT a canonical
      persona channel, per ``is_canonical_persona_channel``) that no live actor
      references. LEGAL, not a defect: the roster-only door mints exactly this,
      on purpose. Reported as a ``notice`` so an operator can see them without
      the doctor calling a supported gesture broken.
    * ``orphan_actors`` — a live instance-keyed actor whose instance is retired
      or missing. A DEFECT: it renders on the level as an agent nothing can
      message. Each row carries a ``reason`` (H-H4), one of the three
      ``ORPHAN_ACTOR_*`` tokens, because the three have different repairs and
      the remediation string could previously only describe the split in prose.
      ``retire_incomplete`` is the close-the-loop half of the retire's office
      report: a failure the ack named and nothing could see once the ack was
      gone now has a standing detector.
    A fourth finding, ``desk_litter`` (plan DL-H1), lived here until 2026-09-18
    and was REMOVED with the pairing it asked about — schema 10, and the note
    above the orphan reasons has the ruling. Nothing below it is kind-aware:
    every row this section still reports is a claim about an ACTOR or an item
    ID, and a desk answers both exactly as an agent does.

    * ``duplicate_placements`` (H-H8) — an ITEM id held by more than one live
      actor, with every holder named and one of the three
      ``DUPLICATE_PLACEMENT_*`` reasons. A defect only for ``same_instance``;
      the other two are reported at ``notice``, and the reasons are where the
      D6 ruling is spent. The join above could not see any of them: it is
      actor-level, so both holders counted as ``placed`` and the section
      reported ``ok``.

    ``health`` is ``unknown`` — never ``ok`` — when either store could not be
    read in full. That includes a scan that returned rows AND a nonzero
    ``unreadable`` count: a census computed over a short world reports an actor
    as orphaned because its roster row is the file that would not decode, which
    is the exact false finding this doctor's None-not-zero counting rule exists
    to forbid.
    """

    # ``_normalize_persona_id`` was imported here beside ``OfficeStore`` — the
    # STORE's own spelling of a persona id, borrowed rather than re-derived so
    # the two halves of a persona-level join could not disagree. Its only
    # readers were the desk sweeps (2026-09-18), and the joins that remain are
    # keyed on ``persona_instance_id`` through :func:`_census_instance_key`,
    # which is that same borrow-the-authority rule applied to the other id.
    from .office_store import OfficeStore
    from .persona_assignments import (
        PersonaInstanceStore,
        is_canonical_persona_channel,
        retired_persona_instance_ids,
    )

    unreadable: list[str] = []

    try:
        roster = PersonaInstanceStore().scan_all()
    except Exception as exc:
        return _census_unknown(_error_text(exc))
    if roster.unreadable:
        unreadable.append(f"persona_instances:{roster.unreadable}")

    live_rows = {
        _census_instance_key(row.id, persona_id=row.persona_id): row
        for row in roster.instances
    }

    store = OfficeStore()
    try:
        workspace_ids = list(store.list_workspaces())
    except Exception as exc:
        return _census_unknown(_error_text(exc))

    placed: list[dict[str, Any]] = []
    orphan_actors: list[dict[str, Any]] = []
    duplicate_placements: list[dict[str, Any]] = []
    per_workspace: dict[str, dict[str, Any]] = {}
    referenced: set[str] = set()

    scans: list[tuple[str, Any]] = []
    for workspace_id in workspace_ids:
        try:
            scan = store.scan_actors(workspace_id)
        except Exception as exc:
            unreadable.append(f"office:{workspace_id} ({_error_text(exc)})")
            continue
        if scan.unreadable:
            unreadable.append(f"office:{workspace_id}:{scan.unreadable}")
        scans.append((workspace_id, scan))

    # EVERY scan first, the partition second, and the gate between them. One
    # unreadable file anywhere in either store is enough to make the JOIN — not
    # merely one row of it — untrustworthy, because the census's two findings
    # are both statements about ABSENCE ("no live actor references this row",
    # "no live row backs this actor") and absence is precisely what a file that
    # would not open is indistinguishable from.
    if unreadable:
        return _census_unknown(
            "unreadable: " + ", ".join(sorted(unreadable)), unreadable=unreadable
        )

    # Read ONCE for the whole census, never per row. The archive is one
    # directory per retire, forever, and ``retired_persona_instance_ids`` says
    # so at its own docstring. It NEVER raises — a listing it could not walk
    # answers the empty set — so it cannot re-open the unreadable gate above.
    # Its remaining reader is the orphan partition (H-H4), which tells an
    # instance this install tombstoned from one it never held.
    retired_instances = retired_persona_instance_ids()
    #: One receipt read per orphaned instance, for the whole census (H-H4).
    retire_receipts: dict[str, dict[str, Any] | None] = {}

    def _retire_receipt_for(instance_id: str) -> dict[str, Any] | None:
        """This instance's retire receipt, read at most once per census.

        The memo is the CALLER's, which is why the join sweep takes a resolver
        rather than a store: the read is per orphaned INSTANCE, never per actor
        and never on the healthy path, so a clean store reaches zero reads —
        what keeps this affordable in a section that already walks both stores
        in full — and it stays that way across every workspace rather than per
        workspace.
        """

        if instance_id not in retire_receipts:
            retire_receipts[instance_id] = (
                PersonaInstanceStore().read_retire_receipt(instance_id)
                if instance_id in retired_instances
                else None
            )
        return retire_receipts[instance_id]

    for workspace_id, scan in scans:
        # Two sweeps, two functions, one resolved binding list between them.
        # The read and the gate above are what had to happen once and in order;
        # everything from here is a question asked of the world they produced.
        bindings = _census_live_actor_bindings(scan)
        ws_placed, ws_orphans, ws_referenced = _census_join_workspace(
            workspace_id,
            bindings,
            live_rows=live_rows,
            retired=retired_instances,
            receipt_for=_retire_receipt_for,
        )
        referenced |= ws_referenced
        ws_duplicates = _census_duplicate_placements(workspace_id, bindings)

        placed.extend(ws_placed)
        orphan_actors.extend(ws_orphans)
        duplicate_placements.extend(ws_duplicates)
        per_workspace[workspace_id] = {
            "placed": len(ws_placed),
            "unplaced_rows": [],
            "orphan_actors": ws_orphans,
            "duplicate_placements": ws_duplicates,
            "observed": True,
        }

    unplaced_rows: list[dict[str, Any]] = []
    for key, row in sorted(live_rows.items()):
        if key in referenced:
            continue
        if is_canonical_persona_channel(row):
            # The persona's global operator channel is not a placement and was
            # never meant to hold one. Counting it would report one "unplaced"
            # row per persona on every healthy runtime — a finding the operator
            # can never clear, which is how a census stops being read.
            continue
        entry = {
            "persona_instance_id": key,
            "persona_id": row.persona_id,
            "workspace_id": row.workspace_id,
        }
        unplaced_rows.append(entry)
        bucket = per_workspace.get(row.workspace_id or "")
        if isinstance(bucket, dict) and isinstance(bucket.get("unplaced_rows"), list):
            bucket["unplaced_rows"].append(entry)

    same_instance_duplicates = [
        row
        for row in duplicate_placements
        if row.get("reason") == DUPLICATE_PLACEMENT_SAME_INSTANCE
    ]
    if orphan_actors or same_instance_duplicates:
        health = HEALTH_DEFECT
    elif unplaced_rows or duplicate_placements:
        # An unplaced row or a non-``same_instance`` duplicate raises the census
        # to ``notice`` and NEVER past it: an orphan actor is a defect because
        # it renders as an agent nothing can message, while neither of these
        # mis-renders anything. Promoting either would turn ``needs_fix`` on for
        # a store with no actual fault, and the doctor's whole contract is that
        # its flags mean something.
        #
        # A duplicate placement splits on that same line — see
        # :func:`_duplicate_placement_reason`. (The ``desk_litter`` term rode
        # this arm until 2026-09-18 and left with the census that produced it.)
        health = HEALTH_NOTICE
    else:
        health = HEALTH_OK
    report: dict[str, Any] = {
        "health": health,
        "observed": True,
        "placed": len(placed),
        "placed_actors": placed,
        "unplaced_rows": unplaced_rows,
        "orphan_actors": orphan_actors,
        "duplicate_placements": duplicate_placements,
        "workspaces": per_workspace,
        # A4. The orphan half used to read "retiring or re-creating its agent",
        # and for the orphan this census reports most often that names the ONE
        # verb that cannot work. A realm-pulled placement is born orphaned —
        # office actors sync, persona instances are per-install by ruling — so
        # its instance has never existed here, and `agent retire` refuses
        # `not_found` terminally. The refusal is correct; prescribing it was
        # not. Both repairs are named, keyed on the fact that decides between
        # them (does this install hold the instance), never on the id's shape.
        #
        # AX7. The pulled-orphan repair names `--local-only`, and that is not a
        # detail. A doctor remediation is DIAGNOSTIC intent: the operator asked
        # what is wrong with THIS install's projection, not to delete a
        # placement on every machine in the realm. Prescribing the tombstoning
        # form would have this report quietly authoring realm-wide deletes on
        # the operator's behalf — the authored form stays available, and stays
        # for the moment the operator actually means it.
        #
        # H-H4 turns the prose split into the rows' own ``reason`` field, so the
        # three repairs are keyed on a token a reader can grep rather than on a
        # sentence they have to parse — and the sentence now names the tokens
        # instead of re-describing the conditions behind them. It names them
        # WITHOUT dropping either of the two guarantees A4 and AX7 put in this
        # string: the arms are still told apart by a fact rather than a
        # spelling, and the form prescribed for the pulled orphan is still the
        # local-only one.
        "remediation": (
            "an orphan actor reading retire_incomplete was named by its own "
            "retire's failure list: re-run `agent retire` — retiring or "
            "re-creating its agent still clears it, and the retire's replay "
            "sweeps live placements — or evict the desk from this install with "
            "`harness office actor-remove --workspace <ws> --actor <key> "
            "--local-only`; one reading instance_retired is cleared the same "
            "two ways; one reading instance_unknown — a realm-pulled placement "
            "this install never held, whose instance stayed on the peer — has "
            "nothing to retire and is cleared with actor-remove --local-only "
            "or `runtime.office.remove` alone (drop --local-only only if you "
            "mean to delete the placement realm-wide, which is what the "
            "launcher's own delete does); an unplaced row is either awaiting a "
            "placement or is the roster-only recovery door working as designed; "
            "a duplicate_placements row reading "
            "same_instance is one instance's placement claimed by two live actor "
            "rows — remove or re-place one holder, whose actor_key is named"
        ),
    }
    return report


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
