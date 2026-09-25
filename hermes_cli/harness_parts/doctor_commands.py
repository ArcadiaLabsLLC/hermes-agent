"""``hermes harness doctor``: the harness health report and its repairs.

Separate because the doctor reads every store and writes repairs only under
``--fix``; the checks themselves live in ``agent_runtime.harness_doctor``.
"""

from __future__ import annotations

from agent_runtime.cli_format import emit_json
from agent_runtime.harness_doctor import (
    DEFAULT_WORKTREE_MIN_AGE_SECONDS,
    doctor_detail_sources,
    run_harness_doctor,
)
from agent_runtime.root_observability import attach_root_observability
from agent_runtime.resolution import resolution_table, resolve_runtime
from hermes_cli.harness_support import ERROR_EXIT_CODES

__layer__ = "lanes"
__all__ = [
    "_cmd_doctor",
]


def _cmd_doctor(args) -> int:
    resolution = resolve_runtime()
    if getattr(args, "fix", False) and not getattr(args, "dry_run", False) and not getattr(args, "yes", False):
        data = {
            "ok": False,
            "error": "confirmation_required",
            "summary": "harness doctor --fix requires --yes, or use --dry-run to preview repairs",
        }
        print(emit_json(data) if args.json else data["summary"])
        return ERROR_EXIT_CODES["confirmation_required"]
    hygiene = run_harness_doctor(
        fix=bool(getattr(args, "fix", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        worktree_min_age_seconds=int(
            getattr(args, "worktree_min_age_seconds", DEFAULT_WORKTREE_MIN_AGE_SECONDS)
            or DEFAULT_WORKTREE_MIN_AGE_SECONDS
        ),
    )
    data = {
        # Command status ("the doctor ran to completion"), NOT the runtime's
        # health — the refusal branch above spends the same key on a rejected
        # invocation. ``healthy`` is the verdict a triage reader wants, mirrored
        # up from ``hygiene.ok`` so `--json | jq .healthy` cannot read the
        # command's exit as an all-clear over an unexamined body.
        "ok": True,
        "healthy": bool(hygiene.get("ok", False)),
        # ``runtime_resolution`` predates the cross-verb ``resolution`` block
        # and stays for its richer layers table; the standard block is stamped
        # below from the SAME resolution object (attach_root_observability).
        "runtime_resolution": {
            "store_root": str(resolution.store_root),
            "layer": resolution.layer,
            "hermes_home": resolution.hermes_home,
            "config_path": resolution.config_path,
            "trace": list(resolution.trace),
            "layers": resolution_table(),
        },
        "hygiene": hygiene,
    }
    attach_root_observability(data, resolution=resolution)
    if args.json:
        print(emit_json(data))
    else:
        print("Harness runtime resolution")
        print(f"resolved: {resolution.store_root} ({resolution.layer})")
        for row in data["runtime_resolution"]["layers"]:
            marker = "*" if row["winner"] else " "
            print(
                f"{marker} {row['layer']:<7} value={row['value'] or '<unset>'} "
                f"exists={row['exists']}"
            )
        summary = hygiene.get("summary") or {}
        counts = summary.get("finding_counts") or {}
        event_log = hygiene.get("findings", {}).get("event_log") or {}
        print("Harness doctor")
        # THE verdict line, first. Text mode printed two counts and an event-log
        # size — three of the five examined sections never reached the operator
        # at all, so a diverged binding or an unreadable model-authority config
        # was invisible on the default path. Every section reports here now, and
        # ``unknown`` is stated as unknown rather than folded into a clean run.
        verdict = (
            "ok"
            if hygiene.get("ok")
            else "NEEDS FIX"
            if summary.get("needs_fix")
            else "UNKNOWN"
        )
        print(f"verdict: {verdict}")
        # Render exactly the findings the report emits. The mission-era counts
        # (runs/workers/open tasks/incidents/compactable rows) went away with
        # the lane; reading them here is what made the default path crash.
        # ``None`` means the class was not observed — say so, never print 0.
        print(
            "findings: "
            + " ".join(
                f"{name}={'unknown' if count is None else count}"
                for name, count in counts.items()
            )
        )
        # Where each section keeps its own error text — DERIVED from the
        # doctor's own section table, not re-typed here. This roster was the
        # fourth copy of one set and the only one no test pinned, so a section
        # added to the report but forgotten here was counted and verdicted while
        # rendering no operator line at all.
        detail_sources = doctor_detail_sources(hygiene)
        for name, health in sorted((summary.get("section_health") or {}).items()):
            if health in (None, "ok"):
                continue
            source = detail_sources.get(name)
            detail = source.get("error") if isinstance(source, dict) else None
            print(f"  {name}: {health}" + (f" ({detail})" if detail else ""))
        if event_log.get("health") == "unknown":
            print(f"event log: unknown ({event_log.get('error') or 'unreadable'})")
        else:
            print(
                "event log: "
                f"size={event_log.get('size_bytes')} bytes lines={event_log.get('line_count')} "
                f"archive_slices={event_log.get('archived_event_slices')} "
                f"index={event_log.get('index_health')}"
            )
        census = hygiene.get("findings", {}).get("placement_census") or {}
        if census.get("observed"):
            # The census's own line, because its lists are the payload an
            # operator acts on and the ``findings:`` counts above only say how
            # many. Orphans are named individually — that id IS the remediation
            # argument — while unplaced rows are counted, since a healthy
            # runtime can legitimately carry several.
            print(
                f"placement census: placed={census.get('placed')} "
                f"unplaced_rows={len(census.get('unplaced_rows') or [])} "
                f"orphan_actors={len(census.get('orphan_actors') or [])} "
                f"duplicate_placements={len(census.get('duplicate_placements') or [])}"
            )
            for orphan in census.get("orphan_actors") or []:
                print(
                    f"  orphan actor: {orphan.get('workspace_id')}/"
                    f"{orphan.get('actor_key')} -> "
                    f"{orphan.get('persona_instance_id')} (no live roster row)"
                )
            # A ``desk litter:`` block stood here, one line per litter row with
            # its reason. It left on 2026-09-18 with the census that produced it
            # (schema 10) — a desk is one generic furniture object addressed by
            # its own id, so it has no agent half for a census to find missing.
            # Every HOLDER on the line, for the same reason the orphan block
            # names its actor: the repair is to remove or re-place one of them,
            # and a row that named only the item id would leave the operator to
            # go find out which two rows are claiming it.
            for duplicate in census.get("duplicate_placements") or []:
                holders = ", ".join(
                    str(holder.get("actor_key"))
                    for holder in duplicate.get("holders") or []
                )
                print(
                    f"  duplicate placement: {duplicate.get('workspace_id')}/"
                    f"{duplicate.get('item_id')} held by {holders} "
                    f"({duplicate.get('reason')})"
                )
        binding = hygiene.get("persona_binding") or {}
        if binding.get("diverged_count"):
            print(
                f"persona binding: {binding['diverged_count']} diverged — "
                f"{binding.get('remediation', '')}"
            )
        for notice in (hygiene.get("model_authority") or {}).get("notices") or []:
            print(f"model authority: {notice}")
        if getattr(args, "fix", False):
            mode = "dry run" if getattr(args, "dry_run", False) else "applied"
            print(f"repairs: {mode}")
    return 0
