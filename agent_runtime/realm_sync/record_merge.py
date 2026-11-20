"""The WORKSPACE and REALM records' pull: a field-wise merge against the last-published baseline.

RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE (review w1118a.50 D7). Seen in Eternia
2026-11-19: a workspace renamed here after its publish read the team's older name again after Sync's
pull. Both record families were ``families.GENERIC_PULL``: ``pull._overwrite_generic_families`` wrote
the team's bytes over the local file whenever they differed, with no baseline, while every other
family merges against one.

One design for both families (the ruling's): each record's fields are decided against the copy this
machine last published or adopted (the baseline, never synced, never published), with the shared
classifier ``sync_merge.classify_three_way_pull``:

* a field changed only here is KEPT, and the next publish ships it;
* a field changed only by the team is TAKEN;
* a field both changed, to different values, is HELD: the local value stays, the team's is parked in a
  conflict sidecar (``paths.record_conflict_path``), the publish ships the team's value for it
  (:func:`keep_team_fields`), and the baseline keeps its old value so the next pull still sees the
  two-sided change — until ``realm sync resolve record::<family>:<id> --take local|remote``.

Fields that are not the member's to merge keep the rule they had: ``updated_at`` is a stamp (the
newer of the two), the realm's resurrection ledgers and its install-local and authority fields are
what ``pull._pulled_artifact_bytes`` reconciled (the reconciled copy is the team side here), a
workspace's ``realm_id`` is the move rules' (the team copy's, when the loop writes it at all), and the realm's
``workspace_ids`` merge as a list — an id added on either side is kept, one removed on either side
leaves — then ``ledgers.drop_left_workspace_ids``. The workspace re-home and moved-out rules
(``pull._workspaces_moved_out``, ``_leave_realms_a_pull_rehomed_from``) run around this merge as before.

A record with no baseline yet (published before this lane, or never published here) is adopted as the
team has it, as before, and the baseline is recorded then: there is nothing to tell "changed here"
from "never seen".
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from .. import paths
from ..sync_merge import PullAction, classify_three_way_pull
from ..sync_take import SyncTake
from .families import SyncFamily
from .ledgers import _UNIONED_REALM_LEDGERS, drop_left_workspace_ids
from .models import RealmSyncArtifact

__layer__ = "stores"
__all__ = [
    "RECORD_KEY_PREFIX",
    "RecordHoldResolveError",
    "RecordMerge",
    "held_record_keys",
    "keep_team_fields",
    "merge_record",
    "merge_record_pull",
    "record_baselines_after_publish",
    "resolve_record_hold",
]

#: The resolve key's prefix: ``record::workspace:<id>`` / ``record::realm:<id>``.
RECORD_KEY_PREFIX: Final = "record::"
#: The families this module merges, by the kind their artifacts carry.
_MERGED_KINDS: Final = (str(SyncFamily.WORKSPACE), str(SyncFamily.REALM))
#: A stamp, never a member's edit: the newer side's wins and it never holds.
_STAMP_FIELDS: Final = ("updated_at",)
#: Realm fields ``pull._pulled_artifact_bytes`` already reconciled (unioned ledgers; ``archived`` and
#: the server authority fields are this machine's): the reconciled team copy is taken as it is.
_REALM_RECONCILED_FIELDS: Final = frozenset((*_UNIONED_REALM_LEDGERS, "archived"))
#: A workspace's realm is the move rules' (``pull._workspaces_moved_out`` skips a workspace that left the
#: pulled realm before this merge; one the loop writes the team placed there, re-homed by
#: ``_leave_realms_a_pull_rehomed_from``): the team copy's value is taken as it is.
_WORKSPACE_RECONCILED_FIELDS: Final = frozenset(("realm_id",))


class RecordHoldResolveError(ValueError):
    """A record hold could not be resolved; ``code`` names the refusal."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class RecordMerge:
    """One record's field-wise merge: what to write, the fields held, and the baseline it leaves."""

    merged: dict[str, Any]
    held: dict[str, dict[str, Any]] = field(default_factory=dict)
    baseline: dict[str, Any] = field(default_factory=dict)


