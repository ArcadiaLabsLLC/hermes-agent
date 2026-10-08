"""Fork gateway extension preparation and native owner registration.

The upstream handler loop stays in server.py: prepare publishes its expected
aliases before that loop, and register installs fork owners afterward.
"""

__layer__ = "lanes"


# The optional handler modules are module-level guarded imports: that shape is the
# bundle profile's seam (``scripts/bundle_profile_closure._imports`` reads eager +
# guarded as "not pinned"); a lazy import inside ``prepare`` would read as the phone
# turn reaching into code its wheel does not ship.
try:
    from tui_gateway import methods_connectors as _methods_connectors
    from tui_gateway import methods_connectors_account as _methods_connectors_account
except ImportError:  # fork seam: phone wheel — the connectors RPCs (pydantic contracts) are not shipped
    _methods_connectors = _methods_connectors_account = None
try:
    from tui_gateway import methods_pdf as _methods_pdf
except ImportError as _pdf_exc:  # a bundle that starts no process (the phone) serves no pdf.attach
    # `from tui_gateway import x` reports a missing submodule as ImportError(name=<package>); anything
    # methods_pdf itself fails to import carries another name and still raises.
    if _pdf_exc.name not in ("tui_gateway", "tui_gateway.methods_pdf"):
        raise
    _methods_pdf = None


def prepare(server) -> None:
    """Preserve bundled connector/PDF omissions and server namespace aliases."""
    connectors, connectors_account, pdf = _methods_connectors, _methods_connectors_account, _methods_pdf
    if connectors is None:
        from types import SimpleNamespace

        def _no_connector_rpcs(server):  # rpc_dispatch reads the set; no connector method is served
            server._CONNECTOR_RPC_METHODS = frozenset()

        connectors = connectors_account = SimpleNamespace(register=_no_connector_rpcs)
        server.SimpleNamespace = SimpleNamespace
        server._no_connector_rpcs = _no_connector_rpcs
    server._methods_connectors = connectors
    server._methods_connectors_account = connectors_account
    if pdf is None:
        from types import SimpleNamespace

        pdf = SimpleNamespace(register=lambda server: None)
        server.SimpleNamespace = SimpleNamespace
    server._methods_pdf = pdf


def register(server) -> None:
    """Install the existing recovery/retirement owners in their original order."""
    from tui_gateway import session_recovery
    server._session_recovery = session_recovery
    session_recovery.register(server)
    from tui_gateway import session_retirement
    server._session_retirement = session_retirement
    session_retirement.register(server)
