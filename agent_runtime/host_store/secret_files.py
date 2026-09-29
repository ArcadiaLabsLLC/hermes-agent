"""Path-keyed secret files in the host secure store — what the upstream credential seams call.

Every credential store in the census is a file under ``HERMES_HOME`` / ``HERMES_AUTH_HOME``
/ the default root. The upstream seams are one line each: ``path = view(path)`` in a
reader (unbound, :func:`view` returns *path* itself), or ``if bound(): return
write_json(...)`` in a writer. Bound, :class:`HostSecretFile` answers the reader's own
``exists`` / ``is_file`` / ``read_text`` / ``read_bytes`` / ``unlink`` calls from the
host store, so the reader's parsing and error handling run unchanged.

The view has no ``__fspath__`` on purpose: code that hands it to ``open()`` or
``shutil`` fails loudly instead of silently touching the disk path. A path outside
the store root is REFUSED: it reads as absent and writes raise
:class:`~agent_runtime.host_store.binding.OutsideStoreRoot`. Every write also
unlinks a plaintext file left at the disk path, so a bound store never leaves one.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, Union

from agent_runtime.host_store import binding as _binding
from agent_runtime.host_store.binding import HostStoreError, OutsideStoreRoot

__layer__ = "stores"

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]


def bound() -> bool:
    return _binding.bound()


def _slot_or_none(path: PathLike) -> Optional[str]:
    try:
        return _binding.require().slot(path)
    except OutsideStoreRoot:
        logger.info("host store: refused a read outside the store root: %s", os.fspath(path))
        return None


def _sweep_plaintext(path: PathLike) -> None:
    try:
        Path(os.fspath(path)).unlink(missing_ok=True)
    except OSError as exc:
        raise HostStoreError(f"a plaintext secret file at {os.fspath(path)} could not be removed: {exc}") from exc


def read_bytes(path: PathLike) -> Optional[bytes]:
    slot = _slot_or_none(path)
    if slot is None:
        return None
    value = _binding.require().callbacks.read(slot)
    return None if value is None else bytes(value)


def exists(path: PathLike) -> bool:
    return read_bytes(path) is not None


def write_bytes(path: PathLike, data: bytes) -> None:
    current = _binding.require()
    slot = current.slot(path)  # raises OutsideStoreRoot: never a write outside the root
    current.callbacks.write(slot, bytes(data))
    _sweep_plaintext(path)


def write_text(path: PathLike, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def write_json(path: PathLike, data: Any, *, indent: int = 2, **dump_kwargs: Any) -> None:
    dump_kwargs.pop("mode", None)
    dump_kwargs.pop("fsync_dir", None)
    dump_kwargs.setdefault("ensure_ascii", False)
    write_text(path, json.dumps(data, indent=indent, **dump_kwargs))


def delete(path: PathLike) -> bool:
    """Forget *path*'s slot; True when it held a value. Outside the root: nothing to forget."""
    slot = _slot_or_none(path)
    if slot is None:
        return False
    current = _binding.require()
    present = current.callbacks.read(slot) is not None
    current.callbacks.delete(slot)
    _sweep_plaintext(path)
    return present


class HostSecretFile:
    """A secret file answered by the host store (the reader-side view of one path)."""

    __slots__ = ("path",)

    def __init__(self, path: PathLike):
        self.path = Path(os.fspath(path))

    def __repr__(self) -> str:
        return f"HostSecretFile({str(self.path)!r})"

    def __str__(self) -> str:
        return str(self.path)

    @property
    def name(self) -> str:
        return self.path.name

    def exists(self) -> bool:
        return exists(self.path)

    def is_file(self) -> bool:
        return exists(self.path)

    def read_bytes(self) -> bytes:
        data = read_bytes(self.path)
        if data is None:
            raise FileNotFoundError(f"{self.path} (host secure store)")
        return data

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self.read_bytes().decode(encoding, errors)

    def write_bytes(self, data: bytes) -> int:
        write_bytes(self.path, data)
        return len(data)

    def write_text(self, text: str, encoding: str = "utf-8", errors: str = "strict") -> int:
        return self.write_bytes(text.encode(encoding, errors))

    def unlink(self, missing_ok: bool = False) -> None:
        if not delete(self.path) and not missing_ok:
            raise FileNotFoundError(f"{self.path} (host secure store)")

    def stat(self):
        raise FileNotFoundError(f"{self.path} is held by the host secure store, not the disk")

    def with_suffix(self, suffix: str) -> Path:
        return self.path.with_suffix(suffix)


def view(path: PathLike) -> Any:
    """*path* itself when unbound; bound, a :class:`HostSecretFile` over the same path."""
    if not _binding.bound():
        return path
    return path if isinstance(path, HostSecretFile) else HostSecretFile(path)


def is_view(path: Any) -> bool:
    return isinstance(path, HostSecretFile)


def external_logins_refused() -> bool:
    """Bound: the machine-wide borrowed CLI logins (Claude Code, Codex, Qwen, gh) are refused."""
    return _binding.bound()


def _known_platform_names() -> set:
    """Every platform value this process can name: the built-in ``Platform`` members, the bundled
    platform plugins and the plugins registered at run time (a user plugin never loaded here is
    listed by name only)."""
    import contextlib

    from gateway.config import Platform

    names = {member.value for member in Platform}
    with contextlib.suppress(Exception):  # no plugins/platforms tree (the phone wheel): built-ins only
        names |= Platform._scan_bundled_plugin_platforms()[0]
    with contextlib.suppress(Exception):
        from gateway.platform_registry import platform_registry
        names |= {entry.name for entry in platform_registry.plugin_entries()}
    return names


def with_slotted_platforms(platforms: Any, directory: PathLike, tail: str) -> Any:
    """``gateway.pairing.PairingStore._all_platforms``'s seam: *platforms* itself when unbound.

    Bound, the pairing files live in host-store slots and a slot has no directory listing, so
    each platform this process can name is asked of the store and the ones held there join the
    disk listing *platforms*.
    """
    if not _binding.bound():
        return platforms
    listed = list(platforms)
    return listed + [p for p in sorted(_known_platform_names() - set(listed))
                     if exists(Path(os.fspath(directory)) / f"{p}{tail}")]
