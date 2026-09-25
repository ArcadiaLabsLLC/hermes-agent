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
from agent_runtime.realm_sync import (
    RealmSyncError,
    publish_realm_sync,
    pull_realm_sync,
    realm_agent_selection_state,
    realm_sync_status,
    skill_tombstone_rows,
)
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
    "_SELECTION_MODES",
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
    "selection_from_args",
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
    from agent_runtime.realm_membership import adopt_realms

    try:
        credential = _realm_sync_credential(args)
        if credential is None:
            raise RealmSyncError(
                "sync_auth_failed",
                "realm adopt requires a launcher-brokered credential; pass --credential-file or set HERMES_REALM_SYNC_CREDENTIAL.",
            )
        adopted = adopt_realms(credential, server_id=getattr(args, "server", None), dry_run=bool(getattr(args, "dry_run", False)))
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    rows = [_realm_row(item) for item in adopted]
    _print_stage42(_list_envelope("realm", _sort_rows(rows, getattr(args, "sort", None))), args=args, default_output="json")
    return 0


def _cmd_realm_sync_status(args) -> int:
    try:
        data = realm_sync_status(args.realm_id, credential=_realm_sync_credential(args))
    except NotFound as exc:
        # An unknown realm id is an ARGUMENT error, not a crash. Without this the
        # store's NotFound escaped the handler uncaught, and the operator got a
        # traceback whose message is the ABSOLUTE PATH of the realm JSON — the
        # one thing the error contract forbids on an operator-visible surface.
        # The sibling verbs that read a realm by id already catch it exactly
        # here (``_cmd_realm_skill_restore``); this one did not, and the response
        # fixture for the case is what made that visible.
        return emit_harness_error(exc, args=args, code="not_found")
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


def _cmd_realm_sync_pull(args) -> int:
    try:
        data = pull_realm_sync(args.realm_id, dry_run=bool(getattr(args, "dry_run", False)), credential=_realm_sync_credential(args))
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


def _cmd_realm_sync_publish(args) -> int:
    if not _require_yes(args):
        return 8
    try:
        data = publish_realm_sync(args.realm_id, dry_run=bool(getattr(args, "dry_run", False)), credential=_realm_sync_credential(args))
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    _print_stage42(data, args=args, default_output="json")
    return 0


