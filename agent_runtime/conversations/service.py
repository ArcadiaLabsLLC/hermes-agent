"""Native conversation capability behind the shared authenticated runtime.

Owns route evidence and worker lifetime, not agent execution or transcripts.
The existing native gateway runs each profile's sessions in its own process.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from . import session_facts
from .live import LiveConversation
from .model import (ConversationError, ConversationScope, Refusal, TurnState,
                    identifier)
from .store import ConversationStore
from .worker import start_worker
from .workers import Workers
from .process_evidence import execution_possible

__layer__ = "lanes"


class ConversationService:
    def __init__(self, root: Path, install_id: str, *, profile_home: Callable[[str], Path],
                 worker_factory=start_worker):
        self.root, self.install_id = root.resolve(), install_id
        self.store = ConversationStore(self.root / "native_conversation_routes.db")
        self.store.recover()
        self.profile_home = profile_home
        self._lock = threading.RLock()
        self._opening: dict[str, threading.Lock] = {}
        self._workers = Workers(worker_factory, self._receive, self._lost)
        self._live: dict[str, LiveConversation] = {}
        self._sessions: dict[tuple[str, str], LiveConversation] = {}
        self._draining = False

    def capabilities(self) -> dict:
        return {"version": 1, "install_id": self.install_id, "accepting": not self._draining,
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
            opening = self._opening.setdefault(route.id, threading.Lock())
        with opening:
            if (route.cwd, route.home) != (str(directory.resolve()), str(home)):
                raise ConversationError(Refusal.WRONG_OWNER)
            live = self._live.get(route.id)
            if live is None or not live.peer.alive:
                live = self._attach(route, home, created=created)
            return {"session_id": route.id, "install_id": self.install_id,
                    "facts": self.facts(scope, route.id), **live.snapshot(0)}

    def _attach(self, route, home: Path, *, created: bool) -> LiveConversation:
        if any(turn.conversation_id == route.id for turn in self.store.unsettled()):
            # A dead worker cannot be made safe by silently replaying/resuming.
            raise ConversationError(Refusal.UNKNOWN)
        # Native sessions intentionally acquire durable history on first send.
        # A lost, provably unused session can be recreated without replaying work.
        created = created or not self.store.has_turns(route)
        worker = self._workers.get(route.profile, home)
        peer = worker.peer
        params = ({"cwd": route.cwd, "source": "eternia_intelligence"} if created else
                  {"session_id": route.native_id, "lazy": True, "omit_messages": True,
                   "source": "eternia_intelligence"})
        result = peer.call("session.create" if created else "session.resume", params)
        native_id = identifier(result["session_id"])
        stored_id = result.get("stored_session_id") or result.get("session_key")
        if created:
            route = self.store.replace_unused(route, identifier(stored_id))
        elif stored_id and stored_id != route.native_id and result.get("resumed") != route.native_id:
            raise ConversationError(Refusal.WRONG_OWNER)
        live = LiveConversation(route, native_id, peer, self.store)
        self.store.worker(route, *peer.process_identity)
        with self._lock:
            self._live[route.id] = live
            self._sessions[(worker.generation, native_id)] = live
        return live

    def _receive(self, generation: str, frame: dict) -> None:
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            return
        with self._lock:
            native_id = params.get("session_id")
            live = self._sessions.get((generation, native_id)) if isinstance(native_id, str) else None
        if live is not None:
            live.receive(frame)

    def _lost(self, generation: str) -> None:
        with self._lock:
            sessions = [live for (owner, _), live in self._sessions.items() if owner == generation]
        for live in sessions:
            live.lost()

    def _session(self, scope: ConversationScope, session_id: str) -> LiveConversation:
        route = self.store.get(session_id, scope)
        if self.profile_home(scope.profile).resolve(strict=True) != Path(route.home):
            raise ConversationError(Refusal.WRONG_OWNER)
        with self._lock:
            live = self._live.get(session_id)
        if live is None:
            raise ConversationError(Refusal.UNAVAILABLE)
        return live

    def send(self, scope: ConversationScope, session_id: str, turn_id: str, prompt: dict) -> dict:
        from .prompt import submit, validate

        validate(prompt)
        live = self._session(scope, session_id)
        with live.operations:
            with self._lock:
                self._admit()
                if not live.peer.alive:
                    raise ConversationError(Refusal.WORKER_LOST)
                receipt, admitted = self.store.admit(live.route, identifier(turn_id), prompt)
            if admitted:
                live.start(turn_id)
                try:
                    submit(live.peer, live.native_id, prompt)
                    live.dispatched(turn_id)
                    self.store.settle(session_id, turn_id, TurnState.RUNNING)
                except ConversationError as exc:
                    # Admission may precede an error reply; never infer no execution.
                    self.store.settle(session_id, turn_id, TurnState.UNKNOWN)
                    raise exc
                receipt = self.store.turn(live.route, turn_id)
            return {"turn_id": turn_id, "state": receipt.state}

    def read(self, scope: ConversationScope, session_id: str, cursor: int,
             turn_id: str | None = None) -> dict:
        live = self._session(scope, session_id)
        return live.snapshot(cursor, turn_id)

    def stop(self, scope: ConversationScope, session_id: str, turn_id: str) -> dict:
        live = self._session(scope, session_id)
        receipt = self.store.turn(live.route, turn_id)
        if receipt.state in (TurnState.DISPATCHING, TurnState.RUNNING):
            live.stop(turn_id)
        # Never wait behind provider admission to request Stop. Native completion
        # alone settles it; a transport write is not confirmation.
        return {"turn_id": turn_id, "state": self.store.turn(live.route, turn_id).state}

    def respond(self, scope: ConversationScope, session_id: str, request_id: str, result: dict) -> dict:
        live = self._session(scope, session_id)
        live.answer(identifier(request_id), result)
        return {"accepted": True}

    def facts(self, scope: ConversationScope, session_id: str) -> dict:
        live = self._session(scope, session_id)
        snapshot = live.peer.call("session.activate", {"session_id": live.native_id, "omit_messages": True})
        inventory = live.peer.call("model.options", {"session_id": live.native_id})
        return session_facts.facts(session_id, snapshot, inventory)

    def select_model(self, scope: ConversationScope, session_id: str, model_id: str) -> dict:
        live = self._session(scope, session_id)
        with live.operations:
            if live.turn_id is not None:
                raise ConversationError(Refusal.BUSY)
            inventory = live.peer.call("model.options", {"session_id": live.native_id})
            session_facts.select(live.peer, live.native_id, model_id, inventory)
            confirmed = self.facts(scope, session_id)
            if confirmed["current_model_id"] != model_id:
                raise ConversationError(Refusal.UNKNOWN)
            return confirmed

    def skills(self, scope: ConversationScope, session_id: str, operation: str,
               skill_id: str | None = None) -> dict:
        live = self._session(scope, session_id)
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

    def close(self) -> None:
        with self._lock:
            self._draining = True
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
