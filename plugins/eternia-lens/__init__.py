"""Eternia Lens, registered as a Hermes plugin (plan ``eternia-lens-in-hermes.md``).

The plugin is the packaging switch: a bundle ships Lens by listing this directory.
Lens's method lane (``runtime.lens.*``) registers through the fork-owned
``agent_runtime/serve_rpc/lens.py`` seam, and its poller runs under ``harness
serve`` (stage L1), so ``register`` has nothing to attach to an ordinary session.
"""

from __future__ import annotations

__layer__ = "wiring"


def register(ctx) -> None:
    """Nothing to register on a session: Lens is a serve-side module."""

    return
