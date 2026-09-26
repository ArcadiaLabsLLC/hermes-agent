"""The persona and mission-chat command family of the harness CLI, one verb family per module.

Lane H3 (``docs/agent-runtime-harness/planned/god-file-layout-sheets/persona_commands.md``)
split the 8,201-line ``harness_parts/persona_commands.py`` into this package. This
file is the MAP and binds nothing: import the module that owns a name, and patch a
name in the module that LOOKS IT UP (W0-G4's rule, one module per lookup).

Entry points: the parser (``harness_parts.parser.persona``) wires each ``_cmd_*`` handler
from its module; ``agent_runtime`` callers (dispatch delivery, discussions, the
peer directory, open-chat, the agent-chat tool, actor prewarm) import the one
module they need.

Modules, by layer (lowest first; a module imports only its own layer or lower):

* stores — ``chat_session`` (session rows, chat model override, native history
  tip), ``chat_events`` (event-log publishes and the protocol-v2 chat frame emitter),
  ``chat_request`` (mission-chat request validation and refusal payloads; reads
  the clarify-ticket store), ``chat_target`` (persona resolution and the
  mission-chat target decision).
* policy — ``chat_reply_stamps`` (visibility and media stamps on a reply payload).
* lanes — ``chat_history_writes`` (the ONE write path for a persona chat row;
  a lane because it drives the live-log mirror's write lane),
  ``inspect_commands`` (persona list/show/tool-diff/permission/assignments),
  ``lifecycle_commands`` (agent create/retire, instance create),
  ``instance_commands`` (instance close/retire/steer/return/update-profile),
  ``model_and_skills_commands`` (set-model and set-skills),
  ``chat_open`` / ``chat_delete`` (open, open-new and delete a persona chat),
  ``chat_coordinator`` (coordinator scope and the steer/queue-skill verbs),
  ``chat_tickets_commands`` (clarify tickets, redeliver, turn resolve),
  ``chat_admission`` (the busy/lease/visibility admission half of a turn),
  ``chat_turn_message`` (``_cmd_mission_chat_message``, the turn's front door) and
  ``chat_turn_commit`` (the turn's run-and-commit half).

Stores written: the persona-instance and assignment stores, the persona chat
session DB, the ``mission_chat_turns`` ledger, the event log. Never imported
from here: ``hermes_cli.harness`` (W0-G6).
"""

from __future__ import annotations

__layer__ = "models"
__all__: list[str] = []
