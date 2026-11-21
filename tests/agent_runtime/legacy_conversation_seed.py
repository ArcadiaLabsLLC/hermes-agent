"""What a retired profile-scoped conversation left on disk, written as its turn path wrote it.

The path that wrote these rows is gone (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT), so
the tests that read or adopt them seed the same bytes: a route with its turn receipts in
``native_conversation_routes.db``, its transcript in the profile's ``state.db``, and a profile group's run
and member rows in the discussion store. Each writer mirrors the retired one's SQL.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from hermes_cli.sqlite_util import transaction

from agent_runtime.conversations.model import ConversationScope, TurnState, conversation_route_id, digest


def seed_turn(store, route, turn_id: str, state: TurnState = TurnState.COMPLETED, payload=None) -> None:
    """One turn receipt, as the retired ``ConversationStore.admit`` + ``settle`` left it."""
    with transaction(store.connect(), immediate=True) as db:
        db.execute("INSERT INTO conversation_turns (conversation_id,turn_id,digest,state,execution_id) "
                   "VALUES(?,?,?,?,?)", (route.id, turn_id, digest(payload or {"text": turn_id}), state,
                                         "native-turn-" + digest([route.id, turn_id])))


def seed_route(store, scope: ConversationScope, key: str, cwd: str, home: Path, *, native_id: str = "",
               turns=(), worker=(os.getpid(), 1.0)):
    """A route as the retired service left it: reserved, bound to its stored native session, its turns settled.
    ``worker`` is the process that ran them; the default names one that is gone (this pid, another start time)."""
    route, _ = store.reserve(scope, key, cwd, str(Path(home).resolve()))
    with transaction(store.connect(), immediate=True) as db:
        db.execute("UPDATE conversation_routes SET native_id=?,worker_pid=?,worker_created=? WHERE id=?",
                   (native_id, worker[0], worker[1], route.id))
    route = store.get(route.id, scope)
    for turn in turns:
        seed_turn(store, route, *turn) if isinstance(turn, tuple) else seed_turn(store, route, turn)
    return route


def seed_transcript(home: Path, session_id: str, messages, *, model: str | None = None,
                    provider: str | None = None) -> None:
    """The route's native session in its profile's ``state.db``, as the gateway stored it."""
    from hermes_state import SessionDB

    with closing(SessionDB(db_path=Path(home) / "state.db")) as db:
        db.create_session(session_id, "eternia_intelligence", model=model,
                          model_config={"provider": provider} if provider else None)
        for role, content in messages:
            db.append_message(session_id, role, content)


def seed_group(db_path: Path, *, install: str, run_id: str, workspace_id: str, actor: str, client: str, cwd: str,
               members, phase: str = "open", name: str = "Saved group") -> dict:
    """A profile group's run and members, as the retired ``run.start_group`` admitted them.

    ``members``: ``(profile, home, display name)`` per member. The member ids, session ids and
    ``initial`` are the retired admission's (``profile_groups.ProfileParticipant`` / ``profile_member``)."""
    from agent_runtime.discussions.run_values import digest as run_digest

    group = {"name": name, "cwd": cwd, "actor": actor, "client": client,
             "settings": {"rounds": 3, "user_participates": True, "allow_invitations": False, "moderator": None},
             "participants": []}
    rows = []
    for ordinal, (profile, home, display) in enumerate(members):
        binding = {"install_id": install, "profile": profile, "home": str(Path(home).resolve()), "name": display}
        group["participants"].append(binding)
        member_id = "m-" + run_digest({"install": install, "profile": profile, "home": binding["home"]})[:24]
        session_id = conversation_route_id(ConversationScope(actor, client, profile), run_id)
        rows.append((run_id, member_id, ordinal, install, profile, display, "agent-" + member_id[2:14],
                     session_id, ordinal, json.dumps(binding, sort_keys=True)))
    now = time.time()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("INSERT INTO mc_discussion_runs VALUES(?,?,?,?,?,1,?,?,?,?,?,?,NULL)",
                     (run_id, workspace_id, None, "legacy-" + run_id, "digest", phase,
                      json.dumps({"group": group}, sort_keys=True), "", actor, now, now))
        conn.executemany("INSERT INTO mc_discussion_members VALUES(?,?,?,?,NULL,NULL,?,?,?,?,?,'active',?)", rows)
    return {"run_id": run_id, "members": [{"member_id": r[1], "profile": r[4], "session_id": r[7]} for r in rows]}


def set_worker(store, route, pid: int, created: float) -> None:
    """The process a route's turns ran in, as the retired service recorded it at attach."""
    with transaction(store.connect(), immediate=True) as db:
        db.execute("UPDATE conversation_routes SET worker_pid=?,worker_created=? WHERE id=?", (pid, created, route.id))
