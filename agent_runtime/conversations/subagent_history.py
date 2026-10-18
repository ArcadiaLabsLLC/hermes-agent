"""Native history uses the existing route owner, without borrowing a worker."""
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from agent_runtime.subagents.history import inspect_history
from agent_runtime.subagents.model import Refusal, SubagentError

__layer__ = "lanes"

#: A ``mode=ro`` open of a WAL store whose writer has just exited can need the -shm recovery
#: a read-only connection cannot run; SQLite answers SQLITE_READONLY with this text until the
#: writer's close finishes (FORK-TEST-OWNED-CHILD-READS). Upstream's read-only open retries only
#: the disk-I/O marker, so the history read retries this one, bounded.
_READONLY_RECOVERY_MARKER = "attempt to write a readonly database"
_READONLY_RECOVERY_ATTEMPTS, _READONLY_RECOVERY_BACKOFF_S = 5, 0.1


def _open_history_db(db_path, *, sleep=time.sleep):
    from hermes_state import SessionDB

    for attempt in range(_READONLY_RECOVERY_ATTEMPTS + 1):
        try:
            return SessionDB(db_path=db_path, read_only=True)
        except sqlite3.OperationalError as exc:
            if attempt >= _READONLY_RECOVERY_ATTEMPTS or _READONLY_RECOVERY_MARKER not in str(exc).lower():
                raise
            sleep(_READONLY_RECOVERY_BACKOFF_S)


def _delegation_db(home):
    # Match the native worker's home context while retaining the canonical
    # explicit head authority used by the async writer.
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from agent_runtime.profile_home import get_hermes_background_work_home

    token = set_hermes_home_override(home)
    try:
        return get_hermes_background_work_home().resolve() / "state.db"
    finally:
        reset_hermes_home_override(token)


def inspect_stored_children(service, scope, route, operation, params):
    identity = {"install_id": service.install_id, "session_id": route.id,
                "client_scope": scope.client, "profile": scope.profile}
    home = Path(route.home)
    db_path = home / "state.db"
    if not db_path.is_file():
        raise SubagentError(Refusal.UNAVAILABLE)
    delegation_db_path = _delegation_db(home)

    def revalidate():
        current = service._owned_route(scope, route.id)
        if ((current.owner, current.home, current.native_id) != (route.owner, route.home, route.native_id)
                or _delegation_db(home) != delegation_db_path):
            raise SubagentError(Refusal.WRONG_OWNER)

    with closing(_open_history_db(db_path)) as db:
        data = inspect_history(operation, params, owner=(tuple(sorted(identity.items())), route.owner, route.native_id),
                               db=db, session_id=route.native_id, home=home, revalidate=revalidate,
                               delegation_db_path=delegation_db_path)
    return {**identity, **data}
