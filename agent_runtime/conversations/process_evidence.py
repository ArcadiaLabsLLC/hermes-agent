"""PID plus creation time: uncertain receipts do not mistake PID reuse for work."""
from __future__ import annotations

import psutil

__layer__ = "lanes"


def execution_possible(pid: int, created: float) -> bool:
    if pid <= 0 or created <= 0:
        return True
    try:
        process = psutil.Process(pid)
        return process.create_time() == created and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True
