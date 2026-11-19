"""The two chat-turn verbs' argv grammar, and the embedded serve's harness tree of those two verbs only.

A chat turn reaches its handler as argv (``runtime.chat.message`` / ``runtime.chat.steer`` →
``harness mission-chat message|steer`` → the serve's argv lane, ``serve.argv_lane.dispatch_argv``).
The argv lane parses with whatever tree was bound (``bind_harness_parser``): a desktop serve binds the
whole ``hermes harness`` tree from its ``serve`` trampoline. The embedded serve (the phone entry,
``serve.in_memory.EmbeddedServe``) has no trampoline, and the whole tree is not a phone's: building it
imports every verb family's wiring and names every handler module, which the phone bundle's closure
would then have to ship (RT-PHONE-TURN-NEEDS-THE-HARNESS-PARSER). So the embedded serve binds
:func:`build_turn_parser`: ``harness mission-chat message`` and ``steer``, with the SAME arguments the
full tree gives them — both trees take them from :func:`add_mission_chat_message_args` and
:func:`add_mission_chat_steer_args` (``parser/persona.py`` is the full tree's caller), so one grammar
cannot drift into two.

Handlers: the serve-side ones. In a serve request the full tree's ``message`` func
(``persona.chat_serve_route.cmd_mission_chat_send``) runs ``chat_turn_message._cmd_mission_chat_message``
itself (a serve request id is bound), so the embedded tree binds that directly; ``steer`` binds the
full tree's own ``chat_coordinator._cmd_mission_chat_steer``. Any other root or verb is refused by the
parser, as a desktop serve refuses an unknown verb (``argv_parse_failed``).

Lanes, not wiring: the argv lane's embedded entry (lanes) builds from it, and it imports nothing above
``argparse`` at module level.
"""

from __future__ import annotations

import argparse
from typing import Any

__layer__ = "lanes"

__all__ = ["add_mission_chat_message_args", "add_mission_chat_steer_args", "build_turn_parser"]


