"""``hermes namespace list | reset | delete`` — the namespace admin verbs (row RT-NAMESPACE-CLI).

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.4, §2.8, §3, §4 H3; owner rulings Q3/Q4 (persistent QA namespace, explicit reset) and Q10 (a
namespace leaves the disk only by ``delete``). The one-time seed lives in
:mod:`agent_runtime.namespace_seed`.

Every verb names its namespaces explicitly; nothing here enumerates ``hermes-namespaces/`` to pick
a source (``list`` reports, it never chooses). ``reset`` and ``delete`` hold the namespace's socket
lock while they remove, and refuse while a serve holds it or a registered serve is live or
unclassifiable.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from hermes_cli._namespace_bootstrap import (
    ENV,
    MANIFEST_NAME,
    Layout,
    NamespaceRefused,
    Reason,
    base_root,
    layout,
    namespace_kind,
    namespace_origin,
    namespaces_dir,
    validate_id,
)

from . import store_epoch
from .file_locks import LockUnavailable, try_lock_exclusive, unlock

__layer__ = "lanes"


class _ServeEvidence(NamedTuple):
    """Where a SEPARATE serve process leaves its marks in a store root (each ``None`` / empty: no such mark)."""

    lock_path: Callable[[Path], Path | None]
    owner_path: Callable[[Path], Path | None]
    busy_rows: Callable[[Path], list[dict[str, Any]]]
    instances_dir: Callable[[Path], Path | None]


_NO_SEPARATE_SERVE = _ServeEvidence(lambda _root: None, lambda _root: None, lambda _root: [], lambda _root: None)


def _separate_serve_evidence() -> _ServeEvidence:
    """The socket lock and the serve registry, or the phone's truth when they are not in this build.

    RT-PHONE-NAMESPACE-DELETE-BEFORE-SERVE: the bundled phone profile switches off
    ``agent_runtime.serve_registry`` and ``agent_runtime.serve_socket`` (``bundled-phone.yaml``,
    ``switched_off_modules``) with the daemon shell. A phone has no separate serve process — its one
    serve is embedded in the host's process, writes no pid row and opens no socket — so there is no
    lock file to hold and no registry row to read. Imported here, never at module level, so the phone
    host can run ``delete`` before ``EmbeddedServe`` starts. On the desktop both modules are always there.
    """
    # MUTATION: move these two imports back to module level and test_phone_namespace_delete_before_serve's
    # "namespace_admin imports and deletes without the switched-off modules" reddens (ImportError).
    try:
        from .serve_registry import (
            CLASSIFICATION_LIVE,
            CLASSIFICATION_UNKNOWN,
            list_serve_instances,
            serve_instances_dir,
        )
        from .serve_socket.owner_lock import socket_lock_path, socket_owner_path
    except ImportError:
        return _NO_SEPARATE_SERVE

    def busy_rows(store_root: Path) -> list[dict[str, Any]]:
        return [row for row in list_serve_instances(store_root)
                if row.get("classification") in (CLASSIFICATION_LIVE, CLASSIFICATION_UNKNOWN)]

    return _ServeEvidence(socket_lock_path, socket_owner_path, busy_rows, serve_instances_dir)

def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _namespace_manifest(item: Layout) -> dict[str, Any] | None:
    try:
        record = json.loads(item.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) and record.get("id") == item.id else None


def _write_manifest(item: Layout, record: dict[str, Any]) -> None:
    tmp = item.manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, item.manifest_path)


def epoch_admitted(item: Layout, env: Mapping[str, str], *, write: bool = False) -> store_epoch.Decision:
    """RT-STORE-EPOCH: a verb that reads or writes a namespace's stores refuses one this build cannot read."""
    decision = store_epoch.guard(item.manifest_path, env, write=write)
    if decision.refusal is not None:
        raise NamespaceRefused(Reason(decision.refusal),
                               f"{item.id!r} is at store epoch {decision.stored}; this build is epoch {decision.mine} "
                               f"({decision.verdict})")
    return decision


