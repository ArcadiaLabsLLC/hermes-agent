from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import paths
from .chat_lane_bundle import chat_lane_bundle
from .mcp_admission import LANE_MISSION_CHAT
from .models import AgentPersona
from .mission_chat_clarify import MissionChatClarifyCapture
from .mission_chat_prompts import (
    MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE,
    _mission_chat_identity_prompt,
    _mission_chat_operative_rules,
    _mission_chat_soul_overlay,
)
from .mission_chat_workdir import mission_chat_workdir_for_persona
from .profile_context import resolve_persona_profile
from .provider_health import assert_provider_health_for_persona
from .terminal_envelope import scope_for_persona as terminal_envelope_scope_for_persona
from .profile_runner import (
    AgentRunRequest,
    AgentRunResult,
    ProfileAgentRunner,
)
from .progress import ChatProgressSink
from .tool_permissions import ChatToolPermissionStore

__layer__ = "lanes"


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
