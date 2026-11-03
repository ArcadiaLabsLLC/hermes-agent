"""The Work operations over a workspace's todo boards and the writer (plan §6.2).

Reads come from hermes's own worktree of each slot after ``Writer.sync`` (steps 1–3 of §5); every
write is one ``Writer.apply`` of a row operation keyed by ID. A row in the ADR 0011 grammar IS a
task; ``project`` is its wire shape. The operator's console writes as ``who="operator"``; a paired
device writes as ``device:<id>`` and may not claim the operator's override.

The default brain is machine-local (ruling 2026-10-18) and is the WORKSPACE's own brain: it stays listed
beside every bound repo brain (owner ruling 2026-11-02, RT-WORK-WORKSPACE-BRAIN-KEPT, retiring the move of
its rows into the first repo brain); a slot-less ``start`` still lands in a repo brain first (``_create_target``).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from agent_runtime.work_store import board as boards_store
from agent_runtime.work_store import receipts
from agent_runtime.work_store.board import Board
from agent_runtime.work_store.default_brain import (
    QUEUE_DIR, QUEUE_NOTE, QUEUE_TEMPLATE, TODO_TEMPLATE, this_machine,
)
from agent_runtime.work_store.grammar import (
    ASSIGNEE, GROUP_SLUG, STATUS, Assignee, Op, Row, RowRef, find, mint_id, parse_note,
)
from agent_runtime.work_store.writer import OPERATOR, Writer, RowOp, checkout_token, work_worktree_for

from agent_runtime.errors import NotFound

from .model import Reason, WorkRefused, fingerprint, text

__layer__ = "stores"

BODY_LIMIT = 50000
RESULT_LIMIT = 4000
BRIEF_DIR = "50 — Agent Handoffs/work"
_TITLE_FORBIDDEN = ("`", "*", " · ")


@dataclass(frozen=True)
class Synced:
    """A workspace's boards read from hermes's worktrees, with the writer of each readable one."""

    boards: list[Board]
    #: Keyed by :attr:`Board.key` (``<project>/<slot>``, bare for the workspace's own).
    writers: dict[str, Writer]
    stale: bool
    #: Keyed like ``writers``: the board whose sync refused, and why (RT-WORK-LIST-ONE-BOARD-REFUSAL).
    refused: dict[str, WorkRefused] = field(default_factory=dict)

    @property
    def read_roots(self) -> dict[str, Path]:
        return {key: writer.worktree for key, writer in self.writers.items()}

    def writer_of(self, board: Board) -> Writer | None:
        return self.writers.get(board.key)


def writer_for(board: Board) -> Writer:
    return Writer(board, machine_id=this_machine())


def worktree_brain(board: Board) -> Board:
    """``board``, its brain found in HERMES'S worktree of the slot when its checkout holds none.

    ``create_brain`` commits a slot's brain in hermes's own worktree and pushes it to the slot's origin;
    the operator's checkout never holds it until the operator pulls, so discovery in the checkout alone
    kept the slot brain-less on every read (RT-WORK-LIST-READS-CREATED-BRAIN). The worktree is the one
    the slot's writer resolves (``work_worktree_for`` keyed by the checkout); no git runs but the
    checkout token's ``rev-parse``.
    """

    if board.brain_dir is not None or not board.bound_here or board.checkout is None:
        return board
    worktree = work_worktree_for(board.workspace_id, board.slot, checkout_token(board.checkout),
                                 project_id=board.project_id)
    if not (worktree / ".git").exists():
        return board
    found = boards_store.brain_dir_of(worktree, {})
    return board if found is None else replace(board, read_root=worktree, brain_dir=found)


def synced(workspace_id: str, *, stale_ok: bool = False, slot: str | None = None) -> Synced:
    writers: dict[str, Writer] = {}
    refused: dict[str, WorkRefused] = {}
    for board in map(worktree_brain, boards_store.boards(workspace_id)):
        if board.bound_here and board.brain_dir and slot in (None, board.slot):
            writer = writer_for(board)
            try:
                writer.sync(stale_ok=stale_ok)
            except WorkRefused as refusal:
                # One board's refusal is that board's answer, never the whole read's
                # (RT-WORK-LIST-ONE-BOARD-REFUSAL): every other board still syncs and lists.
                refused[board.key] = refusal
                continue
            writers[board.key] = writer
    roots = {key: writer.worktree for key, writer in writers.items()}
    return Synced(boards_store.boards(workspace_id, read_roots=roots), writers,
                  any(writer.stale for writer in writers.values()), refused)


def observed(workspace_id: str, *, slot: str | None = None) -> Synced:
    """An OBSERVATION read (RT-WORK-OBSERVATION-READ): the boards as hermes's worktrees hold them now.

    No ``Writer.sync`` (no worktree add, fetch, reset or clean), no row
    write: a board is read from its existing worktree only, and one without a worktree is listed with no
    queues. ``stale`` is true unless every read worktree sits at its local tip; a remote tip is never
    fetched here, so "not stale" means "at the last fetched tip", never "at the remote".
    """

    writers: dict[str, Writer] = {}
    stale = False
    for board in map(worktree_brain, boards_store.boards(workspace_id)):
        if not (board.bound_here and board.brain_dir and slot in (None, board.slot)):
            continue
        writer = writer_for(board)
        try:
            present = (writer.worktree / ".git").exists()
        except WorkRefused:
            present = False
        if not present:
            stale = True
            continue
        writers[board.key] = writer
        stale = stale or not writer.at_tip()
    roots = {key: writer.worktree for key, writer in writers.items()}
    return Synced(boards_store.boards(workspace_id, read_roots=roots), writers, stale)


def _view_board(view: Synced, slot: Any, project_id: Any = None) -> Board:
    """The board ``slot`` (+ ``project_id``, absent = the workspace's own) names; ``slot_ambiguous`` when
    two Projects answer a bare name (``board.pick``)."""

    board = boards_store.pick(view.boards, slot, project_id) if slot is not None else None
    if board is None or not board.bound_here:
        raise WorkRefused(Reason.SLOT_UNBOUND, f"{project_id}/{slot}" if project_id else str(slot))
    if board.key in view.refused:
        raise view.refused[board.key]
    if board.key not in view.writers:
        raise WorkRefused(Reason.NO_BRAIN, board.key)
    return board


def _project_param(params: Mapping[str, Any]) -> str | None:
    """``project_id`` from the params: optional; absent names the workspace's own (or the one owner)."""

    value = params.get("project_id")
    return None if value is None else text(value, maximum=200)


def _now() -> datetime:
    return datetime.now(UTC)


# ── who writes, and to whom ────────────────────────────────────────────────


def resolve_assignee(token: str) -> Assignee:
    """Instance first, then a persona id with at least one instance; else ``assignee_unknown``."""

    from agent_runtime.persona_assignments.store import PersonaInstanceStore

    store = PersonaInstanceStore()
    try:
        store.get(token)
        return Assignee(token)
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError):
        pass
    if any(instance.persona_id == token for instance in store.list_all()):
        return Assignee(token)
    raise WorkRefused(Reason.ASSIGNEE_UNKNOWN, token)


