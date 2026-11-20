"""``UpstreamAdapterTransport.stop`` ends every thread its loop started, the default executor's included.

``_handle`` hands each inbound message to the bridge through ``asyncio.to_thread``, which starts the loop's default
executor (``asyncio_0``); ``loop.stop`` and ``loop.close`` alone shut that executor down without waiting, so its
worker winds down after ``stop`` has returned, which the test seal reported as a leftover
(RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING, review w1118a.52 D13: the loop's owner shuts its
default executor down).

Killing mutation: drop the ``loop.shutdown_default_executor`` call from ``stop`` — the executor is only ever shut
down without a wait (red every run), and its worker is often still alive when ``stop`` returns.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from agent_runtime.messaging.upstream_adapter_transport import UpstreamAdapterTransport


class _Adapter:
    def __init__(self) -> None:
        self.config = SimpleNamespace(extra={})

    def set_message_handler(self, handler) -> None:
        pass

    def set_authorization_check(self, check) -> None:
        pass

    async def cancel_background_tasks(self) -> None:
        pass


class _RecordingExecutor(ThreadPoolExecutor):
    """The loop's default executor, recording whether each shutdown waited for its workers."""

    def __init__(self) -> None:
        super().__init__(thread_name_prefix="asyncio")
        self.waits: list[bool] = []

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.waits.append(wait)
        super().shutdown(wait=wait, cancel_futures=cancel_futures)


def _event(message_id: str) -> SimpleNamespace:
    source = SimpleNamespace(chat_id="4242", thread_id=None, user_id="7", user_name="Op")
    return SimpleNamespace(source=source, message_id=message_id, text="hi")


def test_stop_joins_the_loops_default_executor():
    workers: list[threading.Thread] = []
    transport = UpstreamAdapterTransport(_Adapter(), connect=False)
    transport.start(lambda message: workers.append(threading.current_thread()))
    executor = _RecordingExecutor()
    transport._loop.call_soon_threadsafe(transport._loop.set_default_executor, executor)
    for n in range(3):
        transport._call(transport._handle(_event(str(n))))
    assert workers and all(w is not threading.main_thread() for w in workers)

    transport.stop()

    assert True in executor.waits
    assert [w.name for w in set(workers) if w.is_alive()] == []
