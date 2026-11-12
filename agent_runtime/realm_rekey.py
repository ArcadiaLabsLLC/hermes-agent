"""The one owned re-key of a realm that turned local (RT-REKEY-ONE-OWNED-OPERATION).

Plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §3, §4. A realm whose server the
member left is to sit BESIDE the fresh copy a re-join pulls, so the local copy needs a realm id, workspace ids
and board ids the team's copy does not publish. Nothing else in the tree renames a realm or a workspace, and
NOTHING CALLS THIS YET: the leave does not owe a re-key and a re-join still binds the same realm id again
(``realm_leave``, ``realm_membership.adopt_realms``) until the task's switch-over row lands.

* :data:`STORE_PLACES` puts every top-level entry of the store root in one :class:`PlaceClass`. MOVES is the
  local copy (re-keyed); PARKS keeps the team's ids until a re-join brings the realm back (the agents and every
  chat); HISTORY and DERIVED are never touched. ``tests/agent_runtime/test_realm_rekey_census.py`` keeps the
  table total over ``paths.py``.
* :func:`owe_rekey` mints the id map once and writes it to the journal (``realm_rekey/<old realm>.json``) before
  anything moves, so a resumed run uses the same new ids.
* :func:`rekey_realm` runs the steps under the workspace/realm assign lock. Each step does nothing where the old
  shape is gone, so a run killed anywhere is finished by running it again. JSON is rewritten by VALUE and KEY —
  a whole string, or a whole ``/`` ``\\`` ``:`` separated piece of one — never by text search, so an id that is
  a prefix of another id is never hit.
* :func:`leftover_ids` is the census: where an old id still shows under the store root, by place class.

Still owed, each a place :data:`OWED_HANDLERS` names (the switch-over waits for them): brain markdown and git
worktrees (``RT-REKEY-BRAIN-AND-WORKTREES-FOLLOW``), the agents (``RT-REKEY-LOCAL-COPY-GETS-NEW-AGENTS``), and
the places outside the JSON store (``RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE``).
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from . import paths
from .board_models import default_board_id
from .locks import workspace_realm_assign_lock
from .store import RealmStore, WorkspaceStore

__layer__ = "lanes"
__all__ = [
    "OWED_HANDLERS",
    "STORE_PLACES",
    "PlaceClass",
    "RekeyMap",
    "RekeyState",
    "leftover_ids",
    "owe_rekey",
    "place_class",
    "read_rekey_journal",
    "rekey_journal_path",
    "rekey_realm",
]

JOURNAL_DIRNAME = "realm_rekey"
#: The level document's one embedded id: its store address (``EterniaLauncher`` ``level_ref.dart``).
SCENE_ID_PREFIX = "ws-"
_PIECES = re.compile(r"([/\\:])")
_MINTED_SUFFIX = re.compile(r"_[0-9a-f]{6}$")


class PlaceClass(str, Enum):
    MOVES = "moves"
    PARKS = "parks"
    HISTORY = "history"
    DERIVED = "derived"


class RekeyState(str, Enum):
    OWED = "owed"
    RUNNING = "running"
    DONE = "done"


_M, _P, _H, _D = PlaceClass.MOVES, PlaceClass.PARKS, PlaceClass.HISTORY, PlaceClass.DERIVED
#: Every top-level entry of the store root that can hold a realm, workspace, board or agent id.
STORE_PLACES: dict[str, PlaceClass] = {
    "realms": _M, "workspaces": _M, "workspace_slots": _M, "office": _M, paths.OFFICE_ARCHIVE_DIRNAME: _M,
    "boards": _M, paths.LEVELS_DIRNAME: _M, "slot_worktrees": _M, paths.WORK_DIRNAME: _M, "schedules": _M,
    paths.REALM_SYNC_DIRNAME: _M, "realm_sync_state": _M, "active_workspace.json": _M, "active_realm.json": _M,
    "default_realm.json": _M, "brain_paths.json": _M,
    "persona_instances": _P, "persona_assignments": _P, paths.CHAT_FOLDERS_DIRNAME: _P, "workspace_chats": _P,
    "workspace_chat_fold": _P, "workspace_chat_exports": _P, "persona_chat_mint_receipts": _P,
    "chat_goal_bindings": _P, "chat_goal_parks": _P, "agent_create_reservations": _P, "state.db": _P,
    "persona_instances_archive": _H, "persona_assignments_archive": _H, "events.jsonl": _H,
    "events_archive": _H, "prompt_observability": _H, "prompt_observability_archive": _H, "patch_diffs": _H,
    "patch_diffs_archive": _H, paths.DELETED_ARCHIVE_DIRNAME: _H, "runs": _H, "incidents": _H, "agents": _H,
    "migration_backups": _H, JOURNAL_DIRNAME: _H,
    "snapshot.json": _D, paths.DERIVED_CACHE_DIRNAME: _D, "locks": _D,
}
#: MOVES places this module does not rewrite yet, and the row that owes each.
OWED_HANDLERS: dict[str, str] = {
    "work/<ws>/brain/*.md + git worktrees": "RT-REKEY-BRAIN-AND-WORKTREES-FOLLOW",
    "persona_instances + office actor keys + flow-graph owners": "RT-REKEY-LOCAL-COPY-GETS-NEW-AGENTS",
    "realm_sync/local clone subtree": "RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE",
    "lens.sqlite3 monitors": "RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE",
    "machine_roots.json slot folders": "RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE",
    "skills .realm_inbox + provenance": "RT-REKEY-PLACES-OUTSIDE-THE-JSON-STORE",
}


def place_class(relative: Path) -> PlaceClass | None:
    """The class of a path under the store root, or ``None`` for an entry the table does not know."""
    parts = relative.parts
    if not parts:
        return None
    if parts[0] == paths.WORK_DIRNAME and len(parts) > 1 and parts[1].startswith("workspace_chats_"):
        return PlaceClass.PARKS  # shared chats are chats: they wait for the re-join
    if ".git" in parts:
        return PlaceClass.HISTORY  # a brain's or a sync clone's object store
    if parts[0] == paths.REALM_SYNC_DIRNAME and len(parts) > 1 and (paths.realm_sync_root() / parts[1] / ".git").exists():
        return PlaceClass.HISTORY  # a sync clone (the publish projection): OWED_HANDLERS
    return STORE_PLACES.get(parts[0])


@dataclass
class RekeyMap:
    realm_old: str
    realm_new: str
    workspaces: dict[str, str] = field(default_factory=dict)
    boards: dict[str, str] = field(default_factory=dict)

    def forms(self) -> dict[str, str]:
        """Every whole token that is rewritten: the ids, and the level address ``ws-<workspace>``."""
        forms = {self.realm_old: self.realm_new, **self.boards, **self.workspaces}
        forms.update({SCENE_ID_PREFIX + old: SCENE_ID_PREFIX + new for old, new in self.workspaces.items()})
        return forms



def rekey_journal_path(realm_id: str) -> Path:
    return paths.store_root() / JOURNAL_DIRNAME / f"{paths.safe_path_token(realm_id)}.json"


def read_rekey_journal(realm_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(rekey_journal_path(realm_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_journal(journal: dict[str, Any]) -> dict[str, Any]:
    path = rekey_journal_path(journal["map"]["realm_old"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, journal)
    return journal


def _fresh_id(old: str) -> str:
    """The same readable id with a new minted suffix: ``ws_design_ab12cd`` → ``ws_design_9f03e1``."""
    return f"{_MINTED_SUFFIX.sub('', old)[:80]}_{uuid.uuid4().hex[:6]}"


def _boards_of(workspace_ids: set[str]) -> list[str]:
    found = []
    for definition in sorted(paths.boards_root().glob("*/board.json")):
        try:
            board = json.loads(definition.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if board.get("workspace_id") in workspace_ids:
            found.append(str(board.get("board_id") or definition.parent.name))
    return found


def owe_rekey(realm_id: str, *, reason: str) -> dict[str, Any]:
    """Record that ``realm_id`` owes a re-key and mint its map. A realm that already has a journal answers it."""
    with workspace_realm_assign_lock():
        existing = read_rekey_journal(realm_id)
        if existing is not None:
            return existing
        realm = RealmStore().get(realm_id)
        held = [item.id for item in WorkspaceStore().list_all(include_archived=True) if item.realm_id == realm.id]
        workspaces = {old: _fresh_id(old) for old in dict.fromkeys([*realm.workspace_ids, *held])}
        # A default board is made on first use, so its id is mapped whether or not it is on disk yet.
        boards = {default_board_id(old): default_board_id(new) for old, new in workspaces.items()}
        boards.update({board: _fresh_id(board) for board in _boards_of(set(workspaces)) if board not in boards})
        mapping = RekeyMap(realm.id, _fresh_id(realm.id), workspaces, boards)
        return _write_journal({
            "state": RekeyState.OWED.value, "reason": reason, "owed_at": now().isoformat(),
            "map": asdict(mapping), "steps_done": [], "leftover": [],
        })


def _rewrite_text(value: str, forms: dict[str, str]) -> str:
    if value in forms:
        return forms[value]
    if not _PIECES.search(value):
        return value
    return "".join(forms.get(piece, piece) for piece in _PIECES.split(value))


def _rewrite_json(value: Any, forms: dict[str, str]) -> Any:
    rewrite = _JSON_REWRITERS.get(type(value))
    return rewrite(value, forms) if rewrite else value


_JSON_REWRITERS = {
    str: _rewrite_text,
    list: lambda value, forms: [_rewrite_json(item, forms) for item in value],
    dict: lambda value, forms: {_rewrite_text(key, forms): _rewrite_json(item, forms) for key, item in value.items()},
}


def _git_tree_roots(root: Path) -> set[Path]:
    """Every git working tree under the store root (a default brain, a lane worktree, a sync clone)."""
    return {marker.parent for top in (paths.WORK_DIRNAME, paths.REALM_SYNC_DIRNAME) for marker in (root / top).rglob(".git")}


def _moves_files(root: Path) -> list[Path]:
    """Every entry of a MOVES place, deepest first, so a rename never invalidates a path still to visit.
    What sits INSIDE a git working tree is left to the step that commits it (OWED_HANDLERS); the tree's own
    folder moves with its workspace."""
    trees = _git_tree_roots(root)
    found = [
        path for path in root.rglob("*")
        if place_class(path.relative_to(root)) is PlaceClass.MOVES and not any(parent in trees for parent in path.parents)
    ]
    return sorted(found, key=lambda path: len(path.parts), reverse=True)


def _rewrite_level(path: Path, forms: dict[str, str]) -> None:
    """A level is the launcher's bytes: only the top-level ``sceneId`` string is touched, in place."""
    text = path.read_text(encoding="utf-8")
    for old, new in forms.items():
        if old.startswith(SCENE_ID_PREFIX):
            patched = re.sub(r'("sceneId"\s*:\s*")' + re.escape(old) + '"', lambda m: m.group(1) + new + '"', text, count=1)
            if patched != text:
                path.write_text(patched, encoding="utf-8")
                return