def _assignee_token(value: Any) -> str:
    match = ASSIGNEE.match(f"assignee: {text(value)}")
    if match is None:
        raise WorkRefused(Reason.INVALID, "an assignee is persona:<token>")
    return match.group(1)


def _writer_who(params: Mapping[str, Any], actor: str) -> str:
    who = params.get("who")
    if who is None:
        return actor
    who = text(who)
    if who == OPERATOR and actor != OPERATOR:
        raise WorkRefused(Reason.DENIED, "only the operator's console writes as the operator")
    return who


# ── the wire row ───────────────────────────────────────────────────────────


def status_word(row: Row) -> str | None:
    return "TAKEN" if row.taken is not None else (row.status.value if row.status else None)


def brief_text(row: Row, worktree: Path | None) -> str:
    """The text of the brief note the row's `brief:` pointer names, read from `worktree` ("" when none)."""

    segment = next((s for s in row.segments[1:] if s.startswith("brief:")), None)
    pointer = next((p for p in row.pointers if segment and f"`{p}`" in segment), None)
    path = worktree / pointer if worktree and pointer else None
    return path.read_bytes().decode("utf-8") if path and path.is_file() else ""


def note_meta(path: Path) -> dict[str, Any]:
    """A queue note's ``program`` (frontmatter) and ``title`` (its first ``# `` heading, else the file stem)."""

    text = path.read_bytes().decode("utf-8") if path.is_file() else ""
    lines = text.split("\n")
    front = lines[1:lines.index("---", 1)] if lines[:1] == ["---"] and "---" in lines[1:] else []
    program = next((line.split(":", 1)[1].strip() for line in front if line.startswith("program:")), None)
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), path.stem)
    return {"program": program or None, "title": title}


