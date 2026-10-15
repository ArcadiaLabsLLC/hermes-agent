"""``hermes postinstall`` subcommand parser.

Extracted verbatim from ``hermes_cli/main.py:main()`` (god-file Phase 2).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable


def build_postinstall_parser(subparsers, *, cmd_postinstall: Callable) -> None:
    """Attach the ``postinstall`` subcommand to ``subparsers``."""
    # =========================================================================
    # postinstall command
    # =========================================================================
    postinstall_parser = subparsers.add_parser(
        "postinstall",
        help="Bootstrap non-Python deps for pip installs (node, browser, ripgrep, ffmpeg)",
        description="One-shot post-install for pip users. Installs system "
        "dependencies that pip cannot provide, then runs setup if needed.",
    )
    add_postinstall_arguments(postinstall_parser)
    postinstall_parser.set_defaults(func=cmd_postinstall)


def add_postinstall_arguments(postinstall_parser) -> None:
    """The ``postinstall`` flags, onto an existing parser (the harness plugin's setup)."""
    postinstall_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Run dependency bootstrap non-interactively.",
    )
    postinstall_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Alias for --yes for scripted installers.",
    )
    postinstall_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable summary (shell provisioning + PATH) as "
        "the final stdout line.",
    )
