"""The places a realm re-key reaches that are not JSON under the store root
(RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE).

Plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §3. Each is one small part of the
``outside`` step, and each does nothing where the old id is gone:

* **The machine's own files**, beside the store: ``machine_roots.json`` (the folder each workspace's slots are
  bound to here), ``machine_slot_env.json`` and ``machine_slot_runs.json`` — JSON, rewritten by value and key
  like the store's.
* **Lens**: a watch belongs to a workspace by its ``monitors.workspace_id`` column (``lens/store_scope.py``).
* **Shared skills**: what the realm delivered and nobody promoted yet waits in ``.realm_inbox/<realm>/``, and a
  promoted skill's provenance names the realm it came from (``source.realm_id``).
* **The local copy's version history**: a local realm publishes to the ``local`` sync repository, under
  ``realms/<realm>/``. The subtree is moved with ``git mv``, the ids inside it rewritten as whole tokens (a
  later pull would otherwise hand the old workspace files back), and committed once; earlier commits keep the
  old ids.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from . import paths
from .git_cmd import run_git

__layer__ = "lanes"
__all__ = ["LOCAL_SYNC_REPO", "step_outside"]

#: ``realm_sync/git.py`` keys a server-less realm's sync repository by this name.
LOCAL_SYNC_REPO = "local"
_SYNC_IDENTITY = ("user.name=Hermes Realm Sync", "user.email=realm-sync@localhost")


def _machine_files() -> list[Path]:
    from .machine_roots import machine_roots_registry_paths
    from .workspace_slot_env import slot_env_path
    from .workspace_slot_runs import runs_path

    return [*machine_roots_registry_paths(), slot_env_path(), runs_path()]


def _rekey_machine_files(mapping: Any) -> None:
    from .machine_roots import machine_roots_cache_clear
    from .realm_rekey import rewrite_json

    forms = mapping.forms()
    for path in _machine_files():
        try:
            before = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        after = rewrite_json(before, forms)
        if after != before:
            atomic_json_write(path, after, indent=2, sort_keys=True)
    machine_roots_cache_clear()


def _rekey_lens(mapping: Any) -> None:
    from .lens.store import default_path

    path = default_path()
    if not path.is_file():
        return
    try:
        with sqlite3.connect(path, timeout=10) as connection:
            connection.executemany("UPDATE monitors SET workspace_id = ? WHERE workspace_id = ?",
                                   [(new, old) for old, new in mapping.workspaces.items()])
    except sqlite3.Error:
        return  # a store older than the workspace column holds no workspace id


def _rekey_skills(mapping: Any) -> None:
    from .realm_rekey import merge_folder
    from .skill_promotion import provenance_root, realm_inbox_dir

    old, new = realm_inbox_dir(mapping.realm_old), realm_inbox_dir(mapping.realm_new)
    if old.is_dir():
        if new.exists():
            merge_folder(old, new)
        else:
            old.rename(new)
    records = provenance_root()
    for path in sorted(records.glob("*.json")) if records.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        source = record.get("source") if isinstance(record, dict) else None
        if isinstance(source, dict) and source.get("realm_id") == mapping.realm_old:
            atomic_json_write(path, {**record, "source": {**source, "realm_id": mapping.realm_new}}, indent=2, sort_keys=True)


def _sync_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_git(list(args), repo=repo, config=_SYNC_IDENTITY, timeout=120, stdin=subprocess.DEVNULL, encoding="utf-8")


def _rekey_local_history(mapping: Any) -> None:
    from .realm_rekey import token_pattern

    repo = paths.realm_sync_root() / LOCAL_SYNC_REPO
    old, new = (Path("realms") / paths.safe_path_token(realm) for realm in (mapping.realm_old, mapping.realm_new))
    if not (repo / ".git").exists():
        return
    if (repo / old).exists() and not (repo / new).exists():
        _sync_git(repo, "mv", old.as_posix(), new.as_posix())
    subtree = repo / new
    if not subtree.is_dir():
        return
    forms, names = mapping.forms(), mapping.name_forms()
    pattern = token_pattern(forms)
    for path in sorted(subtree.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file():
            try:
                text = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            rewritten = pattern.sub(lambda match: forms[match.group(1)], text)
            if rewritten != text:
                path.write_bytes(rewritten.encode("utf-8"))
        stem, dot, rest = path.name.partition(".")
        renamed = names.get(path.name) or (names[stem] + dot + rest if dot and stem in names else None)
        if renamed and not path.with_name(renamed).exists():
            path.rename(path.with_name(renamed))
    _sync_git(repo, "add", "-A", "--", "realms")
    if _sync_git(repo, "status", "--porcelain", "--", "realms").stdout.strip():
        _sync_git(repo, "commit", "-q", "-m", f"realm {mapping.realm_new}: this copy's own ids (was {mapping.realm_old})",
                  "--", "realms")


_PARTS = (_rekey_machine_files, _rekey_lens, _rekey_skills, _rekey_local_history)


def step_outside(root: Path, mapping: Any) -> None:
    for part in _PARTS:
        part(mapping)
