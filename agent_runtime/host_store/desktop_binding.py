"""Bind the bundled desktop Hermes to the OS secure store at process start, and move old plaintext in.

The switch is ``auth.os_secure_store`` (default off: full Hermes is unchanged; on in
``bundled-desktop.yaml``). On, every Hermes process of the install binds the same store
before it reads a credential — the ``hermes_cli.main`` entry (so ``harness serve`` on
stdio or the socket, and the ``auth login`` sign-in child it spawns) and the conversation
worker (``agent_runtime.conversations.worker_entry``). A store that is not available is a
typed refusal (:class:`~agent_runtime.host_store.desktop.SecureStoreUnavailable`): the
process exits rather than writing a sign-in in plaintext.

Chat history is NOT moved: the ruling covers sign-ins; desktop chat history stays a plain
file by owner ruling 2026-09-29, and the store passes no ``protect_history_dir``.
``tests/agent_runtime/test_desktop_host_store.py`` pins it.

Shared namespace (RT-NAMESPACE-SECURE-STORE-SHARED, owner Q3 2026-10-20): both editions open ONE
namespace, and a bound process MOVES plaintext into the store and unlinks it — which would sign a
file-reading Developer Edition out of every provider. So the secure store is also a NAMESPACE fact:
the first bind records ``secure_store: true`` in the namespace's ``namespace.json``, and every edition
binds where that fact is set, whatever its own ``auth.os_secure_store`` says. The blobs live under the
namespace root (``<namespace>/secure-store``), which both editions resolve identically.

Migration: a plaintext credential file left by an older bundled install (census:
``docs/downstream/credential-store-census-2026-09-28.md``) is written to its slot,
read back, and only then unlinked. A crash at any point leaves either the plaintext or
the slot holding the value (the store's own write is atomic), and the next start
finishes the move — a plaintext file present at start is always the newest copy,
because a bound write removes the plaintext it supersedes.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from agent_runtime.host_store import binding as _binding
from agent_runtime.host_store import desktop as _desktop
from agent_runtime.host_store.binding import HostStoreError, OutsideStoreRoot

__layer__ = "lanes"

logger = logging.getLogger(__name__)

SWITCH = ("auth", "os_secure_store")
BLOB_DIR_NAME = "secure-store"
DEFAULT_PROFILE = "default"

#: Per-profile plaintext stores under ``HERMES_HOME`` the credential seams read (census §1, 3, 6, 8).
HOME_SECRET_FILES = ("auth.json", ".env", ".anthropic_oauth.json", "webhook_subscriptions.json")
#: Directories whose ``*.json`` files are secrets (census §7 MCP OAuth, §8 pairing).
HOME_SECRET_DIRS = ("mcp-tokens", "pairing", "platforms/pairing")
#: Default-root fallbacks the global readers use when the root is not the home (census §1, 3).
ROOT_SECRET_FILES = ("auth.json", ".anthropic_oauth.json")
#: The shared Nous store (census §5): ``HERMES_SHARED_AUTH_DIR`` or ``<root>/shared``.
NOUS_SHARED_FILE = "nous_auth.json"


#: The ``namespace.json`` key that makes the secure store a namespace fact.
NAMESPACE_FACT = "secure_store"


def os_secure_store_enabled() -> bool:
    """``auth.os_secure_store`` (default off: full Hermes keeps upstream's files), or the namespace fact."""
    from hermes_cli.config_switches import config_switch

    return config_switch(*SWITCH, default=False) or namespace_secure_store()


def _own_manifest_path() -> Optional[Path]:
    """This process's ``namespace.json``, or None on the base root."""
    from hermes_cli._namespace_bootstrap import NamespaceRefused, layout, namespace_stamp

    ns_id = namespace_stamp()
    if not ns_id:
        return None
    try:
        return layout(ns_id, os.environ, long_paths=True).manifest_path
    except NamespaceRefused:
        return None


def _manifest_record(path: Path) -> Optional[dict]:
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def namespace_secure_store() -> bool:
    """True when this process's namespace records that its sign-ins live in the OS secure store."""
    path = _own_manifest_path()
    record = None if path is None else _manifest_record(path)
    return bool(record) and record.get(NAMESPACE_FACT) is True


def record_namespace_secure_store() -> bool:
    """Set the namespace fact at bind (first binder wins; idempotent). True when this call wrote it."""
    path = _own_manifest_path()
    record = None if path is None else _manifest_record(path)
    if record is None or record.get(NAMESPACE_FACT) is True:
        return False
    from agent_runtime.store_epoch import write_manifest

    try:
        write_manifest(path, {**record, NAMESPACE_FACT: True})
    except OSError as exc:  # never move a sign-in another edition could then not find
        raise HostStoreError(f"could not record {NAMESPACE_FACT} in {path}: {exc}; plaintext kept") from exc
    return True


def shared_auth_dir(root: Path) -> Path:
    override = os.getenv("HERMES_SHARED_AUTH_DIR", "").strip()
    return Path(override).expanduser() if override else root / "shared"


def plaintext_secret_paths(home: Path, root: Path, shared_dir: Path) -> list[Path]:
    """Every plaintext credential file a bound process would otherwise leave on disk."""
    paths = [home / name for name in HOME_SECRET_FILES]
    for name in HOME_SECRET_DIRS:
        folder = home / name
        if folder.is_dir():
            paths.extend(sorted(folder.glob("*.json")))
    if os.path.normcase(str(root)) != os.path.normcase(str(home)):
        paths.extend(root / name for name in ROOT_SECRET_FILES)
    paths.append(shared_dir / NOUS_SHARED_FILE)
    return paths


def migrate_plaintext_secrets(current: _binding.HostStoreBinding, paths: Iterable[Path]) -> list[Path]:
    """Move each existing plaintext file into its slot: write, verify, then unlink. Returns the moved paths."""
    moved: list[Path] = []
    for path in paths:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        try:
            slot = current.slot(path)
        except OutsideStoreRoot:
            logger.warning("host store: %s is outside the store root; left in place", path)
            continue
        current.callbacks.write(slot, data)
        if current.callbacks.read(slot) != data:
            raise HostStoreError(f"the secure store did not return what was written for {path}; plaintext kept")
        path.unlink(missing_ok=True)  # a sibling process finishing the same move
        moved.append(path)
    return moved


def _profile_name(home: Path) -> str:
    return home.name if home.parent.name == "profiles" and home.name else DEFAULT_PROFILE


def _reload_dotenv(home: Path) -> None:
    """Publish the (now store-held) ``.env`` again: the entry's first load ran before the bind."""
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=home, load_external_secrets=False)


