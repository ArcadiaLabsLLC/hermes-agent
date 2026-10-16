"""Run-serialization S3: the envelope and the store resolve the RUN's root, not the process env's.

Plan: ``docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md`` S3.

Two runs bound at once on two threads, both with ``export_env=False`` (nothing is
written into ``os.environ``). Each must see its own runtime root through the three
in-process readers that used to key on the raw env var: the harness safety block's
activation, the envelope's audit-root ladder, and ``paths.store_root()``.

Kill-mutation: make ``terminal_policy._harness_safety_block`` read
``os.getenv("HERMES_AGENT_RUNTIME_ROOT")`` again. With the root bound only in the
context the block never activates and ``git push`` is waved through on both runs.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from agent_runtime.profile_context import PersonaProfileBinding, persona_profile_context


def _binding(tmp_path: Path, name: str) -> PersonaProfileBinding:
    home = tmp_path / "profiles" / name
    (home / "home").mkdir(parents=True)
    return PersonaProfileBinding(
        persona_id=f"persona_{name}", hermes_profile=name, profile_home=home,
        readiness="ready", summary="profile exists",
    )


@pytest.fixture
def no_process_root(monkeypatch):
    monkeypatch.delenv("HERMES_AGENT_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("HERMES_REQUIRE_ISOLATED_ROOT", raising=False)


def test_two_overlapping_runs_each_resolve_their_own_root(tmp_path, no_process_root):
    from agent_runtime.paths import store_root
    from agent_runtime.terminal_envelope.receipts import _audit_root, audit_root_source
    from agent_runtime.terminal_policy import _harness_safety_block

    both_inside = threading.Barrier(2, timeout=30)
    seen: dict[str, dict[str, object]] = {}
    errors: list[BaseException] = []

    def run(name: str) -> None:
        try:
            root = tmp_path / f"root-{name}"
            with persona_profile_context(_binding(tmp_path, name), runtime_root=root, export_env=False):
                both_inside.wait()
                view = {
                    "block": _harness_safety_block("git push origin main"),
                    "audit_root": _audit_root(None),
                    "audit_source": audit_root_source(None),
                    "store_root": store_root(),
                }
                both_inside.wait()
            seen[name] = view
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in ("alpha", "beta")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors
    for name in ("alpha", "beta"):
        root = tmp_path / f"root-{name}"
        assert seen[name]["block"] == "git_push_requires_operator_approval", seen[name]
        assert seen[name]["audit_root"] == root, seen[name]
        assert seen[name]["audit_source"] == "env", seen[name]
        assert seen[name]["store_root"] == root, seen[name]
    assert "HERMES_AGENT_RUNTIME_ROOT" not in os.environ


def test_with_no_root_anywhere_the_legacy_block_stays_inert(no_process_root):
    """Positive control for the block's activation arm: no bound root, no env root, no block."""

    from agent_runtime.terminal_policy import _harness_safety_block

    assert _harness_safety_block("git push origin main") is None
