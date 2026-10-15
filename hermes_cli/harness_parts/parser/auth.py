"""Non-interactive setup over Hermes's credential lifecycle."""

from hermes_cli.auth_noninteractive import auth_login_command, auth_set_key_command

__layer__ = "wiring"


def add_auth(subs) -> None:
    parser = subs.add_parser("auth", help="Connect a provider without a terminal prompt")
    actions = parser.add_subparsers(dest="auth_action", required=True)
    key = actions.add_parser("set-key", help="Save an API key from stdin")
    key.add_argument("provider", help="Provider id")
    key.add_argument("--label", help="Display label")
    key.add_argument("--stdin", action="store_true", help="Read the key from stdin (required)")
    key.add_argument("--profile", help="Target profile (default: current)")
    key.set_defaults(func=_set_key)
    login = actions.add_parser("login", help="Stream provider sign-in events")
    login.add_argument("provider", help="Provider id")
    login.add_argument("--flow", choices=["browser", "device_code", "paste_code"])
    login.add_argument("--json", action="store_true", help="Emit NDJSON events (required)")
    login.add_argument("--profile", help="Target profile (default: current)")
    login.set_defaults(func=_login)


def _set_key(args) -> None:
    raise SystemExit(auth_set_key_command(args))


def _login(args) -> None:
    raise SystemExit(auth_login_command(args))
