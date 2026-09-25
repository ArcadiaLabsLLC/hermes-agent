"""The agent-chat tool's handlers — imported by ``tools/agent_chat_tool.py``, which
holds the six ``registry.register`` calls and nothing else (upstream discovery
imports a ``tools/`` module only if its AST registers something, and a
subdirectory only if it has an ``__init__.py``; nothing here registers, so
discovery never imports these modules on their own).

Package map (lane B1, sheet ``god-file-layout-sheets/agent_chat_tool.md`` §1).
Layers point down (models <- policy <- stores <- lanes <- wiring); this map is
``lanes`` because it imports the handlers. ``tools/`` is not under W0-G6's
LAYERED_ROOTS, so the constants are for the reader.

    tools/agent_chat_tool.py   wiring   the ENTRY: the contract docstring + the six registrations
    tools/agent_chat/
      __init__.py    lanes    this map; nothing registers here
      schemas.py     models   the six AGENT_CHAT_*_SCHEMA tables and the two limits (a TABLE module)
      lane.py        lanes    the helpers every handler shares: the refusal reply, the scope switch,
                              the persona token, chat-lane membership, the limit clamp
      send.py        lanes    agent_chat_send = Send phases + _REQUEST_REFUSALS; the inline relay goes through
                              agent_runtime.mission_chat_door (ruling Q10), never the CLI namespace
      detached.py    lanes    the wait=false half and agent_chat_dispatches
      threads.py     lanes    agent_chat_threads, agent_chat_open, agent_chat_log_path, the lane target resolver
      remote.py      lanes    the far-install reads and agent_chat_installs

    entry point                                   opens
    agent_chat_send                               send -> detached (wait=false) -> lane
    agent_chat_dispatches                         detached -> lane
    agent_chat_threads / agent_chat_open          threads -> remote (@install/) -> lane
    agent_chat_installs                           remote -> lane
    agent_chat_log_path                           threads -> lane
    peer_directory's target / membership reads    threads, lane
"""

from __future__ import annotations

from . import detached, lane, remote, schemas, send, threads
from .detached import (
    DISPATCH_FILTERS,
    FILTER_DONE,
    FILTER_RUNNING,
    agent_chat_dispatches,
)
from .lane import (
    SCOPE_OFF,
    refusal_json,
    scope_off,
    session_belongs_to_chat_lane,
)
from .remote import (
    agent_chat_installs,
)
from .schemas import (
    AGENT_CHAT_DISPATCHES_SCHEMA,
    AGENT_CHAT_INSTALLS_SCHEMA,
    AGENT_CHAT_LOG_PATH_SCHEMA,
    AGENT_CHAT_OPEN_SCHEMA,
    AGENT_CHAT_SEND_SCHEMA,
    AGENT_CHAT_THREADS_SCHEMA,
)
from .send import (
    Send,
    agent_chat_send,
)
from .threads import (
    agent_chat_log_path,
    agent_chat_open,
    agent_chat_threads,
    resolve_chat_lane_target,
)

__layer__ = "lanes"