def project(row: Row, writer: Writer | None, *, context=None, detail: bool = False,
            program: str | None = None) -> dict[str, Any]:
    body = brief_text(row, writer.worktree if writer else None) if detail else ""
    if program is None and writer is not None:
        program = note_meta(writer.worktree / row.ref.note)["program"]
    taken = row.taken
    value = {
        "id": row.ref.id, "slot": row.ref.slot, "project_id": row.ref.project_id, "program": program, "note": row.ref.note, "line": row.line_no,
        "title": row.title,
        "status": status_word(row), "status_word": row.status.value if row.status else None,
        "status_date": row.status_date, "status_body": row.status_body, "recommend": row.recommend,
        "assignee": f"persona:{row.assignee.token}" if row.assignee else None,
        "skills": list(row.skills), "group": row.group,
        "taken": {"date": taken.date, "who": taken.who, "persona_instance_id": taken.persona_instance_id}
        if taken else None,
        "rulings": list(row.rulings), "pointers": list(row.pointers), "heading": row.heading, "raw": row.raw,
        "body": body[:BODY_LIMIT], "body_truncated": len(body) > BODY_LIMIT, "result": "",
        "result_truncated": False,
        "in_conversation": bool(context and context.assignee and taken and taken.who == context.assignee),
        "updated_at": writer.note_committed_at(row.ref.note) if writer else None,
    }
    value["revision"] = fingerprint(value)
    return value


def board_wire(board: Board, writer: Writer | None, refusal: WorkRefused | None = None) -> dict[str, Any]:
    """A board on the wire, with its owner: ``project_id`` / ``project_name`` (None for the workspace's
    own), ``projects`` (every Project a merged board answers for), ``checkout`` (THIS machine's path,
    the disclosure ``slots.show`` makes) and ``project_default`` (RT-WORK-BOARD-PER-PROJECT-SLOT).
    ``refused`` is ``{reason, detail}`` when the board's sync refused (``readable`` false, no queues),
    else None (RT-WORK-LIST-ONE-BOARD-REFUSAL)."""

    return {"slot": board.slot, "label": "Work" if board.is_default else board.slot, "brain_dir": board.brain_dir,
            "project_id": board.project_id, "project_name": board.project_name,
            "projects": [{"project_id": pid, "project_name": name} for pid, name in board.projects],
            "project_default": board.project_default,
            "checkout": str(board.checkout) if board.checkout is not None else None,
            "bound_here": board.bound_here, "local": board.local,
            "is_default": board.is_default, "default_branch": board.default_branch,
            "committed_at": writer.note_committed_at(board.brain_dir) if writer and board.brain_dir else None,
            "readable": writer is not None,
            "refused": {"reason": refusal.reason.value, "detail": refusal.detail} if refusal is not None else None}


def _row_now(writer: Writer, ref: RowRef) -> Row | None:
    path = writer.worktree / ref.note
    if not path.is_file():
        return None
    return find(parse_note(path.read_bytes().decode("utf-8"), slot=ref.slot, note=ref.note,
                           project_id=writer.board.project_id), ref.id)


def _task(writer: Writer, ref: RowRef, context) -> dict[str, Any] | None:
    row = _row_now(writer, ref)
    return None if row is None else project(row, writer, context=context, detail=True)


