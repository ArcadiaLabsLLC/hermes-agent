"""Native history uses the existing route owner, without borrowing a worker."""
from contextlib import closing
from pathlib import Path

from agent_runtime.subagents.history import inspect_history
from agent_runtime.subagents.model import Refusal, SubagentError

__layer__ = "lanes"


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
    from hermes_state import SessionDB

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

    with closing(SessionDB(db_path=db_path, read_only=True)) as db:
        data = inspect_history(operation, params, owner=(tuple(sorted(identity.items())), route.owner, route.native_id),
                               db=db, session_id=route.native_id, home=home, revalidate=revalidate,
                               delegation_db_path=delegation_db_path)
    return {**identity, **data}
