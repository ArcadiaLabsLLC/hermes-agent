"""Pay a chat actor's first-turn-only costs on the prewarm thread.

h-conn-pool (``Harness_Brain/20 — Active Initiatives/runtime-queue.md``, the A5
read row). The A5 split named ``lead_in`` (``preflight_done`` -> the start of
``build_api_request``) as the first turn's cost: 516 ms on Neko ``323d4f079037``
turn 1, 0-1 ms on every later turn; ``kwargs`` read 150 ms against 44-73. Run
offline, both are one-time process work, not the agent's:

* ``lead_in`` is ``announce_api_call`` picking a spinner verb --
  ``agent/display.py::KawaiiSpinner.get_thinking_verbs`` -> ``agent.i18n.t`` ->
  the first parse of the bundled locale YAML (pure-Python ruamel, cached per
  ``(home, language)`` in ``agent.i18n._catalog_cache``).
* ``kwargs`` is ``agent._build_api_kwargs``'s lazy forward importing
  ``agent.chat_completion_helpers``.
* ``client_built -> request_sent`` carries a third: the OpenAI SDK's first
  ``platform_headers()`` (``platform.platform()`` -> two WMI queries on Windows,
  ~300 ms, cached for the process) and its ``client.responses`` resource import.

h-send-window (2026-10-06) adds two more, from the Neko turn-1 records ``c1cfc36c``
/ ``3e412f30`` (each the first chat turn of its serve process) against their warm
turns:

* ``provider_request_started -> conversation_started`` 422 / 111 ms (warm 5-12):
  ``agent/turn_facade.py::run_conversation``'s lazy imports -- the Relay binding
  (``nemo_relay`` and its ~20 submodules, via ``relay_runtime._load_nemo_relay``),
  ``relay_shared_metrics`` and its ``shared_metrics*`` family, the turn lease and
  its neighbours; then ``build_turn_context``'s (title generator, native
  persistence, bot-mode DM, MCP tool names). Offline (the turn-cost guard
  scenario, a stack sampler between the marks) 129 ms against 16 warm, every
  sample inside an import.
* ``context_built -> observability_built`` 484 / 518 ms (warm 60-150):
  ``observability_catalog_walk_ms=312 / 330`` -- the serve's skill-catalog memo
  is COLD on its first chat turn, because the hub's snapshot builds (the only
  other readers) run in the snapshot worker process. The memo is process-wide,
  so the prewarm reads it once (:func:`_warm_skill_catalog`).

:func:`warm_first_turn_paths` runs each once, under the prewarm's own scopes (the
catalog is keyed by the profile home the turn will run in), so the first turn
finds them cached. It sends nothing anywhere and never raises.
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: ``profile_timing`` key the prewarm writes: what this warm-up cost it.
PREWARM_FIRST_TURN_WARMUP_MS = "prewarm_first_turn_warmup_ms"

#: Modules a turn imports lazily on its way to the provider request:
#: the loop and its phases, the ``_build_api_kwargs`` target, the dispatch's
#: stream wrapper; then (h-send-window) the turn facade's entry imports, the
#: Relay binding and the turn-context builder's. Each is imported on its own and
#: a missing one (``nemo_relay`` is an optional install) is skipped.
FIRST_TURN_MODULES = (
    "agent.conversation_loop", "agent.chat_completion_helpers", "agent.relay_llm",
    "agent.turn_facade", "agent.turn_facade_lease", "agent.turn_liveness", "agent.periodic_scheduler",
    "agent.aux_accounting", "agent.relay_cwd", "agent.review_idle_queue", "agent.subagent_lifecycle",
    "nemo_relay", "hermes_cli.observability.relay_shared_metrics",
    "hermes_cli.observability.shared_metrics_send_config", "hermes_cli.moa_config",
    "agent_runtime.persona_turn_binding", "agent_runtime.usage_ledger",
    "agent.title_generator", "agent_runtime.native_persistence", "tools.bot_mode_dm", "tools.mcp_tool_agent",
    "hermes_cli.build_info", "hermes_cli.lifecycle",
    "agent.opencode_affinity", "agent.plugin_stream_hooks", "agent.replay_cleanup",
    "hermes_cli.observability.shared_metrics_process", "agent_runtime.skill_publishability",
    "agent_runtime.skills_inventory", "agent_runtime.transport_phase_trace",
    "agent.chat_completion_nonstream", "agent.reasoning_timeouts",
)


def _warm_spinner_catalog() -> None:
    from agent.display import KawaiiSpinner

    KawaiiSpinner.get_thinking_faces()
    KawaiiSpinner.get_thinking_verbs()


def _warm_request_modules() -> None:
    for name in FIRST_TURN_MODULES:
        try:
            importlib.import_module(name)
        except Exception:
            logger.debug("first-turn module %s not importable", name, exc_info=True)


def _warm_skill_catalog() -> None:
    """Fill the process-wide skill-catalog memo the turn's observability row reads."""

    from agent_runtime.prompt_observability.skills_resolver import _installed_skill_catalog

    _installed_skill_catalog()


