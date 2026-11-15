"""The fork's suite runs on GitHub's standard runners, over the validated scope.

Upstream's ``tests.yml`` asks for runner labels the fork's organisation does not
have; a run queued on one held ``ci-refs/heads/main`` for days and cancelled every
later push (FH-CI-MAIN-LARGE-RUNNER-QUEUE). The owner ruled one fork-owned job on
standard runners (2026-10-25). Its scope is the "validated suite" block of
``docs/downstream-development.md``, enumerated from that block, not retyped here.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_runtime import yaml_io

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "fork-gates.yml"
CONTRACT = ROOT / "docs" / "downstream-development.md"
STANDARD = {"ubuntu-latest", "windows-latest", "macos-latest"}


def _job() -> dict:
    return yaml_io.load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validated-suite"]


def _validated_scope() -> list[str]:
    text = CONTRACT.read_text(encoding="utf-8")
    head = text.index("**Validated scope vs. what the runner discovers by default.**")
    block = re.search(r"```\n(.+?)\n```", text[head:], re.DOTALL)
    assert block, "the validated-scope block is gone from docs/downstream-development.md"
    return block.group(1).split()


def _runs(job: dict) -> list[str]:
    return [str(step.get("run", "")) for step in job["steps"]]


def test_the_suite_runs_only_on_standard_runners():
    job = _job()
    labels = set(job["strategy"]["matrix"]["os"])
    assert job["runs-on"] == "${{ matrix.os }}"
    assert labels and labels <= STANDARD, sorted(labels - STANDARD)


def test_the_suite_runs_the_validated_scope():
    scope = _validated_scope()
    assert scope, "the validated-scope block names no directory"
    suites = [run.split()[1:] for run in _runs(_job()) if run.startswith("scripts/run_tests.sh")]
    assert scope in suites, (scope, suites)


def test_the_suite_syncs_the_telegram_extra_and_fails_where_it_is_missing():
    """RT-MESSAGING-TESTS-NEED-THE-MESSAGING-EXTRA: the shim's stranger-before-media pin drives the real
    upstream Telegram adapter, and upstream's ``[all]`` leaves python-telegram-bot out. Killing mutations:
    drop ``--extra telegram`` from the sync, or ``HERMES_REQUIRE_TELEGRAM_EXTRA`` from the suite's env (the
    pin then skips in silence), or the name from ``scripts/fork_test_env.txt`` (``run_tests.sh``'s
    ``env -i`` then drops it) → red."""
    job = _job()
    syncs = [str(step.get("with", {}).get("command", "")) for step in job["steps"]
             if "uv sync" in str(step.get("with", {}).get("command", ""))]
    assert syncs and all("--extra telegram" in command.split("--extra all", 1)[1] for command in syncs)
    [suite] = [step for step in job["steps"] if step.get("name") == "Validated suite"]
    assert str(suite.get("env", {}).get("HERMES_REQUIRE_TELEGRAM_EXTRA")) == "1"
    forwarded = (ROOT / "scripts" / "fork_test_env.txt").read_text(encoding="utf-8").split()
    assert "HERMES_REQUIRE_TELEGRAM_EXTRA" in forwarded
    assert CONTRACT.read_text(encoding="utf-8").count("--extra parallel-web --extra telegram") == 2
