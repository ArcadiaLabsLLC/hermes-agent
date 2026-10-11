"""Native checkpoint contention is typed, finite and releases its lock."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from tools.checkpoint_pruning import CheckpointStoreBusy, PruneError, store_lock


def test_default_refuses_immediately_and_finite_wait_expires(tmp_path):
    store = tmp_path / "checkpoints"
    with store_lock(store):
        with pytest.raises(CheckpointStoreBusy) as caught:
            with store_lock(store):
                pytest.fail("contending write entered")
        assert isinstance(caught.value, PruneError)
        started = time.monotonic()
        with pytest.raises(CheckpointStoreBusy):
            with store_lock(store, wait_seconds=0.1):
                pytest.fail("contending write entered")
        assert time.monotonic() - started < 3
    with store_lock(store):
        pass


def test_waiting_writer_enters_after_release_and_errors_do_not_leak_lock(tmp_path):
    store = tmp_path / "checkpoints"
    waiting = threading.Event()

    def writer():
        waiting.set()
        with store_lock(store, wait_seconds=3):
            raise ValueError("inside operation")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store_lock(store):
            future = pool.submit(writer)
            assert waiting.wait(3)
        with pytest.raises(ValueError, match="inside operation"):
            future.result(timeout=5)
    with store_lock(store):
        pass


@pytest.mark.parametrize("wait", [-1, float("inf"), float("nan")])
def test_nonfinite_or_negative_wait_is_refused_before_acquisition(tmp_path, wait):
    with pytest.raises(ValueError):
        with store_lock(tmp_path / "checkpoints", wait_seconds=wait):
            pytest.fail("invalid wait accepted")
