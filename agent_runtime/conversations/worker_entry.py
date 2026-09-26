"""Native gateway composition for the harness-owned conversation worker."""
from __future__ import annotations

import hermes_bootstrap  # Activate the selected installation's dependency owner first.

__layer__ = "wiring"


def main() -> None:
    from agent_runtime.conversations.worker_skills import install
    from tui_gateway.entry import main as serve_native

    install()
    serve_native()


if __name__ == "__main__":
    main()
