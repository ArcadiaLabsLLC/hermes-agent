"""Secret-file store: one port behind every credential file Hermes reads and writes.

Every credential file (``.anthropic_oauth.json``, ``.env``, pairing stores, webhook
subscriptions, MCP OAuth tokens, borrowed CLI logins) is a path its owning module computes
and then reads or writes with pathlib + :func:`utils.atomic_json_write`. A host that keeps
secrets in an OS secure store (a keychain, the Android Keystore, an embedding app's vault)
registers a :class:`SecretFileStore` through ``ctx.register_secret_file_store()``; the call
sites route through the helpers below, which keep the path the reader computed and let the
store hold the bytes.

**Nothing registered** (the default): every helper is exactly the disk call the site made
before — :func:`secret_path` returns the path object unchanged, :func:`write_secret_json`
is ``atomic_json_write(path, data, mode=mode, ...)``, and so on.

**A store registered**: :func:`secret_path` returns a :class:`SecretFileView` that answers the
reader's own ``exists`` / ``is_file`` / ``read_text`` / ``read_bytes`` / ``unlink`` calls from
the store, so the reader's parsing and error handling run unchanged. The view has no
``__fspath__`` and its ``stat()`` raises on purpose: code that hands it to ``open()`` or
``shutil`` fails loudly instead of silently touching the disk path. The store decides what
it holds: outside its own root it answers absent on read and raises on write.

Sits beside :mod:`agent.secret_sources` (read-only ENV-value sources run by
``load_hermes_dotenv``), which never own a file's read/write/unlink.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union

from agent.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

PathOrView = Union[Path, "SecretFileView"]


class SecretFileStore(ABC):
    """Holds the bytes of credential files instead of the disk.

    Paths are the disk paths the readers compute today; the store maps them to its own
    slots. Outside its root it answers absent (``read`` → None, ``delete`` → False) and
    refuses writes (raise) — the store decides, never the caller.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Registry key (``ctx.register_secret_file_store``)."""

    @abstractmethod
    def read(self, path: Path) -> Optional[bytes]:
        """The bytes held for *path*, or None when absent."""

    @abstractmethod
    def write(self, path: Path, data: bytes) -> None:
        """Hold *data* for *path* (replacing any previous value)."""

    @abstractmethod
    def delete(self, path: Path) -> bool:
        """Forget *path*; True when it held a value."""

    def list(self, directory: Path, suffix: str) -> list[str]:
        """Names (with *suffix* stripped) held for files directly under *directory*.
        Default: none — a store without a listing still answers reads and writes."""
        return []


# Scope-aware like every ``agent/*_registry.py``: a multiplexed gateway registers per profile.
_registry: ProviderRegistry[SecretFileStore] = ProviderRegistry(
    label="secret file store", provider_cls=SecretFileStore, logger=logger,
)
_registry.export(globals())


def _active_store() -> Optional[SecretFileStore]:
    """The store for the current scope (scoped first, then global); first by name if several."""
    stores = _registry.list_providers()
    return stores[0] if stores else None


def _disk_path(path: Any) -> Path:
    return path.path if isinstance(path, SecretFileView) else Path(os.fspath(path))


class SecretFileView:
    """Reader-side view of one secret file whose bytes a :class:`SecretFileStore` holds."""

    __slots__ = ("path",)

    def __init__(self, path: Any):
        self.path = _disk_path(path)

    def __repr__(self) -> str:
        return f"SecretFileView({str(self.path)!r})"

    def __str__(self) -> str:
        return str(self.path)

    @property
    def name(self) -> str:
        return self.path.name

    def exists(self) -> bool:
        return read_secret_bytes(self) is not None

    def is_file(self) -> bool:
        return self.exists()

    def read_bytes(self) -> bytes:
        data = read_secret_bytes(self)
        if data is None:
            raise FileNotFoundError(f"{self.path} (secret file store)")
        return data

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self.read_bytes().decode(encoding, errors)

    def write_bytes(self, data: bytes) -> int:
        write_secret_bytes(self, data)
        return len(data)

    def write_text(self, text: str, encoding: str = "utf-8", errors: str = "strict") -> int:
        return self.write_bytes(text.encode(encoding, errors))

    def unlink(self, missing_ok: bool = False) -> None:
        unlink_secret(self, missing_ok=missing_ok)

    def stat(self):
        raise FileNotFoundError(f"{self.path} is held by the secret file store, not the disk")

    def with_suffix(self, suffix: str) -> Path:
        return self.path.with_suffix(suffix)

    def with_name(self, name: str) -> Path:
        """A sibling disk path (lock files and other non-secret metadata stay on disk)."""
        return self.path.with_name(name)


def secret_store_bound() -> bool:
    """True when a :class:`SecretFileStore` is registered for the current scope."""
    return _active_store() is not None


def secret_path(path: Any) -> Any:
    """*path* itself when no store is registered; otherwise a :class:`SecretFileView` over it."""
    if isinstance(path, SecretFileView) or not secret_store_bound():
        return path
    return SecretFileView(path)


def is_secret_view(obj: Any) -> bool:
    return isinstance(obj, SecretFileView)


def read_secret_bytes(path: Any) -> Optional[bytes]:
    """The file's bytes (disk ``read_bytes``, or the store's), None when absent."""
    store = _active_store()
    if store is None:
        try:
            return _disk_path(path).read_bytes()
        except FileNotFoundError:
            return None
    value = store.read(_disk_path(path))
    return None if value is None else bytes(value)


def write_secret_bytes(path: Any, data: bytes, *, mode: int = 0o600) -> None:
    """Unbound: ``utils.atomic_write_bytes(path, data, mode=mode)``; bound: the store holds it."""
    store = _active_store()
    if store is None:
        from utils import atomic_write_bytes

        atomic_write_bytes(_disk_path(path), data, mode=mode)
        return
    store.write(_disk_path(path), bytes(data))


def write_secret_json(path: Any, data: Any, *, mode: int = 0o600, **dump_kwargs: Any) -> None:
    """Unbound: ``utils.atomic_json_write(path, data, mode=mode, **dump_kwargs)`` — the call the
    sites made before. Bound: the same JSON text (indent 2, raw UTF-8) handed to the store."""
    store = _active_store()
    if store is None:
        from utils import atomic_json_write

        atomic_json_write(_disk_path(path), data, mode=mode, **dump_kwargs)
        return
    dump_kwargs.pop("fsync_dir", None)
    indent = dump_kwargs.pop("indent", 2)
    ensure_ascii = dump_kwargs.pop("ensure_ascii", False)
    try:
        text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, **dump_kwargs)
        payload = text.encode("utf-8")
    except UnicodeEncodeError:  # surrogate-escaped strings: same fallback as atomic_json_write
        payload = json.dumps(data, indent=indent, ensure_ascii=True, **dump_kwargs).encode("utf-8")
    store.write(_disk_path(path), payload)


def unlink_secret(path: Any, *, missing_ok: bool = True) -> bool:
    """Remove the file (disk unlink, or the store forgets it). True when something was removed;
    an absent file raises ``FileNotFoundError`` unless *missing_ok*."""
    store = _active_store()
    disk = _disk_path(path)
    if store is None:
        try:
            disk.unlink()
            return True
        except FileNotFoundError:
            if not missing_ok:
                raise
            return False
    removed = store.delete(disk)
    if not removed and not missing_ok:
        raise FileNotFoundError(f"{disk} (secret file store)")
    return removed


def list_secret_files(directory: Path, suffix: str) -> list[str]:
    """Names (suffix stripped) of the files under *directory* ending in *suffix*.

    Unbound: the disk listing (``directory.iterdir()``, errors propagate as before). Bound: the
    disk listing (empty when the directory is absent) plus the names the store holds."""
    directory = Path(directory)
    store = _active_store()
    if store is None:
        return [f.name[: -len(suffix)] for f in directory.iterdir() if f.name.endswith(suffix)]
    try:
        names = [f.name[: -len(suffix)] for f in directory.iterdir() if f.name.endswith(suffix)]
    except OSError:
        names = []
    for name in store.list(directory, suffix):
        if name not in names:
            names.append(name)
    return names
