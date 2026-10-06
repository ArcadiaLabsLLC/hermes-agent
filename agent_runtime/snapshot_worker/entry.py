"""``python -m agent_runtime.snapshot_worker.entry``: the resident snapshot worker's main."""
from __future__ import annotations

import hermes_bootstrap  # noqa: F401  Activate the selected installation's dependency owner first.

__layer__ = "wiring"


def main() -> None:
    import os
    import sys

    # The protocol owns the real stdout; anything a library prints goes where
    # stderr goes (DEVNULL), never into a frame.
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    from agent_runtime.snapshot_worker.child import serve

    serve(sys.stdin.buffer, replies)


if __name__ == "__main__":
    main()
