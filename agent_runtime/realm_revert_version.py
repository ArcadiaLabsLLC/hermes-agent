"""``hermes harness realm sync revert <realm> --to <sha>`` — restore the local
store to one PUBLISHED VERSION of the realm (H3).

Plain ``revert`` reconciles store drift (store vs baseline) against the
last-pulled subtree. ``--to`` is the opposite on all three axes, which is why it
is its own module and not a flag threaded through that one:

* **Selection.** A row is selected when the store differs from version X's
  subtree — the store-drift rows (store moved since the last sync) PLUS the rows
  whose published artifact moved between X and the last-pulled subtree (the store
  still matches the newer upstream, so plain drift cannot see them).
* **Source.** Every row is read from X's subtree, extracted read-only with
  ``git archive`` into a temporary directory. Skills are read from X too: X's
  ``skills/`` tree is mirrored LF-canonical and tombstone-filtered into a
  temporary inbox by the pull's own mirror, so a restore installs the bytes a
  pull of X would have.
* **Baselines.** NONE are written. The baseline keeps saying what the realm
  holds now, so every restored row reads as a local edit the operator can
  publish (making X the realm's newest version) or revert away.

Owner ruling 2026-09-29, the destructive half: a row CREATED AFTER X (present
locally, absent from X) is never archived and never deleted. It is reported as
``kept_created_after_version`` so the operator can keep or delete it; it stays
where it is.

The write arms, the admission doors and the process order are plain revert's —
a version restore writes nothing a pull of X could not have written. Local-only:
no fetch and no network; the version must already be in the local clone
(``realm sync history`` lists the ones that are). Upstream HEAD is untouched —
``git archive`` reads an object, it moves no ref.
"""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path
from typing import Any

from . import paths
from .git_cmd import run_git
from .realm_revert import (
    CONTAINER_FAMILIES,
    OUTCOME_RESTORED,
    OUTCOME_REVERTED,
    REFUSED_ADMISSION,
    REFUSED_STORE_ERROR,
    REFUSED_UNREADABLE_UPSTREAM,
    REVERT_EVENT_TYPE,
    RevertAction,
    RevertRow,
    _PROCESS_ORDER,
    _Upstream,
    _admission_refusal,
    _apply_revert,
    _check_selection,
    _require_pulled_subtree,
    _select_items,
)
from .realm_revert_writes import _SkillWriteRefused
from .realm_sync import (
    DRIFT_FAMILY_BOARD,
    DRIFT_FAMILY_BOARD_CARD,
    DRIFT_FAMILY_FLOW_GRAPH,
    DRIFT_FAMILY_OFFICE_ACTOR,
    DRIFT_FAMILY_OFFICE_SURFACE,
    DRIFT_FAMILY_PERSONA_DEFINITION,
    DRIFT_FAMILY_PERSONA_INSTANCE,
    DRIFT_FAMILY_SKILL,
    DRIFT_KIND_ADDED,
    DRIFT_KIND_CHANGED,
    DRIFT_KIND_REMOVED,
    RealmSyncError,
    StoreDriftItem,
    _append_realm_sync_event,
    _board_store_drift,
    _mirror_realm_skill_inbox,
    _office_store_drift,
    _safe_display_path,
    _workspaces_for_realm,
    store_drift_items,
)
from .realm_sync.drift import DRIFT_KEY_BOARD_DEF, DRIFT_KEY_OFFICE_SURFACE
from .serde import to_jsonable
from .store import RealmStore

__layer__ = "lanes"

#: A row that exists locally and not in version X — made after it. Kept where it
#: is for the operator to keep or delete (owner ruling 2026-09-29). Not applied,
#: and not a refusal: the pass did exactly what it promises for this row.
OUTCOME_KEPT_CREATED_AFTER = "kept_created_after_version"
#: A selected row that is absent both locally and in X — already at the version.
OUTCOME_ALREADY_AT_VERSION = "already_at_version"

KEPT_OUTCOMES = frozenset({OUTCOME_KEPT_CREATED_AFTER, OUTCOME_ALREADY_AT_VERSION})


def classify_version_restore(*, family: str, kind: str, version_present: bool) -> tuple[RevertAction | None, str]:
    """THE version-restore table, pure. ``kind`` says whether the row is live
    locally (``removed`` means it is not); ``version_present`` whether X holds a
    decodable artifact for it. ``None`` is "write nothing"."""

    if not version_present:
        if kind == DRIFT_KIND_REMOVED:
            return None, OUTCOME_ALREADY_AT_VERSION
        return None, OUTCOME_KEPT_CREATED_AFTER
    if kind == DRIFT_KIND_REMOVED and family not in CONTAINER_FAMILIES:
        return RevertAction.RESTORE, OUTCOME_RESTORED
    return RevertAction.ADOPT, OUTCOME_REVERTED


# --- the version's subtree ---------------------------------------------------


