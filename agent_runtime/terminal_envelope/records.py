"""The typed records and their vocabulary.

``TerminalEnvelopeScope`` and the ContextVar ferry that carries it to the tool
(+ ``scope_for_persona``); the outcome / failure / grant-source / grant-issue
tokens; ``TerminalEnvelopeGrantIssue``, ``TerminalEnvelopeGrants``,
``TerminalEnvelopeDecision``; the grant table's role aliases and config-key
spelling; the two receipt-log filenames.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from agent_runtime.permission_modes import permission_mode_is_unbounded
from agent_runtime.personas import canonical_persona_id

from agent_runtime.terminal_envelope.classes import GOVERNED_LANES, LANE_MISSION_CHAT

__layer__ = "models"



# ── the per-run scope (what lane/role is this command running under) ────────


@dataclass(frozen=True, slots=True)
class TerminalEnvelopeScope:
    """Lane + role identity for the run whose tools are executing.

    Bound by ``profile_runner._execute_agent_run`` for the duration of a run,
    the same ContextVar ferry ``persona_chat_continuity.tool_execution_scope``
    already uses to reach the terminal tool (proving the value survives to the
    tool call). Unbound on every lane that does not construct one, which is how
    "no other lane changes" is enforced structurally rather than by convention.
    """

    lane: str
    role: str
    persona_id: str = ""
    session_id: str = ""
    runtime_root: str = ""
    #: The chat permission mode this run resolved (``tool_permissions.
    #: permission_options_for_chat``). Stamped by ``persona_runtime`` from the
    #: SAME resolve the turn already performs, so the schema plane and the
    #: execution plane cannot disagree about which mode the turn is running
    #: under. Empty on any caller that does not model a permission mode, which
    #: reads exactly as the pre-2026-08-09 behaviour (grants table only).
    permission_mode: str = ""

    @property
    def governed(self) -> bool:
        return self.lane in GOVERNED_LANES

    @property
    def unbounded(self) -> bool:
        return permission_mode_is_unbounded(self.permission_mode)


_ENVELOPE_SCOPE: ContextVar[TerminalEnvelopeScope | None] = ContextVar(
    "hermes_terminal_envelope_scope", default=None
)


@contextmanager
def terminal_envelope_scope(scope: TerminalEnvelopeScope | None) -> Iterator[None]:
    token = _ENVELOPE_SCOPE.set(scope)
    try:
        yield
    finally:
        _ENVELOPE_SCOPE.reset(token)


def current_terminal_envelope_scope() -> TerminalEnvelopeScope | None:
    return _ENVELOPE_SCOPE.get()


# ── typed outcomes ──────────────────────────────────────────────────────────

OUTCOME_ALLOW = "allow"
OUTCOME_GRANTED = "granted"
OUTCOME_REFUSE = "refuse"

#: The gated class has no grant for this role+lane. THE headline failure class.
ENVELOPE_COMMAND_REQUIRES_GRANT = "envelope_command_requires_grant"
#: Reserved for any future gated class kept outside
#: :data:`GRANTABLE_COMMAND_CLASSES`. Ruling R-2 leaves no current hard floors.
ENVELOPE_COMMAND_NOT_GRANTABLE = "envelope_command_not_grantable"
#: Why a granted command was allowed to run. Recorded on the receipt so an
#: operator reading ``terminal_envelope_decisions.jsonl`` can tell an explicit
#: per-role config grant from the standing permission-mode posture.
GRANT_SOURCE_CONFIG = "config_grant"
#: The run's permission mode granted it (``unbounded``). This is the detective
#: half of the 2026-08-09 ruling: the class is no longer refused by default, so
#: the receipt naming the MODE is the only record of why it ran.
GRANT_SOURCE_PERMISSION_MODE = "permission_mode"

#: ``grants`` config issue codes (never widen; always reported).
GRANT_UNKNOWN_COMMAND_CLASS = "envelope_grant_unknown_command_class"
GRANT_CLASS_NOT_GRANTABLE = "envelope_grant_class_not_grantable"
GRANT_MALFORMED = "envelope_grant_malformed"


@dataclass(frozen=True, slots=True)
class TerminalEnvelopeGrantIssue:
    """A typed config error in the grant table. Never a silent grant."""

    code: str
    subject: str
    summary: str
    fix_hint: str = ""

    def row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "subject": self.subject,
            "summary": self.summary,
            "fix_hint": self.fix_hint,
        }


@dataclass(frozen=True, slots=True)
class TerminalEnvelopeGrants:
    """The resolved ``grants.<role>.<lane>`` answer, plus any config faults."""

    role: str
    lane: str
    classes: frozenset[str] = frozenset()
    issues: tuple[TerminalEnvelopeGrantIssue, ...] = ()

    @property
    def config_key(self) -> str:
        return grant_config_key(role=self.role, lane=self.lane)

    def issue_rows(self) -> list[dict[str, Any]]:
        return [issue.row() for issue in self.issues]


@dataclass(frozen=True, slots=True)
class TerminalEnvelopeDecision:
    """The one answer for one command on one run. Pure; no side effects."""

    outcome: str
    lane: str
    role: str
    command_class: str | None = None
    #: Legacy ``_HARNESS_BLOCK_PATTERNS`` reason code, carried so the audit
    #: lane and existing consumers keep their vocabulary.
    reason: str | None = None
    failure_class: str | None = None
    config_key: str | None = None
    summary: str = ""
    fix_hint: str = ""
    persona_id: str = ""
    session_id: str = ""
    grant_issues: tuple[TerminalEnvelopeGrantIssue, ...] = ()
    #: The permission mode the run resolved, carried onto every receipt.
    permission_mode: str = ""
    #: :data:`GRANT_SOURCE_CONFIG` or :data:`GRANT_SOURCE_PERMISSION_MODE` on a
    #: grant; empty otherwise.
    grant_source: str = ""

    @property
    def refused(self) -> bool:
        return self.outcome == OUTCOME_REFUSE

    @property
    def granted(self) -> bool:
        return self.outcome == OUTCOME_GRANTED

    def row(self) -> dict[str, Any]:
        """``{code, subject, entry_point_lane, summary, fix_hint}`` — the same
        typed-row shape ``mcp_lane`` / ``mcp_admission`` / ``machine_roots``
        already emit, so operator surfaces need no new case."""

        return {
            "code": self.failure_class or self.outcome,
            "subject": self.command_class or "",
            "entry_point_lane": self.lane,
            "summary": self.summary,
            "fix_hint": self.fix_hint,
        }

    @property
    def granted_by(self) -> str | None:
        """The provenance string a receipt records for a GRANT.

        A config grant names its ROOT-config key (unchanged). A permission-mode
        grant has no config key by construction — naming the mode is the whole
        point of the receipt, so it says ``permission_mode=unbounded`` rather
        than leaving the field null and losing why the command ran.
        """

        if not self.granted:
            return None
        if self.grant_source == GRANT_SOURCE_PERMISSION_MODE:
            return f"permission_mode={self.permission_mode}"
        return self.config_key



# ── config (ROOT only) ──────────────────────────────────────────────────────

def canonical_role(role: str) -> str:
    """A grant-table role key, lower-cased, with the S64-ruled alias
    (``neko_supervisor`` -> ``alice_supervisor``) resolved one way through its
    ONE owner, :func:`agent_runtime.personas.canonical_persona_id`.

    Retained as wire/config compatibility so persisted role-envelope keys and
    historical decision-contract values still decode. S66 removed a THIRD entry,
    bare ``"neko" -> "alice_supervisor"``, which the S64 ruling never covered:
    this feeds a PERMISSION path (``resolve_terminal_envelope_grants``), so an
    un-ruled alias silently widens who a grant applies to. The owner carries the
    same warning.
    """

    return canonical_persona_id(str(role or "").strip().lower())


def grant_config_key(*, role: str, lane: str) -> str:
    return f"agent_runtime.terminal_envelope.grants.{canonical_role(role)}.{str(lane or '').strip()}"


#: Every governed decision that mattered (granted or refused) lands here.
ENVELOPE_DECISION_LOG = "terminal_envelope_decisions.jsonl"
#: Refusals ALSO keep landing in the pre-existing envelope audit lane so
#: operators watching that file lose nothing.
BLOCKED_ATTEMPT_LOG = "blocked_tool_attempts.jsonl"


def scope_for_persona(
    persona: Any,
    *,
    lane: str = LANE_MISSION_CHAT,
    session_id: str | None = None,
    runtime_root: Any = None,
    permission_mode: str | None = None,
) -> TerminalEnvelopeScope:
    """Build the run scope from a persona. Never raises on a odd role value."""

    from ..personas import role_or_attr

    role = role_or_attr(persona)
    return TerminalEnvelopeScope(
        lane=str(lane or "").strip(),
        role=role,
        persona_id=str(getattr(persona, "id", "") or ""),
        session_id=str(session_id or ""),
        runtime_root=str(runtime_root or ""),
        permission_mode=str(permission_mode or ""),
    )
