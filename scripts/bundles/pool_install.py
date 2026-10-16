"""Install a bundle's locked dependency pool with ``uv pip install --target``.

Fork-owned (bundled desktop). Called by ``scripts/bundle_profile_package.py``
``install_pool``; split out so the packager stays readable.

Two Windows facts shape it (measured 2026-10-15, launcher qa-tooling row "The QA
bundled-harness build has never succeeded"):

* uv installs a wheel's ``<dist>.data/`` tree by creating temporary directories
  beside every file it lands and removing them afterwards. Under one directory
  tree on the owner's box (``%LOCALAPPDATA%\\EterniaLauncher``) that cleanup
  loses a race with a handle nothing in user mode owns, so uv fails removing
  ``pillow_heif-1.6.0.data`` with os error 32 — every time, 9 of 9 runs, with no
  process of ours alive; the same install into the system temp folder passed 4
  of 4. So the pool is installed into a fresh scratch folder OUTSIDE the
  caller's work tree and moved into place whole.
* A genuine transient sharing violation (an AV scan of a freshly written
  ``.pyd``) can still hit any folder, so a uv run that fails on one is retried
  from an empty scratch folder on a bounded backoff; any other failure is not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

#: Waits between attempts; one more attempt than delays, then the failure stands.
RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 15.0)

_SHARING_VIOLATION = re.compile(r"os error 32\b|being used by another process", re.IGNORECASE)


def is_sharing_violation(text: str) -> bool:
    """Whether a uv run's output names a Windows sharing violation (ERROR_SHARING_VIOLATION)."""
    return bool(_SHARING_VIOLATION.search(text))


def _held(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) in (5, 32) or is_sharing_violation(str(exc))


def remove_tree(path: Path, *, delays: Sequence[float] = RETRY_DELAYS,
                sleep: Callable[[float], None] = time.sleep) -> None:
    """``rmtree`` that waits out a held file on a bounded backoff; absent is fine."""
    for delay in (*delays, None):
        try:
            if path.exists():
                shutil.rmtree(path)
            return
        except OSError as exc:
            if delay is None or not _held(exc):
                raise
            print(f"pool: {path} is held ({exc}); retrying in {delay:g}s")
            sleep(delay)


def install_pool(uv_command: Callable[[Path], list[str]], stage: Path, *, cwd: Path,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 scratch_parent: Path | None = None, delays: Sequence[float] = RETRY_DELAYS,
                 sleep: Callable[[float], None] = time.sleep, timeout: float = 1800) -> None:
    """Install into a fresh scratch folder, then move it to ``stage`` (replacing it).

    ``uv_command(target)`` is the full uv argv for one ``--target``. ``scratch_parent``
    is where the scratch folder is made — the system temp folder by default, never
    the caller's work tree.
    """
    for attempt, delay in enumerate((*delays, None), start=1):
        scratch = Path(tempfile.mkdtemp(prefix=f"{stage.name}-", dir=scratch_parent))
        try:
            cmd = uv_command(scratch)
            result = run(cmd, cwd=cwd, timeout=timeout, stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
            sys.stdout.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
            if result.returncode == 0:
                remove_tree(stage, delays=delays, sleep=sleep)
                stage.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(scratch), str(stage))
                return
            output = f"{result.stdout or ''}\n{result.stderr or ''}"
            if delay is None or not is_sharing_violation(output):
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
            print(f"pool: uv hit a Windows sharing violation (attempt {attempt}); "
                  f"retrying from an empty folder in {delay:g}s")
            sleep(delay)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
