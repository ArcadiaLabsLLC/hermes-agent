from __future__ import annotations

from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .tool_visibility import ToolVisibilityOptions

from . import paths
from .chat_lane_bundle import chat_lane_bundle
from .chat_lane_toolsets import (
    ChatLaneDrop,
    chat_lane_blocked_tools,
    chat_lane_tool_drops,
    chat_lane_toolset_drops,
    scope_chat_lane_toolsets,
)
from .config import chat_lane_restore_toolsets
from .mcp_admission import (
    LANE_MISSION_CHAT,
    admission_enabled,
    admitted_operating_skill_ids,
    render_mcp_admission_line,
    resolve_mcp_admission,
    scope_toolsets_to_admission,
)
from .mcp_lane import mission_chat_mcp_lane_line
from .models import AgentPersona
from .mission_chat_clarify import MissionChatClarifyCapture
from .mission_chat_prompts import (
    MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE,
    _mission_chat_identity_prompt,
    _mission_chat_operative_rules,
    _mission_chat_soul_overlay,
)
from .mission_chat_workdir import mission_chat_workdir_for_persona
from .persona_profiles import effective_toolsets
from .personas import _blocked_tool_names_with_registry_hygiene, blocked_tool_names
from .profile_context import resolve_persona_profile
from .provider_health import assert_provider_health_for_persona
from .terminal_envelope import scope_for_persona as terminal_envelope_scope_for_persona
from .profile_runner import (
    AgentRunRequest,
    AgentRunResult,
    ProfileAgentRunner,
)
from .progress import ChatProgressSink
from .tool_permissions import (
    ChatToolPermissionStore,
    extra_blocked_tools_for_permission_mode,
    permission_mode_is_unbounded,
    permission_options_for_chat,
)