def _same(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(right, sort_keys=True, default=str)


def _hash(record: dict[str, Any], name: str) -> str | None:
    return json.dumps(record[name], sort_keys=True, default=str) if name in record else None


def _merge_id_list(local: Any, remote: Any, base: Any) -> list[Any]:
    """A three-way list merge for membership ids: the team's order, an id removed here leaves, one added here joins."""

    local_list = [item for item in local or [] if isinstance(item, str)]
    remote_list = [item for item in remote or [] if isinstance(item, str)]
    base_set = {item for item in base or [] if isinstance(item, str)}
    local_set = set(local_list)
    merged = [item for item in remote_list if item in local_set or item not in base_set]
    merged += [item for item in local_list if item not in base_set and item not in merged]
    return merged


def merge_record(kind: str, local: dict[str, Any], remote: dict[str, Any], base: dict[str, Any]) -> RecordMerge:
    """Merge one record, field by field, against ``base`` (the copy last published or adopted here)."""

    merged: dict[str, Any] = {}
    held: dict[str, dict[str, Any]] = {}
    baseline: dict[str, Any] = {}
    realm = kind == str(SyncFamily.REALM)
    for name in sorted({*local, *remote, *base}):
        if name in _STAMP_FIELDS:
            stamps = [str(side[name]) for side in (local, remote) if side.get(name) is not None]
            if stamps:
                merged[name] = max(stamps)
            if name in remote:
                baseline[name] = remote[name]
            continue
        if name in (_REALM_RECONCILED_FIELDS if realm else _WORKSPACE_RECONCILED_FIELDS):
            if name in remote:
                merged[name] = baseline[name] = remote[name]
            continue
        if realm and name == "workspace_ids":
            merged[name] = _merge_id_list(local.get(name), remote.get(name), base.get(name))
            baseline[name] = remote.get(name, [])
            continue
        decision = classify_three_way_pull(_hash(local, name), _hash(remote, name), _hash(base, name))
        if decision.action == PullAction.CONFLICT:
            if name in local:
                merged[name] = local[name]
            held[name] = {"local": local.get(name), "remote": remote.get(name)}
            if name in base:
                baseline[name] = base[name]
            continue
        if decision.action == PullAction.WRITE_REMOTE:
            merged[name] = remote[name]
        elif decision.action == PullAction.ARCHIVE_LOCAL:
            pass  # the team dropped a field this machine left as it was
        elif name in local:  # KEEP_LOCAL, NOOP
            merged[name] = local[name]
        if name in remote:
            baseline[name] = remote[name]
    if realm:
        drop_left_workspace_ids(merged)
    return RecordMerge(merged=merged, held=held, baseline=baseline)


# --- the baseline and the conflict sidecars (never synced, never published) ----------------------


def _record_key(kind: str, record_id: str) -> str:
    return f"{kind}:{record_id}"


def _read_baseline(realm_id: str) -> dict[str, dict[str, Any]]:
    path = paths.record_baseline_path(realm_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)} if isinstance(entries, dict) else {}


def _write_baseline(realm_id: str, entries: dict[str, dict[str, Any]]) -> None:
    from utils import atomic_json_write

    atomic_json_write(
        paths.record_baseline_path(realm_id),
        {"schema_version": 1, "entries": entries},
        indent=2,
        sort_keys=True,
        default=str,
    )


def _write_hold(realm_id: str, kind: str, record_id: str, held: dict[str, dict[str, Any]]) -> None:
    from utils import atomic_json_write

    path = paths.record_conflict_path(realm_id, kind, record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, {"schema_version": 1, "family": kind, "id": record_id, "fields": held},
                      indent=2, sort_keys=True, default=str)


