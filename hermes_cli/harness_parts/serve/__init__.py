"""``hermes harness serve`` — the package map (program rule 16).

Entry points (what calls in):

* ``commands._cmd_serve`` / ``commands._cmd_serve_connect`` — the two CLI verbs
  the parser wires through ``harness_parts.parser.machine``'s trampolines (lazily,
  so no other verb pays serve's import).
* ``session.serve_loop`` — the dispatch loop over explicit streams; every serve test
  and the two field tools drive it directly.
* ``argv_lane.dispatch_argv`` — one argv request through the harness parser,
  which the ``serve`` trampoline binds (``bind_harness_parser``) so no part of
  this package imports the parser package.
* ``frames.current_serve_request_id`` — read by the harness verbs to learn the
  request they run under.
* ``gateway_listener.gateway_listen_config`` — read by ``gateway_commands``.

Modules, lowest layer first (no module imports one above it — W0-G6):

==================  ======  ====================================================
module              layer   owns
==================  ======  ====================================================
constants           models  the wire protocol (its docstring), the ``OPS``
                            vocabulary and every constant
manifest            policy  ``ops_manifest``, the pairing block, the gateway test
end_reason          stores  ``EndReason``; signal / console-ctrl hooks; recorder
frames              stores  frame writer, line proxies, poll cache, request ids
argv_lane           lanes   ``_ArgvRequest``, the parser binding, ``dispatch_argv``
gateway_listener    lanes   listen config, listener start, hello authenticator
boot                lanes   fingerprint, prewarms, skill install, boot fault
drain               lanes   ``_DrainState``, deadline policy, ``DrainLane``
lanes               lanes   ``ArgvLanes``: ``_run`` and the two pool seams
subscriptions       lanes   ``SubscriptionLanes``: stream hub, fold room, sockets
handle_message      lanes   ``MessageHandling`` and the ``OP_HANDLERS`` table
session             lanes   ``ServeSession``: fields, boot order, liveness;
                            ``serve_loop`` (builds a session, runs it)
commands            lanes   ``_cmd_serve``, ``_cmd_serve_connect``, pipe claim
==================  ======  ====================================================

Stores written: ``<store_root>/serve_instances/`` (through ``serve_registry``),
the end-reason sidecar (through ``serve_registry``), the device and pairing
stores (through ``serve_gateway_credentials`` -> ``serve_gateway_auth`` /
``gateway_peers``). Never imported from here: ``hermes_cli.harness``.

Only PUBLIC names are re-exported below; a private helper is imported from the
module that owns it.

The protocol itself is documented once, in ``constants``' module docstring.
"""

from __future__ import annotations

from hermes_cli.harness_parts.serve.constants import (
    HELLO_OP,
    OPS,
    READER_STOP,
    DEFAULT_DRAIN_DEADLINE_SECONDS,
    DEFAULT_POOL_SIZE,
    DRAINING_EXIT_CODE,
    DRAIN_TIMEOUT_EXIT_CODE,
    FINGERPRINT_HOME_BOOT_SITE,
    GATEWAY_TRANSPORT,
    OPS_CONTRACT_VERSION,
    OPS_EVERY_TRANSPORT,
    OPS_GATEWAY_DENIED,
    OPS_STDIO_ONLY,
    SERVE_SCHEMA_VERSION,
    SUBSCRIBE_LANES,
)
from hermes_cli.harness_parts.serve.manifest import (
    ops_manifest,
)
from hermes_cli.harness_parts.serve.end_reason import (
    EndReason,
    CONSOLE_CTRL_END_REASONS,
    END_REASON_UNCAUGHT_PREFIX,
    END_REASON_UNKNOWN,
    END_REASON_VOCABULARY,
    SIGNAL_END_REASONS,
)
from hermes_cli.harness_parts.serve.frames import (
    current_serve_request_id,
)
from hermes_cli.harness_parts.serve.drain import (
    DrainLane,
)
from hermes_cli.harness_parts.serve.argv_lane import (
    ARGV_ROOT,
    ArgvRootUnsupported,
    HandlerExit,
    dispatch_argv,
)
from hermes_cli.harness_parts.serve.gateway_listener import (
    GATEWAY_OUTCOME_SOCKET_UNAVAILABLE,
    gateway_block_when_no_listener,
    gateway_listen_config,
    start_gateway_listener,
)
from hermes_cli.harness_parts.serve.boot import (
    BOOT_FAULT_ENV_VAR,
    install_harness_skills_at_boot,
)
from hermes_cli.harness_parts.serve.lanes import (
    ArgvLanes,
)
from hermes_cli.harness_parts.serve.subscriptions import (
    SubscriptionLanes,
)
from hermes_cli.harness_parts.serve.handle_message import (
    OP_HANDLERS,
    MessageHandling,
    SubscribeOptions,
    parse_subscribe_options,
)
from hermes_cli.harness_parts.serve.session import (
    ServeSession,
    serve_loop,
)
from hermes_cli.harness_parts.serve.commands import (
    SERVE_CONNECT_NO_SERVICE_EXIT_CODE,
    SERVE_CONNECT_REJECTED_EXIT_CODE,
    SERVE_CONNECT_TRANSPORT_EXIT_CODE,
)

__layer__ = "lanes"

__all__ = [
    "HELLO_OP",
    "OPS",
    "READER_STOP",
    "DEFAULT_DRAIN_DEADLINE_SECONDS",
    "DEFAULT_POOL_SIZE",
    "DRAINING_EXIT_CODE",
    "DRAIN_TIMEOUT_EXIT_CODE",
    "FINGERPRINT_HOME_BOOT_SITE",
    "GATEWAY_TRANSPORT",
    "OPS_CONTRACT_VERSION",
    "OPS_EVERY_TRANSPORT",
    "OPS_GATEWAY_DENIED",
    "OPS_STDIO_ONLY",
    "SERVE_SCHEMA_VERSION",
    "SUBSCRIBE_LANES",
    "ops_manifest",
    "EndReason",
    "CONSOLE_CTRL_END_REASONS",
    "END_REASON_UNCAUGHT_PREFIX",
    "END_REASON_UNKNOWN",
    "END_REASON_VOCABULARY",
    "SIGNAL_END_REASONS",
    "current_serve_request_id",
    "DrainLane",
    "ARGV_ROOT",
    "ArgvRootUnsupported",
    "HandlerExit",
    "dispatch_argv",
    "GATEWAY_OUTCOME_SOCKET_UNAVAILABLE",
    "gateway_block_when_no_listener",
    "gateway_listen_config",
    "start_gateway_listener",
    "BOOT_FAULT_ENV_VAR",
    "install_harness_skills_at_boot",
    "ArgvLanes",
    "SubscriptionLanes",
    "OP_HANDLERS",
    "MessageHandling",
    "SubscribeOptions",
    "parse_subscribe_options",
    "ServeSession",
    "serve_loop",
    "SERVE_CONNECT_NO_SERVICE_EXIT_CODE",
    "SERVE_CONNECT_REJECTED_EXIT_CODE",
    "SERVE_CONNECT_TRANSPORT_EXIT_CODE",
]
