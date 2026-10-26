"""The Work operations over a workspace's todo boards and the writer (plan §6.2).

Reads come from hermes's own worktree of each slot after ``Writer.sync`` (steps 1–3 of §5); every
write is one ``Writer.apply`` of a row operation keyed by ID. A row in the ADR 0011 grammar IS a
task; ``project`` is its wire shape. The operator's console writes as ``who="operator"``; a paired
device writes as ``device:<id>`` and may not claim the operator's override.

The default brain is machine-local (ruling 2026-10-18): once a repo slot with a brain is bound,
``normalize_default_brain`` moves the default board's rows into that brain's ``work-queue.md`` in ONE
commit (IDs kept), removes them from the default brain in one local commit, and retires the binding,
so the default board drops from the list and new rows land in the repo brain.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from agent_runtime.work_store import board as boards_store
from agent_runtime.work_store import receipts
from agent_runtime.work_store.board import Board
from agent_runtime.work_store.default_brain import (
    QUEUE_DIR, QUEUE_NOTE, QUEUE_TEMPLATE, TODO_TEMPLATE, retire_binding, this_machine,
)
from agent_runtime.work_store.grammar import (
    ASSIGNEE, STATUS, Assignee, Op, Row, RowRef, find, mint_id, parse_note,
)
from agent_runtime.work_store.writer import OPERATOR, Writer, RowOp

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
    writers: dict[str, Writer]
    stale: bool

    @property
    def read_roots(self) -> dict[str, Path]:
        return {slot: writer.worktree for slot, writer in self.writers.items()}


def writer_for(board: Board) -> Writer:
    return Writer(board, machine_id=this_machine())


def _token_of(workspace_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", workspace_id)[:120]


def _default_rows(default: Board) -> tuple[Writer, dict[str, list[Row]]]:
    source = writer_for(default)
    source.sync()
    view = replace(default, read_root=source.worktree)
    by_note = {path.relative_to(source.worktree).as_posix(): parse_note(
        path.read_bytes().decode("utf-8"), slot=default.slot, note=path.relative_to(source.worktree).as_posix())
        for path in boards_store.notes(view)}
    return source, {note: rows for note, rows in by_note.items() if rows}


def _move_in(target: Board, rows: list[Row], request: str) -> str | None:
    writer = writer_for(target)
    writer.sync()
    note = f"{target.brain_dir}/{QUEUE_NOTE}"
    files = {} if (writer.worktree / note).is_file() else {
        f"{PurePosixPath(target.brain_dir or '').name}/{QUEUE_NOTE}": QUEUE_TEMPLATE}
    payload = {"rows": [row.raw for row in rows], "files": files}
    return writer.apply(RowOp(RowRef(target.slot, note, rows[0].ref.id), Op.APPEND, OPERATOR, request, payload)).commit


def normalize_default_brain(workspace_id: str) -> dict[str, Any] | None:
    """Move a live default brain's rows into the first bound repo brain, once; then retire it.

    The target is ``board.first_repo_brain`` (the first declared slot by name whose checkout has a brain).
    Every request id is derived from the workspace, so a move interrupted half way replays.
    """

    default = boards_store.default_board(workspace_id)
    target = boards_store.first_repo_brain(workspace_id) if default is not None else None
    if default is None or target is None:
        return None
    source, by_note = _default_rows(default)
    moved = [row for rows in by_note.values() for row in rows]
    base = f"move-default-brain:{_token_of(workspace_id)}"
    commit = _move_in(target, moved, f"{base}:in") if moved else None
    for note, rows in by_note.items():
        ids = [row.ref.id for row in rows]
        source.apply(RowOp(RowRef(default.slot, note, ids[0]), Op.DELETE, OPERATOR, f"{base}:out:{_token_of(note)}",
                           {"ids": ids}))
    ids = [row.ref.id for row in moved]
    retire_binding(workspace_id, into=target.slot, at=_now().isoformat(timespec="seconds"), moved=ids)
    return receipts.emit("work.default_brain_move", workspace_id=workspace_id, into=target.slot, ids=ids,
                         commit=commit)


def synced(workspace_id: str, *, stale_ok: bool = False, slot: str | None = None) -> Synced:
    normalize_default_brain(workspace_id)
    writers: dict[str, Writer] = {}
    for board in boards_store.boards(workspace_id):
        if board.bound_here and board.brain_dir and slot in (None, board.slot):
            writers[board.slot] = writer_for(board)
            writers[board.slot].sync(stale_ok=stale_ok)
    roots = {name: writer.worktree for name, writer in writers.items()}
    return Synced(boards_store.boards(workspace_id, read_roots=roots), writers,
                  any(writer.stale for writer in writers.values()))


def observed(workspace_id: str, *, slot: str | None = None) -> Synced:
    """An OBSERVATION read (RT-WORK-OBSERVATION-READ): the boards as hermes's worktrees hold them now.

    No ``normalize_default_brain``, no ``Writer.sync`` (no worktree add, fetch, reset or clean), no row
    write: a board is read from its existing worktree only, and one without a worktree is listed with no
    queues. ``stale`` is true unless every read worktree sits at its local tip; a remote tip is never
    fetched here, so "not stale" means "at the last fetched tip", never "at the remote".
    """

    writers: dict[str, Writer] = {}
    stale = False
    for board in boards_store.boards(workspace_id):
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
        writers[board.slot] = writer
        stale = stale or not writer.at_tip()
    roots = {name: writer.worktree for name, writer in writers.items()}
    return Synced(boards_store.boards(workspace_id, read_roots=roots), writers, stale)


def _view_board(view: Synced, slot: Any) -> Board:
    board = next((b for b in view.boards if b.slot == slot), None)
    if board is None or not board.bound_here:
        raise WorkRefused(Reason.SLOT_UNBOUND, str(slot))
    if board.slot not in view.writers:
        raise WorkRefused(Reason.NO_BRAIN, board.slot)
    return board


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
        "id": row.ref.id, "slot": row.ref.slot, "program": program, "note": row.ref.note, "line": row.line_no,
        "title": row.title,
        "status": status_word(row), "status_word": row.status.value if row.status else None,
        "status_date": row.status_date, "status_body": row.status_body, "recommend": row.recommend,
        "assignee": f"persona:{row.assignee.token}" if row.assignee else None,
        "skills": list(row.skills),
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


def board_wire(board: Board, writer: Writer | None) -> dict[str, Any]:
    return {"slot": board.slot, "label": "Work" if board.is_default else board.slot, "brain_dir": board.brain_dir,
            "bound_here": board.bound_here, "local": board.local,
            "is_default": board.is_default, "default_branch": board.default_branch,
            "committed_at": writer.note_committed_at(board.brain_dir) if writer and board.brain_dir else None,
            "readable": writer is not None}


def _row_now(writer: Writer, ref: RowRef) -> Row | None:
    path = writer.worktree / ref.note
    if not path.is_file():
        return None
    return find(parse_note(path.read_bytes().decode("utf-8"), slot=ref.slot, note=ref.note), ref.id)


def _task(writer: Writer, ref: RowRef, context) -> dict[str, Any] | None:
    row = _row_now(writer, ref)
    return None if row is None else project(row, writer, context=context, detail=True)


# ── reads ──────────────────────────────────────────────────────────────────


def _row_filter(params: Mapping[str, Any], context, assignees: frozenset[str] | None = None):
    status = params.get("status")
    if assignees is None and params.get("assignee") is not None:
        assignees = frozenset({_assignee_token(params["assignee"])})
    in_view = params.get("view", "all") == "conversation"
    return lambda row: ((status is None or status_word(row) == status)
                        and (assignees is None or (row.assignee is not None and row.assignee.token in assignees))
                        and (not in_view or bool(context and context.assignee and row.taken
                                                 and row.taken.who == context.assignee)))


def list_work(scope, params, *, context=None, assignees: frozenset[str] | None = None):
    """One owner's boards, grouped board -> queue -> rows; ``assignees`` overrides ``params.assignee``
    with a SET of tokens (the agent view's instance id and its persona id, ``work.service``)."""

    if params.get("view", "all") not in ("all", "conversation") or (
            params.get("view") == "conversation" and context is None):
        raise WorkRefused(Reason.INVALID)
    view = (observed(scope.workspace_id) if params.get("observe") is True
            else synced(scope.workspace_id, stale_ok=params.get("stale_ok") is True))
    keep = _row_filter(params, context, assignees)
    slot = params.get("slot")
    listed = [b for b in view.boards if slot is None or b.slot == slot]
    return {"boards": [{**board_wire(b, view.writers.get(b.slot)),
                        "queues": _queues(b, view.writers.get(b.slot), keep, context)} for b in listed],
            "cursor": None, "read_at": _now().isoformat(timespec="seconds"), "stale": view.stale}


def _queues(board: Board, writer: Writer | None, keep, context) -> list[dict[str, Any]]:
    """One entry per ``type: queue`` note (a domain), its rows filtered; an empty domain is still listed."""

    if writer is None or board.read_root is None:
        return []
    out = []
    for path in boards_store.notes(board):
        note = path.relative_to(board.read_root).as_posix()
        meta = note_meta(path)
        rows = parse_note(path.read_bytes().decode("utf-8"), slot=board.slot, note=note)
        out.append({"note": note, **meta, "rows": [project(row, writer, context=context, program=meta["program"])
                                                   for row in rows if keep(row)]})
    return out


def inspect(scope, params, *, context=None):
    task_id = text(params.get("task_id"))
    view = (observed(scope.workspace_id, slot=params.get("slot")) if params.get("observe") is True
            else synced(scope.workspace_id, slot=params.get("slot"), stale_ok=params.get("stale_ok") is True))
    board = _view_board(view, params.get("slot"))
    writer = view.writers[board.slot]
    row = find(boards_store.rows(scope.workspace_id, slot=board.slot, read_roots=view.read_roots), task_id)
    if row is not None:
        return {"task": project(row, writer, context=context, detail=True), "ending": None}
    return {"task": None, "ending": writer.history(RowRef(board.slot, board.brain_dir or "", task_id))}


# ── writes ─────────────────────────────────────────────────────────────────


def _create_target(view: Synced, slot: Any) -> Board:
    if slot is not None:
        return _view_board(view, slot)
    readable = [b for b in view.boards if b.slot in view.writers]
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
               taken_by: str | None = None) -> str:
    segments = [f"- **`{row_id}` — {title}**"]
    segments += [f"brief: `{brief}`"] if brief else []
    segments += [f"assignee: persona:{token}"] if token else []
    segments += [f"READY {date}"]
    segments += [f"**TAKEN {date} {taken_by}**"] if taken_by else []
    return " · ".join(segments)


