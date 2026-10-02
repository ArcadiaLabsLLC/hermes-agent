"""A fresh test process supplies the existing worker lane's cold sample."""
import pytest

from tests.agent_runtime.conversation_latency_probe import (
    measure_lane, worker_read, worker_send, worker_target,
)


@pytest.mark.timeout(150)
def test_worker_first_turn_latency(record_property, monkeypatch):
    measure_lane(record_property, monkeypatch, worker_target, worker_send, worker_read)
