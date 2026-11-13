"""The one owned re-key of a realm that turned local (RT-REKEY-ONE-OWNED-OPERATION).

Plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §3, §4. A realm whose server the
member left is to sit BESIDE the fresh copy a re-join pulls, so the local copy needs a realm id, workspace ids
and board ids the team's copy does not publish. Nothing else in the tree renames a realm or a workspace. The leave
owes it (``realm_leave.make_realm_local`` calls :func:`owe_rekey`); ``agent_runtime.realm_rekey_triggers`` is
the one caller of :func:`rekey_realm` — at the leave, when the serve is idle, at serve start, before a re-join.

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

* The agents are ``agent_runtime.realm_rekey_agents`` (the ``agents`` step, first): the team's agents park, the
  local copy gets new ones of the same personas, and the generic steps re-point desks, flow graphs, schedules
  and open Work claims at them.

* Git is ``agent_runtime.realm_rekey_git`` (the ``git`` step, after the rename): worktrees found again, and one
  new commit in the workspace's own brain; history is never rewritten.

* What is not JSON under the store root is ``agent_runtime.realm_rekey_outside`` (the ``outside`` step): the
  machine's slot files, Lens watches, the shared skills' inbox and provenance, the local sync repository.

:data:`OWED_HANDLERS` is empty: every MOVES place has its step.
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
from .realm_rekey_journal import JOURNAL_DIRNAME, RekeyState, read_rekey_journal, rekey_journal_path, rekeyed_from
from .realm_rekey_git import LANE_WORKTREES_DIRNAME, step_git
from .realm_rekey_outside import LOCAL_SYNC_REPO, step_outside
from .realm_rekey_agents import PARKED_DIRNAME, agent_forms, agent_name_forms, agents_of, fresh_agent_id, step_agents
from .store import RealmStore, WorkspaceStore
from .store_events import emit_store_event

__layer__ = "lanes"
__all__ = [
    "OWED_HANDLERS",
    "STORE_PLACES",
    "PlaceClass",
    "RekeyMap",
    "RekeyState",
    "leftover_ids",
    "merge_folder",
    "rewrite_json",
    "rewrite_text",
    "token_pattern",
    "owe_rekey",
    "place_class",
    "read_rekey_journal",
    "rekeyed_from",
    "rekey_journal_path",
    "rekey_realm",
    "restore_team_catalogues",
    "team_catalogues_dir",
]

#: The level document's one embedded id: its store address (``EterniaLauncher`` ``level_ref.dart``).
SCENE_ID_PREFIX = "ws-"
_PIECES = re.compile(r"([/\\:])")
_MINTED_SUFFIX = re.compile(r"_[0-9a-f]{6}$")
_MINTED_CARD = re.compile(r"^card_[0-9a-f]{32}$")
#: ``realm_sync_state/<realm>.team_baselines/``: written at a leave from ed84b2c01a until the fresh re-join.
LEGACY_TEAM_BASELINES_SUFFIX = ".team_baselines"
#: The drift baselines of the families that are this INSTALL's, not a realm's (``PlaceClass.INSTALL``: maps,
#: prefabs, persona definitions, profile files, skills). Their ids are not re-keyed, so one document serves
#: the local copy and the server's realm alike, and what this install and the team last agreed on about it
#: is still true at a re-join. Kept at the leave, handed to the fresh realm (:func:`restore_team_catalogues`).
CATALOGUE_BASELINES = ("map_baseline.json", "prefab_baseline.json", "persona_config_baseline.json",
                       "profile_artifact_baseline.json", "skill_baseline.json")


class PlaceClass(str, Enum):
    MOVES = "moves"
    PARKS = "parks"
    HISTORY = "history"
    DERIVED = "derived"
    #: This install's own, whatever realms come and go: catalogues every realm shares (maps, prefabs, courses,
    #: skills), machine state. Holds no realm, workspace or agent id of a realm — the census reds one that does.
    INSTALL = "install"


_M, _P, _H, _D, _I = PlaceClass.MOVES, PlaceClass.PARKS, PlaceClass.HISTORY, PlaceClass.DERIVED, PlaceClass.INSTALL
#: Every top-level entry of the store root that can hold a realm, workspace, board or agent id.
STORE_PLACES: dict[str, PlaceClass] = {
    "realms": _M, "workspaces": _M, "workspace_slots": _M, "office": _M, paths.OFFICE_ARCHIVE_DIRNAME: _M,
    "boards": _M, paths.LEVELS_DIRNAME: _M, "slot_worktrees": _M, paths.WORK_DIRNAME: _M, "schedules": _M,
    paths.REALM_SYNC_DIRNAME: _M, "realm_sync_state": _M, "active_workspace.json": _M, "active_realm.json": _M,
    "default_realm.json": _M, "brain_paths.json": _M, "realm_repo_folders.json": _M,
    # Once the ``agents`` step has parked the team's rows, what is left in ``persona_instances`` is this
    # install's own and the local copy's new agents; a flow graph is its owner's canvas and follows the desk.
    "persona_instances": _M, "flow_graphs": _M,
    PARKED_DIRNAME: _P, "persona_assignments": _P, paths.CHAT_FOLDERS_DIRNAME: _P, "workspace_chats": _P,
    "workspace_chat_fold": _P, "workspace_chat_exports": _P, "persona_chat_mint_receipts": _P,
    "chat_goal_bindings": _P, "chat_goal_parks": _P, "agent_create_reservations": _P, "state.db": _P,
    "persona_instances_archive": _H, "persona_assignments_archive": _H, "events.jsonl": _H,
    "events_archive": _H, "prompt_observability": _H, "prompt_observability_archive": _H, "patch_diffs": _H,
    "patch_diffs_archive": _H, paths.DELETED_ARCHIVE_DIRNAME: _H, "runs": _H, "incidents": _H, "agents": _H,
    "migration_backups": _H, JOURNAL_DIRNAME: _H, "flow_graphs_stale": _H,
    "snapshot.json": _D, paths.DERIVED_CACHE_DIRNAME: _D, "locks": _D,
    # Entries no ``paths.py`` function with an id parameter names (the census reads the source for them).
    # Chat bookkeeping is keyed by session and parks with the chats; a messaging binding routes to an agent.
    "mission_chat_turns": _P, "mission_chat_turns_archive": _P, "mission_chat_turns.json": _P,
    "mission_chat_turns.legacy.json": _P, "chat_turn_reservations": _P, "chat_turn_settles": _P,
    "chat_root_send_queue": _P, "persona_chat_clarify_tickets": _P, "session_controls": _P,
    "tool_turn_context": _P, "history_recovery": _P, "chat_head_home.json": _P, "messaging": _P,
    "events_journal.json": _H, "events_manifest.json": _H, "prompt_observability_catalogs": _H,
    "prompt_observability_index.json": _H, "worktree_events.jsonl": _H, "wt_reaped_patches": _H,
    "workspace_creates": _H, "projects": _H, "migrations": _H,
    "serve_read_model": _D, "workspace_write_locks": _D, "chat_history_locks": _D,
    "mission_chat_turns.migrate.lock": _D, "mission_chat_turns.gc.lock": _D,
    "maps": _I, "prefabs": _I, "courses": _I, "queued_skills": _I, "skill_lends": _I, "tool_permissions.json": _I,
    "launcher_supervision": _I, "operator_files": _I, "persona_instance_aliases.json": _I, "wt": _I,
}
#: MOVES places no step rewrites yet, and the row that owes each. Empty since the ``outside`` step; the
#: leave owes a re-key only while it stays empty (pinned).
OWED_HANDLERS: dict[str, str] = {}


def _under_work(parts: tuple[str, ...]) -> tuple[str, ...]:
    return parts[1:] if parts[0] == paths.WORK_DIRNAME else ()


#: Places INSIDE a top-level entry that are not their entry's class; the first rule that holds wins.
_SUB_PLACES: tuple[tuple[Any, PlaceClass], ...] = (
    # shared chats are chats: they wait for the re-join
    (lambda parts: _under_work(parts)[:1] and _under_work(parts)[0].startswith("workspace_chats_"), PlaceClass.PARKS),
    # a brain's or a sync clone's object store
    (lambda parts: ".git" in parts, PlaceClass.HISTORY),
    # a batch lane's checkout is its branch's: it reaches the brain by a merge
    (lambda parts: LANE_WORKTREES_DIRNAME in _under_work(parts)[1:2], PlaceClass.HISTORY),
    # a server's sync clone is the team's projection; the ``local`` one is the local copy's (the outside step)
    (lambda parts: parts[0] == paths.REALM_SYNC_DIRNAME and parts[1:2] not in ((), (LOCAL_SYNC_REPO,))
     and (paths.realm_sync_root() / parts[1] / ".git").exists(), PlaceClass.HISTORY),
)


def place_class(relative: Path) -> PlaceClass | None:
    """The class of a path under the store root, or ``None`` for an entry the table does not know."""
    parts = relative.parts
    if not parts:
        return None
    return next((found for holds, found in _SUB_PLACES if holds(parts)), STORE_PLACES.get(parts[0]))


@dataclass
class RekeyMap:
    realm_old: str
    realm_new: str
    workspaces: dict[str, str] = field(default_factory=dict)
    boards: dict[str, str] = field(default_factory=dict)
    agents: dict[str, str] = field(default_factory=dict)
    cards: dict[str, str] = field(default_factory=dict)

    def forms(self) -> dict[str, str]:
        """Every whole token that is rewritten: the ids, the level address ``ws-<workspace>`` and the forms
        an agent id takes (``realm_rekey_agents.agent_forms``)."""
        forms = {**agent_forms(self.agents), **self.cards, self.realm_old: self.realm_new, **self.boards, **self.workspaces}
        forms.update({SCENE_ID_PREFIX + old: SCENE_ID_PREFIX + new for old, new in self.workspaces.items()})
        return forms

    def name_forms(self) -> dict[str, str]:
        """What a file or folder NAME is matched against: the tokens, and a long actor key's capped file token."""
        return {**agent_name_forms(self.agents), **self.forms()}



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


