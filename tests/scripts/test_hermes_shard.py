"""Fast-gate §3 stage 1 — ``--hermes-shard=i/k`` splits a file by node id.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §3. A
throwaway file of 12 tests (4 of them one parametrised function) is collected
under ``0/3``, ``1/3`` and ``2/3`` in a child pytest: every node lands in
exactly one shard, and no shard holds them all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "scripts" / "_bundle_plugin"

_TWELVE = "\n".join(
    [f"def test_plain_{n}():\n    pass\n" for n in range(8)]
    + ["import pytest\n", "@pytest.mark.parametrize('x', [1, 2, 3, 4])\ndef test_param(x):\n    pass\n"]
)


def _collect(root: Path, *extra: str) -> tuple[int, list[str]]:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"  # the child loads only what it is told to
    env["PYTHONPATH"] = os.pathsep.join([str(_PLUGIN_DIR), env.get("PYTHONPATH", "")])
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-p", "hermes_shard", *extra, "test_twelve.py"],
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    return proc.returncode, [line.strip() for line in proc.stdout.splitlines() if "::" in line]


@pytest.fixture
def twelve(tmp_path: Path) -> Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_twelve.py").write_text(_TWELVE, encoding="utf-8")
    return tmp_path


@pytest.mark.timeout(120)  # four child pytest processes
def test_every_node_lands_in_exactly_one_shard_and_no_shard_holds_them_all(twelve):
    _rc, every = _collect(twelve)
    shards = [_collect(twelve, f"--hermes-shard={i}/3")[1] for i in range(3)]

    assert len(every) == 12 and any("[3]" in node for node in every)
    flat = [node for shard in shards for node in shard]
    assert sorted(flat) == sorted(every)  # each node once, none twice
    assert all(0 < len(shard) < len(every) for shard in shards), [len(s) for s in shards]


def test_a_bad_shard_spec_is_a_usage_error(twelve):
    rc, nodes = _collect(twelve, "--hermes-shard=3/3")

    assert rc == 4 and nodes == []
