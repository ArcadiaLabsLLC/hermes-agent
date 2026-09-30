"""Native conversation capability behind the shared authenticated runtime.

Owns route evidence and worker lifetime, not agent execution or transcripts.
The existing native gateway runs each profile's sessions in its own process.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from . import model_preferences, session_facts
from .bindings import Bindings
from .live import LiveConversation
from .model import (UNSETTLED, ConversationError, ConversationScope, Refusal, TurnState,
                    identifier)
from .store import ConversationStore
from .worker import start_worker
from .workers import Workers
from .process_evidence import execution_possible

__layer__ = "lanes"


class ConversationService:
    def __init__(self, root: Path, install_id: str, *, profile_home: Callable[[str], Path],
                 worker_factory=start_worker, retention_options=None, auth_home: Path | None = None):
        self.root, self.install_id = root.resolve(), install_id
        self.auth_home = auth_home.resolve() if auth_home is not None else None
        self.store = ConversationStore(self.root / "native_conversation_routes.db")
        self.store.recover()
        self.profile_home = profile_home
        self._lock = threading.RLock()
        factory = partial(worker_factory, auth_home=self.auth_home) if self.auth_home is not None else worker_factory
        self._workers = Workers(factory,
            lambda generation, frame: self._bindings.receive(generation, frame),
            lambda generation: self._bindings.lost(generation))
        self._bindings = Bindings(self._attach, self._release, **(retention_options or {}))
        self._draining = False

    def capabilities(self) -> dict:
        return {"version": 2, "install_id": self.install_id, "accepting": not self._draining,
                "execution_identity_guard": True,
                "images": True, "models": True, "skills": True,
                "independent_sessions": True, "disconnect_keeps_work": True}

    def open(self, scope: ConversationScope, *, key: str, cwd: str,
             resume: str | None = None, expected_home: str) -> dict:
        home = self.profile_home(scope.profile).resolve(strict=True)
        if home != Path(expected_home).resolve(strict=True):
            raise ConversationError(Refusal.WRONG_OWNER)
        directory = Path(cwd)
        if not directory.is_absolute() or not directory.is_dir():
            raise ConversationError(Refusal.INVALID_REQUEST)
        with self._lock:
            self._admit()
            route, created = (self.store.get(resume, scope), False) if resume else self.store.reserve(
                scope, identifier(key), str(directory.resolve()), str(home))
        if (route.cwd, route.home) != (str(directory.resolve()), str(home)):
            raise ConversationError(Refusal.WRONG_OWNER)
        with self._bindings.borrow(route, created=created) as live:
            recovered = live.recover()
            inventory = live.peer.call("model.options", {"session_id": live.native_id})
            return {"session_id": route.id, "install_id": self.install_id,
                    "facts": self._facts(route, recovered["recovery"], inventory), **recovered}

    def _attach(self, route, *, created: bool) -> LiveConversation:
        receipt = self.store.latest(route)
        if (receipt and receipt.state in UNSETTLED and
                execution_possible(route.worker_pid, route.worker_created)):
            # A still-live owner cannot be replaced by another profile worker.
            raise ConversationError(Refusal.UNKNOWN)
        # Native sessions intentionally acquire durable history on first send.
        # A lost, provably unused session can be recreated without replaying work.
        created = created or not self.store.has_turns(route)
        worker = self._workers.acquire(route.profile, Path(route.home))
        peer = worker.peer
        params = ({"cwd": route.cwd, "source": "eternia_intelligence"} if created else
                  {"session_id": route.native_id, "observe_only": True, "omit_messages": True,
                   "source": "eternia_intelligence"})
        if created:
            params.update(model_preferences.default_target(Path(route.home), self.auth_home))
        try:
            result = peer.call("session.create" if created else "session.resume", params)
            native_id = identifier(result["session_id"])
            stored_id = result.get("stored_session_id") or result.get("session_key")
            if created:
                route = self.store.replace_unused(route, identifier(stored_id))
            elif stored_id and stored_id != route.native_id and result.get("resumed") != route.native_id:
                raise ConversationError(Refusal.WRONG_OWNER)
            self.store.worker(route, *peer.process_identity)
            return LiveConversation(route, native_id, worker, self.store)
        except Exception:
            self._workers.release(route.profile, worker)
            raise

    def _release(self, live):
        self._workers.release(live.route.profile, live.worker)

    @contextmanager
    def _session(self, scope: ConversationScope, session_id: str) -> Iterator[LiveConversation]:
        route = self.store.get(session_id, scope)
        if self.profile_home(scope.profile).resolve(strict=True) != Path(route.home):
            raise ConversationError(Refusal.WRONG_OWNER)
        with self._bindings.borrow(route) as live:
            yield live

    def send(self, scope: ConversationScope, session_id: str, turn_id: str, prompt: dict) -> dict:
        from .prompt import submit, validate

        validate(prompt)
        with self._session(scope, session_id) as live, live.operations:
            with self._lock:
                self._admit()
                if not live.peer.alive:
                    raise ConversationError(Refusal.WORKER_LOST)
                receipt, admitted = self.store.admit(live.route, identifier(turn_id), prompt)
            if admitted:
                try:
                    submit(live.peer, live.native_id, prompt, receipt.execution_id)
                    live.dispatched(turn_id)
                    self.store.settle(session_id, turn_id, TurnState.RUNNING)
                except ConversationError as exc:
                    # Admission may precede an error reply; never infer no execution.
                    self.store.settle(session_id, turn_id, TurnState.UNKNOWN)
                    raise exc
                receipt = self.store.turn(live.route, turn_id)
            return {"turn_id": turn_id, "state": receipt.state}

    def read(self, scope: ConversationScope, session_id: str, cursor: int,
             turn_id: str | None = None, *, epoch: str | None = None, offset: int = 0) -> dict:
        with self._session(scope, session_id) as live:
            return live.snapshot(cursor, turn_id, epoch=epoch, offset=offset)

    def observe_execution(self, scope: ConversationScope, session_id: str, turn_id: str) -> dict:
        """Read the exact native outcome and its outstanding questions; never dispatch."""
        if self.store.find_route(session_id, scope) is None:
            return {"admitted": False}
        with self._session(scope, session_id) as live, live.operations:
            if self.store.find_turn(live.route, turn_id) is None:
                return {"admitted": False}
            snapshot = live.recover(turn_id)
            requests = live.peer.call("session.events.since", {
                "session_id": live.native_id, "include_events": False})
            return {**snapshot, "admitted": True, "requests": requests.get("open_requests", [])}

    def history(self, scope: ConversationScope, session_id: str, position: dict,
                message_index: int, offset: int) -> dict:
        with self._session(scope, session_id) as live:
            return live.peer.call("session.recovery.history", {"session_id": live.native_id,
                "position": position, "message_index": message_index, "offset": offset})

    def inflight(self, scope: ConversationScope, session_id: str, params: dict) -> dict:
        with self._session(scope, session_id) as live:
            return live.peer.call("session.recovery.inflight", {"session_id": live.native_id,
                **{key: params[key] for key in ("execution_id", "field", "through", "offset", "revision")}})

    def stop(self, scope: ConversationScope, session_id: str, turn_id: str) -> dict:
        with self._session(scope, session_id) as live:
            receipt = self.store.turn(live.route, turn_id)
            if receipt.state in UNSETTLED:
                live.stop(turn_id)
            # Stop bypasses provider admission. Only native completion settles it.
            return live.receipt(turn_id)["turn"]

    def respond(self, scope: ConversationScope, session_id: str, request_id: str, result: dict) -> dict:
        with self._session(scope, session_id) as live:
            return {"accepted": live.answer(identifier(request_id), result)}

    def facts(self, scope: ConversationScope, session_id: str) -> dict:
        with self._session(scope, session_id) as live:
            snapshot = live.peer.call("session.recover", {"session_id": live.native_id})
            inventory = live.peer.call("model.options", {"session_id": live.native_id})
            return self._facts(live.route, snapshot, inventory)

    def _facts(self, route, snapshot: dict, inventory: dict) -> dict:
        from hermes_cli.config import is_managed

        return {**session_facts.facts(route.id, snapshot, inventory),
                "default_model_id": model_preferences.default_id(Path(route.home), self.auth_home),
                "can_save_model_default": not is_managed()}

    def select_model(self, scope: ConversationScope, session_id: str, model_id: str,
                     *, save_default: bool = False) -> dict:
        with self._session(scope, session_id) as live, live.operations:
            if live.turn_id is not None:
                raise ConversationError(Refusal.BUSY)
            from hermes_cli.config import is_managed
            if save_default and is_managed():
                raise ConversationError(Refusal.NATIVE_REFUSAL)
            inventory = live.peer.call("model.options", {"session_id": live.native_id})
            session_facts.select(live.peer, live.native_id, model_id, inventory, save_default=save_default)
            confirmed = self.facts(scope, session_id)
            if (confirmed["current_model_id"] != model_id or
                    (save_default and confirmed["default_model_id"] != model_id)):
                raise ConversationError(Refusal.UNKNOWN)
            return confirmed

    def skills(self, scope: ConversationScope, session_id: str, operation: str,
               skill_id: str | None = None) -> dict:
        with self._session(scope, session_id) as live:
            return live.peer.call("eternia.skills." + operation,
                {"session_id": live.native_id, "skill_id": skill_id})["data"]

    def _admit(self) -> None:
        if self._draining:
            raise ConversationError(Refusal.RUNTIME_STOPPING)

    def begin_drain(self) -> list[str]:
        with self._lock:
            self._draining = True
            # A receipt stays unknown after process death, but a dead worker
            # cannot be killed by draining this service. Keep its history/fence.
            return [row["turn_id"] for row in self.store.unsettled_workers()
                    if execution_possible(row["worker_pid"], row["worker_created"])]

    def begin_idle_drain(self) -> bool:
        """Claim idle atomically with admission; uncertainty is protected work."""
        with self._lock:
            if self.store.unsettled():
                return False
            self._draining = True
            return True

    def pending_count(self) -> int:
        return len(self.store.unsettled())

    def close(self) -> None:
        with self._lock:
            self._draining = True
        self._bindings.close()
        self._workers.close()

    def drain_pending(self, *, close_idle: bool) -> list[str]:
        """An unreadable receipt or unclosed worker holds drain, never kills it."""
        try:
            pending = self.begin_drain()
            if close_idle and not pending:
                self.close()
            return ["conversation:" + key for key in pending]
        except Exception:
            return ["conversation:recovery-unavailable"]
