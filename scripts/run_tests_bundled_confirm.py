"""``--confirm-red <file>``: is a named red the branch's, pre-existing, or load?

Owner ruling 2026-10-16: confirming a named red means that ONE file, run alone on
the branch and on ``origin/main``, never the suite. The file runs alone on HEAD
(this checkout); green there, its red was load — the bundle, the workers, the box
— and is never the branch's (``load``). Red there, it runs alone in a detached
worktree of the base, cut under ``worktrees/`` beside the clone from a neutral cwd
and removed after:
green on the base, or failing a node the base does not, the red is the branch's
(``caused``, the new node ids printed); every failing node failing on the base too
is ``pre-existing``. Exit 1 on ``caused``, 0 otherwise.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Tuple

FLAGS = frozenset({"--confirm-red", "--confirm-base"})
DEFAULT_BASE = "origin/main"
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)")
#: pytest args of the one-file runs: every failing node id in the short summary
PYTEST_ARGS = ("-q", "-rfE", "-p", "no:cacheprovider")

#: (file, cwd, timeout) → (rc, output)
Runner = Callable[[Path, Path, float], tuple[int, str]]


class Verdict(str, Enum):
    CAUSED = "caused"
    PRE_EXISTING = "pre-existing"
    LOAD = "load"


@dataclass
class Attempt:
    where: str
    rc: int
    failing: frozenset = field(default_factory=frozenset)


def failing_ids(output: str) -> frozenset:
    return frozenset(m.group(1) for m in map(_FAILED.match, output.splitlines()) if m)


def judge(head: Attempt, base: Optional[Attempt]) -> tuple[Verdict, frozenset]:
    """The verdict and the node ids that make the red the branch's (empty unless ``caused``)."""

    if head.rc == 0:
        return Verdict.LOAD, frozenset()
    if base is None or base.rc == 0:
        return Verdict.CAUSED, head.failing
    new = head.failing - base.failing
    return (Verdict.CAUSED, new) if new else (Verdict.PRE_EXISTING, frozenset())


def add_arguments(parser) -> None:
    parser.add_argument(
        "--confirm-red", metavar="FILE", default=None,
        help="run FILE alone on HEAD and on the base, print caused / pre-existing / load, run nothing else",
    )
    parser.add_argument("--confirm-base", default=DEFAULT_BASE, metavar="REF", help=f"the base (default {DEFAULT_BASE})")


def _git_strict(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run_alone(file: Path, cwd: Path, timeout: float) -> tuple[int, str]:
    """One file, one fresh process — the per-file runner's hermetic attempt, no retry."""

    import run_tests_parallel as rtp  # registered by run_tests_bundled._load_sibling

    _f, rc, output, _summary, _wall = rtp._run_one_file_once(file, list(PYTEST_ARGS), cwd, timeout)
    return rc, output


def _state(attempt: Attempt) -> str:
    if attempt.rc == 0:
        return "green"
    if not attempt.failing:
        return "red, no failing node id (a timeout or a crash)"
    return f"red, {len(attempt.failing)} failing node(s)"


def worktree_home(primary: Path) -> Path:
    """Where the base worktree is cut: ``worktrees/`` beside the clone (CLAUDE.md § Git discipline)."""

    home = primary.parent / "worktrees"
    home.mkdir(exist_ok=True)
    return home


def confirm(
    rel: str, repo_root: Path, primary: Path, *, base: str = DEFAULT_BASE, timeout: float = 300.0,
    runner: Runner = run_alone, out=print,
) -> Verdict:
    repo_root, primary = Path(repo_root), Path(primary)
    head_rc, head_out = runner(repo_root / rel, repo_root, timeout)
    head = Attempt("HEAD", head_rc, failing_ids(head_out))
    out(f"confirm-red {rel}: HEAD {_state(head)} alone")
    attempt = None
    if head_rc != 0:
        sha = _git_strict(repo_root, "rev-parse", "--verify", f"{base}^{{commit}}")
        tree = Path(tempfile.mkdtemp(prefix=f"confirm-red-{sha[:10]}-", dir=worktree_home(primary)))
        tree.rmdir()
        _git_strict(primary.parent, "-C", str(primary), "worktree", "add", "--detach", str(tree), sha)  # a neutral cwd
        try:
            if (tree / rel).is_file():
                rc, text = runner(tree / rel, tree, timeout)
                attempt = Attempt(f"{base} {sha[:10]}", rc, failing_ids(text))
                out(f"  {attempt.where}: {_state(attempt)} alone")
            else:
                out(f"  {base} {sha[:10]}: the file does not exist there")
        finally:
            try:
                _git_strict(primary.parent, "-C", str(primary), "worktree", "remove", "--force", str(tree))
            except RuntimeError as exc:  # a process the test leaked still holds it: the verdict stands
                out(f"  note: {tree} not removed ({exc}); remove it and run `git worktree prune` once its holder exits")
    verdict, new = judge(head, attempt)
    out(f"  verdict: {verdict.value}")
    for nodeid in sorted(new):
        out(f"    caused: {nodeid}")
    if verdict is Verdict.PRE_EXISTING:
        for nodeid in sorted(head.failing):
            out(f"    red on both: {nodeid}")
    return verdict


def main(args, repo_root: Path, primary: Path, rel_of: Callable[[Path], str]) -> int:
    target = Path(args.confirm_red)
    path = target if target.is_absolute() else Path.cwd() / target
    if not path.is_file():
        path = repo_root / args.confirm_red
    if not path.is_file():
        print(f"error: --confirm-red {args.confirm_red}: no such file", file=sys.stderr)
        return 2
    try:
        verdict = confirm(rel_of(path), repo_root, primary, base=args.confirm_base, timeout=args.file_timeout)
    except RuntimeError as exc:
        print(f"error: --confirm-red: {exc}", file=sys.stderr)
        return 2
    return 1 if verdict is Verdict.CAUSED else 0
