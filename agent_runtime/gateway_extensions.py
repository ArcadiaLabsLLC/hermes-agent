"""Fork gateway extension preparation and native owner registration.

The upstream handler loop stays in server.py: prepare publishes its expected
aliases before that loop, and register installs fork owners afterward.
"""

__layer__ = "lanes"

from agent_runtime.gateway.contract_seam import catalog_forced_in_this_process


# The optional handler modules are module-level guarded imports: that shape is the
# bundle profile's seam (``scripts/bundle_profile_closure._imports`` reads eager +
# guarded as "not pinned"); a lazy import inside ``prepare`` would read as the phone
# turn reaching into code its wheel does not ship.
try:
    if catalog_forced_in_this_process():
        # A conversation worker (agent_runtime.conversations.worker_entry) reads the generated catalog:
        # the serve forwards it no connectors.* method, and methods_connectors_account would import
        # pydantic's whole contract package at module level (RT-WORKER-BOOT-PYDANTIC-CONTRACTS).
        raise ImportError("connector RPCs are served by the serve, not by a catalog worker")
    from tui_gateway import methods_connectors as _methods_connectors
    from tui_gateway import methods_connectors_account as _methods_connectors_account
except ImportError:  # fork seam: phone wheel — the connectors RPCs (pydantic contracts) are not shipped
    _methods_connectors = _methods_connectors_account = None


def prepare(server) -> None:
    """Preserve bundled connector omissions and server namespace aliases."""
    connectors, connectors_account = _methods_connectors, _methods_connectors_account
    if connectors is None:
        from types import SimpleNamespace

        def _no_connector_rpcs(server):  # rpc_dispatch reads the set; no connector method is served
            server._CONNECTOR_RPC_METHODS = frozenset()

        connectors = connectors_account = SimpleNamespace(register=_no_connector_rpcs)
        server.SimpleNamespace = SimpleNamespace
        server._no_connector_rpcs = _no_connector_rpcs
    server._methods_connectors = connectors
    server._methods_connectors_account = connectors_account


def register(server) -> None:
    """Install fork methods once for every native gateway execution host."""
    from agent_runtime.spawn_stand_ins import drop_phone_methods
    drop_phone_methods(server)  # the phone serves no method that must start a process (pdf.attach)
    from agent_runtime.gateway import session_recovery
    server._session_recovery = session_recovery
    session_recovery.register(server)
    from agent_runtime.gateway import session_retirement
    server._session_retirement = session_retirement
    session_retirement.register(server)
    from agent_runtime.gateway import ssh_remote_cwd
    ssh_remote_cwd.register(server)
    from agent_runtime.conversations import worker_subagents
    worker_subagents.register(server)
    from agent_runtime.conversations import worker_permissions
    worker_permissions.register(server)
