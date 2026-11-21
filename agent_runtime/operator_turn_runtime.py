"""The operator chat's turn runtime on the gateway engine: what the turn policy
(``agent_runtime.operator_turn_policy``) reads around one turn of a Mission Control chat.

Which tools and toolsets the turn may use (the blocked-tool set with the registry-hygiene names, the
admitted toolsets), the per-request runtime resolution and its short-lived memo (one memo, one writer),
the first turn's warm-up steps, agent-ready notification and cleanup, a QA turn's forced silence, and the
usage-ledger wrapper around the conversation call. Moved whole from ``profile_runner/execute.py`` when the
operator chat's own turn host was folded into the engine (row
``RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT``, owner 2026-11-21 "Yes, fold and delete").
"""

from __future__ import annotations

import contextvars
import functools
from pathlib import Path
from types import SimpleNamespace
from threading import Event, RLock
import time
from typing import Any, Callable

from hermes_cli.runtime_provider import resolve_runtime_provider

from agent_runtime import idle_turn_keeper
from agent_runtime.personas import _blocked_tool_names_with_registry_hygiene
from agent_runtime.prewarmed_system_prompt import RAN_ON_RUN_END, run_deferred_turn_persist
from agent_runtime.serde import positive_float
from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "lanes"

__all__ = [
    "RUNTIME_RESOLVE_CACHE_TTL_SECONDS",
    "_FIRST_TURN_STORE_STEPS",
    "_RUNTIME_RESOLVE_CACHE",
    "_RUNTIME_RESOLVE_CACHE_LOCK",
    "_RUNTIME_RESOLVE_STAMPED_FILES",
    "_blocked_tool_names_for_run",
    "_cleanup_agent_ready",
    "_emit_agent_ready_callback_warning",
    "_enabled_toolsets_for_run",
    "_local_engine_construction_kwargs",
    "_local_engine_prewarm_scope",
    "_notify_agent_ready",
    "_qa_silence",
    "_resolve_request_runtime",
    "_run_conversation_with_usage_ledger",
    "_run_transport",
    "_runtime_resolve_cache_key",
]

def _warm_skill_catalog(agent) -> None:
    """Fill the process-wide skill-catalog memo the turn's observability row reads (h-send-window)."""

    from agent_runtime.prompt_observability.skills_resolver import _installed_skill_catalog

    _installed_skill_catalog()


def _warm_run_provenance(agent) -> None:
    """Resolve the process's ``ran_by`` stamp the turn's write-ahead records (RT-TURN0-REQUEST-SENT-IDLE-RED).

    ``mission_chat_turns.journal._turn_stamps`` stamps every turn record with
    ``run_provenance.ran_by()``, cached once per process; cold, it is the build stamp's
    ``git rev-parse`` + ``status`` + the ``ls-tree`` code-tree digest (~400 ms of CPU on the
    ``build-stamp-code-tree`` thread), and turn 0's ``write_ahead -> agent_ready`` paid it:
    the idle-box guard read turn 0 at 600-726 ms against warm turns of 177-217.
    """

    from agent_runtime.run_provenance import ran_by

    ran_by()


#: Warm-up steps that read a store; ``first_turn_warmup`` is policy and may not import one.
_FIRST_TURN_STORE_STEPS = (("skill_catalog", _warm_skill_catalog), ("run_provenance", _warm_run_provenance))



# ── which tools and toolsets a run may use ──────────────────────────────────

def _blocked_tool_names_for_run(request: AgentRunRequest) -> list[str]:
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
    request: AgentRunRequest, admitted_servers: tuple[str, ...] = ()
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

    from .mcp_admission.resolve import scope_toolsets_to_admission

    if request.enabled_toolsets is None:
        return None
    return scope_toolsets_to_admission(
        request.enabled_toolsets, admitted_servers=admitted_servers
    )


# ── the per-request runtime resolution and its memo ─────────────────────────

#: T6 (2026-08-09): how long a resolved runtime may be reused for an unchanged
#: (profile, provider, model, config) tuple. 0.28-0.44 s of every send was spent
#: re-resolving an identical answer.
#:
#: THE TTL IS A SAFETY BOUND, NOT A TUNING KNOB, and it is why it is 30 s rather
#: than something generous. ``resolve_runtime_provider`` returns live OAuth
#: credentials and refreshes any token within
#: ``hermes_cli.auth.ACCESS_TOKEN_REFRESH_SKEW_SECONDS`` (120 s) of expiry. A
#: memo handed out T seconds after resolution therefore carries a token with at
#: least ``skew - T`` seconds of validity left: at 30 s that floor is 90 s,
#: comfortably longer than the turn that is about to use it. Raising this past
#: the skew would hand out expired credentials, so it must stay well under it —
#: the invariant is pinned by
#: ``tests/agent_runtime/test_send_path_runner_reuse.py`` (`:425-426`, which
#: asserts this constant is positive AND below half the refresh skew). This
#: line named ``test_runtime_resolve_cache.py``, a file that never existed;
#: repointed MCF-78 2026-08-20.
RUNTIME_RESOLVE_CACHE_TTL_SECONDS = 30.0