def _resolve_version(repo: Path, to: str) -> str:
    text = str(to or "").strip()
    if not text or text.startswith("-"):
        raise RealmSyncError("invalid_request", "--to takes a version sha from `realm sync history`.",
                             safe_details={"to": text})
    proc = run_git(["rev-parse", "--verify", "-q", f"{text}^{{commit}}"], repo=repo)
    sha = (proc.stdout or "").strip()
    if proc.returncode != 0 or not sha:
        raise RealmSyncError(
            "version_not_found",
            "That version is not in the local sync clone; run `realm sync history` for the versions it holds.",
            safe_details={"to": text},
        )
    return sha


def _extract_version_subtree(repo: Path, sha: str, rel: str, dest: Path) -> Path:
    """X's ``realms/<realm>/`` tree, read-only, into ``dest``. No ref moves."""

    if run_git(["cat-file", "-e", f"{sha}:{rel}"], repo=repo).returncode != 0:
        raise RealmSyncError(
            "version_has_no_realm_subtree",
            "That version carries nothing for this realm.",
            safe_details={"to": sha},
        )
    archive = dest / "version.tar"
    proc = run_git(["archive", "--format=tar", "-o", str(archive), sha, rel], repo=repo)
    if proc.returncode != 0:
        raise RealmSyncError("version_not_found", "Could not read that version from the local sync clone.",
                             safe_details={"to": sha})
    tree = dest / "tree"
    with tarfile.open(archive) as tar:
        tar.extractall(tree, filter="data")
    return tree.joinpath(*rel.split("/"))


# --- selection: rows where the store differs from X --------------------------


def _differs(a: Any, b: Any) -> bool:
    return to_jsonable(a) != to_jsonable(b)


def _kind(current_present: bool, version_present: bool) -> str:
    if not version_present:
        return DRIFT_KIND_ADDED
    return DRIFT_KIND_CHANGED if current_present else DRIFT_KIND_REMOVED


def _pair_rows(family: str, container: str, current: dict, version: dict) -> list[StoreDriftItem]:
    rows = []
    for key in sorted(set(current) | set(version)):
        a, b = current.get(key), version.get(key)
        if (a is None) != (b is None) or (a is not None and _differs(a, b)):
            rows.append(StoreDriftItem(family=family, container=container(key) if callable(container) else container,
                                       item_key=key, kind=_kind(a is not None, b is not None)))
    return rows


def _container_dirs(*subtrees: Path, kind: str) -> list[str]:
    names: set[str] = set()
    for subtree in subtrees:
        root = subtree / "store" / kind
        if root.is_dir():
            names.update(child.name for child in root.iterdir() if child.is_dir())
    return sorted(names)


def _upstream_moved_rows(realm, workspaces, current: _Upstream, version: _Upstream,
                         current_subtree: Path, version_subtree: Path, version_skills: Path) -> list[StoreDriftItem]:
    """Rows whose PUBLISHED artifact differs between the last-pulled subtree and
    X. The store matches the newer one for these, so the baseline walk cannot
    see them — and they are exactly what "go back to X" has to move."""

    from .flow_graph import owner_instance_id_of
    from .flow_graph_sync import read_remote_flow_graphs
    from .persona_config_sync import read_remote_persona_defs
    from .persona_instance_sync import read_remote_persona_instances
    from .skill_promotion import iter_skill_packages, realm_inbox_dir, skill_package_sync_hash

    rows: list[StoreDriftItem] = []
    for ws in workspaces:
        cur, ver = current._office(ws.id), version._office(ws.id)
        rows += _pair_rows(DRIFT_FAMILY_OFFICE_SURFACE, ws.id,
                           {DRIFT_KEY_OFFICE_SURFACE: cur.surface} if cur.surface is not None else {},
                           {DRIFT_KEY_OFFICE_SURFACE: ver.surface} if ver.surface is not None else {})
        rows += _pair_rows(DRIFT_FAMILY_OFFICE_ACTOR, ws.id, dict(cur.actors), dict(ver.actors))
    for board_id in _container_dirs(current_subtree, version_subtree, kind="boards"):
        cur, ver = current._board(board_id), version._board(board_id)
        rows += _pair_rows(DRIFT_FAMILY_BOARD, board_id,
                           {DRIFT_KEY_BOARD_DEF: cur.board} if cur.board is not None else {},
                           {DRIFT_KEY_BOARD_DEF: ver.board} if ver.board is not None else {})
        rows += _pair_rows(DRIFT_FAMILY_BOARD_CARD, board_id, dict(cur.cards), dict(ver.cards))

    cur_i, cur_src = read_remote_persona_instances(current_subtree)
    ver_i, ver_src = read_remote_persona_instances(version_subtree)
    if "unreadable" not in (cur_src, ver_src):
        rows += _pair_rows(DRIFT_FAMILY_PERSONA_INSTANCE,
                           lambda key: str(((ver_i.get(key) or cur_i.get(key)) or {}).get("workspace_id") or ""),
                           cur_i, ver_i)
    cur_g, cur_gsrc = read_remote_flow_graphs(current_subtree)
    ver_g, ver_gsrc = read_remote_flow_graphs(version_subtree)
    if "unreadable" not in (cur_gsrc, ver_gsrc):
        rows += _pair_rows(DRIFT_FAMILY_FLOW_GRAPH, owner_instance_id_of, cur_g, ver_g)
    rows += _pair_rows(DRIFT_FAMILY_PERSONA_DEFINITION, "",
                       read_remote_persona_defs(current_subtree)[0], read_remote_persona_defs(version_subtree)[0])

    def _skill_hashes(root: Path) -> dict[str, str]:
        return {slug: skill_package_sync_hash(pkg) for slug, pkg in iter_skill_packages(root)}

    rows += _pair_rows(DRIFT_FAMILY_SKILL, "", _skill_hashes(realm_inbox_dir(realm.id)),
                       _skill_hashes(version_skills))
    return rows


