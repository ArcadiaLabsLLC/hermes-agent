"""The Work writer against real git: a bare ``origin.git``, a clone bound as the slot, hermes's own
worktree, and a second clone playing "the other machine" (plan §5, §6.2)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.git_cmd import run_git
from agent_runtime.work_store.board import boards
from agent_runtime.work_store.default_brain import ensure_default_brain
from agent_runtime.work_store.grammar import Op, RowRef, parse_note
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.writer import OPERATOR, RowOp, Writer

from work_store_support import ISSUED, LATER, bind_here, declare_slots, slot_decl

NOTE = "Harness_Brain/20 — Active Initiatives/q.md"
ROWS = ("- **`RT-A` — first** · READY 2026-10-18\n"
        "- **`RT-B` — second** · READY 2026-10-18\n")
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
ID = ("-c", "user.name=Test Session", "-c", "user.email=session@test.invalid")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *ID, *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def note_text(clone: Path) -> str:
    git("pull", "-q", "--ff-only", cwd=clone)
    return (clone / NOTE).read_text(encoding="utf-8")


def edit_and_push(clone: Path, old: str, new: str) -> None:
    git("pull", "-q", "--ff-only", cwd=clone)
    path = clone / NOTE
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8", newline="\n")
    git("commit", "-q", "-am", f"session edit {new[:20]}", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)


@pytest.fixture
def repo(tmp_path: Path, workspace: str) -> SimpleNamespace:
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    (seed / NOTE).parent.mkdir(parents=True)
    (seed / NOTE).write_text(HEAD + ROWS, encoding="utf-8", newline="\n")
    (seed / "README.md").write_text("outside the brain\n", encoding="utf-8")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    other = tmp_path / "other"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=clone)
    board = next(b for b in boards(workspace) if b.slot == "hermes")
    return SimpleNamespace(ws=workspace, origin=origin, clone=clone, other=other, seed=seed, board=board)


def op(kind: Op, row_id: str = "RT-A", who: str = "persona:pi_a", rid: str = "r1", **payload) -> RowOp:
    return RowOp(RowRef("hermes", NOTE, row_id), kind, who, rid, payload)


def recording(calls: list[list[str]], hook=None):
    def run(args, **kwargs):
        calls.append(list(args))
        if hook is not None:
            answer = hook(list(args))
            if answer is not None:
                return answer
        return run_git(args, **kwargs)
    return run


def taken_count(text: str) -> int:
    return text.count("**TAKEN ")


def test_claim_lands_as_one_commit_pushed_fast_forward(repo):
    before = git("rev-parse", "main", cwd=repo.origin).strip()
    receipt = Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM))
    assert receipt.pushed and receipt.replays == 0 and not receipt.replayed and receipt.kind == "work.row_claim"
    assert git("rev-parse", "main", cwd=repo.origin).strip() == receipt.commit
    assert git("rev-parse", f"{receipt.commit}^", cwd=repo.origin).strip() == before
    text = note_text(repo.other)
    assert "- **`RT-A` — first** · READY 2026-10-18 · **TAKEN " in text and "persona:pi_a**" in text


def test_a_raced_claim_replays_and_exactly_one_taken_exists(repo):
    fired: list[int] = []

    def other_machine_pushes_first(args):
        if args[:1] == ["push"] and not fired:
            fired.append(1)
            edit_and_push(repo.other, "`RT-B` — second** · READY", "`RT-B` — second** · assignee: persona:x · READY")

    writer = Writer(repo.board, machine_id="m1", run=recording([], other_machine_pushes_first))
    receipt = writer.apply(op(Op.CLAIM))
    assert fired and receipt.replays == 1 and receipt.pushed
    text = note_text(repo.seed)
    assert taken_count(text) == 1 and "assignee: persona:x" in text
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.CLAIM, who="persona:pi_b", rid="r2"))
    assert refused.value.reason is Reason.ALREADY_TAKEN and refused.value.detail == "persona:pi_a"
    assert taken_count(note_text(repo.seed)) == 1


def test_row_landed_meanwhile_answers_row_gone(repo):
    writer = Writer(repo.board, machine_id="m1")
    writer.sync()
    edit_and_push(repo.other, "- **`RT-A` — first** · READY 2026-10-18\n", "")
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.CLAIM))
    assert refused.value.reason is Reason.ROW_GONE


def test_not_claimant_and_operator_override(repo):
    writer = Writer(repo.board, machine_id="m1")
    writer.apply(op(Op.CLAIM))
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.RELEASE, who="persona:pi_b", rid="r2"))
    assert refused.value.reason is Reason.NOT_CLAIMANT
    receipt = writer.apply(op(Op.RELEASE, who=OPERATOR, rid="r3"))
    assert receipt.commit and taken_count(note_text(repo.other)) == 0


def test_append_refuses_an_existing_id(repo):
    writer = Writer(repo.board, machine_id="m1")
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.APPEND, row_id="RT-B", rid="r1", row="- **`RT-B` — again** · READY 2026-10-18"))
    assert refused.value.reason is Reason.ID_EXISTS
    receipt = writer.apply(op(Op.APPEND, row_id="RT-C", rid="r2", row="- **`RT-C` — new** · READY 2026-10-18"))
    assert receipt.commit and note_text(repo.other).endswith("- **`RT-C` — new** · READY 2026-10-18\n")


def test_replay_by_request_id_returns_the_recorded_commit(repo):
    writer = Writer(repo.board, machine_id="m1")
    first = writer.apply(op(Op.CLAIM))
    again = writer.apply(op(Op.CLAIM))
    assert again.replayed and again.commit == first.commit
    assert git("rev-parse", "main", cwd=repo.origin).strip() == first.commit


def test_push_contended_after_eight_replays(repo):
    calls: list[list[str]] = []
    rejected = subprocess.CompletedProcess(["git", "push"], 1, "", " ! [rejected]        main (fetch first)\n")
    writer = Writer(repo.board, machine_id="m1", run=recording(calls, lambda a: rejected if a[:1] == ["push"] else None))
    with pytest.raises(WorkRefused) as refused:
        writer.apply(op(Op.CLAIM))
    assert refused.value.reason is Reason.PUSH_CONTENDED
    assert sum(1 for call in calls if call[:1] == ["push"]) == 8
    assert len(refused.value.detail.split(":", 1)[1].split(",")) == 8


def test_fetch_failure_is_typed_and_writes_nothing(repo, tmp_path):
    before = git("rev-parse", "main", cwd=repo.origin).strip()
    git("remote", "set-url", "origin", str(tmp_path / "nowhere.git"), cwd=repo.clone)
    with pytest.raises(WorkRefused) as refused:
        Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM))
    assert refused.value.reason is Reason.FETCH_FAILED
    assert git("rev-parse", "main", cwd=repo.origin).strip() == before


def test_slot_unbound_and_remote_missing(repo, tmp_path):
    declare_slots(repo.ws, slot_decl("hermes"), slot_decl("away"), issued_at=LATER)
    away = next(b for b in boards(repo.ws) if b.slot == "away")
    with pytest.raises(WorkRefused) as unbound:
        Writer(replace(away, brain_dir="X_Brain/20 — Active Initiatives"), machine_id="m1").sync()
    assert unbound.value.reason is Reason.SLOT_UNBOUND
    git("remote", "remove", "origin", cwd=repo.clone)
    with pytest.raises(WorkRefused) as missing:
        Writer(repo.board, machine_id="m1").sync()
    assert missing.value.reason is Reason.REMOTE_MISSING


def test_a_local_slot_skips_fetch_and_push(workspace):
    board = ensure_default_brain(workspace, issued_at=ISSUED)
    calls: list[list[str]] = []
    writer = Writer(board, machine_id="m1", run=recording(calls))
    note = f"{board.brain_dir}/work-queue.md"
    row = "- **`WORK-A2B3C4` — local** · READY 2026-10-18"
    receipt = writer.apply(RowOp(RowRef(board.slot, note, "WORK-A2B3C4"), Op.APPEND, "operator", "r1", {"row": row}))
    assert not receipt.pushed and receipt.commit
    assert not any(call[:1] in (["fetch"], ["push"]) for call in calls)
    brain = Path(str(board.read_root))
    assert git("rev-parse", "main", cwd=brain).strip() == receipt.commit
    assert row in git("show", f"main:{note}", cwd=brain)


def test_dirty_worktree_is_cleaned_once_then_refused(repo):
    writer = Writer(repo.board, machine_id="m1")
    worktree = writer.sync()
    (worktree / "Harness_Brain" / "dropped.md").write_text("someone's file\n", encoding="utf-8")
    assert writer.apply(op(Op.CLAIM)).commit
    stuck = Writer(repo.board, machine_id="m1", run=recording(
        [], lambda a: subprocess.CompletedProcess(a, 0, "", "") if a[:1] == ["clean"] else None))
    (worktree / "Harness_Brain" / "dropped.md").write_text("again\n", encoding="utf-8")
    with pytest.raises(WorkRefused) as refused:
        stuck.apply(op(Op.RELEASE, rid="r2"))
    assert refused.value.reason is Reason.WORKTREE_DIRTY


def test_stale_worktree_registration_is_pruned(repo):
    import shutil

    writer = Writer(repo.board, machine_id="m1")
    shutil.rmtree(writer.sync())
    assert writer.apply(op(Op.CLAIM)).commit
    assert (writer.worktree / NOTE).is_file() and not (writer.worktree / "README.md").exists()


def test_the_clone_index_and_tree_never_change(repo):
    (repo.clone / "README.md").write_text("operator's staged edit\n", encoding="utf-8")
    git("add", "README.md", cwd=repo.clone)
    (repo.clone / NOTE).write_text("operator's unstaged edit\n", encoding="utf-8")
    index = hashlib.sha256((repo.clone / ".git" / "index").read_bytes()).hexdigest()
    head = git("rev-parse", "HEAD", cwd=repo.clone)
    Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM))
    assert hashlib.sha256((repo.clone / ".git" / "index").read_bytes()).hexdigest() == index
    assert git("rev-parse", "HEAD", cwd=repo.clone) == head
    assert (repo.clone / NOTE).read_text(encoding="utf-8") == "operator's unstaged edit\n"
    assert (repo.clone / "README.md").read_text(encoding="utf-8") == "operator's staged edit\n"


def test_commit_identity_is_hermes_via_c_pairs_not_config(repo):
    Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM))
    assert git("log", "-1", "--format=%an <%ae>", "main", cwd=repo.origin).strip() == \
        "Eternia Harness <harness+m1@eternia.local>"
    config = (repo.clone / ".git" / "config").read_text(encoding="utf-8")
    assert "[user]" not in config and "eternia.local" not in config


def test_grammar_invalid_note_is_never_edited(repo):
    edit_and_push(repo.other, "- **`RT-B` — second** · READY 2026-10-18",
                  "- **`RT-B` — second** · READY 2026-10-18 · READY 2026-10-19")
    before = git("rev-parse", "main", cwd=repo.origin).strip()
    with pytest.raises(WorkRefused) as refused:
        Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM))
    assert refused.value.reason is Reason.GRAMMAR_INVALID and ":9:" in refused.value.detail
    assert git("rev-parse", "main", cwd=repo.origin).strip() == before


def test_history_names_the_deleting_commit_and_its_result(repo):
    writer = Writer(repo.board, machine_id="m1")
    writer.apply(op(Op.CLAIM))
    gone = writer.apply(op(Op.DELETE, rid="r2", result="shipped it"))
    ending = writer.history(RowRef("hermes", NOTE, "RT-A"))
    assert ending["commit"] == gone.commit and "result: shipped it" in ending["body"]
    assert ending["subject"].startswith("work: delete RT-A persona:pi_a")
    rows = parse_note(note_text(repo.other), slot="hermes", note=NOTE)
    assert [row.ref.id for row in rows] == ["RT-B"]


def test_a_qa_namespace_never_pushes_to_a_network_remote(repo, monkeypatch):
    """RT-WORK-QA-NAMESPACE-PUSH-FENCE: a ``stagec-*`` namespace writes through a local origin only.
    Control: the same namespace's write through the fixture's local origin lands. The runner STUBS
    ``push`` (FH-QA-FENCE-TEST-REAL-PUSH): a regressed fence reds here without a network push."""
    from agent_runtime import namespace

    assert namespace.qa_namespace({"HERMES_NAMESPACE": "stagec-smoke"})
    assert not namespace.qa_namespace({"HERMES_NAMESPACE": "acct-0123456789abcdef"})
    monkeypatch.setattr(namespace, "qa_namespace", lambda env=None: True)
    assert Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM)).pushed
    before = git("rev-parse", "main", cwd=repo.origin).strip()
    def never_push(args):
        return subprocess.CompletedProcess(args, 0, "", "") if args[:1] == ["push"] else None

    for url in ("https://github.com/acme/brain.git", "git@github.com:acme/brain.git", "relative/brain.git"):
        git("remote", "set-url", "--push", "origin", url, cwd=repo.clone)
        calls: list[list[str]] = []
        with pytest.raises(WorkRefused) as refused:
            Writer(repo.board, machine_id="m1", run=recording(calls, never_push)).apply(
                op(Op.RELEASE, rid=f"r-{len(url)}"))
        assert refused.value.reason is Reason.PUSH_REFUSED, url
        assert not any(call[:1] in (["push"], ["commit"]) for call in calls), url
    assert git("rev-parse", "main", cwd=repo.origin).strip() == before


def _zero_index(worktree: Path) -> Path:
    index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index", cwd=worktree).strip())
    index.write_bytes(b"\0" * 358)  # the shape found on 2026-10-30: a 358-byte all-zero index
    return index


def test_a_zeroed_worktree_index_is_moved_aside_and_the_write_lands(repo):
    """RT-WORK-INDEX-SELF-HEAL. Mutation: drop the heal-and-retry in ``_reset`` -> refused index_corrupt."""
    writer = Writer(repo.board, machine_id="m1")
    index = _zero_index(writer.sync())
    receipt = writer.apply(op(Op.CLAIM))
    assert receipt.commit and "**TAKEN " in note_text(repo.other)
    assert [p.name for p in index.parent.glob("index.corrupt-*")] and index.read_bytes()[:4] == b"DIRC"


def test_an_index_that_stays_corrupt_refuses_index_corrupt_not_branch_missing(repo):
    """Mutation: map git's "index file corrupt" to the caller's reason in ``_must`` -> branch_missing."""
    writer = Writer(repo.board, machine_id="m1")
    _zero_index(writer.sync())
    stuck = Writer(repo.board, machine_id="m1", run=recording([], lambda a: subprocess.CompletedProcess(
        a, 128, "", "error: bad signature 0x00000000\nfatal: index file corrupt\n") if a[:1] == ["reset"] else None))
    with pytest.raises(WorkRefused) as refused:
        stuck.apply(op(Op.CLAIM))
    assert refused.value.reason is Reason.INDEX_CORRUPT and "index file corrupt" in refused.value.detail
    # Positive control: an ordinary reset failure keeps its own word.
    other = Writer(repo.board, machine_id="m1", run=recording([], lambda a: subprocess.CompletedProcess(
        a, 128, "", "fatal: ambiguous argument 'origin/main'\n")
        if a[:1] == ["reset"] or a[:3] == ["rev-parse", "-q", "--verify"] else None))
    with pytest.raises(WorkRefused) as plain:
        other.apply(op(Op.CLAIM, rid="r2"))
    assert plain.value.reason is Reason.BRANCH_MISSING


def test_a_reset_git_fails_with_the_tip_present_is_worktree_failed_not_branch_missing(repo):
    """RT-WORK-WRITER-LONGPATHS. Mutation: drop the tip check in ``_reset_to_tip`` -> branch_missing."""
    Writer(repo.board, machine_id="m1").sync()
    long = Writer(repo.board, machine_id="m1", run=recording([], lambda a: subprocess.CompletedProcess(
        a, 128, "", "error: unable to create file X: Filename too long\n") if a[:1] == ["reset"] else None))
    with pytest.raises(WorkRefused) as refused:
        long.apply(op(Op.CLAIM))
    assert refused.value.reason is Reason.WORKTREE_FAILED and "Filename too long" in refused.value.detail


def test_every_writer_git_call_carries_core_longpaths(repo):
    """RT-WORK-WRITER-LONGPATHS. Mutation: drop ``_REPO_CONFIG`` from ``Writer._git`` -> red."""
    seen: list[tuple[list[str], tuple[str, ...]]] = []

    def run(args, **kwargs):
        seen.append((list(args), tuple(kwargs.get("config") or ())))
        return run_git(args, **kwargs)

    Writer(repo.board, machine_id="m1", run=run).apply(op(Op.CLAIM))
    # ``checkout_token``'s common-dir probe is the module's, not ``Writer._git``'s, and reads no tree path.
    door = [(args, config) for args, config in seen if "--git-common-dir" not in args]
    assert door and all("core.longpaths=true" in config for _args, config in door), \
        [args for args, config in door if "core.longpaths=true" not in config]


def _write_long(path: Path, text: str) -> None:
    """Write past Windows' 260-character limit (the ``\\\\?\\`` prefix), anywhere else plainly."""

    name = "\\\\?\\" + str(path) if os.name == "nt" else str(path)
    os.makedirs(os.path.dirname(name), exist_ok=True)
    with open(name, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def test_a_brain_note_past_260_characters_syncs(tmp_path, workspace):
    """RT-WORK-WRITER-LONGPATHS: a tip holding a note whose worktree path passes 260 characters resets and
    lands (behaviour proof; a box whose git sets core.longpaths system-wide passes it either way —
    the killing test is test_every_writer_git_call_carries_core_longpaths)."""
    origin = tmp_path / "o.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / "s"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    _write_long(seed / NOTE, HEAD + ROWS)
    deep = "Harness_Brain/50 — Agent Handoffs/" + "/".join(["a-rather-long-folder-name-for-a-handoff"] * 5)
    _write_long(seed / deep / "Hermes handoff — a deep note.md", "deep\n")
    git("-c", "core.longpaths=true", "add", "-A", cwd=seed)
    git("-c", "core.longpaths=true", "commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    clone = tmp_path / "c"
    git("-c", "core.longpaths=true", "clone", "-q", "-c", "core.longpaths=true", str(origin), str(clone), cwd=tmp_path)
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=clone)
    board = next(b for b in boards(workspace) if b.slot == "hermes")
    writer = Writer(board, machine_id="m1")
    assert writer.apply(op(Op.CLAIM)).commit
    assert len(str(writer.worktree / deep / "Hermes handoff — a deep note.md")) > 260


ARCHIVE = "Harness_Brain/80 — Archive/Queues/q-2026-11.md"


def test_a_close_creates_the_month_file_appends_the_next_and_drops_the_live_line_in_one_commit(repo):
    """RT-QUEUE-ARCHIVE-GRAMMAR. Mutation: skip the live-line drop in ``Writer._close`` -> the row is both live
    and archived, red; write the archive without its head -> the note is not a queue-archive, red."""
    from agent_runtime.work_store.grammar import is_queue_archive

    writer = Writer(repo.board, machine_id="m1")
    first = writer.apply(op(Op.CLOSE, outcome="DONE", commit="3f9c2a1", date="2026-11-03", result="shipped"))
    assert git("rev-list", "--count", f"{first.commit}^..{first.commit}", cwd=repo.origin).strip() == "1"
    changed = git("-c", "core.quotePath=false", "show", "--name-only", "--format=", first.commit,
                  cwd=repo.origin).split("\n")
    assert set(filter(None, changed)) == {NOTE, ARCHIVE}
    writer.apply(op(Op.CLOSE, row_id="RT-B", rid="r2", outcome="REFUTED", commit="here", date="2026-11-04"))
    git("pull", "-q", "--ff-only", cwd=repo.other)
    archive = (repo.other / ARCHIVE).read_text(encoding="utf-8")
    assert is_queue_archive(archive) and "queue: q.md" in archive and "program: test" in archive
    assert "month: 2026-11" in archive
    archived = parse_note(archive, slot="hermes", note=ARCHIVE)
    assert [(r.ref.id, r.outcome.render(), r.result, r.defects) for r in archived] == [
        ("RT-A", "DONE 2026-11-03 3f9c2a1", "shipped", ()), ("RT-B", "REFUTED 2026-11-04 here", None, ())]
    assert parse_note(note_text(repo.other), slot="hermes", note=NOTE) == []
    assert "result: shipped" in git("log", "-1", "--format=%B", first.commit, cwd=repo.origin)


def test_two_writers_of_one_worktree_are_admitted_one_at_a_time(repo, monkeypatch):
    """RT-WORK-BATCH-WRITER-CONTENTION: a second Writer of the same worktree (the batch manifest's beside a Work
    request's) waits for the first's admission and, past the bound, refuses ``index_locked`` "writer busy" — it
    never runs ``reset --hard`` beside a live one. Killing mutation: ``sync`` without ``with self.admitted()``
    — the busy sync lands while the first writer holds the worktree."""
    import threading

    from agent_runtime import locks

    monkeypatch.setattr(locks, "_lock_timeout_seconds", lambda _value: 0.2)
    first, second = Writer(repo.board, machine_id="m1"), Writer(repo.board, machine_id="m1")
    first.sync()
    seen: list[object] = []

    def other_thread() -> None:
        try:
            second.sync()
            seen.append("synced")
        except WorkRefused as refused:
            seen.append(refused)

    with first.admitted():
        worker = threading.Thread(target=other_thread)
        worker.start()
        worker.join(10)
        # the same thread stays admitted: another instance of the worktree is reentrant here
        Writer(repo.board, machine_id="m1").apply(op(Op.CLAIM))
    assert len(seen) == 1 and isinstance(seen[0], WorkRefused)
    assert seen[0].reason is Reason.INDEX_LOCKED and seen[0].detail.startswith("writer busy: ")
    assert second.sync() == second.worktree  # released: the next sync is admitted
    assert taken_count(note_text(repo.other)) == 1
