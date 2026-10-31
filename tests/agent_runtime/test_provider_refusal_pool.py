"""RT-SINGLE-CREDENTIAL-REFUSAL-NOT-POOLED: a provider refusal reaches the credential pool.

The guarantee lives at the JOIN — a refusal raised by the runner, read back by the
provider probe — so the end-to-end cases drive ``ProfileAgentRunner`` and then ask
``_credential_health`` over a freshly loaded pool, the probe's own read.
"""

from __future__ import annotations

import time

import pytest

from agent.credential_pool import CredentialPool, PooledCredential, load_pool
from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner, ProfileRunnerError
from agent_runtime.provider_refusal_pool import record_provider_refusal, refused_entry
from hermes_cli.auth import write_credential_pool
from hermes_cli.harness_parts.provider_visibility import _credential_health

PROVIDER = "huggingface"
#: The live 2026-10-30 shape: HuggingFace's usage limit, reset given as a delta.
LIVE_BLOCK = {
    "status_code": 429,
    "reason": "usage_limit_reached",
    "message": "The usage limit has been reached",
    "provider": PROVIDER,
    "model": "moonshotai/Kimi-K2-Instruct",
    "failure_reason": "rate_limit",
    "reset_at": 7200,
}


def _seed(keys: list[str]) -> CredentialPool:
    rows = [
        PooledCredential(
            provider=PROVIDER, id=f"row{i}", label=f"key{i}", source="manual",
            auth_type="api_key", access_token=key, priority=i,
        )
        for i, key in enumerate(keys)
    ]
    write_credential_pool(PROVIDER, [row.to_dict() for row in rows])
    return CredentialPool(PROVIDER, rows)


def _health(entry_id: str) -> dict:
    entry = next(e for e in load_pool(PROVIDER).entries() if e.id == entry_id)
    return _credential_health(entry)


class _RefusingAgent:
    api_key = None

    def __init__(self, **kwargs):
        self.session_id = "session_fake"
        self.provider = kwargs.get("provider")
        self.model = kwargs.get("model")
        self.base_url = "https://router.huggingface.co/v1"
        self.tools = []

    def run_conversation(self, user_message, system_message=None, task_id=None):
        return {
            "final_response": None, "messages": [], "provider": PROVIDER,
            "model": LIVE_BLOCK["model"], "completed": False, "failed": True,
            "error": "HTTP 429: The usage limit has been reached",
            "provider_error": dict(_RefusingAgent.block),
        }

    block = LIVE_BLOCK


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(
        "agent_runtime.profile_runner.execute.resolve_runtime_provider",
        lambda requested, target_model: {"provider": requested, "model": target_model, "api_mode": "chat_completions"},
    )
    _RefusingAgent.block = LIVE_BLOCK
    return ProfileAgentRunner(agent_factory=_RefusingAgent)


def _run(runner) -> None:
    with pytest.raises(ProfileRunnerError, match="usage limit"):
        runner.run(AgentRunRequest(profile=None, provider=PROVIDER, user_message="hi"))


def test_a_single_credential_refusal_makes_the_probe_say_so(runner):
    _seed(["hf-only-key"])
    assert _health("row0") == {"state": "healthy"}
    before = time.time()

    _run(runner)

    health = _health("row0")
    assert health["state"] == "rate_limited"
    assert health["code"] == 429
    assert health["reason"] == "usage_limit_reached"
    # The provider's own reset, made absolute — not the pool's sole-credential default.
    assert before + 7200 - 5 <= health["retry_at"] <= time.time() + 7200 + 5


def test_positive_control_a_model_level_refusal_leaves_the_key_healthy(runner):
    """Same bytes, one variable: a 404 is about the model, never the key."""

    _seed(["hf-only-key"])
    _RefusingAgent.block = {**LIVE_BLOCK, "status_code": 404}

    _run(runner)

    assert _health("row0") == {"state": "healthy"}


def test_the_dispatched_key_names_the_entry_and_spares_its_sibling():
    pool = _seed(["key-a", "key-b"])

    class Agent:
        api_key = "key-b"
        _credential_pool = pool

    marked = record_provider_refusal(ProfileRunnerError("x", provider_error=LIVE_BLOCK), agent=Agent())

    assert marked == "row1"
    assert _health("row1")["state"] == "rate_limited"
    assert _health("row0") == {"state": "healthy"}


def test_several_keys_and_no_dispatched_key_is_a_guess_and_marks_nothing():
    _seed(["key-a", "key-b"])

    assert record_provider_refusal(ProfileRunnerError("x", provider_error=LIVE_BLOCK)) is None
    assert _health("row0") == {"state": "healthy"}
    assert _health("row1") == {"state": "healthy"}


def test_one_key_behind_two_entries_is_still_one_key():
    pool = _seed(["same", "same"])

    assert refused_entry(pool, None).id == "row0"


def test_a_dispatched_key_outside_the_pool_marks_nothing():
    pool = _seed(["hf-only-key"])

    assert refused_entry(pool, "a-key-from-somewhere-else") is None


def test_a_harness_authored_unavailable_block_is_not_a_credential_fact():
    _seed(["hf-only-key"])
    block = {"status_code": 0, "reason": "provider_unavailable", "provider": PROVIDER}

    assert record_provider_refusal(ProfileRunnerError("x", provider_error=block)) is None
    assert _health("row0") == {"state": "healthy"}
