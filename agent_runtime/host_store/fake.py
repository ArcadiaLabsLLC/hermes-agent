"""An in-memory host secure store for CI — the fake the Stage 3 Keychain/Keystore port replaces.

``FakeHostSecureStore`` keeps slots in a dict and records every folder the runtime asks it
to protect (``protected``), exactly the shapes :class:`~agent_runtime.host_store.binding.HostStoreCallbacks`
names. ``bind()`` binds it for one test; ``unbind_host_store()`` releases it.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from agent_runtime.host_store import binding as _binding

__layer__ = "stores"


class FakeHostSecureStore:
    def __init__(self) -> None:
        self.slots: Dict[str, bytes] = {}
        self.protected: List[str] = []
        self._lock = threading.Lock()

    def read(self, slot: str) -> Optional[bytes]:
        with self._lock:
            return self.slots.get(slot)

    def write(self, slot: str, value: bytes) -> None:
        with self._lock:
            self.slots[slot] = bytes(value)

    def delete(self, slot: str) -> None:
        with self._lock:
            self.slots.pop(slot, None)

    def protect_history_dir(self, path: str) -> None:
        with self._lock:
            self.protected.append(path)

    def callbacks(self) -> _binding.HostStoreCallbacks:
        return _binding.HostStoreCallbacks(
            read=self.read, write=self.write, delete=self.delete, protect_history_dir=self.protect_history_dir)

    def bind(self, *, profile: str, store_root) -> _binding.HostStoreBinding:
        return _binding.bind_host_store(self.callbacks(), profile=profile, store_root=store_root)
