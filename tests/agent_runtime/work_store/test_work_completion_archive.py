"""Native completions preserve a result in the real writer's archive commit."""
from dataclasses import replace
from types import SimpleNamespace
import pytest

from agent_runtime.batch.board_source import BoardSource
from agent_runtime.work import store
from agent_runtime.work.store import Synced
from agent_runtime.work_store.board import archive_notes, board_rows
from agent_runtime.work_store.executor import Outcome, Verdict
from agent_runtime.work_store.grammar import Op, RowRef, parse_note
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.models import Claimant
from agent_runtime.work_store.writer import Writer
from test_writer import NOTE, edit_and_push, note_text, op, recording, repo


def test_native_completion_survives_reopen_with_result_and_commit(repo):
    writer = Writer(repo.board, machine_id="m1")
    writer.sync()
    board = replace(repo.board, read_root=writer.worktree)
    source = BoardSource(repo.ws, sync=lambda *a, **kw: Synced([board], {board.key: writer}, False))
    ref = RowRef(board.slot, NOTE, "RT-A")
    who = Claimant.persona("inst-a")
    source.claim(ref, who, "claim-archive")
    result = "A saved result with a long explanation. " * 30
    receipt = source.done(ref, who, result, commit="abcdef012345")
    assert all(row.ref.id != ref.id for row in board_rows(board))
    paths = archive_notes(board)
    assert len(paths) == 1
    rows = parse_note(paths[0].read_text(encoding="utf-8"), slot=board.slot,
                      note=paths[0].relative_to(writer.worktree).as_posix())
    assert rows[0].outcome.commit == "abcdef012345" and len(rows[0].result) <= 300
    assert not rows[0].defects
    reopened = Writer(repo.board, machine_id="m1")
    reopened.sync()
    ending = store.archived_ending(replace(repo.board, read_root=reopened.worktree), reopened, ref.id)
    assert ending["outcome"] == "DONE" and ending["commit"] == "abcdef012345"
    assert ending["archive_note"].endswith(".md") and result.strip() in ending["body"]
    assert receipt.commit


def test_completion_commit_never_invents_delivery():
    assert Outcome(Verdict.DONE).completion_commit == "here"
    assert Outcome(Verdict.DONE, commits=("not-a-sha", "abcdef0123")).completion_commit == "abcdef0123"


def test_guarded_owner_completion_rejects_stale_note_and_claim_then_archives(repo, monkeypatch):
    writer = Writer(repo.board, machine_id="m1")
    writer.sync()
    board = replace(repo.board, read_root=writer.worktree)
    monkeypatch.setattr(store, "synced", lambda *a, **kw: Synced([board], {board.key: writer}, False))
    scope = SimpleNamespace(workspace_id=repo.ws)
    row = board_rows(board)[0]
    params = {"request_id": "owner-done", "slot": board.slot, "task_id": row.ref.id,
              "note": NOTE, "expected_raw": row.raw, "result": "Verified by the owner."}
    for changed in ({"note": "wrong.md"}, {"expected_raw": "older revision"}):
        with pytest.raises(WorkRefused) as refused:
            store.done(scope, {**params, **changed}, "operator")
        assert refused.value.reason is Reason.ROW_CHANGED
    writer.apply(op(Op.CLAIM, rid="held-before-close"))
    held = board_rows(board)[0]
    with pytest.raises(WorkRefused) as refused:
        store.done(scope, {**params, "expected_raw": held.raw}, "operator")
    assert refused.value.reason is Reason.ALREADY_TAKEN
    writer.apply(op(Op.RELEASE, rid="release-before-close"))
    current = board_rows(board)[0]
    answer = store.done(scope, {**params, "expected_raw": current.raw}, "operator")
    assert answer["ending"]["outcome"] == "DONE"
    assert params["result"] in answer["ending"]["body"]
    assert all(r.ref.id != row.ref.id for r in board_rows(board))
    assert archive_notes(board)


def test_guarded_status_refuses_a_claim_even_for_operator(repo):
    writer = Writer(repo.board, machine_id="m1")
    writer.apply(op(Op.CLAIM))
    row = board_rows(replace(repo.board, read_root=writer.worktree))[0]
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.SET_STATUS, who="operator", rid="guard", expected_raw=row.raw,
                        status="DEFERRED 2026-11-03: later"))
    assert refused.value.reason is Reason.ALREADY_TAKEN
    assert "TAKEN" in note_text(repo.seed)


def test_guarded_status_rechecks_revision_after_remote_race(repo):
    fired = []
    def race(args):
        if args[:1] == ["push"] and not fired:
            fired.append(True)
            edit_and_push(repo.other, "`RT-A` — first", "`RT-A` — revised by teammate")
    writer = Writer(repo.board, machine_id="m1", run=recording([], race))
    writer.sync()
    row = board_rows(replace(repo.board, read_root=writer.worktree))[0]
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.SET_STATUS, who="operator", rid="guard-race", expected_raw=row.raw,
                        status="DEFERRED 2026-11-03: later"))
    assert fired and refused.value.reason is Reason.ROW_CHANGED
    text = note_text(repo.seed)
    assert "revised by teammate" in text and "DEFERRED" not in text


def test_brief_edit_versions_content_preserves_identity_and_rejects_stale_or_claimed(repo, monkeypatch):
    writer = Writer(repo.board, machine_id="m1")
    writer.sync()
    board = replace(repo.board, read_root=writer.worktree)
    monkeypatch.setattr(store, "synced", lambda *a, **kw: Synced([board], {board.key: writer}, False))
    scope = SimpleNamespace(workspace_id=repo.ws)
    row = board_rows(board)[0]
    params = {"request_id": "edit-1", "slot": board.slot, "task_id": row.ref.id, "note": NOTE,
              "expected_raw": row.raw, "title": "A clear title", "body": "First complete brief"}
    first = store.edit(scope, params, "operator")["task"]
    assert first["title"] == "A clear title" and first["body"] == params["body"]
    assert first["id"] == row.ref.id and first["status"] == row.status.value and first["taken"] is None
    first_raw = first["raw"]
    old_files = set((writer.worktree / writer.brain_root / store.BRIEF_DIR).glob("*.md"))
    second = store.edit(scope, {**params, "request_id": "edit-2", "expected_raw": first_raw,
                               "body": "Second complete brief"}, "operator")["task"]
    assert second["raw"] != first_raw and second["body"] == "Second complete brief"
    assert all(path.read_text(encoding="utf-8") == params["body"] for path in old_files)
    with pytest.raises(WorkRefused) as stale:
        store.edit(scope, {**params, "request_id": "edit-stale", "expected_raw": first_raw}, "operator")
    assert stale.value.reason is Reason.ROW_CHANGED
    with pytest.raises(WorkRefused) as foreign:
        store.edit(scope, {**params, "request_id": "edit-foreign", "note": "elsewhere.md"}, "operator")
    assert foreign.value.reason is Reason.ROW_CHANGED
    writer.apply(op(Op.CLAIM, rid="hold-edit"))
    held = board_rows(board)[0]
    with pytest.raises(WorkRefused) as claimed:
        store.edit(scope, {**params, "request_id": "edit-held", "expected_raw": held.raw}, "operator")
    assert claimed.value.reason is Reason.ALREADY_TAKEN
