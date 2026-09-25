"""``_parity_warnings`` — the frame's parity warnings, the restamp epsilon, the
redaction observation and the event-summary warnings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_runtime.events import event_summary_missing
from agent_runtime.models import looks_like_persona_instance_id
from agent_runtime.persona_chat_history import _canonical_persona_id
from agent_runtime.persona_instance_identity import (
    backed_persona_identity,
    classify_orphan_persona_instances,
    duplicate_persona_instance_groups,
)
from agent_runtime.serde import section_rows

from agent_runtime.snapshot.boards import _board_parity_warnings
from agent_runtime.snapshot.offices import _office_parity_warnings

__all__ = [
    "_LIVE_MISSION_RESTAMP_EPSILON_SECONDS",
    "_event_summary_warnings",
    "_parity_warnings",
    "_parse_iso_timestamp",
    "_redaction_observed",
]


def _parity_warnings(data) -> list[dict]:
    """Snapshot-level self-checks that flag likely UI/harness divergence."""

    # Board/office warnings do not depend on the persona-instance runtime, so
    # they are computed before the runtime-disabled early return below.
    warnings: list[dict] = _board_parity_warnings(data)
    warnings.extend(_office_parity_warnings(data))
    runtime = data.get("persona_instance_runtime") or {}
    if not runtime.get("enabled"):
        warnings.append(
            {
                "code": "persona_instance_runtime_disabled",
                "detail": "persona instance runtime is off; persona_instances / chat_history / chat_trace are absent from this snapshot",
            }
        )
        return warnings

    instances = section_rows(data.get("persona_instances"))
    for group in duplicate_persona_instance_groups(instances):
        warnings.append(
            {
                "code": "duplicate_persona_instance",
                "entity_id": group["canonical_id"],
                "detail": (
                    f"{len(group['instance_ids'])} live persona-instance rows alias to one canonical id; "
                    "run `harness persona-instance reconcile`"
                ),
                "instance_ids": group["instance_ids"],
            }
        )

    # Orphan / held persona-instance accounting: rows whose backing persona/profile is
    # absent (or a mothballed role) project as phantom "on level" agents. Surface them
    # the same way duplicate rows are surfaced so nothing is silently dropped — the
    # reconciler prunes (archives) the prunable ones; held rows are protected and shown.
    template_names = [
        name
        for row in (data.get("available_personas") or [])
        if isinstance(row, dict)
        for name in (str((row or {}).get("hermes_profile") or "").strip(),)
        if name
    ]
    backed_ids, backed_profiles = backed_persona_identity(
        agents=data.get("agents") or [],
        profile_names=template_names,
    )
    orphan_classes = classify_orphan_persona_instances(
        instances,
        backed_persona_ids=backed_ids,
        backed_profile_names=backed_profiles,
        profile_catalog_authoritative=bool(template_names),
    )
    for entry in orphan_classes["prunable"]:
        warnings.append(
            {
                "code": "orphaned_persona_instance",
                "entity_id": entry["persona_instance_id"],
                "reason": entry["reason"],
                "detail": (
                    f"persona instance '{entry['persona_instance_id']}' has no backing persona/profile "
                    f"({entry['reason']}) and renders as a phantom agent; "
                    "run `harness persona-instance reconcile [--dry-run]`"
                ),
            }
        )
    for entry in orphan_classes["held"]:
        warnings.append(
            {
                "code": "held_orphan_persona_instance",
                "entity_id": entry["persona_instance_id"],
                "reason": entry["reason"],
                "detail": (
                    f"persona instance '{entry['persona_instance_id']}' is orphan-shaped but protected "
                    f"from prune ({entry['reason']})"
                ),
            }
        )
    instance_personas = {
        _canonical_persona_id(inst.get("persona_id")) for inst in instances if isinstance(inst, dict)
    }
    instance_ids = {
        str(inst.get("persona_instance_id") or inst.get("agent_profile_id") or "")
        for inst in instances
        if isinstance(inst, dict)
    }
    # Shape-valid JSON can still be referentially stale. Steering fields are
    # foreign keys into persona_instances; report every unresolved target in
    # the parity envelope so clients never have to infer corruption from a
    # missing card or a failed flow sync.
    for instance in instances:
        if not isinstance(instance, dict):
            continue
        source_id = str(
            instance.get("persona_instance_id")
            or instance.get("agent_profile_id")
            or ""
        )
        spawned_by = str(instance.get("spawned_by") or "").strip()
        if (
            spawned_by
            and looks_like_persona_instance_id(spawned_by)
            and spawned_by not in instance_ids
        ):
            warnings.append(
                {
                    "code": "fk_miss",
                    "from_entity": "persona_instance",
                    "from_id": source_id,
                    "fk_field": "spawned_by",
                    "target_entity": "persona_instances",
                    "target_id": spawned_by,
                    "detail": (
                        f"persona_instance '{source_id}' spawned_by -> "
                        f"{spawned_by} does not resolve in persona_instances; "
                        "run `harness persona-instance reconcile [--dry-run]`"
                    ),
                }
            )
        for parent_id in dict.fromkeys(instance.get("steered_by") or []):
            parent_id = str(parent_id or "").strip()
            if not parent_id or parent_id in instance_ids:
                continue
            warnings.append(
                {
                    "code": "fk_miss",
                    "from_entity": "persona_instance",
                    "from_id": source_id,
                    "fk_field": "steered_by",
                    "target_entity": "persona_instances",
                    "target_id": parent_id,
                    "detail": (
                        f"persona_instance '{source_id}' steered_by -> "
                        f"{parent_id} does not resolve in persona_instances; "
                        "run `harness persona-instance reconcile [--dry-run]`"
                    ),
                }
            )
    for row in data.get("persona_chat_trace") or []:
        if not isinstance(row, dict):
            continue
        row_persona = _canonical_persona_id(row.get("persona_id"))
        row_instance = str(row.get("persona_instance_id") or "")
        if row_persona not in instance_personas and row_instance not in instance_ids:
            warnings.append(
                {
                    "code": "trace_persona_not_in_instances",
                    "entity_id": row_instance or row_persona,
                    "detail": "trace row has no matching persona_instance; the launcher may orphan it",
                }
            )

    chat_rows = [
        row for row in data.get("persona_chat_history") or [] if isinstance(row, dict)
    ]
    for row in chat_rows:
        for field in ("created_at", "updated_at"):
            value = row.get(field)
            if value is not None and _parse_iso_timestamp(value) is None:
                warnings.append(
                    {
                        "code": "persona_chat_history.non_iso_timestamp",
                        "entity_id": row.get("session_id"),
                        "detail": f"persona_chat_history.{field} is not an ISO-8601 timestamp",
                    }
                )
                break

    chat_latest_by_persona: dict[str, datetime] = {}
    mission_latest_by_persona: dict[str, tuple[datetime, str | None]] = {}
    for row in chat_rows:
        persona_id = _canonical_persona_id(row.get("persona_id")) or ""
        if not persona_id:
            continue
        timestamp = _parse_iso_timestamp(row.get("updated_at")) or _parse_iso_timestamp(row.get("created_at"))
        if timestamp is None:
            continue
        if row.get("kind") == "mission" or row.get("live_mission") is True:
            current = mission_latest_by_persona.get(persona_id)
            if current is None or timestamp > current[0]:
                mission_latest_by_persona[persona_id] = (timestamp, row.get("session_id"))
        else:
            current = chat_latest_by_persona.get(persona_id)
            if current is None or timestamp > current:
                chat_latest_by_persona[persona_id] = timestamp
    build_moment = data.get("generated_at")
    if not isinstance(build_moment, datetime):
        build_moment = _parse_iso_timestamp(build_moment)
    for persona_id, (mission_time, session_id) in mission_latest_by_persona.items():
        chat_time = chat_latest_by_persona.get(persona_id)
        if chat_time is None or mission_time <= chat_time:
            continue
        # Mission rows anchor to the persisted assignment created_at, which is
        # legitimately newer than every chat right after a mission is assigned.
        # The regression this guard exists for is BUILD-TIME restamping — only a
        # mission timestamp hugging the snapshot's own generated_at is drift.
        if build_moment is not None and abs((mission_time - build_moment).total_seconds()) > _LIVE_MISSION_RESTAMP_EPSILON_SECONDS:
            continue
        warnings.append(
            {
                "code": "persona_chat_history.live_mission_shadow",
                "entity_id": session_id,
                "detail": "mission chat-history row tracks snapshot build time and shadows every real chat for the persona",
            }
        )

    channels = data.get("operator_channels")
    if channels is None:
        warnings.append(
            {
                "code": "operator_channels_missing",
                "detail": "persona runtime is enabled but the Agent Console channel projection is absent",
            }
        )
    elif not isinstance(channels, dict):
        # S4: operator_channels is now an id-keyed map (channel_id -> row).
        warnings.append(
            {
                "code": "operator_channels_invalid",
                "detail": "operator_channels must be an id-keyed map; Launcher Agent Console cannot render this snapshot",
            }
        )
    else:
        # S4 (delete derived copies -> FK-miss reports): each operator channel
        # carries FK ids into the owner entities (persona_instances) rather than
        # restating them. A ``persona_instance_id`` that does not resolve in the
        # keyed persona_instances map is a typed, resolvable pointer miss — not a
        # cross-projection "contract error" reconciling two copies of a fact.
        # Archived channels reference archived (frame-evicted) instances by
        # design, so they are exempt from the live-roster FK check.
        live_instance_ids = {
            str(row.get("persona_instance_id") or "")
            for row in instances
            if isinstance(row, dict) and row.get("persona_instance_id")
        }
        for channel in section_rows(channels):
            if not isinstance(channel, dict):
                continue
            fk_target = str(channel.get("persona_instance_id") or "").strip()
            if (
                fk_target
                and str(channel.get("state") or "") != "archived"
                and fk_target not in live_instance_ids
            ):
                warnings.append(
                    {
                        "code": "fk_miss",
                        "from_entity": "operator_channel",
                        "from_id": channel.get("channel_id"),
                        "fk_field": "persona_instance_id",
                        "target_entity": "persona_instances",
                        "target_id": fk_target,
                        "detail": (
                            f"operator_channel '{channel.get('channel_id')}' "
                            f"persona_instance_id -> {fk_target} does not resolve in "
                            "persona_instances"
                        ),
                    }
                )
            for warning in channel.get("warnings") or []:
                if not isinstance(warning, dict):
                    continue
                code = str(warning.get("code") or "operator_channel_warning")
                warnings.append(
                    {
                        "code": f"operator_channel.{code}",
                        "entity_id": channel.get("channel_id"),
                        "detail": warning.get("detail") or "operator channel projection warning",
                    }
                )

    # B5 (2026-07-31): two more warnings stood here — ``open_tasks_without_task_rows``
    # (keyed on ``summary.open_tasks``) and ``open_incident_budget_exceeded``
    # (keyed on ``summary.open_incidents``, gated by the
    # ``open_incident_warning_threshold`` config knob). Neither key has existed
    # on ``summary`` since the mission-row removal (S9/contract 45) reduced the
    # block to ``persona_instances``, so both branches were unreachable by
    # construction: an operator tuning the threshold was tuning nothing, and the
    # Launcher's ``open_incident_budget_exceeded`` alert could never fire. The
    # config knob went with them. ``SnapshotSummary`` now declares the block's
    # field set so the next warning cannot be written against a field the
    # summary does not emit, and
    # ``tests/agent_runtime/test_parity_warning_catalog.py`` fails if any
    # warning code in this module stops being producible.
    return warnings


# A mission row anchored to its assignment's persisted created_at only matches
# the snapshot's own build moment in the transient poll right after assignment;
# a timestamp that hugs generated_at on every build is the restamping regression.
_LIVE_MISSION_RESTAMP_EPSILON_SECONDS = 10.0


def _parse_iso_timestamp(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _redaction_observed(value) -> dict[str, int]:
    counts: dict[str, int] = {}

    def visit(item) -> None:
        if isinstance(item, dict):
            marker = item.get("would_redact")
            if isinstance(marker, dict):
                for reason in marker.values():
                    key = str(reason or "unknown").strip() or "unknown"
                    counts[key] = counts.get(key, 0) + 1
            elif isinstance(marker, str) and marker.strip():
                key = marker.strip()
                counts[key] = counts.get(key, 0) + 1
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return counts


def _event_summary_warnings(events) -> list[dict]:
    warnings: list[dict] = []
    for event in events:
        try:
            missing = event_summary_missing(event)
        except Exception:
            missing = False
        if not missing:
            continue
        warnings.append(
            {
                "code": "event_summary_missing",
                "event_type": getattr(event, "type", None),
                "task_id": getattr(event, "task_id", None),
                "run_id": getattr(event, "run_id", None),
                "detail": "operator-visible event is missing a redaction-safe summary",
            }
        )
    return warnings