# ── reads ──────────────────────────────────────────────────────────────────


def _row_filter(params: Mapping[str, Any], context, assignees: frozenset[str] | None = None):
    status = params.get("status")
    group = None if params.get("group") is None else _group_slug(params["group"])
    if assignees is None and params.get("assignee") is not None:
        assignees = frozenset({_assignee_token(params["assignee"])})
    in_view = params.get("view", "all") == "conversation"
    return lambda row: ((status is None or status_word(row) == status)
                        and (group is None or row.group == group)
                        and (assignees is None or (row.assignee is not None and row.assignee.token in assignees))
                        and (not in_view or bool(context and context.assignee and row.taken
                                                 and row.taken.who == context.assignee)))


def _group_slug(value: Any) -> str:
    slug = text(value, maximum=120)
    if GROUP_SLUG.match(slug) is None:
        raise WorkRefused(Reason.INVALID, "a group is a slug [a-z0-9][a-z0-9.-]*")
    return slug


def list_work(scope, params, *, context=None, assignees: frozenset[str] | None = None):
    """One owner's boards, grouped board -> queue -> rows; ``assignees`` overrides ``params.assignee``
    with a SET of tokens (the agent view's instance id and its persona id, ``work.service``)."""

    if params.get("view", "all") not in ("all", "conversation") or (
            params.get("view") == "conversation" and context is None):
        raise WorkRefused(Reason.INVALID)
    view = (observed(scope.workspace_id) if params.get("observe") is True
            else synced(scope.workspace_id, stale_ok=params.get("stale_ok") is True))
    keep = _row_filter(params, context, assignees)
    slot, project_id = params.get("slot"), _project_param(params)
    listed = [b for b in view.boards if (slot is None or b.slot == slot)
              and (project_id is None or b.project_id == project_id or project_id in b.owners)]
    from agent_runtime.project_categories import held_projects

    projects = [p for p in held_projects(scope.workspace_id) if project_id is None or p["project_id"] == project_id]
    return {"boards": [{**board_wire(b, view.writer_of(b), view.refused.get(b.key)),
                        "queues": _queues(b, view.writer_of(b), keep, context)} for b in listed],
            "projects": projects,
            "cursor": None, "read_at": _now().isoformat(timespec="seconds"), "stale": view.stale}


def _queues(board: Board, writer: Writer | None, keep, context) -> list[dict[str, Any]]:
    """One entry per ``type: queue`` note (a domain), its rows filtered; an empty domain is still listed."""

    if writer is None or board.read_root is None:
        return []
    out = []
    for path in boards_store.notes(board):
        note = path.relative_to(board.read_root).as_posix()
        meta = note_meta(path)
        rows = parse_note(path.read_bytes().decode("utf-8"), slot=board.slot, note=note, project_id=board.project_id)
        out.append({"note": note, **meta, "rows": [project(row, writer, context=context, program=meta["program"])
                                                   for row in rows if keep(row)]})
    return out


def inspect(scope, params, *, context=None):
    task_id = text(params.get("task_id"))
    view = (observed(scope.workspace_id, slot=params.get("slot")) if params.get("observe") is True
            else synced(scope.workspace_id, slot=params.get("slot"), stale_ok=params.get("stale_ok") is True))
    board = _view_board(view, params.get("slot"), _project_param(params))
    writer = view.writers[board.key]
    row = find(boards_store.board_rows(board), task_id)
    if row is not None:
        return {"task": project(row, writer, context=context, detail=True), "ending": None}
    return {"task": None, "ending": archived_ending(board, writer, task_id)}


def archived_ending(board: Board, writer: Writer, task_id: str) -> dict[str, Any] | None:
    """An immutable archive outcome first; pre-archive git history is explicitly unrecorded."""
    for path in boards_store.archive_notes(board):
        note = path.relative_to(board.read_root).as_posix()
        row = find(parse_note(path.read_text(encoding="utf-8"), slot=board.slot, note=note,
                              project_id=board.project_id, archived=True), task_id)
        if row is None or row.outcome is None or row.defects:
            continue
        history = writer.history(row.ref) or {}
        outcome = row.outcome
        return {**history, "outcome": outcome.kind.value, "date": outcome.date,
                "commit": history.get("commit") if outcome.commit == "here" else outcome.commit,
                "result": row.result, "archive_note": note, "words": outcome.words}
    old = writer.history(RowRef(board.slot, board.brain_dir or "", task_id, board.project_id))
    return {**old, "outcome": "unrecorded"} if old else None


