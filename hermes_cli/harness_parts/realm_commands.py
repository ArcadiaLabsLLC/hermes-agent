"""``hermes harness realm``: realm rows, activation, and the realm-sync verbs.

Separate because realm sync (``agent_runtime.realm_sync``) is its own lane with
its own credential and selection envelopes.
"""

from __future__ import annotations


import uuid

from hermes_time import now
from hermes_cli.flag_binding import list_flag_or_empty
from agent_runtime.default_scope import (
    preview_default_scope_migration,
    reconcile_default_scope_to_legacy,
)
from agent_runtime.errors import NotFound
from agent_runtime.root_observability import attach_root_observability
from agent_runtime import realm_verbs
from agent_runtime.realm_sync import RealmSyncError
from agent_runtime.scope_activation import (
    activate_realm,
    realm_row as _scope_realm_row,
    reconcile_active_workspace_to_realm as _scope_reconcile_active_workspace_to_realm,
)
from agent_runtime.store import RealmStore
from hermes_cli.harness_support import (
    _list_envelope,
    _object_envelope,
    _print_stage42,
    _require_yes,
    _sort_rows,
    emit_harness_error,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_realm_adopt",
    "_cmd_realm_agents_set",
    "_cmd_realm_agents_show",
    "_cmd_realm_bind_server",
    "_cmd_realm_create",
    "_cmd_realm_default_scope",
    "_cmd_realm_list",
    "_cmd_realm_show",
    "_cmd_realm_skills_set",
    "_cmd_realm_skills_show",
    "_cmd_realm_sync_held",
    "_cmd_realm_sync_history",
    "_cmd_realm_sync_publish",
    "_cmd_realm_sync_pull",
    "_cmd_realm_sync_resolve",
    "_cmd_realm_sync_revert",
    "_cmd_realm_sync_status",
    "_cmd_realm_use",
    "_realm_agent_selection_envelope",
    "_realm_row",
    "_realm_skill_selection_envelope",
    "_realm_sync_credential",
    "_realm_sync_subtree",
    "_reconcile_active_workspace_to_realm",
]


#: MOVED to `agent_runtime.scope_activation` with `_workspace_row`, for the same
#: reason and in the same landing — see the note there.
_realm_row = _scope_realm_row


def _cmd_realm_list(args) -> int:
    rows = [_realm_row(item) for item in RealmStore().list_all()]
    _print_stage42(_list_envelope("realm", _sort_rows(rows, getattr(args, "sort", None))), args=args)
    return 0


def _cmd_realm_show(args) -> int:
    item = RealmStore().get(args.realm_id)
    _print_stage42(_object_envelope("realm", _realm_row(item, full=True)), args=args)
    return 0


def _cmd_realm_create(args) -> int:
    if getattr(args, "dry_run", False):
        row = {"id": f"realm_dry_{uuid.uuid4().hex[:6]}", "name": args.name, "server_id": args.server, "workspaces": 0, "sync": None, "updated_at": now()}
        _print_stage42(_object_envelope("realm", row), args=args, default_output="json")
        return 0
    item = RealmStore().create(name=args.name, server_id=args.server)
    _print_stage42(_object_envelope("realm", _realm_row(item)), args=args, default_output="json")
    return 0


def _cmd_realm_bind_server(args) -> int:
    if getattr(args, "dry_run", False):
        item = RealmStore().get(args.realm_id)
    else:
        item = RealmStore().bind_server(args.realm_id, args.server_id)
    row = _realm_row(item)
    if getattr(args, "dry_run", False):
        row["server_id"] = args.server_id
    _print_stage42(_object_envelope("realm", row), args=args, default_output="json")
    return 0


def _cmd_realm_use(args) -> int:
    # Same shared decision as `_cmd_workspace_use`, reconcile included — see
    # `agent_runtime.scope_activation.activate_realm` for why the workspace
    # reconcile lives inside the shared function rather than at each door.
    row = activate_realm(args.realm_id, issued_at=getattr(args, "issued_at", None))
    _print_stage42(_object_envelope("realm", row), args=args, default_output="json")
    return 0


