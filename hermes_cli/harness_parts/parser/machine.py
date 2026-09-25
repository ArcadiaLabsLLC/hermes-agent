"""The machine-level families: init, roots, gateway, the status/health/doctor reads, work, stream and serve.

One ``add_<family>(subs)`` per ``hermes harness`` family, in the order the
contract fixture lists them; ``parser.PARSER_FAMILIES`` is the only reader.
"""

from __future__ import annotations

import argparse

from .common_args import _add_stage42_global_args
from agent_runtime.harness_doctor import DEFAULT_WORKTREE_MIN_AGE_SECONDS
from hermes_cli.harness_parts import runtime_commands
from hermes_cli.harness_parts.doctor_commands import _cmd_doctor
from hermes_cli.harness_parts.gateway_identity_commands import (
    _cmd_gateway_devices_list,
    _cmd_gateway_devices_revoke,
    _cmd_gateway_id,
    _cmd_gateway_introduce,
    _cmd_gateway_pair,
    _cmd_gateway_peers_join,
    _cmd_gateway_peers_list,
    _cmd_gateway_peers_pair,
    _cmd_gateway_peers_revoke,
    _cmd_gateway_rename,
)
from hermes_cli.harness_parts.init_commands import _cmd_init, _cmd_install_harness_skills
from hermes_cli.harness_parts.provider_visibility import _cmd_providers
from hermes_cli.harness_parts.roots_commands import (
    _cmd_roots_list,
    _cmd_roots_migrate,
    _cmd_roots_set,
    _cmd_roots_unset,
)
from hermes_cli.harness_parts.usage.commands import _cmd_usage
from hermes_cli.harness_parts.usage.detect import DEFAULT_USAGE_TIMEOUT

__layer__ = "wiring"
__all__ = [
    "_cmd_serve",
    "_cmd_serve_connect",
    "add_config",
    "add_contracts",
    "add_doctor",
    "add_gateway",
    "add_health",
    "add_init",
    "add_install_harness_skills",
    "add_migrate",
    "add_observe",
    "add_providers",
    "add_roots",
    "add_serve",
    "add_snapshot",
    "add_status",
    "add_stream",
    "add_usage",
    "add_verify",
    "add_work",
    "add_worktree",
]


def add_init(subs) -> None:
    """``hermes harness init``."""
    init = subs.add_parser("init", help="Initialize the harness store")
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=_cmd_init)


def add_roots(subs) -> None:
    """``hermes harness roots``."""
    roots = subs.add_parser(
        "roots",
        help="Machine-local logical roots that make ${roots.<name>} config paths portable",
    )
    roots_subs = roots.add_subparsers(dest="roots_command", required=True)
    roots_list = roots_subs.add_parser("list", help="Show this machine's logical-root bindings (read-only)")
    _add_stage42_global_args(roots_list)
    roots_list.set_defaults(func=_cmd_roots_list)
    roots_set = roots_subs.add_parser("set", help="Bind a logical root to an absolute local path")
    roots_set.add_argument("name", help="Logical root name, e.g. eternia_launcher")
    roots_set.add_argument("path", help="Absolute path to the checkout on THIS machine")
    roots_set.add_argument("--allow-missing", action="store_true", help="Bind even when the path does not exist yet")
    _add_stage42_global_args(roots_set, controls=frozenset({"dry_run"}))
    roots_set.set_defaults(func=_cmd_roots_set)
    roots_unset = roots_subs.add_parser("unset", help="Remove a logical-root binding")
    roots_unset.add_argument("name")
    _add_stage42_global_args(roots_unset, controls=frozenset({"dry_run"}))
    roots_unset.set_defaults(func=_cmd_roots_unset)
    roots_migrate = roots_subs.add_parser(
        "migrate",
        help="Rewrite machine-local absolute paths in profile configs into ${roots.<name>} token form",
    )
    roots_migrate.add_argument("configs", nargs="*", help="config.yaml paths to migrate (default: every Hermes profile config)")
    roots_migrate.add_argument("--root", action="append", default=[], metavar="NAME=PATH", help="Explicit root binding; repeatable. Omit to auto-derive from .git ancestors.")
    roots_migrate.add_argument("--no-platform-gates", action="store_true", help="Do not add platforms:[windows] to PowerShell/.ps1-only MCP entries")
    _add_stage42_global_args(
        roots_migrate, controls=frozenset({"dry_run", "yes"})
    )
    roots_migrate.set_defaults(func=_cmd_roots_migrate)


