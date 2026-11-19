"""The persona families: ``persona``, ``mission-chat``, ``persona-instance``, ``query`` and ``agent``.

One ``add_<family>(subs)`` per ``hermes harness`` family, in the order the
contract fixture lists them; ``parser.PARSER_FAMILIES`` is the only reader.
"""

from __future__ import annotations

from agent_runtime.permission_modes import PERMISSION_MODES

from hermes_cli.harness_parts.chat_turn_argv import add_mission_chat_message_args, add_mission_chat_steer_args

from .common_args import _add_coordinator_permission_args, _add_stage42_global_args
from .lazy import lazy_module

agent_commands = lazy_module("hermes_cli.harness_parts.agent_commands")
chat_coordinator = lazy_module("hermes_cli.harness_parts.persona.chat_coordinator")
chat_delete = lazy_module("hermes_cli.harness_parts.persona.chat_delete")
chat_head_commands = lazy_module("hermes_cli.harness_parts.persona.chat_head_commands")
chat_open = lazy_module("hermes_cli.harness_parts.persona.chat_open")
chat_tickets_commands = lazy_module("hermes_cli.harness_parts.persona.chat_tickets_commands")
context_memory_commands = lazy_module("hermes_cli.harness_parts.persona.context_memory_commands")
chat_turn_message = lazy_module("hermes_cli.harness_parts.persona.chat_turn_message")
chat_serve_route = lazy_module("hermes_cli.harness_parts.persona.chat_serve_route")
inspect_commands = lazy_module("hermes_cli.harness_parts.persona.inspect_commands")
instance_commands = lazy_module("hermes_cli.harness_parts.persona.instance_commands")
lifecycle_commands = lazy_module("hermes_cli.harness_parts.persona.lifecycle_commands")
model_and_skills_commands = lazy_module("hermes_cli.harness_parts.persona.model_and_skills_commands")
query_commands = lazy_module("hermes_cli.harness_parts.query_commands")
runtime_commands = lazy_module("hermes_cli.harness_parts.runtime_commands")
slots_commands = lazy_module("hermes_cli.harness_parts.persona.slots_commands")

__layer__ = "wiring"
__all__ = [
    "add_agent",
    "add_mission_chat",
    "add_persona",
    "add_persona_instance",
    "add_query",
]


def add_persona(subs) -> None:
    """``hermes harness persona``."""
    persona = subs.add_parser("persona", help="Run bounded live-token diagnostics for one persona")
    persona_subs = persona.add_subparsers(dest="persona_command")
    _add_persona_read_verbs(persona_subs)
    _add_persona_chat_and_model_verbs(persona_subs)
    _add_persona_instance_verbs(persona_subs)
    _add_persona_slots_verbs(persona_subs)


def _add_persona_slots_verbs(persona_subs) -> None:
    """``hermes harness persona slots show / set`` — an instance's repo-slot assignment (build plan §3.4)."""
    slots = persona_subs.add_parser("slots", help="A persona instance's assigned repo slots and its primary slot")
    slots_subs = slots.add_subparsers(dest="persona_slots_command", required=True)
    show = slots_subs.add_parser("show", help="The assigned slots, where each is bound here, and the primary (read-only)")
    show.add_argument("persona_instance_id")
    _add_stage42_global_args(show)
    show.set_defaults(func=slots_commands._cmd_persona_slots_show)
    set_ = slots_subs.add_parser("set", help="Replace the assigned slots (a subset of the workspace's) and the primary")
    set_.add_argument("persona_instance_id")
    set_.add_argument("--slot", action="append", default=[], help="An assigned slot name (repeatable; none = no assignment)")
    set_.add_argument("--primary", default=None, help="The primary slot (must be one of --slot); unset = the first assigned")
    set_.add_argument("--issued-at", dest="issued_at", default=None, help="ISO-8601 issue time; an older write is refused")
    _add_stage42_global_args(set_)
    set_.set_defaults(func=slots_commands._cmd_persona_slots_set)


def _add_persona_read_verbs(persona_subs) -> None:
    """``hermes harness persona list / show / tool-diff / permission``."""
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
        choices=list(PERMISSION_MODES),
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


