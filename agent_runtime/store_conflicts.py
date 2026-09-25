"""Sync-conflict sidecars and the revision check, for every store that has them
(program rule 15).

A realm pull that cannot adopt a peer's row writes a conflict SIDECAR beside the
store's files; while it exists, the row is fenced (:func:`guard_no_conflict`), and
resolving it moves the sidecar aside as ``<token>.resolved.json`` stamped with
``resolved_at`` (:func:`archive_conflict_sidecar`). :func:`check_revision` is the
optimistic-concurrency check a guarded write spends.

:func:`park_conflict_sidecar` is the PULL side: the one best-effort write of
the body a HOLD refused to adopt (lane 2B-C created it for
``persona_instance_sync``; ``flow_graph_sync``, ``level_sync`` and ``map_sync``
fold their ``_write_conflict_sidecar`` copies in their own lanes).

Owners today: ``office_store``. ``board_store``'s three twins
(``_guard_no_conflict``, ``_archive_conflict_sidecar``, ``_check_revision``) fold
here in its own lane. Each store keeps only its own PATHS and its own refusal
token; the rule is here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from agent_runtime.errors import StaleRevision, SyncConflict
from agent_runtime.serde import read_json, to_jsonable

__layer__ = "stores"

__all__ = ["archive_conflict_sidecar", "check_revision", "guard_no_conflict", "park_conflict_sidecar"]


def guard_no_conflict(sidecar_path: Path, refusal: str) -> None:
    """Refuse a write while its row has an unresolved conflict sidecar."""
    if sidecar_path.exists():
        raise SyncConflict(refusal)


def archive_conflict_sidecar(sidecar_path: Path, resolved_path: Path, fallback: dict[str, Any]) -> None:
    """Move a resolved sidecar aside, stamped ``resolved_at``; a no-op when absent.

    An unreadable sidecar still resolves: ``fallback`` (the row's key) is
    written in its place, because the resolution is the operator's decision and
    the file's content is only its evidence.
    """
    if not sidecar_path.exists():
        return
    try:
        payload = read_json(sidecar_path)
    except Exception:
        payload = dict(fallback)
    payload["resolved_at"] = to_jsonable(now())
    atomic_json_write(resolved_path, payload, indent=2, sort_keys=True)
    sidecar_path.unlink(missing_ok=True)


def park_conflict_sidecar(
    path: Path,
    *,
    realm_id: str,
    key_field: str,
    key: str,
    kind: str,
    remote_body: Any,
    local_hash: str | None,
    remote_hash: str | None,
) -> None:
    """Park the body a HOLD refused to adopt: ``{schema_version, realm_id,
    <key_field>: key, kind, local_hash, remote_hash, remote_body}``.

    Best-effort: a sidecar this machine cannot write is not a reason to clobber
    the row the hold exists to protect, so a write fault is swallowed.
    """
    try:
        atomic_json_write(
            path,
            {
                "schema_version": 1,
                "realm_id": realm_id,
                key_field: key,
                "kind": kind,
                "local_hash": local_hash,
                "remote_hash": remote_hash,
                "remote_body": remote_body,
            },
            indent=2,
            sort_keys=True,
        )
    except Exception:  # noqa: BLE001 — the HOLD stands with or without its receipt
        pass


def check_revision(current: int | None, expected: int | None) -> None:
    """``expected`` (when given) must equal the row's live revision; a missing
    row has no revision, so any expectation against it is stale."""
    if expected is None:
        return
    if current is None or int(current) != int(expected):
        raise StaleRevision(f"stale_revision: expected {expected}, have {current}")
