"""Profile settings use the owned route, without an execution-worker borrow."""
from pathlib import Path
from agent_runtime.profile_context import process_home_scope
from agent_runtime.subagents.model import Refusal, SubagentError
from agent_runtime.subagents.settings import inspect_settings

__layer__ = "lanes"


def inspect_profile_defaults(service, scope, route, operation, params):
    identity = {"install_id": service.install_id, "session_id": route.id,
                "client_scope": scope.client, "profile": scope.profile}
    home = Path(route.home)

    def revalidate():
        current = service._owned_route(scope, route.id)
        if (current.owner, current.home, current.native_id) != (route.owner, route.home, route.native_id):
            raise SubagentError(Refusal.WRONG_OWNER)

    with process_home_scope(home):
        data = inspect_settings(operation, params, owner=(tuple(sorted(identity.items())), str(home), route.owner),
                                profile_label=scope.profile, revalidate=revalidate)
    return {**identity, **data}