def _cmd_realm_default_scope(args) -> int:
    if getattr(args, "dry_run", False):
        _print_stage42(
            preview_default_scope_migration(),
            args=args,
            default_output="json",
        )
        return 0
    if not getattr(args, "yes", False):
        return emit_harness_error(
            ValueError("default-scope reconciliation requires --dry-run or --yes"),
            args=args,
            code="confirmation_required",
        )
    winner_realm_id = str(getattr(args, "winner_realm", "") or "").strip()
    winner_workspace_id = str(
        getattr(args, "winner_workspace", "") or ""
    ).strip()
    if not winner_realm_id or not winner_workspace_id:
        return emit_harness_error(
            ValueError("--winner-realm and --winner-workspace are required with --yes"),
            args=args,
            code="invalid_request",
        )
    _print_stage42(
        reconcile_default_scope_to_legacy(
            winner_realm_id=winner_realm_id,
            winner_workspace_id=winner_workspace_id,
        ),
        args=args,
        default_output="json",
    )
    return 0


#: MOVED to `agent_runtime.scope_activation` (plan WS4): `activate_realm` calls
#: it, so the reconcile happens on BOTH doors by construction rather than
#: because each door remembered. `_cmd_workspace_delete` still calls it
#: directly — a delete of the active workspace reconciles for the same reason a
#: realm switch does, and that is not an activation.
_reconcile_active_workspace_to_realm = _scope_reconcile_active_workspace_to_realm


def _realm_sync_credential(args):
    """Parse the launcher-brokered credential from --credential-file or the
    HERMES_REALM_SYNC_CREDENTIAL env fallback; None when neither is set."""
    from agent_runtime.realm_membership import load_realm_sync_credential

    return load_realm_sync_credential(getattr(args, "credential_file", None))


def _cmd_realm_adopt(args) -> int:
    try:
        data = realm_verbs.realm_adopt(
            _realm_sync_credential(args),
            server_id=getattr(args, "server", None),
            dry_run=bool(getattr(args, "dry_run", False)),
            sort=getattr(args, "sort", None),
        )
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


def _cmd_realm_sync_status(args) -> int:
    try:
        data = realm_verbs.realm_sync_status(args.realm_id, credential=_realm_sync_credential(args))
    except NotFound as exc:
        # An unknown realm id is an ARGUMENT error, not a crash — and the store's
        # message is the realm JSON's ABSOLUTE PATH, which the error contract
        # forbids on an operator-visible surface.
        return emit_harness_error(exc, args=args, code="not_found")
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


def _cmd_realm_sync_history(args) -> int:
    """H1: the realm's published versions from the local clone — read-only, no fetch, no credential."""
    from agent_runtime.realm_sync.history import realm_sync_history

    try:
        data = realm_sync_history(args.realm_id, limit=getattr(args, "limit", 50))
    except NotFound as exc:
        return emit_harness_error(exc, args=args, code="not_found")
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    # An empty history from the wrong root reads as "never published" — the
    # envelope says which root answered.
    _print_stage42(attach_root_observability(data), args=args, default_output="json")
    return 0


def _cmd_realm_sync_pull(args) -> int:
    try:
        data = realm_verbs.realm_sync_pull(
            args.realm_id, credential=_realm_sync_credential(args), dry_run=bool(getattr(args, "dry_run", False))
        )
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


def _cmd_realm_sync_publish(args) -> int:
    if not _require_yes(args):
        return 8
    try:
        data = realm_verbs.realm_sync_publish(
            args.realm_id, credential=_realm_sync_credential(args), dry_run=bool(getattr(args, "dry_run", False))
        )
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


#: MOVED to ``agent_runtime.realm_verbs`` with the resolve verb that reads it.
_realm_sync_subtree = realm_verbs.realm_sync_subtree


def _cmd_realm_sync_held(args) -> int:
    """Everything this realm is holding because BOTH sides changed.

    TWO kinds in one list since 2026-09-12, distinguished by the row's own
    ``kind``: ``profile_artifact_hold`` (a profile FILE) and ``skill_hold`` (a
    skill PACKAGE). They belong in one verb because they are one question — "what
    is waiting on me to choose a direction" — and both are resolved by the same
    ``realm sync resolve --key … --take local|remote``. The list envelope's
    ``item_kind`` stays ``profile_artifact_hold`` so an existing reader keys off
    the same string it always did; read the per-row ``kind``.
    """

    from agent_runtime.profile_artifact_sync import apply_profile_artifact_pull
    from agent_runtime.realm_sync import _held_skill_packages_for_realm
    from agent_runtime.skill_sync import skill_baseline_key

    summary = apply_profile_artifact_pull(args.realm_id, _realm_sync_subtree(args.realm_id), dry_run=True)
    rows = [
        {"id": key, "kind": "profile_artifact_hold", "realm_id": args.realm_id, "take_hint": "--take local|remote"}
        for key in sorted(set(summary.held))
    ]
    realm = RealmStore().get(args.realm_id)
    rows.extend(
        {
            "id": skill_baseline_key(slug),
            "kind": "skill_hold",
            "realm_id": args.realm_id,
            "skill": slug,
            "take_hint": "--take local|remote",
        }
        for slug in _held_skill_packages_for_realm(realm)
    )
    _print_stage42(_list_envelope("profile_artifact_hold", rows), args=args, default_output="json")
    return 0