def _read_hold(realm_id: str, kind: str, record_id: str) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(paths.record_conflict_path(realm_id, kind, record_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    held = raw.get("fields") if isinstance(raw, dict) else None
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _clear_hold(realm_id: str, kind: str, record_id: str) -> None:
    try:
        paths.record_conflict_path(realm_id, kind, record_id).unlink()
    except FileNotFoundError:
        pass


def held_record_keys(realm_id: str) -> list[str]:
    """Every record a pull HELD in this realm, as resolve keys (``record::workspace:<id>``)."""

    keys: list[str] = []
    root = paths.record_conflicts_root(realm_id)
    if not root.is_dir():
        return keys
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and raw.get("family") and raw.get("id") and raw.get("fields"):
            keys.append(f"{RECORD_KEY_PREFIX}{_record_key(str(raw['family']), str(raw['id']))}")
    return keys


# --- the pull ------------------------------------------------------------------------------------


def _record_id(destination: Path) -> str:
    return destination.stem


def _load(data: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def merge_record_pull(realm_id: str, artifact: RealmSyncArtifact, team: bytes) -> bytes:
    """The bytes the pull writes for one workspace or realm record: ``team`` (the team copy, reconciled)
    merged field-wise with this machine's file against the baseline. Records the baseline and the hold.

    Any other artifact, an unreadable side, or a record with no baseline yet answers ``team`` (the old
    adopt), and the baseline is recorded from it. MUTATION: answer ``team`` always and
    test_a_rename_made_here_after_the_last_publish_survives_a_pull reddens.
    """

    kind = str(artifact.kind)
    if kind not in _MERGED_KINDS:
        return team
    record_id = _record_id(artifact.destination)
    key = _record_key(kind, record_id)
    remote = _load(team)
    baselines = _read_baseline(realm_id)
    base = baselines.get(key)
    local = _load(artifact.destination.read_bytes()) if artifact.destination.is_file() else None
    if remote is None:
        return team
    if local is None or base is None:
        baselines[key] = remote
        _write_baseline(realm_id, baselines)
        return team
    result = merge_record(kind, local, remote, base)
    baselines[key] = result.baseline
    _write_baseline(realm_id, baselines)
    if result.held:
        _write_hold(realm_id, kind, record_id, result.held)
    else:
        _clear_hold(realm_id, kind, record_id)
    if _same(result.merged, remote):
        return team
    if _same(result.merged, local):
        return artifact.destination.read_bytes()
    return json.dumps(result.merged, indent=2, sort_keys=True, default=str).encode("utf-8")


# --- the publish ---------------------------------------------------------------------------------


def keep_team_fields(realm_id: str, artifacts: list[RealmSyncArtifact]) -> list[RealmSyncArtifact]:
    """``artifacts`` with each HELD record's held fields set to the team's value: a hold is the member's
    to resolve, and publishing their value over it would decide it for them. MUTATION: return
    ``artifacts`` unchanged and test_a_rename_on_both_sides_holds_and_publishes_neither reddens."""

    out: list[RealmSyncArtifact] = []
    for artifact in artifacts:
        kind = str(artifact.kind)
        held = _read_hold(realm_id, kind, _record_id(artifact.destination)) if kind in _MERGED_KINDS else {}
        record = _load(artifact.read_bytes()) if held else None
        if record is None:
            out.append(artifact)
            continue
        for name, sides in held.items():
            if "remote" in sides and sides["remote"] is not None:
                record[name] = sides["remote"]
            else:
                record.pop(name, None)
        out.append(replace(artifact, content=json.dumps(record, indent=2, sort_keys=True, default=str).encode("utf-8")))
    return out


def record_baselines_after_publish(realm_id: str, published: Iterable[RealmSyncArtifact]) -> None:
    """Record what the publish shipped as each record's baseline, so this machine's own publish never
    reads as a change on its next pull; a held field keeps the baseline it had (the hold stays two-sided)."""

    baselines = _read_baseline(realm_id)
    for artifact in published:
        kind = str(artifact.kind)
        if kind not in _MERGED_KINDS:
            continue
        record = _load(artifact.read_bytes())
        if record is None:
            continue
        record_id = _record_id(artifact.destination)
        key = _record_key(kind, record_id)
        old = baselines.get(key, {})
        for name in _read_hold(realm_id, kind, record_id):
            if name in old:
                record[name] = old[name]
            else:
                record.pop(name, None)
        baselines[key] = record
    _write_baseline(realm_id, baselines)


# --- the resolve ---------------------------------------------------------------------------------


def _destination(kind: str, record_id: str) -> Path:
    return paths.workspace_path(record_id) if kind == str(SyncFamily.WORKSPACE) else paths.realm_path(record_id)


def resolve_record_hold(realm_id: str, key: str, *, take: str, dry_run: bool = False) -> dict[str, Any]:
    """Resolve ONE held record: ``take=remote`` writes the team's values of its held fields here,
    ``take=local`` keeps this machine's. Both record the team's values as the baseline ("I have seen the
    realm's version"), so a kept local value is published next and the hold does not come back."""

    try:
        side = SyncTake(take)
    except ValueError:
        raise RecordHoldResolveError("invalid_request", "take must be 'local' or 'remote'") from None
    body = str(key or "")[len(RECORD_KEY_PREFIX):] if str(key or "").startswith(RECORD_KEY_PREFIX) else ""
    kind, _, record_id = body.partition(":")
    if kind not in _MERGED_KINDS or not record_id:
        raise RecordHoldResolveError("invalid_request", f"not a record hold key: {key}")
    held = _read_hold(realm_id, kind, record_id)
    if not held:
        raise RecordHoldResolveError("not_found", f"no hold on {key}")
    row = {"key": key, "take": str(side), "fields": sorted(held)}
    if dry_run:
        return row
    destination = _destination(kind, record_id)
    if side is SyncTake.REMOTE:
        record = _load(destination.read_bytes()) if destination.is_file() else None
        if record is None:
            raise RecordHoldResolveError("not_found", f"{key} is not on this machine")
        for name, sides in held.items():
            if sides.get("remote") is not None:
                record[name] = sides["remote"]
            else:
                record.pop(name, None)
        destination.write_text(json.dumps(record, indent=2, sort_keys=True, default=str), encoding="utf-8")
    baselines = _read_baseline(realm_id)
    entry = dict(baselines.get(_record_key(kind, record_id), {}))
    for name, sides in held.items():
        if sides.get("remote") is not None:
            entry[name] = sides["remote"]
        else:
            entry.pop(name, None)
    baselines[_record_key(kind, record_id)] = entry
    _write_baseline(realm_id, baselines)
    _clear_hold(realm_id, kind, record_id)
    return row