class GPTPersonaRuntime:
    def __init__(
        self,
        *,
        default_provider: str | None = None,
        default_model: str | None = None,
        credential_pool=None,
        session_db=None,
        agent_factory=None,
        agent_runner: ProfileAgentRunner | None = None,
        persist_agent_session: bool = True,
    ):
        self._default_provider = default_provider
        self._default_model = default_model
        runner_session_db = session_db if persist_agent_session else None
        self._runner = agent_runner or ProfileAgentRunner(
            agent_factory=agent_factory,
            credential_pool=credential_pool,
            session_db=runner_session_db,
        )

    def mission_chat_reply(
        self,
        persona: AgentPersona,
        message: str,
        *,
        session_id: str | None = None,
        permission_session_id: str | None = None,
        turn_id: str | None = None,
        persona_instance_id: str | None = None,
        provider_override: str | None = None,
        model_override: str | None = None,
        reasoning_effort: str | None = None,
        surface_prompt: str | None = "",
        max_wall_seconds: float | None = 120.0,
        # No API-call cap on the chat lane — align with base Hermes, where a
        # conversational turn is bounded by the tool-calling loop
        # (AgentRunRequest.max_iterations = 90) plus the wall-clock budget, not a
        # hard call count. Operator chats and agent_chat_send relays share this
        # path; both keep their wall deadline (max_wall_seconds / the shared
        # relay budget), so a runaway turn is caught by time + iterations, not an
        # arbitrary 8 that also throttled ordinary multi-step chat requests.
        max_api_calls: int | None = None,
        max_total_tokens: int | None = None,
        stream_callback: Callable[[str | None], None] | None = None,
        pre_trace_callback: Callable[[dict], None] | None = None,
        trace_callback: Callable[[dict], None] | None = None,
        agent_ready_callback: Callable[[object], Callable[[], None] | None] | None = None,
        preloaded_skill_prompt: str | None = None,
        workspace_agents_content: str | None = None,
        # Absolute path of the operator-selected workspace ``AGENTS.md`` (the
        # ``--agents-file`` receipt). Content and PATH are threaded separately on
        # purpose: the content is prompt material, the path is the workspace
        # POINTER rung of the workdir ladder (G6) — the directory the operator
        # aimed this turn at. Never read for content here.
        workspace_agents_path: str | None = None,
        situational_hud_content: str | None = None,
        conversation_history: list[dict] | None = None,
        reuse_current_user_message: bool = False,
        # Relay sender attribution. An ``agent_chat_send`` relay resolves the
        # SENDING agent once at the CLI chokepoint and hands the typed
        # ``relay_from:<persona>:<instance>`` marker down here; the runner stamps
        # it on the native user row this turn persists so the target's
        # conversation attributes the message to the sender instead of the
        # operator. ``None`` on every operator/CLI send — those rows stay
        # byte-identical.
        relay_sender_marker: str | None = None,
        root_chat_session_id: str | None = None,
        client_message_id: str | None = None,
        runtime_registry=None,
        runtime_signature: str | None = None,
        # Receipt-only companion to ``runtime_signature``: the per-component
        # digest map it was folded from, so a refused reuse can name the
        # component that moved instead of only the composite. Never consulted
        # to decide reuse.
        runtime_signature_components: dict[str, str] | None = None,
        native_revision: str | None = None,
        compression_threshold_tokens_override: int | None = None,
        compression_protect_first_n_override: int | None = None,
        compression_protect_last_n_override: int | None = None,
    ) -> AgentRunResult:
        """Run the canonical Mission Control chat path.

        Unlike the older free-floating helper, this uses the normal Hermes
        profile context stack: SOUL.md, profile memory, skills/context files,
        and the profile's standard chat behavior. Mission Control contributes
        only an optional surface prompt, blank by default.

        ``permission_session_id`` resolves the chat-scoped tool permission
        (e.g. an operator-granted ``unbounded`` mode) independently of the run
        ``session_id``. The Mission Control caller passes ``session_id=None`` so
        the runtime does not re-load the transcript it already baked into the
        message, but the permission record is keyed on the real chat session —
        without this, the unbounded grant is silently ignored and the chat falls
        back to the role-default toolset.
        """

        perm_session_id = permission_session_id or session_id
        binding = resolve_persona_profile(persona)
        if binding.readiness == "missing_profile":
            raise ValueError(binding.summary)
        runtime_provider = provider_override or persona.provider or self._default_provider
        runtime_model = model_override or persona.model or self._default_model or ""
        health_persona = AgentPersona(
            **{
                field: getattr(persona, field)
                for field in getattr(persona, "__dataclass_fields__", {})
            }
        )
        health_persona.provider = runtime_provider
        health_persona.model = runtime_model
        assert_provider_health_for_persona(health_persona)
        # Non-blocking clarify bridge for this lane: a clarify call records the
        # question and ends the turn instead of blocking on a human queue the
        # spawn does not have. Read back after the run and threaded to the
        # caller as a structured clarify_request.
        clarify_capture = MissionChatClarifyCapture()
        # Resolve MCP admission ONCE per turn (pure policy — no spawn, no
        # registration) and thread the same answer through the toolset scope and
        # the runner, so the tools the turn asks for and the servers the runner
        # registers can never disagree. Disabled by default: with the flag off
        # this resolves to "nothing admitted" and the request is byte-identical
        # to what it was before admission existed.
        # ONE permission resolve for this turn, reused by both planes below.
        # Resolving it twice was harmless while only the schema plane read it;
        # since the terminal envelope became mode-aware (2026-08-09) the two
        # planes MUST agree, and the cheapest way to guarantee that is to read
        # the answer once.
        #
        # Since 2026-08-23 that "once" is the WHOLE chat lane's visibility, not
        # just the permission mode: the same bundle the turn-context builder
        # already resolved (permission mode, MCP admission, enabled toolsets,
        # blocked tool names) is read here instead of walking
        # ``permission_options_for_chat`` → ``all_registered_toolsets`` → the
        # registry ``check_fn`` sweep a fourth time for the request (that last
        # leg is gone since 2026-09-02 — the toolset NAMES no longer cost an
        # availability verdict — but the composition is still resolved once). The
        # admission object threaded to the runner below is the SAME object the
        # toolset scope was resolved against, which is the property the old
        # inline resolve existed to guarantee. See
        # :mod:`agent_runtime.chat_lane_bundle`.
        lane_bundle = chat_lane_bundle(persona, session_id=perm_session_id)
        admission = lane_bundle.admission
        # Repo grounding for this turn (G6). Resolved ONCE, here, and handed to
        # the EXISTING ``AgentRunRequest.workdir`` seam the worker lane already
        # uses — ``profile_runner`` chdirs and exports ``TERMINAL_CWD`` under its
        # workdir lock, which is what puts a real repo in front of the terminal /
        # file tools. ``None`` (nothing configured, nothing derivable) keeps the
        # pre-G6 behavior exactly: the turn runs in the process cwd. A configured
        # path that does not exist degrades to that same safe cwd and is reported
        # as a typed row on the preview lane — it never fails the turn.
        workdir = mission_chat_workdir_for_persona(
            persona, workspace_agents_path=workspace_agents_path
        )
        # Lane/role identity for the terminal safety envelope. Bound for the
        # WHOLE run so envelope enforcement on this lane is deterministic and
        # operator-governed instead of keyed on whether the persona happens to
        # bind a Hermes profile (the historical fail-open/fail-closed split —
        # see agent_runtime/terminal_envelope.py). Carrying the runtime root on
        # the scope also means the decision receipt lands even for a persona
        # that never exports HERMES_AGENT_RUNTIME_ROOT.
        #
        # Note how G6 and this slice compose: the workdir above puts a REAL repo
        # in front of the terminal tool, which is exactly what makes the envelope
        # gate load-bearing rather than theoretical — a grounded turn can now
        # actually reach a git remote.
        #
        # The scope also carries this turn's PERMISSION MODE (operator ruling
        # 2026-08-09): an unbounded run is granted the grantable command classes
        # by mode rather than by a per-role config stanza, and every such command
        # still writes a receipt naming the mode. Stamped from the same resolve
        # the schema plane used, so "what tools the turn has" and "what commands
        # it may run" cannot come from two different answers.
        envelope_scope = terminal_envelope_scope_for_persona(
            persona,
            lane=LANE_MISSION_CHAT,
            session_id=perm_session_id,
            runtime_root=paths.store_root(),
            permission_mode=lane_bundle.permission_mode,
        )
        result = self._runner.run(
            AgentRunRequest(
                profile=binding.hermes_profile,
                provider=runtime_provider,
                model=runtime_model,
                api_mode=persona.api_mode,
                reasoning_effort=reasoning_effort,
                terminal_envelope_scope=envelope_scope,
                mcp_admission=admission,
                enabled_toolsets=list(lane_bundle.enabled_toolsets),
                blocked_tool_names=list(lane_bundle.blocked_tool_names),
                quiet_mode=True,
                # Operator chat honors the persona's core-context-file opt-in like
                # the mission-run (L143) and free-chat (L208) paths. Isolated
                # personas (the default) must NOT auto-inject the process-cwd repo
                # project docs (e.g. the 72KB hermes-agent AGENTS.md, truncated to
                # ~65K chars = ~16K tokens) into every conversational turn — that
                # is ~20K tokens of fixed overhead per turn regardless of persona.
                # Repo doctrine an operator persona needs is carried by its skills
                # or read on demand; developer repo docs are not chat-turn context.
                skip_context_files=not bool(getattr(persona, "include_core_context_files", False)),
                # Profile memory (MEMORY.md / USER.md) is identity-adjacent: it
                # carries the bound profile's worldview into the turn. Honor the
                # persona's include_profile_memory opt-in instead of loading it
                # unconditionally, so a persona bound to a supervisor profile for
                # *capabilities* does not also inherit that profile's memory-model
                # (the Alice "goal->Neko->Dev" mental model that made Neko relay
                # to itself). A persona keeps its own profile's memory when the
                # binding is its own; it drops a borrowed profile's memory.
                skip_memory=not bool(getattr(persona, "include_profile_memory", False)),
                platform=PERSONA_CHAT_SCRATCH_SOURCE,
                skill_surface="mission_chat",
                skill_root_node_mode=False,
                session_id=session_id,
                # session_id stays None on this lane (the transcript is already
                # baked into the message), but the ChatGPT-Codex prompt cache is
                # scoped by the session_id / x-client-request-id HTTP headers.
                # Feed the STABLE chat session identity (perm_session_id — the id
                # that names the turn store / observability session) as the
                # header-only cache_scope_id so the warm prefix survives across
                # turns. Header/routing value ONLY — never a transcript-load key
                # (T10c). Worker/mission-run lanes leave this unset.
                cache_scope_id=perm_session_id,
                tool_execution_scope_id=root_chat_session_id or perm_session_id,
                conversation_history=conversation_history,
                reuse_current_user_message=reuse_current_user_message,
                persona_chat_user_finish_reason=relay_sender_marker,
                root_chat_session_id=root_chat_session_id or perm_session_id,
                client_message_id=client_message_id,
                turn_id=turn_id,
                persona_instance_id=persona_instance_id,
                persona_chat_runtime_registry=runtime_registry,
                persona_chat_runtime_signature=runtime_signature,
                persona_chat_runtime_signature_components=runtime_signature_components,
                persona_chat_native_revision=native_revision,
                compression_threshold_tokens_override=compression_threshold_tokens_override,
                compression_protect_first_n_override=compression_protect_first_n_override,
                compression_protect_last_n_override=compression_protect_last_n_override,
                max_wall_seconds=max_wall_seconds,
                max_api_calls=max_api_calls,
                max_total_tokens=max_total_tokens,
                # Byte-stable system prompt (T5 + T9a): the volatile Runtime
                # Situation HUD *and* the queued-skill preload ride the operator's
                # user turn, not the codex ``instructions``, so the cross-turn
                # prompt cache prefix survives every follow-up turn — including a
                # turn on which the operator loads a skill mid-conversation. See
                # ``_mission_chat_user_message`` / ``_mission_chat_surface_message``.
                user_message=_mission_chat_user_message(
                    message,
                    situational_hud_content,
                    preloaded_skill_prompt=preloaded_skill_prompt,
                ),
                system_message=_mission_chat_surface_message(
                    persona,
                    surface_prompt,
                    workspace_agents_content=workspace_agents_content,
                ),
                stream_callback=stream_callback,
                agent_ready_callback=agent_ready_callback,
                clarify_callback=clarify_capture.callback,
                # Key chat trace on the real chat session: Mission Control passes
                # session_id=None (the transcript is already baked into the
                # message) but the permission/session lineage lives on
                # perm_session_id, which is also the persona instance's session.
                progress_callback=_chat_trace_callback(
                    session_id=perm_session_id,
                    persona=persona,
                    turn_id=turn_id,
                    before_first_trace=pre_trace_callback,
                    on_trace=trace_callback,
                ),
                runtime_root=paths.store_root(),
                workdir=Path(workdir.path) if workdir.grounded else None,
            )
        )
        ChatToolPermissionStore().consume_turn(persona_id=persona.id, session_id=perm_session_id)
        if clarify_capture.requested and isinstance(result.raw, dict):
            result.raw["clarify_request"] = clarify_capture.request
        if isinstance(result.raw, dict):
            # Per-turn receipt of where the turn actually ran (and of any
            # configured-but-unusable path it degraded past). The caller records
            # it beside the turn's other receipts; the persona-level preview
            # carries the same typed rows in ``requirement_failures``.
            result.raw["mission_chat_workdir"] = workdir.receipt()
        return result