def _step_content(root: Path, mapping: RekeyMap) -> None:
    forms = mapping.forms()
    own_realm = {f"{paths.safe_path_token(mapping.realm_old)}.json", f"{paths.safe_path_token(mapping.realm_new)}.json"}
    for path in _moves_files(root):
        relative = path.relative_to(root)
        if not path.is_file() or path.suffix != ".json":
            continue
        if relative.parts[0] == "realms" and path.name not in own_realm:
            continue  # another realm's ledgers name what LEFT it; they are that realm's, not ours
        if relative.parts[0] == paths.LEVELS_DIRNAME:
            _rewrite_level(path, forms)
            continue
        try:
            before = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        after = _rewrite_json(before, forms)
        if after != before:
            atomic_json_write(path, after)


def _renamed(name: str, forms: dict[str, str]) -> str:
    if name in forms:
        return forms[name]
    stem, dot, rest = name.partition(".")
    return forms[stem] + dot + rest if dot and stem in forms else name


def _merge_folder(old: Path, new: Path) -> None:
    """A late writer re-made the old folder after it moved: bring over what the new one lacks. A file both
    hold stays where it is — the new one is the newer — and the census names what is left."""
    for child in sorted(old.iterdir()):
        target = new / child.name
        if not target.exists():
            shutil.move(str(child), str(target))
        elif child.is_dir() and target.is_dir():
            _merge_folder(child, target)
    if not any(old.iterdir()):
        old.rmdir()


