"""The ``hermes harness`` argparse tree: every verb family, and the handler each one runs.

Separate from the handlers because a parser is wiring, not behaviour: this
module decides which ``func=`` a command line reaches and nothing else. Entry
points: ``hermes_cli.harness.build_cli_parser`` (the plugin door) and
``build_parser`` (the contract dump, the fixture generator, the serve argv lane
and the tests, which all start from a subparsers action).
"""

from __future__ import annotations

import argparse

from agent_runtime.harness_doctor import DEFAULT_WORKTREE_MIN_AGE_SECONDS
from hermes_cli.harness_parts import (
    board as board_commands,
    checkpoint_commands,
    flow_commands,
    level as level_commands,
    map as map_commands,
    office as office_commands,
    runtime_commands,
)
from hermes_cli.harness_parts.persona import (
    chat_coordinator,
    chat_delete,
    chat_open,
    chat_tickets_commands,
    chat_turn_message,
    inspect_commands,
    instance_commands,
    lifecycle_commands,
    model_and_skills_commands,
)

from hermes_cli.harness_parts.agent_commands import _cmd_agent_list, _cmd_agent_set_profile
from hermes_cli.harness_parts.characters.auto import _CHARACTERS_AUTO_STEPS, _cmd_characters_auto
from hermes_cli.harness_parts.characters.commands import (
    _cmd_characters_add_state,
    _cmd_characters_backfill_home,
    _cmd_characters_base,
    _cmd_characters_list,
    _cmd_characters_migrate_home,
    _cmd_characters_payload_contract,
    _cmd_characters_reopen,
    _cmd_characters_sprite,
    _cmd_characters_start,
    _cmd_characters_status,
    _cmd_characters_thumb,
)
from hermes_cli.harness_parts.characters.steps import (
    _cmd_characters_approve_direction,
    _cmd_characters_compose,
    _cmd_characters_reroll_direction,
    _cmd_characters_reroll_row,
    _cmd_characters_rows,
    _cmd_characters_turnaround,
)
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
from .common_args import _add_coordinator_permission_args, _add_stage42_global_args
from hermes_cli.harness_parts.persona.inspect_commands import _cmd_persona_instance_detail
from hermes_cli.harness_parts.pets_commands import (
    _cmd_pets_gallery,
    _cmd_pets_install,
    _cmd_pets_sprite,
    _cmd_pets_thumb,
)
from hermes_cli.harness_parts.prompt_context_commands import _cmd_prompt_context_show
from hermes_cli.harness_parts.provider_visibility import _cmd_providers
from hermes_cli.harness_parts.realm_commands import (
    _cmd_realm_adopt,
    _cmd_realm_agents_set,
    _cmd_realm_agents_show,
    _cmd_realm_bind_server,
    _cmd_realm_create,
    _cmd_realm_default_scope,
    _cmd_realm_list,
    _cmd_realm_show,
    _cmd_realm_skills_set,
    _cmd_realm_skills_show,
    _cmd_realm_sync_held,
    _cmd_realm_sync_publish,
    _cmd_realm_sync_pull,
    _cmd_realm_sync_resolve,
    _cmd_realm_sync_revert,
    _cmd_realm_sync_status,
    _cmd_realm_use,
)
from hermes_cli.harness_parts.roots_commands import (
    _cmd_roots_list,
    _cmd_roots_migrate,
    _cmd_roots_set,
    _cmd_roots_unset,
)
from hermes_cli.harness_parts.skills_commands import (
    _cmd_skills_catalog,
    _cmd_skills_inbox,
    _cmd_skills_inventory,
    _cmd_skills_link_external,
    _cmd_skills_publishable,
)
from hermes_cli.harness_parts.skills_promotion_commands import (
    _cmd_skills_delete,
    _cmd_skills_promote,
    _cmd_skills_restore,
)
from hermes_cli.harness_parts.usage.commands import _cmd_usage
from hermes_cli.harness_parts.usage.detect import DEFAULT_USAGE_TIMEOUT
from hermes_cli.harness_parts.workspace_commands import (
    _cmd_workspace_add_agent,
    _cmd_workspace_archive,
    _cmd_workspace_create,
    _cmd_workspace_delete,
    _cmd_workspace_list,
    _cmd_workspace_remove_agent,
    _cmd_workspace_rename,
    _cmd_workspace_show,
    _cmd_workspace_use,
)

__layer__ = "wiring"
__all__ = [
    "_cmd_serve",
    "_cmd_serve_connect",
    "build_parser",
    "harness_command",
    "populate_parser",
]


def build_parser(parent_subparsers) -> None:
    populate_parser(parent_subparsers.add_parser("harness", help="Experimental Agent Runtime Harness"))