# ── writes ─────────────────────────────────────────────────────────────────


def _create_target(view: Synced, slot: Any, project_id: Any = None) -> Board:
    """The named board, else a Project's default board with a brain here (D1), else the first by name."""

    if slot is not None:
        return _view_board(view, slot, project_id)
    readable = [b for b in boards_store.preferred(view.boards) if b.key in view.writers
                and (project_id is None or b.project_id == project_id or project_id in b.owners)]
    chosen = next((b for b in readable if not b.is_default), readable[0] if readable else None)
    if chosen is None:
        raise WorkRefused(Reason.NO_BRAIN, "the workspace has no board with a brain on this machine")
    return chosen


def _first_note(board: Board, params: Mapping[str, Any]) -> str:
    if params.get("note") is not None:
        return text(params["note"], maximum=1024)
    notes = boards_store.notes(board)
    if not notes or board.read_root is None:
        raise WorkRefused(Reason.NOTE_MISSING, board.slot)
    named = [path for path in notes if board.is_default and path.name == QUEUE_NOTE]
    return (named or notes)[0].relative_to(board.read_root).as_posix()


def _start_row(row_id: str, title: str, brief: str | None, token: str | None, date: str,
               group: str | None = None) -> str:
    """The appended line: ``READY <date>``, never a claim mark — assignment is not execution."""
    segments = [f"- **`{row_id}` — {title}**"]
    segments += [f"group: {group}"] if group else []
    segments += [f"brief: `{brief}`"] if brief else []
    segments += [f"assignee: persona:{token}"] if token else []
    segments += [f"READY {date}"]
    return " · ".join(segments)


def start(scope, params, actor, *, context=None):
    title = text(params.get("title"), maximum=160).strip()
    if any(mark in title for mark in _TITLE_FORBIDDEN):
        raise WorkRefused(Reason.INVALID, "a title carries no backtick, `*` or ` · `")
    group = None if params.get("group") is None else _group_slug(params["group"])
    body = params.get("body") or ""
    if body:
        body = text(body, maximum=BODY_LIMIT, multiline=True)
    request = text(params.get("request_id"))
    # From an operator conversation the persona instance it talks to is the default assignee. Start
    # never claims (owner ruling 2026-11-02, RT-WORK-START-NEVER-CLAIMS): taking the row is
    # ``runtime.work.claim`` or a batch, each its own explicit choice.
    here = context.assignee if context is not None else None
    assigned = params.get("assignee") or here
    token = resolve_assignee(_assignee_token(assigned)).token if assigned else None
    view = synced(scope.workspace_id)
    board = _create_target(view, params.get("slot"), _project_param(params))
    writer = view.writers[board.key]
    row_id = mint_id()
    brief = f"{writer.brain_root}/{BRIEF_DIR}/{row_id}.md" if body else None
    line = _start_row(row_id, title, brief, token, _now().date().isoformat(), group)
    payload = {"row": line, "files": {f"{BRIEF_DIR}/{row_id}.md": body} if body else {}}
    ref = RowRef(board.slot, _first_note(board, params), row_id, board.project_id)
    receipt = writer.apply(RowOp(ref, Op.APPEND, actor, request, payload))
    return {"task": _task(writer, receipt.ref, context), "disposition": "accepted", "receipt": receipt.wire()}


