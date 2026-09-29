"""The fork's red-main notifier must watch a workflow the fork actually runs.

``fork-ci-red-notify.yml`` fires on ``workflow_run`` of the workflows it names.
Upstream's ``CI`` (``ci.yaml``) is disabled on the fork since 2026-09-26, so a
notifier watching it fires on nothing. It watches the fork's own gate workflow
(a ``fork-*.yml`` file) that runs on a push to ``main``.
"""

from __future__ import annotations

from pathlib import Path

from agent_runtime import yaml_io

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(path: Path) -> dict:
    return yaml_io.load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # A YAML 1.1 loader reads the bare key ``on`` as the boolean True.
    return workflow.get("on", workflow.get(True)) or {}


def test_the_notifier_watches_a_fork_workflow_that_runs_on_main():
    targets = _triggers(_load(WORKFLOWS / "fork-ci-red-notify.yml"))["workflow_run"]["workflows"]
    by_name = {_load(path).get("name"): path for path in sorted(WORKFLOWS.glob("*.y*ml"))}
    assert targets, "the notifier watches no workflow"
    for target in targets:
        path = by_name.get(target)
        assert path is not None, f"{target!r} names no workflow in .github/workflows"
        assert path.name.startswith("fork-"), f"{target!r} is {path.name}, not a fork-owned workflow"
        push = _triggers(_load(path)).get("push") or {}
        assert "main" in (push.get("branches") or []), f"{path.name} does not run on a push to main"
