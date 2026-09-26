"""Read-only persona verbs: list, show, tool-diff, and the permission/assignment views.

Separate because nothing here writes a chat or starts a turn; the one write
(``permission set`` and the assignment task-id migration) is a store call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from agent_runtime.cli_format import emit_json
from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
from agent_runtime.mcp_admission import LANE_MISSION_CHAT, resolve_mcp_admission
from agent_runtime.mcp_lane import HARNESS_LANE
from agent_runtime.mission_chat_workdir import mission_chat_workdir_for_persona
from agent_runtime.persona_assignments import (
    PersonaAssignmentStore,
    PersonaInstanceStore,
    migrate_retired_persona_assignment_task_ids,
    normalize_persona_id as _normalize_cli_persona_id,
    persona_assignment_summary,
    persona_instance_id_for,
    persona_instance_summary,
)
from agent_runtime.chat_lane_bundle import chat_lane_capability_drops
from agent_runtime.tool_permissions import (
    ChatToolPermissionStore,
    default_permission_mode,
    permission_state_for_chat,
)
from agent_runtime.tool_visibility import ToolVisibilityOptions, resolve_tool_visibility
from hermes_cli.harness_support import emit_harness_error
from .chat_target import _persona_by_id

__layer__ = "lanes"
__all__ = [
    "_cmd_persona_assignment_task_id_migration",
    "_cmd_persona_assignments",
    "_cmd_persona_instance_detail",
    "_cmd_persona_list",
    "_cmd_persona_permission_set",
    "_cmd_persona_show",
    "_cmd_persona_tool_diff",
]


def _cmd_persona_list(args) -> int:
    cfg = load_agent_runtime_config()
    store = PersonaInstanceStore()
    personas = ensure_persisted_personas(cfg)
    personas_by_id = {str(getattr(persona, "id", "") or ""): persona for persona in personas}
    # S56 made the roster unconditional; the two `enterprise_worker_sessions`
    # gates went with the block, and S56 kept `feature_enabled` /
    # `assignment_store_enabled` on the reply "so operator tooling that reads
    # them keeps parsing". A 2026-08-31 trace found no such reader: not in this
    # repo (the only other `feature_enabled` is skills-sync's, a different key
    # on a different reply) and not in the launcher, whose `lib/` never names
    # either and whose CLI contract dump covers argv only. Both were therefore
    # constants that no one read and that could only ever say `true` — the same
    # always-true shape AX2 took off the snapshot wire in `s76` — so they are
    # gone from this reply too. The keys a caller actually branches on (`ok`,
    # the rows) are untouched.
    instances = store.ensure_for_personas(personas)
    data = {
        "persona_instances": [
            persona_instance_summary(
                instance,
                personas_by_id.get(str(getattr(instance, "persona_id", "") or "")),
                roster=ensure_persisted_personas,
            )
            for instance in instances
        ],
    }
    if args.json:
        print(emit_json(data))
    else:
        for instance in data["persona_instances"]:
            print(f"{instance['persona_instance_id']}: {instance['display_name']} state={instance['state']} assignment={instance['current_assignment_id'] or '-'}")
    return 0


def _cmd_persona_show(args) -> int:
    cfg = load_agent_runtime_config()
    store = PersonaInstanceStore()
    personas = ensure_persisted_personas(cfg)
    personas_by_id = {str(getattr(persona, "id", "") or ""): persona for persona in personas}
    store.ensure_for_personas(personas)
    value = str(args.persona_id_or_instance_id or "").strip()
    instance_id = value if value.startswith("personainst_") else persona_instance_id_for(_normalize_cli_persona_id(value))
    try:
        instance = store.get(instance_id)
    except Exception:
        data = {"ok": False, "error": f"persona instance not found: {value}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    assignments = PersonaAssignmentStore().list_for_persona(instance.persona_id)
    data = {
        "ok": True,
        "persona_instance": persona_instance_summary(
            instance,
            personas_by_id.get(str(getattr(instance, "persona_id", "") or "")),
            roster=ensure_persisted_personas,
        ),
        "assignments": [persona_assignment_summary(item) for item in assignments[-25:]],
    }
    if args.json:
        print(emit_json(data))
    else:
        summary = data["persona_instance"]
        print(f"{summary['persona_instance_id']}: {summary['display_name']} state={summary['state']}")
    return 0


def _cmd_persona_tool_diff(args) -> int:
    cfg = load_agent_runtime_config()
    persona = _persona_by_id(cfg, str(args.persona_id or ""))
    if persona is None:
        data = {"ok": False, "error": f"persona not found: {args.persona_id}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    # No flag ⇒ the RUNTIME DEFAULT, so the preview describes what a real turn
    # gets. Hardcoding ``profile_default`` here would have made every preview
    # report the bounded shape while every turn ran under the configured default.
    permission_mode = str(args.permission_mode or "").strip() or default_permission_mode()
    visibility = resolve_tool_visibility(
        persona,
        ToolVisibilityOptions(
            permission_mode=permission_mode,
            permission_source="cli_preview",
            repo_scope=args.repo_scope,
            workdir=args.workdir,
            session_id=args.session_id,
            # S27: no ``task_id``/``goal_id``. Their ``--task``/``--goal`` flags
            # were the only writers and nothing emitted them (the Launcher's
            # permission-preview argv never carried either), so this preview
            # could only ever correlate against a mission record deleted in S8.
            # The fields themselves stay on ToolVisibilityOptions -- the CHAT
            # lane fills them from the live persona-instance row.
            # This command IS the harness lane; say so rather than letting the
            # lane be inferred from argv.
            entry_point_lane=HARNESS_LANE,
            # G5: account for what the CHAT lane takes AWAY from this persona,
            # under the mode the operator is asking about (``--permission-mode
            # unbounded`` genuinely bypasses the cost policy and so honestly
            # reports no drops). Accounting only — the resolved tool list is
            # unchanged; these rows explain absences it would otherwise show as
            # nothing at all.
            chat_lane_capability_drops=chat_lane_capability_drops(
                persona,
                session_id=args.session_id,
                permission_mode=permission_mode,
            ),
            mission_chat_workdir=mission_chat_workdir_for_persona(persona),
        ),
    )
    data = {"ok": True, "tool_visibility": visibility}
    # Inspection only: resolve_mcp_admission is pure policy — it never connects
    # to or registers an MCP server — so an operator can read exactly what a
    # persona WOULD be admitted before the kill switch is ever flipped.
    if getattr(args, "explain_mcp", False):
        data["mcp_admission"] = resolve_mcp_admission(
            persona,
            lane=LANE_MISSION_CHAT,
            permission_mode=permission_mode,
        ).explain()
    # Same shape, same guarantee, the other gate: what the TERMINAL safety
    # envelope will do to this persona's mission-chat lane. Rendered entirely
    # from the canonical envelope authorities (``explain_terminal_envelope`` +
    # ``hard_floor_command_classes``) — no parallel derivation of the taxonomy,
    # the stage floor, or the grant table lives here.
    if getattr(args, "explain_envelope", False):
        from agent_runtime.terminal_envelope_explain import (
            explain_persona_terminal_envelope,
        )

        data["terminal_envelope"] = explain_persona_terminal_envelope(
            persona, session_id=args.session_id, permission_mode=permission_mode
        )
    if args.json:
        print(emit_json(data))
    else:
        print(f"{visibility['persona_id']}: {visibility['final_tool_count']} tools")
        # S0a A2: say WHERE the capability came from. Before this, an operator
        # reading a preview had no way to tell a profile declaration from the
        # lane default — or to see that the persona-level ``toolsets`` list in
        # the config/store was being ignored.
        declaration = visibility.get("toolset_declaration") or {}
        if declaration:
            declared = ", ".join(declaration.get("declared") or []) or "-"
            where = declaration.get("config_path") or "no profile config"
            print(f"toolsets: {declared} ({declaration.get('source')}, {where})")
            persona_list = declaration.get("persona_list") or []
            if persona_list:
                print(
                    "persona-level toolsets list ignored (legacy; delete it from "
                    f"agent_runtime.personas.{visibility['persona_id']}.toolsets): "
                    + ", ".join(persona_list)
                )
        envelope = data.get("terminal_envelope")
        if envelope is not None:
            from agent_runtime.terminal_envelope_explain import (
                render_terminal_envelope_explanation,
            )

            for line in render_terminal_envelope_explanation(envelope):
                print(line)
        admission = data.get("mcp_admission")
        if admission is not None:
            print(
                f"mcp admission ({admission['lane']}, role={admission['role']}, "
                f"mode={admission['permission_mode']}): "
                f"{'enabled' if admission['enabled'] else 'DISABLED'}"
            )
            print(f"  requested: {', '.join(admission['requested']) or '-'}")
            print(f"  admitted:  {', '.join(admission['admitted']) or '-'}")
            # What would actually REGISTER. An empty include is the launcher's
            # full-capability glob ("everything this server advertises"), not an
            # empty admission — say which, or the operator has to infer it.
            for server, include in sorted((admission.get("tool_include") or {}).items()):
                shape = (
                    f"{len(include)} tool(s): {', '.join(include)}"
                    if include
                    else "every tool the server advertises (no include filter)"
                )
                print(f"  include {server}: {shape}")
            for row in admission["denied"]:
                print(f"  denied {row['server']} ({row['code']}): {row['summary']}")
        if visibility["blocked_tools"]:
            print("blocked:")
            for item in visibility["blocked_tools"]:
                print(f"  {item['name']} ({item['reason']})")
        # A declared-but-unregistered capability is a real gap in what this
        # persona can do here. Printing it beside the tool count is what stops
        # the count from being read as the whole story.
        for failure in visibility.get("requirement_failures") or []:
            print(f"requirement failure: {failure.get('code')}")
            print(f"  {failure.get('summary')}")
            if failure.get("fix_hint"):
                print(f"  fix: {failure['fix_hint']}")
    return 0


def _cmd_persona_permission_set(args) -> int:
    cfg = load_agent_runtime_config()
    persona = _persona_by_id(cfg, str(args.persona_id or ""))
    if persona is None:
        data = {"ok": False, "error": f"persona not found: {args.persona_id}"}
        print(emit_json(data) if args.json else data["error"])
        return 2
    expires_at = str(args.expires_at or "").strip() or None
    ttl_seconds = getattr(args, "ttl_seconds", None)
    if expires_at is None and ttl_seconds is not None and ttl_seconds > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
    record = ChatToolPermissionStore().set(
        persona_id=persona.id,
        session_id=str(args.session_id or ""),
        mode=str(args.mode or "profile_default"),
        reason=str(args.reason or ""),
        source="operator",
        expires_at=expires_at,
        turns_remaining=getattr(args, "turns", None),
    )
    data = {
        "ok": True,
        "permission": {
            "persona_id": record.persona_id,
            "session_id": record.session_id,
            "mode": record.mode,
            "reason": record.reason,
            "source": record.source,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at or None,
            "turns_remaining": record.turns_remaining,
        },
        "permission_state": permission_state_for_chat(persona, session_id=record.session_id),
    }
    if args.json:
        print(emit_json(data))
    else:
        print(f"{record.persona_id}: {record.session_id} mode={record.mode}")
    return 0


def _cmd_persona_assignments(args) -> int:
    cfg = load_agent_runtime_config()
    store = PersonaAssignmentStore()
    if args.persona_id:
        assignments = store.list_for_persona(_normalize_cli_persona_id(args.persona_id))
    else:
        assignments = store.list_all()
    data = {
        "ok": True,
        "assignments": [persona_assignment_summary(item) for item in assignments],
    }
    if args.json:
        print(emit_json(data))
    else:
        for item in data["assignments"]:
            print(f"{item['assignment_id']}: {item['persona_id']} {item['kind']} state={item['state']} task={item['task_id'] or '-'}")
    return 0


def _cmd_persona_assignment_task_id_migration(args) -> int:
    data = migrate_retired_persona_assignment_task_ids(
        dry_run=bool(getattr(args, "dry_run", False))
    )
    if args.json:
        print(emit_json(data))
    else:
        mode = "preview" if data["dry_run"] else "apply"
        print(
            f"assignment task-id migration {mode}: scanned={data['scanned']} "
            f"eligible={data['eligible']} archived={data['archived']} "
            f"held={len(data['held'])}"
        )
    return 0 if data["ok"] else 2


def _cmd_persona_instance_detail(args) -> int:
    """Serve the persona-instance tool detail evicted from the frame (residue-slim
    R2), rebuilt read-only from the stores so the launcher's visibility dialog
    fetches identical bytes on open. A miss is an honest ``not_found``, never a
    fabricated empty payload."""

    from agent_runtime.snapshot.details import persona_instance_detail_for_id

    entity_id = str(getattr(args, "instance_id", "") or "")
    detail = persona_instance_detail_for_id(entity_id)
    if detail is None:
        return emit_harness_error(
            ValueError(f"persona-instance '{entity_id}' did not resolve"),
            args=args,
            code="not_found",
        )
    print(emit_json(detail))
    return 0
