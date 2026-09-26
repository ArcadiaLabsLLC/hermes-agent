#!/usr/bin/env python3
"""Agent chat tool — agent-to-agent orchestration over the canonical chat lane.

Lets any chat persona brief, deploy, or steer ANOTHER persona by sending a
message into that persona's own Mission Control chat session ("Alice, deploy
Neko on X" -> Alice calls this tool -> the prompt lands in Neko's session,
Neko replies there, and the whole exchange is visible in Mission Control with
real provenance). This is the CHAT lane: no task, no daemon, no proof gates,
and no tracked-work creation.

Runs fully in-process by invoking the same handler behind
``hermes harness mission-chat message`` (session dedup, transcript persistence,
prompt observability, trace — one canonical lane, nothing re-implemented).
In-process matters: one Hermes process shelling out to another can hit the
``agent.log`` rotation lock, and the operator lane
must never fork a second, slightly different chat pipeline.

Thread contract (V3 — task-scoped dispatch, 2026-07-27): a send that names no
thread opens a FRESH one per dispatched task (``agent_runtime.mission_chat.
dispatch_session_policy``, default ``new_per_dispatch``); continuation is
explicit — pass back the ``session_id`` the reply returned, or ``new_session:
false`` to continue the target's CURRENT default thread (the most recently
established one: every dispatch mint repoints that pointer through
``open_chat``, so it is NOT a stable per-pair thread — naming the ``session_id``
is the only way to continue a SPECIFIC conversation). Every reply carries
``session_established`` {fresh, reason, predecessor_session_id}, and a fresh
thread records its predecessor in the session meta (``_dispatched_from``). The
decision itself belongs to ``agent_runtime.dispatch_session_policy``; this tool
only forwards the caller's tri-state intent uncoerced.

Clarify continuity (2026-07-27): a ``clarify_request`` carries a
``clarify_token``. Echoing it on the reply binds the answer to the thread the
question was asked in — outranking policy AND a stale ``session_id`` — so the
one exchange that MUST stay threaded no longer depends on a model reproducing an
opaque session id. The token resolves in the handler (one ticket-store
authority); this tool forwards it and reports the resulting ``clarify_binding``.

Scope contract (V2 — chained relays enabled 2026-07-08):
- relays may chain (operator -> Alice -> Neko -> Dev). Depth, cycle, and
  budget decisions are owned by ONE authority — ``agent_runtime.relay_policy``
  evaluated by the mission-chat handler at the canonical persona chokepoint
  (after persona-id canonicalization, so instance-id targets cannot dodge the
  cycle guard). This tool only CARRIES the envelope: it reads the current
  chain/deadline from the policy ContextVars (seeded per turn by the handler;
  tool workers inherit them via ``copy_context``) and forwards them as
  explicit ``relay_chain`` / ``relay_deadline_epoch`` request fields, so
  provenance survives process boundaries;
- typed refusals propagate honestly: ``relay_depth_limit``, ``relay_cycle``,
  ``relay_budget_exhausted`` (all carry ``relay_chain``);
- chained hops share ONE wall deadline — a relay does not reset the clock;
- ``HERMES_AGENT_CHAT_SCOPE=off`` disables the tool with a typed refusal;
  a blueprint-graph allow-list (only message agents wired to yours) is the
  planned ``graph`` scope and is not implemented yet — the tool passes the
  caller session id as ``requested_by`` provenance so the graph check has an
  anchor when it lands.
"""

from tools.agent_chat.detached import (
    agent_chat_dispatches,
    _async_delivery_available,
)
from tools.agent_chat.lane import (
    session_belongs_to_chat_lane,
)
from tools.agent_chat.remote import (
    agent_chat_installs,
)
from tools.agent_chat.schemas import (
    AGENT_CHAT_DISPATCHES_SCHEMA,
    AGENT_CHAT_INSTALLS_SCHEMA,
    AGENT_CHAT_LOG_PATH_SCHEMA,
    AGENT_CHAT_OPEN_SCHEMA,
    AGENT_CHAT_SEND_SCHEMA,
    AGENT_CHAT_THREADS_SCHEMA,
    _MESSAGE_LIMIT,
    _REPLY_LIMIT,
)
from tools.agent_chat.send import (
    agent_chat_send,
)
from tools.agent_chat.threads import (
    agent_chat_log_path,
    agent_chat_open,
    agent_chat_threads,
    resolve_chat_lane_target,
)
from tools.registry import registry