def _minted_cards_of(board_ids: Any) -> list[str]:
    """The cards a board store minted (``card_<hex32>``) on these boards, archived ones too. A card adopted
    from a Work row carries that row's id and keeps it: the id is the row's, in the brain's own text."""
    found = []
    for board_id in board_ids:
        for folder in (paths.board_cards_dir(board_id), paths.board_archive_dir(board_id)):
            found.extend(path.stem for path in sorted(folder.glob("*.json")) if _MINTED_CARD.match(path.stem))
    return found


def _file_done_journal(realm_id: str, journal: dict[str, Any]) -> None:
    """A realm id that was re-keyed, came back with a re-join and is left AGAIN: the first cycle's journal is
    filed beside (``<old>.<new>.json``) — it is still what names the first local copy's ``rekeyed_from``."""
    path = rekey_journal_path(realm_id)
    path.replace(path.with_name(f"{path.stem}.{paths.safe_path_token(journal['map']['realm_new'])}.json"))


def team_catalogues_dir(realm_id: str) -> Path:
    """Beside the journal (HISTORY: never renamed), under the id the TEAM knows the realm by."""
    return rekey_journal_path(realm_id).with_suffix(".team_catalogues")


def _keep_team_catalogues(realm_id: str) -> None:
    """At the moment a re-key is owed — the leave, before any sync of the now-local realm moves them. A realm
    left under the older build has that moment's set in its ``team_baselines`` folder: that one is read."""
    live = paths.realm_sync_root() / paths.safe_path_token(realm_id)
    legacy = paths.store_root() / "realm_sync_state" / f"{paths.safe_path_token(realm_id)}{LEGACY_TEAM_BASELINES_SUFFIX}"
    source, kept = (legacy if legacy.is_dir() else live), team_catalogues_dir(realm_id)
    shutil.rmtree(kept, ignore_errors=True)
    for name in CATALOGUE_BASELINES:
        if (source / name).is_file():
            kept.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, kept / name)


