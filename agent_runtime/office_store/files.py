"""The office store's file helpers — the ONE place a surface, an actor or a
conflict sidecar is written to disk — and ``read_actor_dir``, the actor
directory read every scan goes through.
"""

from __future__ import annotations

from hermes_time import now
from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.errors import AlreadyExists, StaleRevision
from agent_runtime.models import OfficeActor, OfficeSurface
from agent_runtime.serde import from_jsonable, to_jsonable
from agent_runtime.office_store.models import ActorScan, UnreadableActorFiles

__layer__ = "stores"

__all__ = [
    "read_actor_dir",
    "_archive_conflict_sidecar",
    "_check_revision",
    "_free_surface_archive_dir",
    "_read_json",
    "_write_actor",
    "_write_surface",
]


def read_actor_dir(directory) -> ActorScan:
    """One directory of actor files, COUNTING the ones that would not open.

    THE decoder for an actor directory, wherever the directory came from. It
    was a private method on the store until AX6, which meant the pull's reader
    of a PEER's ``office/<ws>/actors`` (``office_sync._read_remote_office``)
    had to spell the same walk, the same swallow and the same count a second
    time — two spellings of one discipline, free to drift, in the two places
    whose disagreement produces a DELETION (a remote key that reads as absent
    is how the pull infers "the peer removed this desk"). It takes no ``self``
    and never did, so the extraction is a move rather than a redesign.

    The skip stays — a whole office must not vanish because one file is
    mid-write or held by an AV scanner — but ``continue`` alone made the skip
    invisible, and an invisible skip is a shortened projection that reports
    itself complete. The count leaves with the rows.

    Logged once per scan, aggregated by exception CLASS: an operator needs to
    know whether they are looking at a share violation or a half-written JSON
    file, and per-file lines would turn a directory of stale files into a log
    flood on every read of the office. Class only, never the message — the same
    disclosure rule the rest of this runtime's receipts follow. The location is
    ``<parent>/<name>`` rather than the bare directory name, because every one
    of these directories is called ``actors`` and the line now has two possible
    origins: a local workspace and a pulled peer's copy of one.
    """

    actors: list[OfficeActor] = []
    if not directory.exists():
        return ActorScan(actors)
    # The NAMES, not just a tally: the reader is standing on the paths, and the
    # shortfall row downstream can only name a file if this loop keeps one.
    # Qualified by the directory (``actors/x.json`` vs ``archive/x.json``)
    # because ``scan_actors`` merges two of these and the file TOKEN alone is
    # the same in both.
    unreadable_names: list[str] = []
    classes: dict[str, int] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            actors.append(from_jsonable(OfficeActor, _read_json(path)))
        except Exception as exc:  # noqa: BLE001 — the scan survives one bad file
            unreadable_names.append(f"{directory.name}/{path.name}")
            name = type(exc).__name__
            classes[name] = classes.get(name, 0) + 1
    unreadable = UnreadableActorFiles.of(unreadable_names)
    if classes:
        import logging

        logging.getLogger(__name__).warning(
            "office actor files unreadable in %s: %d (%s) [%s]",
            f"{directory.parent.name}/{directory.name}",
            unreadable.total,
            ", ".join(f"{name} x{count}" for name, count in sorted(classes.items())),
            unreadable.describe(),
        )
    return ActorScan(actors, unreadable)


# --- module-level file helpers ---------------------------------------------


def _read_json(path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _write_surface(surface: OfficeSurface) -> None:
    atomic_json_write(paths.office_surface_path(surface.workspace_id), to_jsonable(surface), indent=2, sort_keys=True)


def _write_actor(actor: OfficeActor) -> None:
    atomic_json_write(paths.office_actor_path(actor.workspace_id, actor.actor_key), to_jsonable(actor), indent=2, sort_keys=True)


def _archive_conflict_sidecar(workspace_id: str, actor_key: str) -> None:
    sidecar_path = paths.office_conflict_path(workspace_id, actor_key)
    if not sidecar_path.exists():
        return
    try:
        payload = _read_json(sidecar_path)
    except Exception:
        payload = {"actor_key": actor_key}
    payload["resolved_at"] = to_jsonable(now())
    from ..office_models import actor_file_token

    dest = paths.office_conflicts_dir(workspace_id) / f"{actor_file_token(actor_key)}.resolved.json"
    atomic_json_write(dest, payload, indent=2, sort_keys=True)
    sidecar_path.unlink(missing_ok=True)


def _free_surface_archive_dir(workspace_id: str):
    """First unused archive slot for ``workspace_id``.

    Deterministic rather than timestamped so a test can name the destination,
    and suffixed rather than refusing so an operator who archives a re-created
    orphan a second time is not stuck with a conflict they cannot resolve
    without hand-moving files — which is the thing this verb exists to avoid.
    """

    base = paths.office_archived_surface_dir(workspace_id)
    if not base.exists():
        return base
    for attempt in range(2, 1000):
        candidate = base.with_name(f"{base.name}-{attempt}")
        if not candidate.exists():
            return candidate
    raise AlreadyExists(f"office_archive:{workspace_id}")


def _check_revision(current: int | None, expected: int | None) -> None:
    if expected is None:
        return
    if current is None or int(current) != int(expected):
        raise StaleRevision(f"stale_revision: expected {expected}, have {current}")
