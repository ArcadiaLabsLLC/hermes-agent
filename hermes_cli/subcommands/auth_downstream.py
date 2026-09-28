"""Fork-owned ``hermes auth`` verbs: ``set-key`` and ``login`` (non-interactive).

The launcher's argv builds these spellings (``provider_connect_controller.dart``); their
handlers are ``hermes_cli/auth_noninteractive.py``. Attached by one call from upstream's
``hermes_cli/subcommands/auth.py::build_auth_parser`` (lane FOOTPRINT-DROP 2026-09-27);
retires with a plugin-sub-verbs-on-a-builtin-parser widening PR.
"""

from __future__ import annotations


def add_noninteractive_auth_parsers(auth_subparsers) -> None:
    """Attach ``set-key`` and ``login`` to the ``auth`` subparsers."""
    # `set-key` is the machine-drivable API-key write. It deliberately has NO
    # value-bearing flag: `auth add --api-key <value>` exists for operators at a
    # terminal, but the verb a GUI drives must not put a secret in argv, where
    # it is visible to process listings, transport receipts, and shell history.
    # The secret arrives on stdin; --stdin is required so the verb can never
    # silently fall back to a prompt no GUI will answer.
    auth_set_key = auth_subparsers.add_parser(
        "set-key",
        help="Store a provider API key read from stdin (non-interactive, JSON ack)",
    )
    auth_set_key.add_argument("provider", help="Provider id")
    auth_set_key.add_argument("--label", help="Optional display label")
    auth_set_key.add_argument(
        "--stdin",
        action="store_true",
        help="Read the key as the first line of stdin (required)",
    )
    auth_set_key.add_argument(
        "--profile",
        help="Profile whose home receives the credential (default: current)",
    )
    auth_login = auth_subparsers.add_parser(
        "login",
        help="Non-interactive provider login as an NDJSON event stream",
    )
    auth_login.add_argument("provider", help="Provider id")
    auth_login.add_argument("--flow", choices=["browser", "device_code", "paste_code"],
                            help="A browser login method advertised by the provider catalog")
    auth_login.add_argument(
        "--json",
        action="store_true",
        help="Emit NDJSON events (the only supported mode)",
    )
    auth_login.add_argument(
        "--profile",
        help="Profile whose home receives the credential (default: current)",
    )
