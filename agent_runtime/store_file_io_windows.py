"""The Windows half of :func:`agent_runtime.store_file_io.narrow_windows_acl`: the ``icacls`` spawn.

A sibling module so the store helpers carry no process spawn on a platform with no
Windows: the bundled phone profile switches this module off, and ``store_file_io``
imports it only inside ``narrow_windows_acl``, whose production callers all sit behind
``os.name == "nt"``. The rules (the grant, never a raise) are ``store_file_io``'s.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .store_file_io import WINDOWS_STORE_GRANT

__layer__ = "stores"
__all__ = ["narrow_windows_acl"]


def narrow_windows_acl(path: Path) -> str:
    """``icacls`` with inheritance removed and one grant to this user; the outcome, never a raise."""

    user = os.environ.get("USERNAME") or ""
    if not user:
        return "skipped:no_username"
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{user}:{WINDOWS_STORE_GRANT}",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"error:{type(exc).__name__}"
    return "narrowed" if completed.returncode == 0 else f"error:rc{completed.returncode}"
