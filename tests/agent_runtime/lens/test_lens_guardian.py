"""Lens's own safety-check layer (``agent_runtime/lens/guardian.py``, owner ruling 2026-11-14) is the one
the rules check calls, and it is the smart-approval guardian's call — same task, same request — not a
second classifier and not a seam in upstream ``tools/approval_smart.py``.

Gates and their killing mutations (each red recorded in the commit):

* the rules check reaches the model through THIS layer — killed by pointing ``rules_check`` back at
  ``tools.approval_smart.guardian_verdict`` (gone from the upstream file: the check escalates);
* the call is the guardian's: task ``approval``, temperature 0, 16 tokens, the guardian's own reasoning
  setting read through the door — killed by passing ``reasoning_config=None``;
* one word decides; empty, unknown or a raising call is ``escalate`` — killed by mapping an unknown
  word to ``approve``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.lens import guardian as lens_guardian


class _Model:
    def __init__(self, answer, tokens: int | None = 180) -> None:
        self.answer, self.tokens, self.calls = answer, tokens, []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, BaseException):
            raise self.answer
        message = SimpleNamespace(content=self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(total_tokens=self.tokens))


@pytest.fixture
def model(monkeypatch, guardian):
    import agent.auxiliary_client as auxiliary_client
    import tools.approval_smart as approval_smart

    monkeypatch.setattr(lens_guardian, "guardian_verdict", guardian.real)  # the real layer, not the fake
    monkeypatch.setattr(approval_smart, "_verdict_reasoning", lambda: {"enabled": False, "probe": 1})
    fake = _Model("APPROVE")
    monkeypatch.setattr(auxiliary_client, "call_llm", fake)
    return fake


def test_the_rules_check_reaches_the_model_through_lens_own_guardian_layer(model):
    from agent_runtime.lens.rules_check import RulesVerdict, check_investigate

    checked = check_investigate(guidance="Investigate cpu only.", monitor_name="status", fired=[],
                                turns_left_today={"monitor": 3})

    assert (checked.verdict, checked.tokens) == (RulesVerdict.APPROVE, 180)
    [call] = model.calls
    assert (call["task"], call["temperature"], call["max_tokens"]) == ("approval", 0, 16)
    assert call["reasoning_config"] == {"enabled": False, "probe": 1}  # the shell guardian's own setting
    system, user = call["messages"]
    assert system["role"] == "system" and system["content"].endswith("Investigate cpu only.")
    assert user["role"] == "user" and "<request>" in user["content"]


def test_upstream_approval_smart_carries_no_lens_seam():
    import tools.approval_smart as approval_smart

    assert not hasattr(approval_smart, "guardian_verdict")


@pytest.mark.parametrize(("answer", "verdict"), [("DENY", "deny"), (" approve\n", "approve"), ("", "escalate"),
                                                 ("MAYBE", "escalate"), (None, "escalate"),
                                                 (RuntimeError("provider down"), "escalate")])
def test_one_word_decides_and_anything_else_is_unsure(model, answer, verdict):
    model.answer = answer
    usage: dict = {}

    assert lens_guardian.guardian_verdict("s", "u", usage=usage) == verdict
    if not isinstance(answer, BaseException):
        assert usage == {"total_tokens": 180}
