"""Fork half of ``test_cron_kanban_env_isolation`` (h10b-fix, owner 2026-09-29; v0216 plan §2).

The harness's process-env defaults add exactly ``HERMES_KANBAN_CLAIM_TTL_SECONDS`` and
``HERMES_DISABLE_LAZY_INSTALLS``, applied by the fork's process composers (never plugin code):
the worker identity keys upstream isolates are never touched, and an operator value wins.
"""

from __future__ import annotations

from hermes_cli import kanban_db

from agent_runtime.process_env_defaults import (
    KANBAN_CLAIM_TTL_SECONDS,
    apply_harness_process_env_defaults,
)

_TTL = "HERMES_KANBAN_CLAIM_TTL_SECONDS"
_LAZY = "HERMES_DISABLE_LAZY_INSTALLS"


def test_the_defaults_add_exactly_the_two_keys():
    env = {"HERMES_KANBAN_TASK": "t_worker", "PATH": "x"}
    written = apply_harness_process_env_defaults(env)
    assert set(written) == {_TTL, _LAZY}
    assert env == {"HERMES_KANBAN_TASK": "t_worker", "PATH": "x",
                   _TTL: str(KANBAN_CLAIM_TTL_SECONDS), _LAZY: "1"}


def test_the_operator_ttl_wins():
    """Positive control: the operator's TTL is already set -> only the other key is added."""
    env = {_TTL: "60"}
    assert apply_harness_process_env_defaults(env) == (_LAZY,)
    assert env == {_TTL: "60", _LAZY: "1"}


def test_upstream_reads_the_applied_ttl(monkeypatch):
    monkeypatch.delenv(_TTL, raising=False)
    apply_harness_process_env_defaults()
    assert kanban_db._resolve_claim_ttl_seconds() == KANBAN_CLAIM_TTL_SECONDS
    monkeypatch.setenv(_TTL, "60")
    apply_harness_process_env_defaults()
    assert kanban_db._resolve_claim_ttl_seconds() == 60
