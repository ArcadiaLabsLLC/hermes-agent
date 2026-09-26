"""A run's blocked tools, enforced through upstream's plugin surface instead of core edits.

The runtime blocks tools per run (the persona blocklist, the chat lane's cost cuts,
the registry hygiene set, an MCP admission's denied mutators). Upstream has no
per-agent tool block, so the block reaches upstream's code through three doors:

* **construction** — :func:`prune_agent_tools` drops the names from the constructed
  agent's ``tools`` / ``valid_tool_names`` once, so upstream's tool-conditional prompt
  guidance, memory/skill review nudges and invalid-tool-name handling see the same
  set the model does (``profile_runner.runner._default_agent_factory``);
* **the wire** — the eternia-harness ``llm_request`` middleware drops a blocked
  definition from the provider payload (a tool set refreshed after construction
  cannot bring one back);
* **the call** — the eternia-harness ``pre_tool_call`` hook refuses a blocked name,
  including one unwrapped from the ``tool_call`` bridge, whose deferred catalog is
  not filtered (plugin-fit §4 Q2).

The hooks see a ``session_id``, so the run binds its block to its agent's session id
(:func:`bound_tool_block`). The run's own context carries the same block as the
fallback for a session id the run did not know when it bound — compression rotates
the agent onto a child session mid-turn.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable, Iterator

__layer__ = "policy"

_lock = threading.Lock()
_by_session: dict[str, frozenset[str]] = {}
_RUN_BLOCK: ContextVar[frozenset[str]] = ContextVar("eternia_run_tool_block", default=frozenset())


def _names(names: Iterable[Any] | None) -> frozenset[str]:
    return frozenset(str(name) for name in (names or ()) if name)


@contextmanager
def bound_tool_block(names: Iterable[Any] | None, *, session_ids: Iterable[Any] = ()) -> Iterator[frozenset[str]]:
    """Bind ``names`` as the block for ``session_ids`` and for this context, for the ``with`` body.

    A session's previous binding is restored on exit, so a nested or overlapping run on
    the same session never leaves the other's block behind.
    """

    block = _names(names)
    ids = tuple(dict.fromkeys(str(sid) for sid in session_ids if sid))
    token = _RUN_BLOCK.set(block)
    with _lock:
        previous = {sid: _by_session.get(sid) for sid in ids}
        for sid in ids:
            _by_session[sid] = block
    try:
        yield block
    finally:
        with _lock:
            for sid, before in previous.items():
                if before is None:
                    _by_session.pop(sid, None)
                else:
                    _by_session[sid] = before
        _RUN_BLOCK.reset(token)


def blocked_tools_for(session_id: Any = None) -> frozenset[str]:
    """The block bound for ``session_id``, else the current run's, else nothing."""

    if session_id:
        with _lock:
            found = _by_session.get(str(session_id))
        if found is not None:
            return found
    return _RUN_BLOCK.get()


def _tool_name(entry: Any) -> str:
    """A tool definition's name in the chat, Responses or Anthropic payload shape."""

    if not isinstance(entry, dict):
        return ""
    inner = entry.get("function")
    target = inner if isinstance(inner, dict) else entry
    return str(target.get("name") or "")


def drop_blocked_request_tools(request: Any, *, session_id: Any = None) -> dict[str, Any] | None:
    """The provider kwargs without the session's blocked tool definitions, or None if unchanged."""

    if not isinstance(request, dict) or not isinstance(request.get("tools"), list):
        return None
    block = blocked_tools_for(session_id)
    if not block:
        return None
    tools = [entry for entry in request["tools"] if _tool_name(entry) not in block]
    if len(tools) == len(request["tools"]):
        return None
    return {**request, "tools": tools}


def blocked_call_message(tool_name: Any, *, session_id: Any = None) -> str | None:
    """The refusal for a call to a blocked tool, or None when the call may proceed."""

    name = str(tool_name or "")
    if not name or name not in blocked_tools_for(session_id):
        return None
    return f"Tool '{name}' is not available in this session."


def prune_agent_tools(agent: Any, names: Iterable[Any] | None) -> None:
    """Drop ``names`` from a constructed agent's tool list and valid-name set, once."""

    block = _names(names)
    tools = getattr(agent, "tools", None)
    if not block or not isinstance(tools, list):
        return
    kept = [entry for entry in tools if _tool_name(entry) not in block]
    if len(kept) != len(tools):
        agent.tools = kept
    valid = getattr(agent, "valid_tool_names", None)
    if isinstance(valid, (set, frozenset)):
        agent.valid_tool_names = {name for name in valid if name not in block}
    # Resolved at construction from the unpruned set (agent_init._load_tools).
    if "kanban_show" in block and hasattr(agent, "_kanban_worker_guidance"):
        agent._kanban_worker_guidance = ""


__all__ = [
    "blocked_call_message",
    "blocked_tools_for",
    "bound_tool_block",
    "drop_blocked_request_tools",
    "prune_agent_tools",
]