def restamped(record: dict[str, Any]) -> dict[str, Any]:
    """A manifest this build re-shapes from scratch (``reset``, ``seed``): its epoch is this build's."""
    return store_epoch.stamped(record, raise_to=store_epoch.STORE_EPOCH)


def existing_namespace(ns_id: str, env: Mapping[str, str]) -> Layout:
    """A namespace that provably exists (its manifest names it) — never an arbitrary directory."""
    item = layout(ns_id, env)
    if _namespace_manifest(item) is None:
        raise NamespaceRefused(Reason.NOT_FOUND, f"no namespace {ns_id!r} at {item.root} (no {MANIFEST_NAME})")
    return item


def busy_reason(item: Layout) -> str | None:
    """Why a serve may be using this namespace now, or ``None``. Unclassifiable counts as busy."""
    lock = _separate_serve_evidence().lock_path(item.store_root)
    if lock is not None and lock.is_file():
        with open(lock, "a+b") as handle:
            try:
                try_lock_exclusive(handle)
            except LockUnavailable:
                return "socket_lock_held"
            unlock(handle)
    return _rows_busy(item)


@contextmanager
def _exclusive(item: Layout) -> Iterator[None]:
    """Hold the namespace's socket lock for the body, or refuse ``namespace_busy``."""
    lock = _separate_serve_evidence().lock_path(item.store_root)
    handle = None
    if lock is not None and lock.is_file():
        handle = open(lock, "a+b")
        try:
            try_lock_exclusive(handle)
        except LockUnavailable:
            handle.close()
            raise NamespaceRefused(Reason.BUSY, f"a serve holds {lock}") from None
    try:
        reason = _rows_busy(item)
        if reason:
            raise NamespaceRefused(Reason.BUSY, f"namespace {item.id!r} is in use ({reason})")
        yield
    finally:
        if handle is not None:
            unlock(handle)
            handle.close()


def _rows_busy(item: Layout) -> str | None:
    for row in _separate_serve_evidence().busy_rows(item.store_root):
        return f"serve_instance_{row.get('classification')}:{row.get('pid')}"
    return None


def _refuse_own(ns_id: str, env: Mapping[str, str]) -> None:
    if str(env.get(ENV) or "") == ns_id:
        raise NamespaceRefused(Reason.IN_USE_BY_THIS_PROCESS, f"this process runs in namespace {ns_id!r}")


def _rm(path: Path) -> None:
    def _writable(func, target, _exc) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.is_dir() and not path.is_symlink():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_writable)
        else:  # pragma: no cover - 3.11
            shutil.rmtree(path, onerror=lambda f, t, e: _writable(f, t, e))
    else:
        path.unlink(missing_ok=True)


def _empty_keeping_lock(item: Layout) -> None:
    """Remove every entry of the namespace except the manifest and the (held) socket lock file."""
    lock = _separate_serve_evidence().lock_path(item.store_root)
    for entry in item.root.iterdir():
        if entry.name == MANIFEST_NAME:
            continue
        if entry == item.store_root:
            for child in entry.iterdir():
                if child != lock:
                    _rm(child)
            continue
        _rm(entry)


def _resettable(ns_id: str, env: Mapping[str, str]) -> tuple[Layout, bool]:
    """``(layout, made)``: a namespace, or a folder hermes never made one of (``made`` False).

    RT-QA-LANE-FOLDER-NEITHER-SEEDABLE-NOR-RESETTABLE (ruling 2026-11-15, REVIEW_W1114A_B42): a QA lane
    folder with NO manifest file (a launch wrote into it before any seed) is reset like a namespace, so the
    one-time seed can follow; the seed itself never treats such a folder as fresh. Only a real directory
    directly under the namespaces dir, named by a valid id that is not ``base`` (``layout``) and not the
    caller's own (``reset``); an unreadable or foreign manifest stays ``namespace_not_found``.
    """
    item = layout(ns_id, env)
    if _namespace_manifest(item) is not None:
        return item, True
    lane_folder = (item.root.is_dir() and not item.root.is_symlink() and not item.manifest_path.exists()
                   and item.root.resolve().parent == item.namespaces_dir.resolve())
    if not lane_folder:
        raise NamespaceRefused(Reason.NOT_FOUND, f"no namespace {ns_id!r} at {item.root} (no {MANIFEST_NAME})")
    return item, False


