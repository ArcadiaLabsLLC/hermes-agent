"""Disposable route bindings; native sessions decide whether retirement is safe."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

__layer__ = "lanes"
_log = logging.getLogger(__name__)


@dataclass
class _Binding:
    live: object
    touched: float
    users: int = 0


class Bindings:
    def __init__(self, attach, release, *, clock=time.monotonic, idle_seconds=900,
                 unobserved_seconds=30, budget=64):
        self._attach, self._release, self._clock = attach, release, clock
        self._idle, self._unobserved, self._budget = idle_seconds, unobserved_seconds, budget
        self._lock = threading.RLock()
        self._gates = tuple(threading.RLock() for _ in range(64))
        self._entries: dict[str, _Binding] = {}
        self._sessions: dict[tuple[str, str], object] = {}
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._maintain, daemon=True,
                                        name="conversation-retention")
        self._thread.start()

    def _gate(self, route_id):
        return self._gates[hash(route_id) % len(self._gates)]

    @contextmanager
    def borrow(self, route, *, created=False):
        with self._gate(route.id):
            with self._lock:
                entry = self._entries.get(route.id)
            if entry is not None and entry.live.retirement_pending and self._retire(entry):
                entry = None
            if entry is None or not entry.live.peer.alive:
                live = self._attach(route, created=created)
                old = entry
                with self._lock:
                    if entry is not None:
                        self._forget(entry)
                    entry = _Binding(live, self._clock())
                    self._entries[route.id] = entry
                    self._sessions[(live.worker.generation, live.native_id)] = live
                if old is not None:
                    self._release(old.live)
            with self._lock:
                entry.users += 1
                entry.touched = self._clock()
        try:
            yield entry.live
        finally:
            with self._lock:
                entry.users -= 1
                entry.touched = self._clock()

    def receive(self, generation, frame):
        params = frame.get("params") or {}
        if not isinstance(params, dict) or not isinstance(params.get("session_id"), str):
            return
        with self._lock:
            live = self._sessions.get((generation, params["session_id"]))
        if live is not None:
            live.receive(frame)

    def lost(self, generation):
        with self._lock:
            sessions = [live for (owner, _), live in self._sessions.items() if owner == generation]
        for live in sessions:
            live.lost()

    def sweep(self):
        with self._lock:
            candidates = sorted(self._entries.items(), key=lambda pair: pair[1].touched)
        for key, candidate in candidates:
            with self._gate(key):
                with self._lock:
                    age = self._clock() - candidate.touched
                    due = age >= self._idle or (len(self._entries) > self._budget and age >= self._unobserved)
                    if self._entries.get(key) is not candidate or candidate.users or not due:
                        continue
                try:
                    self._retire(candidate)
                except Exception:
                    _log.debug("Conversation retirement deferred", exc_info=True)

    def _retire(self, entry):
        if not entry.live.retire():
            return False
        with self._lock:
            self._forget(entry)
        self._release(entry.live)
        return True

    def _forget(self, entry):
        live = entry.live
        self._entries.pop(live.route.id, None)
        self._sessions.pop((live.worker.generation, live.native_id), None)

    def _maintain(self):
        while not self._stopped.wait(30):
            self.sweep()

    def close(self):
        self._stopped.set()
        self._thread.join(timeout=2)
