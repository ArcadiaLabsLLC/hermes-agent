"""The ``hermes harness characters`` family: character-sheet drafts, one verb per call.

This file is the MAP and binds nothing: import the module that owns a name, and
patch a name in the module that LOOKS IT UP (W0-G4's rule).

Entry points: the parser (``harness_parts.parser``) wires each ``_cmd_characters_*``
handler from its module; ``hermes_cli.charsheet_payload_contract`` runs the read
verbs against a throwaway library.

Modules, by layer (lowest first; a module imports only its own layer or lower):

* policy — ``payloads`` (the payload, refusal and ``next``-hint shapes every verb
  emits).
* lanes — ``steps`` (the four pipeline steps and their one-call verbs),
  ``commands`` (start, list, status, thumb, sprite, base, reopen, add-state,
  home backfill/migrate, payload-contract), ``auto`` (the one-shot autopilot that
  drives the steps).

Stores written: the charsheet draft library (through ``agent.charsheet.draft``).
Never imported from here: ``hermes_cli.harness`` (W0-G6).
"""

from __future__ import annotations

__layer__ = "models"
__all__: list[str] = []
