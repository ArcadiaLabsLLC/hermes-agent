"""Bind the bundled desktop Hermes to the OS secure store at process start, and move old plaintext in.

The switch is ``auth.os_secure_store`` (default off: full Hermes is unchanged; on in
``bundled-desktop.yaml``). On, every Hermes process of the install binds the same store
before it reads a credential — the ``hermes_cli.main`` entry (so ``harness serve`` on
stdio or the socket, and the ``auth login`` sign-in child it spawns) and the conversation
worker (``agent_runtime.conversations.worker_entry``). A store that is not available is a
typed refusal (:class:`~agent_runtime.host_store.desktop.SecureStoreUnavailable`): the
process exits rather than writing a sign-in in plaintext.

Chat history is NOT moved (``history=False``): the worker is a second process on the same
``state.db`` and the encrypted image has one writer. The ruling covers sign-ins; desktop
chat history stays a plain file by owner ruling 2026-09-29 (revisit only with a one-writer
or multi-process sealed store). ``tests/agent_runtime/test_desktop_host_store.py`` pins it.

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


def os_secure_store_enabled() -> bool:
    """``auth.os_secure_store`` — default off (full Hermes keeps upstream's files)."""
    from hermes_cli.config import config_switch

    return config_switch(*SWITCH, default=False)


def shared_auth_dir(root: Path) -> Path:
    override = os.getenv("HERMES_SHARED_AUTH_DIR", "").strip()
    return Path(override).expanduser() if override else root / "shared"


def plaintext_secret_paths(home: Path, root: Path, shared_dir: Path) -> List[Path]:
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


def migrate_plaintext_secrets(current: _binding.HostStoreBinding, paths: Iterable[Path]) -> List[Path]:
    """Move each existing plaintext file into its slot: write, verify, then unlink. Returns the moved paths."""
    moved: List[Path] = []
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
    *, store_factory: Optional[Callable[[Path], "_desktop._SecureStoreBase"]] = None,
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
    current = _binding.bind_host_store(store.callbacks(), profile=_profile_name(home), store_root=root, history=False)
    try:
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