def _add_persona_chat_and_model_verbs(persona_subs) -> None:
    """``hermes harness persona chat / set-model / set-skills / set-context``."""
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
    persona_chat_tool_io = persona_chat_subs.add_parser(
        "tool-io", help="Read one tool call's full redacted input and result (the transcript keeps a head-cut copy)"
    )
    persona_chat_tool_io.add_argument("--session-id", dest="session_id", required=True)
    persona_chat_tool_io.add_argument("--tool-call-id", dest="tool_call_id", required=True, help="The tool element's tool_call_id")
    persona_chat_tool_io.add_argument("--offset", type=int, default=0, help="Window start; pass the previous answer's next_offset")
    persona_chat_tool_io.add_argument("--json", action="store_true")
    persona_chat_tool_io.set_defaults(func=runtime_commands._cmd_persona_chat_tool_io)
    chat_head = persona_subs.add_parser("chat-head", help="Where each agent's chats live (its own profile's state.db)")
    chat_head_subs = chat_head.add_subparsers(dest="persona_chat_head_command", required=True)
    migrate = chat_head_subs.add_parser(
        "migrate", help="Move each agent's chats out of the process head into its own profile; dry-run unless --apply"
    )
    migrate.add_argument("--instance", default=None, help="One persona instance id; omit for every live instance")
    migrate.add_argument("--apply", action="store_true", help="Copy, verify, flip the record, then delete from the process head")
    migrate.add_argument("--json", action="store_true")
    migrate.set_defaults(func=chat_head_commands._cmd_persona_chat_head_migrate)

    persona_set_model = persona_subs.add_parser("set-model", help="Persist a persona's default provider/model (profile-default lane; future instances inherit it)")
    persona_set_model.add_argument("persona_id", help="Persona id or profile_<name>")
    persona_set_model.add_argument("--provider", default=None, help="Provider lane (canonical name or alias; api_mode is derived from it)")
    persona_set_model.add_argument("--model", default=None, help="Model id for the provider lane")
    persona_set_model.add_argument("--use-default", action="store_true", help="Clear the persona's model/provider/api_mode so the runtime default cascade applies")
    persona_set_model.add_argument("--issued-at", default=None, help="ISO-8601 issue timestamp; stale writes are superseded instead of applied")
    persona_set_model.add_argument("--requested-by", default="operator")
    persona_set_model.add_argument("--json", action="store_true")
    persona_set_model.set_defaults(func=model_and_skills_commands._cmd_persona_set_model)
    persona_set_skills = persona_subs.add_parser("set-skills", help="Persist a persona's default skill set (profile-default lane; future instances inherit it)")
    persona_set_skills.add_argument("persona_id", help="Persona id or profile_<name>")
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
    persona_set_context = persona_subs.add_parser("set-context", help="Turn a persona's core context files and profile memory on or off (profile-default lane; the reply states each switch's cost)")
    persona_set_context.add_argument("persona_id", help="Persona id or profile_<name>")
    persona_set_context.add_argument("--core-context-files", dest="core_context_files", choices=("on", "off"), default=None, help="Load the project context files (AGENTS.md, CLAUDE.md, ...) into every turn: a fixed per-turn prompt cost")
    persona_set_context.add_argument("--profile-memory", dest="profile_memory", choices=("on", "off"), default=None, help="Load the bound profile's MEMORY.md / USER.md into every turn: the persona inherits that profile's memory")
    persona_set_context.add_argument("--json", action="store_true")
    persona_set_context.set_defaults(func=context_memory_commands._cmd_persona_set_context)


def _add_persona_instance_verbs(persona_subs) -> None:
    """``hermes harness persona instance``."""
    persona_instance = persona_subs.add_parser("instance", help="Create, open, steer, retire, and maintain persona instances (chat is the only messaging lane)")
    persona_instance_subs = persona_instance.add_subparsers(dest="persona_instance_command")
    _add_persona_instance_lifecycle_verbs(persona_instance_subs)
    _add_persona_instance_steering_verbs(persona_instance_subs)


