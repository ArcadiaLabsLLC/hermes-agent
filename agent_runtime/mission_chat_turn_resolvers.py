"""The impure seams one mission-chat turn's context is assembled through, each bound to its ONE authority.

Moved out of ``mission_chat_turn_context`` (``FH-SIZE-CEILING-TWO-FILES-OVER-800``): that module assembles
the context and is pure given a :class:`MissionChatTurnResolvers`; this one is the only impure surface —
the default of every seam is the same function the turn itself would have called inline, imported on use.
Tests override fields to drive ``build_mission_chat_turn_context`` without a runtime root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .workspace_scope import LaneWorkspace

__layer__ = "lanes"
__all__ = ["DEFAULT_RESOLVERS", "PRELOAD_SURFACE", "MissionChatTurnResolvers"]

#: Surface name the required-skill preload policy keys on.
PRELOAD_SURFACE = "mission_chat"


def _default_consume_queued_skills(*, persona_id: str, session_id: str) -> list[str]:
    from .queued_skills import consume_skills_for_next_turn

    return list(consume_skills_for_next_turn(persona_id=persona_id, session_id=session_id))


def _default_required_preload_skills(
    skills: Sequence[Any], *, root_registries: dict[str, Any] | None = None
) -> list[str]:
    from agent_runtime.skill_resolution import required_preload_skill_ids

    return list(
        required_preload_skill_ids(
            list(skills or []),
            surface=PRELOAD_SURFACE,
            root_node_mode=False,
            _root_registries=root_registries,
        )
    )


def _default_build_preloaded_skills_prompt(
    names: Sequence[str], *, task_id: str, required_skill_names: set[str] | None
) -> tuple[str, list[str], list[str]]:
    from agent.skill_commands import build_preloaded_skills_prompt

    prompt, loaded, missing = build_preloaded_skills_prompt(list(names), task_id=task_id)
    prompt = str(prompt or "")
    loaded = list(loaded or [])
    required = [name for name in loaded if name in (required_skill_names or ())]
    if prompt and required:
        # Upstream's per-skill preload note already marks each skill active for the
        # session; the "required on this surface" emphasis is one fork line on top of
        # it (lane DOORS-A 2026-09-24 — it used to be a parameter threaded into
        # upstream's ``build_preloaded_skills_prompt``).
        quoted = ", ".join(f'"{name}"' for name in required)
        prompt = (f"[IMPORTANT: Runtime policy requires the {quoted} skill"
                  f"{'s' if len(required) > 1 else ''} on this surface. Their instructions "
                  "are active for this turn.]\n\n" + prompt)
    return prompt, loaded, list(missing or [])


def _default_load_workspace_agents(agents_file: Any) -> Any:
    from .prompt_observability import load_workspace_agents_context

    return load_workspace_agents_context(agents_file)


def _default_load_slot_context(instance: Any) -> Any:
    from .persona_slots import load_slot_context

    return load_slot_context(instance)


def _default_load_category_context(instance: Any) -> Any:
    from .persona_slots import load_category_context

    return load_category_context(instance)


def _default_mission_chat_workdir(
    persona: Any, *, workspace_agents_path: str | None, primary_slot_path: str | None,
    chat_folder_path: str | None = None,
) -> Any:
    from .mission_chat_workdir import mission_chat_workdir_for_persona

    return mission_chat_workdir_for_persona(
        persona, workspace_agents_path=workspace_agents_path, primary_slot_path=primary_slot_path,
        chat_folder_path=chat_folder_path,
    )


def _default_capability_block(persona: Any, *, session_id: str | None) -> dict[str, Any]:
    # Through the bundle, which resolves ``capability_block_for_persona``.
    from .chat_lane_bundle import chat_lane_bundle

    return chat_lane_bundle(persona, session_id=session_id).capability()


def _default_settled_tool_surface(session_id: str, *, signature: str) -> dict[str, Any] | None:
    # The tool form's owner: the receipt it settled on the actor this turn reuses.
    from .chat_lane_tool_form import settled_surface_receipt

    return settled_surface_receipt(session_id, signature=signature)


def _default_situational_hud(
    instance: Any, *, turn_budget: dict[str, Any], capability: dict[str, Any]
) -> dict[str, Any]:
    from .runtime_hud import situational_hud_for_instance

    return situational_hud_for_instance(
        instance, turn_budget=turn_budget, capability=capability
    )


def _default_lane_workspace(instance: Any) -> LaneWorkspace:
    from .runtime_hud import lane_workspace_for_instance

    return lane_workspace_for_instance(instance)


def _default_admission_line(persona: Any, *, session_id: str | None) -> str:
    # Through the bundle, which resolves ``mission_chat_admission_line``.
    from .chat_lane_bundle import chat_lane_bundle

    return chat_lane_bundle(persona, session_id=session_id).admission_line


def _default_tool_contract(persona: Any, *, session_id: str | None) -> dict[str, Any]:
    # Through the bundle, which composes the two tool lists from the SAME
    # resolve the request the actor is built from uses, so the reuse key and
    # the request cannot describe different tool surfaces.
    from .chat_lane_bundle import chat_lane_bundle

    return chat_lane_bundle(persona, session_id=session_id).tool_contract()


def _default_permission_state(persona: Any, *, session_id: str | None) -> dict[str, Any]:
    # Through the bundle, which resolves ``permission_state_for_chat``.
    from .chat_lane_bundle import chat_lane_bundle

    return chat_lane_bundle(persona, session_id=session_id).permission_state()


def _default_store_root() -> str:
    from . import paths

    return str(paths.store_root())


def _default_chat_head(instance: Any) -> str:
    """The chat store this instance's conversation writes (chat-head plan §7.2 decision 7)."""

    from .chat_session_scope import resolve_instance_chat_scope

    return str(resolve_instance_chat_scope(instance).db_path)


