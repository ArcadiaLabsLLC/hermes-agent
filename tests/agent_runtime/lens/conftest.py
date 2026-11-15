"""Lens tests' shared fixture: the rules check before an investigate turn approves by default.

No Lens test calls a model. The exit door runs the monitor's rules check (``rules_check.py``,
RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE) through the smart-approval guardian, which fails closed when
no provider answers — so every door test would read ``notified_by_rules``. The guardian's one call
(``tools.approval_smart.guardian_verdict``) answers ``approve`` here; ``test_lens_rules_check.py``
binds its own answers over this.
"""

from __future__ import annotations

import pytest


class GuardianFake:
    """A guardian that answers ``answer`` and keeps every ``(system_prompt, user_prompt)`` it was asked."""

    def __init__(self, answer: str = "approve", tokens: int | None = 212) -> None:
        self.answer = answer
        self.tokens = tokens
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system_prompt: str, user_prompt: str, *, usage: dict | None = None) -> str:
        self.calls.append((system_prompt, user_prompt))
        if usage is not None:
            usage["total_tokens"] = self.tokens
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


@pytest.fixture(autouse=True)
def guardian(monkeypatch):
    import tools.approval_smart as approval_smart

    fake = GuardianFake()
    monkeypatch.setattr(approval_smart, "guardian_verdict", fake)
    return fake