#: Files whose content can change what ``resolve_runtime_provider`` returns for
#: an otherwise identical request (default provider/model, base_url, a provider
#: flipped to ``enabled: false``, a rotated key). Their (mtime_ns, size) join the
#: cache key, so an operator edit invalidates the memo immediately instead of
#: waiting out the TTL.
_RUNTIME_RESOLVE_STAMPED_FILES = ("config.yaml", ".env")


_RUNTIME_RESOLVE_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}


_RUNTIME_RESOLVE_CACHE_LOCK = RLock()


def _runtime_resolve_cache_key(request: AgentRunRequest) -> tuple:
    """Everything that can change the answer, and nothing that cannot.

    ``HERMES_HOME`` is in the key because this resolves INSIDE
    ``persona_profile_context`` — two personas bound to different profiles must
    never share a memo (the same reason profile-context memos key on it).
    """

    from hermes_constants import get_hermes_home
    from agent.provider_access import authentication_owner_stamps

    home = Path(get_hermes_home())
    stamps = []
    for name in _RUNTIME_RESOLVE_STAMPED_FILES:
        try:
            stat = (home / name).stat()
            stamps.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            # An absent file is a stable fact about the config too; it becomes a
            # different key the moment one is created.
            stamps.append((name, None, None))
    return (
        str(home),
        str(request.provider or ""),
        str(request.model or ""),
        tuple(stamps),
        authentication_owner_stamps(),
    )


def _run_transport(request: AgentRunRequest, runtime: dict) -> dict:
    """``api_mode`` + ``base_url`` for the run, decided as ONE pair. An OpenCode relay serves
    Anthropic-wire, Responses and chat/completions models behind one provider, so a persisted
    instance/persona ``api_mode`` (the provider default) is wrong for every model but one; the relay's
    per-model authority, ``opencode_transport``, decides both halves so the URL and the client agree."""
    from agent.opencode_affinity import opencode_transport

    base_url = runtime.get("base_url")
    api_mode, url = opencode_transport(runtime.get("provider") or request.provider,
                                       runtime.get("model") or request.model, base_url)
    if api_mode is not None:
        return {"api_mode": api_mode, "base_url": url or base_url}
    return {"api_mode": request.api_mode or runtime.get("api_mode"), "base_url": base_url}



def _local_engine_shipped() -> bool:
    """Whether the local engine ships: a profile that leaves it out (the phone) has no local provider,
    so its scopes and construction arguments are neutral there."""
    from .module_presence import shipped

    return shipped("agent_runtime.local_llama_adapter")


def _local_engine_prewarm_scope(*args: Any, **kwargs: Any):
    import contextlib

    if not _local_engine_shipped():
        return contextlib.nullcontext()
    from .local_llama_adapter.provider import prewarm_scope

    return prewarm_scope(*args, **kwargs)


def _local_engine_construction_kwargs():
    if not _local_engine_shipped():
        return lambda *_args, **_kwargs: {}
    from .local_llama_adapter.provider import construction_kwargs

    return construction_kwargs

def _resolve_request_runtime(
    request: AgentRunRequest, timing: dict[str, Any] | None = None
) -> dict[str, Any]:
    if _local_engine_shipped():
        from .local_llama_adapter import is_local_llama_provider
        if is_local_llama_provider(request.provider):
            from .local_llama_adapter.provider import resolve
            return resolve(request.model, root=request.runtime_root)
    if not request.provider:
        return {}
    key = _runtime_resolve_cache_key(request)
    now = time.monotonic()
    with _RUNTIME_RESOLVE_CACHE_LOCK:
        cached = _RUNTIME_RESOLVE_CACHE.get(key)
        if cached is not None and now - cached[0] <= RUNTIME_RESOLVE_CACHE_TTL_SECONDS:
            if timing is not None:
                timing["runtime_resolve_cached"] = 1
            return dict(cached[1])
    resolved = _resolved_fields(resolve_runtime_provider(requested=request.provider, target_model=request.model))
    # h-idle-turn: between turns the idle keeper re-resolves this entry before it lapses, in this
    # turn's context (the profile binding), so the next turn after a pause reads it warm.
    idle_turn_keeper.register_refresh(
        f"runtime_resolve:{key[0]}|{key[1]}|{key[2]}",
        functools.partial(contextvars.copy_context().run, _idle_refresh_runtime_resolve,
                          str(request.provider or ""), str(request.model or "")),
    )
    _store_resolved(key, now, resolved)
    if timing is not None:
        timing["runtime_resolve_cached"] = 0
    return resolved