def add_gateway(subs) -> None:
    """``hermes harness gateway``."""
    # Remote-gateway Stage 0b. Beside `roots` deliberately: both answer
    # questions about THIS MACHINE'S runtime root rather than about anything in
    # the store, and neither reads a workspace or a realm.
    #
    # Two subverbs, where the plan wrote `gateway id --set-name`. A rename is a
    # WRITE, and on this tree a write is its own subverb with its own control
    # set (`roots set`, `workspace rename`) — `_add_stage42_global_args` cannot
    # give one parser both the reader's full flag set and the writer's
    # `--dry-run`, so a single verb would have had to advertise one of them
    # falsely. The deviation is recorded in
    # `docs/agent-runtime-harness/archive/remote-gateway.md` § Stage 0b.
    gateway = subs.add_parser(
        "gateway",
        help="This runtime root's remote-gateway install identity — the name and id a phone's install picker shows",
    )
    gateway_subs = gateway.add_subparsers(dest="gateway_command", required=True)
    _add_gateway_identity_verbs(gateway_subs)
    _add_gateway_pairing_verbs(gateway_subs)
    _add_gateway_peers_verbs(gateway_subs)


def _add_gateway_identity_verbs(gateway_subs) -> None:
    """``hermes harness gateway id / rename``."""
    gateway_id = gateway_subs.add_parser(
        "id",
        help="Show this root's install identity (read-only — never mints; a root that has never served has none)",
    )
    _add_stage42_global_args(gateway_id)
    gateway_id.set_defaults(func=_cmd_gateway_id)
    gateway_rename = gateway_subs.add_parser(
        "rename",
        help="Set the operator-facing display name for this root's install (the install_id never changes)",
    )
    gateway_rename.add_argument("name", help="What a human should call this install, e.g. workstation")
    _add_stage42_global_args(gateway_rename, controls=frozenset({"dry_run"}))
    gateway_rename.set_defaults(func=_cmd_gateway_rename)