def _row_write(scope, params, op: Op, who: str, payload: Mapping[str, Any], *, context, request: str | None = None):
    view = synced(scope.workspace_id, slot=params.get("slot"))
    board = _view_board(view, params.get("slot"), _project_param(params))
    writer = view.writers[board.key]
    row = find(boards_store.board_rows(board), text(params.get("task_id")))
    if row is None:
        raise WorkRefused(Reason.ROW_GONE, str(params.get("task_id")))
    if op is Op.EDIT:
        relative = f"{BRIEF_DIR}/{row.ref.id}-{fingerprint(payload['body'])[:16]}.md"
        payload = {"title": payload["title"], "brief": f"{writer.brain_root}/{relative}",
                   "files": {relative: payload["body"]}}
    if "expected_raw" in params:
        if op not in (Op.SET_STATUS, Op.ASSIGN, Op.EDIT, Op.CLOSE) or params.get("note") != row.ref.note:
            raise WorkRefused(Reason.ROW_CHANGED, row.ref.id)
        payload = {**payload, "expected_raw": text(params["expected_raw"], maximum=20000)}
    receipt = writer.apply(RowOp(row.ref, op, who, request or text(params.get("request_id")), payload))
    return writer, receipt


def assign(scope, params, actor, *, context=None):
    token = resolve_assignee(_assignee_token(params["assignee"])).token if params.get("assignee") is not None else None
    writer, receipt = _row_write(scope, params, Op.ASSIGN, _writer_who(params, actor), {"assignee": token},
                                 context=context)
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire()}


def edit(scope, params, actor, *, context=None):
    """Guarded title/brief edit. A new immutable brief pointer versions the row itself."""
    title = text(params.get("title"), maximum=160).strip()
    if any(mark in title for mark in _TITLE_FORBIDDEN):
        raise WorkRefused(Reason.INVALID, "a title carries no backtick, `*` or ` · `")
    text(params.get("expected_raw"), maximum=20000)
    text(params.get("note"), maximum=2000)
    body = text(params.get("body"), maximum=BODY_LIMIT, multiline=True)
    writer, receipt = _row_write(scope, params, Op.EDIT, _writer_who(params, actor),
                                 {"title": title, "body": body}, context=context)
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire()}


#: ``runtime.work.lend_skills`` modes: the row's lent set after the call, from (held, asked).
LEND_MODES = {
    "lend": lambda held, asked: list(dict.fromkeys([*held, *asked])),
    "revoke": lambda held, asked: [skill for skill in held if skill not in asked],
}


def lend_skills(scope, params, actor, *, context=None, rejected=None):
    """Lend skills to whoever works a row (``mode: lend``, the union) or take them back (``revoke``).

    Every lent slug is resolved and compatibility-checked first (``rejected``: slug list -> {slug: reason},
    the ``runtime.chat.queue_skill`` check the service hands in); one unloadable skill refuses the whole call
    ``skills_not_loadable`` with nothing written. The set is the row's ``skills:`` segment (p10-work S1).
    """

    mode = params.get("mode", "lend")
    asked = params.get("skills")
    if mode not in LEND_MODES or not isinstance(asked, list) or not asked:
        raise WorkRefused(Reason.INVALID, "skills is a non-empty list and mode is lend | revoke")
    asked = list(dict.fromkeys(text(skill, maximum=128) for skill in asked))
    refused = (rejected or (lambda skills: {}))(asked) if mode == "lend" else {}
    if refused:
        raise WorkRefused(Reason.SKILLS_NOT_LOADABLE, ", ".join(sorted(refused)), data={"rejected_skills": refused})
    view = synced(scope.workspace_id, slot=params.get("slot"))
    board = _view_board(view, params.get("slot"), _project_param(params))
    row = find(boards_store.board_rows(board), text(params.get("task_id")))
    held = list(row.skills) if row is not None else []
    writer, receipt = _row_write(scope, params, Op.SET_SKILLS, _writer_who(params, actor),
                                 {"skills": LEND_MODES[mode](held, asked)}, context=context)
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire()}


def claim(scope, params, actor, *, context=None):
    who = params.get("who") or (context.assignee if context else None)
    instance = _assignee_token(who) if who else None
    if instance is None:
        raise WorkRefused(Reason.INVALID, "a claim names who: persona:<instance_id>")
    _instance_exists(instance)
    writer, receipt = _row_write(scope, params, Op.CLAIM, f"persona:{instance}", {}, context=context)
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire()}


