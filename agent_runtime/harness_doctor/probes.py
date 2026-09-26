"""The six one-question probes: orphan worktrees, event log, persona binding, root-config misplacement, model authority, snapshot null ids.

Map: ``agent_runtime/harness_doctor/__init__.py``.
"""

from __future__ import annotations

from typing import Any

from ..delivery_directive import reap_orphan_worktrees
from ..events import event_log_health
from .model import HEALTH_DEFECT, HEALTH_NOTICE, HEALTH_OK, HEALTH_UNKNOWN, _DoctorProbeContext, _error_text

__layer__ = "lanes"


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
        from ..persona_profile_binding import binding_index

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

    from ..config import harness_root_config_path, scan_misplaced_root_only_keys

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
    from ..config import OVERRIDE_STATE_REDUNDANT, OVERRIDE_STATE_SHADOWING, describe_runtime_default_authority

    try:
        authority = describe_runtime_default_authority()
    except Exception as exc:
        return {"available": False, "health": HEALTH_UNKNOWN, "error": _error_text(exc)}
    override = authority.get("harness_override", {})
    pins = authority.get("persona_pins", []) or []
    redundant_pins = [p for p in pins if p.get("matches_runtime_default") is True]
    provider_only_pins = [p for p in pins if p.get("provider_pinned_without_model")]
    notices: list[str] = []
    if override.get("model_state") == OVERRIDE_STATE_SHADOWING:
        notices.append(
            f"agent_runtime.default_model ({override.get('model')}) shadows the runtime default from model.default"
        )
    elif override.get("model_state") == OVERRIDE_STATE_REDUNDANT:
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
        "divergent": override.get("model_state") == OVERRIDE_STATE_SHADOWING,
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
