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
# The site keeps its pre-plugin spelling: receipts and sidecars already carry it.
_FINGERPRINT_HOME_CLI_BOOT_SITE = "hermes_cli.main:harness_command_dispatch"


def _capture_core_cache_fingerprint_home(args) -> None:
    """Capture the core cache's fingerprint home BEFORE the command runs (HC-1).

    THE RULE, and why it is applied here and only here. ``core_cache`` freezes
    the Hermes home its input closure is stat'd under on FIRST USE, and a first
    use that lands inside ``profile_context.persona_profile_context`` pins that
    persona's home for the life of the process — after which any sidecar this
    process writes is keyed under it, and the NEXT boot demotes the pair
    ``reason=home_mismatch``. A one-shot CLI is not exempt from that: ``hermes
    harness chat send`` runs a persona turn through
    ``profile_runner._execute_agent_run``, whose whole body is inside that
    scope, and a tool in that turn reaching the snapshot is a first fingerprint
    taken under the override. The poisoned pair then outlives the process.

    SCOPE, decided on evidence rather than on caution: only ``hermes harness …``
    can reach this lane at all — ``core_cache``/``agent_runtime.snapshot`` are
    imported by ``hermes_cli.harness``, ``harness_support`` and the four
    ``harness_parts`` modules, and by nothing else under ``hermes_cli``. It runs
    from :func:`_harness_entry`, which only the harness tree's handlers carry, so
    no other command pays for it.

    ``hermes harness serve`` passes through here too, and that is deliberate
    rather than redundant: this is the earliest instant in the process the
    command owns, and ``serve_loop`` re-declares its own, more specific site
    under it. Capture-once means the second call is an observation, not a
    second answer.

    Best effort by contract: an instrument must never be why a command fails.
    """

    if getattr(args, "command", None) != "harness":
        return
    try:
        from agent_runtime import core_cache

        core_cache.declare_fingerprint_home_boot_site(_FINGERPRINT_HOME_CLI_BOOT_SITE)
        core_cache.capture_fingerprint_home()
    except Exception:
        pass


def _harness_entry(fn):
    """Wrap one harness handler: capture the fingerprint home first, and render an
    exception escaping the handler as the harness error envelope (exit code from
    ``emit_harness_error``). Idempotent."""

    import functools

    if getattr(fn, "__harness_entry__", False):
        return fn

    @functools.wraps(fn)
    def entry(args, *rest, **kwargs):
        _capture_core_cache_fingerprint_home(args)
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
