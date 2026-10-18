"""The isolated-compute host of the real delegate_task child reads, in its own file.

Each case boots a real worker, a compute host and two real agents; the six cases in one
file serialized ~70 s of engine CPU on one gate worker.
"""
import pytest

from tests.agent_runtime.test_subagent_native_roundtrip import run_owned_child_reads

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize("mode", ["isolated-compute"])
@pytest.mark.parametrize("action", ["steer", "stop"])
def test_owned_child_reads_across_execution_hosts(tmp_path, mode, action):
    run_owned_child_reads(tmp_path, mode, action)
