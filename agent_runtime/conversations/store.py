"""Durable route and dispatch receipts, never a second transcript store."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from hermes_cli.sqlite_util import open_db, transaction

from .model import (UNSETTLED, ConversationError, ConversationRoute,
                    ConversationScope, Refusal, TurnReceipt, TurnState, digest, conversation_route_id)

__layer__ = "stores"


class ConversationStore:
    def __init__(self, path: Path):
        self.path = path
        with transaction(self.connect(), immediate=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_routes (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, profile TEXT NOT NULL,
                cwd TEXT NOT NULL, home TEXT NOT NULL, native_id TEXT NOT NULL DEFAULT '',
                worker_pid INTEGER NOT NULL DEFAULT 0, worker_created REAL NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_turns (
                conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                digest TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY(conversation_id,turn_id))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(conversation_turns)")}
            for name, declaration in (("execution_id", "TEXT NOT NULL DEFAULT ''"),
                                      ("cancel_requested", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:
                    db.execute(f"ALTER TABLE conversation_turns ADD COLUMN {name} {declaration}")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS conversation_unsettled
                ON conversation_turns(conversation_id)
                WHERE state IN ('dispatching','running','unknown')""")
            db.execute("""CREATE INDEX IF NOT EXISTS conversation_execution
                ON conversation_turns(conversation_id,execution_id)""")
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_migrations (
                conversation_id TEXT PRIMARY KEY, persona_id TEXT NOT NULL,
                persona_instance_id TEXT NOT NULL)""")

    def connect(self):
        return open_db(self.path, db_label="native conversation receipts", synchronous_full=True)

    def recover(self) -> None:
        """Only the socket-owning service calls this at boot, before admission."""
        with transaction(self.connect(), immediate=True) as db:
            db.execute("UPDATE conversation_turns SET state='unknown' WHERE state IN ('dispatching','running')")

    def reserve(self, scope: ConversationScope, key: str, cwd: str, home: str) -> tuple[ConversationRoute, bool]:
        rid = conversation_route_id(scope, key)
        with transaction(self.connect(), immediate=True) as db:
            row = db.execute("SELECT * FROM conversation_routes WHERE id=?", (rid,)).fetchone()
            if row is not None:
                if (row["cwd"], row["home"]) != (cwd, home):
                    raise ConversationError(Refusal.CONFLICT)
                return ConversationRoute(**dict(row)), False
            db.execute("INSERT INTO conversation_routes(id,owner,profile,cwd,home) VALUES(?,?,?,?,?)",
                       (rid, scope.key, scope.profile, cwd, home))
        return ConversationRoute(rid, scope.key, scope.profile, cwd, home, ""), True

    def get(self, conversation_id: str, scope: ConversationScope) -> ConversationRoute:
        route = self.find_route(conversation_id, scope)
        if route is None:
            raise ConversationError(Refusal.UNAVAILABLE)
        return route

    def find_route(self, conversation_id: str, scope: ConversationScope) -> ConversationRoute | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM conversation_routes WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            return None
        if row["owner"] != scope.key:
            raise ConversationError(Refusal.UNAVAILABLE)
        return ConversationRoute(**dict(row))

    def admit(self, route: ConversationRoute, turn_id: str, payload: dict) -> tuple[TurnReceipt, bool]:
        signature = digest(payload)
        with transaction(self.connect(), immediate=True) as db:
            self._require_executable(db, route.id)
            prior = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? AND turn_id=?",
                               (route.id, turn_id)).fetchone()
            if prior is not None:
                if prior["digest"] != signature:
                    raise ConversationError(Refusal.CONFLICT)
                return _receipt(prior), False
            if db.execute("SELECT 1 FROM conversation_turns WHERE conversation_id=? AND state IN (?,?,?)",
                          (route.id, *UNSETTLED)).fetchone():
                raise ConversationError(Refusal.BUSY)
            execution_id = "native-turn-" + digest([route.id, turn_id])
            db.execute("""INSERT INTO conversation_turns
                (conversation_id,turn_id,digest,state,execution_id) VALUES(?,?,?,?,?)""",
                       (route.id, turn_id, signature, TurnState.DISPATCHING, execution_id))
        return TurnReceipt(route.id, turn_id, signature, TurnState.DISPATCHING, execution_id), True

    def turn(self, route: ConversationRoute, turn_id: str) -> TurnReceipt:
        receipt = self.find_turn(route, turn_id)
        if receipt is None:
            raise ConversationError(Refusal.UNAVAILABLE)
        return receipt

    def find_turn(self, route: ConversationRoute, turn_id: str) -> TurnReceipt | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? AND turn_id=?",
                             (route.id, turn_id)).fetchone()
        return _receipt(row) if row is not None else None

    def settle(self, conversation_id: str, turn_id: str, state: TurnState, *, authoritative=False) -> None:
        with transaction(self.connect(), immediate=True) as db:
            # A late admission reply proves neither recovery nor completion.
            allowed = (TurnState.DISPATCHING,) if state == TurnState.RUNNING and not authoritative else UNSETTLED
            slots = ",".join("?" for _ in allowed)
            db.execute(f"""UPDATE conversation_turns SET state=?
                WHERE conversation_id=? AND turn_id=? AND state IN ({slots})""",
                       (state, conversation_id, turn_id, *allowed))

    def latest(self, route: ConversationRoute) -> TurnReceipt | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1",
                             (route.id,)).fetchone()
        return _receipt(row) if row is not None else None

    def execution(self, route: ConversationRoute, execution_id: str) -> TurnReceipt | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM conversation_turns WHERE conversation_id=? AND execution_id=?",
                             (route.id, execution_id)).fetchone()
        return _receipt(row) if row is not None else None

    def request_cancel(self, route: ConversationRoute, turn_id: str) -> TurnReceipt:
        with transaction(self.connect(), immediate=True) as db:
            db.execute("""UPDATE conversation_turns SET cancel_requested=1
                WHERE conversation_id=? AND turn_id=? AND state IN (?,?,?)""", (route.id, turn_id, *UNSETTLED))
        return self.turn(route, turn_id)

    def has_turns(self, route: ConversationRoute) -> bool:
        with closing(self.connect()) as db:
            return db.execute("SELECT 1 FROM conversation_turns WHERE conversation_id=? LIMIT 1",
                              (route.id,)).fetchone() is not None

    def turn_receipts(self, route: ConversationRoute) -> list[dict]:
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT turn_id,state,cancel_requested FROM conversation_turns WHERE conversation_id=? ORDER BY rowid",
                (route.id,)).fetchall()]

    def replace_unused(self, route: ConversationRoute, native_id: str) -> ConversationRoute:
        """Replace a lost empty native session; never change a dispatched route."""
        with transaction(self.connect(), immediate=True) as db:
            self._require_executable(db, route.id)
            if db.execute("SELECT 1 FROM conversation_turns WHERE conversation_id=? LIMIT 1",
                          (route.id,)).fetchone():
                raise ConversationError(Refusal.UNKNOWN)
            db.execute("UPDATE conversation_routes SET native_id=? WHERE id=? AND owner=?",
                       (native_id, route.id, route.owner))
        return ConversationRoute(route.id, route.owner, route.profile, route.cwd, route.home, native_id)

    def unsettled(self) -> list[TurnReceipt]:
        with closing(self.connect()) as db:
            rows = db.execute("""SELECT t.* FROM conversation_turns t WHERE state IN (?,?,?)
                AND NOT EXISTS (SELECT 1 FROM conversation_migrations m WHERE m.conversation_id=t.conversation_id)""",
                              UNSETTLED).fetchall()
        return [_receipt(row) for row in rows]

    def worker(self, route: ConversationRoute, pid: int, created: float) -> None:
        with transaction(self.connect(), immediate=True) as db:
            db.execute("UPDATE conversation_routes SET worker_pid=?,worker_created=? WHERE id=? AND owner=?",
                       (pid, created, route.id, route.owner))

    def unsettled_workers(self) -> list[dict]:
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute("""SELECT t.turn_id,r.worker_pid,r.worker_created
                FROM conversation_turns t JOIN conversation_routes r ON r.id=t.conversation_id
                WHERE t.state IN (?,?,?) AND NOT EXISTS
                (SELECT 1 FROM conversation_migrations m WHERE m.conversation_id=t.conversation_id)""",
                                                  UNSETTLED).fetchall()]

    @staticmethod
    def _require_executable(db, conversation_id: str) -> None:
        if db.execute("SELECT 1 FROM conversation_migrations WHERE conversation_id=?",
                      (conversation_id,)).fetchone():
            raise ConversationError(Refusal.MIGRATED)

    def require_executable(self, route: ConversationRoute) -> None:
        with closing(self.connect()) as db:
            self._require_executable(db, route.id)

    def migration_target(self, route: ConversationRoute) -> tuple[str, str] | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT persona_id,persona_instance_id FROM conversation_migrations "
                             "WHERE conversation_id=?", (route.id,)).fetchone()
        return tuple(row) if row is not None else None

    def reserve_migration(self, route: ConversationRoute, persona_id: str, instance_id: str) -> None:
        """Fence old sends durably before importing; retries cannot retarget the route."""
        with transaction(self.connect(), immediate=True) as db:
            prior = db.execute("SELECT persona_id,persona_instance_id FROM conversation_migrations "
                               "WHERE conversation_id=?", (route.id,)).fetchone()
            if prior is not None:
                if tuple(prior) != (persona_id, instance_id):
                    raise ConversationError(Refusal.CONFLICT)
                return
            # UNKNOWN is preserved after the caller proves its worker is gone.
            # A new dispatch racing the snapshot must still refuse this fence.
            if db.execute("SELECT 1 FROM conversation_turns WHERE conversation_id=? AND state IN (?,?)",
                          (route.id, TurnState.DISPATCHING, TurnState.RUNNING)).fetchone():
                raise ConversationError(Refusal.UNKNOWN)
            db.execute("INSERT INTO conversation_migrations VALUES(?,?,?)", (route.id, persona_id, instance_id))


def _receipt(row) -> TurnReceipt:
    return TurnReceipt(row["conversation_id"], row["turn_id"], row["digest"], TurnState(row["state"]),
                       row["execution_id"], bool(row["cancel_requested"]))