# Source label for the agent's own scratch turns during an operator chat reply.
# The caller persists the redacted canonical transcript under
# ``agent_runtime_persona_chat``; this scratch lineage uses upstream's hidden
# ``"tool"`` session source (``tools/session_search_tool._HIDDEN_SESSION_SOURCES``)
# so the agent's raw, in-flight copy never becomes recall-reachable while real
# cross-session recall stays on.
PERSONA_CHAT_SCRATCH_SOURCE = "tool"


def _mission_chat_surface_message(
    persona: AgentPersona,
    surface_prompt: str | None,
    *,
    workspace_agents_content: str | None = None,
) -> str:
    """Compose the operator-chat system message (the codex ``instructions``):
    the persona's first-person identity block first, then the non-negotiable
    operative rules, then the operator's optional per-session surface prompt.
    The identity block gives the channel its selected runtime persona, the
    profile's own SOUL overlay supplies durable character and voice, and the
    rules always apply so the anti-fabrication invariant holds even when the
    operator supplies a session surface override.

    BYTE-STABILITY INVARIANT (T5, 2026-07-18): every part of this string must be
    byte-identical across every turn of a conversation, so the codex transport's
    ``prompt_cache_key = sha256(instructions + tools)`` stops rotating and the
    ~13K-token stable prefix (system prompt + tool schema) hits the cross-turn
    prompt cache. The identity/rules are static; the persona SOUL, workspace
    AGENTS.md, and operator surface prompt change only when their source
    actually changes (legitimate content-driven invalidation, like MEMORY.md).
    The Runtime Situation HUD — whose roster/scope/mission state rotated every
    turn — is deliberately NOT here anymore: it rides the operator's user turn
    instead (see ``_mission_chat_user_message``). Do NOT reintroduce per-turn
    volatile text into this builder; it re-bills the whole prefix every turn.
    (T9a, 2026-07-18: the queued-skill preload — the secondary content-driven
    invalidation vector T5 flagged — was likewise moved OUT of this builder onto
    the operator user turn via ``_mission_chat_user_message``. It must NOT come
    back here: loading a skill mid-conversation would otherwise rotate the whole
    stable prefix for that turn.)"""

    identity = _mission_chat_identity_prompt(persona)
    operator_surface = (surface_prompt or "").strip()
    workspace_agents = (workspace_agents_content or "").strip()
    rules = _mission_chat_operative_rules()
    # The persona's OWN SOUL is the profile-owned identity layer between the
    # Mission Control identity hat and the channel rules. Profile personas used
    # to require a duplicated `soul_overlay_path: SOUL.md` binding on the
    # Mission Control persona row; profile-derived/free personas do not carry
    # that field, so a perfectly valid profile SOUL could be observed yet not
    # injected. `_mission_chat_soul_overlay` makes the profile's canonical
    # SOUL.md the default while preserving explicit safe relative overrides.
    soul = _mission_chat_soul_overlay(persona)
    parts = [identity, soul or "", rules]
    if workspace_agents:
        parts.append(MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE + workspace_agents)
    if operator_surface:
        parts.append(operator_surface)
    return "\n\n".join(part for part in parts if part)


