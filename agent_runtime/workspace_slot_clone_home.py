"""The Harness's default clone folder for a slot not set up on this machine (row RT-SLOT-DEFAULT-CLONE-FOLDER).

Owner ruling 2026-11-13 (Eternia ``MC-SLOT-JOIN-ONE-PROMPT-SETUP``): when Eternia offers to set a workspace's
slots up on a computer, its "Clone into" folder defaults to one the Harness owns, inside the account's
namespace and organized by realm::

    <namespace>/repos/<realm folder>/<slot>

``<namespace>`` is the folder that holds the runtime store (``agent-runtime/``). ``<realm folder>`` is a
filesystem-safe form of the realm's display name, FIXED the first time a realm is given one: the mapping
realm id -> folder is persisted in ``<store>/realm_repo_folders.json`` so a renamed realm keeps its clones
where they are; a second realm whose name gives the same folder takes ``-2``, ``-3`` … Inside one realm a
repository (same normalized clone URL) is cloned ONCE: a slot of any workspace of the realm already bound
here to that repository under ``repos/<realm folder>/`` gives its path as the default (the client binds it
rather than clones). A ``<slot>`` folder already used by a different repository — bound to it, or on disk
and not a checkout of this one — is suffixed ``<slot>-2``, ``-3`` …

This is only the default answer: nothing here clones, and the mapping file is the one thing written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from . import paths

__layer__ = "stores"

REPOS_DIRNAME = "repos"
#: The store-root file of the realm id -> folder mapping (``realm_rekey.STORE_PLACES``: it moves with a re-key).
FOLDERS_FILENAME = "realm_repo_folders.json"
FOLDERS_SCHEMA = 1
#: The mapping key and display name of a workspace placed in no realm.
NO_REALM_KEY = ""
NO_REALM_NAME = "local"

_UNSAFE_RE = re.compile(r"[^\w.-]+")
_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                               *(f"lpt{n}" for n in range(1, 10))})
_MAX_FOLDER = 64


def namespace_root() -> Path:
    """The account namespace: the folder holding the runtime store (``<namespace>/agent-runtime``)."""

    return paths.store_root().parent


def repos_root() -> Path:
    return namespace_root() / REPOS_DIRNAME


def folders_path() -> Path:
    return paths.store_root() / FOLDERS_FILENAME


def safe_folder_name(name: str, *, fallback: str) -> str:
    """``name`` as one folder name every OS accepts: word characters, ``.`` and ``-``, at most 64."""

    text = _UNSAFE_RE.sub("-", str(name or "").strip()).strip(".-")[:_MAX_FOLDER].strip(".-")
    if not text:
        return fallback
    return f"{text}_" if text.lower().split(".", 1)[0] in _WINDOWS_RESERVED else text


def _suffixed(base: str, taken) -> str:
    candidate, n = base, 2
    while candidate.lower() in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _load_folders() -> dict[str, str]:
    try:
        payload = json.loads(folders_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    folders = payload.get("folders") if isinstance(payload, dict) else None
    return {str(k): str(v) for k, v in folders.items() if isinstance(v, str) and v} if isinstance(folders, dict) else {}


def realm_folder(realm_id: str | None, display_name: str) -> str:
    """The realm's folder under ``repos/``: the persisted one, else fixed now from ``display_name``."""

    from .locks import realm_repo_folders_lock

    key = realm_id or NO_REALM_KEY
    with realm_repo_folders_lock():
        folders = _load_folders()
        if key in folders:
            return folders[key]
        taken = {folder.lower() for folder in folders.values()}
        folder = _suffixed(safe_folder_name(display_name, fallback="realm"), taken)
        folders[key] = folder
        folders_path().parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(folders_path(), {"schema_version": FOLDERS_SCHEMA, "folders": folders})
    return folder


