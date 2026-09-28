"""The host secure-store contract and the one process-wide binding.

The host supplies four callbacks (``HostStoreCallbacks``):

* ``read(slot: str) -> bytes | None`` — the value stored under *slot*, or None;
* ``write(slot: str, value: bytes) -> None`` — store *value* under *slot*;
* ``delete(slot: str) -> None`` — forget *slot* (absent is not an error);
* ``history_key(profile: str) -> bytes`` — the 32-byte raw key that encrypts this
  profile's chat history. The host holds it in its secure store and unwraps it
  through the Eternia account; Hermes never stores it and never wraps it.

A slot is ``hermes/v1/<profile>/<path relative to the store root>``: the profile the
host bound, then the exact store path — so ``auth.json`` under a moved
``HERMES_AUTH_HOME`` and the one under ``HERMES_HOME`` are different slots, and two
profiles never share one. Paths are relative to the store root so a phone's app
container moving (iOS re-homes it on update) keeps every slot. A path outside the
store root has no slot: reads of it are refused and writes raise, which is also what
refuses the machine-wide borrowed stores (``~/.claude``, ``~/.codex``, ``~/.qwen``).
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

__layer__ = "models"

SLOT_PREFIX = "hermes/v1"
HISTORY_KEY_BYTES = 32
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class HostStoreError(RuntimeError):
    """The host store refused, or a path has no slot under the bound store root."""


class OutsideStoreRoot(HostStoreError):
    """A secret or history path outside the bound store root (never written in plaintext)."""


@dataclass(frozen=True)
class HostStoreCallbacks:
    read: Callable[[str], Optional[bytes]]
    write: Callable[[str, bytes], None]
    delete: Callable[[str], None]
    history_key: Callable[[str], bytes]


@dataclass(frozen=True)
class HostStoreBinding:
    callbacks: HostStoreCallbacks
    profile: str
    store_root: Path

    def relative(self, path: "os.PathLike[str] | str") -> str:
        """*path* relative to the store root, POSIX-spelled; raises :class:`OutsideStoreRoot`."""
        target = Path(os.path.abspath(os.fspath(path)))
        try:
            rel = target.relative_to(self.store_root)
        except ValueError:
            raise OutsideStoreRoot(f"{target} is outside the host store root {self.store_root}") from None
        spelled = rel.as_posix()
        if spelled in ("", "."):
            raise OutsideStoreRoot(f"{target} is the store root itself, not a store path")
        return spelled.lower() if os.name == "nt" else spelled  # NTFS is case-insensitive: one slot per file

    def slot(self, path: "os.PathLike[str] | str") -> str:
        return f"{SLOT_PREFIX}/{self.profile}/{self.relative(path)}"

    def history_key(self) -> bytes:
        key = self.callbacks.history_key(self.profile)
        if not isinstance(key, (bytes, bytearray)) or len(key) != HISTORY_KEY_BYTES:
            raise HostStoreError(
                f"host history_key({self.profile!r}) must return {HISTORY_KEY_BYTES} raw bytes")
        return bytes(key)


_LOCK = threading.Lock()
_BINDING: Optional[HostStoreBinding] = None


def bind_host_store(callbacks: HostStoreCallbacks, *, profile: str, store_root: "os.PathLike[str] | str") -> HostStoreBinding:
    """Bind the process to a host store. One binding per process; rebinding raises."""
    global _BINDING
    if not isinstance(profile, str) or not _PROFILE_RE.match(profile):
        raise HostStoreError(f"profile {profile!r} is not a valid slot namespace")
    root = Path(os.path.abspath(os.fspath(store_root)))
    binding = HostStoreBinding(callbacks=callbacks, profile=profile, store_root=root)
    with _LOCK:
        if _BINDING is not None:
            raise HostStoreError(f"a host store is already bound (profile {_BINDING.profile!r})")
        _BINDING = binding
    return binding


def unbind_host_store() -> None:
    global _BINDING
    with _LOCK:
        _BINDING = None


def current() -> Optional[HostStoreBinding]:
    return _BINDING


def bound() -> bool:
    return _BINDING is not None


def require() -> HostStoreBinding:
    """The binding, or :class:`HostStoreError` when the process has none."""
    current = _BINDING
    if current is None:
        raise HostStoreError("no host store is bound")
    return current