def _cmd_realm_sync_resolve(args) -> int:
    """Resolve ONE hold — a profile file, or (since 2026-09-12) a skill package.

    Dispatched on the KEY (``skill::<slug>`` vs ``<profile>:<path>``) inside
    ``agent_runtime.realm_verbs.realm_sync_resolve``. ``--yes``-gated, and
    ``--dry-run`` writes nothing; either take records the realm's hash as the
    new baseline (``skill_sync.resolve_held_skill`` says why ``--take local``
    writing nothing is the whole point).
    """

    from agent_runtime.profile_artifact_sync import ProfileArtifactResolveError
    from agent_runtime.skill_sync import SkillResolveError

    if not _require_yes(args):
        return 8
    try:
        envelope = realm_verbs.realm_sync_resolve(
            args.realm_id, key=args.key, take=args.take, dry_run=bool(getattr(args, "dry_run", False))
        )
    except (SkillResolveError, ProfileArtifactResolveError) as exc:
        return emit_harness_error(exc, args=args, code=exc.code)
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _cmd_realm_sync_revert(args) -> int:
    """`realm sync revert` — the SECOND exit from unpublished local changes.

    Gated on ``--yes`` like publish/resolve: destructive of LOCAL state
    (archive-never-delete, so recoverable, but the operator still has to mean
    it). Local-only — no ``--credential-file``; the upstream it reverts to is the
    subtree the last pull put on disk. ``--to <sha>`` restores one published
    version and writes no baseline.
    """

    if not _require_yes(args):
        return 8
    try:
        envelope = realm_verbs.realm_sync_revert(
            args.realm_id,
            items=list_flag_or_empty(args, "items"),
            revert_all=bool(getattr(args, "revert_all", False)),
            to=getattr(args, "to", None),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(envelope, args=args, default_output="json")
    return 0


#: MOVED to ``agent_runtime.realm_verbs`` (lane h-twins): the method twins
#: ``runtime.realm.skills.*`` / ``runtime.realm.agents.*`` render the same
#: envelopes, so they are built once below both doors.
_realm_skill_selection_envelope = realm_verbs.realm_skill_selection_envelope
_realm_agent_selection_envelope = realm_verbs.realm_agent_selection_envelope


def _cmd_realm_skills_show(args) -> int:
    _print_stage42(realm_verbs.realm_skills_show(args.realm_id), args=args, default_output="json")
    return 0


def _split_selection(text: str | None) -> list[str] | None:
    """``--skills a,b`` / ``--agents a,b``: None when the flag was not given."""
    return None if text is None else [item.strip() for item in str(text).split(",") if item.strip()]


def _cmd_realm_skills_set(args) -> int:
    try:
        envelope = realm_verbs.realm_skills_set(
            args.realm_id,
            publish_all=bool(args.publish_all),
            skills=_split_selection(args.skills),
            publish_none=bool(args.publish_none),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except realm_verbs.RealmSelectionInvalid as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _cmd_realm_agents_show(args) -> int:
    # RealmStore lookup occurs inside the state resolver, so a missing id keeps
    # the same typed command error behavior as every other Realm read verb.
    _print_stage42(realm_verbs.realm_agents_show(args.realm_id), args=args, default_output="json")
    return 0


def _cmd_realm_agents_set(args) -> int:
    try:
        envelope = realm_verbs.realm_agents_set(
            args.realm_id,
            publish_workspace=bool(args.publish_workspace),
            agents=_split_selection(args.agents),
            publish_none=bool(args.publish_none),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except realm_verbs.RealmSelectionInvalid as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    _print_stage42(envelope, args=args, default_output="json")
    return 0
