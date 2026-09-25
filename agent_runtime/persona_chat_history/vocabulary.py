"""The persona-chat projection's vocabulary: message kinds, terminal and silent turn markers, read statuses, limits.

Separate because every other module in the package — and ``operator_channels``,
``snapshot`` and ``chat_live_log`` outside it — reads these names, and a
vocabulary imports nothing that reads it. Layer ``policy``, not ``models``: the
two client-message-id functions here call the assignment token policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from ..mission_chat_turns.states import TERMINAL_TURN_STATES
from ..serde import safe_assignment_text, safe_assignment_token
from ..redaction import TEXT_SECRET_ASSIGNMENT_RE
from ..turn_visibility import SILENT_REASONS, VisibilityReason

__layer__ = "policy"
__all__ = [
    "PERSONA_PRE_TRACE_ACK_FINISH_REASON",
    "PERSONA_PRE_TRACE_ACK_KIND",
    "PERSONA_RELAYED_MESSAGE_KIND",
    "PERSONA_HARNESS_DELIVERY_KIND",
    "PERSONA_TURN_INTERRUPTED_KIND",
    "PERSONA_TURN_BUDGET_EXHAUSTED_KIND",
    "TerminalTurnMarker",
    "TERMINAL_TURN_MARKERS",
    "PERSONA_TURN_SILENT_KIND",
    "SILENT_TURN_MARKER_TEXTS",
    "ChatReadStatus",
    "MessageRole",
    "WIRE_ROLES",
    "CHAT_READ_UNAVAILABLE",
    "CHAT_READ_FAILED",
    "CHAT_SCOPE_UNRESOLVED",
    "CHAT_SCOPE_MISMATCH",
    "CHAT_REDACTION_UNKNOWN",
    "DEFAULT_PERSONA_CHAT_MESSAGE_TAIL",
    "MAX_PERSONA_CHAT_MESSAGE_TAIL",
    "PERSONA_CHAT_MESSAGE_TEXT_LIMIT",
    "_CHAT_MODEL_OVERRIDE_CONFIG_KEY",
    "_TRACE_EVENT_TYPES",
    "_TRACE_FETCH_HEADROOM",
    "_TRACE_FETCH_CEILING",
    "_SECRET_RE",
    "logical_persona_chat_client_message_id",
    "canonical_persona_chat_turn_id",
]


# Structural marker for the canned "I'll … then report back with …" pre-trace
# acknowledgment the persona-chat turn writes ahead of the real LLM reply. The
# ack text is tool-specific (several variants) and changes over time, so we stamp
# a machine flag at persist time (``finish_reason``) and re-emit it as a typed
# message ``kind`` through every projection. Consumers (operator conversation,
# the Launcher) key on the kind instead of matching the prose.
PERSONA_PRE_TRACE_ACK_FINISH_REASON = "pre_trace_ack"


PERSONA_PRE_TRACE_ACK_KIND = "pre_trace_ack"


# Typed kind for an incoming role="user" row that a relay tagged with the
# sending agent's identity (finish_reason=relay_from:<persona>:<instance>). The
# conversation projection keys on this to attribute the message to the sending
# AGENT instead of the operator. See agent_runtime/relay_policy.py.
PERSONA_RELAYED_MESSAGE_KIND = "relayed_message"


# Typed kind for the role="user" row a dispatch DELIVERY turn is forged under
# (finish_reason=harness_delivery:<dispatch_id>:<0|1>). Same column, same
# precedent, different origin: nobody sent this message — the harness brought
# back the answer to work the agent dispatched. Without the kind it renders as
# something the operator typed, which is the one thing it is not.
PERSONA_HARNESS_DELIVERY_KIND = "harness_delivery"


# ── terminal-turn marker vocabulary (ONE table, keyed on the turn state) ─────
#
# A turn that settles TERMINALLY without a recorded reply synthesizes a typed
# system marker row. The marker is what tells every downstream projection the
# turn is over — most concretely, it is the input
# ``operator_channels._settle_terminal_tool_calls`` reads to stop a
# ``tool_started``-without-``tool_finished`` row rendering a live spinner
# forever.
#
# The table exists because the filter used to be ``state != "interrupted"``: one
# hardcoded legacy state. When the wall-budget work (2026-07-26) added the
# ``budget_exhausted`` terminal state, that single-state filter silently
# excluded it — no marker, no settlement, and the launcher cockpit spun a tool
# row for a turn that had been over for minutes. Adding a terminal state must
# extend a TABLE, not require finding every string comparison.
#
# ``kind`` values are the wire vocabulary the Launcher already consumes
# (``mission_agent_chat_adapter.dart``: ``turn_interrupted`` →
# retry affordance, ``budget_exhausted`` → graceful-checkpoint marker). Do not
# mint a new kind for a state the Launcher already renders.
PERSONA_TURN_INTERRUPTED_KIND = "turn_interrupted"


PERSONA_TURN_BUDGET_EXHAUSTED_KIND = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class TerminalTurnMarker:
    """How one terminal turn state presents when it recorded no reply."""

    kind: str
    id_slug: str
    text: str


TERMINAL_TURN_MARKERS: dict[str, TerminalTurnMarker] = {
    "interrupted": TerminalTurnMarker(
        kind=PERSONA_TURN_INTERRUPTED_KIND,
        id_slug="turn-interrupted",
        text=(
            "Agent turn interrupted before a reply was recorded. Retry the message "
            "to run a fresh turn."
        ),
    ),
    "budget_exhausted": TerminalTurnMarker(
        kind=PERSONA_TURN_BUDGET_EXHAUSTED_KIND,
        id_slug="turn-budget-exhausted",
        text=(
            "Agent turn reached its wall budget and settled at a graceful checkpoint "
            "before a reply was recorded. Any work it committed stands; send a new "
            "message to continue from there."
        ),
    ),
}


# Guard, not decoration: a marker may only be declared for a state the turn
# store itself calls terminal. A typo, or a state that is still in flight, would
# otherwise mark a LIVE turn as over — the opposite failure of the one this
# table fixes, and a worse one. Raised (not asserted) so ``python -O`` cannot
# strip the contract. The turn store's own vocabulary guards
# (``mission_chat_turns._guard_turn_state_vocabulary``) already prove
# ``TERMINAL_TURN_STATES`` partitions the known universe with the in-flight and
# settling buckets, so this check is the last link of one chain, not a second
# opinion about which states are terminal.
_UNKNOWN_MARKER_STATES = sorted(set(TERMINAL_TURN_MARKERS) - TERMINAL_TURN_STATES)
if _UNKNOWN_MARKER_STATES:  # pragma: no cover - import-time contract guard
    raise RuntimeError(
        "TERMINAL_TURN_MARKERS declares non-terminal turn state(s): "
        f"{_UNKNOWN_MARKER_STATES}"
    )


# ── the turn that ended without saying anything ─────────────────────────────
#
# A turn can settle in a state nothing above calls terminal — it ran, it
# finished, the store calls it completed — and still produce no printable text.
# Its assistant row IS persisted (empty ``content``, a ``finish_reason`` that
# explains why), and ``_curate_chat_message_text`` then drops it, because an
# empty assistant row is overwhelmingly an intermediate tool-call round: across
# the operator's live profiles, 22,179 of them are scaffolding and 5 are this.
# The result was a turn that renders as nothing at all — no reply, no marker,
# no gap — and reopening the conversation showed the same nothing. A forged
# dispatch DELIVERY turn that ends this way was never rendered at all, so the
# operator's completion notice appeared to have been answered.
#
# The verdict comes from ``turn_visibility.classify_persisted_turn_row``, which
# is the one authority that separates scaffolding from silence; this table only
# decides what the marker SAYS. Wording lives here rather than being re-derived
# downstream for the same reason ``TERMINAL_TURN_MARKERS`` above owns its own
# prose: a projected row is text the projection is responsible for.
PERSONA_TURN_SILENT_KIND = "turn_silent"


_SILENT_TURN_RETRY_HINT = (
    "Nothing was lost in transit — the turn ran and produced no content, so "
    "sending again runs a fresh turn."
)


SILENT_TURN_MARKER_TEXTS: dict[VisibilityReason, str] = {
    VisibilityReason.TRUNCATED: (
        "Agent turn ended without a reply — the model was cut off before it "
        f"produced any content. {_SILENT_TURN_RETRY_HINT}"
    ),
    VisibilityReason.FILTERED: (
        "Agent turn ended without a reply — the provider blocked the content. "
        "Nothing was lost in transit; only a rephrased message can change the "
        "outcome, since sending the same one again reruns the same turn."
    ),
    VisibilityReason.FAILED: (
        "Agent turn ended without a reply — the turn ended in an error. "
        f"{_SILENT_TURN_RETRY_HINT}"
    ),
    VisibilityReason.EMPTY: (
        "Agent turn ended without a reply — the model produced no content and "
        f"nothing recorded why. {_SILENT_TURN_RETRY_HINT}"
    ),
}


# Same guard shape, and same argument, as _UNKNOWN_MARKER_STATES above: a silent
# reason with no text would project a marker row with an empty body, which the
# transcript reader drops — silently restoring the exact defect this table
# exists to fix. Proven against the authority's own vocabulary, never a second
# hand-written list.
_UNTEXTED_SILENT_REASONS = sorted(
    reason.value for reason in SILENT_REASONS - set(SILENT_TURN_MARKER_TEXTS)
)
if _UNTEXTED_SILENT_REASONS:  # pragma: no cover - import-time contract guard
    raise RuntimeError(
        "SILENT_TURN_MARKER_TEXTS is missing silent visibility reason(s): "
        f"{_UNTEXTED_SILENT_REASONS}"
    )


_CHAT_INSTANCE_MODES = {"chat", "free_floating"}


# ── "we did not read the transcript" is its own answer ──────────────────────
#
# A failed SessionDB read used to return ``[], "safe"`` — byte-identical to a
# genuinely empty conversation, right down to a ``redaction_status`` asserting
# the content had been verified when none of it was ever loaded. An operator
# reads that as "my messages are gone"; an agent hunting a missing turn is told
# authoritatively there are none.
#
# The vocabulary is the one ``persona_assignments.py`` already uses for exactly
# this condition (``None, "session_db_unavailable"``), and the shape follows the
# orphan sweep in ``cron/executions.py``: a typed unknown, never a plausible
# default.
class ChatReadStatus(StrEnum):
    """Why a chat read answered with no transcript — the closed ``error_kind``
    vocabulary of a read that did not happen (program rule 14). The values are
    the launcher contract and never change spelling."""

    UNAVAILABLE = "session_db_unavailable"  # no SessionDB to read from
    FAILED = "session_db_read_failed"  # the read itself raised
    SCOPE_UNRESOLVED = "chat_scope_unresolved"  # ambient rung on a chat read
    SCOPE_MISMATCH = "chat_scope_mismatch"  # two authorities disagree
    INVALID_CURSOR = "invalid_history_cursor"  # a ``before`` cursor that does not resolve


CHAT_READ_UNAVAILABLE = ChatReadStatus.UNAVAILABLE  # no SessionDB to read from
CHAT_READ_FAILED = ChatReadStatus.FAILED  # the read itself raised


# ── typed chat-scope refusals (2026-08-12 ambient chat-history incident) ─────
#
# Reaching the AMBIENT rung on a CHAT READ means "no authority told this
# process where the operator's transcripts live". Answering anyway reads
# whichever ``state.db`` ambient resolution happens to produce and returns a
# well-formed EMPTY page — ``ok: true, count: 0`` — indistinguishable from a
# genuinely empty conversation. That silent-empty class cost a full operator
# day on 2026-08-12; the read now refuses with a typed reason instead, and the
# refusal carries the resolved ``chat_scope`` block so the caller learns WHY.
CHAT_SCOPE_UNRESOLVED = ChatReadStatus.SCOPE_UNRESOLVED  # ambient rung on a chat read
CHAT_SCOPE_MISMATCH = ChatReadStatus.SCOPE_MISMATCH  # two authorities disagree


# The ``redaction_status`` an unread body reports. Not a redaction verdict —
# the absence of one. "safe" here is a claim about content nobody loaded.
CHAT_REDACTION_UNKNOWN = "unknown"


# ── the transcript's roles ───────────────────────────────────────────────────
#
# SessionDB rows carry the WIRE role (``user`` / ``assistant`` / ``system``, and
# the fork's own ``operator`` / ``agent`` spellings); the transcript speaks in
# three roles. ``WIRE_ROLES`` is the one lookup between them, and a wire role it
# does not name (``tool``, ``function``, empty) has no transcript role at all.


class MessageRole(StrEnum):
    """A transcript row's role; each member IS its string (``"operator"`` …)."""

    OPERATOR = "operator"
    AGENT = "agent"
    SYSTEM = "system"

    @classmethod
    def from_wire(cls, value: Any) -> "MessageRole | None":
        return WIRE_ROLES.get(safe_assignment_token(value))


