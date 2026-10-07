"""Per-process gateway lock directory cleanup, extracted from conftest."""
import os
import shutil
from pathlib import Path

LOCK_DIR_PREFIX = "hermes-test-gateway-locks-"


def sweep_stale_lock_dirs(root: Path, prefix: str = LOCK_DIR_PREFIX) -> None:
    for _stale in root.glob(f"{prefix}*"):
        try:
            _stale_pid = int(_stale.name[len(prefix):])
        except ValueError:
            continue
        if os.name == "nt":
            # This sweep runs before fixtures can intercept console signals.
            from gateway.status import _pid_exists
            if not _pid_exists(_stale_pid):
                shutil.rmtree(_stale, ignore_errors=True)
            continue
        try:
            os.kill(_stale_pid, 0)  # windows-footgun: ok — Windows continues above
        except OSError:
            shutil.rmtree(_stale, ignore_errors=True)