def _step_rename(root: Path, mapping: RekeyMap) -> None:
    forms = mapping.forms()
    for path in _moves_files(root):
        target = path.with_name(_renamed(path.name, forms))
        if target == path or not path.exists():
            continue
        if not target.exists():
            path.rename(target)
        elif path.is_dir() and target.is_dir():
            _merge_folder(path, target)


def _step_ledgers(root: Path, mapping: RekeyMap) -> None:
    """The delete ledger and the lifts speak to the team's copy about the team's ids; the local copy starts clean."""
    path = paths.realm_path(mapping.realm_new)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    cleared = {key: type(record[key])() for key in ("deleted_workspace_ids", "workspace_lifts") if record.get(key)}
    if cleared:
        atomic_json_write(path, {**record, **cleared})


STEPS = (("content", _step_content), ("rename", _step_rename), ("ledgers", _step_ledgers))


def rekey_realm(realm_id: str) -> dict[str, Any]:
    """Run, or finish, the owed re-key of ``realm_id`` (its OLD id). Returns the journal, ``done``.

    The caller has already made sure nothing is running in the realm (plan §5); this holds the assign lock so no
    move, archive or leave sees the realm half re-keyed."""
    with workspace_realm_assign_lock():
        journal = read_rekey_journal(realm_id)
        if journal is None:
            raise KeyError(f"realm {realm_id} owes no re-key")
        if journal["state"] == RekeyState.DONE.value:
            return journal
        mapping = RekeyMap(**journal["map"])
        root = paths.store_root()
        journal = _write_journal({**journal, "state": RekeyState.RUNNING.value, "steps_done": []})
        for name, step in STEPS:
            step(root, mapping)
            journal = _write_journal({**journal, "steps_done": [*journal["steps_done"], name]})
        leftover = leftover_ids(root, list(mapping.forms()), only=PlaceClass.MOVES)
        return _write_journal({
            **journal, "state": RekeyState.DONE.value, "done_at": now().isoformat(), "leftover": leftover,
        })


