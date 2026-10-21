"""``hermes postinstall`` subcommand flags.

Extracted verbatim from ``hermes_cli/main.py:main()`` (god-file Phase 2). The
eternia-harness plugin registers the subcommand and its handler; this module owns
only the flags.
"""

from __future__ import annotations


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