def _warm_sdk_request_build(agent: Any) -> None:
    """The SDK's process-wide first-request costs: platform headers and the resource import."""

    client = getattr(agent, "client", None)
    platform_headers = getattr(type(client), "platform_headers", None)
    if callable(platform_headers):
        platform_headers(client)
    getattr(client, "responses", None)


_STEPS = (
    ("spinner_catalog", lambda agent: _warm_spinner_catalog()),
    ("request_modules", lambda agent: _warm_request_modules()),
    ("skill_catalog", lambda agent: _warm_skill_catalog()),
    ("sdk_request_build", _warm_sdk_request_build),
)


def warm_first_turn_paths(agent: Any, timing: dict[str, Any]) -> None:
    """Run every warm-up step for *agent*; record the total in *timing*. Never raises."""

    started = time.perf_counter()
    for name, step in _STEPS:
        try:
            step(agent)
        except Exception:
            logger.debug("first-turn warm-up step %s failed", name, exc_info=True)
    try:
        timing[PREWARM_FIRST_TURN_WARMUP_MS] = max(0, int((time.perf_counter() - started) * 1000))
    except Exception:
        pass


# ── the process-once half, paid at serve boot (h-prewarm-order) ───────────────
#
# The 2026-10-06 01:24:59.35 -> 01:25:04.62 silent span of the boot actor
# prewarm (5.3 s, ``system_prompt_build_ms=2159``), re-measured offline in a
# cold process (scratch home, loopback provider): the first system-prompt build
# is 3,232 ms of which 3,050 ms is upstream's once-per-process scratch prune
# (``build_environment_hints`` -> ``get_scratch_dir`` -> ``prune_scratch_dir``
# -> ``reap_processes_rooted_in``: ``psutil`` reads the cwd of every process on
# the host, ~6 ms each); the second build is 39 ms. ``sdk_request_build`` is
# 1,579 ms, of which ~1,420 ms is importing ``openai.resources.responses`` and
# ~130 ms ``platform.platform()``. On Linux the prune runs at import
# (``hermes_bootstrap.export_scratch_tmp_env``); on Windows the OS's ``%TEMP%``
# makes that hook return before it, so the first prompt build paid it -- on the
# one worker the operator's opened chat queues behind.
#
# Every step below is process-wide (a global flag, a module import, the
# ``platform`` cache), so paying it once on the serve's boot thread removes it
# from every construction after.

PROCESS_ONCE_WARM_RECEIPT = (
    "serve_process_once_warm scratch_prune_ms=%d sdk_responses_ms=%d platform_ms=%d request_modules_ms=%d"
)

#: The SDK resource the codex turn sends through (``client.responses``).
SDK_RESPONSES_MODULE = "openai.resources.responses"


def _warm_scratch_prune() -> None:
    from hermes_constants import get_scratch_dir

    get_scratch_dir()


def _warm_sdk_responses() -> None:
    importlib.import_module(SDK_RESPONSES_MODULE)


def _warm_platform() -> None:
    import platform

    platform.platform()


_PROCESS_ONCE_STEPS = (
    ("scratch_prune", _warm_scratch_prune),
    ("sdk_responses", _warm_sdk_responses),
    ("platform", _warm_platform),
    ("request_modules", _warm_request_modules),
)


def warm_process_once_costs() -> dict[str, int]:
    """Pay the process-once costs a chat actor's construction would pay; log one receipt. Never raises."""

    spent: dict[str, int] = {}
    for name, step in _PROCESS_ONCE_STEPS:
        started = time.perf_counter()
        try:
            step()
        except Exception:
            logger.debug("process-once warm step %s failed", name, exc_info=True)
        spent[name] = max(0, int((time.perf_counter() - started) * 1000))
    logger.info(PROCESS_ONCE_WARM_RECEIPT, *(spent[name] for name, _ in _PROCESS_ONCE_STEPS))
    return spent


__all__ = [
    "FIRST_TURN_MODULES",
    "PREWARM_FIRST_TURN_WARMUP_MS",
    "PROCESS_ONCE_WARM_RECEIPT",
    "warm_first_turn_paths",
    "warm_process_once_costs",
]
