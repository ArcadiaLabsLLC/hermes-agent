"""Fork-owned tests moved out of ``tests/hermes_cli/test_subcommands_batch.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import argparse
from hermes_cli.subcommands.postinstall import add_postinstall_arguments

from tests.hermes_cli.test_subcommands_batch import (  # upstream names the moved tests use
    _h,
)


# Fork-retained: `hermes postinstall` survives the upstream removal (Windows
# Git-Bash provisioning), so its parser contract stays covered here.
def test_postinstall_parser_accepts_non_interactive_aliases():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    handler = _h("postinstall")
    # The parser the eternia-harness plugin builds: its own subparser, these flags.
    postinstall = sub.add_parser("postinstall")
    add_postinstall_arguments(postinstall)
    postinstall.set_defaults(func=handler)

    yes = parser.parse_args(["postinstall", "--yes"])
    non_interactive = parser.parse_args(["postinstall", "--non-interactive"])

    assert yes.func is handler
    assert yes.yes is True
    assert non_interactive.func is handler
    assert non_interactive.non_interactive is True