@dataclass(frozen=True, slots=True)
class MissionChatTurnResolvers:
    """The impure seams the assembly needs, each bound to its ONE authority.

    Every default is the same function the turn itself would have called
    inline — this object relocates the calls, it does not reinterpret them.
    Tests override fields to drive :func:`build_mission_chat_turn_context`
    without a runtime root.
    """

    consume_queued_skills: Callable[..., list[str]] = _default_consume_queued_skills
    #: chat-turn-prep CP-5: takes an optional ``root_registries`` keyword so the
    #: preload policy and the prompt-observability row share ONE registry walk
    #: per physical root per turn. Injected fakes may still take just ``skills``
    #: — the call site passes the keyword only when it is accepted.
    required_preload_skills: Callable[..., list[str]] = (
        _default_required_preload_skills
    )
    build_preloaded_skills_prompt: Callable[..., tuple[str, list[str], list[str]]] = (
        _default_build_preloaded_skills_prompt
    )
    load_workspace_agents: Callable[[Any], Any] = _default_load_workspace_agents
    #: The instance's repo-slot context (build plan §3.3); None = no assignment.
    load_slot_context: Callable[[Any], Any] = _default_load_slot_context
    #: The instance's workspace's listed documents + shared guidance (its categories); None = nothing to offer.
    #: Its own field: it reaches an UNASSIGNED instance too, and never supersedes the alias.
    load_category_context: Callable[[Any], Any] = _default_load_category_context
    #: Where the turn runs (G6 workdir ladder), resolved ONCE here from the three inputs this
    #: builder is the first to hold, and handed down to ``mission_chat_reply`` (D1.12 S1).
    mission_chat_workdir: Callable[..., Any] = _default_mission_chat_workdir
    capability_block: Callable[..., dict[str, Any]] = _default_capability_block
    #: The cost layer's settled receipt for this turn's actor, or None (no settle yet).
    settled_tool_surface: Callable[..., dict[str, Any] | None] = _default_settled_tool_surface
    situational_hud: Callable[..., dict[str, Any]] = _default_situational_hud
    #: The workspace this lane's turn is in. The SAME function the HUD's scope
    #: line is named from, so the record and the agent's picture agree.
    lane_workspace: Callable[[Any], LaneWorkspace] = _default_lane_workspace
    admission_line: Callable[..., str] = _default_admission_line
    tool_contract: Callable[..., dict[str, Any]] = _default_tool_contract
    permission_state: Callable[..., dict[str, Any]] = _default_permission_state
    store_root: Callable[[], str] = _default_store_root
    #: The instance's chat head ``db_path``: a resident actor holds the
    #: ``session_db`` it was built with, so a head that moves must rebuild it.
    chat_head: Callable[[Any], str] = _default_chat_head


DEFAULT_RESOLVERS = MissionChatTurnResolvers()
