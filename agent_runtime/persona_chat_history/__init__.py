"""The persona-chat history package: the roster of a persona's chats, one chat's transcript, the trace tail.

Owner doc: ``docs/agent-runtime-harness/05-chat-turn-lane.md``. This file re-exports
the names production importers take (``snapshot``, ``status``,
``operator_channels``, ``chat_live_log``, ``peer_directory``, the harness CLI,
``tools/agent_chat_tool``); import anything else from the module that owns it,
and patch a name in the module that LOOKS IT UP.

Entry points (lanes): ``summary`` (``persona_chat_history_summary``),
``messages`` (``persona_chat_session_messages``).

Modules, by layer (lowest first; a module imports only its own layer or lower):

* models — ``vocabulary`` (message kinds, terminal and silent markers, read
  statuses, limits).
* policy — ``text`` (one message's text), ``trace_rows`` (one trace event's
  row).
* stores — ``markers`` (terminal and silent turn markers, transcript order;
  read from the turn journal), ``curation`` (the transcript policy, its
  revision and cursor; reads the turn journal), ``history_rows`` (SessionDB session rows), ``trace`` (the event-log
  trace tail).
* lanes — ``summary``, ``messages``.

Stores written: none (reads SessionDB, the turn journal and the event log).
Never imported from here: ``hermes_cli.harness``, and no module here imports a
layer above its own (W0-G6).
"""

from __future__ import annotations

#: Single-homed in ``agent_runtime.persona_chat_continuity`` — this module used
#: to carry its own ``= "agent_runtime_persona_chat"`` literal, which was drift
#: waiting for a one-sided edit to a wire token. The import is also the
#: re-export: the package's own projections and four test import sites
#: (``test_agent_chat_tool.py``, ``test_persona_chat_continuity.py`` ×3) read the
#: name off ``persona_chat_history``, and they keep resolving. Neither module
#: imports the other transitively at module scope, so there is no cycle to
#: dodge here.
from ..persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from .history_rows import _canonical_persona_id, _default_session_db
from .messages import persona_chat_session_messages
from .summary import persona_chat_history_summary
from .trace import persona_chat_trace_summary
from .vocabulary import (
    DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    MAX_PERSONA_CHAT_MESSAGE_TAIL,
    PERSONA_HARNESS_DELIVERY_KIND,
    PERSONA_PRE_TRACE_ACK_KIND,
    PERSONA_RELAYED_MESSAGE_KIND,
    PERSONA_TURN_BUDGET_EXHAUSTED_KIND,
    PERSONA_TURN_INTERRUPTED_KIND,
    _SECRET_RE,
    canonical_persona_chat_turn_id,
    logical_persona_chat_client_message_id,
)

__layer__ = "lanes"
__all__ = [
    "DEFAULT_PERSONA_CHAT_MESSAGE_TAIL",
    "MAX_PERSONA_CHAT_MESSAGE_TAIL",
    "PERSONA_CHAT_SESSION_SOURCE",
    "PERSONA_HARNESS_DELIVERY_KIND",
    "PERSONA_PRE_TRACE_ACK_KIND",
    "PERSONA_RELAYED_MESSAGE_KIND",
    "PERSONA_TURN_BUDGET_EXHAUSTED_KIND",
    "PERSONA_TURN_INTERRUPTED_KIND",
    "_SECRET_RE",
    "_canonical_persona_id",
    "_default_session_db",
    "canonical_persona_chat_turn_id",
    "logical_persona_chat_client_message_id",
    "persona_chat_history_summary",
    "persona_chat_session_messages",
    "persona_chat_trace_summary",
]