WIRE_ROLES: Mapping[str, MessageRole] = MappingProxyType({
    "user": MessageRole.OPERATOR,
    "operator": MessageRole.OPERATOR,
    "assistant": MessageRole.AGENT,
    "agent": MessageRole.AGENT,
    "system": MessageRole.SYSTEM,
})

DEFAULT_PERSONA_CHAT_MESSAGE_TAIL = 40


MAX_PERSONA_CHAT_MESSAGE_TAIL = 40


PERSONA_CHAT_MESSAGE_TEXT_LIMIT = 20000


_CHAT_MODEL_OVERRIDE_CONFIG_KEY = "mission_control_chat_model_override"


_TRACE_EVENT_TYPES = {
    "run.tool.started",
    "run.tool.finished",
    "run.progress",
    "task.transition",
    "persona_assignment.created",
    "persona_assignment.closed",
}


# Per-task trace fetch sizing: headroom over tail*agents to survive dilution by
# non-trace event rows, and a hard ceiling on the reverse log scan.
_TRACE_FETCH_HEADROOM = 6


_TRACE_FETCH_CEILING = 2000


# Single-homed in ``agent_runtime.redaction`` — see the header there for the
# JSON blind spot every local spelling shared. Detection here (a matching line
# is dropped/blocked whole), so the shared pattern's group(2) is inert.
# ``snapshot`` imports this name; it stays a module attribute on purpose.
_SECRET_RE = TEXT_SECRET_ASSIGNMENT_RE


_ASSISTANT_CLIENT_MESSAGE_ID_RE = re.compile(r"^(.+):assistant:\d+$")


def logical_persona_chat_client_message_id(value: Any) -> str | None:
    """Return the durable operator-turn identity for a persisted chat row."""

    client_message_id = safe_assignment_text(value, limit=240)
    if not client_message_id:
        return None
    match = _ASSISTANT_CLIENT_MESSAGE_ID_RE.fullmatch(client_message_id)
    return match.group(1) if match else client_message_id


def canonical_persona_chat_turn_id(value: Any) -> str | None:
    """Return the tokenized turn id shared by operator and assistant rows."""

    logical_id = logical_persona_chat_client_message_id(value)
    return safe_assignment_token(logical_id) or None