def _sqlite_text(path: Path) -> str:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            return "\n".join(connection.iterdump())
    except sqlite3.Error:
        return ""


def leftover_ids(root: Path, ids: list[str], *, only: PlaceClass | None = None) -> list[dict[str, str]]:
    """Every place under ``root`` where one of ``ids`` still shows, in a file's name or its content:
    ``{"path", "id", "class", "where"}``. ``class`` is the place's class, ``unclassified`` for an entry
    :data:`STORE_PLACES` does not know. ``only`` reads one class and nothing inside a git working tree (what
    the operation checks itself against); without it every file under ``root`` is read."""
    trees = _git_tree_roots(root) if only else set()
    token = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(sorted(map(re.escape, ids), key=len, reverse=True)) + r")(?![A-Za-z0-9_-])")
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        found = place_class(relative)
        if only and (found is not only or any(parent in trees for parent in path.parents)):
            continue
        label = found.value if found else "unclassified"
        for hit in {match.group(1) for match in token.finditer(path.name)}:
            rows.append({"path": relative.as_posix(), "id": hit, "class": label, "where": "name"})
        if not path.is_file():
            continue
        if path.suffix in (".db", ".sqlite3"):
            text = _sqlite_text(path)
        else:
            text = path.read_bytes().decode("utf-8", errors="ignore")
        for hit in {match.group(1) for match in token.finditer(text)}:
            rows.append({"path": relative.as_posix(), "id": hit, "class": label, "where": "content"})
    return rows