def _add_gateway_pairing_verbs(gateway_subs) -> None:
    """``hermes harness gateway pair / introduce / devices``."""
    # Stage 1's three. `pair` is a WRITE (it mints a credential channel) and
    # still takes the reader's flag set rather than `dry_run`, which is the one
    # deviation from `rename`'s reasoning and has its own: a dry run of `pair`
    # would have to print a code it did not mint, and a preview that shows an
    # operator eight characters nothing will accept is worse than no preview.
    # `devices revoke` DOES take `dry_run`, because there the preview is a real
    # row an operator can recognise before they cut a device off.
    gateway_pair = gateway_subs.add_parser(
        "pair",
        help="Mint a short-TTL pairing code plus the QR payload a device scans to reach this install",
    )
    gateway_pair.add_argument("--name", help="What to call the device that redeems this code, e.g. \"the phone\"")
    gateway_pair.add_argument(
        "--tier",
        choices=["console", "read"],
        default="console",
        help="What the paired device may do. console: run console verbs (create/retire agents). read: view only.",
    )
    _add_stage42_global_args(gateway_pair)
    gateway_pair.set_defaults(func=_cmd_gateway_pair)
    # S2. `introduce` sits under `gateway` rather than under `peers`, and that
    # placement is the honest one: it mints BOTH halves — a peer code and a
    # device code — so filing it under `peers` would name half of what it does.
    # It takes the reader's flag set for `pair`'s reason (a dry run would have
    # to print codes it did not mint).
    gateway_introduce = gateway_subs.add_parser(
        "introduce",
        help="Mint one envelope a launcher posts as a backend pair-grant: a peer code, a device code, and where to dial this install",
    )
    gateway_introduce.add_argument(
        "--for-install",
        dest="for_install",
        help="The hermes install id this introduction is FOR — the peer half is minted scoped to it and no other install can spend it",
    )
    gateway_introduce.add_argument(
        "--for-device",
        dest="for_device",
        help="The ACCOUNT device id this introduction is for — copied onto the device row as a join key (a label, not a check)",
    )
    gateway_introduce.add_argument(
        "--correlation",
        help="The backend grant id, stamped through both mints and every event so all three parties name one errand",
    )
    gateway_introduce.add_argument(
        "--note",
        help="What this introduction is for, e.g. \"the laptop\" — shown while the codes are pending",
    )
    _add_stage42_global_args(gateway_introduce)
    gateway_introduce.set_defaults(func=_cmd_gateway_introduce)
    gateway_devices = gateway_subs.add_parser(
        "devices",
        help="Devices paired with this install's gateway — list them, or revoke one",
    )
    gateway_devices_subs = gateway_devices.add_subparsers(
        dest="gateway_devices_command", required=True
    )
    gateway_devices_list = gateway_devices_subs.add_parser(
        "list",
        help="Every paired device, oldest first, revoked ones included (never the credential — there is no field for it)",
    )
    # No `sort` control, and that is the honest registration rather than the
    # generous one: `list_devices` returns one deterministic order (created_at,
    # then device_id) and nothing here re-sorts, so advertising the flag would
    # be a WRONG ANSWER believed — an operator who passes `--sort name` gets the
    # unsorted answer and no signal the flag was ignored. Exactly what
    # `_add_stage42_global_args`' own docstring is built around, and what
    # `test_every_stage42_global_flag_is_honored` caught here.
    _add_stage42_global_args(gateway_devices_list)
    gateway_devices_list.set_defaults(func=_cmd_gateway_devices_list)
    gateway_devices_revoke = gateway_devices_subs.add_parser(
        "revoke",
        help="Refuse a paired device from its next handshake on (the row is kept, so an audit can tell it from never-paired)",
    )
    gateway_devices_revoke.add_argument(
        "device_id", help="The device id from `harness gateway devices list`"
    )
    _add_stage42_global_args(gateway_devices_revoke, controls=frozenset({"dry_run"}))
    gateway_devices_revoke.set_defaults(func=_cmd_gateway_devices_revoke)