def start(scope, params, actor, *, context=None):
    title = text(params.get("title"), maximum=160).strip()
    if any(mark in title for mark in _TITLE_FORBIDDEN):
        raise WorkRefused(Reason.INVALID, "a title carries no backtick, `*` or ` · `")
    body = params.get("body") or ""
    if body:
        body = text(body, maximum=BODY_LIMIT, multiline=True)
    request = text(params.get("request_id"))
    # From an operator conversation the persona instance it talks to is the default assignee, and a
    # row assigned to that instance is taken in the conversation (``in_conversation``).
    here = context.assignee if context is not None else None
    assigned = params.get("assignee") or here
    token = resolve_assignee(_assignee_token(assigned)).token if assigned else None
    taken_by = here if here and token == _assignee_token(here) else None
    view = synced(scope.workspace_id)
    board = _create_target(view, params.get("slot"))
    writer = view.writers[board.slot]
    row_id = mint_id()
    brief = f"{writer.brain_root}/{BRIEF_DIR}/{row_id}.md" if body else None
    line = _start_row(row_id, title, brief, token, _now().date().isoformat(), taken_by)
    payload = {"row": line, "files": {f"{BRIEF_DIR}/{row_id}.md": body} if body else {}}
    ref = RowRef(board.slot, _first_note(board, params), row_id)
    receipt = writer.apply(RowOp(ref, Op.APPEND, actor, request, payload))
    return {"task": _task(writer, receipt.ref, context), "disposition": "accepted", "receipt": receipt.wire()}


