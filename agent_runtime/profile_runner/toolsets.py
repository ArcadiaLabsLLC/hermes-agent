"""Which tools and toolsets a run may use: the blocked-tool set (with the
registry-hygiene names) and the enabled toolsets for one request.
"""

from __future__ import annotations

from agent_runtime.personas import REGISTRY_HYGIENE_BLOCKED_TOOLS

from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "policy"

__all__ = [
    "_blocked_tool_names_for_run",
    "_blocked_tool_names_with_registry_hygiene",
    "_enabled_toolsets_for_run",
]


def _blocked_tool_names_with_registry_hygiene(requested: list[str] | None) -> list[str]:
    """Union the fork registry-hygiene block into a request's ``blocked_tool_names``.

    This is the single fork-owned chokepoint that makes the deregistered upstream
    toolsets (``kanban`` + ``feishu_doc`` / ``feishu_drive``) unresolvable on EVERY
    agent-runtime lane — the persona chat/run lanes already carry them via
    ``PERSONA_BLOCKED_TOOLS``, but the worker / root-node lanes construct their
    request with ``blocked_tool_names=[]`` and would otherwise resolve them. Applied
    here (agent construction) so no call site can opt out. Order-preserving; the
    downstream tool-def cache keys on the set, so duplicates/order are harmless."""

    names = list(requested or [])
    seen = set(names)
    for name in sorted(REGISTRY_HYGIENE_BLOCKED_TOOLS):
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _blocked_tool_names_for_run(request: "AgentRunRequest") -> list[str]:
    """Registry hygiene plus this run's admission-scoped MCP tool block."""

    names = _blocked_tool_names_with_registry_hygiene(request.blocked_tool_names)
    admission = request.mcp_admission
    if admission is None:
        return names
    seen = set(names)
    for name in admission.blocked_tool_names:
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _enabled_toolsets_for_run(
    request: "AgentRunRequest", admitted_servers: tuple[str, ...] = ()
) -> list[str] | None:
    """Scope this run's toolsets to the MCP servers it was ADMITTED.

    The second fork-owned chokepoint at agent construction, and the one that
    makes the cross-persona isolation property hold on every lane rather than
    only on the chat lane: MCP registration is process-global, so in a warm
    multi-persona harness process any run whose toolsets were resolved from the
    live registry (``unbounded`` resolves ``all_registered_toolsets()``) would
    otherwise inherit another persona's admitted ``mcp-*`` toolsets. Applied
    here, no call site can opt out.

    With no admission on the request — every lane today except an admitted
    mission-chat turn — this strips any MCP toolset the run did not earn, which
    is a no-op while the harness lane registers nothing at all.
    ``enabled_toolsets=None`` (the "everything" sentinel) is passed through
    untouched: narrowing it would change what a default run resolves.
    """

    from ..mcp_admission.resolve import scope_toolsets_to_admission

    if request.enabled_toolsets is None:
        return None
    return scope_toolsets_to_admission(
        request.enabled_toolsets, admitted_servers=admitted_servers
    )
