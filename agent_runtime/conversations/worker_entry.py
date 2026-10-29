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


def stop_compute_host() -> None:
    """Stop this worker's compute-host child before the worker goes (RT-NATIVE-PEER-RETIRE-ORPHANS-COMPUTE-HOST).

    With ``dashboard.turn_isolation`` the engine runs turns in one ``tui_gateway.compute_host``
    child, owned by the gateway's lazily-made ``HostSupervisor``. Nothing in the worker's exit
    shut it down, so a retired worker left that child running, re-parented to ``systemd --user``
    on Linux, until it noticed its stdin close ~1.4 s later — ``execution_possible`` false on the
    peer with compute still live. ``HostSupervisor.shutdown`` is the supervisor's own stop (a
    ``shutdown`` frame, then terminate on timeout) and reaps the child, so when this worker has
    exited no compute process of it is left. Reads the singleton without making one: a worker
    that never isolated a turn has no child to stop.
    """
    import sys

    server = sys.modules.get("tui_gateway.server")
    supervisor = getattr(server, "_compute_host_supervisor", None) if server is not None else None
    if supervisor is None:
        return
    try:
        supervisor.shutdown()
    except Exception:  # the worker is exiting either way; the child then exits on its stdin EOF
        pass


def exit_without_finalization(clean: list[bool]) -> None:
    """After every exit handler, end a cleanly stopped worker without interpreter teardown.

    Registered first, so it runs last — which is why it also stops the compute-host child
    (:func:`stop_compute_host`), clean or not: every other handler has finished with it. Tearing down the engine's module graph costs ~0.45 s
    per worker on Windows (measured 0.61-0.66 s -> 0.18-0.23 s from stdin EOF to process
    end) and persists nothing; the one handler registered before it, ``logging.shutdown``,
    runs here. A worker that did not return from its loop exits the ordinary way.
    """
    stop_compute_host()  # after every other exit handler: they may still talk to the child
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

    from agent_runtime.gateway.contract_seam import use_catalog_in_this_process

    use_catalog_in_this_process()  # before any tui_gateway import (RT-WORKER-BOOT-PYDANTIC-CONTRACTS)
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
