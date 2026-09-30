"""The host secure-store contract and the one process-wide binding.

The host supplies three credential callbacks and, on a phone, a fourth
(``HostStoreCallbacks``):

* ``read(slot: str) -> bytes | None`` — the value stored under *slot*, or None;
* ``write(slot: str, value: bytes) -> None`` — store *value* under *slot*;
* ``delete(slot: str) -> None`` — forget *slot* (absent is not an error);
* ``protect_history_dir(path: str) -> None`` — REQUIRED on a phone (the embedded
  serve refuses to start without it, :meth:`HostStoreBinding.protect_history_dir`): put the OS's file
  protection and a no-cloud-backup mark on *path*, the Hermes home that holds the chat
  history (``state.db`` and its WAL, ``sessions/``, ``logs/``). iOS: the strongest Data
  Protection class (``NSFileProtectionComplete``, inherited by files created inside) and
  ``isExcludedFromBackup``; Android: an app-private directory under file-based
  encryption, excluded from Auto Backup / device transfer (or under
  ``noBackupFilesDir``). Idempotent — called on every embedded start. Raising refuses
  the start. The history itself is upstream's plain SQLite and JSONL: Hermes seals
  nothing (owner ruling 2026-09-30); the OS's protection of the app container is the
  at-rest encryption. A store sealed by the retired app-level seal (``hsec1``
  envelopes, before 2026-09-30) is not readable and may be discarded — no users.
  The bundled desktop never passes it: its history stays a plain file by ruling.

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
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class HostStoreError(RuntimeError):
    """The host store refused, or a path has no slot under the bound store root."""


class OutsideStoreRoot(HostStoreError):
    """A secret or history path outside the bound store root (never written in plaintext)."""


class HistoryProtectionMissing(HostStoreError):
    """The host bound no ``protect_history_dir``: the phone's history folder would be unprotected."""


class HostStoreNotBound(HostStoreError):
    """The process has no host store, and the caller must not fall back to plaintext files.

    The embedded serve (the phone profile's entry) raises it before it accepts a request:
    unbound, every credential and history store would be upstream's plaintext file.
    """


@dataclass(frozen=True)
class HostStoreCallbacks:
    read: Callable[[str], Optional[bytes]]
    write: Callable[[str, bytes], None]
    delete: Callable[[str], None]
    protect_history_dir: Optional[Callable[[str], None]] = None


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

    def protect_history_dir(self, path: "os.PathLike[str] | str") -> Path:
        """Ask the host to protect *path* (see the module doc); refuse when it cannot.

        Raises :class:`HistoryProtectionMissing` when the host supplied no callback, and
        :class:`OutsideStoreRoot` when *path* is not under the store root."""
        target = Path(os.path.abspath(os.fspath(path)))
        if not target.is_relative_to(self.store_root):
            raise OutsideStoreRoot(f"{target} is outside the host store root {self.store_root}")
        protect = self.callbacks.protect_history_dir
        if protect is None:
            raise HistoryProtectionMissing(
                "the host store has no protect_history_dir callback: chat history would be stored "
                "without the OS's file protection and could reach a cloud backup")
        protect(str(target))
        return target


_LOCK = threading.Lock()
_BINDING: Optional[HostStoreBinding] = None


def bind_host_store(callbacks: HostStoreCallbacks, *, profile: str,
                    store_root: "os.PathLike[str] | str") -> HostStoreBinding:
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
    """The binding, or :class:`HostStoreNotBound` when the process has none."""
    current = _BINDING
    if current is None:
        raise HostStoreNotBound("no host store is bound")
    return current
