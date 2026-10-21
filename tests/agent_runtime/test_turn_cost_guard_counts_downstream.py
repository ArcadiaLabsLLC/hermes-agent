"""FORK-LAZY-IMPORT-TURN-COST-CLASS: the turn-cost guard's COUNTS run on every landing gate.

``test_turn_cost_guard_downstream.py`` is idle-box only (its span budgets are absolute, owner
ruling 2026-10-10), so its count checks -- above all the "no module imported between
``agent_ready`` and ``request_sent``" check -- ran on the idle box alone, and four lazy imports
reached the turn path before one was caught. This file runs the same scenario (``_run_guard``)
and asserts only its ``violations``: counts, which do not move with box load. It is NOT on
``scripts/test_idle_box_files.txt``.

Killing mutation (recorded in the CHANGE commit): a new lazy import on the turn path.
"""

from __future__ import annotations

import pytest

from tests.agent_runtime.test_stream_turn_section import home  # (a fixture)
from tests.agent_runtime.test_turn_cost_guard_downstream import _run_guard


@pytest.mark.timeout(240)
def test_a_new_chat_and_three_turns_keep_the_turn_cost_guard_counts(
    monkeypatch, capsys, isolate_agent_runtime_root, home
):
    violations, _budgets, _spans = _run_guard(monkeypatch, capsys)
    assert not violations, "turn-cost guard (counts):\n  " + "\n  ".join(violations)
