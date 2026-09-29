"""An in-memory host secure store for CI — the fake the Stage 3 Keychain/Keystore port replaces.

``FakeHostSecureStore`` keeps slots in a dict and hands out one random 32-byte history
key per profile, exactly the shapes :class:`~agent_runtime.host_store.binding.HostStoreCallbacks`
names. ``bind()`` binds it for one test; ``unbind_host_store()`` releases it.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

from agent_runtime.host_store import binding as _binding

__layer__ = "stores"


class FakeHostSecureStore:
    def __init__(self) -> None:
        self.slots: Dict[str, bytes] = {}
        self.history_keys: Dict[str, bytes] = {}
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

    def history_key(self, profile: str) -> bytes:
        with self._lock:
            return self.history_keys.setdefault(profile, os.urandom(_binding.HISTORY_KEY_BYTES))

    def callbacks(self) -> _binding.HostStoreCallbacks:
        return _binding.HostStoreCallbacks(
            read=self.read, write=self.write, delete=self.delete, history_key=self.history_key)

    def bind(self, *, profile: str, store_root) -> _binding.HostStoreBinding:
        return _binding.bind_host_store(self.callbacks(), profile=profile, store_root=store_root)