def _realm_sync_subtree(realm_id: str):
    """The checked-out realm subtree the profile-file lane reconciles against.

    Read-only: never clones, never fetches, never mutates the repo — the resolve
    verb operates on what the last pull already put on disk.
    """
    from agent_runtime.realm_sync import _realm_subtree, _sync_repo_path

    realm = RealmStore().get(realm_id)
    return _realm_subtree(_sync_repo_path(realm), realm.id)


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

    Dispatched on the KEY, not on a new flag or a new verb: a skill key is
    ``skill::<slug>`` and a profile-file key is ``<profile>:<path>``, so the
    doubled colon is unambiguous and an operator (or the launcher) uses the id the
    ``held`` row and the drift row already carry. Both arms are ``--yes``-gated,
    both honour ``--dry-run`` by writing nothing at all, and both record the
    realm's hash as the new baseline on EITHER take — see
    ``skill_sync.resolve_held_skill`` for why ``--take local`` writing nothing is
    the whole point.
    """

    from agent_runtime.profile_artifact_sync import (
        ProfileArtifactResolveError,
        resolve_profile_artifact,
    )
    from agent_runtime.skill_sync import SKILL_KEY_PREFIX, SkillResolveError, resolve_held_skill

    if not _require_yes(args):
        return 8
    dry_run = bool(getattr(args, "dry_run", False))
    if str(args.key or "").startswith(SKILL_KEY_PREFIX):
        try:
            skill_row = resolve_held_skill(
                args.realm_id, args.key, take=args.take, dry_run=dry_run
            )
        except SkillResolveError as exc:
            return emit_harness_error(exc, args=args, code=exc.code)
        skill_envelope = _object_envelope("skill_hold", skill_row)
        if dry_run:
            skill_envelope["dry_run"] = True
        _print_stage42(skill_envelope, args=args, default_output="json")
        return 0
    try:
        row = resolve_profile_artifact(
            args.realm_id,
            _realm_sync_subtree(args.realm_id),
            args.key,
            take=args.take,
            dry_run=dry_run,
        )
    except ProfileArtifactResolveError as exc:
        return emit_harness_error(exc, args=args, code=exc.code)
    envelope = _object_envelope("profile_artifact_hold", {"id": row["key"], **row})
    if dry_run:
        envelope["dry_run"] = True
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _cmd_realm_sync_revert(args) -> int:
    """`realm sync revert` — the SECOND exit from unpublished local changes.

    Gated on ``--yes`` like publish/resolve: it is destructive of LOCAL state
    (archive-never-delete, so recoverable, but the operator still has to mean
    it). Local-only — it takes no ``--credential-file``, because it never
    reaches the remote; the upstream it reverts to is the subtree the last pull
    already put on disk.
    """

    from agent_runtime.realm_revert import revert_realm_sync

    if not _require_yes(args):
        return 8
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        data = revert_realm_sync(
            args.realm_id,
            item_specs=list_flag_or_empty(args, "items"),
            revert_all=bool(getattr(args, "revert_all", False)),
            dry_run=dry_run,
        )
    except RealmSyncError as exc:
        return emit_harness_error(exc, args=args)
    envelope = attach_root_observability(_object_envelope("realm_sync_revert", data))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _realm_skill_selection_envelope(realm) -> dict:
    """The realm_skill_selection/v1 envelope (design §5): current mode +
    selection, the shared-catalog slugs on THIS machine, and the honest
    ``missing`` accounting (selection − catalog).

    ``tombstones`` is ADDITIVE (realm skill-delete §4) and is the same row shape
    the sync status envelope and the sidecar carry — one ledger, one rendering.
    It belongs beside the selection because the two answer the one question an
    operator actually asks here: a slug absent from ``selection`` is merely
    unpublished HERE, while a slug in ``tombstones`` is deleted EVERYWHERE."""
    from agent_runtime.skills_inventory import build_shared_catalog

    _root, _exists, catalog = build_shared_catalog()
    catalog_slugs = sorted({entry["slug"] for entry in catalog})
    selection = sorted(realm.skill_selection or [])
    missing = sorted(set(selection) - set(catalog_slugs))
    return {
        "schema_version": 1,
        "id": realm.id,
        "kind": "realm_skill_selection",
        "mode": realm.skill_publish_mode,
        "selection": selection,
        "catalog": catalog_slugs,
        "missing": missing,
        "tombstones": skill_tombstone_rows(realm),
    }


def _cmd_realm_skills_show(args) -> int:
    realm = RealmStore().get(args.realm_id)
    _print_stage42(_realm_skill_selection_envelope(realm), args=args, default_output="json")
    return 0


#: The publish-selection flags of ``realm skills set`` and ``realm agents set``:
#: one row per flag, ``(flag, args attribute, mode, carries a list)``. Exactly
#: one row must be given. A list row's value is its comma-separated selection
#: (``--skills``/``--agents``, present when not None); a switch row stores an
#: empty selection — ``--all``/``--workspace`` keep the stored list on the
#: realm, ``--none`` empties it.
_SELECTION_MODES: dict[str, tuple[tuple[str, str, str, bool], ...]] = {
    "skills": (
        ("--all", "publish_all", "all", False),
        ("--skills", "skills", "selected", True),
        ("--none", "publish_none", "selected", False),
    ),
    "agents": (
        ("--workspace", "publish_workspace", "workspace", False),
        ("--agents", "agents", "selected", True),
        ("--none", "publish_none", "selected", False),
    ),
}


def selection_from_args(args, noun: str) -> tuple[str, list[str]]:
    """``(mode, selection)`` for a ``realm <noun> set`` call.

    Raises :class:`ValueError` naming the flags when not exactly one is given.
    """

    rows = _SELECTION_MODES[noun]
    given = [
        row
        for row in rows
        if (getattr(args, row[1], None) is not None if row[3] else bool(getattr(args, row[1], False)))
    ]
    if len(given) != 1:
        flags = [row[0] for row in rows]
        raise ValueError(f"exactly one of {', '.join(flags[:-1])}, or {flags[-1]} is required")
    _flag, attr, mode, carries_list = given[0]
    if not carries_list:
        return mode, []
    return mode, [item.strip() for item in str(getattr(args, attr)).split(",") if item.strip()]


def _cmd_realm_skills_set(args) -> int:
    try:
        mode, selection = selection_from_args(args, "skills")
    except ValueError as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    dry_run = bool(getattr(args, "dry_run", False))
    realm = RealmStore().set_skill_selection(
        args.realm_id, mode=mode, selection=selection, dry_run=dry_run
    )
    envelope = _realm_skill_selection_envelope(realm)
    if dry_run:
        envelope["dry_run"] = True
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _realm_agent_selection_envelope(realm_id: str) -> dict:
    state = realm_agent_selection_state(realm_id)
    return {
        "schema_version": 1,
        "id": realm_id,
        "kind": "realm_agent_selection",
        **state,
    }


def _cmd_realm_agents_show(args) -> int:
    # RealmStore lookup occurs inside the state resolver, so a missing id keeps
    # the same typed command error behavior as every other Realm read verb.
    _print_stage42(
        _realm_agent_selection_envelope(args.realm_id),
        args=args,
        default_output="json",
    )
    return 0


def _cmd_realm_agents_set(args) -> int:
    try:
        mode, selection = selection_from_args(args, "agents")
    except ValueError as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    dry_run = bool(getattr(args, "dry_run", False))
    RealmStore().set_agent_selection(
        args.realm_id,
        mode=mode,
        selection=selection,
        dry_run=dry_run,
    )
    envelope = _realm_agent_selection_envelope(args.realm_id)
    if dry_run:
        # The state resolver reads disk, so reflect the validated would-be
        # selection in the preview without mutating RealmStore.
        preview = RealmStore().set_agent_selection(
            args.realm_id,
            mode=mode,
            selection=selection,
            dry_run=True,
        )
        envelope["mode"] = preview.agent_publish_mode
        envelope["selection"] = sorted(preview.agent_selection or [])
        effective = set(envelope["required"])
        if preview.agent_publish_mode == "selected":
            effective.update(envelope["selection"])
        catalog = set(envelope["catalog"])
        envelope["published"] = sorted(effective & catalog)
        envelope["missing"] = sorted(effective - catalog)
        envelope["dry_run"] = True
    _print_stage42(envelope, args=args, default_output="json")
    return 0