def _add_gateway_peers_verbs(gateway_subs) -> None:
    """``hermes harness gateway peers``."""
    # Stage 6's four. A `peers` subtree beside `devices` rather than more verbs
    # under it, because the two answer different questions about different
    # stores: `devices` is "which phones may reach this install", `peers` is
    # "which INSTALLS has an operator approved an edge with". Folding them would
    # make a list that mixes a phone and a workstation and needs a `kind` column
    # to be readable — which is a discriminator standing in for the two verbs
    # this tree already has room for.
    #
    # `pair` and `join` take the reader's flag set for `gateway pair`'s reason
    # (a dry run would have to print a code it did not mint, or perform half a
    # handshake); `revoke` takes `dry_run`, because there the preview is a real
    # row an operator can recognise before they cut an install off.
    gateway_peers = gateway_subs.add_parser(
        "peers",
        help="Installs paired with this one (operator-approved on BOTH sides) — pair, join, list, revoke",
    )
    gateway_peers_subs = gateway_peers.add_subparsers(
        dest="gateway_peers_command", required=True
    )
    gateway_peers_pair = gateway_peers_subs.add_parser(
        "pair",
        help="Mint a short-TTL PEER code plus the payload another install's operator runs `peers join` with",
    )
    gateway_peers_pair.add_argument(
        "--note", help="What this edge is for, e.g. \"laptop\" — shown while the code is pending"
    )
    _add_stage42_global_args(gateway_peers_pair)
    gateway_peers_pair.set_defaults(func=_cmd_gateway_peers_pair)
    gateway_peers_join = gateway_peers_subs.add_parser(
        "join",
        help="Redeem a peer code from ANOTHER install: dials it, and records the edge in both stores",
    )
    gateway_peers_join.add_argument(
        "payload",
        help="The join_payload string from `harness gateway peers pair` over there, or the bare 8-character code with --host/--port",
    )
    gateway_peers_join.add_argument("--host", help="Override the address in the payload (a second interface, a NAT, a machine that moved)")
    gateway_peers_join.add_argument("--port", type=int, help="Override the port in the payload")
    gateway_peers_join.add_argument("--fingerprint", help="Override the certificate fingerprint to pin; omitting it pins NOTHING, which is weaker")
    gateway_peers_join.add_argument(
        "--expect-fingerprint",
        dest="expect_fingerprint",
        help="The certificate fingerprint the ACCOUNT attests for that install; a payload that disagrees is refused before anything is dialled",
    )
    gateway_peers_join.add_argument(
        "--correlation",
        help="The backend grant id this join fulfils; echoed on the receipt so all three parties name one errand",
    )
    gateway_peers_join.add_argument("--timeout", type=float, default=20.0, help="Seconds to wait for the other install's handshake")
    _add_stage42_global_args(gateway_peers_join)
    gateway_peers_join.set_defaults(func=_cmd_gateway_peers_join)
    gateway_peers_list = gateway_peers_subs.add_parser(
        "list",
        help="Every paired install, oldest first, revoked ones included (never the credential — there is no field for it)",
    )
    # No `sort` control, for `devices list`'s reason: `list_peers` returns one
    # deterministic order (approved_at, then install id) and nothing here
    # re-sorts, so advertising the flag would be a wrong answer believed.
    _add_stage42_global_args(gateway_peers_list)
    gateway_peers_list.set_defaults(func=_cmd_gateway_peers_list)
    gateway_peers_revoke = gateway_peers_subs.add_parser(
        "revoke",
        help="Refuse a paired install from its next handshake on — ONE-SIDED: the other install keeps its own row",
    )
    gateway_peers_revoke.add_argument(
        "peer_install_id", help="The install id from `harness gateway peers list`"
    )
    gateway_peers_revoke.add_argument(
        "--no-announce",
        dest="no_announce",
        action="store_true",
        help="Skip telling the other install it was revoked (offline, or when it must not be contacted); it learns at its next call",
    )
    _add_stage42_global_args(gateway_peers_revoke, controls=frozenset({"dry_run"}))
    gateway_peers_revoke.set_defaults(func=_cmd_gateway_peers_revoke)


def add_status(subs) -> None:
    """``hermes harness status``."""
    status = subs.add_parser("status", help="Show harness status")
    status.add_argument("--json", action="store_true")
    status.add_argument(
        "--prune-stale",
        action="store_true",
        help=(
            "Delete serve_instances entries whose PID is PROVABLY dead, and report "
            "exactly which (recycled-PID and unclassifiable entries are always kept)"
        ),
    )
    status.set_defaults(func=runtime_commands._cmd_status)


def add_providers(subs) -> None:
    """``hermes harness providers``."""
    providers = subs.add_parser(
        "providers",
        help="List credential pools with typed auth health (machine-readable via --json)",
    )
    providers.add_argument("--json", action="store_true")
    providers.set_defaults(func=_cmd_providers)


def add_usage(subs) -> None:
    """``hermes harness usage``."""
    usage = subs.add_parser(
        "usage",
        help="Per-provider account usage/limit windows (machine-readable via --json)",
    )
    usage.add_argument("--json", action="store_true")
    usage.add_argument(
        "--provider",
        default=None,
        help="Restrict to a single provider lane (still emits the full envelope)",
    )
    usage.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_USAGE_TIMEOUT,
        help="Overall wall-clock bound (seconds) for the concurrent lane fetches",
    )
    usage.set_defaults(func=_cmd_usage)


def add_doctor(subs) -> None:
    """``hermes harness doctor``."""
    doctor = subs.add_parser("doctor", help="Show Harness runtime diagnostics: orphan worktrees, snapshot ids, event-log health, model authority, persona/profile binding")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--fix", action="store_true", help="Capture-then-reap the orphan worktrees the scan reports")
    doctor.add_argument("--dry-run", action="store_true", help="Preview --fix repairs without mutating runtime state")
    doctor.add_argument("--yes", "-y", action="store_true", help="Confirm --fix repairs")
    doctor.add_argument("--worktree-min-age-seconds", type=int, default=DEFAULT_WORKTREE_MIN_AGE_SECONDS)
    # The six stale-threshold / --compact-events knobs were removed: they fed
    # task, run, worker and incident sweeps that died with the mission lane, so
    # the CLI accepted them and silently ignored them.
    doctor.set_defaults(func=_cmd_doctor)