def restore_team_catalogues(realm_id: str) -> list[str]:
    """Hand the kept catalogue baselines to the realm a re-join has just made way for (its id is free): the
    fresh pull then takes what the TEAM changed while the member was away, keeps what the MEMBER changed as an
    unpublished change, and holds only what both changed — instead of holding every difference as "both
    added". Never over a baseline that is already there. Returns the file names restored."""
    kept, live = team_catalogues_dir(realm_id), paths.realm_sync_root() / paths.safe_path_token(realm_id)
    restored = []
    for source in sorted(kept.glob("*.json")) if kept.is_dir() else []:
        if not (live / source.name).exists():
            live.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, live / source.name)
            restored.append(source.name)
    shutil.rmtree(kept, ignore_errors=True)
    return restored


def owe_rekey(realm_id: str, *, reason: str) -> dict[str, Any]:
    """Record that ``realm_id`` owes a re-key and mint its map. A realm whose journal is still ``owed`` or
    ``running`` answers it; one left again after a re-join gets a new journal and a new map."""
    with workspace_realm_assign_lock():
        existing = read_rekey_journal(realm_id)
        if existing is not None and existing.get("state") != RekeyState.DONE.value:
            return existing
        if existing is not None:
            _file_done_journal(realm_id, existing)
        _keep_team_catalogues(realm_id)
        realm = RealmStore().get(realm_id)
        held = [item.id for item in WorkspaceStore().list_all(include_archived=True) if item.realm_id == realm.id]
        workspaces = {old: _fresh_id(old) for old in dict.fromkeys([*realm.workspace_ids, *held])}
        # A default board is made on first use, so its id is mapped whether or not it is on disk yet.
        boards = {default_board_id(old): default_board_id(new) for old, new in workspaces.items()}
        boards.update({board: _fresh_id(board) for board in _boards_of(set(workspaces)) if board not in boards})
        agents = {old: fresh_agent_id(old, persona) for old, persona in agents_of(realm.id, set(workspaces)).items()}
        cards = {old: f"card_{uuid.uuid4().hex}" for old in dict.fromkeys(_minted_cards_of(boards))}
        mapping = RekeyMap(realm.id, _fresh_id(realm.id), workspaces, boards, agents, cards)
        return _write_journal({
            "state": RekeyState.OWED.value, "reason": reason, "owed_at": now().isoformat(),
            "map": asdict(mapping), "steps_done": [], "leftover": [],
        })