__layer__ = "wiring"

#: What this entry re-exports: every name a caller or test spelled on the old
#: module. The handlers live in ``tools/agent_chat/``; this file is the six
#: registrations upstream discovery scans for (``tools/registry.py``).
__all__ = [
    "AGENT_CHAT_DISPATCHES_SCHEMA",
    "AGENT_CHAT_INSTALLS_SCHEMA",
    "AGENT_CHAT_LOG_PATH_SCHEMA",
    "AGENT_CHAT_OPEN_SCHEMA",
    "AGENT_CHAT_SEND_SCHEMA",
    "AGENT_CHAT_THREADS_SCHEMA",
    "_MESSAGE_LIMIT",
    "_REPLY_LIMIT",
    "_async_delivery_available",
    "resolve_chat_lane_target",
    "session_belongs_to_chat_lane",
    "agent_chat_dispatches",
    "agent_chat_installs",
    "agent_chat_log_path",
    "agent_chat_open",
    "agent_chat_send",
    "agent_chat_threads",
]


registry.register(
    name="agent_chat_send",
    toolset="agent_chat",
    schema=AGENT_CHAT_SEND_SCHEMA,
    handler=lambda args, **kw: agent_chat_send(
        persona_id=args.get("persona_id"),
        message=args.get("message"),
        session_id=args.get("session_id"),
        clarify_token=args.get("clarify_token"),
        # No `False` default: an omitted new_session must reach the policy
        # resolver as "unset", not as an explicit request to continue.
        new_session=args.get("new_session"),
        title=args.get("title"),
        # No `240` default here either: an omitted max_seconds must reach the
        # budget resolvers as "unset" so a wait=false dispatch gets the
        # background budget rather than a silently-applied conversational one.
        max_seconds=args.get("max_seconds"),
        # Tri-state like new_session: omitted stays unset (= wait inline).
        wait=args.get("wait"),
        notify_operator=args.get("notify_operator"),
        requested_by_session=kw.get("session_id"),
    ),
    description="Send a chat message to another Harness persona and return their reply, or dispatch it in the background with wait=false (agent-to-agent chat).",
    emoji="🤝",
)

registry.register(
    name="agent_chat_dispatches",
    toolset="agent_chat",
    schema=AGENT_CHAT_DISPATCHES_SCHEMA,
    handler=lambda args, **kw: agent_chat_dispatches(
        limit=args.get("limit", 10),
        state=args.get("state"),
        requested_by_session=kw.get("session_id"),
    ),
    description="List your in-flight and recent background dispatches (read-only).",
    emoji="📡",
)

registry.register(
    name="agent_chat_threads",
    toolset="agent_chat",
    schema=AGENT_CHAT_THREADS_SCHEMA,
    handler=lambda args, **kw: agent_chat_threads(
        persona_id=args.get("persona_id"),
        requested_by_session=kw.get("session_id"),
    ),
    description="List your agent-to-agent chat threads with reachable teammates (read-only, no mint).",
    emoji="🧵",
)

registry.register(
    name="agent_chat_open",
    toolset="agent_chat",
    schema=AGENT_CHAT_OPEN_SCHEMA,
    handler=lambda args, **kw: agent_chat_open(
        persona_id=args.get("persona_id"),
        session_id=args.get("session_id"),
        limit=args.get("limit", 20),
        requested_by_session=kw.get("session_id"),
    ),
    description="Review the recent message tail of your shared thread with a teammate (read-only, no mint).",
    emoji="📖",
)

registry.register(
    name="agent_chat_installs",
    toolset="agent_chat",
    schema=AGENT_CHAT_INSTALLS_SCHEMA,
    handler=lambda args, **kw: agent_chat_installs(
        install=args.get("install"),
        requested_by_session=kw.get("session_id"),
    ),
    description="List the other installs (machines) paired with this one, or one install's agent roster (read-only, no mint).",
    emoji="🖧",
)

registry.register(
    name="agent_chat_log_path",
    toolset="agent_chat",
    schema=AGENT_CHAT_LOG_PATH_SCHEMA,
    handler=lambda args, **kw: agent_chat_log_path(
        persona_id=args.get("persona_id"),
        session_id=args.get("session_id"),
        all_threads=args.get("all_threads"),
        requested_by_session=kw.get("session_id"),
    ),
    description="Get the file path of a teammate thread's live transcript log to grep/tail the full history (read-only, no mint).",
    emoji="🗂️",
)
