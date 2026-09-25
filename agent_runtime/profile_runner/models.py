"""``AgentRunRequest`` and ``AgentRunResult`` — what a run is asked and what it
answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__layer__ = "models"

__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
]


@dataclass(slots=True)
class AgentRunRequest:
    profile: str | None
    provider: str | None = None
    model: str | None = None
    api_mode: str | None = None
    # Optional per-run reasoning-effort override (one of
    # hermes_constants.VALID_REASONING_EFFORTS or "none"). None = inherit the
    # global config default at the transport. Threaded into the agent's
    # reasoning_config so a per-agent-instance choice actually takes effect.
    reasoning_effort: str | None = None
    enabled_toolsets: list[str] | None = None
    disabled_toolsets: list[str] | None = None
    blocked_tool_names: list[str] | None = None
    skills: list[str] | None = None
    session_id: str | None = None
    # Codex cache-scope routing hint (header-only), DISTINCT from ``session_id``.
    # The persona-chat lane passes ``session_id=None`` so the runtime does not
    # re-load a transcript it already baked into the message, but the
    # ChatGPT-Codex backend routes its prompt cache on the ``session_id`` /
    # ``x-client-request-id`` HTTP headers. ``cache_scope_id`` supplies a STABLE
    # per-conversation value for those headers without ever touching transcript
    # or session loading (which stay keyed on ``session_id``). None ⇒ the codex
    # transport falls back to ``session_id`` (worker/mission-run lanes carry a
    # real one, so their behavior is unchanged). See T10c / codex.py header seam.
    cache_scope_id: str | None = None
    # Stable persona-chat root used by terminal/file tool ephemeral state.
    # It is intentionally separate from task_id and native compression tip.
    tool_execution_scope_id: str | None = None
    conversation_history: list[dict[str, Any]] | None = None
    reuse_current_user_message: bool = False
    # Typed presentation marker stamped on the NATIVE user row this turn
    # persists (the row's ``finish_reason`` column; see
    # ``hermes_state._rows_to_conversation`` and ``agent_runtime.relay_policy``).
    # Its only producer today is relay sender attribution: an
    # ``agent_chat_send`` hop resolves WHO is speaking at the CLI chokepoint,
    # and the target's transcript must show the SENDING agent rather than the
    # operator. ``None`` on operator/CLI sends leaves those rows byte-identical.
    persona_chat_user_finish_reason: str | None = None
    client_message_id: str | None = None
    turn_id: str | None = None
    persona_instance_id: str | None = None
    root_chat_session_id: str | None = None
    persona_chat_runtime_registry: Any | None = None
    persona_chat_runtime_signature: str | None = None
    #: The per-component digest map the signature above was folded from
    #: (``mission_chat_turn_context.mission_chat_runtime_signature_digests``).
    #: Optional and receipt-only: reuse is decided by the composite signature,
    #: and this exists so a refused reuse can NAME the component that moved.
    persona_chat_runtime_signature_components: dict[str, str] | None = None
    persona_chat_native_revision: str | None = None
    # Explicit one-turn proof/debug seam. Normal persona-chat turns leave these
    # unset and inherit the model/profile compressor configuration.
    compression_threshold_tokens_override: int | None = None
    compression_protect_first_n_override: int | None = None
    compression_protect_last_n_override: int | None = None
    platform: str = "agent_runtime"
    skill_surface: str | None = None
    skill_root_node_mode: bool = False
    quiet_mode: bool = True
    skip_context_files: bool = True
    skip_memory: bool = True
    max_iterations: int = 90
    max_wall_seconds: float | None = None
    max_api_calls: int | None = None
    max_total_tokens: int | None = None
    system_message: str | None = None
    user_message: str = ""
    task_id: str | None = None
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    stream_callback: Callable[[str | None], None] | None = None
    agent_ready_callback: Callable[[Any], Callable[[], None] | None] | None = None
    # Interactive clarify bridge: ``callback(question, choices) -> str``. On the
    # operator/relay chat lane this is a NON-blocking capture (records the
    # question and ends the turn) rather than the CLI's blocking human prompt;
    # unset on autonomous runs so ``clarify`` stays inert there.
    clarify_callback: Callable[[str, list[str] | None], str] | None = None
    runtime_root: Path | None = None
    workdir: Path | None = None
    # Resolved, side-effect-free MCP admission for this run (agent_runtime.
    # mcp_admission.resolve_mcp_admission). Unset on every lane that declares no
    # MCP servers or runs with the admission flag off — which is all of them
    # until an operator enables it. The RUNNER performs the registration, inside
    # the persona profile context and before agent construction, so the decision
    # (policy) and the side effect (spawn) stay separable and separately tested.
    mcp_admission: Any | None = None
    # Build this run's agent, register it in the resident-chat registry, and
    # STOP — no conversation, no provider call, no `agent_ready` notification.
    # Set only by `agent_runtime.persona_chat_actor_prewarm`, which pays §2.3's
    # 3.0-3.6 s construction on a background worker so the operator's first
    # message of a chat finds an already-registered resident entry. The whole
    # point is that it rides the SAME `_execute_agent_run` body — same
    # `_WORKDIR_LOCK`, same `persona_profile_context`, same workdir/tool/
    # terminal/skill scopes, same MCP admission and teardown, same `acquire()`
    # with the same signature and revision — because a construction performed
    # under different scopes is a different agent, and an actor built under a
    # signature the next turn does not reproduce is discarded on arrival.
    # Reached through `ProfileAgentRunner.prewarm`, never through `run`.
    prewarm_only: bool = False
    # Lane/role identity for the terminal safety envelope
    # (agent_runtime.terminal_envelope.TerminalEnvelopeScope). Set ONLY by
    # lanes the envelope grant policy governs — mission-chat today. Left None
    # everywhere else, which is how "no other lane changes" is enforced
    # structurally: with no scope bound, ``envelope_decision`` returns None and
    # the terminal tool keeps its legacy pattern-table behavior byte-for-byte.
    terminal_envelope_scope: Any | None = None


@dataclass(slots=True)
class AgentRunResult:
    final_response: str
    session_id: str | None
    provider: str | None
    model: str | None
    base_url: str | None
    messages: list[dict[str, Any]]
    api_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    # Canonical cache/reasoning buckets. ``input_tokens`` is already the uncached,
    # full-price remainder (canonical usage subtracts these; see
    # agent/usage_pricing.CanonicalUsage). Carrying them here keeps the accounting
    # object complete end-to-end so downstream writers never have to reconstruct
    # a lossy subset — the persona-chat bound-session record and the Launcher
    # cache indicator both read from these.
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    # Per-call canonical usage rows for this turn (call_index/prompt_tokens/…),
    # in call order. The token fields above are turn-cumulative and answer "what
    # did this turn burn"; row 1 answers "how big was the assembled context",
    # which is the only honest source for Mission Control's context budget.
    # Collected per API call by agent_runtime.usage_ledger (bound around run_conversation).
    usage_ledger: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int | None = None
    # Mostly ``_ms`` / ``_count`` integers, plus the one structured entry
    # ``run_budget`` (the accounting block from ``run_budget.RunBudgetLedger``).
    # Live downstream readers copy the dict wholesale; S34 retired the dead
    # run-record accumulator that used to filter it to ``_ms``/``_count`` keys.
    profile_timing: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