def _add_persona_instance_lifecycle_verbs(persona_instance_subs) -> None:
    """``hermes harness persona instance create / open-chat / retire``."""
    persona_instance_create = persona_instance_subs.add_parser("create", help="Create an Agent Profile (operator chat channel) or an additional placement-backed instance (--add-instance); requires --display-name")
    persona_instance_create.add_argument("--persona", dest="persona_id", required=True)
    persona_instance_create.add_argument("--title", required=True, help="Fallback display name when --display-name is empty (launcher wire-compat)")
    persona_instance_create.add_argument("--requested-by", default="cli")
    _add_coordinator_permission_args(persona_instance_create)
    persona_instance_create.add_argument("--client-message-id", default=None)
    persona_instance_create.add_argument("--independent-agent", action="store_true", help="Give the new agent its own persona and backing profile")
    persona_instance_create.add_argument("--source-instance-id", default=None, help="Use an existing agent's model and skill choices as the starting point")
    persona_instance_create.add_argument("--display-name", default=None)
    persona_instance_create.add_argument("--session-id", default=None)
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
    persona_instance_open.add_argument("--add-instance", action="store_true", help="Open the chat on an additional placement-backed instance")
    persona_instance_open.add_argument("--placement-id", default=None, help="Scene itemId for an additional placement-backed instance; must end in the deliberate-placement shape <persona-token>_agent_<hex8>")
    persona_instance_open.add_argument("--workspace-id", "--workspace", dest="workspace_id", default=None, help="Mission Control workspace the placement belongs to (scope-provenance pointer; only meaningful with --add-instance)")
    persona_instance_open.add_argument("--realm-id", dest="realm_id", default=None, help="Mission Control realm the placement belongs to (scope-provenance pointer; only meaningful with --add-instance)")
    persona_instance_open.add_argument("--display-name", default=None, help="Authoritative name for a deliberately placed additional instance; ignored unless --add-instance")
    persona_instance_open.add_argument("--requested-by", default="cli")
    # Correlation-id plan P2: the gesture token, on the door the launcher's
    # add-instance placement still takes (its method lane pins the minting
    # keys closed). Rides ``persona_instance.chat_opened`` and its paired row;
    # absent → both byte-identical. Not on ``--new-session``: that branch is a
    # chat-root mint with no placement gesture behind it.
    persona_instance_open.add_argument("--correlation-id", dest="correlation_id", default=None)
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
    # `close` / `archive` (residual free-floating assignment settle) are retired with
    # the assignment store (RT-FULL-PERSONAASSIGNMENTSTORE, 2026-10-25).
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
    # S8b-b: the flag the (since-deleted) `agent retire` took, on this door onto
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


def _add_persona_instance_steering_verbs(persona_instance_subs) -> None:
    """``hermes harness persona instance steer / repair-steering / return-summary / update-profile / set-model``."""
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


def _add_mission_chat_audit(mission_chat_subs) -> None:
    """RT-TURN-AUDIT-ENTRY: ``mission-chat audit`` — what a persona's turns did, read from the turn journal."""
    audit = mission_chat_subs.add_parser(
        "audit", help="Audit a persona instance's or chat's turns: tool calls, files, worktrees, commits, model and tokens"
    )
    audit.add_argument("--persona-instance-id", default=None)
    audit.add_argument("--session-id", default=None, help="A chat's root or active session id")
    audit.add_argument("--turn-id", default=None)
    audit.add_argument("--limit", type=int, default=20, help="Turns, newest first (clamped 1..200)")
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=chat_tickets_commands._cmd_mission_chat_audit)


