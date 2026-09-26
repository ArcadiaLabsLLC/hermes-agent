"""The ``hermes harness`` argparse tree: ``PARSER_FAMILIES``, and the door onto it.

This file is the MAP of the tree. Entry points: ``hermes_cli.harness.build_cli_parser``
(the plugin door) calls :func:`populate_parser`; :func:`build_parser` starts from a
subparsers action (the contract dump, the fixture generator, the serve argv lane,
the tests).

Modules (all wiring; each holds one ``add_<family>(subs)`` per family and imports
the handlers it binds as ``func=``):

* ``machine`` — init, roots, gateway, status/providers/usage/doctor/health/verify,
  config, migrate, observe, contracts, worktree, install-harness-skills, snapshot,
  stream, serve (with its two lazy ``_cmd_serve*`` trampolines), work;
* ``scope`` — workspace, realm;
* ``surfaces`` — flow, checkpoint, skills, prompt-context, board, office, level, map;
* ``persona`` — persona, mission-chat, persona-instance, agent;
* ``characters`` — pets, characters;
* ``common_args`` — the stage42 globals and the coordinator permission flags.

Routing is data (program rule 12): the ORDER of ``PARSER_FAMILIES`` is the order
``hermes harness --help`` lists the families and the order
``tests/fixtures/hermes_cli_contract.json`` records them. Never imported from
here: ``hermes_cli.harness`` (W0-G6).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from .characters import add_characters, add_pets
from .common_args import _add_stage42_global_args
from .machine import (
    add_config,
    add_contracts,
    add_doctor,
    add_gateway,
    add_health,
    add_init,
    add_install_harness_skills,
    add_migrate,
    add_observe,
    add_providers,
    add_roots,
    add_serve,
    add_snapshot,
    add_status,
    add_stream,
    add_usage,
    add_verify,
    add_work,
    add_worktree,
)
from .persona import add_agent, add_mission_chat, add_persona, add_persona_instance
from .scope import add_realm, add_workspace
from .execution_identity import add_execution_identity
from .surfaces import (
    add_board,
    add_checkpoint,
    add_flow,
    add_level,
    add_map,
    add_office,
    add_prompt_context,
    add_skills,
)

__layer__ = "wiring"
__all__ = ["PARSER_FAMILIES", "build_parser", "harness_command", "populate_parser"]

#: Every ``hermes harness`` family, in the order the tree lists them.
PARSER_FAMILIES: Final[tuple[Callable[[object], None], ...]] = (
    add_execution_identity,
    add_init,
    add_roots,
    add_gateway,
    add_workspace,
    add_realm,
    add_flow,
    add_checkpoint,
    add_skills,
    add_prompt_context,
    add_board,
    add_office,
    add_level,
    add_map,
    add_persona,
    add_mission_chat,
    add_status,
    add_providers,
    add_usage,
    add_doctor,
    add_health,
    add_verify,
    add_config,
    add_migrate,
    add_observe,
    add_contracts,
    add_worktree,
    add_persona_instance,
    add_agent,
    add_install_harness_skills,
    add_snapshot,
    add_stream,
    add_serve,
    add_work,
    add_pets,
    add_characters,
)


def build_parser(parent_subparsers) -> None:
    populate_parser(parent_subparsers.add_parser("harness", help="Experimental Agent Runtime Harness"))


def populate_parser(parser) -> None:
    """Build the whole ``hermes harness`` tree onto an existing ``harness`` parser."""
    _add_stage42_global_args(parser)
    subs = parser.add_subparsers(dest="harness_command")
    parser.set_defaults(func=harness_command)
    for add_family in PARSER_FAMILIES:
        add_family(subs)


def harness_command(args) -> int:
    print("Use `hermes harness --help`.")
    return 0