def _instance_exists(instance: str) -> None:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

    try:
        PersonaInstanceStore().get(instance)
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError) as exc:
        raise WorkRefused(Reason.ASSIGNEE_UNKNOWN, instance) from exc


def _status_segment(value: Any) -> str:
    segment = text(value, maximum=1000)
    if STATUS.match(segment.split(" · ")[0]) is None:
        raise WorkRefused(Reason.GRAMMAR_INVALID, "status is READY / BLOCKED / DEFERRED / NEEDS PLAN <date>[: …]")
    return segment


def release(scope, params, actor, *, context=None):
    who = _writer_who(params, actor)
    request = text(params.get("request_id"))
    if params.get("status") is not None:
        _row_write(scope, params, Op.SET_STATUS, who, {"status": _status_segment(params["status"])},
                   context=context, request=f"{request}:status")
    writer, receipt = _row_write(scope, params, Op.RELEASE, who, {}, context=context)
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire()}


def set_status(scope, params, actor, *, context=None):
    payload = {"status": _status_segment(params.get("status"))}
    writer, receipt = _row_write(scope, params, Op.SET_STATUS, _writer_who(params, actor), payload, context=context)
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire()}


#: ``runtime.work.move``'s columns: the status words a card can be dropped on (a TAKEN column is a claim).
MOVE_COLUMNS = ("READY", "BLOCKED", "DEFERRED", "NEEDS PLAN")


def move(scope, params, actor, *, context=None):
    """The Work board's drag between status columns, as one write (RT-WORK-MOVE-ROW-COLUMN).

    ``to`` is a column word; the serve dates the status. ``reason`` is the status body (``BLOCKED`` needs
    one, starting with a blocked-reason word). ``revision`` (the card's ``revision``) refuses ``row_changed``
    when the row moved on since the card was drawn. A TAKEN row is released by the move. A drop on the
    row's own column with nothing to change answers ``unchanged: true`` with no commit.
    """

    to = params.get("to")
    if to not in MOVE_COLUMNS:
        raise WorkRefused(Reason.INVALID, "to is READY | BLOCKED | DEFERRED | NEEDS PLAN")
    reason = params.get("reason")
    reason = None if reason is None else text(reason, maximum=900).strip()
    segment = f"{to} {_now().date().isoformat()}" + (f": {reason}" if reason else "")
    if to == "BLOCKED":
        from agent_runtime.work_store.grammar import blocked_reason

        if not reason or blocked_reason(reason) is None:
            raise WorkRefused(Reason.GRAMMAR_INVALID, "a BLOCKED drop names a reason: owner decision | backend | …")
    view = synced(scope.workspace_id, slot=params.get("slot"))
    board = _view_board(view, params.get("slot"), _project_param(params))
    writer = view.writers[board.key]
    row = find(boards_store.board_rows(board), text(params.get("task_id")))
    if row is None:
        raise WorkRefused(Reason.ROW_GONE, str(params.get("task_id")))
    current = project(row, writer, context=context)
    # A card is drawn from ``list`` (no brief body) or ``inspect`` (with it): either revision is current.
    if params.get("revision") is not None and text(params["revision"]) not in (
            current["revision"], project(row, writer, context=context, detail=True)["revision"]):
        raise WorkRefused(Reason.ROW_CHANGED, row.ref.id, data={"task": current})
    if current["status"] == to and (reason is None or (row.status_body or "") == reason):
        return {"task": _task(writer, row.ref, context), "receipt": None, "unchanged": True}
    request = text(params.get("request_id"))
    who = _writer_who(params, actor)
    receipt = writer.apply(RowOp(row.ref, Op.SET_STATUS, who, f"{request}:status", {"status": segment}))
    if row.taken is not None:
        receipt = writer.apply(RowOp(row.ref, Op.RELEASE, who, request, {}))
    return {"task": _task(writer, receipt.ref, context), "receipt": receipt.wire(), "unchanged": False}


