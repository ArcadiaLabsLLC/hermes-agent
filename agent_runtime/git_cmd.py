"""One door for running ``git`` as a subprocess (program rule 15's ``git_cmd``).

Every fork module that shells out to git builds the same argv — per-invocation
``-c`` config pairs, an optional ``-C <repo>``, the subcommand — and captures
text. That construction lives here once; what a FAILURE means stays with each
caller (realm sync raises a typed ``RealmSyncError`` with scrubbed stderr, the
build stamp answers a typed reason token), because those are different
contracts over the same process.

``config`` pairs are rendered as ``git -c`` arguments and never written to
``.git/config``; a caller that carries a credential in one scrubs it from any
stderr it surfaces (``realm_sync.git._scrub_config_values``).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__layer__ = "stores"
__all__ = ["run_git"]


def run_git(
    args: Sequence[str],
    *,
    repo: Path | str | None = None,
    config: Sequence[str] | None = None,
    **run_kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """``git [-c PAIR ...] [-C REPO] ARGS...`` with stdout/stderr captured as text.

    ``run_kwargs`` pass through to :func:`subprocess.run` (``cwd``, ``timeout``,
    ``env``, ``stdin``, ``encoding``, ...). Never raises on a non-zero exit —
    the caller reads ``returncode``.
    """

    command = ["git"]
    for pair in config or ():
        command.extend(["-c", str(pair)])
    if repo is not None:
        command.extend(["-C", str(repo)])
    command.extend(args)
    return subprocess.run(command, capture_output=True, text=True, **run_kwargs)
