"""``hermes namespace list | seed | reset | delete`` — the namespace admin verbs (row RT-NAMESPACE-CLI).

Plan: ``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md``
§2.4, §2.8, §3, §4 H3; owner rulings Q3/Q4 (persistent QA namespace, explicit reset; the seed
carries config, SOUL, skills, skins, world and persona definitions, never credentials, sessions,
pairing or realm_sync), Q10 (a namespace leaves the disk only by ``delete``) and Q11 (a namespace
is seeded AT MOST ONCE, when it is created — never per launch; ``reset`` empties it, after which a
seed is again an explicit operator act).

The allowlists and :data:`NEVER_SEED` moved here from the launcher's
``EterniaLauncher/tool/stagec_qa_mcp_server/lib/hermes_parity_seed.dart``; this module is now the
one authority. Persona DEFINITIONS (``agent-runtime/agents/``) are seeded; persona INSTANCES
(``agent-runtime/persona_instances/``) are not — an instance record carries its source's
``runtime_root``, ``chat_head_home`` and session ids, so a copy would point the new namespace back
into the old one; instances re-mint from the definitions.

Every verb names its namespaces explicitly; nothing here enumerates ``hermes-namespaces/`` to pick
a source (``list`` reports, it never chooses). ``reset`` and ``delete`` hold the namespace's socket
lock while they remove, and refuse while a serve holds it or a registered serve is live or
unclassifiable.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_cli._namespace_bootstrap import (
    ACCOUNT_ID,
    BASE_ID,
    ENV,
    MANIFEST_NAME,
    STORE_DIRNAME,
    Layout,
    NamespaceRefused,
    Reason,
    base_root,
    ensure_manifest,
    layout,
    namespaces_dir,
    validate_id,
)

from .file_locks import LockUnavailable, try_lock_exclusive, unlock
from .serve_registry import CLASSIFICATION_LIVE, CLASSIFICATION_UNKNOWN, list_serve_instances, serve_instances_dir
from .serve_socket.owner_lock import socket_lock_path, socket_owner_path

__layer__ = "lanes"

#: Profile-home entries a seed copies (the root's own and each ``profiles/<name>/``'s).
HOME_SEED = ("config.yaml", "SOUL.md", "skills", "skins")
#: Runtime-store entries: the world definitions and the persona definitions.
STORE_SEED = ("realms", "workspaces", "levels", "maps", "office", "active_realm.json", "active_workspace.json", "agents")
#: Root entries: the machine-root registry.
ROOT_SEED = ("machine_roots.json",)
#: Names a seed never copies at ANY depth, whatever an allowlist says.
NEVER_SEED = re.compile(
    r"^(auth\.json|auth\.lock|credential_rotation\.json|\.env.*|"
    r".*(token|secret|credential|password).*|.*\.db(-shm|-wal)?|state\.db.*|"
    r"sessions|pairing|memories|backups|state-snapshots|chat_live_logs|logs|"
    r"realm_sync|\.git|secure-store|gateway|install_id|persona_instances)$",
    re.IGNORECASE,
)


def allowlist_violations(names: tuple[str, ...]) -> list[str]:
    """Entries no seed may copy: a never-seed name, or anything that is not one plain path segment."""
    return [
        name for name in names
        if name != name.strip() or name in ("", ".", "..") or "/" in name or "\\" in name or NEVER_SEED.match(name)
    ]


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


def _existing(ns_id: str, env: Mapping[str, str]) -> Layout:
    """A namespace that provably exists (its manifest names it) — never an arbitrary directory."""
    item = layout(ns_id, env)
    if _namespace_manifest(item) is None:
        raise NamespaceRefused(Reason.NOT_FOUND, f"no namespace {ns_id!r} at {item.root} (no {MANIFEST_NAME})")
    return item


def busy_reason(item: Layout) -> str | None:
    """Why a serve may be using this namespace now, or ``None``. Unclassifiable counts as busy."""
    lock = socket_lock_path(item.store_root)
    if lock.is_file():
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
    lock = socket_lock_path(item.store_root)
    handle = None
    if lock.is_file():
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
    for row in list_serve_instances(item.store_root):
        if row.get("classification") in (CLASSIFICATION_LIVE, CLASSIFICATION_UNKNOWN):
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
    lock = socket_lock_path(item.store_root)
    for entry in item.root.iterdir():
        if entry.name == MANIFEST_NAME:
            continue
        if entry == item.store_root:
            for child in entry.iterdir():
                if child != lock:
                    _rm(child)
            continue
        _rm(entry)


def reset(ns_id: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Empty a namespace back to a fresh manifest (a seed is allowed again)."""
    _refuse_own(validate_id(ns_id), env)
    item = _existing(ns_id, env)
    with _exclusive(item):
        _empty_keeping_lock(item)
    _rm(socket_lock_path(item.store_root))
    if item.store_root.is_dir() and not any(item.store_root.iterdir()):
        item.store_root.rmdir()
    _write_manifest(item, {"schema": 1, "id": item.id, "created_at": _now(), "reset_at": _now()})
    return {"ok": True, "verb": "reset", "id": item.id, "root": str(item.root)}


