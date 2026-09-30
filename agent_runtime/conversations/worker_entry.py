"""Native gateway composition for the harness-owned conversation worker."""
from __future__ import annotations

import hermes_bootstrap  # Activate the selected installation's dependency owner first.

__layer__ = "wiring"


def main() -> None:
    from agent_runtime.host_store.desktop_binding import bind_desktop_host_store_or_exit

    bind_desktop_host_store_or_exit()  # before the engine reads a credential (bundled desktop)
    from agent_runtime.conversations.worker_skills import install
    from tui_gateway.entry import main as serve_native

    install()
    from agent_runtime.conversations.worker_app_functions import install as install_app_functions
    install_app_functions()
    serve_native()


if __name__ == "__main__":
    main()