def add_health(subs) -> None:
    """``hermes harness health``."""
    health = subs.add_parser("health", help="Check Harness runtime/provider dependencies are reachable and configured")
    health.add_argument("--json", action="store_true")
    health.set_defaults(func=runtime_commands._cmd_health)


def add_verify(subs) -> None:
    """``hermes harness verify``."""
    verify = subs.add_parser("verify", help="Run runtime smoke verification: read-only harness CLI commands plus the focused store/snapshot/status test modules")
    verify.add_argument("--json", action="store_true")
    verify.add_argument("--mode", choices=["live-tony", "ci", "temp-root"], default="ci")
    verify.add_argument("--skip-tests", action="store_true")
    verify.set_defaults(func=runtime_commands._cmd_verify)


def add_config(subs) -> None:
    """``hermes harness config``."""
    config = subs.add_parser("config", help="Inspect Harness runtime config")
    config_subs = config.add_subparsers(dest="config_command")
    config_show = config_subs.add_parser("show", help="Show effective Harness runtime config")
    config_show.add_argument("--json", action="store_true")
    config_show.set_defaults(func=runtime_commands._cmd_config)


def add_migrate(subs) -> None:
    """``hermes harness migrate``."""
    migrate = subs.add_parser("migrate", help="Inspect Harness runtime migrations")
    migrate.add_argument("--check", action="store_true", help="Report pending migrations without modifying data")
    migrate.add_argument("--json", action="store_true")
    migrate.set_defaults(func=runtime_commands._cmd_migrate)


def add_observe(subs) -> None:
    """``hermes harness observe``."""
    observe = subs.add_parser("observe", help="Show redaction-safe Mission Control observability")
    observe.add_argument("--json", action="store_true")
    observe.set_defaults(func=runtime_commands._cmd_observe)


def add_contracts(subs) -> None:
    """``hermes harness contracts``."""
    contracts = subs.add_parser("contracts", help="Inspect canonical Mission Control event contracts")
    contracts_subs = contracts.add_subparsers(dest="contracts_command")
    contracts_dump = contracts_subs.add_parser("dump", help="Dump redaction-safe contract registry")
    contracts_dump.add_argument("--json", action="store_true")
    contracts_dump.set_defaults(func=runtime_commands._cmd_contracts_dump)


def add_worktree(subs) -> None:
    """``hermes harness worktree``."""
    worktree = subs.add_parser("worktree", help="Manage harness-managed git worktrees")
    worktree_subs = worktree.add_subparsers(dest="worktree_command", required=True)
    worktree_reap = worktree_subs.add_parser(
        "reap",
        help="Capture-then-reap orphan harness worktrees with no live owner",
    )
    worktree_reap.add_argument("--min-age-seconds", type=int, default=3600)
    worktree_reap.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview typed reap/keep decisions without removing worktrees, capturing patches, or emitting events",
    )
    worktree_reap.add_argument(
        "--include-legacy-temp",
        action="store_true",
        help="Also inventory the canonical legacy system-temp hermes-agent-wt base",
    )
    worktree_reap.add_argument("--json", action="store_true")
    worktree_reap.set_defaults(func=runtime_commands._cmd_worktree_reap)


def add_install_harness_skills(subs) -> None:
    """``hermes harness install-harness-skills``."""
    skills = subs.add_parser("install-harness-skills", help="Install versioned Harness skills into configured persona profiles")
    skills.add_argument("--active-profile-only", action="store_true", help="Install all Harness skills only into the active Hermes profile")
    skills.add_argument("--json", action="store_true")
    skills.set_defaults(func=_cmd_install_harness_skills)


