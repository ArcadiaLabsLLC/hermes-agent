"""Fork half of ``test_cron_kanban_env_isolation`` (h10b-fix, owner 2026-09-29).

The harness plugin adds exactly one kanban env key, ``HERMES_KANBAN_CLAIM_TTL_SECONDS``, as a
default: the worker identity keys upstream isolates are never touched, and an operator value wins.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_kanban_ttl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _kanban_env():
    return {k: v for k, v in os.environ.items() if k.startswith("HERMES_KANBAN_")}


def test_the_default_adds_only_the_claim_ttl(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_CLAIM_TTL_SECONDS", raising=False)
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_worker")
    before = _kanban_env()
    plugin = _plugin()
    plugin.default_kanban_claim_ttl()
    assert _kanban_env() == {**before, "HERMES_KANBAN_CLAIM_TTL_SECONDS": str(plugin.KANBAN_CLAIM_TTL_SECONDS)}


def test_the_operator_ttl_wins(monkeypatch):
    """Positive control: same call, operator value already set -> env unchanged."""
    monkeypatch.setenv("HERMES_KANBAN_CLAIM_TTL_SECONDS", "60")
    before = _kanban_env()
    _plugin().default_kanban_claim_ttl()
    assert _kanban_env() == before
