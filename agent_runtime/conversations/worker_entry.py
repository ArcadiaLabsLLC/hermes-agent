"""Native gateway composition for the harness-owned conversation worker."""
from __future__ import annotations

import hermes_bootstrap  # Activate the selected installation's dependency owner first.

__layer__ = "wiring"


def own_protocol_input() -> None:
    """Read requests on a private descriptor; grandchildren inherit the null device."""
    import os
    import sys

    descriptor = sys.stdin.fileno()
    private = os.dup(descriptor)
    null = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(null, descriptor)
    finally:
        os.close(null)
    sys.stdin = os.fdopen(private, encoding="utf-8")


def exit_without_finalization(clean: list[bool]) -> None:
    """After every exit handler, end a cleanly stopped worker without interpreter teardown.

    Registered first, so it runs last. Tearing down the engine's module graph costs ~0.45 s
    per worker on Windows (measured 0.61-0.66 s -> 0.18-0.23 s from stdin EOF to process
    end) and persists nothing; the one handler registered before it, ``logging.shutdown``,
    runs here. A worker that did not return from its loop exits the ordinary way.
    """
    if not clean:
        return
    import logging
    import os
    import sys

    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(0)


def main() -> None:
    import atexit

    clean: list[bool] = []
    atexit.register(exit_without_finalization, clean)
    own_protocol_input()
    from agent_runtime.store_epoch import refuse_unreadable_store
    from tui_gateway.server import write_json

    # RT-STORE-EPOCH: the worker opens state.db too. It checks and never stamps: its serve, the same
    # build, stamped this boot, and a raise is the serve's alone (consent travels to the serve).
    refused = refuse_unreadable_store(write_json, write=False)
    if refused is not None:
        raise SystemExit(refused)
    from agent_runtime.host_store.desktop_binding import bind_desktop_host_store_or_exit

    bind_desktop_host_store_or_exit()  # before the engine reads a credential (bundled desktop)
    from agent_runtime.conversations.worker_skills import install
    from tui_gateway.entry import main as serve_native

    install()
    from agent_runtime.conversations.worker_app_functions import install as install_app_functions
    install_app_functions()
    from agent_runtime.conversations.process_evidence import worker_ready_frame

    write_json(worker_ready_frame())
    serve_native()
    clean.append(True)


if __name__ == "__main__":
    main()
