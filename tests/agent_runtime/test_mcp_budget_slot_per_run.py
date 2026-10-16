"""Run-serialization S5: two concurrent runs of one MCP scope each spend THEIR OWN budget.

Before S5 ``_WORKDIR_LOCK`` serialized runs, so one binding per resident scope was enough.
Now two roots of one persona can run at once over the same ``(home, server)`` scope: a
second run's bind must not take over the first run's calls, and the first run's release
must not strip the second of its budget.

Kill-mutation: make ``BudgetSlot.current`` ignore ``_RUN_CALL_BUDGET`` and return the most
recent binding. Run A's call is then charged to run B's budget, and the test reds.
"""

from __future__ import annotations

import contextvars
import threading

from agent_runtime.mcp_admission.resident import BudgetSlot, run_call_budget_scope


class _Budget:
    def __init__(self, name: str) -> None:
        self.name = name


def test_each_run_reads_its_own_binding_from_its_own_thread():
    slot = BudgetSlot()
    a, b = _Budget("a"), _Budget("b")
    slot.bind(a, None)
    slot.bind(b, None)  # B bound last: the pre-S5 slot would hand every call B's budget
    seen: dict[str, object] = {}

    def tool_thread(name: str, budget: _Budget) -> None:
        with run_call_budget_scope(budget):
            # A tool thread started by the run inherits the run's context.
            ctx = contextvars.copy_context()
            worker = threading.Thread(target=lambda: seen.__setitem__(name, ctx.run(slot.current)[0]))
            worker.start()
            worker.join(10)

    for name, budget in (("a", a), ("b", b)):
        tool_thread(name, budget)
    assert seen == {"a": a, "b": b}


def test_a_run_that_bound_nothing_is_refused_and_an_unnamed_context_gets_the_latest():
    slot = BudgetSlot()
    a, stranger = _Budget("a"), _Budget("stranger")
    slot.bind(a, None)
    with run_call_budget_scope(stranger):
        assert slot.current() == (None, None)
    assert slot.current()[0] is a  # a thread that names no run: the single-run behaviour


def test_one_runs_release_keeps_the_other_runs_binding():
    slot = BudgetSlot()
    a, b = _Budget("a"), _Budget("b")
    slot.bind(a, None)
    slot.bind(b, None)
    slot.clear(a)
    assert slot.bound()
    with run_call_budget_scope(b):
        assert slot.current()[0] is b
    slot.clear(b)
    assert not slot.bound()
