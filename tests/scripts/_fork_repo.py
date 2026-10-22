"""A throwaway git repo shaped like the fork: an upstream base commit, then fork edits.

Shared by ``test_fork_lines.py`` and ``test_check_fork_scope.py``. ``up.py`` is upstream
(listed in the manifest); at the base it reads::

    1 import os
    2 A = 1
    3 B = 2
    4 C = 3

and the fork turns it into (line 2 added, ``B`` deleted, ``A``/``C`` renumbered)::

    1 import os
    2 X = 0
    3 A = 1
    4 C = 3

``fork.py`` is absent at the base and outside the manifest: wholly the fork's.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

UP_BASE = "import os\nA = 1\nB = 2\nC = 3\n"
UP_FORK = "import os\nX = 0\nA = 1\nC = 3\n"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    ).stdout.strip()


def make_fork_repo(root: Path, *, up_base: str = UP_BASE, up_fork: str = UP_FORK,
                   fork_files: dict[str, str] | None = None) -> str:
    """Build the repo under ``root``; returns the base sha. The fork edits are committed."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    (root / "up.py").write_text(up_base, encoding="utf-8", newline="\n")
    git(root, "add", "up.py")
    git(root, "commit", "-q", "-m", "upstream base")
    base = git(root, "rev-parse", "HEAD")
    manifest = root / "tests" / "fixtures" / "upstream_manifest.txt"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f"# base {base[:10]}\nup.py\n", encoding="utf-8", newline="\n")
    (root / "up.py").write_text(up_fork, encoding="utf-8", newline="\n")
    for rel, text in (fork_files or {"fork.py": "Y = 1\n"}).items():
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fork edits")
    return base