def _store_resolved(key: tuple, at: float, resolved: dict[str, Any], *, replace_only: bool = False) -> None:
    """The memo's one write path (a turn's resolve; the idle keeper's, ``replace_only``)."""

    with _RUNTIME_RESOLVE_CACHE_LOCK:
        if replace_only and key not in _RUNTIME_RESOLVE_CACHE:
            return
        # Bounded: one entry per live (profile, provider, model, config) tuple,
        # and the set of those is small. Evict the oldest wholesale rather than
        # keep an LRU — a cold re-resolve costs one turn 0.3 s, a leak costs the
        # process.
        if len(_RUNTIME_RESOLVE_CACHE) >= 64:
            _RUNTIME_RESOLVE_CACHE.clear()
        _RUNTIME_RESOLVE_CACHE[key] = (at, dict(resolved))


def _resolved_fields(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        key_name: value
        for key_name, value in runtime.items()
        if key_name in {"provider", "model", "api_mode", "base_url", "api_key"} and value
    }


def _idle_refresh_runtime_resolve(provider: str, model: str) -> bool:
    """h-idle-turn: re-resolve one warm memo entry that would lapse before the keeper's next tick."""

    request = SimpleNamespace(provider=provider, model=model)
    key = _runtime_resolve_cache_key(request)  # type: ignore[arg-type]
    with _RUNTIME_RESOLVE_CACHE_LOCK:
        cached = _RUNTIME_RESOLVE_CACHE.get(key)
    lapse_after = max(0.0, RUNTIME_RESOLVE_CACHE_TTL_SECONDS - idle_turn_keeper.KEEPER_INTERVAL_SECONDS)
    if cached is None or time.monotonic() - cached[0] < lapse_after:
        return False  # gone (a config edit moved the key) or still fresh
    started = time.monotonic()
    _store_resolved(key, started, _resolved_fields(resolve_runtime_provider(requested=provider, target_model=model)),
                    replace_only=True)
    return True


def _notify_agent_ready(request: AgentRunRequest, agent: Any) -> Callable[[], None] | None:
    callback = request.agent_ready_callback
    if callback is None:
        return None
    try:
        return callback(agent)
    except Exception as exc:
        _emit_agent_ready_callback_warning(request, exc, phase="start")
        return None


def _qa_silence(request: AgentRunRequest, expired: Event | None) -> None:
    """A QA turn's forced model silence (``agent_runtime.qa_turn_overrides``): wait before the first
    provider call. Cut short by the hard wall (``expired``); a no-op on every real turn."""

    seconds = positive_float(request.qa_silence_seconds)
    if seconds is None:
        return
    (expired or Event()).wait(seconds)


def _run_conversation_with_usage_ledger(agent: Any, conversation_kwargs: dict[str, Any]) -> Any:
    """Run the turn with a per-call usage ledger, the persona agent bound for plugin
    middleware (dispatch timing, cache routing) and the provider stream observers armed;
    a dict result carries the ledger as ``usage_ledger``, the turn's reasoning
    (``stream_gap_receipt.TurnReasoning``) as ``reasoning_window`` and what the turn
    left behind (``turn_outcome.TurnOutcomeFold.block``, None when nothing) as
    ``turn_outcome``."""
    from agent_runtime.chat_lane_defer import turn_defer_tools
    from agent_runtime.codex_observability import stream_observers_armed
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent
    from agent_runtime.stream_gap_receipt import bind_turn_reasoning
    from agent_runtime.turn_outcome import bind_turn_outcome
    from agent_runtime.usage_ledger import bind_usage_ledger
    from tools.tool_search_downstream import scoped_turn_defer

    # The persona's defer reaches the bridge's reads (search catalog, tool_call resolve) here.
    with bind_usage_ledger() as usage_ledger, bind_persona_turn_agent(agent), stream_observers_armed(),             scoped_turn_defer(turn_defer_tools(agent)), bind_turn_reasoning(agent) as reasoning,             bind_turn_outcome() as outcome:
        try:
            raw_result = agent.run_conversation(**conversation_kwargs)
        finally:
            # h-turn1-conn: a held first-turn persist whose request never went out runs now.
            run_deferred_turn_persist(agent, RAN_ON_RUN_END)
    if isinstance(raw_result, dict):
        raw_result["usage_ledger"] = list(usage_ledger)
        raw_result["turn_outcome"] = outcome.block()
        window = reasoning.fields()
        reported = sum(row.get("reasoning_tokens", 0) for row in usage_ledger)
        if reported > 0:
            raw_result["reasoning_tokens"] = reported
            if not window:
                window = {"reasoning_tokens": reported}
        raw_result["reasoning_window"] = window
    return raw_result


def _cleanup_agent_ready(cleanup: Callable[[], None] | None, request: AgentRunRequest) -> None:
    if cleanup is None:
        return
    try:
        cleanup()
    except Exception as exc:
        _emit_agent_ready_callback_warning(request, exc, phase="cleanup")


def _emit_agent_ready_callback_warning(request: AgentRunRequest, exc: Exception, *, phase: str) -> None:
    if request.progress_callback is None:
        return
    try:
        request.progress_callback(
            {
                "type": "run.progress",
                "phase": "agent_ready_callback",
                "severity": "warning",
                "step": phase,
                "status": "failed",
                "summary": f"Agent ready callback {phase} failed: {type(exc).__name__}",
            }
        )
    except Exception:
        return
