"""``agent_runtime.skill_lends`` — a worker's lend record (p10-work S2, RT-ETERNIA-SKILLS-LENDS-SKILLS)."""
from __future__ import annotations

import os
import subprocess
import sys

from agent_runtime import paths, skill_lends


def test_lend_union_revoke_difference_and_sweep_of_dead_children():
    first = skill_lends.lend("child:a", ["git", "qa"], owner_session="s1", by="s1")
    assert first.skills == ("git", "qa") and first.pid == os.getpid()
    assert skill_lends.lend("child:a", ["qa", "pytest"], owner_session="s1", by="s1").skills == ("git", "qa", "pytest")
    assert skill_lends.revoke("child:a", ["git", "pytest"]).skills == ("qa",)
    assert skill_lends.revoke("child:a", ["qa"]) is None and skill_lends.lent_to("child:a") == ()
    assert skill_lends.revoke("child:never", ["qa"]) is None

    for target in ("child:live", "child:done"):
        skill_lends.lend(target, ["git"], owner_session="s1", by="s1")
    assert skill_lends.sweep(lambda subagent_id: subagent_id == "live") == 1
    assert skill_lends.lent_to("child:live") == ("git",) and skill_lends.lent_to("child:done") == ()

    # Another process's record: kept while that process lives, dropped once it is dead.
    skill_lends.lend("child:elsewhere", ["git"], owner_session="s1", by="s1")
    assert skill_lends.sweep(lambda subagent_id: False, pid=os.getpid() + 1_000_000) == 0
    dead = int(subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True,
                              text=True).stdout)
    skill_lends._write_lend(skill_lends.LendRecord("child:orphan", "s1", ("git",), "now", "s1", dead))
    assert skill_lends.sweep(lambda subagent_id: subagent_id in ("live", "elsewhere")) == 1
    assert skill_lends.lent_to("child:orphan") == () and skill_lends.lent_to("child:elsewhere") == ("git",)
    assert sorted(p.stem for p in (paths.store_root() / "skill_lends").glob("*.json")) == ["child_elsewhere", "child_live"]
