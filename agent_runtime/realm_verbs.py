"""The ten realm verbs the launcher runs — ONE implementation, two doors.

``harness realm sync status|pull|publish|revert|resolve``, ``harness realm
skills show|set``, ``harness realm agents show|set`` and ``harness realm adopt``
(argv, ``hermes_cli.harness_parts.realm_commands``) and their ``runtime.realm.*``
twins (the method lane, ``serve_rpc.realm``) call the functions here. Each
returns the envelope the argv verb prints with ``--json`` and RAISES its typed
refusal — :class:`RealmSyncError` (``code``), ``NotFound``, the two resolve
errors (``code``) or :class:`RealmSelectionInvalid` — for each door to render.

Argv census rows 1-10 (launcher ``argv-census-full-2026-10-03.md``): every one
of these ran as a COLD process per call (5.7-9.2 s of interpreter start,
measured on ``realm sync revert``), the 4-minute status poll included.

What stays per door: the ``--yes`` gate (argv's ``_require_yes`` chokepoint, the
method's ``yes`` param — the same predicate, ``yes or dry_run``), the
credential's TRANSPORT (argv: ``--credential-file`` or the env path; method: the
credential object inline) and rendering. The credential's PARSE is
``RealmSyncCredential`` either way, and it is never echoed.
"""

from __future__ import annotations

from typing import Any

from .cli_format import list_envelope, object_envelope, sort_rows
from .root_observability import attach_root_observability

__layer__ = "lanes"
__all__ = [
    "RealmSelectionInvalid",
    "realm_adopt",
    "realm_agent_selection_envelope",
    "realm_agents_set",
    "realm_agents_show",
    "realm_skill_selection_envelope",
    "realm_skills_set",
    "realm_skills_show",
    "realm_sync_publish",
    "realm_sync_pull",
    "realm_sync_resolve",
    "realm_sync_revert",
    "realm_sync_status",
    "realm_sync_subtree",
    "selection_mode",
]


class RealmSelectionInvalid(ValueError):
    """Not exactly one publish-selection mode was given (``invalid_request``)."""

    code = "invalid_request"


#: ``noun -> ((flag, mode, carries_list), ...)`` in the order the argv flags
#: are spelled; a list row's selection is its items, a switch row's is empty
#: (``--all`` / ``--workspace`` keep the stored list on the realm, ``--none``
#: empties it).
_SELECTION_MODES: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "skills": (("--all", "all", False), ("--skills", "selected", True), ("--none", "selected", False)),
    "agents": (("--workspace", "workspace", False), ("--agents", "selected", True), ("--none", "selected", False)),
}


def selection_mode(noun: str, switch_on: bool, items: list[str] | None, none: bool) -> tuple[str, list[str]]:
    """``(mode, selection)`` from the three selectors of ``realm <noun> set``.

    ``items`` is ``None`` when the list selector was not given (an empty list IS
    given). Raises :class:`RealmSelectionInvalid` naming the flags unless
    exactly one selector is given.
    """
    rows = _SELECTION_MODES[noun]
    given = [row for row, on in zip(rows, (bool(switch_on), items is not None, bool(none))) if on]
    if len(given) != 1:
        flags = [row[0] for row in rows]
        raise RealmSelectionInvalid(f"exactly one of {', '.join(flags[:-1])}, or {flags[-1]} is required")
    _flag, mode, carries_list = given[0]
    if not carries_list:
        return mode, []
    return mode, [item.strip() for item in items or [] if str(item).strip()]


# ── sync: status / pull / publish ────────────────────────────────────────────


def realm_sync_status(realm_id: str, *, credential: Any = None) -> dict:
    from .realm_sync import realm_sync_status as status

    return status(realm_id, credential=credential)


def realm_sync_pull(realm_id: str, *, credential: Any = None, dry_run: bool = False) -> dict:
    from .realm_sync import pull_realm_sync

    return pull_realm_sync(realm_id, dry_run=dry_run, credential=credential)


def realm_sync_publish(realm_id: str, *, credential: Any = None, dry_run: bool = False) -> dict:
    """Publish. The caller has already passed its door's ``--yes`` gate."""
    from .realm_sync import publish_realm_sync

    return publish_realm_sync(realm_id, dry_run=dry_run, credential=credential)


# ── sync: revert / resolve ───────────────────────────────────────────────────


def realm_sync_revert(
    realm_id: str, *, items: list[str] | None = None, revert_all: bool = False,
    to: str | None = None, dry_run: bool = False,
) -> dict:
    """Revert drifted local rows to the last pull, or ``to`` one published
    version (which writes no baseline). Local-only: no credential."""
    from .realm_revert import revert_realm_sync
    from .realm_revert_version import revert_realm_sync_to_version

    selection = {"item_specs": list(items or []), "revert_all": bool(revert_all), "dry_run": bool(dry_run)}
    if to is not None:
        data = revert_realm_sync_to_version(realm_id, to=to, **selection)
    else:
        data = revert_realm_sync(realm_id, **selection)
    return attach_root_observability(object_envelope("realm_sync_revert", data))


