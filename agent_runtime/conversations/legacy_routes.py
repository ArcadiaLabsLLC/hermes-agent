"""The retired profile-scoped conversations' saved routes: read and adopted, never run.

A profile-scoped conversation (``runtime.conversation.*``, and the legacy profile-group discussion
rooms built on it) used to run its turns on its own path beside the operator chat. That path is
retired (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT, owner 2026-11-21 "yea retire
the old path"): every chat with an agent is an operator chat on the one engine. What a retired
conversation left behind stays: its route and turn receipts in ``native_conversation_routes.db``
and its transcript in its profile's ``state.db``. This owner keeps them and does exactly one thing
with them, :meth:`LegacyRoutes.migrate` — import a route's transcript into an agent's chat
(``migration.migrate_conversation``), as a group adoption or a compare import does. It starts no
worker and sends no turn.
"""
from __future__ import annotations

import threading
from pathlib import Path

from .model import ConversationError, ConversationScope, Refusal
from .process_evidence import execution_possible
from .store import ConversationStore

__layer__ = "lanes"

ROUTES_FILE = "native_conversation_routes.db"


def profile_home(profile: str) -> Path:
    from hermes_cli.profiles import get_profile_dir, profile_exists

    if not profile_exists(profile):
        raise ConversationError(Refusal.UNAVAILABLE)
    return get_profile_dir(profile)


class LegacyRoutes:
    def __init__(self, root: Path, install_id: str, *, profile_home=profile_home):
        self.root, self.install_id = root.resolve(), install_id
        self.store = ConversationStore(self.root / ROUTES_FILE)
        # A turn a retired worker left dispatching or running is unknown now: no worker of this serve runs one.
        self.store.recover()
        self.profile_home = profile_home
        self._lock = threading.RLock()

    def _owned_route(self, scope: ConversationScope, session_id: str):
        route = self.store.get(session_id, scope)
        if self.profile_home(scope.profile).resolve(strict=True) != Path(route.home):
            raise ConversationError(Refusal.WRONG_OWNER)
        return route

    def migrate(self, scope: ConversationScope, session_id: str, params: dict) -> dict:
        """Import the route's transcript into the instance ``params`` names; idempotent per route."""
        from .migration import migrate_conversation, migration_target

        route = self._owned_route(scope, session_id)
        target = migration_target(scope, params)
        with self._lock:
            # A process from before the retirement may still hold a turn of this route: never import
            # under it. Nothing in this serve can start one.
            if (self.store.migration_target(route) is None and self.store.has_turns(route)
                    and execution_possible(route.worker_pid, route.worker_created)):
                raise ConversationError(Refusal.BUSY)
            self.store.reserve_migration(route, target.persona_id, target.id)
            return migrate_conversation(self, scope, route, target)
