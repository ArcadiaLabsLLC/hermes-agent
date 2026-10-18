"""``Trigger.from_cron_job`` — the one door from upstream's cron job record (dispatcher plan §4, B4).

Killing mutation: ``from_cron_job`` drops the zone (``Trigger.cron(expr)``) →
``test_cron_job_keeps_its_zone`` red. Also guarded: nothing in the fork's scheduler imports upstream's
cron runner (a resolved-import read, not a spelling).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest

from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.scheduler import Trigger, TriggerKind


def test_once_is_at_in_utc():
    job = {"schedule": {"kind": "once", "run_at": "2026-10-18T09:00:00+05:30"}}
    trigger = Trigger.from_cron_job(job)
    assert trigger.kind is TriggerKind.AT
    assert trigger.at == datetime(2026, 10, 18, 3, 30, tzinfo=UTC)


def test_a_naive_run_at_is_read_in_the_jobs_zone():
    job = {"schedule": {"kind": "once", "run_at": "2026-10-18T09:00:00"}}
    trigger = Trigger.from_cron_job(job, tz="Asia/Kolkata")
    assert trigger.at.astimezone(timezone(timedelta(hours=5, minutes=30))).hour == 9


def test_interval_is_every():
    trigger = Trigger.from_cron_job({"schedule": {"kind": "interval", "minutes": 45, "display": "every 45m"}})
    assert (trigger.kind, trigger.minutes) == (TriggerKind.EVERY, 45)


def test_cron_job_keeps_its_zone():
    job = {"schedule": {"kind": "cron", "expr": "0  9 * * 1-5", "display": "0 9 * * 1-5"}}
    assert Trigger.from_cron_job(job, tz="Europe/London") == Trigger.cron("0 9 * * 1-5", "Europe/London")
    assert Trigger.from_cron_job({**job, "tz": "Asia/Tokyo"}, tz="Europe/London").tz == "Asia/Tokyo"


@pytest.mark.parametrize("job", [
    {}, {"schedule": None}, {"schedule": {"kind": "monitor"}}, {"schedule": {"kind": "interval"}},
    {"schedule": {"kind": "once", "run_at": "soon"}}, {"schedule": {"kind": "cron", "expr": "0 9"}},
])
def test_an_unreadable_job_is_schedule_invalid(job):
    with pytest.raises(WorkRefused) as refused:
        Trigger.from_cron_job(job)
    assert refused.value.reason is Reason.SCHEDULE_INVALID


def test_the_fork_scheduler_never_imports_upstreams_cron_runner():
    """Positive read of the RESOLVED import graph in a fresh interpreter: importing the scheduler, its verbs and its tool loads no ``cron.*``."""

    code = (
        "import sys\n"
        "from agent_runtime.work_store import schedule_ops, serve_scheduler, schedule_tool\n"
        "print(sorted(m for m in sys.modules if m == 'cron' or m.startswith('cron.')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True)
    assert out.stdout.strip().splitlines()[-1] == "[]", out.stdout
