"""Lens tests' shared fixture: the rules check before an investigate turn approves by default.

No Lens test calls a model. The exit door runs the monitor's rules check (``rules_check.py``,
RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE) through the smart-approval guardian, which fails closed when
no provider answers — so every door test would read ``notified_by_rules``. The guardian's one call
(``agent_runtime.lens.guardian.guardian_verdict``, Lens's own safety-check layer) answers ``approve`` here; ``test_lens_rules_check.py``
binds its own answers over this.
"""

from __future__ import annotations

import pytest


class GuardianFake:
    """A guardian that answers ``answer`` (a list: one answer per call, in order) and keeps every ``(system_prompt, user_prompt)`` it was asked."""

    def __init__(self, answer: str = "approve", tokens: int | None = 212) -> None:
        self.answer = answer
        self.tokens = tokens
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system_prompt: str, user_prompt: str, *, usage: dict | None = None) -> str:
        self.calls.append((system_prompt, user_prompt))
        if usage is not None:
            usage["total_tokens"] = self.tokens
        answer = self.answer.pop(0) if isinstance(self.answer, list) else self.answer  # a list: one per call
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def guardian(monkeypatch):
    from agent_runtime.lens import guardian as lens_guardian

    fake = GuardianFake()
    fake.real = lens_guardian.guardian_verdict  # test_lens_guardian.py calls the real layer
    monkeypatch.setattr(lens_guardian, "guardian_verdict", fake)
    return fake
