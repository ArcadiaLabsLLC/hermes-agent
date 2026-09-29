"""The chat lane's tool scope: which toolsets a chat turn enables, which tool names it
blocks, what the cost policy took out, and the MCP admission line and manuals it is told.

Moved out of :mod:`agent_runtime.chat_lane_bundle` (god-file readability cap; sheet §2.1
``persona_runtime`` row). The bundle composes these once per turn and memoizes the
answer; this module is the resolution itself — one chokepoint for the free-chat and the
operator/mission chat call sites, and the preview (:func:`apply_chat_lane_tool_scope`)
reuses it so the operator sees the same scope the turn ships.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .chat_lane_toolsets import (
    ChatLaneDrop,
    chat_lane_blocked_tools,
    chat_lane_tool_drops,
    chat_lane_toolset_drops,
    scope_chat_lane_toolsets,
)
from .config import chat_lane_restore_toolsets
from .mcp_admission.outcomes import render_mcp_admission_line
from .mcp_admission.resolve import (
    admission_enabled,
    admitted_operating_skill_ids,
    resolve_mcp_admission,
    scope_toolsets_to_admission,
)
from .mcp_admission.vocabulary import LANE_MISSION_CHAT
from .mcp_lane import mission_chat_mcp_lane_line
from .mission_chat_workdir import mission_chat_workdir_for_persona
from .models import AgentPersona
from .persona_profiles import effective_toolsets
from .personas import _blocked_tool_names_with_registry_hygiene, blocked_tool_names
from .tool_permissions import (
    extra_blocked_tools_for_permission_mode,
    permission_mode_is_unbounded,
    permission_options_for_chat,
)

if TYPE_CHECKING:
    from .tool_visibility import ToolVisibilityOptions

__layer__ = "stores"


def _blocked_tool_names_for_chat(persona: AgentPersona, *, session_id: str | None) -> list[str]:
    options = permission_options_for_chat(persona, session_id=session_id)
    if permission_mode_is_unbounded(options.permission_mode):
        return []
    names = set(blocked_tool_names())
    names.update(extra_blocked_tools_for_permission_mode(options.permission_mode))
    # T6a chat-lane cost policy: drop single heavy tools whose whole toolset must
    # stay enabled. ``skill_manage`` (skill authoring) rides here so the ``skills``
    # toolset keeps skill_search / skill_view / skills_list for read-only recall.
    # Shares the per-persona ``chat_lane_restore_toolsets`` knob with the toolset
    # exclusion, so an operator can restore it the same way. This applies only on
    # the bounded lane — the unbounded escape hatch returns [] above, though the
    # T6c registry-hygiene names are still unioned in at agent construction
    # (profile_runner) on every lane: hygiene is registry junk removal, not a
    # permission tier, so unbounded does not resurrect kanban/feishu.
    names.update(chat_lane_blocked_tools(restore=chat_lane_restore_toolsets(persona.id)))
    # clarify is globally blocked (PERSONA_BLOCKED_TOOLS) because autonomous
    # runs have no interactive callback to answer it — but the operator/relay
    # chat lane provides a non-blocking clarify bridge (MissionChatClarifyCapture),
    # so it is allowed here even in bounded permission mode.
    names.discard("clarify")
    return sorted(names)


def _enabled_toolsets_for_chat(
    persona: AgentPersona,
    *,
    session_id: str | None,
    admission=None,
) -> list[str]:
    """The single chat-lane toolset chokepoint (both the free-chat and operator/
    mission chat call sites funnel through here).

    Resolution order: permission mode → role/persona toolset resolution → chat
    capability augmentation → the chat-lane cost policy
    (``scope_chat_lane_toolsets``) that drops browser / vision / heavy-dev from a
    conversational lane → the MCP admission
    scope. ``unbounded`` permission mode bypasses the cost policy, but never the
    global chat-only default. A persona that wants a
    specific cost-excluded toolset back on its *bounded* chat lane restores it via
    ``agent_runtime.personas.<id>.chat_lane_restore_toolsets`` (see
    ``config.chat_lane_restore_toolsets``). Worker/dev task lanes never call this
    — they resolve toolsets via ``effective_toolsets`` directly.

    BOTH branches start from the SAME declaration since S0a A1 (2026-09-03):
    ``effective_toolsets(persona)`` = the bound profile's ``toolsets:`` key, or
    ``harness_core`` when it declares nothing (``persona_profiles.declared_lane_toolsets``).
    ``unbounded`` used to resolve ``all_registered_toolsets()`` — every toolset in
    the process — which is why every persona had the same 79-tool surface with 17
    hygiene-withheld names on every turn. What ``unbounded`` still bypasses is the
    cost policy and the blocklist; what it no longer does is widen the declaration.

    The MCP admission scope is applied LAST, after permission-mode resolution, on
    purpose. It was load-bearing while ``unbounded`` resolved the whole registry
    (which in a warm multi-persona process contains another persona's admitted
    ``mcp-*`` toolsets); on the declared set it is defensive — no ``mcp-*`` name
    reaches it unless the profile named one — and it stays, because "no permission
    mode can widen the admitted MCP set" must be true by construction rather than
    by the shape of today's declarations. The same pure helper
    runs again at agent construction (``profile_runner._enabled_toolsets_for_run``)
    so no lane can bypass it; running it here keeps the operator-facing preview
    honest about the same boundary."""

    options = permission_options_for_chat(persona, session_id=session_id)
    # Idempotent: agent_chat / board / clarify are ``harness_core`` members, so
    # the augmentation is a no-op on the default declaration and still adds them
    # for a profile that declared a narrower list of its own.
    resolved = _augment_chat_capabilities(persona, list(effective_toolsets(persona)))
    if not permission_mode_is_unbounded(options.permission_mode):
        resolved = scope_chat_lane_toolsets(
            resolved, restore=chat_lane_restore_toolsets(persona.id)
        )
    admitted = admission.server_names if admission is not None else ()
    if admission is None and admission_enabled():
        # Only pay the policy resolve when the kill switch is on. With it off the
        # answer is always "nothing admitted" — and the scope below still strips
        # any MCP toolset that reached the resolved set, which is what keeps the
        # isolation property independent of the flag.
        admitted = resolve_mcp_admission(
            persona, lane=LANE_MISSION_CHAT, permission_mode=options.permission_mode
        ).server_names
    return scope_toolsets_to_admission(resolved, admitted_servers=admitted)


def chat_lane_capability_drops(
    persona: AgentPersona,
    *,
    session_id: str | None = None,
    permission_mode: str | None = None,
) -> tuple[ChatLaneDrop, ...]:
    """What the chat-lane cost policy REMOVES for this persona, typed (G5).

    The accounting twin of :func:`_enabled_toolsets_for_chat`: it walks the same
    resolution in the same order — permission mode, role/persona resolution,
    chat capability augmentation — and then asks the same droppers what they
    took out instead of what they left in. Same inputs, same policy, one
    authority; the kept list and the drop list cannot disagree.

    ``unbounded`` returns no drops because that mode genuinely bypasses the cost
    policy (``_enabled_toolsets_for_chat`` ships the declared set unscoped) — a
    row there would report a drop that did not happen. ``permission_mode`` may be
    passed to account for a HYPOTHETICAL mode (the ``persona tool-diff
    --permission-mode`` preview); left ``None`` the stored chat permission for
    ``session_id`` is resolved, exactly as a live turn would.

    Pure accounting: it registers nothing, restores nothing, and is never
    consulted to decide what a turn ships.
    """

    mode = str(permission_mode or "").strip() or permission_options_for_chat(
        persona, session_id=session_id
    ).permission_mode
    if permission_mode_is_unbounded(mode):
        return ()
    restore = chat_lane_restore_toolsets(persona.id)
    resolved = _augment_chat_capabilities(persona, list(effective_toolsets(persona)))
    kept = scope_chat_lane_toolsets(resolved, restore=restore)
    # Local import: the tool→toolset map is the REGISTRY's answer, never a mirror
    # kept here (a silently drifting mirror is the bug class ``mcp_lane`` needed a
    # guard test for), and importing it lazily keeps ``persona_runtime``'s module
    # import free of ``model_tools``.
    from model_tools import get_toolset_for_tool

    return chat_lane_toolset_drops(
        resolved, restore=restore, persona_id=persona.id
    ) + chat_lane_tool_drops(
        restore=restore,
        persona_id=persona.id,
        enabled_toolsets=kept,
        toolset_for_tool=get_toolset_for_tool,
    )


def mission_chat_admission_line(
    persona: AgentPersona, *, session_id: str | None
) -> str:
    """The agent-visible MCP line for this turn's volatile envelope tail.

    ONE slot on the tail, two producers behind it, because the agent must hear
    one voice about MCP:

    * **Admission ON** — design §D3. Resolves the SAME pure policy the turn
      itself resolves (same function, same inputs, so the line and the turn's
      admission can never disagree) and renders the compact denial line.
    * **Admission OFF** — the R0 half (``mcp_lane``). Admission is inert with
      the flag off, so this used to return ``""`` and a declared-but-dark server
      was reported to the OPERATOR (``requirement_failures``) and to NOBODY the
      agent could hear. That blind spot was G5: the agent saw a tool list with
      no ``mcp__<server>__*`` entries and no explanation, and improvised — the
      exact W3 failure the design says is cheaper to prevent by telling the
      truth. It now renders the same honest fact from the same rows the operator
      reads.

    The kill switch still gates ADMISSION, not honesty. The flag-off path pays
    neither a root-config load nor a persona-profile read (see
    ``mcp_lane.mission_chat_mcp_lane_line`` for how that is preserved), and a
    persona that declares no MCP server pays nothing and renders nothing — so
    the envelope stays byte-identical for every turn that had nothing to be told.

    Returns ``""`` when there is nothing to say.
    """

    if not admission_enabled():
        return mission_chat_mcp_lane_line(persona)
    try:
        admission = resolve_mcp_admission(
            persona,
            lane=LANE_MISSION_CHAT,
            permission_mode=permission_options_for_chat(
                persona, session_id=session_id
            ).permission_mode,
        )
    except Exception:  # pragma: no cover - a context line must never fail a turn
        return ""
    return render_mcp_admission_line(admission)


def mission_chat_operating_skills(
    persona: AgentPersona, *, session_id: str | None
) -> list[str]:
    """The operating manual(s) this turn's ADMITTED MCP surface comes with.

    The twin of :func:`mission_chat_admission_line`, and deliberately built from
    the SAME pure policy with the SAME inputs: the line tells the agent which
    declared servers it did NOT get, and this tells the turn which manuals it
    must be handed for the ones it DID. Resolved once here rather than inferred
    from the rendered line, so the two can never describe different admissions.

    Flag-off costs nothing — no root-config load past the kill switch, no
    persona-profile read, no filesystem — because with admission off nothing is
    ever admitted and there is no surface to document. A persona whose admitted
    servers have no registered manual, or who was never granted it, gets ``[]``
    and the turn's preload is byte-identical to what it was before.

    Never raises: an unavailable policy must degrade the turn's context, never
    fail the turn.
    """

    if not admission_enabled():
        return []
    try:
        admission = resolve_mcp_admission(
            persona,
            lane=LANE_MISSION_CHAT,
            permission_mode=permission_options_for_chat(
                persona, session_id=session_id
            ).permission_mode,
        )
    except Exception:  # pragma: no cover - a context input must never fail a turn
        return []
    return admitted_operating_skill_ids(
        admission, granted_skills=getattr(persona, "skills", None) or ()
    )


def apply_chat_lane_tool_scope(
    persona: AgentPersona,
    options: "ToolVisibilityOptions",
    *,
    session_id: str | None,
) -> "ToolVisibilityOptions":
    """Thread the REAL chat-lane resolution onto a tool-visibility PREVIEW (T9b).

    The operator-facing permission preview (``persona_instance_summary`` /
    ``persona_instance_tool_detail``) resolved ``effective_toolsets(persona)`` —
    the persona's raw configured set — so it omitted BOTH the operator-chat
    capability augmentation (agent_chat / board / clarify) and the
    T3/T6a chat-lane cost scoping (browser / vision / file / terminal /
    skill_manage cut). The preview therefore lied about the actual chat lane.

    This mutates ``options`` so the preview reuses the ONE chat-lane authority:
    ``enabled_toolsets`` becomes the chat-lane-scoped toolset list
    (``_enabled_toolsets_for_chat``) and ``chat_lane_blocked_tool_names`` becomes
    the chat lane's authoritative block (``_blocked_tool_names_for_chat`` unioned
    with the fork registry hygiene the runner enforces on every lane, minus the
    ``clarify`` unblock the chat bridge grants). ``resolve_tool_visibility`` then
    emits ``final_model_tools`` byte-identical to the schema the chat lane ships.
    Display-parity only — no policy change, no parallel resolver.

    G5: it also threads the TYPED account of what that scoping removed
    (:func:`chat_lane_capability_drops`) and of this persona's repo grounding
    (``mission_chat_workdir_for_persona``), so one preview reports what SURVIVED
    *and* what was taken away and why. A list of survivors was never an account
    of the removals — which is how "I have no terminal" read as an unexplained
    absence instead of a by-design, restorable cost cut.
    """

    # ONE declaration on both modes (S0a A1): the ``all_registered_toolsets()``
    # arm that used to answer here for ``unbounded`` is what made the preview
    # report 32 configured toolsets / 79 tools for every persona alike.
    configured = _augment_chat_capabilities(persona, list(effective_toolsets(persona)))
    options.configured_toolsets = configured
    options.enabled_toolsets = _enabled_toolsets_for_chat(persona, session_id=session_id)
    options.chat_lane_blocked_tool_names = _blocked_tool_names_with_registry_hygiene(
        _blocked_tool_names_for_chat(persona, session_id=session_id)
    )
    options.chat_lane_capability_drops = chat_lane_capability_drops(
        persona, session_id=session_id
    )
    # Preview scope: the CONFIG rung of the workdir ladder only. A live turn also
    # offers the workspace pointer (``--agents-file``), which is a per-turn fact
    # this persona-level preview has no honest access to.
    options.mission_chat_workdir = mission_chat_workdir_for_persona(persona)
    return options


# Operator-chat first-class capabilities that a chat persona gets regardless of
# what its persisted/config toolset list happens to enumerate. This is capability
# *discovery* — it does not widen any downstream gate.
#
# `agent_chat`, `board` and `clarify` are UNCONDITIONAL on purpose (mission-lane
# removal, S1). This is the ONLY path that puts `board` and `agent_chat` on a chat lane, and
# it used to gate them on a hardcoded role map. Such a gate silently strips the Mission Board
# and agent-to-agent chat from every chat persona the moment either happens. Both
# are explicit KEEP. The gate had no protective value either: all four roles in the
# dict already allow `board` and `agent_chat`, so removing it changes nothing for a
# known role and *restores* the intended surface for an unknown one.
#
# `clarify` is likewise universal: ask a question, get the answer as the next
# message in the same session.
_CHAT_CAPABILITY_TOOLSETS = ("agent_chat", "board", "clarify")


def _augment_chat_capabilities(persona: AgentPersona, toolsets: list[str]) -> list[str]:
    from .launcher_app_functions import APP_FUNCTIONS_TOOLSET, app_function_tools_registered

    augmented = list(toolsets)
    capabilities = list(_CHAT_CAPABILITY_TOOLSETS)
    # The Launcher's app functions (Stage 7) are a chat capability once a
    # Launcher has listed them; the Launcher's dispatcher is their policy, and
    # each tool is offered only to a turn bound to a Launcher link.
    if app_function_tools_registered():
        capabilities.append(APP_FUNCTIONS_TOOLSET)
    for toolset in capabilities:
        if toolset in augmented:
            continue
        augmented.append(toolset)
    return augmented


__all__ = [
    "apply_chat_lane_tool_scope",
    "chat_lane_capability_drops",
    "mission_chat_admission_line",
    "mission_chat_operating_skills",
]
