"""``hermes harness workspace``: list, show, create, delete, use, rename, archive, roster.

Separate because the workspace store (``agent_runtime.store.WorkspaceStore``) is
one store with one verb family.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from hermes_time import now
from hermes_cli.profiles import list_profiles
from hermes_cli.flag_binding import list_flag_or_empty
from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
from agent_runtime.errors import NotFound, WorkspaceDeleteBlocked
from agent_runtime.realm_sync import sync_artifacts_for_workspace_agent
from agent_runtime.scope_activation import activate_workspace, workspace_row as _scope_workspace_row
from agent_runtime.store import RealmStore, WorkspaceStore
from hermes_cli.harness_support import (
    _list_envelope,
    _object_envelope,
    _print_stage42,
    _require_yes,
    _sort_rows,
    emit_harness_error,
)

from .realm_commands import _reconcile_active_workspace_to_realm

__layer__ = "lanes"
__all__ = [
    "_cmd_workspace_add_agent",
    "_cmd_workspace_archive",
    "_cmd_workspace_create",
    "_cmd_workspace_delete",
    "_cmd_workspace_list",
    "_cmd_workspace_remove_agent",
    "_cmd_workspace_rename",
    "_cmd_workspace_show",
    "_cmd_workspace_use",
    "_known_persona_ids",
    "_validate_roster_persona",
    "_workspace_agent_sync_warnings",
    "_workspace_row",
]


#: MOVED to `agent_runtime.scope_activation` by plan WS4, and imported back
#: under its old private name so every call site below is unchanged. The reason
#: is the second door: `runtime.workspace.use` answers with THIS row, and a row
#: the method lane could only reach by re-deriving would be the S48 twin all
#: over again. It is a re-key of `agent_runtime.snapshot._workspace_summary`, so
#: agent_runtime is where it always belonged.
_workspace_row = _scope_workspace_row


def _cmd_workspace_list(args) -> int:
    rows = [_workspace_row(item) for item in WorkspaceStore().list_all()]
    _print_stage42(_list_envelope("workspace", _sort_rows(rows, getattr(args, "sort", None))), args=args)
    return 0


def _cmd_workspace_show(args) -> int:
    item = WorkspaceStore().get(args.workspace_id)
    _print_stage42(_object_envelope("workspace", _workspace_row(item, full=True)), args=args)
    return 0


def _cmd_workspace_create(args) -> int:
    from agent_runtime.workspace_template import (
        CONTENT_COPY_SCOPES,
        copy_workspace_content,
        normalize_copy_scopes,
    )

    template = None
    scopes: tuple[str, ...] = ()
    if getattr(args, "from_workspace", None):
        try:
            template = WorkspaceStore().get(args.from_workspace)
        except NotFound as exc:
            return emit_harness_error(exc, args=args, code="template_workspace_not_found")
        scopes = normalize_copy_scopes(getattr(args, "copy", None))
    elif getattr(args, "copy", None):
        return emit_harness_error(
            ValueError("--copy requires --from-workspace"), args=args, code="invalid_request"
        )
    if getattr(args, "dry_run", False):
        row = {"id": f"ws_dry_{uuid.uuid4().hex[:6]}", "name": args.name, "realm_id": args.realm, "agents": len(list_flag_or_empty(args, "agent")), "goals": 0, "isolation": args.isolation or "soft", "updated_at": now()}
        if template is not None:
            row["template_workspace_id"] = template.id
            row["copy_scopes"] = list(scopes)
        _print_stage42(_object_envelope("workspace", row), args=args, default_output="json")
        return 0
    if args.realm:
        RealmStore().get(args.realm)
    # Template settings/roster feed the create itself; explicit flags always
    # win over the template so the operator can override any copied field.
    agent_ids = list_flag_or_empty(args, "agent")
    blueprint = args.blueprint
    isolation = args.isolation
    max_lanes = args.max_lanes
    if template is not None:
        if "agents" in scopes and not agent_ids:
            agent_ids = list(template.agent_ids or [])
        if "settings" in scopes:
            if blueprint is None:
                blueprint = template.default_blueprint_id
            if isolation is None:
                isolation = template.isolation
            if max_lanes is None:
                max_lanes = template.max_concurrent_lanes
    item = WorkspaceStore().create(
        name=args.name,
        agent_ids=agent_ids,
        default_blueprint_id=blueprint,
        isolation=isolation or "soft",
        max_concurrent_lanes=max_lanes,
        realm_id=args.realm,
    )
    if args.realm:
        realm = RealmStore().get(args.realm)
        if item.id not in realm.workspace_ids:
            realm.workspace_ids.append(item.id)
            RealmStore().save(realm)
    # Office/board content copies AFTER the workspace exists, through the
    # store chokepoints, so every copied artifact rides its contract event.
    warnings: list[dict] = []
    copied = None
    if template is not None:
        content_scopes = tuple(scope for scope in scopes if scope in CONTENT_COPY_SCOPES)
        if content_scopes:
            outcome = copy_workspace_content(template.id, item.id, scopes=content_scopes)
            copied = outcome["copied"]
            warnings.extend(outcome["warnings"])
    # A workspace created inside the ACTIVE realm becomes active
    # immediately — the operator expects to land in the workspace they
    # just created, not to run a second `workspace use` by hand.
    # (workspace.created / workspace.activated are emitted by the store
    # chokepoint — Stage 12.)
    if item.realm_id and item.realm_id == RealmStore().active_id():
        WorkspaceStore().set_active(item.id)
    row = _workspace_row(item)
    if template is not None:
        row["template_workspace_id"] = template.id
        row["copy_scopes"] = list(scopes)
        if copied is not None:
            row["copied"] = copied
    _print_stage42(_object_envelope("workspace", row, warnings=warnings), args=args, default_output="json")
    return 0


def _cmd_workspace_delete(args) -> int:
    if not _require_yes(args):
        return 8
    store = WorkspaceStore()
    try:
        item = store.get(args.workspace_id)
    except NotFound as exc:
        return emit_harness_error(exc, args=args)
    if getattr(args, "dry_run", False):
        row = _workspace_row(item, full=True)
        row["deleted"] = False
        row["dry_run"] = True
        _print_stage42(_object_envelope("workspace", row), args=args, default_output="json")
        return 0
    was_active = store.active_id() == item.id
    realm_id = item.realm_id
    try:
        row = store.delete(args.workspace_id)
    except WorkspaceDeleteBlocked as exc:
        return emit_harness_error(exc, args=args, code=exc.code)
    # Deleting the ACTIVE workspace falls back to the realm's default (same
    # reconcile rule as a realm switch) instead of leaving the operator on a
    # cleared pointer.
    if was_active and realm_id:
        try:
            _reconcile_active_workspace_to_realm(RealmStore().get(realm_id))
        except Exception:  # noqa: BLE001 — pointer reconcile is best-effort; the delete already landed
            pass
    _print_stage42(_object_envelope("workspace", row), args=args, default_output="json")
    return 0


def _cmd_workspace_use(args) -> int:
    # The DECISION is `agent_runtime.scope_activation`'s, not this handler's —
    # `runtime.workspace.use` reaches the same function, so the argv verb and
    # the method lane cannot drift about what `applied` / `superseded` /
    # `duplicate` mean (plan WS4). All that is left here is the envelope.
    row = activate_workspace(args.workspace_id, issued_at=getattr(args, "issued_at", None))
    _print_stage42(_object_envelope("workspace", row), args=args, default_output="json")
    return 0


def _known_persona_ids() -> set[str]:
    """Persona definition ids across every `.hermes` profile (Add-agent source)."""
    known: set[str] = set()
    for profile in list_profiles():
        try:
            personas = ensure_persisted_personas(load_agent_runtime_config(Path(profile.path) / "config.yaml"))
        except Exception:
            continue
        known.update(persona.id for persona in personas)
    try:
        known.update(persona.id for persona in ensure_persisted_personas(load_agent_runtime_config()))
    except Exception:
        pass
    return known


def _validate_roster_persona(persona_id: str) -> None:
    """Reject an unknown persona before it pollutes a workspace roster.

    Adding an agent is meant to sync that agent's skills/soul/memory/context —
    a non-existent persona has none, so this must fail rather than silently
    persist garbage (`persona_not_found`, exit 3).
    """
    if persona_id not in _known_persona_ids():
        raise NotFound(f"persona not found: {persona_id}")


def _cmd_workspace_add_agent(args) -> int:
    try:
        _validate_roster_persona(args.persona_id)
    except NotFound as exc:
        return emit_harness_error(exc, args=args, code="persona_not_found")
    if getattr(args, "dry_run", False):
        item = WorkspaceStore().get(args.workspace_id)
        row = _workspace_row(item)
        roster_agent_ids = list(dict.fromkeys([*item.agent_ids, args.persona_id]))
        row["roster_agent_ids"] = roster_agent_ids
        row["roster_agent_count"] = len(roster_agent_ids)
        warnings = _workspace_agent_sync_warnings(item.id, args.persona_id)
        _print_stage42(_object_envelope("workspace", row, warnings=warnings), args=args, default_output="json")
        return 0
    item = WorkspaceStore().add_agent(args.workspace_id, args.persona_id)
    warnings = _workspace_agent_sync_warnings(item.id, args.persona_id)
    _print_stage42(_object_envelope("workspace", _workspace_row(item), warnings=warnings), args=args, default_output="json")
    return 0


def _workspace_agent_sync_warnings(workspace_id: str, persona_id: str) -> list[dict]:
    artifacts = sync_artifacts_for_workspace_agent(workspace_id, persona_id)
    if not artifacts:
        return []
    return [
        {
            "code": "realm_sync_set_updated",
            "message": "Workspace agent artifacts are now included in the realm sync allowlist.",
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }
    ]


def _cmd_workspace_remove_agent(args) -> int:
    if not _require_yes(args):
        return 8
    if getattr(args, "dry_run", False):
        item = WorkspaceStore().get(args.workspace_id)
    else:
        item = WorkspaceStore().remove_agent(args.workspace_id, args.persona_id)
    _print_stage42(_object_envelope("workspace", _workspace_row(item)), args=args, default_output="json")
    return 0


def _cmd_workspace_rename(args) -> int:
    if getattr(args, "dry_run", False):
        item = WorkspaceStore().get(args.workspace_id)
    else:
        item = WorkspaceStore().rename(args.workspace_id, args.name)
    row = _workspace_row(item)
    if getattr(args, "dry_run", False):
        row["name"] = args.name
    _print_stage42(_object_envelope("workspace", row), args=args, default_output="json")
    return 0


def _cmd_workspace_archive(args) -> int:
    if not _require_yes(args):
        return 8
    if getattr(args, "dry_run", False):
        item = WorkspaceStore().get(args.workspace_id)
    else:
        item = WorkspaceStore().archive(args.workspace_id)
    _print_stage42(_object_envelope("workspace", _workspace_row(item, full=True)), args=args, default_output="json")
    return 0
