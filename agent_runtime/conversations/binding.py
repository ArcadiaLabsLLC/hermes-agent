"""Composition at the existing socket-owner boundary; no import-time boot."""
from __future__ import annotations

import threading
from pathlib import Path

from .model import ConversationError, Refusal
from .service import ConversationService

__layer__ = "lanes"
_lock = threading.Lock()
_owner: ConversationService | None = None


def _profile_home(profile: str) -> Path:
    from hermes_cli.profiles import get_profile_dir, profile_exists

    if not profile_exists(profile):
        raise ConversationError(Refusal.UNAVAILABLE)
    return get_profile_dir(profile)


def bind(root: Path, install_id: str) -> ConversationService:
    from .worker import select_worker_factory
    from agent_runtime.provider_credentials import bound_provider_home
    from hermes_constants import get_hermes_home

    global _owner
    auth_home = bound_provider_home() or get_hermes_home().resolve()
    with _lock:
        if _owner is not None:
            if (_owner.root, _owner.install_id, _owner.auth_home) != (root.resolve(), install_id, auth_home):
                raise ConversationError(Refusal.WRONG_OWNER)
            return _owner
        _owner = ConversationService(root, install_id, profile_home=_profile_home,
            worker_factory=select_worker_factory(), auth_home=auth_home)
        return _owner


def get_service() -> ConversationService:
    with _lock:
        if _owner is None:
            raise ConversationError(Refusal.UNAVAILABLE)
        return _owner


def shutdown(*, root: Path) -> None:
    global _owner
    with _lock:
        owner = _owner
        if owner is None or owner.root != root.resolve():
            return
        _owner = None
    owner.close()
