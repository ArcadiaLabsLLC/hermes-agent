"""The contract catalog as ``tui_gateway.contracts`` leaves it at import — what the generator renders.

``tui_gateway.contracts.registry``'s four tables are filled at package import (the topic
modules, the recovery seam, ``canonical``) and then GROW: importing ``tui_gateway.server`` runs
the fork lanes' ``declare_contracts()``, which add ``eternia.subagents.*``, the skills /
permission / app-function methods and a second ``SubagentSteerParams``. Those must stay in the
live tables (``test_generated.py::test_catalog_covers_the_whole_wire`` checks the tables against
``server._methods``), but upstream's TypeScript + OpenRPC must not depend on which modules the
rendering process imported first. So the package's ``__init__`` calls :func:`freeze` as its last
statement, and ``scripts/gen_gateway_contracts.py`` renders these copies instead of the live
tables (FH-FORK-CONTRACTS-MUTATE-RENDERED-REGISTRY; owner ruling 2026-10-27).
"""

from __future__ import annotations
__layer__ = "models"

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui_gateway.contracts.registry import EventContract, MethodContract, ServerRequestContract

__all__ = ["CANONICAL_METHODS", "EVENTS", "METHODS", "SERVER_REQUESTS", "freeze"]

METHODS: dict[str, MethodContract] = {}
CANONICAL_METHODS: dict[str, MethodContract] = {}
SERVER_REQUESTS: dict[str, ServerRequestContract] = {}
EVENTS: dict[str, EventContract] = {}


def freeze() -> None:
    """Copy the live tables as they stand now — the package's import-time catalog.

    Called once, from the end of ``tui_gateway/contracts/__init__.py``; a later call (a reload)
    re-takes the copy, so the snapshot always equals the catalog the package itself declares."""
    from tui_gateway.contracts import registry

    for mine, live in (
        (METHODS, registry.METHODS),
        (CANONICAL_METHODS, registry.CANONICAL_METHODS),
        (SERVER_REQUESTS, registry.SERVER_REQUESTS),
        (EVENTS, registry.EVENTS),
    ):
        mine.clear()
        mine.update(live)


# Imported here, after ``freeze`` exists: a process whose first import is this module still gets
# the catalog (the package's ``__init__`` calls ``freeze`` on its way out), and one already inside
# the package's ``__init__`` gets the partly built package back and is called from there.
import tui_gateway.contracts