def add_mission_chat_message_args(parser: argparse.ArgumentParser) -> None:
    """Every argument of ``hermes harness mission-chat message`` — one Mission Control chat turn."""
    parser.add_argument("--persona", dest="persona_id", required=True)
    parser.add_argument("--persona-instance-id", default=None)
    parser.add_argument("--session-id", default=None)
    # The owning account's client-scope digest (RT-CHAT-MESSAGE-MINT-UNSCOPED): a send that names
    # no session and MINTS one stamps it on the new root, so the chat lists under that account
    # (the Launcher's chat list filters on it). Lowered from `runtime.chat.message`'s
    # `client_scope`, which the door has already validated.
    parser.add_argument("--client-scope", dest="client_scope", default=None, help="The owning account's client-scope digest (64 hex) a chat this send MINTS is stamped with; ignored when continuing an existing thread")
    # store_true (absent → False) is deliberate on THIS lane: False is now an
    # explicit "continue the target's current default thread", so the operator
    # console and any bare CLI send keep threading exactly as before (that
    # pointer follows the most recently established thread — it is not a
    # separate durable pair thread), while a caller that omits
    # the flag entirely (the agent_chat_send dispatch lane, which forwards
    # None) falls through to agent_runtime.mission_chat.dispatch_session_policy.
    parser.add_argument("--new-session", dest="new_session", action="store_true", help="Force a fresh canonical chat session for the target instead of continuing the default thread (agent_chat_send new_session lane); ignored when --session-id is given")
    # The echo half of the clarify binding. A reply that carries the token the
    # question shipped down lands in the question's OWN thread — outranking both
    # the policy default and a stale --session-id (reported, never silent, in the
    # turn's clarify_binding block). Unknown/pruned tokens degrade to normal
    # precedence rather than refusing.
    parser.add_argument("--clarify-token", dest="clarify_token", default=None, help="Answer a clarify question by its token (clarify_request.clarify_token from the asking turn); binds this reply to the thread the question was asked in")
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
    parser.add_argument("--title", default=None, help="Title for a chat session this send MINTS (a fresh --new-session thread, or a dispatch under the new_per_dispatch policy); ignored when continuing an existing thread")
    parser.add_argument("--message", required=True)
    parser.add_argument("--provider", default=None, help="Provider override for this persona chat session only")
    parser.add_argument("--model", default=None, help="Model override for this persona chat session only")
    parser.add_argument("--use-agent-default", action="store_true", help="Clear the chat-scoped provider/model override before sending")
    parser.add_argument("--surface-prompt", default="")
    parser.add_argument("--agents-file", default=None, help="Absolute path to one operator-selected workspace AGENTS.md to inject for this turn")
    parser.add_argument("--intent-hint", default="chat")
    parser.add_argument("--requested-by", default="cli")
    parser.add_argument("--client-message-id", default=None)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--input-mode", dest="input_mode", choices=("typed", "voice"), default=None, help="How the operator made this message (typed | voice; absent = typed); recorded on the turn and carried on its history row")
    parser.add_argument("--retry-of", dest="retry_of", default=None, help="client_message_id of the interrupted or budget-exhausted turn of this chat that this send re-runs, or, with --turn-model, of the chat's latest delivered turn this send redoes (recorded as the turn's lineage; any other target is refused chat_turn_retry_target_invalid)")
    parser.add_argument("--turn-provider", dest="turn_provider", default=None, help="Provider for THIS turn only; never written to the chat, the agent or the profile")
    parser.add_argument("--turn-model", dest="turn_model", default=None, help="Model for THIS turn only (a redo of the latest reply with --retry-of); never written to the chat, the agent or the profile")
    parser.add_argument("--image", dest="images", action="append", default=None, help="A pasted image stored by runtime.chat.message, by reference (sha256:<hex>.png|.jpg); repeatable, at most 4; sent to a vision-capable model as an image part, refused vision_unsupported otherwise")
    parser.add_argument("--file", dest="files", action="append", default=None, help="A reviewed file stored by runtime.chat.message, by reference (sha256:<hex>.<ext>); repeatable, at most 8 (limits.files); staged for the agent as a FILE:<path> line it reads with read_file, never inlined")
    parser.add_argument("--skill", dest="skills", action="append", default=None, help="Preload a skill for this message only; repeatable, carried with this turn's durable request")
    parser.add_argument("--stream", action="store_true", help="Emit operator-chat deltas and the final payload as NDJSON")
    # Default is resolved at RUN time (agent_runtime.mission_chat.default_max_seconds
    # in the ROOT config.yaml, itself defaulting to 240s) rather than pinned in the
    # parser: an argparse default cannot be told apart from an explicit flag, and
    # "explicit --max-seconds always wins over the configured default" has to be
    # decidable. `None` here IS "the caller expressed no opinion" — no wall clock
    # at all on an attended turn (config.resolve_mission_chat_turn_seconds).
    parser.add_argument("--max-seconds", type=float, default=None, help="Wall budget for this turn (default: none on a turn a person sent — it runs until it ends or is stopped; agent_runtime.mission_chat.default_max_seconds, or 240s when unset, on a machine-origin turn). The agent is told how much remains, and the last max(60s, 15%%) is reserved for a final checkpoint reply; the turn then settles as budget_exhausted (terminal, no turn-resolve)")
    parser.add_argument("--compression-threshold-tokens", type=int, default=None, help="One-turn native-compression proof seam; overrides the compressor token threshold without changing profile config")
    parser.add_argument("--compression-protect-first-n", type=int, default=None, help="One-turn native-compression proof seam; override protected head messages")
    parser.add_argument("--compression-protect-last-n", type=int, default=None, help="One-turn native-compression proof seam; override protected tail messages")
    # QA-only seams (agent_runtime.qa_turn_overrides): refused outside a QA namespace under a QA provider pool.
    parser.add_argument("--qa-checkpoint-after-seconds", type=float, default=None, help="QA only (a stagec-* namespace under HERMES_QA_PROVIDER_POOL; refused elsewhere): open this turn's wall-budget checkpoint this many seconds in (1-600)")
    parser.add_argument("--qa-max-iterations", type=int, default=None, help="QA only (refused outside a QA provider pool): this turn's tool-iteration limit (1-90; default 90)")
    parser.add_argument("--qa-silence-seconds", type=float, default=None, help="QA only (refused outside a QA provider pool): wait this many seconds before the first provider call, a model silence the turn heartbeat beats through (0-300)")
    parser.add_argument("--relay-chain", default=None, help="Comma-separated canonical persona ids already on the agent-relay chain (envelope provenance for chained agent_chat_send hops)")
    parser.add_argument("--relay-deadline-epoch", type=float, default=None, help="Absolute unix-epoch deadline shared by every hop on the relay chain")
    # Sender provenance, not guard logic: the sender's chat-root session id
    # scopes bare-persona target resolution to the SENDER's workspace. The
    # in-process relay always carried it on the args object; a DETACHED dispatch
    # runs its target turn in a CHILD PROCESS, so without an argv spelling the
    # child would silently resolve bare personas against the wrong scope.
    parser.add_argument("--requested-by-session", dest="requested_by_session", default=None, help="Chat-root session id of the sender (envelope provenance; scopes bare-persona target resolution to the sender's workspace)")
    # The tri-state ``new_session`` has no argparse spelling: absent is False
    # ("continue the target's current default thread"), present is True, and
    # there is no way to say UNSET ("no opinion — let
    # agent_runtime.mission_chat.dispatch_session_policy decide"), which is
    # exactly what the dispatch lane forwards in-process. Changing
    # ``--new-session``'s default to None would express it, but would also
    # silently start minting a fresh thread for every bare CLI send that omits
    # the flag. This states the unset case explicitly instead, so the child
    # process reproduces the in-process lane's threading exactly.
    parser.add_argument("--defer-thread-policy", dest="defer_thread_policy", action="store_true", help="State NO opinion about the thread: let agent_runtime.mission_chat.dispatch_session_policy decide (the tri-state 'unset' the in-process dispatch lane forwards). Overrides --new-session")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--in-process", dest="in_process", action="store_true", help="Run the turn in THIS process with this shell's home and credentials instead of handing it to the live serve (the default whenever a serve is live for the runtime root)")