def populate_parser(parser) -> None:
    """Build the whole ``hermes harness`` tree onto an existing ``harness`` parser."""
    _add_stage42_global_args(parser)
    subs = parser.add_subparsers(dest="harness_command")
    parser.set_defaults(func=harness_command)

    init = subs.add_parser("init", help="Initialize the harness store")
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=_cmd_init)

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

    workspace = subs.add_parser("workspace", help="Manage Harness workspaces")
    workspace_subs = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_list = workspace_subs.add_parser("list", help="List workspaces")
    _add_stage42_global_args(workspace_list, controls=frozenset({"sort"}))
    workspace_list.set_defaults(func=_cmd_workspace_list)
    workspace_show = workspace_subs.add_parser("show", help="Show one workspace")
    workspace_show.add_argument("workspace_id")
    _add_stage42_global_args(workspace_show)
    workspace_show.set_defaults(func=_cmd_workspace_show)
    workspace_create = workspace_subs.add_parser("create", help="Create a workspace")
    workspace_create.add_argument("--name", required=True)
    workspace_create.add_argument("--realm", default=None)
    workspace_create.add_argument("--agent", action="append", default=[])
    workspace_create.add_argument("--blueprint", default=None)
    # ``None`` (not "soft") so a template's isolation can win when the operator
    # did not choose one explicitly; WorkspaceStore.create defaults None→soft.
    workspace_create.add_argument("--isolation", choices=["soft", "hard"], default=None)
    workspace_create.add_argument("--max-lanes", type=int, default=None)
    workspace_create.add_argument(
        "--from-workspace",
        dest="from_workspace",
        default=None,
        help="Use this workspace (any realm) as the template: copy the scopes below into the new workspace",
    )
    workspace_create.add_argument(
        "--copy",
        action="append",
        choices=["office", "board", "agents", "settings"],
        default=None,
        help="Template scope to copy (repeatable). Default with --from-workspace: every scope. Requires --from-workspace.",
    )
    _add_stage42_global_args(workspace_create, controls=frozenset({"dry_run"}))
    workspace_create.set_defaults(func=_cmd_workspace_create)
    workspace_use = workspace_subs.add_parser("use", help="Set active workspace")
    workspace_use.add_argument("workspace_id")
    workspace_use.add_argument(
        "--issued-at",
        dest="issued_at",
        default=None,
        help="ISO-8601 UTC instant the operator issued this switch; a pointer already owned by a strictly newer intent rejects this one as superseded (transport replay guard)",
    )
    _add_stage42_global_args(workspace_use)
    workspace_use.set_defaults(func=_cmd_workspace_use)
    workspace_add_agent = workspace_subs.add_parser("add-agent", help="Add a persona to a workspace roster")
    workspace_add_agent.add_argument("workspace_id")
    workspace_add_agent.add_argument("persona_id")
    _add_stage42_global_args(
        workspace_add_agent, controls=frozenset({"dry_run"})
    )
    workspace_add_agent.set_defaults(func=_cmd_workspace_add_agent)
    workspace_remove_agent = workspace_subs.add_parser("remove-agent", help="Remove a persona from a workspace roster")
    workspace_remove_agent.add_argument("workspace_id")
    workspace_remove_agent.add_argument("persona_id")
    _add_stage42_global_args(
        workspace_remove_agent, controls=frozenset({"dry_run", "yes"})
    )
    workspace_remove_agent.set_defaults(func=_cmd_workspace_remove_agent)
    workspace_rename = workspace_subs.add_parser("rename", help="Rename a workspace")
    workspace_rename.add_argument("workspace_id")
    workspace_rename.add_argument("name")
    _add_stage42_global_args(workspace_rename, controls=frozenset({"dry_run"}))
    workspace_rename.set_defaults(func=_cmd_workspace_rename)
    workspace_archive = workspace_subs.add_parser("archive", help="Archive a workspace")
    workspace_archive.add_argument("workspace_id")
    _add_stage42_global_args(
        workspace_archive, controls=frozenset({"dry_run", "yes"})
    )
    workspace_archive.set_defaults(func=_cmd_workspace_archive)
    workspace_delete = workspace_subs.add_parser(
        "delete", help="Permanently delete a workspace and its office/board content (archive is the reversible path)"
    )
    workspace_delete.add_argument("workspace_id")
    _add_stage42_global_args(
        workspace_delete, controls=frozenset({"dry_run", "yes"})
    )
    workspace_delete.set_defaults(func=_cmd_workspace_delete)

    realm = subs.add_parser("realm", help="Manage Harness realms")
    realm_subs = realm.add_subparsers(dest="realm_command", required=True)
    realm_list = realm_subs.add_parser("list", help="List realms")
    _add_stage42_global_args(realm_list, controls=frozenset({"sort"}))
    realm_list.set_defaults(func=_cmd_realm_list)
    realm_show = realm_subs.add_parser("show", help="Show one realm")
    realm_show.add_argument("realm_id")
    _add_stage42_global_args(realm_show)
    realm_show.set_defaults(func=_cmd_realm_show)
    realm_create = realm_subs.add_parser("create", help="Create a realm")
    realm_create.add_argument("--name", required=True)
    realm_create.add_argument("--server", default=None)
    _add_stage42_global_args(realm_create, controls=frozenset({"dry_run"}))
    realm_create.set_defaults(func=_cmd_realm_create)
    realm_adopt = realm_subs.add_parser("adopt", help="Adopt server-granted realms from the Eternia backend")
    realm_adopt.add_argument("--server", default=None, help="Only adopt realms bound to this Eternia server id")
    realm_adopt.add_argument("--credential-file", default=None, help="Launcher-brokered realm sync credential JSON (fallback: HERMES_REALM_SYNC_CREDENTIAL)")
    _add_stage42_global_args(
        realm_adopt, controls=frozenset({"dry_run", "sort"})
    )
    realm_adopt.set_defaults(func=_cmd_realm_adopt)
    realm_bind = realm_subs.add_parser("bind-server", help="Bind a realm to an Eternia server id")
    realm_bind.add_argument("realm_id")
    realm_bind.add_argument("server_id")
    _add_stage42_global_args(realm_bind, controls=frozenset({"dry_run"}))
    realm_bind.set_defaults(func=_cmd_realm_bind_server)
    realm_use = realm_subs.add_parser("use", help="Set active realm")
    realm_use.add_argument("realm_id")
    realm_use.add_argument(
        "--issued-at",
        dest="issued_at",
        default=None,
        help="ISO-8601 UTC instant the operator issued this switch; a pointer already owned by a strictly newer intent rejects this one as superseded (transport replay guard)",
    )
    _add_stage42_global_args(realm_use)
    realm_use.set_defaults(func=_cmd_realm_use)
    realm_default_scope = realm_subs.add_parser(
        "default-scope",
        help="Preview default-scope adoption/reconciliation without mutating persisted state",
    )
    realm_default_scope.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory only; never mutates persisted state",
    )
    realm_default_scope.add_argument("--winner-realm", default=None)
    realm_default_scope.add_argument("--winner-workspace", default=None)
    realm_default_scope.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Apply the explicitly selected recoverable reconciliation",
    )
    _add_stage42_global_args(realm_default_scope)
    realm_default_scope.set_defaults(func=_cmd_realm_default_scope)
    realm_sync = realm_subs.add_parser("sync", help="Git-backed selective sync for non-source-controlled realm artifacts")
    realm_sync_subs = realm_sync.add_subparsers(dest="realm_sync_command", required=True)
    realm_sync_status_cmd = realm_sync_subs.add_parser("status", help="Show realm sync state")
    realm_sync_status_cmd.add_argument("realm_id")
    realm_sync_status_cmd.add_argument("--credential-file", default=None, help="Launcher-brokered realm sync credential JSON (fallback: HERMES_REALM_SYNC_CREDENTIAL)")
    _add_stage42_global_args(realm_sync_status_cmd)
    realm_sync_status_cmd.set_defaults(func=_cmd_realm_sync_status)
    realm_sync_pull = realm_sync_subs.add_parser("pull", help="Pull and materialize realm sync artifacts")
    realm_sync_pull.add_argument("realm_id")
    realm_sync_pull.add_argument("--credential-file", default=None, help="Launcher-brokered realm sync credential JSON (fallback: HERMES_REALM_SYNC_CREDENTIAL)")
    _add_stage42_global_args(realm_sync_pull, controls=frozenset({"dry_run"}))
    realm_sync_pull.set_defaults(func=_cmd_realm_sync_pull)
    realm_sync_publish = realm_sync_subs.add_parser("publish", help="Publish allowlisted realm sync artifacts")
    realm_sync_publish.add_argument("realm_id")
    realm_sync_publish.add_argument("--credential-file", default=None, help="Launcher-brokered realm sync credential JSON (fallback: HERMES_REALM_SYNC_CREDENTIAL)")
    _add_stage42_global_args(
        realm_sync_publish, controls=frozenset({"dry_run", "yes"})
    )
    realm_sync_publish.set_defaults(func=_cmd_realm_sync_publish)
    realm_sync_held = realm_sync_subs.add_parser(
        "held",
        help="List what a pull HELD because BOTH sides changed: profile files (MEMORY.md / core context / persona prompts) and skill packages",
    )
    realm_sync_held.add_argument("realm_id")
    _add_stage42_global_args(realm_sync_held)
    realm_sync_held.set_defaults(func=_cmd_realm_sync_held)
    realm_sync_resolve = realm_sync_subs.add_parser(
        "resolve",
        help="Resolve one held profile file or skill package: --take local keeps the member's content (and leaves it to publish), --take remote adopts the realm's",
    )
    realm_sync_resolve.add_argument("realm_id")
    realm_sync_resolve.add_argument("--key", required=True, help="Entity key from `realm sync held` — a profile file (alice:memories/MEMORY.md) or a skill package (skill::launcher-mcp-operations)")
    realm_sync_resolve.add_argument("--take", required=True, choices=["local", "remote"])
    _add_stage42_global_args(
        realm_sync_resolve, controls=frozenset({"dry_run", "yes"})
    )
    realm_sync_resolve.set_defaults(func=_cmd_realm_sync_resolve)
    realm_sync_revert = realm_sync_subs.add_parser(
        "revert",
        help="Revert drifted local store rows to the last-pulled upstream (local-only: no git, no network, no credential — and never mints a realm-visible tombstone)",
    )
    realm_sync_revert.add_argument("realm_id")
    realm_sync_revert.add_argument(
        "--item",
        dest="items",
        action="append",
        default=None,
        help="FAMILY:CONTAINER:KEY from `realm sync status` store_drift.items (e.g. office_actor:ws_x:dev_agent_1234); the container is empty when the row's holder is gone, and is passed back empty (persona_instance::personainst_1234) — the whole skill family is spelled that way (skill::launcher-mcp-operations), since a skill package has no realm-scoped container; repeatable",
    )
    realm_sync_revert.add_argument(
        "--all",
        dest="revert_all",
        action="store_true",
        help="Revert every drifted item in this realm",
    )
    _add_stage42_global_args(
        realm_sync_revert, controls=frozenset({"dry_run", "yes"})
    )
    realm_sync_revert.set_defaults(func=_cmd_realm_sync_revert)

    realm_skills = realm_subs.add_parser("skills", help="Per-realm selection of which shared skills publish to a realm")
    realm_skills_subs = realm_skills.add_subparsers(dest="realm_skills_command", required=True)
    realm_skills_show = realm_skills_subs.add_parser("show", help="Show a realm's shared-skill publish selection (read-only, local store)")
    realm_skills_show.add_argument("realm_id")
    _add_stage42_global_args(realm_skills_show)
    realm_skills_show.set_defaults(func=_cmd_realm_skills_show)
    realm_skills_set = realm_skills_subs.add_parser(
        "set",
        help="Set a realm's shared-skill publish selection (local, reversible store edit — no --yes gate, like `realm use`)",
    )
    realm_skills_set.add_argument("realm_id")
    realm_skills_set.add_argument("--all", dest="publish_all", action="store_true", help="Publish all shared skills (mode=all; the stored selection list is preserved)")
    realm_skills_set.add_argument("--skills", dest="skills", default=None, help="Comma-separated skill slugs to publish (mode=selected)")
    realm_skills_set.add_argument("--none", dest="publish_none", action="store_true", help="Publish no skills (mode=selected, empty selection)")
    _add_stage42_global_args(realm_skills_set, controls=frozenset({"dry_run"}))
    realm_skills_set.set_defaults(func=_cmd_realm_skills_set)

    realm_agents = realm_subs.add_parser(
        "agents", help="Per-realm selection of which persona definitions publish to a realm"
    )
    realm_agents_subs = realm_agents.add_subparsers(
        dest="realm_agents_command", required=True
    )
    realm_agents_show = realm_agents_subs.add_parser(
        "show", help="Show a realm's persona-definition publish selection"
    )
    realm_agents_show.add_argument("realm_id")
    _add_stage42_global_args(realm_agents_show)
    realm_agents_show.set_defaults(func=_cmd_realm_agents_show)
    realm_agents_set = realm_agents_subs.add_parser(
        "set",
        help="Set a realm's persona-definition selection (required workspace/Office references remain pinned)",
    )
    realm_agents_set.add_argument("realm_id")
    realm_agents_set.add_argument(
        "--workspace",
        dest="publish_workspace",
        action="store_true",
        help="Publish only definitions required by workspace rosters and Office placements",
    )
    realm_agents_set.add_argument(
        "--agents",
        dest="agents",
        default=None,
        help="Comma-separated persona ids to publish in addition to required references",
    )
    realm_agents_set.add_argument(
        "--none",
        dest="publish_none",
        action="store_true",
        help="Clear the explicit selection; required references remain pinned",
    )
    _add_stage42_global_args(realm_agents_set, controls=frozenset({"dry_run"}))
    realm_agents_set.set_defaults(func=_cmd_realm_agents_set)

    flow = subs.add_parser("flow", help="Operator flow-graph documents: ingest the Launcher's authored agent map whole and set the referenced instances' steering relations")
    flow_subs = flow.add_subparsers(dest="flow_command", required=True)
    flow_set = flow_subs.add_parser("set", help="Store one flow-graph JSON doc and reconcile steering for the EXISTING instances it references (never creates instances)")
    flow_set.add_argument("--graph", default=None, help="The flow-graph JSON document, inline")
    flow_set.add_argument("--graph-file", default=None, help="Path to a file holding the flow-graph JSON document")
    flow_set.add_argument("--requested-by", default="operator")
    flow_set.add_argument("--json", action="store_true")
    flow_set.set_defaults(func=flow_commands._cmd_flow_set)
    flow_show = flow_subs.add_parser("show", help="Show the runtime's stored copy of one flow-graph doc")
    flow_show.add_argument("graph_id")
    flow_show.add_argument("--json", action="store_true")
    flow_show.set_defaults(func=flow_commands._cmd_flow_show)
    flow_list = flow_subs.add_parser("list", help="List stored flow-graph doc ids")
    flow_list.add_argument("--json", action="store_true")
    flow_list.set_defaults(func=flow_commands._cmd_flow_list)

    checkpoint = subs.add_parser(
        "checkpoint",
        help="Per-actor read-model checkpoint: bundle the on-disk entity-class stores into a keyed transport envelope (the store IS the checkpoint)",
    )
    checkpoint_subs = checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_fetch = checkpoint_subs.add_parser(
        "fetch",
        help="Bundle the per-actor store files into a keyed checkpoint envelope (entity class -> actor id -> row read verbatim); read-only, writes nothing",
    )
    checkpoint_fetch.add_argument(
        "--classes",
        default=None,
        help="Comma-separated entity-class filter (default: all discovered classes); absent/unknown names are accounted in requested_absent",
    )
    checkpoint_fetch.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional per-class row cap; truncation is accounted ({truncated,total,returned}), never silent",
    )
    checkpoint_fetch.add_argument("--json", action="store_true")
    checkpoint_fetch.set_defaults(func=checkpoint_commands._cmd_checkpoint_fetch)
    checkpoint_classes = checkpoint_subs.add_parser(
        "classes",
        help="List discovered entity classes with per-class actor counts and byte sizes (stat only; contents not read)",
    )
    checkpoint_classes.add_argument("--json", action="store_true")
    checkpoint_classes.set_defaults(func=checkpoint_commands._cmd_checkpoint_classes)

    skills = subs.add_parser("skills", help="Inspect the shared skills substrate the Launcher's Skills console consumes")
    skills_subs = skills.add_subparsers(dest="skills_command", required=True)
    skills_inventory_cmd = skills_subs.add_parser(
        "inventory",
        help="Typed snapshot of the shared skill catalog, per-persona grants, and per-realm publish/drift state",
    )
    skills_inventory_cmd.add_argument("--json", action="store_true", help="Emit the skills_inventory/v1 contract as JSON")
    skills_inventory_cmd.set_defaults(func=_cmd_skills_inventory)
    # Rehomed from `hermes skills link-external` (seam Stage 2): the verb is the harness's, not core's.
    skills_link_cmd = skills_subs.add_parser(
        "link-external", help="Link the shared skills root into external harnesses (~/.claude, ~/.codex)",
    )
    skills_link_cmd.add_argument("--json", action="store_true", help="Emit the link report as JSON")
    skills_link_cmd.set_defaults(func=_cmd_skills_link_external)
    skills_catalog_cmd = skills_subs.add_parser(
        "catalog",
        help="S8: resolve ONE content-addressed skills catalog by its hash (the frame ships only *_ref hashes; bodies are fetched once and cached forever)",
    )
    skills_catalog_cmd.add_argument("--hash", dest="content_hash", required=True, help="The content hash carried by a chat_contexts row's available_skills_ref / accessible_skills_ref")
    skills_catalog_cmd.add_argument("--json", action="store_true")
    skills_catalog_cmd.set_defaults(func=_cmd_skills_catalog)

    skills_publishable_cmd = skills_subs.add_parser(
        "publishable",
        help="List every resolvable skill with whether it can reach a realm, and if not, the typed reason (read-only)",
    )
    skills_publishable_cmd.add_argument(
        "--source-kind",
        dest="source_kind",
        default=None,
        choices=["profile_local", "shared_core", "external"],
        help="Restrict to one resolver tier (default: all three)",
    )
    skills_publishable_cmd.add_argument(
        "--unpublishable-only",
        dest="unpublishable_only",
        action="store_true",
        help="Show only packages that cannot reach a realm as they stand",
    )
    _add_stage42_global_args(skills_publishable_cmd)
    skills_publishable_cmd.set_defaults(func=_cmd_skills_publishable)

    skills_inbox_cmd = skills_subs.add_parser(
        "inbox",
        help="List quarantined per-realm inbox skill packages and how each would reconcile (read-only)",
    )
    skills_inbox_cmd.add_argument("--realm", default=None, help="Restrict to one realm id (default: all realms)")
    _add_stage42_global_args(skills_inbox_cmd)
    skills_inbox_cmd.set_defaults(func=_cmd_skills_inbox)

    skills_promote_cmd = skills_subs.add_parser(
        "promote",
        help="Promote a held / authored / profile-local skill package into the canonical shared root (hash-guarded, never-delete)",
    )
    skills_promote_cmd.add_argument("skill", help="Canonical skill slug (bare name or <category>/<name>)")
    skills_promote_cmd.add_argument("--from-realm", dest="from_realm", default=None, help="Promote from this realm's inbox mirror")
    skills_promote_cmd.add_argument("--from-profile", dest="from_profile", default=None, help="Promote from a profile's skills/ (implies --move-source)")
    skills_promote_cmd.add_argument("--from-path", dest="from_path", default=None, help="Promote from an explicit package directory")
    skills_promote_cmd.add_argument("--adopt-divergent", dest="adopt_divergent", action="store_true", help="Adopt over a divergent canonical (archives the previous copy)")
    skills_promote_cmd.add_argument("--move-source", dest="move_source", action="store_true", help="Archive the source package after a successful promotion (retire the duplicate)")
    _add_stage42_global_args(
        skills_promote_cmd, controls=frozenset({"dry_run"})
    )
    skills_promote_cmd.set_defaults(func=_cmd_skills_promote)

    skills_delete_cmd = skills_subs.add_parser(
        "delete",
        help="Delete a shared skill realm-wide: archive the local canonical package and record a tombstone so a member's surviving copy cannot republish it",
    )
    skills_delete_cmd.add_argument("skill", help="Canonical skill slug (bare name or <category>/<name>)")
    skills_delete_cmd.add_argument(
        "--realm",
        dest="realms",
        action="append",
        default=None,
        help="Narrow the delete to this realm id (repeatable). Default (R-E): every non-archived realm that currently publishes the slug — one canonical root serves all realms, so leaving one un-tombstoned resurrects the copy on that realm's next pull",
    )
    _add_stage42_global_args(skills_delete_cmd, controls=frozenset({"dry_run"}))
    skills_delete_cmd.set_defaults(func=_cmd_skills_delete)

    skills_restore_cmd = skills_subs.add_parser(
        "restore",
        help="Lift ONE realm's skill tombstone (un-tombstone only — re-admitting the BYTES is `skills promote`, and the receipt names the archived copy)",
    )
    skills_restore_cmd.add_argument("skill", help="Canonical skill slug named by the ledger entry to lift")
    skills_restore_cmd.add_argument("--realm", dest="realm", required=True, help="Realm id whose ledger entry is lifted (a tombstone is per-realm truth; there is no all-realms restore)")
    _add_stage42_global_args(skills_restore_cmd)
    skills_restore_cmd.set_defaults(func=_cmd_skills_restore)

    prompt_context = subs.add_parser(
        "prompt-context",
        help="S8: on-demand prompt-observability contexts (the frame ships only LIVE persona instances' current-session rows; historical rows are fetched here)",
    )
    prompt_context_subs = prompt_context.add_subparsers(dest="prompt_context_command", required=True)
    prompt_context_show = prompt_context_subs.add_parser(
        "show",
        help="Show one persisted prompt-observability context by id (read-only; the persisted files stay on disk after frame eviction)",
    )
    prompt_context_show.add_argument("--context-id", dest="context_id", required=True)
    prompt_context_show.add_argument("--json", action="store_true")
    prompt_context_show.set_defaults(func=_cmd_prompt_context_show)

    board = subs.add_parser("board", help="Manage Mission Board planning boards + cards (planning only — cards never drive runtime execution)")
    board_subs = board.add_subparsers(dest="board_command", required=True)
    board_list = board_subs.add_parser("list", help="List boards")
    board_list.add_argument("--workspace", "--workspace-id", default=None)
    _add_stage42_global_args(board_list, controls=frozenset({"sort"}))
    board_list.set_defaults(func=board_commands._cmd_board_list)
    board_show = board_subs.add_parser("show", help="Show one board")
    board_show.add_argument("board_id")
    board_show.add_argument("--full", action="store_true", help="Include card bodies")
    _add_stage42_global_args(board_show)
    board_show.set_defaults(func=board_commands._cmd_board_show)
    board_create = board_subs.add_parser("create", help="Create a board")
    board_create.add_argument("--workspace", "--workspace-id", required=True)
    board_create.add_argument("--title", default=None)
    _add_stage42_global_args(board_create, controls=frozenset({"dry_run"}))
    board_create.set_defaults(func=board_commands._cmd_board_create)
    board_update = board_subs.add_parser("update", help="Update a board title/columns")
    board_update.add_argument("board_id")
    board_update.add_argument("--title", default=None)
    board_update.add_argument("--columns-json", dest="columns_json", default=None, help="JSON array of {column_id,title,kind,wip_limit}")
    board_update.add_argument("--expect-revision", dest="expect_revision", type=int, default=None)
    _add_stage42_global_args(board_update)
    board_update.set_defaults(func=board_commands._cmd_board_update)

    board_card = board_subs.add_parser("card", help="Manage board cards")
    board_card_subs = board_card.add_subparsers(dest="board_card_command", required=True)
    card_add = board_card_subs.add_parser("add", help="Add a card")
    card_add.add_argument("--board", default=None, help="Board id (default: active workspace's default board)")
    card_add.add_argument("--workspace", "--workspace-id", default=None)
    card_add.add_argument("--title", required=True)
    card_add.add_argument("--description", default="")
    card_add.add_argument("--column", default=None, help="Column id or kind (default: first queued column)")
    card_add.add_argument("--priority", default=None, choices=["p0", "p1", "p2", "p3"])
    card_add.add_argument("--labels", default=None, help="Comma-separated labels")
    card_add.add_argument("--assignee", default=None)
    card_add.add_argument("--created-by", dest="created_by", default=None, help="operator (default) or a persona id")
    _add_stage42_global_args(
        card_add, controls=frozenset({"dry_run", "idempotency_key"})
    )
    card_add.set_defaults(func=board_commands._cmd_board_card_add)
    card_edit = board_card_subs.add_parser("edit", help="Edit a card")
    card_edit.add_argument("card_id")
    card_edit.add_argument("--title", default=None)
    card_edit.add_argument("--description", default=None)
    card_edit.add_argument("--priority", default=None, choices=["p0", "p1", "p2", "p3"])
    card_edit.add_argument("--labels", default=None, help="Comma-separated labels (replaces)")
    card_edit.add_argument("--assignee", default=None)
    card_edit.add_argument("--clear-assignee", dest="clear_assignee", action="store_true")
    card_edit.add_argument("--expect-revision", dest="expect_revision", type=int, default=None)
    _add_stage42_global_args(
        card_edit, controls=frozenset({"idempotency_key"})
    )
    card_edit.set_defaults(func=board_commands._cmd_board_card_edit)
    card_move = board_card_subs.add_parser("move", help="Move a card to a column / position")
    card_move.add_argument("card_id")
    card_move.add_argument("--column", required=True, help="Target column id or kind")
    card_move.add_argument("--before", default=None, help="Place before this card id")
    card_move.add_argument("--after", default=None, help="Place after this card id")
    card_move.add_argument("--expect-revision", dest="expect_revision", type=int, default=None)
    _add_stage42_global_args(
        card_move, controls=frozenset({"idempotency_key"})
    )
    card_move.set_defaults(func=board_commands._cmd_board_card_move)
    card_archive = board_card_subs.add_parser("archive", help="Archive a card (archive-never-delete)")
    card_archive.add_argument("card_id")
    _add_stage42_global_args(card_archive)
    card_archive.set_defaults(func=board_commands._cmd_board_card_archive)
    card_restore = board_card_subs.add_parser("restore", help="Restore an archived card")
    card_restore.add_argument("card_id")
    _add_stage42_global_args(card_restore)
    card_restore.set_defaults(func=board_commands._cmd_board_card_restore)

    board_resolve = board_subs.add_parser("resolve-conflict", help="Resolve a realm-sync conflict on a card")
    board_resolve.add_argument("card_id")
    board_resolve.add_argument("--take", required=True, choices=["local", "remote"])
    _add_stage42_global_args(board_resolve)
    board_resolve.set_defaults(func=board_commands._cmd_board_resolve_conflict)

    office = subs.add_parser("office", help="Manage the Mission Office layout (one file per actor placement; realm-synced like boards)")
    office_subs = office.add_subparsers(dest="office_command", required=True)
    office_show = office_subs.add_parser("show", help="Show a workspace's office surface + actors")
    office_show.add_argument("--workspace", "--workspace-id", default=None)
    office_show.add_argument("--full", action="store_true", help="Include actor item bodies")
    _add_stage42_global_args(office_show)
    office_show.set_defaults(func=office_commands._cmd_office_show)
    office_actor_upsert = office_subs.add_parser("actor-upsert", help="Create or update one actor placement (keys are minted store-side)")
    office_actor_upsert.add_argument("--workspace", "--workspace-id", default=None)
    office_actor_upsert.add_argument("--actor-json", dest="actor_json", required=True, help="Actor object (path or inline JSON): {persona_id, persona_instance_id?, backing_profile?, items:[...]}")
    # Optional, never required: class-keyed placements are a legal shape (see
    # OfficeStore.archive_actors_for_instance). The re-key migration's fence is
    # the CONDITIONAL refusal in _cmd_office_actor_upsert, not a mandatory flag.
    office_actor_upsert.add_argument("--persona-instance-id", dest="persona_instance_id", default=None, help="Bind the placement to this persona instance (overrides --actor-json's persona_instance_id); the store still mints the key")
    office_actor_upsert.add_argument("--allow-class-key", dest="allow_class_key", action="store_true", help="Escape hatch: force a class-keyed write that would otherwise be refused for re-creating an archived or duplicated placement")
    # Orthogonal to --allow-class-key and deliberately not implied by it: that
    # flag consents to the KEY SHAPE, this one to raising a deleted key. The
    # sanctioned un-archive verb remains `harness office actor-restore`.
    office_actor_upsert.add_argument("--resurrect", dest="resurrect", action="store_true", help="Escape hatch: re-add an actor key that was deleted, clearing its tombstone (default: such a write is refused)")
    office_actor_upsert.add_argument("--expect-revision", dest="expect_revision", type=int, default=None)
    office_actor_upsert.add_argument("--updated-by", dest="updated_by", default=None)
    _add_stage42_global_args(
        office_actor_upsert, controls=frozenset({"dry_run"})
    )
    office_actor_upsert.set_defaults(func=office_commands._cmd_office_actor_upsert)
    office_actor_remove = office_subs.add_parser("actor-remove", help="Archive an actor placement (archive-never-delete); tombstones and propagates realm-wide unless --local-only")
    office_actor_remove.add_argument("--workspace", "--workspace-id", default=None)
    office_actor_remove.add_argument("--actor", required=True, help="Actor key")
    office_actor_remove.add_argument("--reason", default=None)
    # The AUTHORED-vs-DIAGNOSTIC split (operator ruling, 2026-08-30). Without
    # the flag this verb carries an operator's intent to delete and writes the
    # tombstone a realm pull replicates — which is what makes a delete stick
    # against a peer that still holds the row. With it, the actor is archived
    # HERE and nothing is asserted about the realm, which is the only honest
    # posture for a repair the operator did not ask for by name.
    office_actor_remove.add_argument("--local-only", dest="local_only", action="store_true", help="Diagnostic repair: archive on THIS install only — no tombstone, nothing propagates, and a realm pull may legitimately bring the actor back. Use for doctor/dispatch/census repairs of local projection; omit when the operator means to delete the placement everywhere")
    office_actor_remove.add_argument("--expect-revision", dest="expect_revision", type=int, default=None)
    _add_stage42_global_args(
        office_actor_remove, controls=frozenset({"dry_run"})
    )
    office_actor_remove.set_defaults(func=office_commands._cmd_office_actor_remove)
    office_actor_restore = office_subs.add_parser("actor-restore", help="Restore an archived actor placement")
    office_actor_restore.add_argument("--workspace", "--workspace-id", default=None)
    office_actor_restore.add_argument("--actor", required=True, help="Actor key")
    _add_stage42_global_args(
        office_actor_restore, controls=frozenset({"dry_run"})
    )
    office_actor_restore.set_defaults(func=office_commands._cmd_office_actor_restore)
    office_set_folders = office_subs.add_parser("set-folders", help="Replace the surface's shared folder taxonomy")
    office_set_folders.add_argument("--workspace", "--workspace-id", default=None)
    office_set_folders.add_argument("--folders", required=True, help="Comma-separated folder names (structural defaults always kept)")
    office_set_folders.add_argument("--expect-revision", dest="expect_revision", type=int, default=None)
    _add_stage42_global_args(
        office_set_folders, controls=frozenset({"dry_run"})
    )
    office_set_folders.set_defaults(func=office_commands._cmd_office_set_folders)
    office_resolve = office_subs.add_parser("resolve-conflict", help="Resolve a realm-sync conflict on an actor placement")
    office_resolve.add_argument("--workspace", "--workspace-id", default=None)
    office_resolve.add_argument("--actor", required=True, help="Actor key")
    office_resolve.add_argument("--take", required=True, choices=["local", "remote"])
    office_resolve.add_argument("--allow-class-key", dest="allow_class_key", action="store_true", help="Escape hatch: adopt a remote actor on a persona CLASS key the re-key migration archived (re-creates the class-keyed placement beside its instance-keyed sibling)")
    _add_stage42_global_args(
        office_resolve, controls=frozenset({"dry_run"})
    )
    office_resolve.set_defaults(func=office_commands._cmd_office_resolve_conflict)
    office_archive_surface = office_subs.add_parser(
        "archive-surface",
        help="Archive an ORPHANED office surface (a surface whose workspace no longer resolves); clears its orphaned_office parity warning",
    )
    office_archive_surface.add_argument("--workspace", "--workspace-id", default=None)
    _add_stage42_global_args(
        office_archive_surface, controls=frozenset({"dry_run"})
    )
    office_archive_surface.set_defaults(func=office_commands._cmd_office_archive_surface)

    level = subs.add_parser(
        "level",
        help="Read or set a workspace's LEVEL document (the environment it stands in; realm-synced whole-document)",
    )
    level_subs = level.add_subparsers(dest="level_command", required=True)
    level_show = level_subs.add_parser("show", help="Show a workspace's level (metadata; --full carries the document)")
    level_show.add_argument("--workspace", "--workspace-id", default=None)
    level_show.add_argument("--full", action="store_true", help="Include the level document itself, byte for byte as stored")
    _add_stage42_global_args(level_show)
    level_show.set_defaults(func=level_commands._cmd_level_show)
    level_set = level_subs.add_parser("set", help="Store a workspace's level document VERBATIM (hermes validates that it is JSON with a version and reformats nothing)")
    level_set.add_argument("--workspace", "--workspace-id", default=None)
    level_set.add_argument(
        "--document",
        required=True,
        help="Level document: a PATH to a JSON file (use this — a level can be 1 MB and a Windows command line caps at ~32 KB), or inline JSON",
    )
    level_set.add_argument(
        "--expect-sha256",
        default=None,
        help="Compare-and-set: the sha256 of the stored bytes this write is based on, or 'none' if the workspace must have no level yet",
    )
    _add_stage42_global_args(level_set, controls=frozenset({"dry_run"}))
    level_set.set_defaults(func=level_commands._cmd_level_set)
    level_clear = level_subs.add_parser("clear", help="Remove a workspace's level (local only — a level the realm still publishes returns on the next pull)")
    level_clear.add_argument("--workspace", "--workspace-id", default=None)
    level_clear.add_argument(
        "--expect-sha256",
        default=None,
        help="Compare-and-set: the sha256 of the stored bytes this clear is based on, or 'none' if the workspace must have no level",
    )
    _add_stage42_global_args(level_clear, controls=frozenset({"dry_run"}))
    level_clear.set_defaults(func=level_commands._cmd_level_clear)
    map_parser = subs.add_parser(
        "map",
        help="Map CATALOGUE: the named scenes this install knows about, carried by the realm",
    )
    map_subs = map_parser.add_subparsers(dest="map_command", required=True)
    map_list = map_subs.add_parser("list", help="List the catalogue (names and hashes; never the documents)")
    _add_stage42_global_args(map_list)
    map_list.set_defaults(func=map_commands._cmd_map_list)
    map_show = map_subs.add_parser("show", help="Show one catalogue map (metadata; --full carries the document)")
    map_show.add_argument("--map", "--map-id", default=None)
    map_show.add_argument("--full", action="store_true", help="Include the map document itself, byte for byte as stored")
    _add_stage42_global_args(map_show)
    map_show.set_defaults(func=map_commands._cmd_map_show)
    map_set = map_subs.add_parser("set", help="Store a catalogue map VERBATIM (hermes validates that it is JSON with a version and a name, and reformats nothing)")
    map_set.add_argument("--map", "--map-id", default=None)
    map_set.add_argument(
        "--document",
        required=True,
        help="Map document: a PATH to a JSON file (use this — a map carries a scene and a Windows command line caps at ~32 KB), or inline JSON",
    )
    map_set.add_argument(
        "--expect-sha256",
        default=None,
        help="Compare-and-set: the sha256 of the stored bytes this write is based on, or 'none' if the catalogue must not hold this map yet",
    )
    _add_stage42_global_args(map_set, controls=frozenset({"dry_run"}))
    map_set.set_defaults(func=map_commands._cmd_map_set)
    map_clear = map_subs.add_parser("clear", help="Remove a catalogue map (local only — a map the realm still publishes returns on the next pull)")
    map_clear.add_argument("--map", "--map-id", default=None)
    map_clear.add_argument(
        "--expect-sha256",
        default=None,
        help="Compare-and-set: the sha256 of the stored bytes this clear is based on, or 'none' if the catalogue must not hold this map",
    )
    _add_stage42_global_args(map_clear, controls=frozenset({"dry_run"}))
    map_clear.set_defaults(func=map_commands._cmd_map_clear)

    persona = subs.add_parser("persona", help="Run bounded live-token diagnostics for one persona")
    persona_subs = persona.add_subparsers(dest="persona_command")
    persona_list = persona_subs.add_parser("list", help="List durable persona instances")
    persona_list.add_argument("--json", action="store_true")
    persona_list.set_defaults(func=inspect_commands._cmd_persona_list)
    persona_show = persona_subs.add_parser("show", help="Show one durable persona instance")
    persona_show.add_argument("persona_id_or_instance_id")
    persona_show.add_argument("--json", action="store_true")
    persona_show.set_defaults(func=inspect_commands._cmd_persona_show)
    persona_tool_diff = persona_subs.add_parser("tool-diff", help="Show resolved model tools and blocked tools for one persona")
    persona_tool_diff.add_argument("persona_id", help="Persona id")
    persona_tool_diff.add_argument("--session-id", default=None)
    # Unset ⇒ preview the persona under the RUNTIME DEFAULT
    # (``agent_runtime.tool_permissions.default_mode``, shipped ``unbounded``),
    # which is what a real turn gets. Pass a mode to preview a hypothetical one:
    # ``--permission-mode profile_default`` still renders the bounded shape.
    persona_tool_diff.add_argument(
        "--permission-mode",
        default=None,
        help=(
            "Preview under this permission mode (profile_default | bounded | "
            "read_only | unbounded). Default: the runtime default from the ROOT config."
        ),
    )
    persona_tool_diff.add_argument("--repo-scope", default=None)
    persona_tool_diff.add_argument("--workdir", default=None)
    persona_tool_diff.add_argument(
        "--explain-mcp",
        action="store_true",
        help=(
            "Explain MCP admission for this persona (requested / admitted / denied, "
            "with typed reasons). Inspection only — resolves policy without "
            "connecting to or registering any MCP server."
        ),
    )
    persona_tool_diff.add_argument(
        "--explain-envelope",
        action="store_true",
        help=(
            "Explain the terminal safety envelope for this persona's mission-chat "
            "lane: whether the lane binds an envelope scope, which command classes "
            "are operator-grantable vs a hard floor no config lifts, which grants "
            "are active from the ROOT config, and any typed grant-config issues. "
            "Inspection only — resolves policy without running a command."
        ),
    )
    persona_tool_diff.add_argument("--json", action="store_true")
    persona_tool_diff.set_defaults(func=inspect_commands._cmd_persona_tool_diff)
    persona_permission = persona_subs.add_parser(
        "permission",
        help=(
            "Restrict (or clear a restriction on) one chat session's tool permissions. "
            "The runtime default is the standing posture — this is the temporary "
            "narrowing lane, not an escalation ritual."
        ),
    )
    persona_permission_subs = persona_permission.add_subparsers(dest="persona_permission_command")
    persona_permission_set = persona_permission_subs.add_parser(
        "set",
        help=(
            "Set this session's permission mode. 'bounded' / 'read_only' RESTRICT it "
            "below the runtime default; 'profile_default' CLEARS the restriction "
            "(the session falls back to the runtime default); 'unbounded' is normally "
            "redundant with the default and only needed when the default is narrower."
        ),
    )
    persona_permission_set.add_argument("persona_id", help="Persona id")
    persona_permission_set.add_argument("--session-id", required=True)
    persona_permission_set.add_argument(
        "--mode",
        choices=["profile_default", "bounded", "read_only", "unbounded"],
        required=True,
        help=(
            "bounded = the historical bounded tier (persona-safety blocks + chat-lane "
            "cost cuts + envelope grants table only); read_only = bounded plus the "
            "mutating-tool block and the reviewer-shaped MCP subset; profile_default = "
            "no opinion, defer to the runtime default; unbounded = full access."
        ),
    )
    persona_permission_set.add_argument("--reason", required=True)
    persona_permission_set.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Expire the restriction after this many turns (any restricting mode decrements).",
    )
    persona_permission_set.add_argument("--ttl-seconds", type=int, default=None)
    persona_permission_set.add_argument("--expires-at", default=None)
    persona_permission_set.add_argument("--json", action="store_true")
    persona_permission_set.set_defaults(func=inspect_commands._cmd_persona_permission_set)
    persona_assignments = persona_subs.add_parser("assignments", help="List persona assignments")
    persona_assignments.add_argument("--persona", dest="persona_id", default=None)
    persona_assignments.add_argument("--json", action="store_true")
    persona_assignments.set_defaults(func=inspect_commands._cmd_persona_assignments)
    persona_assignment_task_id_migration = persona_subs.add_parser(
        "migrate-assignment-task-ids",
        help="Archive pre-retirement persona assignments whose task_id is non-null",
    )
    persona_assignment_task_id_migration.add_argument("--dry-run", action="store_true")
    persona_assignment_task_id_migration.add_argument("--json", action="store_true")
    persona_assignment_task_id_migration.set_defaults(
        func=inspect_commands._cmd_persona_assignment_task_id_migration
    )
    persona_chat = persona_subs.add_parser("chat", help="Manage durable persona chat sessions")
    persona_chat_subs = persona_chat.add_subparsers(dest="persona_chat_command")
    persona_chat_delete = persona_chat_subs.add_parser("delete", help="Delete a persona chat session and clear active persona bindings")
    persona_chat_delete.add_argument("--session-id", required=True)
    persona_chat_delete.add_argument("--persona", dest="persona_id", default=None)
    persona_chat_delete.add_argument("--persona-instance-id", default=None)
    persona_chat_delete.add_argument("--requested-by", default="cli")
    persona_chat_delete.add_argument("--json", action="store_true")
    persona_chat_delete.set_defaults(func=chat_delete._cmd_persona_chat_delete)
    persona_chat_history = persona_chat_subs.add_parser("history", help="Page a persona chat session's complete redaction-safe transcript")
    persona_chat_history.add_argument("--session-id", dest="session_id", required=True)
    persona_chat_history.add_argument("--limit", type=int, default=40, help="Page size (clamped 1..40)")
    persona_chat_history.add_argument("--before", default=None, help="Opaque cursor returned by the previous page")
    persona_chat_history.add_argument("--json", action="store_true")
    persona_chat_history.set_defaults(func=runtime_commands._cmd_persona_chat_history)

    persona_set_model = persona_subs.add_parser("set-model", help="Persist a persona's default provider/model (profile-default lane; future instances inherit it)")
    persona_set_model.add_argument("persona_id", help="Persona id or profile:<name>")
    persona_set_model.add_argument("--provider", default=None, help="Provider lane (canonical name or alias; api_mode is derived from it)")
    persona_set_model.add_argument("--model", default=None, help="Model id for the provider lane")
    persona_set_model.add_argument("--use-default", action="store_true", help="Clear the persona's model/provider/api_mode so the runtime default cascade applies")
    persona_set_model.add_argument("--issued-at", default=None, help="ISO-8601 issue timestamp; stale writes are superseded instead of applied")
    persona_set_model.add_argument("--requested-by", default="operator")
    persona_set_model.add_argument("--json", action="store_true")
    persona_set_model.set_defaults(func=model_and_skills_commands._cmd_persona_set_model)
    persona_set_skills = persona_subs.add_parser("set-skills", help="Persist a persona's default skill set (profile-default lane; future instances inherit it)")
    persona_set_skills.add_argument("persona_id", help="Persona id or profile:<name>")
    # `--skill` keeps the tree's ONE spelling — `action="append", default=None`
    # — so an omitted flag arrives as ABSENT and not as `[]`. What absent MEANS
    # is what differs by tier: on `persona instance update-profile` and `agent
    # create` absent means "inherit the persona's skills", and `[]` means
    # "override with none". The template tier is the ROOT of that cascade and
    # has no one to inherit from, so absent cannot be a write at all — it is a
    # typed `nothing_to_write` refusal (see `_cmd_persona_set_skills`). Keeping
    # `default=None` is what lets the handler tell the two apart; `default=[]`
    # would hand a transport-mangled argv a silent clear-every-skill.
    persona_set_skills.add_argument("--skill", dest="skills", action="append", default=None, help="Skill id for the persona default set (repeatable); the flags given REPLACE the stored set")
    persona_set_skills.add_argument("--clear-skills", action="store_true", help="Write an empty default set: every future inheriting placement starts with no skills")
    persona_set_skills.add_argument("--issued-at", default=None, help="ISO-8601 issue timestamp; stale writes are superseded instead of applied")
    persona_set_skills.add_argument("--requested-by", default="operator")
    persona_set_skills.add_argument("--json", action="store_true")
    persona_set_skills.set_defaults(func=model_and_skills_commands._cmd_persona_set_skills)
    persona_instance = persona_subs.add_parser("instance", help="Create, open, steer, retire, and maintain persona instances (chat is the only messaging lane)")
    persona_instance_subs = persona_instance.add_subparsers(dest="persona_instance_command")
    persona_instance_create = persona_instance_subs.add_parser("create", help="Create an Agent Profile (operator chat channel) or an additional placement-backed instance (--add-instance); requires --display-name")
    persona_instance_create.add_argument("--persona", dest="persona_id", required=True)
    persona_instance_create.add_argument("--title", required=True, help="Fallback display name when --display-name is empty (launcher wire-compat)")
    persona_instance_create.add_argument("--requested-by", default="cli")
    _add_coordinator_permission_args(persona_instance_create)
    persona_instance_create.add_argument("--client-message-id", default=None)
    persona_instance_create.add_argument("--display-name", default=None)
    persona_instance_create.add_argument("--session-id", default=None)
    persona_instance_create.add_argument("--kill-active", action="store_true", help="Cancel the current run/worker before replacing the active chat")
    persona_instance_create.add_argument("--add-instance", action="store_true", help="Create an additional placement-backed instance instead of targeting the primary placement")
    persona_instance_create.add_argument("--placement-id", default=None, help="Scene itemId for an additional placement-backed instance; must end in the deliberate-placement shape <persona-token>_agent_<hex8>")
    persona_instance_create.add_argument("--workspace-id", "--workspace", dest="workspace_id", default=None, help="Mission Control workspace the placement belongs to (scope-provenance pointer; only meaningful with --add-instance)")
    persona_instance_create.add_argument("--realm-id", dest="realm_id", default=None, help="Mission Control realm the placement belongs to (scope-provenance pointer; only meaningful with --add-instance)")
    # S70 removed `--auto-run` / `--stream` / `--max-actions` / `--max-seconds`,
    # and S-DUP5 finished the set with `--message`: all five belonged to the
    # retired free-floating assignment queue (argparse now rejects them cleanly
    # instead of silently ignoring them). `--title` is NOT one of them — it is
    # the live display-name fallback above.
    persona_instance_create.add_argument("--json", action="store_true")
    persona_instance_create.set_defaults(func=lifecycle_commands._cmd_persona_instance_create)
    persona_instance_open = persona_instance_subs.add_parser("open-chat", help="Bind a persona instance to a durable chat session without ticking")
    persona_instance_open.add_argument("--persona", dest="persona_id", required=True)
    persona_instance_open.add_argument("--persona-instance-id", default=None, help="Exact existing persona instance to bind when minting a new chat")
    persona_instance_open.add_argument("--session-id", default=None)
    persona_instance_open.add_argument("--new-session", action="store_true", help="Mint and select a fresh server-owned chat session for the target instance")
    persona_instance_open.add_argument("--idempotency-key", default=None, help="Stable retry key required with --new-session")
    persona_instance_open.add_argument("--kill-active", action="store_true", help="Cancel the current run/worker before replacing the active chat")
    persona_instance_open.add_argument("--add-instance", action="store_true", help="Open the chat on an additional placement-backed instance")
    persona_instance_open.add_argument("--placement-id", default=None, help="Scene itemId for an additional placement-backed instance; must end in the deliberate-placement shape <persona-token>_agent_<hex8>")
    persona_instance_open.add_argument("--workspace-id", "--workspace", dest="workspace_id", default=None, help="Mission Control workspace the placement belongs to (scope-provenance pointer; only meaningful with --add-instance)")
    persona_instance_open.add_argument("--realm-id", dest="realm_id", default=None, help="Mission Control realm the placement belongs to (scope-provenance pointer; only meaningful with --add-instance)")
    persona_instance_open.add_argument("--display-name", default=None, help="Authoritative name for a deliberately placed additional instance; ignored unless --add-instance")
    persona_instance_open.add_argument("--requested-by", default="cli")
    _add_coordinator_permission_args(persona_instance_open)
    persona_instance_open.add_argument("--json", action="store_true")
    persona_instance_open.set_defaults(func=chat_open._cmd_persona_instance_open_chat)
    # `persona instance resolve-chat-turn` lived here until 2026-08-19: a
    # second parser binding the SAME handler as `mission-chat turn-resolve`,
    # with the same four required flags and the instance id positional instead
    # of a flag. Two spellings for one operation, zero invocations in either
    # repo, and the launcher has always emitted `turn-resolve` — so the alias
    # could only ever be reached by a human who read the wrong doc line.
    # S70 removed `persona instance message`. It queued a "free-floating
    # persona assignment" — a lane whose only durable consumer was the tick
    # loop removed by the 2026-07-30 chat-only purge (a queued row dead-ended
    # forever; the advertised `run-once` follow-up verb never existed), and its
    # `--auto-run` variant was a second, parallel turn authority. Messaging an
    # instance is `harness mission-chat message`.
    persona_instance_close = persona_instance_subs.add_parser("close", help="Cancel residual free-floating assignment rows for one persona instance (maintenance; the lane that minted them is retired)")
    persona_instance_close.add_argument("persona_instance_id")
    persona_instance_close.add_argument("--reason", required=True)
    persona_instance_close.add_argument("--requested-by", default="cli")
    _add_coordinator_permission_args(persona_instance_close)
    persona_instance_close.add_argument("--json", action="store_true")
    persona_instance_close.set_defaults(func=instance_commands._cmd_persona_instance_close)
    persona_instance_archive = persona_instance_subs.add_parser("archive", help="Complete residual free-floating assignment rows for one persona instance (maintenance; the lane that minted them is retired)")
    persona_instance_archive.add_argument("persona_instance_id")
    persona_instance_archive.add_argument("--reason", default="archived residual free-floating assignment row")
    persona_instance_archive.add_argument("--requested-by", default="cli")
    persona_instance_archive.add_argument("--json", action="store_true")
    persona_instance_archive.set_defaults(func=instance_commands._cmd_persona_instance_archive)
    # D4. `delete` is an argparse ALIAS, not a second parser: one parser object,
    # so the two spellings cannot drift in flags, help, or handler — which is
    # the failure mode a copied `add_parser` would have had, and the operator
    # ruling ("why retire it should just be delete") is about the WORD, not
    # about a second behaviour.
    #
    # `retire` stays the canonical name here and everywhere machine-readable —
    # the RPC method, the capability id `persona.instance.retire`, the event
    # types, the internal symbols. Renaming those would break every launcher
    # build in the field to change a noun; the operator reads "delete" on the
    # surface, and the surface is where the ruling applies.
    persona_instance_retire = persona_instance_subs.add_parser("retire", aliases=["delete"], help="Delete (end-of-life) a placement-backed persona instance: archive its row (chat history preserved)")
    persona_instance_retire.add_argument("persona_instance_id")
    persona_instance_retire.add_argument("--reason", default="placement removed")
    persona_instance_retire.add_argument("--requested-by", default="cli")
    # S8b-b: the same flag `agent retire` took, on the OTHER door onto the same
    # `perform_agent_retire`. S8b withheld it here on the stated grounds that
    # "no gesture behind it is the truth for that door" — which was measured to
    # be false: the launcher's `persona.instance.retire` capability IS this
    # door, fired from `MissionOfficeLayoutController.retireAgent`'s
    # `Unavailable` arm, and `retireAgent` takes `correlationId` as a REQUIRED
    # parameter. So the arm the launcher falls back to when the RPC lane cannot
    # carry the call was the ONE arm that dropped the token — on the lane where
    # joining the two halves of a gesture matters most, because a degraded
    # transport is exactly when an operator greps the event log.
    persona_instance_retire.add_argument("--correlation-id", dest="correlation_id", default=None)
    _add_coordinator_permission_args(persona_instance_retire)
    persona_instance_retire.add_argument("--json", action="store_true")
    persona_instance_retire.set_defaults(func=instance_commands._cmd_persona_instance_retire)
    # No `sweep-orphans`: S65 retired the owning-task release inference the
    # janitor decided on (and de-registered the `persona_instance.reaped` event
    # it emitted), leaving only this registration and a handler that raised
    # AttributeError. Retired at S66 with them. `persona instance retire` is the
    # live end-of-life verb.
    persona_instance_steer = persona_instance_subs.add_parser("steer", help="Re-route a persona instance's living-graph wiring (Stage 77 steering edge; supports multi-parent fan-in)")
    persona_instance_steer.add_argument("persona_instance_id")
    persona_instance_steer.add_argument("--parent", dest="parent_instance_id", default=None, help="Back-compat: REPLACE the steering set with this single parent (== --set-parents <p>)")
    persona_instance_steer.add_argument("--add-parent", dest="add_parent", default=None, help="Additively ADD one parent to the steering set (fan-in; idempotent)")
    persona_instance_steer.add_argument("--remove-parent", dest="remove_parent", default=None, help="Remove ONE parent from the steering set (detach-one; last one detaches)")
    persona_instance_steer.add_argument("--set-parents", dest="set_parents", nargs="+", default=None, metavar="PARENT", help="Declaratively REPLACE the whole steering set with these parents (fan-in)")
    persona_instance_steer.add_argument("--goal", dest="goal_id", default=None, help="Correlation id this sub-agent inherits from its parent; rides the snapshot as persona_instance.goal_id, which the Launcher groups its agent rooms by")
    persona_instance_steer.add_argument("--detach", action="store_true", help="Detach from ALL parents and clear the inherited correlation id (becomes a standalone owner)")
    persona_instance_steer.add_argument("--requested-by", default="operator")
    _add_coordinator_permission_args(persona_instance_steer)
    persona_instance_steer.add_argument("--json", action="store_true")
    persona_instance_steer.set_defaults(func=instance_commands._cmd_persona_instance_steer)
    persona_instance_repair = persona_instance_subs.add_parser(
        "repair-steering",
        help="Strip non-instance principals (e.g. the operator) out of a persona instance's steering fields; --dry-run previews without writing or emitting",
    )
    persona_instance_repair.add_argument("persona_instance_id", nargs="?", default=None, help="Target one row; omit and pass --all to scan every row")
    persona_instance_repair.add_argument("--all", action="store_true", help="Scan and repair every persona-instance row")
    _add_stage42_global_args(
        persona_instance_repair,
        controls=frozenset({"dry_run"}),
        omit=frozenset({"--output", "--quiet", "--fields"}),
    )
    persona_instance_repair.set_defaults(func=instance_commands._cmd_persona_instance_repair_steering)
    persona_instance_return = persona_instance_subs.add_parser("return-summary", help="Post a bounded child summary back into a parent chat session")
    persona_instance_return.add_argument("persona_instance_id")
    persona_instance_return.add_argument("--parent-session-id", required=True)
    persona_instance_return.add_argument("--summary", required=True)
    persona_instance_return.add_argument("--proof-id", dest="proof_ids", action="append", default=[])
    persona_instance_return.add_argument("--artifact-ref", dest="artifact_refs", action="append", default=[])
    persona_instance_return.add_argument("--json", action="store_true")
    persona_instance_return.set_defaults(func=instance_commands._cmd_persona_instance_return_summary)
    persona_instance_update = persona_instance_subs.add_parser("update-profile", help="Update runtime persona-instance profile overrides without editing the backing Hermes profile")
    persona_instance_update.add_argument("persona_instance_id")
    persona_instance_update.add_argument("--display-name", default=None)
    persona_instance_update.add_argument("--current-chat-goal", default=None)
    persona_instance_update.add_argument("--goal", dest="goal_id", default=None)
    persona_instance_update.add_argument("--skill", dest="skills", action="append", default=None)
    persona_instance_update.add_argument("--clear-skills", action="store_true", help="Pin this agent to NO skills — an explicit empty set, not the template's")
    persona_instance_update.add_argument("--inherit-skills", dest="inherit_skills", action="store_true", help="Drop this agent's own skill set so it follows its persona template again, live")
    persona_instance_update.add_argument("--requested-by", default="operator")
    _add_coordinator_permission_args(persona_instance_update)
    persona_instance_update.add_argument("--json", action="store_true")
    persona_instance_update.set_defaults(func=instance_commands._cmd_persona_instance_update_profile)
    persona_instance_set_model = persona_instance_subs.add_parser("set-model", help="Persist an instance-level provider/model override (this agent only; duplicates keep theirs)")
    persona_instance_set_model.add_argument("persona_instance_id")
    persona_instance_set_model.add_argument("--provider", default=None, help="Provider lane (canonical name or alias; api_mode is derived from it)")
    persona_instance_set_model.add_argument("--model", default=None, help="Model id for the provider lane")
    persona_instance_set_model.add_argument("--reasoning-effort", dest="reasoning_effort", default=None, help="Per-instance reasoning effort for reasoning-capable models (none, minimal, low, medium, high, xhigh); empty string clears it")
    persona_instance_set_model.add_argument("--use-profile-default", action="store_true", help="Clear the instance override so the backing profile default applies live")
    persona_instance_set_model.add_argument("--issued-at", default=None, help="ISO-8601 issue timestamp; stale writes are superseded instead of applied")
    persona_instance_set_model.add_argument("--requested-by", default="operator")
    _add_coordinator_permission_args(persona_instance_set_model)
    persona_instance_set_model.add_argument("--json", action="store_true")
    persona_instance_set_model.set_defaults(func=model_and_skills_commands._cmd_persona_instance_set_model)

    mission_chat = subs.add_parser("mission-chat", help="Canonical Mission Control chat path")
    mission_chat_subs = mission_chat.add_subparsers(dest="mission_chat_command")
    mission_chat_message = mission_chat_subs.add_parser("message", help="Send one Mission Control chat turn through the normal Hermes profile context")
    mission_chat_message.add_argument("--persona", dest="persona_id", required=True)
    mission_chat_message.add_argument("--persona-instance-id", default=None)
    mission_chat_message.add_argument("--session-id", default=None)
    # store_true (absent → False) is deliberate on THIS lane: False is now an
    # explicit "continue the target's current default thread", so the operator
    # console and any bare CLI send keep threading exactly as before (that
    # pointer follows the most recently established thread — it is not a
    # separate durable pair thread), while a caller that omits
    # the flag entirely (the agent_chat_send dispatch lane, which forwards
    # None) falls through to agent_runtime.mission_chat.dispatch_session_policy.
    mission_chat_message.add_argument("--new-session", dest="new_session", action="store_true", help="Force a fresh canonical chat session for the target instead of continuing the default thread (agent_chat_send new_session lane); ignored when --session-id is given")
    # The echo half of the clarify binding. A reply that carries the token the
    # question shipped down lands in the question's OWN thread — outranking both
    # the policy default and a stale --session-id (reported, never silent, in the
    # turn's clarify_binding block). Unknown/pruned tokens degrade to normal
    # precedence rather than refusing.
    mission_chat_message.add_argument("--clarify-token", dest="clarify_token", default=None, help="Answer a clarify question by its token (clarify_request.clarify_token from the asking turn); binds this reply to the thread the question was asked in")
    # No --task/--goal: the goal/task mission lane is retired (contract 45) and
    # chat is the only lane. They were not inert residue -- the handler consumed
    # them by writing instance.current_task_id/goal_id and flipping instance.mode
    # to the RETIRED "task_bound", so an armed row re-armed retired runtime state
    # on the operator's next ordinary message. The Launcher stopped emitting them
    # first (launcher 87957547); this is the lockstep half. `persona instance
    # steer --goal` is untouched -- goal_id rides the contract-45 wire and the
    # Launcher groups its agent rooms by it.
    # Default None = "no title opinion": consumed as the fresh thread's title
    # when this send mints one, otherwise the durable "<persona> chat" title
    # stands. A literal default would name every freshly minted thread after it.
    mission_chat_message.add_argument("--title", default=None, help="Title for a chat session this send MINTS (a fresh --new-session thread, or a dispatch under the new_per_dispatch policy); ignored when continuing an existing thread")
    mission_chat_message.add_argument("--message", required=True)
    mission_chat_message.add_argument("--provider", default=None, help="Provider override for this persona chat session only")
    mission_chat_message.add_argument("--model", default=None, help="Model override for this persona chat session only")
    mission_chat_message.add_argument("--use-agent-default", action="store_true", help="Clear the chat-scoped provider/model override before sending")
    mission_chat_message.add_argument("--surface-prompt", default="")
    mission_chat_message.add_argument("--agents-file", default=None, help="Absolute path to one operator-selected workspace AGENTS.md to inject for this turn")
    mission_chat_message.add_argument("--workspace-id", "--workspace", default=None)
    mission_chat_message.add_argument("--workspace-name", default=None)
    mission_chat_message.add_argument("--intent-hint", default="chat")
    mission_chat_message.add_argument("--requested-by", default="cli")
    mission_chat_message.add_argument("--client-message-id", default=None)
    mission_chat_message.add_argument("--idempotency-key", default=None)
    mission_chat_message.add_argument("--stream", action="store_true", help="Emit operator-chat deltas and the final payload as NDJSON")
    # Default is resolved at RUN time (agent_runtime.mission_chat.default_max_seconds
    # in the ROOT config.yaml, itself defaulting to 240s) rather than pinned in the
    # parser: an argparse default cannot be told apart from an explicit flag, and
    # "explicit --max-seconds always wins over the configured default" has to be
    # decidable. `None` here IS "the caller expressed no opinion".
    mission_chat_message.add_argument("--max-seconds", type=float, default=None, help="Wall budget for this turn (default: agent_runtime.mission_chat.default_max_seconds, or 240s when unset). The agent is told how much remains, and the last max(60s, 15%%) is reserved for a final checkpoint reply; the turn then settles as budget_exhausted (terminal, no turn-resolve)")
    mission_chat_message.add_argument("--compression-threshold-tokens", type=int, default=None, help="One-turn native-compression proof seam; overrides the compressor token threshold without changing profile config")
    mission_chat_message.add_argument("--compression-protect-first-n", type=int, default=None, help="One-turn native-compression proof seam; override protected head messages")
    mission_chat_message.add_argument("--compression-protect-last-n", type=int, default=None, help="One-turn native-compression proof seam; override protected tail messages")
    mission_chat_message.add_argument("--relay-chain", default=None, help="Comma-separated canonical persona ids already on the agent-relay chain (envelope provenance for chained agent_chat_send hops)")
    mission_chat_message.add_argument("--relay-deadline-epoch", type=float, default=None, help="Absolute unix-epoch deadline shared by every hop on the relay chain")
    # Sender provenance, not guard logic: the sender's chat-root session id
    # scopes bare-persona target resolution to the SENDER's workspace. The
    # in-process relay always carried it on the args object; a DETACHED dispatch
    # runs its target turn in a CHILD PROCESS, so without an argv spelling the
    # child would silently resolve bare personas against the wrong scope.
    mission_chat_message.add_argument("--requested-by-session", dest="requested_by_session", default=None, help="Chat-root session id of the sender (envelope provenance; scopes bare-persona target resolution to the sender's workspace)")
    # The tri-state ``new_session`` has no argparse spelling: absent is False
    # ("continue the target's current default thread"), present is True, and
    # there is no way to say UNSET ("no opinion — let
    # agent_runtime.mission_chat.dispatch_session_policy decide"), which is
    # exactly what the dispatch lane forwards in-process. Changing
    # ``--new-session``'s default to None would express it, but would also
    # silently start minting a fresh thread for every bare CLI send that omits
    # the flag. This states the unset case explicitly instead, so the child
    # process reproduces the in-process lane's threading exactly.
    mission_chat_message.add_argument("--defer-thread-policy", dest="defer_thread_policy", action="store_true", help="State NO opinion about the thread: let agent_runtime.mission_chat.dispatch_session_policy decide (the tri-state 'unset' the in-process dispatch lane forwards). Overrides --new-session")
    mission_chat_message.add_argument("--json", action="store_true")
    mission_chat_message.set_defaults(func=chat_turn_message._cmd_mission_chat_message)
    mission_chat_queue_skill = mission_chat_subs.add_parser("queue-skill", help="Load a skill on the next Mission Control chat turn")
    mission_chat_queue_skill.add_argument("--persona", dest="persona_id", required=True)
    mission_chat_queue_skill.add_argument("--persona-instance-id", default=None)
    mission_chat_queue_skill.add_argument("--session-id", required=True)
    mission_chat_queue_skill.add_argument("--skill", action="append", default=[])
    mission_chat_queue_skill.add_argument("--skills", nargs="+", default=[])
    mission_chat_queue_skill.add_argument("--json", action="store_true")
    mission_chat_queue_skill.set_defaults(func=chat_coordinator._cmd_mission_chat_queue_skill)
    mission_chat_steer = mission_chat_subs.add_parser("steer", help="Steer an active streamed Mission Control chat turn")
    mission_chat_steer.add_argument("--session-id", required=True)
    mission_chat_steer.add_argument("--message", required=True)
    mission_chat_steer.add_argument("--client-message-id", required=True)
    mission_chat_steer.add_argument("--persona", dest="persona_id", default=None)
    mission_chat_steer.add_argument("--persona-instance-id", default=None)
    mission_chat_steer.add_argument("--json", action="store_true")
    mission_chat_steer.set_defaults(func=chat_coordinator._cmd_mission_chat_steer)
    mission_chat_resolve = mission_chat_subs.add_parser(
        "turn-resolve", help="Resolve one outcome_unknown chat turn"
    )
    mission_chat_resolve.add_argument("--session-id", required=True)
    mission_chat_resolve.add_argument("--client-message-id", required=True)
    mission_chat_resolve.add_argument("--turn-id", required=True)
    mission_chat_resolve.add_argument("--persona-instance-id", default=None)
    mission_chat_resolve.add_argument("--action", choices=["abandon"], required=True)
    mission_chat_resolve.add_argument("--json", action="store_true")
    mission_chat_resolve.set_defaults(func=chat_tickets_commands._cmd_mission_chat_turn_resolve)
    # Read-only adoption readout for the clarify-token binding. Registered with
    # the NON-mutating stage42 args on purpose: it never mints, settles, or
    # sweeps, so it has no --dry-run to honor and nothing to confirm. Whether
    # agents are echoing the token is answered from state the binding already
    # records, with no new event kinds (telemetry is not the EventLog here).
    mission_chat_clarify_tickets = mission_chat_subs.add_parser(
        "clarify-tickets",
        help="Clarify-token adoption readout: live tickets with state/age/session binding, and the bound_via histogram",
    )
    _add_stage42_global_args(
        mission_chat_clarify_tickets, controls=frozenset({"limit", "sort"})
    )
    mission_chat_clarify_tickets.add_argument("--session-id", default=None, help="Only list tickets bound to this chat root (counts still cover the whole store)")
    mission_chat_clarify_tickets.add_argument("--state", default=None, choices=["open", "answered", "rebound"], help="Only list tickets in this lifecycle state (counts still cover the whole store)")
    mission_chat_clarify_tickets.set_defaults(func=chat_tickets_commands._cmd_mission_chat_clarify_tickets)
    # The agent-to-agent delivery QUEUE, as opposed to the chat turns it forges
    # into. Repair verbs only: the drain owns the normal path, and this group
    # exists for the rows it gave up on.
    mission_chat_dispatch = mission_chat_subs.add_parser(
        "dispatch", help="Operate the agent-to-agent dispatch delivery queue"
    )
    mission_chat_dispatch_subs = mission_chat_dispatch.add_subparsers(
        dest="mission_chat_dispatch_command"
    )
    mission_chat_dispatch_redeliver = mission_chat_dispatch_subs.add_parser(
        "redeliver",
        help=(
            "Re-arm a DROPPED dispatch reply for another delivery pass (dropped -> "
            "pending, attempts 0, previous drop reason cleared)"
        ),
    )
    mission_chat_dispatch_redeliver.add_argument(
        "dispatch_id", help="The dispatch handle, e.g. dispatch-2540634d5cf3"
    )
    mission_chat_dispatch_redeliver.add_argument("--json", action="store_true")
    mission_chat_dispatch_redeliver.set_defaults(
        func=chat_tickets_commands._cmd_mission_chat_dispatch_redeliver
    )

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

    providers = subs.add_parser(
        "providers",
        help="List credential pools with typed auth health (machine-readable via --json)",
    )
    providers.add_argument("--json", action="store_true")
    providers.set_defaults(func=_cmd_providers)

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

    health = subs.add_parser("health", help="Check Harness runtime/provider dependencies are reachable and configured")
    health.add_argument("--json", action="store_true")
    health.set_defaults(func=runtime_commands._cmd_health)

    verify = subs.add_parser("verify", help="Run runtime smoke verification: read-only harness CLI commands plus the focused store/snapshot/status test modules")
    verify.add_argument("--json", action="store_true")
    verify.add_argument("--mode", choices=["live-tony", "ci", "temp-root"], default="ci")
    verify.add_argument("--skip-tests", action="store_true")
    verify.set_defaults(func=runtime_commands._cmd_verify)

    config = subs.add_parser("config", help="Inspect Harness runtime config")
    config_subs = config.add_subparsers(dest="config_command")
    config_show = config_subs.add_parser("show", help="Show effective Harness runtime config")
    config_show.add_argument("--json", action="store_true")
    config_show.set_defaults(func=runtime_commands._cmd_config)

    migrate = subs.add_parser("migrate", help="Inspect Harness runtime migrations")
    migrate.add_argument("--check", action="store_true", help="Report pending migrations without modifying data")
    migrate.add_argument("--json", action="store_true")
    migrate.set_defaults(func=runtime_commands._cmd_migrate)

    observe = subs.add_parser("observe", help="Show redaction-safe Mission Control observability")
    observe.add_argument("--json", action="store_true")
    observe.set_defaults(func=runtime_commands._cmd_observe)

    contracts = subs.add_parser("contracts", help="Inspect canonical Mission Control event contracts")
    contracts_subs = contracts.add_subparsers(dest="contracts_command")
    contracts_dump = contracts_subs.add_parser("dump", help="Dump redaction-safe contract registry")
    contracts_dump.add_argument("--json", action="store_true")
    contracts_dump.set_defaults(func=runtime_commands._cmd_contracts_dump)

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

    persona_instance = subs.add_parser(
        "persona-instance", help="Manage durable persona-instance store rows"
    )
    persona_instance_subs = persona_instance.add_subparsers(
        dest="persona_instance_command", required=True
    )
    persona_instance_reconcile = persona_instance_subs.add_parser(
        "reconcile",
        help=(
            "Archive-and-fold legacy-id persona-instance rows onto their canonical "
            "channel (duplicate agent cards repair); records identity_map aliases; "
            "prunes orphan rows; repairs missing steering parents and chat-session "
            "bindings whose session SessionDB no longer has"
        ),
    )
    persona_instance_reconcile.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report actions without mutating the store. To ONLY ask which chat "
            "bindings are stale, prefer `persona-instance chat-bindings`, which "
            "has no write mode at all"
        ),
    )
    persona_instance_reconcile.add_argument("--json", action="store_true")
    persona_instance_reconcile.set_defaults(func=runtime_commands._cmd_persona_instance_reconcile)

    # H4 (plan realm-pull-live-projection). `reconcile` DEFAULTS TO APPLY and
    # runs five phases; asking it "which instance is the amber chip" means
    # remembering --dry-run on a verb that archives rows, prunes graphs and
    # appends events when you forget. This verb has NO write mode to forget: it
    # is the phase-4 probe alone, read-only by construction.
    persona_instance_chat_bindings = persona_instance_subs.add_parser(
        "chat-bindings",
        help=(
            "READ-ONLY: name every persona instance whose bound chat session "
            "SessionDB no longer holds — the producer of the snapshot's "
            "`session_not_in_db` parity drop. Never writes; `persona-instance "
            "reconcile` is the repair"
        ),
    )
    persona_instance_chat_bindings.add_argument("--json", action="store_true")
    persona_instance_chat_bindings.set_defaults(func=runtime_commands._cmd_persona_instance_chat_bindings)

    persona_instance_detail = persona_instance_subs.add_parser(
        "detail",
        help=(
            "Serve the tool-detail payloads (tool_resolution / turn_tool_context / "
            "permission_state / blocked_tools) evicted from the steady-state frame "
            "behind the visibility_ref pointer"
        ),
    )
    persona_instance_detail.add_argument(
        "instance_id", help="Persona-instance id (or persona id) whose tool detail to fetch"
    )
    persona_instance_detail.add_argument("--json", action="store_true")
    persona_instance_detail.set_defaults(func=_cmd_persona_instance_detail)

    agent = subs.add_parser("agent", help="Inspect and rebind harness agent definitions")
    agent_subs = agent.add_subparsers(dest="agent_command", required=True)
    agent_list = agent_subs.add_parser("list", help="List persisted/configured agent definitions")
    agent_list.add_argument("--all-profiles", action="store_true")
    _add_stage42_global_args(agent_list, controls=frozenset({"sort"}))
    agent_list.set_defaults(func=_cmd_agent_list)

    # UC-H3: the ONE unified create door for scripts, cron and operators. It
    # calls `agent_create.perform_agent_create` — the exact function
    # `runtime.agent.create` answers with — so a roster row, a chat root and an
    # office placement land together or not at all. `persona instance create`
    # deliberately stays the roster-only / serve-absent recovery door: it mints
    # no placement, which is its feature, not its bug.
    agent_create = agent_subs.add_parser(
        "create",
        help="Place an agent: roster row, chat root and office placement in ONE atomic call",
    )
    agent_create.add_argument("--persona", dest="persona_id", required=True, help="Roster persona id (or profile:<token>); an unknown id is refused before any write")
    agent_create.add_argument("--workspace", "--workspace-id", dest="workspace_id", required=True, help="Mission Control workspace the placement lands in; must already exist")
    # OPTIONAL since plan S2. Omitted, the service resolves the slot through
    # `agent_runtime.office_layout_policy` — the same lattice the launcher
    # predicts with — so a door with no canvas (this one, a cron, a remote
    # connector over `call`) has an answer instead of a required guess.
    agent_create.add_argument("--pos", dest="pos", nargs=2, metavar=("X", "Y"), default=None, help="Canvas position for the placement; omitted, the layout policy picks the first free slot in the folder")
    # BYTE-PARALLEL with the RPC's `skills` param (UC-H3's rule, plan D5).
    # `default=None` is load-bearing and is the same spelling `persona instance
    # update-profile` uses: an OMITTED flag must reach the service as an ABSENT
    # key, because absent means "inherit the persona's skills" while `[]` means
    # "override with none" — two different agents. `append` is what makes
    # `--skill a --skill b` one request rather than a last-one-wins.
    agent_create.add_argument("--skill", dest="skills", action="append", default=None, help="Assign a skill to the new instance (repeatable); a canonical harness skill is installed and hash-verified first")
    agent_create.add_argument("--display-name", default=None, help="Authoritative name; omitted falls back to the persona's configured display name")
    agent_create.add_argument("--placement-id", default=None, help="Scene itemId to predict the actor key from; must end in <persona-token>_agent_<hex8>, and omitted mints one server-side")
    agent_create.add_argument("--realm-id", dest="realm_id", default=None)
    agent_create.add_argument("--folder", default=None, help="Office folder for the placement (default: Agents)")
    # A re-run is a NEW gesture unless the caller says otherwise — the same rule
    # the launcher applies by stamping micros into every key. A script that
    # wants resume-on-retry passes its own stable key.
    agent_create.add_argument("--idempotency-key", dest="idempotency_key", default=None, help="Stable retry key; omitted mints a fresh cli-<uuid4> so a re-run is a new gesture")
    agent_create.add_argument("--correlation-id", dest="correlation_id", default=None)
    agent_create.add_argument("--json", action="store_true")
    agent_create.set_defaults(func=lifecycle_commands._cmd_agent_create)

    # S5: the INVERSE of the create above, and the door that never existed. The
    # store method has always archived BOTH halves (roster row + every office
    # actor bound to the instance); what was missing was a verb over it and an
    # ack that NAMES what it archived. `persona instance retire` stays and calls
    # the very same service function, so the two doors cannot drift.
    agent_retire = agent_subs.add_parser(
        "retire",
        help="Retire a placed agent: archive its roster row AND every office actor bound to it in ONE call",
    )
    agent_retire.add_argument("persona_instance_id", help="Persona-instance id of the placement to retire")
    agent_retire.add_argument("--reason", default="placement removed")
    agent_retire.add_argument("--requested-by", dest="requested_by", default="cli")
    # S8b: the flag `agent create` has carried since D-V2, on the verb that
    # undoes it. A script that placed an agent under one gesture token can now
    # delete it under that token, and ONE grep over the event log joins both
    # halves — which is the whole point of the token and was true of every
    # level-mutating verb except this one.
    agent_retire.add_argument("--correlation-id", dest="correlation_id", default=None)
    agent_retire.add_argument("--json", action="store_true")
    agent_retire.set_defaults(func=lifecycle_commands._cmd_agent_retire)

    agent_set_profile = agent_subs.add_parser(
        "set-profile",
        help="Rebind an agent to a different Hermes profile (the ONE door; cascades every instance projection)",
    )
    agent_set_profile.add_argument("persona_id", help="Store-persisted agent id")
    agent_set_profile.add_argument("--profile", required=True, help="Target Hermes profile name; must exist and resolve ready")
    agent_set_profile.add_argument("--requested-by", default="operator")
    _add_stage42_global_args(agent_set_profile, controls=frozenset({"dry_run"}))
    agent_set_profile.set_defaults(func=_cmd_agent_set_profile)

    skills = subs.add_parser("install-harness-skills", help="Install versioned Harness skills into configured persona profiles")
    skills.add_argument("--active-profile-only", action="store_true", help="Install all Harness skills only into the active Hermes profile")
    skills.add_argument("--json", action="store_true")
    skills.set_defaults(func=_cmd_install_harness_skills)

    # STAGE 6 (2026-08-22): the help text read "Write redaction-safe
    # snapshot.json" until the boot-cache writer it named (``snapshot.write_snapshot``)
    # was deleted with the read-model lane. This verb BUILDS a frame and prints
    # it; it writes no store state. `--json` is the only flag it has ever had —
    # the cache preference was resolved from config, never from argv, so there
    # was no cache-lane flag to retire with the lane.
    snap = subs.add_parser("snapshot", help="Build and print a redaction-safe runtime snapshot frame")
    snap.add_argument("--json", action="store_true")
    snap.set_defaults(func=runtime_commands._cmd_snapshot)
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

    pets = subs.add_parser("pets", help="Mission Control Petdex bridge")
    pets_subs = pets.add_subparsers(dest="pets_command", required=True)
    pets_gallery = pets_subs.add_parser("gallery", help="List Petdex pets for Launcher")
    pets_gallery.add_argument("--local-only", action="store_true", help="Only include installed pets; skip the remote manifest")
    pets_gallery.add_argument("--limit", type=int, default=0, help="Maximum remote rows; 0 = all")
    pets_gallery.add_argument("--query", default="", help="Filter by slug/display name substring")
    pets_gallery.add_argument("--json", action="store_true")
    pets_gallery.set_defaults(func=_cmd_pets_gallery)
    pets_install = pets_subs.add_parser("install", help="Install a Petdex pet by slug")
    pets_install.add_argument("slug")
    pets_install.add_argument("--force", action="store_true")
    pets_install.add_argument("--json", action="store_true")
    pets_install.set_defaults(func=_cmd_pets_install)
    pets_sprite = pets_subs.add_parser("sprite", help="Return an installed pet spritesheet payload")
    pets_sprite.add_argument("slug")
    pets_sprite.add_argument("--no-sheet", dest="no_sheet", action="store_true", help="Metadata only: drop `spritesheetBase64` and carry `sheet`, the absolute path, in its place. `spritesheetRevision` and every geometry/taxonomy key are unchanged. Mirrors `characters sprite --no-sheet`. The default is byte-identical to what it always was")
    pets_sprite.add_argument("--json", action="store_true")
    pets_sprite.set_defaults(func=_cmd_pets_sprite)
    pets_thumb = pets_subs.add_parser("thumb", help="Return a Petdex pet thumbnail")
    pets_thumb.add_argument("slug")
    pets_thumb.add_argument("--url", default="", help="Optional Petdex spritesheet URL for non-installed gallery pets")
    pets_thumb.add_argument("--json", action="store_true")
    pets_thumb.set_defaults(func=_cmd_pets_thumb)

    # Character sheets — the QA bridge for `agent.charsheet`. Deliberately a
    # sibling of `pets`, not an extension of it: character sheets carry their row
    # taxonomy as data and must never enter a pet read path (which infers the
    # taxonomy from sheet height and would misread a 16-row sheet as a 9-row pet).
    # Every verb here is a thin veneer over one CharacterDraft method; the stage
    # machine, the pixels and the revision store all live in agent/charsheet/.
    characters = subs.add_parser("characters", help="Mission Control character-sheet bridge (8-way sheets + QA)")
    characters_subs = characters.add_subparsers(dest="characters_command", required=True)

    characters_start = characters_subs.add_parser("start", help="Create a character draft at stage 'turnaround' (offline; generates nothing)")
    characters_start.add_argument("--concept", required=True, help="What to draw, e.g. 'a tall knight in green enamel armour'")
    characters_start.add_argument("--slug", default="", help="Install slug; defaults to a slugified display name")
    characters_start.add_argument("--display-name", dest="display_name", default="", help="Human name; defaults to the concept")
    characters_start.add_argument("--style", default="auto", help="Art-style hint passed to the prompts")
    characters_start.add_argument("--states", default="", help="Animation states as 'idle:6,walk:8[,cheer:5:fixed]'; default = the CHAR8 states")
    characters_start.add_argument("--directions", default="8", help="Direction scheme: 8 (five authored, three mirrored) or 4")
    characters_start.add_argument("--base-image", dest="base_image", default="", help="Identity-anchor image; copied into the draft")
    characters_start.add_argument("--authored-by", dest="authored_by", default="", help="Persona driving this authoring run, recorded as provenance; nothing scopes where the draft lives — the character library is install-wide at <hermes_root>/shared/characters, one directory for every persona and profile — but it is what lets a later reader check a resume is opening under the profile that authored it")
    characters_start.add_argument("--json", action="store_true")
    characters_start.set_defaults(func=_cmd_characters_start)
    characters_list = characters_subs.add_parser("list", help="List character drafts and installed characters")
    characters_list.add_argument("--json", action="store_true")
    characters_list.set_defaults(func=_cmd_characters_list)
    characters_backfill_home = characters_subs.add_parser("backfill-home", help="Record `hermes_home` on library drafts that carry no home, and on no others. The field is provenance of the authoring RUN, not an address — the library is install-wide, so this stamps the home THIS run resolved onto a draft that arrived without one (restored from quarantine, hand-copied in); `migrate-home` stamps the legacy source home instead, which is the case that had a better answer available. Explicit and receipted on purpose: a draft that already states a home keeps it, and the write leaves `updated` and every other key exactly as it found them, because the drafts this reaches are dormant exhibits whose timeline is evidence. Idempotent — a second run stamps nothing")
    characters_backfill_home.add_argument("--json", action="store_true")
    characters_backfill_home.set_defaults(func=_cmd_characters_backfill_home)
    characters_migrate_home = characters_subs.add_parser("migrate-home", help="Move THIS home's legacy `<HERMES_HOME>/characters` store into the install-wide library at `<hermes_root>/shared/characters`. Run once per profile that has one. Drafts keep their directory leaf names and installed characters keep their slugs, so a stored draft id still resolves; a draft carrying no `hermes_home` is stamped with the SOURCE home BEFORE it moves, because afterwards the directory no longer witnesses where it lived. A destination that already holds the leaf or slug is a per-entry REFUSAL, never a merge and never an overwrite, and nothing is deleted — the emptied source tree is left standing as its own tombstone. Idempotent: a second run moves nothing")
    characters_migrate_home.add_argument("--json", action="store_true")
    characters_migrate_home.set_defaults(func=_cmd_characters_migrate_home)
    characters_status = characters_subs.add_parser("status", help="Full draft state: stage, spec, per-item QA history")
    characters_status.add_argument("--draft", required=True, help="Draft id from `harness characters list`")
    characters_status.add_argument("--json", action="store_true")
    characters_status.set_defaults(func=_cmd_characters_status)
    characters_thumb = characters_subs.add_parser("thumb", help="Write a card-size QA crop of ONE FRAME of one row attempt (chroma keyed out, NEAREST upscale on a flat dark backdrop) and return its path")
    characters_thumb.add_argument("--draft", required=True)
    # One crop verb, two QA item kinds — the same two budget booleans for both.
    # A direction reference used to have no crop verb at all, which left the
    # launcher's card drawing a tile through the whole turnaround stage for want
    # of an ANSWER, never for want of a safe picture.
    characters_thumb_item = characters_thumb.add_mutually_exclusive_group(required=True)
    characters_thumb_item.add_argument("--row", help="An authored row key, e.g. walk-n")
    characters_thumb_item.add_argument("--direction", default="", help="An authored direction, e.g. e — crops that direction's turnaround REFERENCE instead of a row strip. Mirrored directions are never drawn and are refused. A reference holds one pose, so --frame does not apply to it")
    characters_thumb.add_argument("--attempt", type=int, default=-1, help="Which attempt to crop, 0-based as in `status --json` history; -1 = latest")
    # No defaults spelled here: the numbers live in `draft.DEFAULT_THUMB_SCALE` /
    # `draft.DEFAULT_THUMB_FRAME` and are resolved in the handler, which is also
    # where charsheet is imported — build_parser runs for EVERY harness call and
    # must not pull in Pillow.
    characters_thumb.add_argument("--frame", type=int, default=None, help="Which frame cell of the strip to crop, 0-based (default 0); the crop is the half that removes pixels, so there is always one")
    characters_thumb.add_argument("--scale", type=int, default=None, help="NEAREST upscale factor (default 2); refused, never clamped. At or below the default the OUTPUT must fit the console's fixed decode ceiling; above it the crop is a fullscreen-viewer artifact, bounded by the write ceiling and reported as withinConsoleBudget=false. The payload carries a SECOND bound, withinOwnSheet — is the crop no larger than the sheet THIS draft composes — which refuses nothing and is reported at every scale. Draw a crop inline only when BOTH are true; otherwise open it in the viewer")
    characters_thumb.add_argument("--square", action="store_true", help="Pad the finished crop onto a square flat-dark backdrop (side = the longer edge, cell centred) so the console's 1:1 centre-cover hero card shows the WHOLE frame instead of a torso zoom. The filename gains -sq and the payload says square: true. Both budget booleans are weighed on the padded output. Use it for a hero card; take the bare crop for a compare pair, whose panes align on today's shapes")
    characters_thumb.add_argument("--json", action="store_true")
    characters_thumb.set_defaults(func=_cmd_characters_thumb)
    characters_base = characters_subs.add_parser("base", help="Set or replace the draft's base identity image")
    characters_base.add_argument("--draft", required=True)
    characters_base.add_argument("--image", required=True, help="Path to the identity-anchor image; copied into the draft")
    characters_base.add_argument("--json", action="store_true")
    characters_base.set_defaults(func=_cmd_characters_base)
    characters_turnaround = characters_subs.add_parser("turnaround", help="Generate the authored direction references (stage 'turnaround')")
    characters_turnaround.add_argument("--draft", required=True)
    characters_turnaround.add_argument("--json", action="store_true")
    characters_turnaround.set_defaults(func=_cmd_characters_turnaround)
    characters_reroll_direction = characters_subs.add_parser("reroll-direction", help="Re-generate ONE direction reference, with an optional operator note")
    characters_reroll_direction.add_argument("--draft", required=True)
    characters_reroll_direction.add_argument("--direction", required=True, help="An authored direction, e.g. ne (mirrored directions are never generated)")
    characters_reroll_direction.add_argument("--note", default="", help="Operator note appended to the prompt and stored with the attempt")
    characters_reroll_direction.add_argument("--json", action="store_true")
    characters_reroll_direction.set_defaults(func=_cmd_characters_reroll_direction)
    characters_approve_direction = characters_subs.add_parser("approve-direction", help="Approve direction references; advances to stage 'rows' once all are approved")
    characters_approve_direction.add_argument("--draft", required=True)
    characters_approve_direction_which = characters_approve_direction.add_mutually_exclusive_group(required=True)
    characters_approve_direction_which.add_argument("--direction", default="", help="Approve this one direction")
    characters_approve_direction_which.add_argument("--all", dest="approve_all", action="store_true", help="Approve the latest attempt of every authored direction")
    characters_approve_direction.add_argument("--attempt", type=int, default=-1, help="Which attempt to approve; -1 = latest (single-direction only)")
    characters_approve_direction.add_argument("--json", action="store_true")
    characters_approve_direction.set_defaults(func=_cmd_characters_approve_direction)
    characters_rows = characters_subs.add_parser("rows", help="Generate the animation row strips (stage 'rows')")
    characters_rows.add_argument("--draft", required=True)
    characters_rows.add_argument("--only", default="", help="Restrict the run to these row keys, e.g. 'walk-e,walk-ne'")
    characters_rows.add_argument("--json", action="store_true")
    characters_rows.set_defaults(func=_cmd_characters_rows)
    characters_reroll_row = characters_subs.add_parser("reroll-row", help="Re-generate ONE row strip, with an optional operator note")
    characters_reroll_row.add_argument("--draft", required=True)
    characters_reroll_row.add_argument("--row", required=True, help="An authored row key, e.g. walk-e")
    characters_reroll_row.add_argument("--note", default="", help="Operator note appended to the prompt and stored with the attempt")
    characters_reroll_row.add_argument("--json", action="store_true")
    characters_reroll_row.set_defaults(func=_cmd_characters_reroll_row)
    characters_compose = characters_subs.add_parser("compose", help="Compose, validate and install the sheet (stage 'rows' → 'composed')")
    characters_compose.add_argument("--draft", required=True)
    characters_compose.add_argument("--accept-handedness", default="", help="Mirrored-art REFUSALS you have looked at and are overriding, spelled '<row>:<basis>' — take the spelling from the refusal. Per row, never blanket. TWO shapes refuse and both can be accepted: a row BOTH passes agree about ('idle-e:rotation+states'), and a row carried by a whole mirrored STATE, where every judged row of that state reads as a mirror ('jumping-e:states') — that one is accepted row by row like any other. A single-basis finding about a single row is a warning and there is nothing to accept. The basis is named on purpose: a bare row key waived a second, independent body of evidence at once. Naming a row that was not flagged is itself refused, and the honoured list rides on the installed manifest, 'characters list' and the sprite payload as {row, gain, basis}")
    characters_compose.add_argument("--json", action="store_true")
    characters_compose.set_defaults(func=_cmd_characters_compose)
    characters_auto = characters_subs.add_parser("auto", help="Drive the whole pipeline in ONE process — turnaround, approve every direction, generate the missing rows, compose and install — printing a receipt line as each stage lands. For an operator's EXPLICIT 'drive it all the way' ask and nothing else: it auto-approves the turnaround, which is the last moment a reference can change. It never overrides a handedness refusal (there is no --accept-handedness here) and it writes the same per-attempt history the interactive verbs write, so `reopen` repair and every QA crop work exactly as they do after a hand-driven run. It resumes rather than restarts: a stage whose work already exists is skipped, with the reason on the summary line, so running it after `reopen` regenerates the missing rows instead of discarding the approved ones. Output is newline-delimited — with --json every line is ONE compact object, and the LAST line is always the summary")
    characters_auto.add_argument("--draft", required=True)
    characters_auto.add_argument("--through", default="compose", choices=list(_CHARACTERS_AUTO_STEPS), help="Last step to run (default: compose, the whole pipeline). Steps before it that the draft already carries are skipped and reported")
    characters_auto.add_argument("--json", action="store_true")
    characters_auto.set_defaults(func=_cmd_characters_auto)
    characters_reopen = characters_subs.add_parser("reopen", help="Reopen a composed draft for fixes (stage 'composed' → 'rows'); the installed sheet stays until the next compose")
    characters_reopen.add_argument("--draft", required=True)
    characters_reopen.add_argument("--json", action="store_true")
    characters_reopen.set_defaults(func=_cmd_characters_reopen)
    characters_add_state = characters_subs.add_parser("add-state", help="Add ONE animation state to a draft at stage 'rows' (reopen a composed draft first); the new rows start un-generated and no approved row is touched")
    characters_add_state.add_argument("--draft", required=True)
    characters_add_state.add_argument("--state", required=True, help="One state in the --states grammar: 'jumping:6' or 'cheer:4:fixed'. Frames 2..8 — a one-frame row is refused HERE rather than several generations later at 'rows'")
    characters_add_state.add_argument("--json", action="store_true")
    characters_add_state.set_defaults(func=_cmd_characters_add_state)
    characters_sprite = characters_subs.add_parser("sprite", help="Return an installed character spritesheet payload")
    characters_sprite.add_argument("slug")
    characters_sprite.add_argument("--no-sheet", dest="no_sheet", action="store_true", help="Metadata only: drop `spritesheetBase64` (468.8 KiB of it on the live 3-state character, and the sheet bytes are not read at all) and carry `sheet`, the absolute path, in its place. `spritesheetRevision` and every geometry/taxonomy key are unchanged, so a consumer that wants framesByRow/states/rows and reads the file itself pays kilobytes instead of half a megabyte. The default is byte-identical to what it always was")
    characters_sprite.add_argument("--json", action="store_true")
    characters_sprite.set_defaults(func=_cmd_characters_sprite)
    characters_payload_contract = characters_subs.add_parser("payload-contract", help="Publish the KEY SET every `characters` READ payload can carry — the cross-repo contract the launcher commits and diffs, so the two sides disagree in a file instead of at runtime. Derived by RUNNING the verbs against a throwaway library in a temp directory (the real library is never touched), never from a hand-written list, so a key a producer grows or drops is in the dump the day it moves. Key PATHS only and never a value, so the dump is byte-stable. Conditional keys are marked with the modes that carry them — `spritesheetBase64` and `sheet` are one slot spelled two ways, which a flat key list cannot express")
    characters_payload_contract.add_argument("--json", action="store_true")
    characters_payload_contract.set_defaults(func=_cmd_characters_payload_contract)


def harness_command(args) -> int:
    print("Use `hermes harness --help`.")
    return 0


def _cmd_serve(args) -> int:
    # Lazy: serve is the process's main loop, owns the sys.stdout/sys.stderr
    # swaps, and every other verb would pay its import weight.
    from hermes_cli.harness_parts.serve.commands import _cmd_serve as _run_serve

    # The argv lane parses with THIS module's tree; the part may not import it.
    return _run_serve(args, harness_parser=build_parser)


def _cmd_serve_connect(args) -> int:
    from hermes_cli.harness_parts.serve.commands import _cmd_serve_connect as _run_connect

    return _run_connect(args)