def reset(ns_id: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Empty a namespace back to a fresh manifest (a seed is allowed again) — a manifest-less lane
    folder under the namespaces dir too, which then becomes a namespace (``made_now``)."""
    _refuse_own(validate_id(ns_id), env)
    item, made = _resettable(ns_id, env)
    with _exclusive(item):
        _empty_keeping_lock(item)
    lock = _separate_serve_evidence().lock_path(item.store_root)
    if lock is not None:
        _rm(lock)
    if item.store_root.is_dir() and not any(item.store_root.iterdir()):
        item.store_root.rmdir()
    origin = namespace_origin(_namespace_manifest(item), item.id)  # a reset keeps what kind of namespace it is
    _write_manifest(item, restamped({"schema": 1, "id": item.id, "created_at": _now(), "reset_at": _now(),
                                     "origin": origin}))
    reply = {"ok": True, "verb": "reset", "id": item.id, "root": str(item.root)}
    return reply if made else {**reply, "made_now": True}


def delete(ns_id: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Remove a namespace from the disk (Q10: the explicit action or an erasure signal, never sign-out)."""
    _refuse_own(validate_id(ns_id), env)
    item = existing_namespace(ns_id, env)
    with _exclusive(item):
        _empty_keeping_lock(item)
    origin = namespace_origin(_namespace_manifest(item), item.id)
    _rm(item.root)
    return {"ok": True, "verb": "delete", "id": item.id, "origin": origin, "root": str(item.root)}


def _namespace_bytes(root: Path) -> int:
    total = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(folder, d))]
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


def _last_serve(item: Layout) -> str | None:
    evidence = _separate_serve_evidence()
    marks = [mark for mark in (evidence.owner_path(item.store_root),) if mark is not None]
    folder = evidence.instances_dir(item.store_root)
    if folder is not None and folder.is_dir():
        marks.extend(folder.iterdir())
    times = [p.stat().st_mtime for p in marks if p.is_file()]
    return datetime.fromtimestamp(max(times), UTC).isoformat(timespec="seconds") if times else None


def list_namespaces(env: Mapping[str, str]) -> dict[str, Any]:
    """Every namespace of this install: id, kind, size, last serve, busy. Reports; never chooses.

    Its one write: a namespace seeded from the base root before ``SEEDED_INTO.json`` existed is
    recorded in that marker (idempotent), named in ``base_root_marked_seeded_into``.
    """
    base = base_root(env)
    folder = namespaces_dir(env, base)
    rows = []
    manifests: dict[str, dict[str, Any]] = {}
    for entry in sorted(folder.iterdir()) if folder.is_dir() else []:
        try:
            item = layout(validate_id(entry.name), env, long_paths=True)
        except NamespaceRefused:
            continue
        manifest = _namespace_manifest(item)
        if manifest is None:
            continue
        rows.append({
            "id": item.id, "kind": namespace_kind(item.id), "origin": namespace_origin(manifest, item.id),
            "root": str(item.root),
            "size_bytes": _namespace_bytes(item.root), "last_serve_at": _last_serve(item), "busy": busy_reason(item),
            "created_at": manifest.get("created_at"), "seeded_from": manifest.get("seeded_from"),
        })
        manifests[item.id] = manifest
    out = {"ok": True, "verb": "list", "base_root": str(base), "namespaces_dir": str(folder), "namespaces": rows}
    try:  # RT-BASE-ROOT-STALE-AFTER-SEED: a seed that predates the marker is recorded in the base root once
        from .namespace_seed.superseded import backfill
    except ImportError:  # the bundled closure ships no seed machinery, and seeds nothing
        return out
    out["base_root_marked_seeded_into"] = backfill(
        base, folder, ({"id": key, "manifest": value} for key, value in manifests.items()))
    return out
