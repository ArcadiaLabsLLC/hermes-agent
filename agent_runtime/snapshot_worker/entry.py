"""``python -m agent_runtime.snapshot_worker.entry``: the resident snapshot worker's main."""
from __future__ import annotations

import hermes_bootstrap  # noqa: F401  Activate the selected installation's dependency owner first.

__layer__ = "wiring"


def own_protocol_pipes():
    """``(requests, replies)``: the protocol's pipes, on private descriptors no grandchild inherits.

    ``os.dup`` is non-inheritable. Fds 0 and 1 -- and so the std handles a build's
    subprocess inherits -- become the null device. On Windows a grandchild handed
    the request pipe stalls at startup behind this process's pending read of it:
    every ``git`` probe of a cold build sat out its 3 s timeout, and a probe with
    no timeout hung the worker's first build until the serve gave up (2026-10-06
    12:04, generation 1, 120 s). Anything a library prints goes where stderr goes
    (DEVNULL), never into a frame.
    """

    import os
    import sys

    requests = os.fdopen(os.dup(sys.stdin.fileno()), "rb")
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, sys.stdin.fileno())
    os.close(null)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.stdout = sys.stderr
    return requests, replies


def main() -> None:
    requests, replies = own_protocol_pipes()
    from agent_runtime.snapshot_worker.child import serve

    serve(requests, replies)


if __name__ == "__main__":
    main()
