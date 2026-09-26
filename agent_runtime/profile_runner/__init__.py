"""The profile runner — one agent run under a profile's runtime (the package map, rule 16).

Entry points (what calls in):

* ``runner.ProfileAgentRunner`` (``run`` / ``prewarm``) — the chat turn lane,
  the persona runtime and the dispatch lanes run an agent through it.
* ``models.AgentRunRequest`` / ``AgentRunResult`` — the request and the answer.
* ``errors.RunBudgetExceeded`` — a run that spent its budget.
* ``workdir.agent_runs_in_flight`` — the in-flight census.

Modules, lowest layer first (no module imports one above it — W0-G6):

=========================  ======  ============================================
module                     layer   owns
=========================  ======  ============================================
errors                     models  runner errors, provider-error capture
models                     models  ``AgentRunRequest``, ``AgentRunResult``
budget                     policy  wall budget, tool guard, result budgets
status                     policy  timing, status callback, profile binding
operator_redaction         policy  the operator-facing scrubbers
workdir                    stores  working directory, in-flight census
tool_payloads              stores  tool/dev-work/todo payloads, safe labels
dispatch_payloads          stores  dispatch payload fields (reads a persona label)
progress                   stores  callback -> progress payloads
model_input_observability  stores  compaction and model-input receipts
resident_actor             lanes   the resident chat actor around a run
mcp_lane                   lanes   MCP admission notices in a run
execute                    lanes   ``AgentRunExecution`` (one run, phase by phase);
                                   blocked tools, enabled toolsets; the per-request
                                   runtime resolution memo
runner                     lanes   ``ProfileAgentRunner`` (admit MCP, run, tear down)
=========================  ======  ============================================

Stores written: none of its own beyond the process memos (``workdir``,
``execute``'s runtime-resolution memo); receipts ride the progress callback and the observability
records. Never imported from here: ``hermes_cli.harness``.
"""

from __future__ import annotations

import time
from hermes_cli.profiles import get_profile_dir, normalize_profile_name, profile_exists
from hermes_cli.runtime_provider import resolve_runtime_provider
from agent_runtime.profile_context import persona_profile_context
from agent_runtime.profile_runner import (  # noqa: F401 — every family, in the original definition order
    errors,
    models,
    budget,
    resident_actor,
    runner,
    execute,
    mcp_lane,
    workdir,
    status,
    progress,
    dispatch_payloads,
    tool_payloads,
    operator_redaction,
    model_input_observability,
)
from agent_runtime.profile_runner.errors import (
    ProfileRunnerError,
    RunBudgetExceeded,
    _ProviderErrorCapture,
    _capture_provider_errors,
)
from agent_runtime.profile_runner.models import AgentRunRequest, AgentRunResult
from agent_runtime.profile_runner.budget import WallBudgetCheckpoint, _ToolBudgetGuard
from agent_runtime.profile_runner.resident_actor import (
    _finish_resident_persona_chat_agent,
    stage_persona_chat_user_row_marker,
)
from agent_runtime.profile_runner.runner import (
    ProfileAgentRunner,
    _default_agent_factory,
    _normalize_result,
)
from agent_runtime.profile_runner.execute import (
    RUNTIME_RESOLVE_CACHE_TTL_SECONDS,
    _resolve_request_runtime,
    _run_conversation_with_usage_ledger,
    _runtime_resolve_cache_key,
    reset_runtime_resolve_cache,
)
from agent_runtime.profile_runner.workdir import (
    _WORKDIR_LOCK,
    _agent_workdir,
    _counted_agent_run,
    agent_runs_in_flight,
)
from agent_runtime.profile_runner.status import (
    _binding_for_profile,
    _profile_status_callback,
)
from agent_runtime.profile_runner.progress import _progress_adapter
from agent_runtime.profile_runner.dispatch_payloads import _agent_chat_target_label
from agent_runtime.profile_runner.tool_payloads import (
    _TODO_STATE_MAX_CONTENT,
    _TODO_STATE_MAX_ITEMS,
    _todo_items_from,
    _todo_state_payload,
    _tool_finished_payload,
    _tool_started_payload,
)
from agent_runtime.profile_runner.operator_redaction import _is_error_result
from agent_runtime.profile_runner.model_input_observability import (
    _apply_chat_compaction_threshold,
    _rendered_skills_prompt_chars,
    _system_prompt_section_receipts,
)

__layer__ = "lanes"

__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
    "ProfileAgentRunner",
    "ProfileRunnerError",
    "RUNTIME_RESOLVE_CACHE_TTL_SECONDS",
    "RunBudgetExceeded",
    "WallBudgetCheckpoint",
    "_ProviderErrorCapture",
    "_TODO_STATE_MAX_CONTENT",
    "_TODO_STATE_MAX_ITEMS",
    "_ToolBudgetGuard",
    "_WORKDIR_LOCK",
    "_agent_chat_target_label",
    "_agent_workdir",
    "_apply_chat_compaction_threshold",
    "_binding_for_profile",
    "_capture_provider_errors",
    "_counted_agent_run",
    "_default_agent_factory",
    "_finish_resident_persona_chat_agent",
    "_is_error_result",
    "_normalize_result",
    "_profile_status_callback",
    "_progress_adapter",
    "_rendered_skills_prompt_chars",
    "_resolve_request_runtime",
    "_run_conversation_with_usage_ledger",
    "_runtime_resolve_cache_key",
    "_system_prompt_section_receipts",
    "_todo_items_from",
    "_todo_state_payload",
    "_tool_finished_payload",
    "_tool_started_payload",
    "agent_runs_in_flight",
    "get_profile_dir",
    "normalize_profile_name",
    "persona_profile_context",
    "profile_exists",
    "reset_runtime_resolve_cache",
    "resolve_runtime_provider",
    "stage_persona_chat_user_row_marker",
    "time",
]
