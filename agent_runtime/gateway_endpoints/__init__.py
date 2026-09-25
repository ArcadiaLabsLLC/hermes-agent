"""Where the other install should dial this one — the address & dial POLICY.

Moved DOWN out of ``hermes_cli.harness_parts.gateway_commands`` (layout sheet
``gateway_commands.md`` §1) so the runtime's own dial (``gateway_peers.dial``)
and the serve boot's announce stop importing the CLI. Nothing in this package
imports ``hermes_cli`` except the one public upstream read inside
``gateway_listen_config`` (``hermes_cli.config.load_config_readonly``, lazy).

The package map (program rule 16), lowest layer first — no module imports one
above it (W0-G6):

==========  ======  ==========================================================
module      layer   owns
==========  ======  ==========================================================
addresses   policy  the offer filter, RFC1918 / same-/24 / same-/64 tests, the
                    dial-order rank, R-D20's two words and their errno sets
routes      stores  the routing table's owner of ``0.0.0.0/0`` (R-D8): one
                    bounded spawn per platform question, three parsers
candidates  stores  ``gateway_listen_config``, the listener endpoint, this
                    machine's addresses in dial order, the candidate list, the
                    one dial host, and ``classify_dial_error``
==========  ======  ==========================================================

Entry points and the modules an agent opens: ``_candidate_endpoints`` /
``_dial_host`` / ``_endpoint`` (callers: ``gateway_peers.dial``,
``serve/boot_phases``, ``gateway id``, the payload writers) — candidates,
routes, addresses; ``classify_dial_error`` (caller: ``gateway_peers.dial``,
``peers join``) — candidates, addresses.

Stores written: none. ``routes`` spawns ``route`` / ``ip`` / ``ifconfig`` and
``candidates`` opens a datagram socket that sends nothing; both read only.
"""

from __future__ import annotations

from .addresses import (  # noqa: F401
    DIAL_LOCAL_POLICY,
    DIAL_UNREACHABLE,
    LOCAL_POLICY_SENTENCE,
    MAX_CANDIDATE_ENDPOINTS,
)
from .candidates import (  # noqa: F401
    _candidate_endpoints,
    _dial_host,
    _endpoint,
    _machine_addresses,
    _self_endpoints,
    classify_dial_error,
    gateway_listen_config,
)

__layer__ = "stores"

__all__ = [
    "DIAL_LOCAL_POLICY",
    "DIAL_UNREACHABLE",
    "LOCAL_POLICY_SENTENCE",
    "MAX_CANDIDATE_ENDPOINTS",
    "classify_dial_error",
    "gateway_listen_config",
]
