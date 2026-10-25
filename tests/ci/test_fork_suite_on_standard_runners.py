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