def _realm_of(workspace_id: str) -> tuple[str | None, str]:
    from .errors import NotFound
    from .store import RealmStore, WorkspaceStore

    realm_id = WorkspaceStore().get(workspace_id).realm_id
    if not realm_id:
        return None, NO_REALM_NAME
    try:
        return realm_id, RealmStore().get(realm_id).name
    except NotFound:  # a realm record not on this machine: its id is the only name there is
        return realm_id, realm_id


def _realm_workspaces(realm_id: str | None, workspace_id: str) -> list[str]:
    from .store import WorkspaceStore

    ids = [ws.id for ws in WorkspaceStore().list_all(include_archived=False) if (ws.realm_id or None) == realm_id]
    return sorted(set(ids) | {workspace_id})


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


class _Bindings:
    """This machine's slot bindings, each with the normalized clone URL its workspace declares for it."""

    def __init__(self) -> None:
        from .workspace_slots import live_slots, load_document, scoped_roots
        from .workspace_slots_probe import _normalize_remote

        self.rows: list[tuple[str, Path, str]] = []  # (workspace id, bound path, normalized url)
        for workspace_id, fills in scoped_roots().workspace_roots.items():
            declared = live_slots(load_document(workspace_id))
            for slot, path in fills.items():
                url = str(((declared.get(slot) or {}).get("repo") or {}).get("clone_url") or "")
                if path:
                    self.rows.append((workspace_id, Path(path), _normalize_remote(url) if url else ""))

    def shared_clone(self, url: str, workspaces: list[str], realm_dir: Path) -> Path | None:
        """A folder under ``realm_dir`` a slot of the realm binds to ``url`` and that exists here."""

        for workspace_id, path, bound_url in self.rows:
            if bound_url == url and workspace_id in workspaces and path.is_dir() and _inside(path, realm_dir):
                return path
        return None

    def other_repo_at(self, candidate: Path, url: str) -> bool:
        target = str(candidate.resolve()).lower()
        return any(bound_url != url and str(path.resolve()).lower() == target for _, path, bound_url in self.rows)


def _free_on_disk(candidate: Path, slot: dict[str, Any]) -> bool:
    """Absent, an empty directory, or already a checkout of this repository."""

    from .workspace_slots_probe import origin_matches

    if not candidate.exists():
        return True
    return candidate.is_dir() and (not any(candidate.iterdir()) or origin_matches(candidate, slot))


def default_clone_paths(workspace_id: str, document: dict[str, Any], here: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    """``{slot: default clone path or None}`` for every slot of ``here`` (``workspace_slots.show``'s rows).

    None when the slot is bound and ready here, local-only, or declares no clone URL.
    """

    from .workspace_slots import live_slots
    from .workspace_slots_probe import _normalize_remote

    declared = live_slots(document)
    wanted = {name: declared.get(name) or {} for name, row in here.items() if not row.get("bound_here")}
    wanted = {name: slot for name, slot in wanted.items()
              if (slot.get("repo") or {}).get("clone_url") and (slot.get("repo") or {}).get("local") is not True}
    answers: dict[str, str | None] = dict.fromkeys(here)
    if not wanted:
        return answers
    realm_id, realm_name = _realm_of(workspace_id)
    realm_dir = repos_root() / realm_folder(realm_id, realm_name)
    workspaces, bindings = _realm_workspaces(realm_id, workspace_id), _Bindings()
    offered: set[str] = set()
    by_url: dict[str, str] = {}  # two unbound slots of one repository share one clone too
    for name, slot in sorted(wanted.items()):
        url = _normalize_remote(str(slot["repo"]["clone_url"]))
        shared = bindings.shared_clone(url, workspaces, realm_dir)
        if shared is not None or url in by_url:
            answers[name] = str(shared) if shared is not None else by_url[url]
            continue
        base = safe_folder_name(name, fallback="repo")
        candidate, n = realm_dir / base, 2
        while (str(candidate).lower() in offered or bindings.other_repo_at(candidate, url)
               or not _free_on_disk(candidate, slot)):
            candidate, n = realm_dir / f"{base}-{n}", n + 1
        offered.add(str(candidate).lower())
        answers[name] = by_url[url] = str(candidate)
    return answers