def bind_desktop_host_store(
    *, store_factory: Optional[Callable[[Path], _desktop._SecureStoreBase]] = None,
) -> Optional[_binding.HostStoreBinding]:
    """Switched on: bind the OS secure store over the install's root and migrate. Else None.

    Raises :class:`HostStoreError` (``SecureStoreUnavailable`` among them) and leaves the
    process unbound when the store cannot be used or the migration cannot complete.
    """
    if not os_secure_store_enabled():
        return None
    existing = _binding.current()
    if existing is not None:
        return existing
    from hermes_constants import get_default_hermes_root, get_hermes_home

    home = Path(os.path.abspath(get_hermes_home()))
    root = Path(os.path.abspath(get_default_hermes_root()))
    store = (store_factory or _desktop.os_secure_store)(root / BLOB_DIR_NAME)
    current = _binding.bind_host_store(store.callbacks(), profile=_profile_name(home), store_root=root)
    try:
        # The fact first: once a plaintext file is gone, an edition that missed the fact is signed out.
        record_namespace_secure_store()
        moved = migrate_plaintext_secrets(current, plaintext_secret_paths(home, root, shared_auth_dir(root)))
        _reload_dotenv(home)
    except BaseException:
        _binding.unbind_host_store()
        raise
    if moved:
        logger.info("host store: moved %d plaintext credential file(s) into the OS secure store", len(moved))
    return current


def bind_desktop_host_store_or_exit() -> None:
    """The entry points' call: bind when switched on; a refusal ends the process (exit 2), never plaintext."""
    try:
        bind_desktop_host_store()
    except HostStoreError as exc:
        print(json.dumps({"ok": False, "error": "secure_store_unavailable", "detail": str(exc)}))
        sys.stdout.flush()
        raise SystemExit(2) from exc