def add_snapshot(subs) -> None:
    """``hermes harness snapshot``."""
    # STAGE 6 (2026-08-22): the help text read "Write redaction-safe
    # snapshot.json" until the boot-cache writer it named (``snapshot.write_snapshot``)
    # was deleted with the read-model lane. This verb BUILDS a frame and prints
    # it; it writes no store state. `--json` is the only flag it has ever had —
    # the cache preference was resolved from config, never from argv, so there
    # was no cache-lane flag to retire with the lane.
    snap = subs.add_parser("snapshot", help="Build and print a redaction-safe runtime snapshot frame")
    snap.add_argument("--json", action="store_true")
    snap.set_defaults(func=runtime_commands._cmd_snapshot)


def add_stream(subs) -> None:
    """``hermes harness stream``."""
    stream = subs.add_parser("stream", help="Emit Mission Control hydrate/delta frames as NDJSON")
    stream.add_argument("--poll-interval", type=float, default=0.25)
    stream.add_argument("--heartbeat-interval", type=float, default=5.0)
    stream.add_argument(
        "--delta-debounce-ms",
        type=int,
        default=200,
        help="Settle window for coalescing an event burst into one delta frame (0 disables)",
    )
    stream.add_argument("--max-frames", type=int, default=None, help=argparse.SUPPRESS)
    stream.add_argument(
        "--resync",
        action="store_true",
        help="Force the first post-hydrate batch to a full core (S6: a reconnecting fold client re-baselining before it folds patches)",
    )
    stream.add_argument(
        "--fold-entities",
        default=None,
        metavar="persona_instance,incident",
        help=(
            "Comma-separated entity classes THIS client can fold in place. A batch naming any "
            "other entity is demoted to a full core rather than shipping a patch the client "
            "would have to re-hydrate from. Omit the flag for the historical set "
            "(persona_instance,incident) — exactly today's wire; pass an empty value to declare "
            "that you fold nothing."
        ),
    )
    stream.set_defaults(func=runtime_commands._cmd_stream)


def add_serve(subs) -> None:
    """``hermes harness serve``."""
    serve = subs.add_parser("serve", help="Persistent NDJSON bridge: dispatch harness argv requests in one warm process (Mission Control serve lane), on stdio and on the per-root localhost socket")
    serve.add_argument("--ndjson", action="store_true", help="NDJSON frame transport over stdio (the only v1 transport)")
    serve.add_argument("--pool-size", type=int, default=4, help=argparse.SUPPRESS)
    serve.add_argument(
        "--no-socket",
        action="store_true",
        help="Run stdio-only: do not race for the per-root socket ownership lock and do not listen (the ready frame reports socket.outcome=disabled)",
    )
    serve.add_argument(
        "--service",
        action="store_true",
        help=(
            "Run as a durable service: stdin EOF means the starter DETACHED, not stop. The "
            "runtime keeps serving both socket lanes and ends only on `serve connect --drain`, "
            "SIGTERM, or a stdio `shutdown` sent before EOF. A starter that loses the per-root "
            "ownership lock exits 0 naming the winner instead of becoming a second executor. "
            "Incompatible with --no-socket (a drain would have no lane to arrive on)."
        ),
    )
    serve.set_defaults(func=_cmd_serve)
    # Sub-verbs under `serve`. The subparser is NOT required, so a bare
    # `harness serve --ndjson` keeps parsing exactly as it always has and still
    # dispatches to `_cmd_serve`.
    serve_subs = serve.add_subparsers(dest="serve_command")
    serve_connect = serve_subs.add_parser(
        "connect",
        help="Connect to this root's live serve socket, perform the hello handshake, and print the reply as JSON",
    )
    serve_connect.add_argument("--probe", action="store_true", help="Also ask the service for its version block (build, boot_id, connections)")
    serve_connect.add_argument("--drain", action="store_true", help="Ask the service to drain and read to its terminal frame (the durable-service restart verb, from the outside)")
    serve_connect.add_argument("--deadline-seconds", type=float, default=None, help="Drain deadline handed to the service (the service floors it at its own minimum, 30s by default, and caps it at 3600s)")
    serve_connect.add_argument("--client", default=None, help="Client name recorded on the connection and in the service's logs (default: harness-serve-connect)")
    serve_connect.add_argument("--timeout", type=float, default=10.0, help="Socket connect/read timeout in seconds")
    serve_connect.set_defaults(func=_cmd_serve_connect)


