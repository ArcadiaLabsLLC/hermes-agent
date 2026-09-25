"""``hermes harness serve`` — the package map (program rule 16).

Entry points (what calls in):

* ``commands._cmd_serve`` / ``commands._cmd_serve_connect`` — the two CLI verbs
  ``hermes_cli.harness`` wires (lazily, so no other verb pays serve's import).
* ``loop.serve_loop`` — the dispatch loop over explicit streams; every serve test
  and the two field tools drive it directly.
* ``argv_lane.dispatch_argv`` — one argv request through the harness parser.
* ``frames.current_serve_request_id`` — read by the harness verbs to learn the
  request they run under.
* ``gateway_listener.gateway_listen_config`` — read by ``gateway_commands``.

Modules, lowest layer first (no module imports one above it — W0-G6):

==================  ======  ====================================================
module              layer   owns
==================  ======  ====================================================
constants           models  the wire protocol (its docstring) and every constant
manifest            policy  ``ops_manifest``, pairing block, credential kind
end_reason          stores  why the process ended; signal / console-ctrl hooks
frames              stores  frame writer, line proxies, poll cache, request ids
drain               lanes   ``_DrainState`` and the deadline policy
argv_lane           lanes   ``_ArgvRequest``, the parser, ``dispatch_argv``
gateway_listener    lanes   listen config, listener start, hello authenticator
boot                lanes   fingerprint, prewarms, skill install, boot fault
loop                lanes   ``serve_loop``
commands            lanes   ``_cmd_serve``, ``_cmd_serve_connect``, pipe claim
==================  ======  ====================================================

Stores written: ``<store_root>/serve_instances/`` (through ``serve_registry``),
the end-reason sidecar (through ``serve_registry``), the device and pairing
stores (through ``serve_gateway_auth``). Never imported from here:
``hermes_cli.harness`` (the parser reaches the argv lane through a binding).

The protocol itself is documented once, in ``constants``' module docstring.
"""

from __future__ import annotations

from hermes_cli.harness_parts.serve.constants import (
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
    _CACHEABLE_ARGV,
    _CHAT_TURN_COMMANDS,
    _DRAIN_ABANDON_GRACE_SECONDS,
    _DRAIN_DEADLINE_FLOOR_SECONDS,
    _DRAIN_DEADLINE_MAX_SECONDS,
    _DRAIN_EXIT_DEADLINE_SECONDS,
    _DRAIN_POLL_INTERVAL_SECONDS,
    _DRAIN_PROGRESS_INTERVAL_SECONDS,
    _DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS,
    _FINGERPRINT_BOARD_CARD_CAP,
    _FINGERPRINT_ROOT_FILES,
    _FINGERPRINT_STORE_DIRS,
    _LONG_RUN_COMMANDS,
    _READ_CACHE_MAX_AGE_SECONDS,
    _REQUEST_SILENCE_SECONDS,
    _SERVICE_PARK_POLL_SECONDS,
)
from hermes_cli.harness_parts.serve.manifest import (
    _is_gateway,
    _pairing_block,
    ops_manifest,
)
from hermes_cli.harness_parts.serve.gateway_listener import (
    GATEWAY_OUTCOME_SOCKET_UNAVAILABLE,
    gateway_block_when_no_listener,
    gateway_listen_config,
    start_gateway_listener,
)
from hermes_cli.harness_parts.serve.end_reason import (
    CONSOLE_CTRL_END_REASONS,
    END_REASON_UNCAUGHT_PREFIX,
    END_REASON_UNKNOWN,
    END_REASON_VOCABULARY,
    SIGNAL_END_REASONS,
    _CONSOLE_CTRL_HANDLER_KEEPALIVE,
    _ServeEndReason,
    _UNCAUGHT_TYPE_MAX_LENGTH,
    _console_ctrl_reason_callback,
    _end_reason_is_known,
    _install_console_ctrl_reason_handler,
    _install_service_stop_signal,
    _install_signal_reason_handlers,
    _restore_service_stop_signal,
)
from hermes_cli.harness_parts.serve.boot import (
    BOOT_FAULT_ENV_VAR,
    _FINGERPRINT_TURN_FILE_CAP,
    _annotate_import_tax,
    _maybe_inject_boot_fault,
    _prewarm_persona_chat_actors,
    _prewarm_provider_runtime,
    _prewarm_read_model_snapshot,
    _repoint_logging_root_stderr,
    _runtime_state_fingerprint,
    _stat_board_tree,
    _stat_turn_store_tree,
    install_harness_skills_at_boot,
)
from hermes_cli.harness_parts.serve.frames import (
    _FrameWriter,
    _LineFrameProxy,
    _PollResponseCache,
    _PollResponseCacheEntry,
    _SafeSink,
    _emit_deferred_reply,
    _request_id,
    _request_sink,
    current_serve_request_id,
)
from hermes_cli.harness_parts.serve.argv_lane import (
    ARGV_ROOT,
    ArgvRootUnsupported,
    HandlerExit,
    _ArgvRequest,
    _build_harness_parser,
    _clean_argv_root,
    _system_exit_code,
    dispatch_argv,
)
from hermes_cli.harness_parts.serve.drain import (
    _DrainState,
    _drain_deadline_seconds,
)
from hermes_cli.harness_parts.serve.loop import (
    serve_loop,
)
from hermes_cli.harness_parts.serve.commands import (
    SERVE_CONNECT_NO_SERVICE_EXIT_CODE,
    SERVE_CONNECT_REJECTED_EXIT_CODE,
    SERVE_CONNECT_TRANSPORT_EXIT_CODE,
    _claim_protocol_pipes,
    _cmd_serve,
    _cmd_serve_connect,
    _raw_fd_lines,
)

