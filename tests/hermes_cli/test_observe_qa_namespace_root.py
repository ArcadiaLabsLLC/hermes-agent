"""``hermes harness observe … --qa-namespace-root``: the read verbs read a QA lane namespace's folder.

RT-OBSERVE-QA-LANE-NAMESPACE-REFUSED: ``--namespace stagec-*`` from outside the launcher is refused, so a
perf recipe on a QA serve had no observe read. The verbs take the lane's folder instead, resolve no
namespace and read only its head home's agent.log and its agent-runtime store. Every path is under
``tmp_path``; nothing reads the operator's root.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from hermes_cli.harness_parts import observe_commands


@pytest.fixture
def lane(tmp_path: Path) -> Path:
    root = tmp_path / "qa" / "hermes-namespaces" / "stagec-smoke-lane-0123456789"
    logs = root / "profiles" / "base" / "logs"
    logs.mkdir(parents=True)
    (logs / "agent.log").write_text("", encoding="utf-8")
    (root / "agent-runtime").mkdir()
    return root


@pytest.fixture(autouse=True)
def _no_process_store(monkeypatch):
    """The lane's read must never fall back to this process's own store root."""
    from agent_runtime import paths

    def refuse():
        raise AssertionError("observe read this process's store root")

    monkeypatch.setattr(paths, "store_root", refuse)


def test_snapshot_builds_reads_the_lanes_agent_log(lane: Path, capsys):
    args = Namespace(since="1h", log=None, qa_namespace_root=str(lane), json=True)
    assert observe_commands._cmd_observe_snapshot_builds(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["window"]["files"] == [str(lane / "profiles" / "base" / "logs" / "agent.log")]
    assert report["home"] == {"path": str(lane / "profiles" / "base"), "source": "--qa-namespace-root"}


def test_turn_timing_reads_the_lanes_store_and_log(lane: Path, monkeypatch, capsys):
    from agent_runtime import turn_timing_census

    seen = {}

    def census(*, store_root, log, launcher_log, baseline, since):
        seen.update(store_root=store_root, log=log)
        return {"turns": [], "baseline": {}}

    monkeypatch.setattr(turn_timing_census, "census_turn_timing", census)
    args = Namespace(since="1h", log=None, launcher_log=None, baseline=None, qa_namespace_root=str(lane),
                     json=True, check=False)
    assert observe_commands._cmd_observe_turn_timing(args) == 0
    assert seen == {"store_root": lane / "agent-runtime", "log": lane / "profiles" / "base" / "logs" / "agent.log"}
    assert json.loads(capsys.readouterr().out)["home"]["source"] == "--qa-namespace-root"


@pytest.mark.parametrize("name", ["acct-0123456789abcdef", "qa", "base"])
def test_only_a_qa_lane_namespace_folder_is_read(tmp_path: Path, name: str, capsys):
    folder = tmp_path / "hermes-namespaces" / name
    folder.mkdir(parents=True)
    args = Namespace(since="1h", log=None, qa_namespace_root=str(folder), json=True)
    assert observe_commands._cmd_observe_snapshot_builds(args) == 2
    assert "QA lane namespace" in capsys.readouterr().err


def test_a_missing_folder_is_refused(tmp_path: Path):
    with pytest.raises(ValueError):
        observe_commands.qa_namespace_paths(str(tmp_path / "stagec-smoke-gone"))
    assert observe_commands.qa_namespace_paths(None) is None
