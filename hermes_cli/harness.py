"""``hermes harness``: the plugin's parser door, and nothing else.

The ``eternia-harness`` plugin (``plugins/eternia-harness/__init__.py``) calls
:func:`build_cli_parser`, which builds the whole tree
(``hermes_cli.harness_parts.parser``) and wraps every handler with
:func:`_harness_entry` (the core-cache fingerprint capture, and the harness
error envelope for an exception escaping a handler).

Where things live — import the module that owns a name, and patch a name in
the module that LOOKS IT UP (W0-G4, ``tests/tooling/test_harness_namespace_is_thin.py``):

* the parser tree, ``build_parser`` and the ``func=`` root — ``harness_parts/parser/``;
* the verb families — one module (or package) per family under ``harness_parts/``
  (``roots_commands``, ``gateway_identity_commands``, ``skills_commands``,
  ``skills_promotion_commands``, ``workspace_commands``, ``realm_commands``,
  ``agent_commands``, ``pets_commands``, ``characters/``, ``provider_visibility``,
  ``usage/``, ``doctor_commands``, ``init_commands``, ``prompt_context_commands``,
  and the H1/H3/H4 parts ``persona/``, ``serve/``, ``runtime_commands`` …);
* the error envelope and the stage42 printing helpers — ``hermes_cli.harness_support``.

This module defines the plugin door and binds no other module's callable except
``build_parser`` (the contract dump and the fixture generator import it from
here) and ``emit_harness_error`` (the entry wrapper's envelope) — W0-G4's
allowlist. The tree is reached through its MODULE (``harness_tree``), so a test
patches ``harness_parts.parser``, where the name is looked up.
"""

from __future__ import annotations

import argparse
import sys

from hermes_cli.harness_parts import parser as harness_tree
from hermes_cli.harness_parts.parser import build_parser
from hermes_cli.harness_support import emit_harness_error

__all__ = ["build_cli_parser", "build_parser", "emit_harness_error"]


# --- The CLI entry: what `hermes harness …` runs through (seam Stage 1) ---------


def _harness_entry(fn):
    """Wrap one harness handler: capture the fingerprint home first, and render an
    exception escaping the handler as the harness error envelope (exit code from
    ``emit_harness_error``). Idempotent."""

    import functools

    if getattr(fn, "__harness_entry__", False):
        return fn

    @functools.wraps(fn)
    def entry(args, *rest, **kwargs):
        # The core cache's fingerprint home, captured BEFORE the command runs
        # (HC-1); the instrument and its reasons live in ``core_cache.home``.
        from agent_runtime.core_cache.home import capture_for_harness_command

        capture_for_harness_command(args)
        try:
            return fn(args, *rest, **kwargs)
        except Exception as exc:
            sys.exit(emit_harness_error(exc, args=args))

    entry.__harness_entry__ = True
    return entry


def _install_harness_entries(parser) -> None:
    """Wrap every ``func=`` default in ``parser``'s tree with :func:`_harness_entry`."""

    stack, seen = [parser], set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue  # aliases share one parser
        seen.add(id(node))
        func = node._defaults.get("func")
        if func is not None:
            node._defaults["func"] = _harness_entry(func)
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())


def build_cli_parser(parser) -> None:
    """The ``harness`` plugin command's parser setup: the tree, every handler behind
    :func:`_harness_entry`. :func:`build_parser` (contract dump, tests) stays unwrapped."""

    harness_tree.populate_parser(parser)
    _install_harness_entries(parser)
