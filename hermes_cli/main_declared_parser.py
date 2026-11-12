"""The parser for an argv that names a manifest-declared plugin command — built without the other commands.

``hermes harness serve`` is spawned on every Mission Control start, and ``main()`` built every one of
upstream's ~75 subcommand parsers before parsing it: 2.2 s of a 3.4 s ``hermes harness serve --help`` on the
Linux dev box (load 24, 2026-11-12), 3.4–4.5 s per serve boot in the 2026-11-10 measurement
(``RT-HARNESS-SERVE-SKIP-UPSTREAM-PARSERS``). :func:`declared_command_parser` answers the same
``(parser, subparsers)`` pair ``main._build_cli_parser`` does, holding the top-level flags, ``chat`` (the
top-level parser's own) and ONLY the declared command argv names. ``main()`` asks it first and builds the
whole tree when it answers None, so everything after the build — container routing, the parse, startup
discovery, dispatch — is upstream's code, unchanged. It is the shape of upstream's own
``_try_fast_serve_launch``, one step earlier and for plugin commands.

It answers None — the whole tree is built, as before — when: ``HERMES_DISABLE_FAST_DECLARED_LAUNCH=1``; argv
has no command, or its first positional is a built-in (a declared sub-verb of a built-in, ``hermes auth
<verb>``, needs that built-in's parser); no enabled plugin's manifest declares the command top-level
(``HERMES_SAFE_MODE`` declares none); or the plugin fails to attach. What the full path does for a declared
command is unchanged here: the same manifest scan and the same attach, and no plugin discovery.

Pinned by ``tests/hermes_cli/test_main_declared_parser.py``.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Collection

logger = logging.getLogger(__name__)

DISABLE_ENV = "HERMES_DISABLE_FAST_DECLARED_LAUNCH"


def declared_command_parser(builtins: Collection[str]):
    """``(parser, subparsers)`` for an argv whose first positional is a top-level manifest-declared plugin
    command, with only that command attached; None for any other argv (the caller builds the whole tree).
    ``builtins`` is main's ``_BUILTIN_SUBCOMMANDS``, passed in so this module never imports the CLI facade."""
    if os.environ.get(DISABLE_ENV) == "1":
        return None
    from hermes_cli._parser import build_top_level_parser, command_argv

    args = command_argv(sys.argv[1:])
    if not args or args[0] in builtins:
        return None
    try:
        from hermes_cli.plugins import discover_declared_cli_commands

        commands = discover_declared_cli_commands()
    except Exception:  # a broken manifest must never take the CLI down; the whole tree still builds
        logger.warning("Declared plugin CLI scan failed", exc_info=True)
        return None
    declared = next((c for c in commands if c["name"] == args[0] and not c.get("parent")), None)
    if declared is None:
        return None
    from hermes_cli.main_plugin_cli import attach_plugin_cli_command

    parser, subparsers, _chat_parser = build_top_level_parser()
    try:
        attach_plugin_cli_command(subparsers, declared, builtins)
    except Exception:  # a plugin's setup_fn is third-party code; the whole tree and full discovery still run
        logger.warning("Plugin CLI command %r failed to attach", args[0], exc_info=True)
        return None
    return parser, subparsers