def add_work(subs) -> None:
    """``hermes harness work``."""
    # STAGE 6 (duplicate-implementation retirement, 2026-08-22): the two
    # `read_model.db` verbs stood here — `rebuild-read-model` (Projector.full_rebuild)
    # and `read` (ReadModel.read_projection). Both were the ONLY production
    # entries into `agent_runtime/read_model.py`, a lane that populated a
    # database nothing on the serve path ever read: `hermes serve` builds cores
    # through `build_snapshot()` and persists them under `<store_root>/serve_read_model/`
    # via `core_cache.write_back()`, which is a different store with a different
    # validity model. Operator ruling: RETIRE. Absence is pinned by
    # `tests/agent_runtime/test_s46_incremental_projection_lane_removal.py` (deleted 2026-09-24) and
    # by the `agent_runtime.read_model` / `.projector` MODULE tombstones.

    # `harness work` — the operator's view of background work in flight
    # (terminal processes, subagent delegations, in-flight chat turns, MCP
    # servers, cron jobs). `list`/`peek` are strictly read-only; `cancel` is a
    # stage42 mutation verb and carries the confirm + replay guards.
    work = subs.add_parser("work", help="Background work running right now (list / peek / cancel)")
    work_subs = work.add_subparsers(dest="work_command", required=True)
    work_list = work_subs.add_parser("list", help="Every piece of running background work, with per-source health")
    work_list.add_argument("--kind", default=None, help="Only rows of this kind (terminal, delegation, chat_turn, mcp_server, cron_job, dispatch)")
    # No `--cursor`/`--since`: this projection is a point-in-time census of what
    # is running NOW, built fresh on every call. There is no page to resume from
    # and no history to filter by, so advertising either would accept a flag and
    # silently return the whole unfiltered set.
    _add_stage42_global_args(
        work_list, controls=frozenset({"limit", "sort"})
    )
    work_list.set_defaults(func=runtime_commands._cmd_work_list)
    work_peek = work_subs.add_parser("peek", help="Bounded read-only look at one item's recent output/progress")
    work_peek.add_argument("work_id", help="Work id from `harness work list`, e.g. terminal:sess-1")
    # Peek answers about ONE row, so nothing to sort, page or bound.
    _add_stage42_global_args(work_peek)
    work_peek.set_defaults(func=runtime_commands._cmd_work_peek)
    work_cancel = work_subs.add_parser("cancel", help="Interrupt one piece of running work through its owning subsystem")
    work_cancel.add_argument("work_id", help="Work id from `harness work list`")
    work_cancel.add_argument("--reason", default="operator_cancel", help="Recorded interrupt reason")
    work_cancel.add_argument("--issued-at", dest="issued_at", default=None, help="ISO-8601 issue timestamp; a cancel issued before the work started is superseded instead of applied")
    # Same single-row reasoning, plus `--idempotency-key`: replay protection on
    # this verb is `--issued-at` (a cancel aimed at a previous incarnation is
    # superseded), and a second, unread key would imply a guarantee nothing here
    # provides.
    _add_stage42_global_args(
        work_cancel, controls=frozenset({"dry_run", "yes"})
    )
    work_cancel.set_defaults(func=runtime_commands._cmd_work_cancel)


def _cmd_serve(args) -> int:
    # Lazy: serve is the process's main loop, owns the sys.stdout/sys.stderr
    # swaps, and every other verb would pay its import weight.
    from hermes_cli.harness_parts.serve.commands import _cmd_serve as _run_serve

    # The argv lane parses with the harness tree; the part may not import it.
    # Lazy: the parser package imports this module to build PARSER_FAMILIES.
    from hermes_cli.harness_parts.parser import build_parser

    return _run_serve(args, harness_parser=build_parser)


def _cmd_serve_connect(args) -> int:
    from hermes_cli.harness_parts.serve.commands import _cmd_serve_connect as _run_connect

    return _run_connect(args)
