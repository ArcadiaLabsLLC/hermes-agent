"""Windows terminal writes for upstream's ``terminal_notify.write_tty`` (fork, L4.04).

Windows has no ``/dev/tty``: the path resolves under the cwd drive's root, so a ``\\dev`` folder
there turned the escape into a FILE. stdout is the terminal on Windows. Retires with draft PR D5
(gate the ``/dev/tty`` attempt on POSIX).
"""

from __future__ import annotations

import sys


def write_tty_windows(seq: str) -> None:
    """Write raw escapes to stdout. Never raises."""
    try:
        sys.stdout.write(seq)
        sys.stdout.flush()
    except Exception:
        pass