def _row_write(scope, params, op: Op, who: str, payload: Mapping[str, Any], *, context, request: str | None = None):
    view = synced(scope.workspace_id, slot=params.get("slot"))
    board = _view_board(view, params.get("slot"))
    writer = view.writers[board.slot]
    row = find(boards_store.rows(scope.workspace_id, slot=board.slot, read_roots=view.read_roots),
               text(params.get("task_id")))
    if row is None:
        raise WorkRefused(Reason.ROW_GONE, str(params.get("task_id")))
    receipt = writer.apply(RowOp(row.ref, op, who, request or text(params.get("request_id")), payload))
    return writer, receipt


def assign(scope, params, actor, *, context=None):
    token = resolve_assignee(_assignee_token(params["assignee"])).token if params.get("assignee") is not None else None
    writer, receipt = _row_write(scope, params, Op.ASSIGN, _writer_who(params, actor), {"assignee": token},
                                 context=context)
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
    board = _view_board(view, params.get("slot"))
    row = find(boards_store.rows(scope.workspace_id, slot=board.slot, read_roots=view.read_roots),
               text(params.get("task_id")))
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


def done(scope, params, actor, *, context=None):
    result = text(params.get("result"), maximum=RESULT_LIMIT)
    writer, receipt = _row_write(scope, params, Op.DELETE, _writer_who(params, actor), {"result": result},
                                 context=context)
    return {"ending": writer.history(receipt.ref), "receipt": receipt.wire()}


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
    if record is None or record.get("retired_into"):
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
    found = next((b for b in boards_store.boards(scope.workspace_id) if b.slot == params["slot"]), None)
    if found is None or not found.bound_here:
        raise WorkRefused(Reason.SLOT_UNBOUND, str(params["slot"]))
    if found.brain_dir is not None:
        return {"board": board_wire(found, None), "receipt": None}
    board = replace(found, brain_dir=QUEUE_DIR)
    writer = writer_for(board)
    files = {"TODO.md": TODO_TEMPLATE, f"{PurePosixPath(QUEUE_DIR).name}/{QUEUE_NOTE}": QUEUE_TEMPLATE}
    ref = RowRef(board.slot, f"{QUEUE_DIR}/{QUEUE_NOTE}", "BRAIN")
    receipt = writer.apply(RowOp(ref, Op.APPEND, actor, request, {"files": files}))
    return {"board": board_wire(board, writer), "receipt": receipt.wire()}
