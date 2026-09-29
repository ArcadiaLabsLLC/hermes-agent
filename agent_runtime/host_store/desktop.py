"""The desktop OS secure stores behind :class:`~agent_runtime.host_store.binding.HostStoreCallbacks`.

The bundled desktop Hermes keeps its sign-ins in the OS secure store through the same
seam the phones use (owner ruling 2026-09-28, item 4). Full Hermes never binds one.

* Windows — :class:`DpapiHostSecureStore`: each slot is one file under the bundled data
  root holding ``CryptProtectData`` output (pywin32, CURRENT USER scope, UI forbidden),
  with the slot name as the per-slot entropy. The file name is a hash of the slot, so
  neither a path nor a provider name reaches the disk in the clear.
* macOS / Linux — :class:`KeyringHostSecureStore`: the Keychain or the Secret Service
  through ``keyring``, admitted only when its resolved backend is one of those two.
  Anything else (no ``keyring`` in the bundle, a plaintext or null backend) is
  :class:`SecureStoreUnavailable` — a typed refusal, never a plaintext fallback.

``history_key(profile)`` is a random 32-byte key generated once per profile and held in
the same store (:data:`HISTORY_KEY_SLOT`, outside the path-slot namespace).
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from agent_runtime.host_store import binding as _binding
from agent_runtime.host_store.binding import HostStoreError

__layer__ = "stores"

HISTORY_KEY_SLOT = "hermes/v1-keys/{profile}/history"
DEFAULT_SCOPE = b"hermes-host-store-v1"
BLOB_SUFFIX = ".dpapi"
_TMP_SUFFIX = ".dpapi-tmp"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
KEYRING_SERVICE = "hermes-agent"
#: ``keyring`` backend modules that ARE an OS secure store. Everything else is refused.
KEYRING_BACKENDS = frozenset({
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.libsecret",
})


class SecureStoreUnavailable(HostStoreError):
    """This platform's OS secure store is not in the bundle (or not usable); nothing is stored."""


class SecretUnreadable(HostStoreError):
    """A protected slot this user / scope cannot unprotect. Never read as absent: that would
    let a sign-in overwrite another account's credentials."""


def _history_key_slot(profile: str) -> str:
    return HISTORY_KEY_SLOT.format(profile=profile)


class _SecureStoreBase:
    """The ``HostStoreCallbacks`` shape plus a generate-once history key over read/write."""

    def read(self, slot: str) -> Optional[bytes]:
        raise NotImplementedError

    def write(self, slot: str, value: bytes) -> None:
        raise NotImplementedError

    def delete(self, slot: str) -> None:
        raise NotImplementedError

    def _write_if_absent(self, slot: str, value: bytes) -> None:
        if self.read(slot) is None:
            self.write(slot, value)

    def history_key(self, profile: str) -> bytes:
        slot = _history_key_slot(profile)
        key = self.read(slot)
        if key is None:
            self._write_if_absent(slot, os.urandom(_binding.HISTORY_KEY_BYTES))
            key = self.read(slot)  # the winner's key when two processes raced
        if key is None or len(key) != _binding.HISTORY_KEY_BYTES:
            raise HostStoreError(f"the history key for profile {profile!r} is missing or malformed")
        return bytes(key)

    def callbacks(self) -> _binding.HostStoreCallbacks:
        return _binding.HostStoreCallbacks(
            read=self.read, write=self.write, delete=self.delete, history_key=self.history_key)


def _load_win32crypt() -> Any:
    try:
        import win32crypt  # pywin32: a base dependency on Windows
    except ImportError as exc:
        raise SecureStoreUnavailable("DPAPI needs pywin32's win32crypt, which this install lacks") from exc
    return win32crypt