def pull(scope, params, actor, *, context=None):
    """``runtime.work.pull``: fast-forward a bound slot's OWN checkout (the user's repo) when clean.

    The one write that moves the user's checkout, and only on their ask (RT-WORK-PULL-PROJECT-CHECKOUT):
    the remote check only counts a Project brain's ``behind``. Refusals are ``brain_remote.pull_checkout``'s
    plus ``slot_unbound``; the answer carries ``pulled``, ``behind`` (now) and ``head``, and the brain list is
    rewritten with the new count before the reply.
    """

    from agent_runtime.brain_remote import pull_checkout

    board = boards_store.pick(boards_store.boards(scope.workspace_id), params.get("slot"), _project_param(params))
    if board is None or not board.bound_here or board.checkout is None:
        raise WorkRefused(Reason.SLOT_UNBOUND, str(params.get("slot")))
    pulled = pull_checkout(board.checkout)
    record = receipts.emit("work.pull", workspace_id=scope.workspace_id, slot=board.slot, project_id=board.project_id,
                           who=actor, request_id=params.get("request_id"), **pulled)
    return {"slot": board.slot, "project_id": board.project_id, **pulled, "receipt": record}


def done(scope, params, actor, *, context=None):
    result = text(params.get("result"), maximum=RESULT_LIMIT)
    writer, receipt = _row_write(scope, params, Op.CLOSE, _writer_who(params, actor),
                                 {"outcome": "DONE", "commit": "here", "result": result},
                                 context=context)
    return {"ending": archived_ending(replace(writer.board, read_root=writer.worktree), writer, receipt.ref.id),
            "receipt": receipt.wire()}


def _create_default(scope, params, actor):
    from agent_runtime.work_store.default_brain import ensure_default_brain

    made = ensure_default_brain(scope.workspace_id, issued_at=_now().isoformat(timespec="seconds"))
    record = receipts.emit("work.brain_create", workspace_id=scope.workspace_id, slot=made.slot, who=actor,
                           request_id=params.get("request_id"))
    return {"board": board_wire(made, None), "receipt": record}


def _promote_default(scope, params, actor):
    """``promote: true`` — the manual door to the default brain's remote (p10-work §2.5); it ignores the back-off."""
    from agent_runtime.work_store.default_brain import ensure_default_brain, promote_default_brain

    issued = _now().isoformat(timespec="seconds")
    record = boards_store.read_binding(scope.workspace_id)
    if record is None:
        ensure_default_brain(scope.workspace_id, issued_at=issued)
    promotion = promote_default_brain(scope.workspace_id, issued_at=issued)
    made = ensure_default_brain(scope.workspace_id, issued_at=issued)
    record = receipts.emit("work.brain_create", workspace_id=scope.workspace_id, slot=made.slot, who=actor,
                           request_id=params.get("request_id"), promote=True)
    return {"board": board_wire(made, None), "receipt": record, "promotion": promotion}


def create_brain(scope, params, actor, *, context=None):
    request = text(params.get("request_id"))
    if params.get("slot") is None:
        if params.get("promote") is True:
            return _promote_default(scope, params, actor)
        return _create_default(scope, params, actor)
    found = boards_store.pick(boards_store.boards(scope.workspace_id), params["slot"], _project_param(params))
    if found is None or not found.bound_here:
        raise WorkRefused(Reason.SLOT_UNBOUND, str(params["slot"]))
    found = worktree_brain(found)
    if found.brain_dir is not None:
        return {"board": board_wire(found, None), "receipt": None}
    board = replace(found, brain_dir=QUEUE_DIR)
    writer = writer_for(board)
    files = {"TODO.md": TODO_TEMPLATE, f"{PurePosixPath(QUEUE_DIR).name}/{QUEUE_NOTE}": QUEUE_TEMPLATE}
    ref = RowRef(board.slot, f"{QUEUE_DIR}/{QUEUE_NOTE}", "BRAIN", board.project_id)
    receipt = writer.apply(RowOp(ref, Op.APPEND, actor, request, {"files": files}))
    from agent_runtime.brain_paths import changed

    changed("work.brain_created")
    return {"board": board_wire(board, writer), "receipt": receipt.wire()}
