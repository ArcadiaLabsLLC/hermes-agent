"""Profile worker leases. Only the last retired binding releases its process."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .model import ConversationError, Refusal

__layer__ = "lanes"


@dataclass
class Worker:
    generation: str
    home: Path
    peer: object
    leases: int = 0


class Workers:
    def __init__(self, factory, receive, lost):
        self.factory, self.receive, self.lost = factory, receive, lost
        self._lock = threading.Lock()
        self._boots = tuple(threading.Lock() for _ in range(64))
        self._workers: dict[str, Worker] = {}
        self._closed = False

    def acquire(self, profile: str, home: Path) -> Worker:
        boot = self._boots[hash(profile) % len(self._boots)]
        with boot:
            with self._lock:
                if self._closed:
                    raise ConversationError(Refusal.RUNTIME_STOPPING)
                prior = self._workers.get(profile)
            if prior is not None:
                if prior.home != home:
                    raise ConversationError(Refusal.WRONG_OWNER)
                if prior.peer.alive:
                    prior.leases += 1
                    return prior
                if prior.peer.execution_possible:
                    raise ConversationError(Refusal.UNKNOWN)
                prior.peer.close()
            generation = uuid.uuid4().hex
            peer = self.factory(home,
                receive=lambda frame: self.receive(generation, frame),
                lost=lambda: self.lost(generation))
            worker = Worker(generation, home, peer, leases=1)
            with self._lock:
                closed = self._closed
                if not closed:
                    self._workers[profile] = worker
            if closed or not peer.alive:
                peer.close()
                raise ConversationError(Refusal.WORKER_LOST)
            return worker

    def release(self, profile: str, worker: Worker) -> None:
        with self._boots[hash(profile) % len(self._boots)]:
            worker.leases -= 1
            if worker.leases:
                return
            # Keep the entry on failure: a live process must not be replaced.
            worker.peer.close()
            with self._lock:
                if self._workers.get(profile) is worker:
                    self._workers.pop(profile)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            workers = list(self._workers.values())
        errors = []
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="conversation-shutdown") as pool:
            for future in [pool.submit(worker.peer.close) for worker in workers]:
                try:
                    future.result()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise ConversationError(Refusal.WORKER_LOST) from errors[0]
