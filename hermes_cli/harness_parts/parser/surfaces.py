"""The Mission Control surface families: flow, checkpoint, skills, prompt-context, board, office, level, map.

One ``add_<family>(subs)`` per ``hermes harness`` family, in the order the
contract fixture lists them; ``parser.PARSER_FAMILIES`` is the only reader.
"""

from __future__ import annotations

from .common_args import _add_stage42_global_args
from hermes_cli.harness_parts import (
    board as board_commands,
    checkpoint_commands,
    flow_commands,
    level as level_commands,
    map as map_commands,
    office as office_commands,
)
from hermes_cli.harness_parts.prompt_context_commands import _cmd_prompt_context_show
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

__layer__ = "wiring"
__all__ = [
    "add_board",
    "add_checkpoint",
    "add_flow",
    "add_level",
    "add_map",
    "add_office",
    "add_prompt_context",
    "add_skills",
]


def add_flow(subs) -> None:
    """``hermes harness flow``."""
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


def add_checkpoint(subs) -> None:
    """``hermes harness checkpoint``."""
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


def add_skills(subs) -> None:
    """``hermes harness skills``."""
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


def add_prompt_context(subs) -> None:
    """``hermes harness prompt-context``."""
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


def add_board(subs) -> None:
    """``hermes harness board``."""
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


def add_office(subs) -> None:
    """``hermes harness office``."""
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


def add_level(subs) -> None:
    """``hermes harness level``."""
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


def add_map(subs) -> None:
    """``hermes harness map``."""
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
