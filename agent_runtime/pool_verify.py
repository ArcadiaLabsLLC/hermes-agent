"""The ``verify`` a fork-built keep-alive client must pass to land in the TURN's pool (FH-CONN-POOL-TITLE-CALL-RED).

``agent.process_bootstrap.build_keepalive_http_client`` pools sync transports by ``(verify,
proxy, codex-cloud)``, and since the shared-truststore carry (``212458ec8d``,
``agent/ssl_verify.py::resolve_httpx_verify``) the agent's and the auxiliary lane's clients pass
ONE shared ``SSLContext`` — keyed by its identity — where a caller passing the default
``verify=True`` keys a DIFFERENT pool. A fork client built with the default therefore warmed or
used connections the turn never checks out: the idle keeper's ``HEAD`` opened a second pool, and
the anthropic adoption rode its own. :func:`turn_pool_verify` resolves ``verify`` the way the
auxiliary lane does (``agent/auxiliary_client.py::_resolve_aux_verify``: the provider's
``ssl_ca_cert`` / ``ssl_verify`` for that base URL, else the shared default), so every fork
keep-alive client mounts the turn's transport. Any failure answers ``True``, the old behaviour.

Since FH-POOL-VERIFY-KEY-ONE-AUTHORITY ``_shared_transport_key`` keys ``verify=True`` as that shared
default context itself, so the pool no longer depends on this call; what stays here is the
per-provider half — a base URL with its own ``ssl_ca_cert`` / ``ssl_verify`` must get THAT trust,
which ``True`` cannot express.
"""

from __future__ import annotations

from typing import Any

__layer__ = "policy"
__all__ = ["turn_pool_verify"]


def turn_pool_verify(base_url: str) -> Any:
    try:
        from agent.ssl_verify import resolve_httpx_verify
        from hermes_cli.config import get_custom_provider_tls_settings, load_config_readonly

        tls = get_custom_provider_tls_settings(str(base_url or ""), config=load_config_readonly())
        return resolve_httpx_verify(ca_bundle=tls.get("ssl_ca_cert"), ssl_verify=tls.get("ssl_verify"),
                                    base_url=str(base_url or ""))
    except Exception:
        return True
