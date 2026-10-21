"""The dispatcher's three library contracts: SOURCE, EXECUTOR, SCHEDULER (plan §2, stage B1).

Killing mutations: ``ManualScheduler.tick`` fires a ``StartBatch`` → ``test_manual_never_fires`` red;
``Reason`` drops ``already_taken`` → ``test_reasons_cover_writer_refusals`` red.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_runtime.work import model as work_model
from agent_runtime.work_store import executor, scheduler, source
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.scheduler import (
    ManualScheduler, PersonaPrompt, StartBatch, Trigger, TriggerKind,
)
from agent_runtime.work_store.source import Claimant, Domain, domain_of

from tests.agent_runtime.work_store.contract_fakes import FakeExecutor, FakeSource, row

WORK_STORE = Path(source.__file__).parent
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
NOTE = "Harness_Brain/20 — Active Initiatives/runtime-queue.md"


def _reason_names(path: Path) -> set[str]:
    """Every ``Reason.<NAME>`` the module's AST reads."""

    return {node.attr for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "Reason"}


def test_reasons_cover_writer_refusals():
    """Every refusal the writer, engine and executor raise, and every plan §2 wire word, is one ``Reason``."""

    used = set().union(*(_reason_names(path) for path in sorted(WORK_STORE.glob("*.py"))))
    assert {"ALREADY_TAKEN", "ROW_GONE", "PUSH_CONTENDED"} <= used  # positive control: the walk sees the writer
    assert used - set(Reason.__members__) == set()
    plan_words = {
        "row_gone", "already_taken", "not_claimant", "id_exists", "push_contended", "slot_unbound", "grammar_invalid",
        "executor_busy", "persona_unavailable", "cap_reached", "drain_begun", "door_unbound", "worktree_failed",
        "schedule_invalid", "automation_off", "not_owner_machine",
    }
    assert plan_words - {r.value for r in Reason} == set()
    assert {r.value for r in source.REFUSALS | executor.REFUSALS | scheduler.REFUSALS} >= plan_words


def test_old_work_reasons_kept_and_re_exported():
    assert work_model.Reason is Reason
    assert [r.value for r in list(Reason)[:6]] == [
        "invalid_request", "work_owner_changed", "work_unavailable", "idempotency_conflict", "scope_denied",
        "work_outcome_unknown"]


def test_manual_never_fires():
    sched = ManualScheduler(owner_machine="m1")
    sched.arm("nightly", Trigger.manual(), StartBatch("ws", "plan-1"))
    for minutes in (0, 1, 60, 60 * 24 * 365):
        at = NOW + timedelta(minutes=minutes)
        assert sched.due(at) == []
        assert sched.tick(at) == []
    assert [a.key for a in sched.armed()] == ["nightly"]
    assert sched.armed()[0].next_fire is None


def test_manual_arm_joins_by_key_and_disarms():
    sched = ManualScheduler()
    first = sched.arm("k", Trigger.manual(), StartBatch("ws", "p1"))
    assert sched.arm("k", Trigger.manual(), PersonaPrompt("inst", "hi")) is first
    assert sched.disarm("k") is True
    assert sched.disarm("k") is False
    assert sched.armed() == []


@pytest.mark.parametrize("trigger", [Trigger.every(5), Trigger.at_utc(NOW), Trigger.cron("0 3 * * *"),
                                     Trigger.when_idle("root-1")])
def test_manual_refuses_timed_triggers(trigger):
    with pytest.raises(WorkRefused) as refused:
        ManualScheduler().arm("k", trigger, StartBatch("ws", "p"))
    assert refused.value.reason is Reason.NOT_BUILT


@pytest.mark.parametrize("build", [
    lambda: Trigger.every(0),
    lambda: Trigger.at_utc(datetime(2026, 10, 18, 12)),  # naive
    lambda: Trigger.cron("* *"),
    lambda: Trigger.cron("0 3 * * *", tz="Mars/Olympus"),
    lambda: Trigger.when_idle(""),
    lambda: Trigger(TriggerKind.WHEN_IDLE, root="r", settle_ticks=0),
])
def test_malformed_trigger_is_schedule_invalid(build):
    with pytest.raises(WorkRefused) as refused:
        build()
    assert refused.value.reason is Reason.SCHEDULE_INVALID


def test_bad_key_is_schedule_invalid():
    with pytest.raises(WorkRefused) as refused:
        ManualScheduler().arm("../escape", Trigger.manual(), StartBatch("ws", "p"))
    assert refused.value.reason is Reason.SCHEDULE_INVALID


def _public(protocol: type) -> dict[str, inspect.Signature]:
    return {name: inspect.signature(fn) for name, fn in vars(protocol).items()
            if callable(fn) and not name.startswith("_")}


@pytest.mark.parametrize(("protocol", "impl"), [
    (source.WorkSource, FakeSource),
    (executor.Executor, FakeExecutor),
    (executor.Executor, PersonaTurnExecutor),
    (scheduler.Scheduler, ManualScheduler),
])
def test_fakes_and_production_match_the_contracts(protocol, impl):
    """Each implementation carries every contract method with the contract's parameter names and kinds."""

    expected = _public(protocol)
    assert expected, "positive control: the protocol has methods"
    for name, sig in expected.items():
        got = inspect.signature(getattr(impl, name))
        assert [(p.name, p.kind) for p in got.parameters.values()] == \
            [(p.name, p.kind) for p in sig.parameters.values()], name


def test_domain_is_the_batching_key():
    a, b = row("hermes", NOTE, "RT-A", heading="Fork-owned"), row("hermes", NOTE, "RT-B", heading="Fork-owned")
    c = row("hermes", NOTE, "RT-C", heading="Seams")
    assert domain_of(a) == domain_of(b) == Domain("hermes", NOTE, "Fork-owned")
    assert domain_of(c) != domain_of(a)


def test_fake_source_refuses_like_the_writer():
    src = FakeSource([row("hermes", NOTE, "RT-A")])
    ref = src.ready("ws")[0].ref
    persona, other = Claimant.persona("inst-1"), Claimant.persona("inst-2")
    assert persona.persona_instance_id == "inst-1" and Claimant.operator().persona_instance_id is None
    assert src.claim(ref, persona, "r1").kind == "work.row_claim"
    assert src.ready("ws") == []
    for call, reason in [(lambda: src.claim(ref, other, "r2"), Reason.ALREADY_TAKEN),
                         (lambda: src.done(ref, other, "x"), Reason.NOT_CLAIMANT)]:
        with pytest.raises(WorkRefused) as refused:
            call()
        assert refused.value.reason is reason
    assert src.done(ref, persona, "shipped").kind == "work.row_delete"
    with pytest.raises(WorkRefused) as gone:
        src.claim(ref, persona, "r3")
    assert gone.value.reason is Reason.ROW_GONE