def rewrite_text(value: str, forms: dict[str, str]) -> str:
    if value in forms:
        return forms[value]
    if not _PIECES.search(value):
        return value
    return "".join(forms.get(piece, piece) for piece in _PIECES.split(value))


def rewrite_json(value: Any, forms: dict[str, str]) -> Any:
    rewrite = _JSON_REWRITERS.get(type(value))
    return rewrite(value, forms) if rewrite else value


_JSON_REWRITERS = {
    str: rewrite_text,
    list: lambda value, forms: [rewrite_json(item, forms) for item in value],
    dict: lambda value, forms: {rewrite_text(key, forms): rewrite_json(item, forms) for key, item in value.items()},
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
            _rewrite_membership(path, forms)
            continue
        if relative.parts[0] == paths.LEVELS_DIRNAME:
            _rewrite_level(path, forms)
            continue
        try:
            before = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        after = rewrite_json(before, forms)
        if after != before:
            atomic_json_write(path, after)


#: What another realm's record says it HOLDS. Its ledgers name what LEFT it — the team's ids, that realm's own
#: business — and are never touched; a workspace moved into it after the leave is listed under its new id.
_MEMBERSHIP_FIELDS = ("workspace_ids", "default_workspace_id")


def _rewrite_membership(path: Path, forms: dict[str, str]) -> None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    held = {key: rewrite_json(record[key], forms) for key in _MEMBERSHIP_FIELDS if key in record}
    if any(record[key] != value for key, value in held.items()):
        atomic_json_write(path, {**record, **held})


def _renamed(name: str, forms: dict[str, str]) -> str:
    if name in forms:
        return forms[name]
    stem, dot, rest = name.partition(".")
    return forms[stem] + dot + rest if dot and stem in forms else name


def merge_folder(old: Path, new: Path) -> None:
    """A late writer re-made the old folder after it moved: bring over what the new one lacks. A file both
    hold stays where it is — the new one is the newer — and the census names what is left."""
    for child in sorted(old.iterdir()):
        target = new / child.name
        if not target.exists():
            shutil.move(str(child), str(target))
        elif child.is_dir() and target.is_dir():
            merge_folder(child, target)
    if not any(old.iterdir()):
        old.rmdir()


def _step_rename(root: Path, mapping: RekeyMap) -> None:
    forms = mapping.name_forms()
    for path in _moves_files(root):
        target = path.with_name(_renamed(path.name, forms))
        if target == path or not path.exists():
            continue
        if not target.exists():
            path.rename(target)
        elif path.is_dir() and target.is_dir():
            merge_folder(path, target)


def _step_ledgers(root: Path, mapping: RekeyMap) -> None:
    """The delete ledger and the lifts speak to the team's copy about the team's ids; the local copy starts clean.
    So does a set of drift baselines an older build set aside at the leave for a re-bind that no longer exists."""
    for realm_id in (mapping.realm_old, mapping.realm_new):
        shutil.rmtree(root / "realm_sync_state" / f"{paths.safe_path_token(realm_id)}{LEGACY_TEAM_BASELINES_SUFFIX}",
                      ignore_errors=True)
    path = paths.realm_path(mapping.realm_new)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    cleared = {key: type(record[key])() for key in ("deleted_workspace_ids", "workspace_lifts") if record.get(key)}
    if cleared:
        atomic_json_write(path, {**record, **cleared})


STEPS = (("agents", step_agents), ("content", _step_content), ("rename", _step_rename), ("git", step_git),
         ("outside", step_outside), ("ledgers", _step_ledgers))


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
            try:
                step(root, mapping)
            except Exception as exc:
                # Still ``running``, with the step that stopped it named: the next trigger runs it again.
                _write_journal({**journal, "blocked": {"step": name, "error": type(exc).__name__}})
                raise
            journal = _write_journal({**journal, "steps_done": [*journal["steps_done"], name], "blocked": None})
        leftover = leftover_ids(root, list(mapping.forms()), only=PlaceClass.MOVES)
        journal = _write_journal({
            **journal, "state": RekeyState.DONE.value, "done_at": now().isoformat(), "leftover": leftover,
        })
        # The one event of a re-key: it advances the event log every reader is gated on, and carries the map
        # a client needs to follow what it had open (the realm row's ``rekeyed_from`` says the same, durably).
        told = rekeyed_from(mapping.realm_new) or {}
        emit_store_event(RealmStore().event_log, "realm.rekeyed", {
            "realm_id": mapping.realm_new, "realm_id_was": told.get("realm_id"), "at": told.get("at"),
            "workspaces": told.get("workspaces"), "agents": told.get("agents"),
        }, domain="store")
        return journal


def token_pattern(ids: Any) -> re.Pattern[str]:
    """Matches any of ``ids`` as a whole token in free text: never inside a longer id."""
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(sorted(map(re.escape, ids), key=len, reverse=True)) + r")(?![A-Za-z0-9_-])")


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
    token = token_pattern(ids)
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
