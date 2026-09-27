"""Fork-owned half of ``plugins/memory/__init__.py``'s CLI loader: publish a module the way
real import machinery does (lane FOOTPRINT-DROP 2026-09-27 moved it out of the upstream
file, which keeps one import and one call). Retires with an upstream PR making
``discover_plugin_cli_commands`` bind the child on its parent package.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger("plugins.memory")


def publish_module(full_name: str, module) -> None:
    """Register ``module`` under ``full_name`` the way real import machinery does.

    TWO steps, and this loader only ever did the first.  ``importlib``'s
    ``_handle_fromlist`` / ``_load`` finish an import by ALSO binding the child
    on its parent package object (``setattr(plugins.memory, "honcho", mod)``);
    a hand-rolled ``spec_from_file_location`` + ``sys.modules[name] = mod``
    stops one step short, and the two spellings of the same import then answer
    differently forever:

    * ``import plugins.memory.honcho`` / ``importlib.import_module(...)`` read
      ``sys.modules`` and succeed — including on a LATER call, because
      ``import_module`` short-circuits on the row it finds and never repairs
      the missing attribute;
    * ``from plugins.memory import honcho`` and every attribute walk built on
      it — ``getattr(plugins.memory, "honcho")``, which is what
      ``unittest.mock.patch("plugins.memory.honcho.client…")`` and pytest's
      ``monkeypatch.setattr("<dotted>")`` resolver actually do — raise
      ``AttributeError: 'module' object at plugins.memory has no attribute
      'honcho'``.

    So whether ``memory.<name>`` resolves depends on which spelling ran first,
    which is a PRODUCT shape and not a test shape: a plugin doing ``from
    plugins.memory import <sibling>``, or any caller patching into a provider,
    hits it in production exactly as a test does.  Repairing it at the loader
    is the fix; ``tests/hermes_cli/conftest.py``'s setup-half repair loop is a
    suite-order mitigation for the same defect and is not what makes the
    product correct.

    Idempotent and never destructive: the attribute is set unconditionally to
    the module just registered (that is what an import does — a re-import
    rebinds), and a parent that is absent from ``sys.modules`` is simply not
    written to.
    """

    sys.modules[full_name] = module
    parent_name, _, child = full_name.rpartition(".")
    if not parent_name:
        return
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    try:
        setattr(parent, child, module)
    except Exception:  # noqa: BLE001 — a binding failure must never fail a load
        logger.debug("could not bind %s on %s", child, parent_name, exc_info=True)
