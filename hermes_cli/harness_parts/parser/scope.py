"""The scope families: ``workspace`` and ``realm`` (with realm sync and the realm skill/agent selections).

One ``add_<family>(subs)`` per ``hermes harness`` family, in the order the
contract fixture lists them; ``parser.PARSER_FAMILIES`` is the only reader.
"""

from __future__ import annotations

from .common_args import _add_stage42_global_args
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
    "add_realm",
    "add_workspace",
]


def add_workspace(subs) -> None:
    """``hermes harness workspace``."""
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


def add_realm(subs) -> None:
    """``hermes harness realm``."""
    realm = subs.add_parser("realm", help="Manage Harness realms")
    realm_subs = realm.add_subparsers(dest="realm_command", required=True)
    _add_realm_row_verbs(realm_subs)
    _add_realm_sync_verbs(realm_subs)
    _add_realm_selection_verbs(realm_subs)


def _add_realm_row_verbs(realm_subs) -> None:
    """``hermes harness realm list / show / create / adopt / bind-server / use / default-scope``."""
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


def _add_realm_sync_verbs(realm_subs) -> None:
    """``hermes harness realm sync``."""
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


def _add_realm_selection_verbs(realm_subs) -> None:
    """``hermes harness realm skills / agents``."""
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
