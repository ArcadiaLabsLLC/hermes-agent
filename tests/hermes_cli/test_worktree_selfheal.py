"""Tests for git self-heal: atomic worktree-add failure cleanup + pack maintenance.

Regression for the Aug 2026 `hermes -w` timeout incident: 39 accumulated packs
slowed object lookups until `git worktree add` blew its 30s timeout, and the
timed-out add left a partially-materialized worktree plus a LOCKED admin entry
(lock pid = the live hermes process), poisoning every retry.

Two behaviors:
1. `_cleanup_failed_worktree_add` — removes the partial dir, the admin entry
   (even when LOCKED), and the orphaned branch, so a failed add is atomic.
2. `_maintain_pack_health` — repacks when *.pack count reaches the sprawl
   threshold; no-op below it.
"""

import functools
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


@functools.lru_cache(maxsize=1)
def _geometric_repack_supported() -> bool:
    """Does THIS git RUN the command upstream's repack actually issues?

    ``git repack --geometric`` / ``--write-midx`` landed in git 2.32. Older git exits 129 with
    "unknown option `geometric=2'", and ``_run_bounded_repack`` sends both streams to DEVNULL
    and never reads the return code — so on such a host pack maintenance claims its 6-hour
    slot, runs a command that fails in milliseconds, reports nothing, and then suppresses
    retries for six hours. Measured on this workstation (git 2.31.1.windows.1) while resolving
    the 2026-09-17 upstream merge.

    This RUNS the command in a throwaway repo instead of grepping ``git repack -h``. The first
    version of this helper did grep, for ``"--geometric" in usage`` — and git 2.53 prints the
    flag as ``-g, --[no-]geometric``, so the probe answered False on a git that supports it
    perfectly and would have skipped the multi-pack-index assertion on the one platform that
    can make it. A capability question asked of help TEXT is a question about a spelling; ask
    the binary to do the thing instead.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "probe"
        repo.mkdir()
        env = {**os.environ, "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@example.com",
               "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@example.com"}
        def run(*args, check=True):
            return subprocess.run(["git", *args], cwd=str(repo), env=env,
                                  capture_output=True, text=True, check=check)
        run("init", "-q", ".")
        (repo / "a.txt").write_text("a\n")
        run("add", "-A")
        run("commit", "-qm", "probe")
        return run("repack", "-d", "--geometric=2", "--write-midx", "--quiet",
                   check=False).returncode == 0


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


class TestCleanupFailedWorktreeAdd:
    def _simulate_timed_out_add(self, repo):
        """Reproduce git's post-timeout wreckage: partial dir + LOCKED admin
        entry + branch. Built from a real add then re-locking + damaging it,
        which yields the same on-disk shape as a killed `worktree add`."""
        wt = repo / ".worktrees" / "hermes-dead00"
        _git(repo, "worktree", "add", str(wt), "-b", "hermes/hermes-dead00")
        # Live-pid lock, exactly what `hermes -w` writes before the checkout.
        _git(repo, "worktree", "lock", str(wt), "--reason", "hermes pid=999999")
        # Partial materialization: gut the checkout but keep the dir + .git file.
        for child in wt.iterdir():
            if child.name != ".git":
                child.unlink()
        return wt

    def test_sweeps_dir_admin_entry_and_branch(self, repo):
        from hermes_cli.worktree_ops import _cleanup_failed_worktree_add

        wt = self._simulate_timed_out_add(repo)
        admin = repo / ".git" / "worktrees" / "hermes-dead00"
        assert admin.exists() and (admin / "locked").exists()

        _cleanup_failed_worktree_add(str(repo), wt, "hermes/hermes-dead00")

        assert not wt.exists(), "partial worktree dir must be removed"
        assert not admin.exists(), "LOCKED admin entry must be removed"
        branches = _git(repo, "branch", "--list", "hermes/hermes-dead00").stdout
        assert branches.strip() == "", "orphaned branch must be deleted"

    def test_retry_succeeds_after_cleanup(self, repo):
        """The whole point: the same worktree name is creatable again."""
        from hermes_cli.worktree_ops import _cleanup_failed_worktree_add

        wt = self._simulate_timed_out_add(repo)
        _cleanup_failed_worktree_add(str(repo), wt, "hermes/hermes-dead00")

        result = _git(
            repo, "worktree", "add", str(wt), "-b", "hermes/hermes-dead00", check=False
        )
        assert result.returncode == 0, f"retry failed: {result.stderr}"

    def test_noop_when_nothing_exists(self, repo):
        """Fail-soft on an error path where git never created anything."""
        from hermes_cli.worktree_ops import _cleanup_failed_worktree_add

        _cleanup_failed_worktree_add(
            str(repo), repo / ".worktrees" / "never-existed", "hermes/never-existed"
        )  # must not raise


class TestMaintainPackHealth:
    def _pack_count(self, repo):
        return len(list((repo / ".git" / "objects" / "pack").glob("*.pack")))

    def _make_packs(self, repo, n):
        """Create exactly n distinct packs via git pack-objects (deterministic
        across git versions — incremental `git repack` consolidates small
        packs on newer CI git builds, which made the count nondeterministic)."""
        pack_dir = repo / ".git" / "objects" / "pack"
        pack_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (repo / f"p{i}.txt").write_text(f"{i}\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", f"c{i}")
            sha = _git(repo, "rev-parse", f"HEAD^{{commit}}").stdout.strip()
            # One pack per commit object: pipe the sha into pack-objects.
            subprocess.run(
                ["git", "pack-objects", "-q", str(pack_dir / f"tpack{i}")],
                input=f"{sha}\n", cwd=str(repo), capture_output=True, text=True, check=True,
            )
        return self._pack_count(repo)

    def test_repacks_at_threshold(self, repo, monkeypatch):
        """What upstream's INCREMENTAL geometric repack actually guarantees.

        This used to assert a strict decrease, which was the contract of the old
        ``repack -a -d`` (one pack, always). The 2026-09-17 upstream merge replaced that with
        ``repack -d --geometric=2 --write-midx`` behind a once-per-clone-per-6h slot: a
        geometric repack maintains a size progression and does NOT promise to collapse N packs
        into fewer on any given pass. Asserting the old promise against the new implementation
        pins a contract nobody implements.

        Measured, not assumed, before this was written (git 2.31.1: 12 -> 12, no midx, because
        the flags do not exist there — see ``_geometric_repack_supported``).
        """
        import cli
        from hermes_cli import worktree_ops

        made = self._make_packs(repo, 12)
        threshold = 2
        monkeypatch.setattr(worktree_ops, "_PACK_SPRAWL_THRESHOLD", threshold)
        assert made > threshold, f"fixture failed to produce sprawl (made={made})"

        cli._maintain_pack_health(str(repo))

        # Liveness FIRST, so the assertions below cannot pass by the pass never running:
        # claiming the slot is the observable that the maintenance path went all the way
        # through its guards to the repack.
        assert (repo / ".git" / worktree_ops._REPACK_LOCK).exists(), (
            "maintenance never claimed the repack slot — it returned before repacking, so "
            "everything below would be true of a pass that did nothing"
        )

        after = self._pack_count(repo)
        assert after <= made, f"maintenance must never GROW sprawl (made={made}, after={after})"
        if _geometric_repack_supported():
            # Lookups go through one multi-pack-index. Only assertable where the flag exists.
            assert (repo / ".git" / "objects" / "pack" / "multi-pack-index").exists()

    def test_a_second_pass_inside_the_slot_does_not_repack_again(self, repo, monkeypatch):
        """One repack per clone per ``_REPACK_MIN_INTERVAL``, box-wide.

        Upstream's reason (``_claim_repack_slot``): every ``hermes -w`` launch on a shared
        clone used to start its own full repack, and on a multi-agent box that stacked 50+
        concurrent multi-GB repacks, each too slow under the others to finish inside its
        timeout. The slot is what makes the second launch cheap.

        Pinned at ``_run_bounded_repack`` rather than by comparing pack listings, because on a
        git without ``--geometric`` the listing is identical either way — the count would
        "prove" a no-op that never happened.
        """
        import cli
        from hermes_cli import worktree_ops

        made = self._make_packs(repo, 12)
        monkeypatch.setattr(worktree_ops, "_PACK_SPRAWL_THRESHOLD", 2)
        assert made > 2, f"fixture failed to produce sprawl (made={made})"
        repacks = []
        monkeypatch.setattr(worktree_ops, "_run_bounded_repack", lambda root: repacks.append(root))

        cli._maintain_pack_health(str(repo))
        # Positive control for the refusal below: the FIRST pass must actually repack, or
        # "the second one did not" is a statement about a path nothing ever takes.
        assert repacks == [str(repo)], f"first pass did not repack (repacks={repacks})"

        cli._maintain_pack_health(str(repo))
        assert repacks == [str(repo)], (
            f"a second pass inside the 6h slot repacked again (repacks={repacks})"
        )

    def test_noop_below_threshold(self, repo, monkeypatch):
        import cli
        from hermes_cli import worktree_ops

        made = self._make_packs(repo, 2)
        monkeypatch.setattr(worktree_ops, "_PACK_SPRAWL_THRESHOLD", 50)

        cli._maintain_pack_health(str(repo))

        assert self._pack_count(repo) == made, "below threshold must be a no-op"  # noqa: same-count contract

    def test_fail_soft_on_missing_pack_dir(self, tmp_path):
        from cli import _maintain_pack_health

        _maintain_pack_health(str(tmp_path / "not-a-repo"))  # must not raise


class TestRepackStampede:
    """Regression for the Sep 2026 shared-clone incident: every ``hermes -w`` launch started its
    own full repack, and a timed-out repack left ``pack-objects`` running for days."""

    def test_one_repack_per_clone_per_interval(self, repo, monkeypatch):
        from hermes_cli import worktree_ops

        monkeypatch.setattr(worktree_ops, "_PACK_SPRAWL_THRESHOLD", 0)
        runs: list = []
        monkeypatch.setattr(worktree_ops, "_run_bounded_repack", lambda root: runs.append(root))

        for _ in range(3):  # three concurrent-ish launches sharing the clone
            worktree_ops._maintain_pack_health(str(repo))
        assert runs == [str(repo)], "N launches inside the interval must produce exactly one repack"

        # A stale stamp (older than the interval) hands the slot to the next launch.
        monkeypatch.setattr(worktree_ops, "_REPACK_MIN_INTERVAL", 0)
        worktree_ops._maintain_pack_health(str(repo))
        assert len(runs) == 2

    @pytest.mark.linux_only
    def test_timeout_kills_the_whole_repack_tree(self, tmp_path, monkeypatch):
        import os
        import time

        from hermes_cli import worktree_ops

        # A stand-in ``git`` that forks a long-lived grandchild, the way repack forks pack-objects.
        shim_dir = tmp_path / "bin"
        shim_dir.mkdir()
        pidfile = tmp_path / "grandchild.pid"
        shim = shim_dir / "git"
        shim.write_text(f"#!/bin/sh\nsleep 300 &\necho $! > {pidfile}\nwait\n")
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setattr(worktree_ops, "_REPACK_TIMEOUT", 1)

        worktree_ops._run_bounded_repack(str(tmp_path))

        grandchild = int(pidfile.read_text().strip())
        deadline = time.time() + 5
        while time.time() < deadline:
            if not Path(f"/proc/{grandchild}").exists():
                return
            time.sleep(0.05)
        subprocess.run(["kill", "-9", str(grandchild)], check=False)
        pytest.fail("pack-objects stand-in survived the repack timeout")
