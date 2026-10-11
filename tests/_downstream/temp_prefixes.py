"""The system-temp sweep: what this repo's runs leave in ``%TEMP%``, removed by name (D3.08).

The runners put the test-temp root under ``HERMES_TEST_TMP_ROOT`` (defaulted
by ``scripts/run_tests.sh``), so a run that finishes leaves nothing in the
system temp dir. What is there anyway came from before that, from a killed
session, or from a run launched outside the runners: upstream's root conftest
mints its session home with ``tempfile.mkdtemp(prefix="hermes-test-home-")``
at import, the per-file runner's scratch root is ``<temp>/hermes-pytest``, the
stream-fixture generator works in ``hermes-stream-fixtures-*``. The census of
the operator's ``%TEMP%`` on 2026-10-10 (518 directories) is design sweep D3.08.

``conftest_plugin``'s once-an-hour prune calls :func:`sweep_system_temp`, which
removes entries carrying one of :data:`HERMES_TEMP_PREFIXES` that are older
than a day and NAMES each one it removed. A launcher prefix is never on the
list: another repository's artefacts are not this sweep's to delete.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Iterable, Mapping

#: Name prefixes this repository's tests and runners mint in the system temp dir.
HERMES_TEMP_PREFIXES: tuple[str, ...] = (
    "hermes-test-home-",
    "hermes-pytest",
    "hermes-stream-fixtures-",
)

#: An entry younger than this may belong to a run still in flight.
SWEEP_KEEP_SECONDS = 24 * 3600


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:  # different drives
        return False


def system_temp_dirs(environ: Mapping[str, str], redirect_root: str) -> list[str]:
    """The system temp dirs a run may have littered, never inside ``redirect_root``.

    The runner exports the redirect root as TEMP/TMP, so the process's own temp
    variables usually name it; the Windows per-user default
    (``%LOCALAPPDATA%\\Temp``) and the POSIX ``/tmp`` are the system dirs then.
    """

    candidates = [environ.get(key, "") for key in ("TEMP", "TMP", "TMPDIR")]
    if sys.platform == "win32":
        local = environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(os.path.join(local, "Temp"))
    else:
        candidates.append("/tmp")
    seen: list[str] = []
    for candidate in candidates:
        if not candidate or not os.path.isdir(candidate) or _inside(candidate, redirect_root):
            continue
        real = os.path.realpath(candidate)
        if real not in seen:
            seen.append(real)
    return seen


def sweep_system_temp(
    dirs: Iterable[str],
    *,
    now: float,
    rmtree: Callable[[str], None],
    keep_seconds: float = SWEEP_KEEP_SECONDS,
    prefixes: Iterable[str] = HERMES_TEMP_PREFIXES,
) -> list[str]:
    """Remove each known-prefix entry older than ``keep_seconds``; return the paths removed."""

    prefixes = tuple(prefixes)
    cutoff = now - keep_seconds
    removed: list[str] = []
    for directory in dirs:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if not entry.name.startswith(prefixes):
                continue
            try:
                if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    rmtree(entry.path)
                else:
                    os.unlink(entry.path)
            except OSError:
                continue
            if not os.path.lexists(entry.path):
                removed.append(entry.path)
    return removed
