"""Is THIS process a read-only CLI invocation that must leave its HERMES_HOME untouched?

Fork-owned (RT-SESSIONS-EXPORT-HOME-WRITES). The launcher's owner-chat import runs
``hermes sessions export`` against the owner's home. Before this predicate the boot wrote into
that home whenever it was writable: the scratch prune (``cache/scratch/.last_prune``), the
file log handlers (``logs/agent.log``, ``errors.log``), the boot bootstrap's per-install record
(``installs/<id>/bootstrap/default.json``) and ``ensure_hermes_home``'s skeleton (SOUL.md,
cron/, memories/, sessions/ …). Each of those four writers reads :func:`is_read_only_invocation`
in one ``# fork seam`` guard and skips its write; upstream PR candidate: the same predicate
and the four guards (``docs/agent-runtime-harness/planned/upstream-footprint-ledger.md``).

The answer comes from ``sys.argv`` alone, so it holds from the first import
(``hermes_bootstrap`` runs the scratch export before argparse exists) and is False in any
process that is not that command — a test, the gateway, ``hermes harness serve``. Stdlib-only at
import: ``hermes_constants`` reads it.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

# (subcommand, action) pairs that only read the home. ``sessions export`` is the launcher's
# owner-chat import; its ``--delete-after-verified`` arm deletes sessions and is excluded below.
READ_ONLY_COMMANDS: frozenset[tuple[str, str]] = frozenset({("sessions", "export")})

# Flags that turn a read-only command into a mutation. argparse accepts any unambiguous prefix
# of a long option, so a token is matched as a prefix, not by equality.
_MUTATING_FLAGS: tuple[str, ...] = ("--delete-after-verified",)
_MIN_ABBREVIATION = len("--d")


def _is_mutating_flag(token: str) -> bool:
    name = token.split("=", 1)[0]
    return len(name) >= _MIN_ABBREVIATION and any(flag.startswith(name) for flag in _MUTATING_FLAGS)


def is_read_only_invocation(argv: Sequence[str] | None = None) -> bool:
    """True when *argv* (default ``sys.argv``) is a command in :data:`READ_ONLY_COMMANDS` run
    without a mutating flag. Never raises: an argv it cannot read is not read-only."""
    try:
        args = list(sys.argv if argv is None else argv)[1:]
        from hermes_cli._parser import command_argv  # lazy: keeps this module stdlib-only at import

        command = command_argv(args)
        if tuple(command[:2]) not in READ_ONLY_COMMANDS:
            return False
        return not any(_is_mutating_flag(token) for token in command[2:] if token.startswith("--"))
    except Exception:
        return False