class DpapiHostSecureStore(_SecureStoreBase):
    """Windows DPAPI, current-user scope; one protected blob file per slot under *blob_dir*.

    *scope* is prefixed to each slot's entropy. Production uses :data:`DEFAULT_SCOPE`;
    a different scope stands in for a different Windows user in tests (both make
    ``CryptUnprotectData`` refuse).
    """

    def __init__(self, blob_dir: "os.PathLike[str] | str", *, scope: bytes = DEFAULT_SCOPE,
                 crypt: Any = None) -> None:
        self.blob_dir = Path(os.path.abspath(os.fspath(blob_dir)))
        self.scope = bytes(scope)
        self._crypt = crypt if crypt is not None else _load_win32crypt()
        self._lock = threading.Lock()
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        for stale in self.blob_dir.glob(f"*{_TMP_SUFFIX}"):  # an interrupted write: protected bytes only
            stale.unlink(missing_ok=True)

    def _entropy(self, slot: str) -> bytes:
        return self.scope + b"\x00" + slot.encode("utf-8")

    def blob_path(self, slot: str) -> Path:
        return self.blob_dir / (hashlib.sha256(slot.encode("utf-8")).hexdigest() + BLOB_SUFFIX)

    def _protect(self, slot: str, value: bytes) -> bytes:
        return bytes(self._crypt.CryptProtectData(
            bytes(value), None, self._entropy(slot), None, None, _CRYPTPROTECT_UI_FORBIDDEN))

    def _stage(self, slot: str, value: bytes) -> str:
        fd, tmp = tempfile.mkstemp(dir=str(self.blob_dir), prefix=".", suffix=_TMP_SUFFIX)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self._protect(slot, value))
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return tmp

    def read(self, slot: str) -> Optional[bytes]:
        try:
            blob = self.blob_path(slot).read_bytes()
        except FileNotFoundError:
            return None
        try:
            _description, value = self._crypt.CryptUnprotectData(
                blob, self._entropy(slot), None, None, _CRYPTPROTECT_UI_FORBIDDEN)
        except Exception as exc:  # pywintypes.error: another user, another scope, or tampering
            raise SecretUnreadable(f"secure-store slot for {slot!r} cannot be unprotected by this user") from exc
        return bytes(value)

    def write(self, slot: str, value: bytes) -> None:
        with self._lock:
            tmp = self._stage(slot, value)
            try:
                os.replace(tmp, self.blob_path(slot))
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

    def delete(self, slot: str) -> None:
        with self._lock:
            self.blob_path(slot).unlink(missing_ok=True)

    def _write_if_absent(self, slot: str, value: bytes) -> None:
        with self._lock:
            tmp = self._stage(slot, value)
            try:
                os.link(tmp, self.blob_path(slot))  # atomic create-if-absent: a racing writer keeps its key
            except FileExistsError:
                pass
            finally:
                Path(tmp).unlink(missing_ok=True)


class KeyringHostSecureStore(_SecureStoreBase):
    """The macOS Keychain or the Linux Secret Service, through an admitted ``keyring`` backend."""

    def __init__(self, backend: Any, *, service: str = KEYRING_SERVICE) -> None:
        self._backend = backend
        self.service = service

    def read(self, slot: str) -> Optional[bytes]:
        text = self._backend.get_password(self.service, slot)
        return None if text is None else base64.b64decode(text.encode("ascii"))

    def write(self, slot: str, value: bytes) -> None:
        self._backend.set_password(self.service, slot, base64.b64encode(bytes(value)).decode("ascii"))

    def delete(self, slot: str) -> None:
        try:
            self._backend.delete_password(self.service, slot)
        except Exception as exc:  # keyring.errors.PasswordDeleteError: absent is not an error
            if self.read(slot) is not None:
                raise HostStoreError(f"secure-store slot for {slot!r} could not be deleted") from exc


def admitted_keyring_backend(load_keyring: Callable[[], Any] | None = None) -> Any:
    """The resolved ``keyring`` backend when it is the Keychain or the Secret Service; else refuse."""
    if load_keyring is None:
        def load_keyring() -> Any:
            import keyring

            return keyring
    try:
        backend = load_keyring().get_keyring()
    except ImportError as exc:
        raise SecureStoreUnavailable(
            "no OS secure store in this bundle: the `keyring` library (Keychain / Secret Service) is absent") from exc
    module = type(backend).__module__
    if module not in KEYRING_BACKENDS:
        raise SecureStoreUnavailable(
            f"the keyring backend {module}.{type(backend).__name__} is not an OS secure store; refusing it")
    return backend


def _keyring_store(_blob_dir: "os.PathLike[str] | str") -> _SecureStoreBase:
    return KeyringHostSecureStore(admitted_keyring_backend())


#: ``sys.platform`` family -> its OS secure store (Linux platforms are ``linux*``).
_PLATFORM_STORES: dict[str, Callable[["os.PathLike[str] | str"], _SecureStoreBase]] = {
    "win32": DpapiHostSecureStore,
    "darwin": _keyring_store,
    "linux": _keyring_store,
}


def os_secure_store(blob_dir: "os.PathLike[str] | str", *, platform: str | None = None) -> _SecureStoreBase:
    """This platform's OS secure store; :class:`SecureStoreUnavailable` when it has none usable."""
    platform = platform or sys.platform
    factory = _PLATFORM_STORES.get("linux" if platform.startswith("linux") else platform)
    if factory is None:
        raise SecureStoreUnavailable(f"no OS secure store is supported on {platform!r}")
    return factory(blob_dir)