def add_mission_chat_steer_args(parser: argparse.ArgumentParser) -> None:
    """Every argument of ``hermes harness mission-chat steer`` — steer an active streamed chat turn."""
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--client-message-id", required=True)
    parser.add_argument("--persona", dest="persona_id", default=None)
    parser.add_argument("--persona-instance-id", default=None)
    parser.add_argument("--json", action="store_true")


def _mission_chat_message(args: Any) -> int:
    from hermes_cli.harness_parts.persona.chat_turn_message import _cmd_mission_chat_message

    return _cmd_mission_chat_message(args)


def _mission_chat_steer(args: Any) -> int:
    from hermes_cli.harness_parts.persona.chat_coordinator import _cmd_mission_chat_steer

    return _cmd_mission_chat_steer(args)


def build_turn_parser(parent_subparsers: Any) -> None:
    """Add ``harness mission-chat {message, steer}`` to *parent_subparsers* (the argv lane's builder shape)."""

    harness = parent_subparsers.add_parser("harness", help="Experimental Agent Runtime Harness")
    families = harness.add_subparsers(dest="harness_command")
    mission_chat = families.add_parser("mission-chat", help="Canonical Mission Control chat path")
    verbs = mission_chat.add_subparsers(dest="mission_chat_command")
    message = verbs.add_parser("message", help="Send one Mission Control chat turn through the normal Hermes profile context")
    add_mission_chat_message_args(message)
    message.set_defaults(func=_mission_chat_message)
    steer = verbs.add_parser("steer", help="Steer an active streamed Mission Control chat turn")
    add_mission_chat_steer_args(steer)
    steer.set_defaults(func=_mission_chat_steer)
