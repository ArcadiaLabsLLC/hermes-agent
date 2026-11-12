"""The git half of a realm re-key: worktrees found again, and ONE new commit in the workspace's own brain
(RT-REKEY-BRAIN-AND-WORKTREES-FOLLOW).

Plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §4(e). ``work/<workspace>/`` moved
whole in the rename step, so by the time this runs every path below is the NEW one.

* **Worktrees.** A linked worktree's ``.git`` file names its repository by absolute path, and the repository
  names the worktree back. Each ``.git`` file under ``work/<ws>/`` is re-pointed by path piece (a worktree of
  the workspace's own brain: both moved; one cut from the member's clone: unchanged), then ``git worktree
  repair`` run in the worktree writes the repository's back link.
* **Hermes's own Writer worktrees** (``work/<ws>/worktrees/``) are removed: each is a sparse, reset-on-every-sync
  view on a branch named after the old workspace id, and the Writer cuts a new one on demand.
* **A batch lane's worktree** (``work/<ws>/.worktrees/``) is kept as it is, uncommitted work included; what it
  has checked out is its branch's and reaches the brain by a merge.
* **The one commit.** In the workspace's own brain, when it is this machine's alone (no remote): the workspace
  ids and agent ids of the map are rewritten in its markdown as whole tokens — the batch notes' ``workspace_id``,
  the claim text ``persona:<agent>`` — and committed under hermes's identity. History is never rewritten: the
  commits before it keep the old ids, which is what they should say. A brain that has a remote is the team's
  (or the member's own repository) and is left alone, like the branch names in a member's clone.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import paths
from .git_cmd import run_git

__layer__ = "lanes"
__all__ = ["LANE_WORKTREES_DIRNAME", "step_git"]

#: ``batch/lane_git.py`` cuts a lane beside its clone, under this name.
LANE_WORKTREES_DIRNAME = ".worktrees"
_GITDIR = "gitdir:"


def _git(repo: Path, *args: str, config: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    return run_git(list(args), repo=repo, config=config, timeout=60, stdin=subprocess.DEVNULL, encoding="utf-8")


def _linked_worktrees(base: Path, forms: dict[str, str]) -> dict[Path, list[Path]]:
    """``{repository: [worktree, ...]}`` for every linked worktree under ``base``, its ``.git`` file re-pointed."""
    from .realm_rekey import rewrite_text

    by_repo: dict[Path, list[Path]] = {}
    for marker in sorted(base.rglob(".git")):
        if not marker.is_file():
            continue
        text = marker.read_text(encoding="utf-8").strip()
        if not text.startswith(_GITDIR):
            continue
        admin = text[len(_GITDIR):].strip()
        moved = rewrite_text(admin, forms)
        if moved != admin:
            marker.write_text(f"{_GITDIR} {moved}\n", encoding="utf-8")
        by_repo.setdefault(Path(moved).parent.parent.parent, []).append(marker.parent)
    return by_repo


def _repair_worktrees(workspace_id: str, base: Path, forms: dict[str, str]) -> None:
    writer_trees = paths.work_worktrees_dir(workspace_id)
    for repo, trees in _linked_worktrees(base, forms).items():
        for tree in trees:
            _git(tree, "worktree", "repair")  # its ``.git`` file is right again: write the repository's back link
            if writer_trees in tree.parents:
                if _git(repo, "worktree", "remove", "--force", str(tree)).returncode != 0:
                    shutil.rmtree(tree, ignore_errors=True)
                    _git(repo, "worktree", "prune")


def _commit_new_ids(workspace_id: str, tokens: dict[str, str]) -> None:
    from .realm_rekey import token_pattern
    from .work_store.board import read_binding
    from .work_store.default_brain import IDENTITY_PAIRS

    brain = paths.default_brain_dir(workspace_id)
    record = read_binding(workspace_id) or {}
    if not (brain / ".git").is_dir() or record.get("remote_url") or not tokens:
        return
    pattern = token_pattern(tokens)
    changed = []
    for name in _git(brain, "ls-files", "-z", "--", "*.md").stdout.split("\0"):
        path = brain / name
        if not name or not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="surrogateescape")  # bytes in, bytes out: line ends kept
        rewritten = pattern.sub(lambda match: tokens[match.group(1)], text)
        if rewritten != text:
            path.write_bytes(rewritten.encode("utf-8", errors="surrogateescape"))
            changed.append(name)
    if changed:
        machine = str(record.get("machine") or "local")
        _git(brain, "add", "--", *changed, config=IDENTITY_PAIRS(machine))
        _git(brain, "commit", "-q", "-m", f"work: this copy's own ids ({workspace_id})", "--", *changed,
             config=IDENTITY_PAIRS(machine))


def step_git(root: Path, mapping: Any) -> None:
    """After the rename: per moved workspace, find its worktrees again, then the one commit. Re-run it finds
    nothing to re-point and nothing left to rewrite."""
    if shutil.which("git") is None:
        return  # no git here: nothing cut a worktree or a brain on this machine, and the Writer recuts
    forms = mapping.forms()
    tokens = {**mapping.workspaces, **mapping.agents}
    for workspace_id in mapping.workspaces.values():
        base = paths.work_workspace_dir(workspace_id)
        if base.is_dir():
            _repair_worktrees(workspace_id, base, forms)
            _commit_new_ids(workspace_id, tokens)