def _version_candidates(store_drift: list[StoreDriftItem], moved: list[StoreDriftItem]) -> list[StoreDriftItem]:
    """Store drift first — its ``kind`` is the truth about the LOCAL row — then
    every upstream-moved row the drift set does not already name."""

    seen = {item.spec for item in store_drift}
    return list(store_drift) + [item for item in moved if item.spec not in seen]


# --- the pass ------------------------------------------------------------------


def revert_realm_sync_to_version(
    realm_id: str,
    *,
    to: str,
    item_specs: list[str] | None = None,
    revert_all: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore the selected rows to version ``to``. Writes no baseline."""

    from .board_store import BoardStore
    from .office_store import OfficeStore
    from .store import skill_tombstoned

    requested = [spec for spec in (item_specs or []) if str(spec).strip()]
    _check_selection(requested, revert_all=revert_all)
    realm = RealmStore().get(realm_id)
    repo, subtree = _require_pulled_subtree(realm)
    sha = _resolve_version(repo, to)
    rel = f"realms/{paths.safe_path_token(realm.id)}"
    workspaces = _workspaces_for_realm(realm)

    with tempfile.TemporaryDirectory(prefix="realm-revert-to-") as tmp:
        tmp_root = Path(tmp)
        version_subtree = _extract_version_subtree(repo, sha, rel, tmp_root)
        version_skills = tmp_root / "skill_inbox"
        _mirror_realm_skill_inbox(
            version_subtree / "skills", version_skills,
            tombstoned=lambda slug: skill_tombstoned(realm, slug) is not None,
        )
        current = _Upstream(subtree, realm_id=realm.id)
        version = _Upstream(version_subtree, realm_id=realm.id, skill_root=version_skills)
        candidates = _version_candidates(
            store_drift_items(realm.id, workspaces),
            _upstream_moved_rows(realm, workspaces, current, version, subtree, version_subtree, version_skills),
        )
        selected, rows = _select_items(candidates, requested, revert_all=revert_all)
        office_store, board_store = OfficeStore(), BoardStore()
        for item in sorted(selected, key=lambda r: (_PROCESS_ORDER[r.family], r.family, r.container, r.item_key)):
            rows.append(_restore_one(item, version, office_store=office_store, board_store=board_store,
                                     realm_id=realm.id, dry_run=dry_run))

    applied = [row for row in rows if row.applied]
    kept = [row for row in rows if row.outcome in KEPT_OUTCOMES]
    if not dry_run and applied:
        _append_realm_sync_event(REVERT_EVENT_TYPE, realm, changed=True, artifacts=len(applied))
    return {
        "id": realm.id,
        "realm_id": realm.id,
        "dry_run": bool(dry_run),
        "selection": "all" if revert_all else "items",
        "to": sha,
        "count": len(rows),
        "reverted": len(applied),
        "kept": len(kept),
        "refused": len(rows) - len(applied) - len(kept),
        "items": [row.as_dict() for row in rows],
        "store_drift_after": {
            "boards": _board_store_drift(realm.id, workspaces),
            "office": _office_store_drift(realm.id, workspaces),
        },
        "sync_repo": _safe_display_path(repo),
    }


def _restore_one(item: StoreDriftItem, version: _Upstream, *, office_store, board_store,
                 realm_id: str, dry_run: bool) -> RevertRow:
    entity, unreadable = version.lookup(item.family, item.container, item.item_key)
    row = RevertRow(family=item.family, container=item.container, item_key=item.item_key,
                    kind=item.kind, outcome=REFUSED_UNREADABLE_UPSTREAM)
    if unreadable:
        row.detail = "version_artifact_unreadable"
        return row
    action, row.outcome = classify_version_restore(
        family=item.family, kind=item.kind, version_present=entity is not None)
    if action is None:
        return row
    refusal = _admission_refusal(item, entity, item.baseline_key())
    if refusal is not None:
        row.outcome, row.detail = REFUSED_ADMISSION, refusal.code
        return row
    if dry_run:
        return row
    try:
        _apply_revert(item, entity, action, office_store=office_store, board_store=board_store, realm_id=realm_id)
    except _SkillWriteRefused as exc:
        row.outcome, row.detail = REFUSED_STORE_ERROR, exc.code
    except Exception as exc:  # noqa: BLE001 — accounted, never silent; the pass continues
        row.outcome, row.detail = REFUSED_STORE_ERROR, type(exc).__name__
    return row