def realm_sync_subtree(realm_id: str):
    """The checked-out realm subtree the last pull put on disk (read-only)."""
    from .realm_sync import _realm_subtree, _sync_repo_path
    from .store import RealmStore

    realm = RealmStore().get(realm_id)
    return _realm_subtree(_sync_repo_path(realm), realm.id)


def realm_sync_resolve(realm_id: str, *, key: str, take: str, dry_run: bool = False) -> dict:
    """Resolve ONE hold, dispatched on the key: ``skill::<slug>`` is a skill
    package, ``<profile>:<path>`` a profile file. Raises the resolve error of
    the arm it took (``code`` names the refusal)."""
    from .profile_artifact_sync import resolve_profile_artifact
    from .skill_sync import SKILL_KEY_PREFIX, resolve_held_skill

    if str(key or "").startswith(SKILL_KEY_PREFIX):
        envelope = object_envelope("skill_hold", resolve_held_skill(realm_id, key, take=take, dry_run=dry_run))
    else:
        row = resolve_profile_artifact(realm_id, realm_sync_subtree(realm_id), key, take=take, dry_run=dry_run)
        envelope = object_envelope("profile_artifact_hold", {"id": row["key"], **row})
    if dry_run:
        envelope["dry_run"] = True
    return envelope


# ── skills / agents selection ────────────────────────────────────────────────


def realm_skill_selection_envelope(realm) -> dict:
    """``realm_skill_selection/v1``: mode + selection, the shared-catalog slugs
    on THIS machine, the ``missing`` accounting (selection - catalog) and the
    skill ``tombstones`` (deleted EVERYWHERE, not merely unpublished here)."""
    from .realm_sync import skill_tombstone_rows
    from .skills_inventory import build_shared_catalog

    _root, _exists, catalog = build_shared_catalog()
    catalog_slugs = sorted({entry["slug"] for entry in catalog})
    selection = sorted(realm.skill_selection or [])
    return {
        "schema_version": 1,
        "id": realm.id,
        "kind": "realm_skill_selection",
        "mode": realm.skill_publish_mode,
        "selection": selection,
        "catalog": catalog_slugs,
        "missing": sorted(set(selection) - set(catalog_slugs)),
        "tombstones": skill_tombstone_rows(realm),
    }


def realm_skills_show(realm_id: str) -> dict:
    from .store import RealmStore

    return realm_skill_selection_envelope(RealmStore().get(realm_id))


def realm_skills_set(
    realm_id: str, *, publish_all: bool = False, skills: list[str] | None = None,
    publish_none: bool = False, dry_run: bool = False,
) -> dict:
    from .store import RealmStore

    mode, selection = selection_mode("skills", publish_all, skills, publish_none)
    realm = RealmStore().set_skill_selection(realm_id, mode=mode, selection=selection, dry_run=dry_run)
    envelope = realm_skill_selection_envelope(realm)
    if dry_run:
        envelope["dry_run"] = True
    return envelope


def realm_agent_selection_envelope(realm_id: str) -> dict:
    from .realm_sync import realm_agent_selection_state

    return {"schema_version": 1, "id": realm_id, "kind": "realm_agent_selection",
            **realm_agent_selection_state(realm_id)}


def realm_agents_show(realm_id: str) -> dict:
    return realm_agent_selection_envelope(realm_id)


def _agent_selection_preview(envelope: dict, preview) -> None:
    """Reflect a validated would-be selection without mutating the store (the
    state resolver reads disk, so a dry run cannot read it back)."""
    envelope["mode"] = preview.agent_publish_mode
    envelope["selection"] = sorted(preview.agent_selection or [])
    effective = set(envelope["required"])
    if preview.agent_publish_mode == "selected":
        effective.update(envelope["selection"])
    catalog = set(envelope["catalog"])
    envelope["published"] = sorted(effective & catalog)
    envelope["missing"] = sorted(effective - catalog)
    envelope["dry_run"] = True


def realm_agents_set(
    realm_id: str, *, publish_workspace: bool = False, agents: list[str] | None = None,
    publish_none: bool = False, dry_run: bool = False,
) -> dict:
    from .store import RealmStore

    mode, selection = selection_mode("agents", publish_workspace, agents, publish_none)
    preview = RealmStore().set_agent_selection(realm_id, mode=mode, selection=selection, dry_run=dry_run)
    envelope = realm_agent_selection_envelope(realm_id)
    if dry_run:
        _agent_selection_preview(envelope, preview)
    return envelope


# ── adopt ────────────────────────────────────────────────────────────────────


def realm_adopt(
    credential: Any, *, server_id: str | None = None, dry_run: bool = False, sort: str | None = None,
) -> dict:
    """Adopt the server-granted realms the credential admits. A missing
    credential is ``sync_auth_failed`` — adopt has no local-stub arm."""
    from .realm_membership import adopt_realms
    from .realm_sync import RealmSyncError
    from .scope_activation import realm_row

    if credential is None:
        raise RealmSyncError(
            "sync_auth_failed",
            "realm adopt requires a launcher-brokered credential; pass --credential-file or set "
            "HERMES_REALM_SYNC_CREDENTIAL.",
        )
    adopted = adopt_realms(credential, server_id=server_id, dry_run=dry_run)
    return list_envelope("realm", sort_rows([realm_row(item) for item in adopted], sort))