def add_mission_chat(subs) -> None:
    """``hermes harness mission-chat``."""
    mission_chat = subs.add_parser("mission-chat", help="Canonical Mission Control chat path")
    mission_chat_subs = mission_chat.add_subparsers(dest="mission_chat_command")
    _add_mission_chat_message(mission_chat_subs)
    mission_chat_queue_skill = mission_chat_subs.add_parser("queue-skill", help="Load a skill on the next Mission Control chat turn")
    mission_chat_queue_skill.add_argument("--persona", dest="persona_id", required=True)
    mission_chat_queue_skill.add_argument("--persona-instance-id", default=None)
    mission_chat_queue_skill.add_argument("--session-id", required=True)
    mission_chat_queue_skill.add_argument("--skill", action="append", default=[])
    mission_chat_queue_skill.add_argument("--skills", nargs="+", default=[])
    mission_chat_queue_skill.add_argument("--json", action="store_true")
    mission_chat_queue_skill.set_defaults(func=chat_coordinator._cmd_mission_chat_queue_skill)
    mission_chat_steer = mission_chat_subs.add_parser("steer", help="Steer an active streamed Mission Control chat turn")
    add_mission_chat_steer_args(mission_chat_steer)
    mission_chat_steer.set_defaults(func=chat_coordinator._cmd_mission_chat_steer)
    mission_chat_resolve = mission_chat_subs.add_parser(
        "turn-resolve", help="Resolve an uncertain turn or dismiss an interruption"
    )
    mission_chat_resolve.add_argument("--session-id", required=True)
    mission_chat_resolve.add_argument("--client-message-id", required=True)
    mission_chat_resolve.add_argument("--turn-id", required=True)
    mission_chat_resolve.add_argument("--persona-instance-id", default=None)
    from agent_runtime.mission_chat_turns.states import TurnResolution
    mission_chat_resolve.add_argument("--action", choices=list(TurnResolution), required=True)
    mission_chat_resolve.add_argument("--json", action="store_true")
    mission_chat_resolve.set_defaults(func=chat_tickets_commands._cmd_mission_chat_turn_resolve)
    _add_mission_chat_audit(mission_chat_subs)
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


def _add_mission_chat_message(mission_chat_subs) -> None:
    """``hermes harness mission-chat message`` — one Mission Control chat turn."""
    mission_chat_message = mission_chat_subs.add_parser("message", help="Send one Mission Control chat turn through the normal Hermes profile context")
    add_mission_chat_message_args(mission_chat_message)
    mission_chat_message.set_defaults(func=chat_serve_route.cmd_mission_chat_send)


def add_persona_instance(subs) -> None:
    """``hermes harness persona-instance``."""
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
    persona_instance_detail.set_defaults(func=inspect_commands._cmd_persona_instance_detail)


def add_query(subs) -> None:
    """``hermes harness query`` — the narrow read-only lookups (HQ1).

    The choices are the core's own question names, so the verb and the
    in-turn ``harness_query`` tool cannot drift into two vocabularies.
    """
    from agent_runtime.harness_query.core import QUESTIONS

    query = subs.add_parser(
        "query",
        help=(
            "READ-ONLY narrow lookups: roster, one instance (with its MCP resolution), an "
            "instance's chat sessions with hot/busy/cold state, and live QA sessions by id. "
            "Answered by the running serve when one is up; use this, not `snapshot`, for lookups"
        ),
    )
    query.add_argument("question", choices=QUESTIONS)
    query.add_argument("target", nargs="?", default=None, help="Persona-instance id or persona id (instance, sessions)")
    query.add_argument("--limit", type=int, default=None, help="Most sessions to return (default 10, max 50)")
    query.add_argument("--direct", action="store_true", help="Read in this process; do not ask the running serve")
    query.add_argument("--json", action="store_true")
    query.set_defaults(func=query_commands._cmd_query)


def add_agent(subs) -> None:
    """``hermes harness agent``."""
    agent = subs.add_parser("agent", help="Inspect and rebind harness agent definitions")
    agent_subs = agent.add_subparsers(dest="agent_command", required=True)
    agent_list = agent_subs.add_parser("list", help="List persisted/configured agent definitions")
    agent_list.add_argument("--all-profiles", action="store_true")
    _add_stage42_global_args(agent_list, controls=frozenset({"sort"}))
    agent_list.set_defaults(func=agent_commands._cmd_agent_list)

    # `agent create` / `agent retire` were deleted 2026-10-02 (owner ruling): the
    # launcher reaches both only as `runtime.agent.create` / `runtime.agent.retire`
    # and no operator or script uses the argv form. `persona instance retire`
    # stays the argv retire door onto the same `perform_agent_retire`.

    agent_set_profile = agent_subs.add_parser(
        "set-profile",
        help="Rebind an agent to a different Hermes profile (the ONE door; cascades every instance projection)",
    )
    agent_set_profile.add_argument("persona_id", help="Store-persisted agent id")
    agent_set_profile.add_argument("--profile", required=True, help="Target Hermes profile name; must exist and resolve ready")
    agent_set_profile.add_argument("--requested-by", default="operator")
    _add_stage42_global_args(agent_set_profile, controls=frozenset({"dry_run"}))
    agent_set_profile.set_defaults(func=agent_commands._cmd_agent_set_profile)
