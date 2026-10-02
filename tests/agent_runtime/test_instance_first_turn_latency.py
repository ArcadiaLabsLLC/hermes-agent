"""A fresh test process supplies the instance lane's cold sample."""
import pytest

from tests.agent_runtime.conversation_latency_probe import (
    instance_read, instance_send, instance_target, measure_lane,
)


@pytest.mark.timeout(150)
def test_instance_first_turn_latency(record_property, monkeypatch):
    measure_lane(record_property, monkeypatch, instance_target, instance_send, instance_read)
