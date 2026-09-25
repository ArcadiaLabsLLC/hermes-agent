"""The persona families: ``persona``, ``mission-chat``, ``persona-instance`` and ``agent``.

One ``add_<family>(subs)`` per ``hermes harness`` family, in the order the
contract fixture lists them; ``parser.PARSER_FAMILIES`` is the only reader.
"""

from __future__ import annotations

from .common_args import _add_coordinator_permission_args, _add_stage42_global_args
from hermes_cli.harness_parts import runtime_commands
from hermes_cli.harness_parts.agent_commands import _cmd_agent_list, _cmd_agent_set_profile
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
from hermes_cli.harness_parts.persona.inspect_commands import _cmd_persona_instance_detail

__layer__ = "wiring"
__all__ = [
    "add_agent",
    "add_mission_chat",
    "add_persona",
    "add_persona_instance",
]


def add_persona(subs) -> None:
    """``hermes harness persona``."""
    persona = subs.add_parser("persona", help="Run bounded live-token diagnostics for one persona")
    persona_subs = persona.add_subparsers(dest="persona_command")
    _add_persona_read_verbs(persona_subs)
    _add_persona_chat_and_model_verbs(persona_subs)
    _add_persona_instance_verbs(persona_subs)


def _add_persona_read_verbs(persona_subs) -> None:
    """``hermes harness persona list / show / tool-diff / permission / assignments / migrate-assignment-task-ids``."""
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


def _add_persona_chat_and_model_verbs(persona_subs) -> None:
    """``hermes harness persona chat / set-model / set-skills``."""
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


def _add_persona_instance_verbs(persona_subs) -> None:
    """``hermes harness persona instance``."""
    persona_instance = persona_subs.add_parser("instance", help="Create, open, steer, retire, and maintain persona instances (chat is the only messaging lane)")
    persona_instance_subs = persona_instance.add_subparsers(dest="persona_instance_command")
    _add_persona_instance_lifecycle_verbs(persona_instance_subs)
    _add_persona_instance_steering_verbs(persona_instance_subs)


def _add_persona_instance_lifecycle_verbs(persona_instance_subs) -> None:
    """``hermes harness persona instance create / open-chat / close / archive / retire``."""
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


def add_mission_chat(subs) -> None:
    """``hermes harness mission-chat``."""
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
    persona_instance_detail.set_defaults(func=_cmd_persona_instance_detail)


def add_agent(subs) -> None:
    """``hermes harness agent``."""
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