def delete(ns_id: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Remove a namespace from the disk (Q10: the explicit action or an erasure signal, never sign-out)."""
    _refuse_own(validate_id(ns_id), env)
    item = _existing(ns_id, env)
    with _exclusive(item):
        _empty_keeping_lock(item)
    _rm(item.root)
    return {"ok": True, "verb": "delete", "id": item.id, "root": str(item.root)}


def _copy(src: Path, dst: Path, copied: list[str], rel: str, skipped: list[str]) -> None:
    """Copy one allowlisted entry; a never-seed name or a link at any depth is skipped AND accounted."""
    if src.is_symlink() or NEVER_SEED.match(src.name):
        skipped.append(rel)
        return
    if not src.exists():
        return

    def _skip(directory: str, names: list[str]) -> set[str]:
        out = {n for n in names if NEVER_SEED.match(n) or os.path.islink(os.path.join(directory, n))}
        skipped.extend(f"{rel}/" + os.path.relpath(os.path.join(directory, n), src).replace(os.sep, "/")
                       for n in sorted(out))
        return out

    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=False, ignore=_skip, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    copied.append(rel)


def seed(target_id: str, source: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Copy the allowlist from ``base`` or a NAMED namespace into a freshly created namespace, once."""
    item = layout(target_id, env)
    source = validate_id(source)
    if source == item.id:
        raise NamespaceRefused(Reason.SEED_SOURCE, "a namespace cannot seed itself")
    src_root = item.base_root if source == BASE_ID else _existing(source, env).root
    if not src_root.is_dir():
        raise NamespaceRefused(Reason.NOT_FOUND, f"the seed source {src_root} does not exist")
    bad = allowlist_violations(HOME_SEED + STORE_SEED + ROOT_SEED)
    if bad:
        raise NamespaceRefused(Reason.SEED_SOURCE, f"the seed allowlist names never-seed entries {bad}; nothing copied")
    ensure_manifest(item)
    manifest = _namespace_manifest(item) or {}
    if manifest.get("seeded_at"):
        raise NamespaceRefused(Reason.ALREADY_SEEDED,
                               f"{item.id!r} was seeded from {manifest.get('seeded_from')!r} at {manifest['seeded_at']}; "
                               "a namespace is seeded at most once — `hermes namespace reset` first")
    used = sorted(p.name for p in item.root.iterdir() if p.name != MANIFEST_NAME)
    if used:
        raise NamespaceRefused(Reason.NOT_FRESH, f"{item.id!r} already holds {used}; seed only at creation")
    copied: list[str] = []
    skipped: list[str] = []
    with _exclusive(item):
        for name in ROOT_SEED + HOME_SEED:
            _copy(src_root / name, item.root / name, copied, name, skipped)
        profiles = src_root / "profiles"
        for profile in sorted(profiles.iterdir()) if profiles.is_dir() else []:
            if profile.is_dir() and not profile.name.startswith(".") and not allowlist_violations((profile.name,)):
                for name in HOME_SEED:
                    _copy(profile / name, item.root / "profiles" / profile.name / name, copied,
                          f"profiles/{profile.name}/{name}", skipped)
        for name in STORE_SEED:
            _copy(src_root / STORE_DIRNAME / name, item.store_root / name, copied, f"{STORE_DIRNAME}/{name}", skipped)
    _write_manifest(item, {**manifest, "seeded_from": source, "seeded_at": _now(), "seeded": copied, "skipped": skipped})
    return {"ok": True, "verb": "seed", "id": item.id, "from": source, "copied": copied, "skipped": skipped}


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
    marks = [socket_owner_path(item.store_root)]
    folder = serve_instances_dir(item.store_root)
    if folder.is_dir():
        marks.extend(folder.iterdir())
    times = [p.stat().st_mtime for p in marks if p.is_file()]
    return datetime.fromtimestamp(max(times), UTC).isoformat(timespec="seconds") if times else None


def list_namespaces(env: Mapping[str, str]) -> dict[str, Any]:
    """Every namespace of this install: id, kind, size, last serve, busy. Reports; never chooses."""
    base = base_root(env)
    folder = namespaces_dir(env, base)
    rows = []
    for entry in sorted(folder.iterdir()) if folder.is_dir() else []:
        try:
            item = layout(validate_id(entry.name), env, long_paths=True)
        except NamespaceRefused:
            continue
        manifest = _namespace_manifest(item)
        if manifest is None:
            continue
        rows.append({
            "id": item.id, "kind": "account" if ACCOUNT_ID.fullmatch(item.id) else "profile", "root": str(item.root),
            "size_bytes": _namespace_bytes(item.root), "last_serve_at": _last_serve(item), "busy": busy_reason(item),
            "created_at": manifest.get("created_at"), "seeded_from": manifest.get("seeded_from"),
        })
    return {"ok": True, "verb": "list", "base_root": str(base), "namespaces_dir": str(folder), "namespaces": rows}
