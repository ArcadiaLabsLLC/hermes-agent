"""Name the agent and turn on every commit a persona turn makes (RT-AGENT-COMMIT-ATTRIBUTION).

A commit an agent made carried the machine's git identity and a model trailer, nothing naming the
persona instance or turn, so Neko's launcher commit ``bbd4fe12ae`` read as the owner's own. The
eternia-harness plugin's ``tool_request`` middleware runs :func:`attribute_commits` on every tool
call: a ``terminal`` command that runs ``git … commit`` during a persona turn gains two trailers,

    Agent-Instance: <persona instance id>
    Agent-Turn: <turn id>

through git's own ``--trailer`` option, inserted right after the ``commit`` verb, so ``git log``
alone answers which agent and which turn wrote a change. The values are id tokens, so the option
is written ``--trailer=Key:value`` with no quoting and survives any shell the command runs under.

Unbound (not a persona turn, or a turn with no id) changes nothing; a command that already names
an ``Agent-Turn`` trailer is left alone. Like ``turn_outcome.classify_command`` this reads the
command text, so a ``git commit`` spelled inside a quoted string is also rewritten — harmless,
because the option only lands where git parses it.
"""

from __future__ import annotations

import re
from typing import Any

__layer__ = "policy"
__all__ = ["INSTANCE_TRAILER", "TURN_TRAILER", "attribute_commits", "with_commit_trailers"]

INSTANCE_TRAILER = "Agent-Instance"
TURN_TRAILER = "Agent-Turn"

# ``git``, its global options (``-C <dir>``, ``-c k=v``, ``--no-pager``), then the ``commit`` verb
# itself — ``commit-tree`` and ``commit-graph`` are other verbs, so a separator must follow.
_COMMIT_VERB = re.compile(
    r"\bgit(?:\.exe)?(?:\s+-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+)|\s+--?[\w-]+(?:=\S+)?)*\s+commit(?=$|[\s;&|)])"
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")


def with_commit_trailers(command: str, *, persona_instance_id: str, turn_id: str) -> str:
    """``command`` with the two trailers after each ``git commit`` verb (unchanged when none)."""

    if not (_ID.fullmatch(persona_instance_id or "") and _ID.fullmatch(turn_id or "")):
        return command
    if f"{TURN_TRAILER}:" in command:
        return command
    option = f" --trailer={INSTANCE_TRAILER}:{persona_instance_id} --trailer={TURN_TRAILER}:{turn_id}"
    return _COMMIT_VERB.sub(lambda match: match.group(0) + option, command)


def attribute_commits(tool_name: str, args: Any, agent: Any) -> dict | None:
    """The ``terminal`` args with the trailers added, or None when nothing changes."""

    if tool_name != "terminal" or not isinstance(args, dict) or agent is None:
        return None
    command = args.get("command")
    if not isinstance(command, str) or "commit" not in command:
        return None
    from agent_runtime.live_turns import persona_instance_of

    turn_id = str(getattr(agent, "_persona_chat_turn_id", None) or "")
    instance = persona_instance_of(agent) or ""
    rewritten = with_commit_trailers(command, persona_instance_id=instance, turn_id=turn_id)
    return None if rewritten == command else {**args, "command": rewritten}