def _mission_chat_user_message(
    message: str,
    situational_hud_content: str | None = None,
    *,
    preloaded_skill_prompt: str | None = None,
) -> str:
    """Compose the operator turn's user message: the operator's message (which
    already carries the redaction-safe rolling chat history baked in by
    the native structured conversation history), then the queued-skill preload (when
    the operator loaded a skill this turn), then the per-turn Runtime Situation
    HUD.

    Why the HUD *and* the skill preload ride here and not in the system prompt:
    the codex transport keys its cross-turn prompt cache on
    ``sha256(instructions + tools)``. A HUD whose roster / scope / mission state
    rotates every turn — e.g. ``QA Agent`` vs ``QA Agent (2)`` — would evict the
    ~13K-token stable prefix on every follow-up turn's first call; likewise a
    skill preload layered into ``instructions`` (T5's flagged secondary
    invalidation vector) would rotate the whole prefix on any turn the operator
    loads a skill. Riding both in the operator's user turn keeps the system
    prompt byte-stable for the life of the conversation while still giving the
    model the loaded skill and the same live picture the operator sees.

    Placement is load-bearing: the skill preload and HUD TRAIL the history +
    current operator message rather than leading it, and the HUD stays last. The
    user turn is already per-turn volatile (history grows, the message changes),
    so appending these at its tail keeps the append-only, cache-friendly ordering
    the spec requires — a volatile block ahead of the history would push it
    earlier in the (already uncached) input. This mirrors Hermes's own per-turn
    ephemeral-context injection, which appends recall / plugin context onto the
    current user turn rather than mutating the cached system prompt
    (agent/conversation_loop.py), and the skill-command pattern that injects the
    loaded skill as a user message to preserve caching (agent/skill_commands.py).

    Transport note: on the codex Responses path a mid-conversation ``system``
    message is dropped by the input converter and two consecutive ``user`` items
    violate the role-alternation invariant, so neither the HUD nor the skill
    preload can be a distinct non-user message without either vanishing or
    breaking alternation. Folding them onto the operator user turn is the
    transport-safe realization of "a per-turn message adjacent to the current
    operator message."
    """

    skill_prompt = (preloaded_skill_prompt or "").strip()
    hud = (situational_hud_content or "").strip()
    body = message if isinstance(message, str) else ("" if message is None else str(message))
    parts = [body, skill_prompt, hud]
    return "\n\n".join(part for part in parts if part)


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


def _chat_trace_callback(
    *,
    session_id: str | None,
    persona: AgentPersona,
    turn_id: str | None = None,
    before_first_trace: Callable[[dict], None] | None = None,
    on_trace: Callable[[dict], None] | None = None,
) -> Callable[[dict], None] | None:
    """Build a runner ``progress_callback`` that records a chat turn's tool
    calls as redaction-safe trace events keyed on the chat session.

    ``turn_id`` is the turn's canonical identity (the operator's
    ``client_message_id`` token); it is stamped on every recorded event so the
    snapshot projections carry one reconciliation key for the whole turn.

    Returns ``None`` when there is no session to key on (e.g. a sandbox run with
    no durable chat), which leaves the chat turn's telemetry exactly as it was
    before — no run row is created, nothing is persisted.
    """

    if not session_id and on_trace is None:
        return None
    sink = ChatProgressSink(
        session_id=session_id or "",
        persona_id=getattr(persona, "id", None),
        turn_id=turn_id,
        before_first_trace=before_first_trace,
        on_trace=on_trace,
    )
    return sink.callback()


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
    augmented = list(toolsets)
    for toolset in _CHAT_CAPABILITY_TOOLSETS:
        if toolset in augmented:
            continue
        augmented.append(toolset)
    return augmented
