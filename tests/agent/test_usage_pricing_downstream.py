"""Fork-owned tests moved out of ``tests/agent/test_usage_pricing.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from types import SimpleNamespace
from agent.usage_pricing import (
    normalize_usage,
)


# Fork-retained (Context-Cost T4, 2026-07-18): the codex_responses metering
# branch is a live-turn path with no upstream coverage. Keep both guards.
def test_normalize_usage_codex_responses_reads_cached_from_input_tokens_details():
    """Codex Responses (``api_mode='codex_responses'``, e.g. openai-codex /
    gpt-5.6-luna) reports usage in the OpenAI *Responses* shape: ``input_tokens``
    is the FULL prompt (cached tokens included) and the cached portion is broken
    out under ``input_tokens_details.cached_tokens`` — NOT ``prompt_tokens`` /
    ``prompt_tokens_details`` (that's the Chat Completions shape).

    Regression guard for the Context-Cost T4 investigation (2026-07-18): the
    codex_responses branch of normalize_usage() was the one live-metering path
    with no unit coverage even though live turns depend on it for cache-hit
    accounting. Live frames confirmed multi-call codex turns record nonzero
    ``cache_read_tokens`` precisely because this mapping works; this test locks
    that contract so a future refactor can't silently drop it back to 0.

    Contract asserted (not a frozen snapshot): input_tokens = input_total −
    cached, cache_read = cached, and prompt_tokens (the billed bucket) =
    input_tokens + cache_read == input_total.
    """
    usage = SimpleNamespace(
        input_tokens=14822,
        output_tokens=30,
        input_tokens_details=SimpleNamespace(cached_tokens=12800),
        output_tokens_details=SimpleNamespace(reasoning_tokens=12),
        total_tokens=14852,
    )

    normalized = normalize_usage(usage, provider="openai-codex", api_mode="codex_responses")

    assert normalized.cache_read_tokens == 12800
    assert normalized.cache_write_tokens == 0
    # input_tokens = input_total - cached (the Responses total is inclusive)
    assert normalized.input_tokens == 14822 - 12800
    # prompt bucket = uncached input + cache read == the reported input total
    assert normalized.prompt_tokens == 14822
    assert normalized.output_tokens == 30
    assert normalized.reasoning_tokens == 12


def test_normalize_usage_codex_responses_ignores_chat_completions_fields():
    """The codex_responses branch must key off ``input_tokens`` /
    ``input_tokens_details``, never ``prompt_tokens`` / ``prompt_tokens_details``.

    A Responses-shape payload has no ``prompt_tokens``; if the wrong branch ran,
    prompt_total would resolve to 0 and cache_read would be missed. This proves
    the api_mode dispatch selects the Responses reader, and that a cold first
    call (no cached prefix yet — the sampled T4 frame) correctly reports 0
    cache_read without inventing one.
    """
    usage = SimpleNamespace(
        input_tokens=14822,
        output_tokens=30,
        input_tokens_details=SimpleNamespace(cached_tokens=0),
        total_tokens=14852,
    )

    normalized = normalize_usage(usage, provider="openai-codex", api_mode="codex_responses")

    assert normalized.cache_read_tokens == 0
    assert normalized.input_tokens == 14822
    assert normalized.prompt_tokens == 14822
