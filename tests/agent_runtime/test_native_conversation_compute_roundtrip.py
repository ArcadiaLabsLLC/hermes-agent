"""The compute-child half of the real native A→B→A roundtrip, in its own file.

Each case boots real workers and builds real agents (~30 s of engine CPU), so the four
cases in one file were the landing gate's critical path; a file runs on one worker.
"""
import pytest

from tests.agent_runtime.test_native_conversation_roundtrip import run_profile_a_b_a

pytestmark = [pytest.mark.timeout(120), pytest.mark.slow_native]


@pytest.mark.parametrize("compute", [True], ids=["compute-child"])
@pytest.mark.parametrize("shared", [False, True], ids=["private-provider", "shared-provider"])
def test_real_profile_a_b_a_native_turns_and_persistent_sessions(tmp_path, compute, shared):
    run_profile_a_b_a(tmp_path, compute, shared)
