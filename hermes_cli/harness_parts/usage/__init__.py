"""The ``hermes harness usage`` family: typed per-provider account-limit lanes.

This file is the MAP and binds nothing: import the module that owns a name, and
patch a name in the module that LOOKS IT UP (W0-G4's rule).

Entry point: the parser wires ``commands._cmd_usage``.

Modules, by layer (lowest first; a module imports only its own layer or lower):

* policy — ``providers`` (``USAGE_LANES``: one detect/fetch strategy per
  provider, the lane vocabulary), ``detect`` (active-provider and signed-in
  detection through the table, failure reasons), ``serialize`` (snapshot and
  envelope shapes).
* lanes — ``lanes`` (one lane, and every detected lane failure-isolated),
  ``commands`` (``build_account_usage``, the human render, ``_cmd_usage``).

Stores written: none (reads credentials and the upstream usage fetchers). Never
imported from here: ``hermes_cli.harness`` (W0-G6).
"""

from __future__ import annotations

__layer__ = "models"
__all__: list[str] = []