__layer__ = "lanes"

__all__ = [
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
    "_CACHEABLE_ARGV",
    "_CHAT_TURN_COMMANDS",
    "_DRAIN_ABANDON_GRACE_SECONDS",
    "_DRAIN_DEADLINE_FLOOR_SECONDS",
    "_DRAIN_DEADLINE_MAX_SECONDS",
    "_DRAIN_EXIT_DEADLINE_SECONDS",
    "_DRAIN_POLL_INTERVAL_SECONDS",
    "_DRAIN_PROGRESS_INTERVAL_SECONDS",
    "_DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS",
    "_FINGERPRINT_BOARD_CARD_CAP",
    "_FINGERPRINT_ROOT_FILES",
    "_FINGERPRINT_STORE_DIRS",
    "_LONG_RUN_COMMANDS",
    "_READ_CACHE_MAX_AGE_SECONDS",
    "_REQUEST_SILENCE_SECONDS",
    "_SERVICE_PARK_POLL_SECONDS",
    "_is_gateway",
    "_pairing_block",
    "ops_manifest",
    "GATEWAY_OUTCOME_SOCKET_UNAVAILABLE",
    "gateway_block_when_no_listener",
    "gateway_listen_config",
    "start_gateway_listener",
    "CONSOLE_CTRL_END_REASONS",
    "END_REASON_UNCAUGHT_PREFIX",
    "END_REASON_UNKNOWN",
    "END_REASON_VOCABULARY",
    "SIGNAL_END_REASONS",
    "_CONSOLE_CTRL_HANDLER_KEEPALIVE",
    "_ServeEndReason",
    "_UNCAUGHT_TYPE_MAX_LENGTH",
    "_console_ctrl_reason_callback",
    "_end_reason_is_known",
    "_install_console_ctrl_reason_handler",
    "_install_service_stop_signal",
    "_install_signal_reason_handlers",
    "_restore_service_stop_signal",
    "BOOT_FAULT_ENV_VAR",
    "_FINGERPRINT_TURN_FILE_CAP",
    "_annotate_import_tax",
    "_maybe_inject_boot_fault",
    "_prewarm_persona_chat_actors",
    "_prewarm_provider_runtime",
    "_prewarm_read_model_snapshot",
    "_repoint_logging_root_stderr",
    "_runtime_state_fingerprint",
    "_stat_board_tree",
    "_stat_turn_store_tree",
    "install_harness_skills_at_boot",
    "_FrameWriter",
    "_LineFrameProxy",
    "_PollResponseCache",
    "_PollResponseCacheEntry",
    "_SafeSink",
    "_emit_deferred_reply",
    "_request_id",
    "_request_sink",
    "current_serve_request_id",
    "ARGV_ROOT",
    "ArgvRootUnsupported",
    "HandlerExit",
    "_ArgvRequest",
    "_build_harness_parser",
    "_clean_argv_root",
    "_system_exit_code",
    "dispatch_argv",
    "_DrainState",
    "_drain_deadline_seconds",
    "serve_loop",
    "SERVE_CONNECT_NO_SERVICE_EXIT_CODE",
    "SERVE_CONNECT_REJECTED_EXIT_CODE",
    "SERVE_CONNECT_TRANSPORT_EXIT_CODE",
    "_claim_protocol_pipes",
    "_cmd_serve",
    "_cmd_serve_connect",
    "_raw_fd_lines",
]
