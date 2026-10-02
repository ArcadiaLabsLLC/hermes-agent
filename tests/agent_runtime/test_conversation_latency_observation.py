"""Historical output cannot satisfy a subsequent turn's first-output clock."""
from tests.agent_runtime.conversation_latency_probe import (
    ANSWER, instance_observation, worker_observation,
)


def test_instance_first_output_excludes_previous_answer():
    state = dict(messages=[{"text": ANSWER}], active_turns=[],
                 delivery_observed=False, delivery_pending=True)
    assert instance_observation(state, "warm-1") == (False, False)
    state["active_turns"] = [{"client_message_id": "warm-1", "elements": [ANSWER]}]
    assert instance_observation(state, "warm-1") == (True, False)
    state.update(active_turns=[], messages=[{"text": ANSWER}] * 2,
                 delivery_observed=True, delivery_pending=False)
    assert instance_observation(state, "warm-1") == (True, True)


def test_worker_first_output_excludes_previous_answer():
    state = dict(events=[{"turn_id": "cold", "text": ANSWER}], turn={"state": "running"})
    assert worker_observation(state, "warm-1") == (False, False)
    state["events"].append({"turn_id": "warm-1", "text": ANSWER})
    assert worker_observation(state, "warm-1") == (True, False)
    state["turn"]["state"] = "completed"
    assert worker_observation(state, "warm-1") == (True, True)
