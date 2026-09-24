"""Regression test: `hermes dashboard --tui` must not hard-crash.

Older Hermes desktop app shells (<= 0.15.x) spawn the backend as::

    hermes dashboard --no-open --tui --host 127.0.0.1 --port <PORT>

The ``--tui`` flag was removed from the ``dashboard`` subcommand in cae6b5486
(embedded chat is always on now). When a user's CLI updates past that commit
but their desktop app binary has not, argparse used to reject the unknown flag
with ``error: unrecognized arguments: --tui`` and ``exit(2)`` — the backend
died before it became ready and the desktop GUI showed only "Hermes couldn't
start" with no actionable cause.

The fix adds a hidden, deprecated, accepted-and-ignored ``--tui`` flag to the
dashboard subparser so an old app shell + new CLI degrades gracefully instead
of bricking. These tests pin that contract.

=============================================================================
WHY THIS FILE NO LONGER SPAWNS THE CLI (ML-14 / B20(i))
=============================================================================

It used to run ``python -m hermes_cli.main dashboard --no-open --tui … --status``
in a real subprocess. Two costs, one cause — the claim is about ARGPARSE, and a
process was being paid for it:

* the root conftest's guards do not reach into a child, and ``--status`` is not
  an inert flag: it scans the OS process table for ``hermes dashboard`` /
  ``hermes serve`` cmdlines (its sibling ``--stop`` then SIGTERMs them). So the
  "just parse it" test was walking the operator's live process table on every
  run — ML-7 / R-c's class, one layer out;
* a real ``hermes dashboard`` spawn is exactly what the backend-spawn arm added
  to ``tests/conftest.py``'s live-system guard now refuses, and the honest
  disposition for a test whose claim does NOT need the child is to stop
  spawning one rather than to hold a bypass marker.

What is pinned instead is the SAME parser, built by the SAME factory the CLI
wires in (:func:`build_dashboard_parser`), fed the SAME argv. What is no longer
pinned is that ``python -m hermes_cli.main`` is runnable as a module — a fact
about packaging, not about this flag, and not what this file was ever red for.
"""

import argparse
from pathlib import Path


from hermes_cli.subcommands.dashboard import build_dashboard_parser

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The exact argv an old desktop app shell sends, minus the ``--status`` the
#: subprocess form needed only to make the child exit before starting a server.
OLD_APP_SHELL_ARGV = [
    "dashboard",
    "--no-open",
    "--tui",
    "--host",
    "127.0.0.1",
    "--port",
    "39997",
]


def _cli_parser() -> argparse.ArgumentParser:
    """A parser carrying the real ``dashboard`` subcommand.

    The handlers are stubs because nothing here dispatches — argparse stores
    them on the namespace and this file never calls ``args.func``.
    """
    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    build_dashboard_parser(
        subparsers,
        cmd_dashboard=lambda _args: None,
        cmd_dashboard_register=lambda _args: None,
    )
    return parser


def test_dashboard_tui_flag_is_accepted_not_rejected(capsys):
    """The exact argv an old desktop app sends must parse without argparse error."""
    args = _cli_parser().parse_args(OLD_APP_SHELL_ARGV)

    # The pre-fix failure signature was a usage error on stderr + exit(2); an
    # exit would have raised SystemExit out of parse_args above, so reaching
    # here already means it did not. Assert the message never appeared either,
    # so a future argparse that merely WARNS is caught too.
    assert "unrecognized arguments" not in capsys.readouterr().err
    assert args.command == "dashboard"


