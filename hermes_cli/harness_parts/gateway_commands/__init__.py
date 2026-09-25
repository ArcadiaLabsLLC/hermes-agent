"""The operator's door onto the gateway's credentials (Stage 1 devices, Stage 6 peers).

Seven verbs — ``harness gateway pair``, ``devices list``, ``devices revoke
<device_id>``, and Stage 6's ``peers pair`` / ``peers join`` / ``peers list`` /
``peers revoke <peer_install_id>`` — sitting beside Stage 0b's ``id`` /
``rename`` in the same subtree, because they answer questions about THIS
machine's runtime root rather than about anything in the store.

They hold no rule of their own. What a code may be, how long it lives, how many
may be outstanding, what a lockout is, and when a device is refused are all
decided in :mod:`agent_runtime.serve_gateway_auth`, because the serve process
enforces the same rules over the wire and two answers to "is this code still
good" is the whole failure this lane exists to prevent.

R3, as ruled: **QR plus typed-code fallback, CLI-first.** So one run prints
both — the eight characters an operator reads onto a phone by hand with the
``host:port`` they need beside them, and the JSON payload a phone scans:
``{host, port, install_id, cert_fingerprint, code}``. Same code, same endpoint,
one mint. The launcher's own pairing screen arrives with the Stage 4/5 UI and
will call the same store.

**The code is a short-TTL channel, and stdout is the channel.** It is printed
once, to the operator who asked, and it is never logged, never written to the
store in the clear, and never recoverable — a lost code is re-minted, which is
the intended failure mode and the reason the TTL can be short.

No authorization gate, and — as in Stage 0b — that is written down rather than
left absent. These verbs have ONE door: there is no ``gateway.*`` RPC method for
them, so there is no wire twin that could answer differently, which is the exact
condition the A4 mirror exists to prevent. The caller is the operator at the
install's own shell, and under Ruling A that operator IS the account-auth trace
the device tier descends from: a `CLI_CONSOLE` check here would gate a door
against a predicate that allows every caller that can reach it. When a paired
DEVICE may pair another device, the door is a `gateway.*` method with a tier
declaration and the gate goes there, where the caller is something the transport
proved.

Stage 6 and "agents can never mint peers" (R5) — what the CLI-only shape buys
------------------------------------------------------------------------------

R5 is ADOPTED (primary plan §5): every install⇄install edge is explicitly
approved on BOTH sides, and agents can never initiate pairing. The four peer
verbs are the operator's half of that, and their being CLI verbs is what
enforces the second clause **against remote callers, structurally**:

* there is no ``gateway.*`` RPC method for any of them, so the method lane has
  nothing to call — a peer or device holding any tier finds no name;
* and the argv lane, which is where a CLI verb would otherwise be reachable
  over the wire, is REFUSED outright to every gateway connection (Stage 1,
  ``serve.py``'s ``argv_lane_unavailable``). So "send the verb as argv" is not
  a second door standing beside a missing method; it is a door that answers one
  typed error.

Together those close the remote half completely: no caller on the gateway
listener, at any tier, on either lane, can mint a peer anywhere.

**The residual, named rather than claimed closed.** A LOCAL agent with shell
access on this machine can run these verbs — exactly as it can run ``harness
gateway pair``, read ``serve_auth_token``, or open ``peers.json`` in an editor.
Every tool-using agent on an install already holds the machine owner's
authority; that is what ``CALLER_STDIO_OWNER``'s docstring says, and it is no
less true here. So the accurate claim is: *no agent on install A can cause
install B to trust it* — because minting a code on A does nothing until a human
at B types it into ``peers join`` — *and no remote caller of any tier can mint a
peer anywhere.* An agent that has already taken over the machine its operator is
sitting at was never a case this ceremony could fix, and writing "agents cannot
mint peers" without that sentence beside it would put a false claim in the file
an auditor would read first.

The package map (program rule 16; layout sheet ``gateway_commands.md`` §1)
---------------------------------------------------------------------------

The file was two things and the split is the sheet: the seven operator verbs
stay here, and the address & dial POLICY moved DOWN to
``agent_runtime.gateway_endpoints`` — which is what deletes the runtime's
upward import (``gateway_peers.dial`` reached up into this module for the
candidate list and the R-D20 classifier).

============  ======  ========================================================
module        layer   owns
============  ======  ========================================================
join_payload  policy  the ``peers join`` payload grammar
refusals      lanes   ``StoreRefusal`` -> harness error, the operator sentences,
                      the grant payload's shape, ``_dial_target``
devices       lanes   ``pair``, ``devices list``, ``devices revoke``
introduce     lanes   ``peers pair``, ``introduce``
join          lanes   ``peers join``
peers         lanes   ``peers list``, ``peers revoke``
============  ======  ========================================================

Entry points (the parser's ``func=`` targets, read as attributes of this
package by ``parser/machine.py``) and the modules an agent opens:
``pair`` / ``devices list`` / ``devices revoke`` — devices, refusals,
gateway_endpoints; ``peers pair`` / ``introduce`` — introduce, refusals,
gateway_endpoints; ``peers join`` — join, join_payload, refusals;
``peers list`` / ``peers revoke`` — peers, refusals.

Stores written: none directly — every write is ``agent_runtime.gateway_peers``'
or ``serve_gateway_auth``'s, through their public doors.

Re-exported below: the eight ``cmd_*`` (the parser's ``func=`` targets), the
``__all__`` names (the R-D20 words and ``classify_dial_error``, which live in
``agent_runtime.gateway_endpoints``), and the refusal vocabulary the tests pin.
The address policy is imported from ``agent_runtime.gateway_endpoints``, never
from here.
"""

from __future__ import annotations

from agent_runtime.gateway_endpoints import (  # noqa: F401
    DIAL_LOCAL_POLICY,
    DIAL_UNREACHABLE,
    classify_dial_error,
)

from .devices import (  # noqa: F401
    cmd_gateway_devices_list,
    cmd_gateway_devices_revoke,
    cmd_gateway_pair,
)
from .introduce import (  # noqa: F401
    cmd_gateway_introduce,
    cmd_gateway_peers_pair,
)
from .join import cmd_gateway_peers_join  # noqa: F401
from .peers import (  # noqa: F401
    cmd_gateway_peers_list,
    cmd_gateway_peers_revoke,
)
from .refusals import (  # noqa: F401
    _REFUSAL_CODES,
    _STORE_WRITE_REASONS,
    GRANT_PAYLOAD_KEYS,
    GRANT_PAYLOAD_MAX_BYTES,
    LISTENER_OFF_SENTENCE,
    NO_DIAL_HOST_SENTENCE,
)

__layer__ = "wiring"

__all__ = [
    "cmd_gateway_introduce",
    "cmd_gateway_pair",
    "cmd_gateway_devices_list",
    "cmd_gateway_devices_revoke",
    "cmd_gateway_peers_pair",
    "cmd_gateway_peers_join",
    "cmd_gateway_peers_list",
    "cmd_gateway_peers_revoke",
    "classify_dial_error",
    "DIAL_LOCAL_POLICY",
    "DIAL_UNREACHABLE",
]
