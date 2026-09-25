"""Token authority: the provider meter, not a heuristic, sizes the context.

Regression cover for the 2026-07-16 defect class — the Mission Control context
inspector reported a bytes//4 estimate over system+user messages only (blind to
tool schemas, which ship in full on every API call) while the turn was billed
per call across a 2-19 call tool loop. Two parallel authorities, no
reconciliation, a 6K inspector next to a 13K bill.

Design: docs/mission_control/TOKEN_AUTHORITY_DESIGN_2026-07-16.md (launcher repo).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent.usage_pricing import CanonicalUsage
from agent_runtime.usage_ledger import (
    USAGE_LEDGER_MAX_ROWS,
    bind_usage_ledger,
    on_post_api_request,
    record_usage,
)
from agent_runtime.prompt_observability import (
    BUDGET_BASIS_ESTIMATE_MESSAGES_ONLY,
    BUDGET_BASIS_ESTIMATE_WITH_TOOLS,
    BUDGET_BASIS_METERED_FIRST_CALL,
    _context_budget,
    _context_budget_needs_refresh,
    _safe_final_model_input,
    _safe_turn_usage,
    turn_usage_from_result,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_SELECTION = {"effective_model": "claude-sonnet-5", "effective_provider": "anthropic"}
# 40,100 message bytes + 47,603 tool-schema bytes (the live 27-tool measurement
# from `hermes prompt-size --json`, 2026-07-16).
TOOL_JSON_BYTES = 47_603
MESSAGE_BYTES = 40_100
FINAL_INPUT_WITH_TOOLS = {
    "messages": [{"bytes": 40_000}, {"bytes": 100}],
    "tool_schema": {"json_bytes": TOOL_JSON_BYTES, "tool_count": 27, "final_model_tools": ["read_file"]},
}
FINAL_INPUT_NO_TOOLS = {"messages": [{"bytes": 40_000}, {"bytes": 100}]}


# --------------------------------------------------------------------------
# H1 — per-call usage ledger (agent_runtime.usage_ledger, fed by post_api_request)
# --------------------------------------------------------------------------


def test_ledger_records_one_row_per_call_with_canonical_prompt_tokens():
    with bind_usage_ledger() as ledger:
        record_usage(CanonicalUsage(input_tokens=100, cache_read_tokens=900, output_tokens=5))
        record_usage(CanonicalUsage(input_tokens=50, cache_read_tokens=2_000, output_tokens=7))

    assert [row["call_index"] for row in ledger] == [1, 2]
    # prompt = input + cache_read + cache_write (CanonicalUsage's definition).
    assert ledger[0]["prompt_tokens"] == 1_000
    assert ledger[1]["prompt_tokens"] == 2_050
    assert ledger[0]["cache_read_tokens"] == 900


def test_post_api_request_usage_summary_becomes_a_row():
    """The hook payload's ``usage`` is upstream's normalized bucket summary."""
    with bind_usage_ledger() as ledger:
        on_post_api_request(usage={"prompt_tokens": 42_733, "input_tokens": 733, "output_tokens": 9,
                                   "cache_read_tokens": 42_000}, turn_id="t", session_id="s")
        on_post_api_request(usage=None, turn_id="t")  # a response without usage adds no row

    assert ledger == [{"call_index": 1, "prompt_tokens": 42_733, "input_tokens": 733, "output_tokens": 9,
                       "cache_read_tokens": 42_000, "cache_write_tokens": 0, "reasoning_tokens": 0}]


def test_no_bound_ledger_records_nothing():
    record_usage(CanonicalUsage(input_tokens=1))
    with bind_usage_ledger() as ledger:
        pass
    assert ledger == []


def test_ledger_is_bounded():
    with bind_usage_ledger() as ledger:
        for _ in range(USAGE_LEDGER_MAX_ROWS + 20):
            record_usage(CanonicalUsage(input_tokens=1))

    assert len(ledger) == USAGE_LEDGER_MAX_ROWS


def test_every_usage_accrual_site_is_covered_by_the_ledger():
    """Guard: a new accrual site must not silently skip the ledger.

    Exactly two sites advance the session_* token counters. ``turn_usage.py`` is
    upstream's, and the call it accrues for fires ``post_api_request`` (the
    plugin's ledger hook); the Codex app-server path never fires that hook, so
    ``codex_runtime.py`` records the row itself. A third site reds here.
    """
    # The direct form, and the Codex path's ``setattr(agent, f"session_{key}", ... + value)`` loop.
    accrual = re.compile(r"session_(?:prompt|input)_tokens\s*\+=|setattr\(agent, f\"session_\{key\}\"")
    sites = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "agent").rglob("*.py")
        if accrual.search(path.read_text(encoding="utf-8", errors="replace"))
    )
    assert sites == ["agent/codex_runtime.py", "agent/turn_usage.py"]
    codex = (REPO_ROOT / "agent" / "codex_runtime.py").read_text(encoding="utf-8")
    assert "record_usage(canonical_usage)" in codex


def test_the_plugin_feeds_the_ledger_from_post_api_request():
    import importlib.util

    path = REPO_ROOT / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_ledger_under_test", path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    hooks = {}

    class _Ctx:
        def __getattr__(self, name):
            return lambda *a, **k: None

        def register_hook(self, name, callback):
            hooks[name] = callback

    plugin.register(_Ctx())
    with bind_usage_ledger() as ledger:
        hooks["post_api_request"](usage={"prompt_tokens": 7}, turn_id="t", api_call_count=1)
    assert [row["prompt_tokens"] for row in ledger] == [7]


def test_the_persona_runner_binds_the_ledger_around_the_turn():
    from agent_runtime.profile_runner import _run_conversation_with_usage_ledger

    class _Agent:
        def run_conversation(self, **kwargs):
            on_post_api_request(usage={"prompt_tokens": 11})
            on_post_api_request(usage={"prompt_tokens": 13})
            return {"final_response": "ok", **kwargs}

    result = _run_conversation_with_usage_ledger(_Agent(), {"user_message": "hi"})
    assert [row["prompt_tokens"] for row in result["usage_ledger"]] == [11, 13]
    assert result["user_message"] == "hi"


# --------------------------------------------------------------------------
# H4 — tool schemas survive the redaction whitelist
# --------------------------------------------------------------------------


def test_safe_final_model_input_forwards_tool_schema():
    safe = _safe_final_model_input(
        {
            "messages": [{"role": "system", "content": "hi", "bytes": 2}],
            "tool_schema": {
                "final_model_tools": ["read_file", "patch"],
                "tool_count": 2,
                "json_bytes": TOOL_JSON_BYTES,
            },
        }
    )

    assert safe["tool_schema"]["json_bytes"] == TOOL_JSON_BYTES
    assert safe["tool_schema"]["final_model_tools"] == ["read_file", "patch"]
    assert safe["tool_schema"]["tool_count"] == 2


def test_safe_final_model_input_without_tool_schema_is_none_not_a_crash():
    safe = _safe_final_model_input({"messages": [{"role": "user", "content": "x", "bytes": 1}]})

    assert safe["tool_schema"] is None


def test_safe_final_model_input_whitelists_only_cache_routing_fingerprints():
    safe = _safe_final_model_input(
        {
            "messages": [],
            "cache_routing": {
                "schema_version": 1,
                "backend": "openai_codex",
                "prompt_cache_key_present": True,
                "prompt_cache_key_source": "static_prefix",
                "prompt_cache_key_fingerprint": f"sha256:{'a' * 64}",
                "cache_scope_source": "cache_scope_id",
                "session_header_present": True,
                "session_header_fingerprint": f"sha256:{'b' * 64}",
                "client_request_header_present": True,
                "client_request_header_fingerprint": f"sha256:{'b' * 64}",
                "scope_headers_match": True,
                "raw_values_omitted": False,
                "raw_session_id": "must-not-survive",
            },
        }
    )

    routing = safe["cache_routing"]
    assert routing["prompt_cache_key_fingerprint"] == f"sha256:{'a' * 64}"
    assert routing["session_header_fingerprint"] == f"sha256:{'b' * 64}"
    assert routing["raw_values_omitted"] is True
    assert "raw_session_id" not in routing


def test_safe_final_model_input_rejects_untyped_cache_fingerprints():
    safe = _safe_final_model_input(
        {
            "messages": [],
            "cache_routing": {
                "prompt_cache_key_fingerprint": "raw-cache-key",
                "session_header_fingerprint": "private-session",
            },
        }
    )

    assert safe["cache_routing"]["prompt_cache_key_fingerprint"] is None
    assert safe["cache_routing"]["session_header_fingerprint"] is None


# --------------------------------------------------------------------------
# H5 — the basis matrix
# --------------------------------------------------------------------------


def test_metered_first_call_wins_over_the_estimate_and_reports_drift():
    budget = _context_budget(
        MODEL_SELECTION,
        FINAL_INPUT_WITH_TOOLS,
        {"api_calls": 14, "prompt_tokens": 801_373, "first_call_prompt_tokens": 42_733},
    )

    assert budget["used_tokens"] == 42_733
    assert budget["used_basis"] == BUDGET_BASIS_METERED_FIRST_CALL
    assert budget["used_estimated"] is False
    assert budget["estimate_tokens"] == (MESSAGE_BYTES + TOOL_JSON_BYTES) // 4
    assert budget["estimate_drift_ratio"] == round(42_733 / budget["estimate_tokens"], 2)
    # The turn burned 801K across 14 calls; the CONTEXT was 42.7K. The budget
    # bar must never show the burn.
    assert budget["used_tokens"] < 801_373


def test_single_call_turn_total_is_its_first_call():
    budget = _context_budget(MODEL_SELECTION, FINAL_INPUT_WITH_TOOLS, {"api_calls": 1, "prompt_tokens": 55_000})

    assert budget["used_tokens"] == 55_000
    assert budget["used_basis"] == BUDGET_BASIS_METERED_FIRST_CALL


def test_multi_call_turn_without_a_ledger_stays_on_the_estimate():
    """The cumulative total of a multi-call turn is NOT the context size."""
    budget = _context_budget(MODEL_SELECTION, FINAL_INPUT_WITH_TOOLS, {"api_calls": 5, "prompt_tokens": 300_000})

    assert budget["used_basis"] == BUDGET_BASIS_ESTIMATE_WITH_TOOLS
    assert budget["used_tokens"] != 300_000


def test_estimate_counts_tool_schema_bytes_when_no_call_has_completed():
    budget = _context_budget(MODEL_SELECTION, FINAL_INPUT_WITH_TOOLS, None)

    assert budget["used_basis"] == BUDGET_BASIS_ESTIMATE_WITH_TOOLS
    assert budget["used_tokens"] == (MESSAGE_BYTES + TOOL_JSON_BYTES) // 4
    assert budget["used_estimated"] is True
    assert "estimate_drift_ratio" not in budget


def test_estimate_without_tool_schema_is_labeled_messages_only():
    """The old behavior, now named: this is the number that read ~4x low."""
    budget = _context_budget(MODEL_SELECTION, FINAL_INPUT_NO_TOOLS, None)

    assert budget["used_basis"] == BUDGET_BASIS_ESTIMATE_MESSAGES_ONLY
    assert budget["used_tokens"] == MESSAGE_BYTES // 4
    assert budget["used_estimated"] is True


@pytest.mark.parametrize(
    "turn_usage, expected_estimated",
    [
        ({"api_calls": 1, "prompt_tokens": 55_000}, False),
        (None, True),
    ],
)
def test_used_estimated_bool_mirrors_the_basis(turn_usage, expected_estimated):
    """Legacy launchers read the bool; it must never disagree with the enum."""
    budget = _context_budget(MODEL_SELECTION, FINAL_INPUT_WITH_TOOLS, turn_usage)

    assert budget["used_estimated"] is expected_estimated
    assert budget["used_estimated"] == (budget["used_basis"] != BUDGET_BASIS_METERED_FIRST_CALL)


def test_budget_is_none_when_the_window_cannot_be_resolved():
    assert _context_budget({"effective_model": ""}, FINAL_INPUT_WITH_TOOLS, None) is None


def test_metered_budget_is_never_refreshed_back_to_an_estimate():
    metered = {
        "context_budget": _context_budget(
            MODEL_SELECTION, FINAL_INPUT_WITH_TOOLS, {"api_calls": 2, "first_call_prompt_tokens": 42_733}
        ),
        "final_model_input": FINAL_INPUT_WITH_TOOLS,
    }
    legacy = {"context_budget": {"window_tokens": 200_000, "used_tokens": None}, "final_model_input": FINAL_INPUT_WITH_TOOLS}

    assert _context_budget_needs_refresh(metered) is False
    assert _context_budget_needs_refresh(legacy) is True


# --------------------------------------------------------------------------
# H5/H6 — turn_usage envelope block
# --------------------------------------------------------------------------


def test_safe_turn_usage_whitelists_and_coerces():
    safe = _safe_turn_usage(
        {"api_calls": 2, "prompt_tokens": 85_515, "cache_read_tokens": 81_920, "secret": "nope"}
    )

    assert safe["api_calls"] == 2
    assert safe["prompt_tokens"] == 85_515
    assert "secret" not in safe


def test_safe_turn_usage_empty_inputs_are_none():
    assert _safe_turn_usage(None) is None
    assert _safe_turn_usage({"unrelated": 1}) is None


def test_turn_usage_from_result_reads_first_ledger_row_and_sums():
    class _Result:
        api_calls = 14
        input_tokens = 50_781
        output_tokens = 2_360
        cache_read_tokens = 750_592
        cache_write_tokens = 0
        reasoning_tokens = 702
        usage_ledger = [
            {"call_index": 1, "prompt_tokens": 42_733},
            {"call_index": 2, "prompt_tokens": 60_000},
        ]

    usage = turn_usage_from_result(_Result())

    assert usage["first_call_prompt_tokens"] == 42_733
    assert usage["api_calls"] == 14
    # prompt = input + cache_read + cache_write, per CanonicalUsage.
    assert usage["prompt_tokens"] == 50_781 + 750_592
    assert usage["input_tokens"] == 50_781


def test_turn_usage_from_result_without_a_ledger_still_reports_sums():
    class _Result:
        api_calls = 2
        input_tokens = 3_595
        output_tokens = 394
        cache_read_tokens = 81_920
        cache_write_tokens = 0
        reasoning_tokens = 268
        usage_ledger = []

    usage = turn_usage_from_result(_Result())

    assert usage["first_call_prompt_tokens"] is None
    assert usage["prompt_tokens"] == 85_515


def test_turn_usage_from_result_is_none_for_a_turn_that_never_ran():
    class _Empty:
        api_calls = None
        input_tokens = None
        output_tokens = None
        cache_read_tokens = None
        cache_write_tokens = None
        reasoning_tokens = None
        usage_ledger = []

    assert turn_usage_from_result(_Empty()) is None
    assert turn_usage_from_result(None) is None


def test_persona_commands_binds_turn_usage_from_result():
    """The mission-chat turn resolves ``turn_usage_from_result`` in its OWN module.

    ``persona_commands`` is a real module since lane H1 (2026-09-24), so the
    name must be bound there — read from the runtime module, not its spelling —
    and be the one ``prompt_observability`` owns.
    """
    from agent_runtime import prompt_observability
    from hermes_cli.harness_parts import persona_commands

    assert persona_commands.turn_usage_from_result is prompt_observability.turn_usage_from_result
