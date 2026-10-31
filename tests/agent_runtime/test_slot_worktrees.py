"""RT-WORKTREE-RECORDED-ON-SLOT: a git worktree a turn cuts is recorded against its repo slot's folder."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runtime import slot_worktrees as sw

TURN = "machine:mach_1/namespace:base/persona-instance:personainst_neko/chat:c1/turn:t1"


def _porcelain(*linked: tuple[str, str]) -> str:
    out = "worktree C:/slots/launcher\nHEAD aaaa\nbranch refs/heads/main\n\n"
    for path, branch in linked:
        out += f"worktree {path}\nHEAD bbbb\nbranch refs/heads/{branch}\n\n"
    return out


def test_the_slot_checkout_itself_is_never_a_development_workspace():
    assert sw.parse_porcelain(_porcelain()) == {}
    assert sw.parse_porcelain(_porcelain(("C:/wt/x", "feat"))) == {"C:/wt/x": {"head": "bbbb", "branch": "feat"}}


def test_a_worktree_first_seen_at_a_turn_end_is_that_turns_and_its_removal_is_recorded(tmp_path):
    repo = tmp_path / "launcher"
    listing = {"text": _porcelain()}
    run = lambda _repo: listing["text"]
    assert sw.observe("ws_1", "launcher", repo, phase=sw.PHASE_START, turn=TURN, run=run) == {"created": [], "removed": []}
    listing["text"] = _porcelain(("C:/wt/x", "feat"))
    assert sw.observe("ws_1", "launcher", repo, phase=sw.PHASE_END, turn=TURN, run=run)["created"] == ["C:/wt/x"]
    row = sw.load_ledger("ws_1", "launcher")["worktrees"]["C:/wt/x"]
    assert row["created_by_turn"] == TURN and row["branch"] == "feat" and row["removed_at"] is None
    listing["text"] = _porcelain()
    later = TURN.replace("t1", "t2")
    assert sw.observe("ws_1", "launcher", repo, phase=sw.PHASE_END, turn=later, run=run)["removed"] == ["C:/wt/x"]
    row = sw.load_ledger("ws_1", "launcher")["worktrees"]["C:/wt/x"]
    assert row["removed_seen_by_turn"] == later and row["created_by_turn"] == TURN


def test_a_worktree_first_seen_at_a_turn_start_was_cut_outside_any_turn(tmp_path):
    run = lambda _repo: _porcelain(("C:/wt/operator", "op"))
    sw.observe("ws_1", "launcher", tmp_path, phase=sw.PHASE_START, turn=TURN, run=run)
    assert sw.load_ledger("ws_1", "launcher")["worktrees"]["C:/wt/operator"]["created_by_turn"] is None


def test_an_unreadable_listing_infers_nothing(tmp_path):
    run = lambda _repo: _porcelain(("C:/wt/x", "feat"))
    sw.observe("ws_1", "launcher", tmp_path, phase=sw.PHASE_END, turn=TURN, run=run)
    assert sw.observe("ws_1", "launcher", tmp_path, phase=sw.PHASE_END, turn=TURN, run=lambda _r: None) == {
        "created": [], "removed": []}
    assert sw.load_ledger("ws_1", "launcher")["worktrees"]["C:/wt/x"]["removed_at"] is None


def test_the_real_git_listing_round_trips(tmp_path):
    repo = tmp_path / "slot"
    repo.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run([*git, "-C", str(repo), "worktree", "add", "-q", "-b", "lane", str(tmp_path / "wt")], check=True)
    seen = sw.parse_porcelain(sw._git_worktrees(repo) or "")
    assert [Path(p).name for p in seen] == ["wt"] and next(iter(seen.values()))["branch"] == "lane"


def test_a_turn_observes_at_its_start_then_at_its_end_off_its_own_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(sw, "observe_bound_slots", lambda ws, *, phase, turn, run: calls.append((ws, phase, turn)) or {})
    watch = sw.TurnObservation("ws_1", TURN)
    watch.finish()
    watch.finish()  # a second finish is a no-op
    watch.join(5)
    assert calls == [("ws_1", sw.PHASE_START, TURN), ("ws_1", sw.PHASE_END, TURN)]
    calls.clear()
    sw.TurnObservation(None, TURN).finish()  # no realm workspace: nothing observed
    assert calls == []
