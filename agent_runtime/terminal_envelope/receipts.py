"""The receipts: where a governed decision is written, and what the tool result carries.

The audit-root ladder (scope -> env -> resolver) and which rung answered; the
two JSONL receipts (``record_envelope_decision``, ``record_legacy_block``);
``envelope_provenance`` and ``blocked_result`` — the tool-result shapes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Mapping

from agent_runtime.terminal_envelope.decision import refusal_text
from agent_runtime.terminal_envelope.records import (
    BLOCKED_ATTEMPT_LOG,
    ENVELOPE_DECISION_LOG,
    OUTCOME_ALLOW,
    TerminalEnvelopeDecision,
    TerminalEnvelopeScope,
    current_terminal_envelope_scope,
)

__layer__ = "stores"


logger = logging.getLogger(__name__)



# ── provenance ──────────────────────────────────────────────────────────────





#: Where a receipt root came from. Recorded on the row so an operator reading
#: a receipt can tell a scope-carried root from a resolved one.
AUDIT_ROOT_SOURCE_SCOPE = "scope"
AUDIT_ROOT_SOURCE_ENV = "env"
AUDIT_ROOT_SOURCE_RESOLVER = "resolver"


def _audit_root(scope: TerminalEnvelopeScope | None) -> Path | None:
    """The directory a governed decision's receipt lands in — a full ladder.

    Three rungs, first non-empty wins: the bound scope's ``runtime_root``, then
    ``HERMES_AGENT_RUNTIME_ROOT``, then the canonical resolver
    (``paths.store_root`` → ``resolution.resolve_runtime``, which has its own
    env → config → default ladder and always answers).

    The third rung is the point. Rungs 1 and 2 can BOTH be empty — ``scope`` is
    optional and ``scope_for_persona``'s ``runtime_root`` argument defaults to
    ``None``, and a profile-less persona never exports the variable
    (``profile_context.py``'s ``profile_home is None`` early-yield). Without a
    resolver rung, that combination silently drops the receipt for a decision
    that was itself made deterministically — the SAME ambient-presence
    dependence this module was written to retire, one layer down: the decision
    became a policy, but whether anyone could later prove it happened was still
    decided by process ancestry.

    Never raises: the resolver can refuse (``ProbeIsolationViolation`` under
    ``HERMES_REQUIRE_ISOLATED_ROOT``), and auditability must not gate the
    answer. Returning ``None`` after all three rungs means "genuinely nowhere
    to write", not "nobody exported a variable".
    """

    root = ""
    if scope is not None:
        root = str(scope.runtime_root or "").strip()
    if not root:
        root = str(os.getenv("HERMES_AGENT_RUNTIME_ROOT", "") or "").strip()
    if not root:
        try:
            from ..paths import store_root

            root = str(store_root() or "").strip()
        except Exception:
            # A refusing resolver (probe isolation) or an unimportable module
            # is a real "nowhere to write" — fall through to None rather than
            # inventing a path.
            logger.debug("Envelope audit root unresolvable", exc_info=True)
            root = ""
    if not root:
        return None
    try:
        return Path(root).expanduser()
    except Exception:  # pragma: no cover - defensive
        return None


def audit_root_source(scope: TerminalEnvelopeScope | None) -> str:
    """Which rung of :func:`_audit_root` answered. Pure; for receipts + tests."""

    if scope is not None and str(scope.runtime_root or "").strip():
        return AUDIT_ROOT_SOURCE_SCOPE
    if str(os.getenv("HERMES_AGENT_RUNTIME_ROOT", "") or "").strip():
        return AUDIT_ROOT_SOURCE_ENV
    return AUDIT_ROOT_SOURCE_RESOLVER


def _append_jsonl(root: Path, name: str, event: Mapping[str, Any]) -> bool:
    """Append one receipt row. Returns whether the row actually landed.

    The boolean is not decoration. Since the 2026-08-09 ruling the receipt IS
    the compensating control, so "a receipt was written" is a claim the runtime
    now makes to the agent (:func:`envelope_provenance`). A writer that swallows
    its IO error and still reports success would turn the one honest record of a
    detective control into an unfalsifiable assertion — the failure had to become
    a VALUE, not just a log line nobody reads.
    """

    try:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        logger.warning("Failed to write terminal-envelope audit row", exc_info=True)
        return False
    return True


def record_envelope_decision(
    decision: TerminalEnvelopeDecision,
    command: str,
    *,
    scope: TerminalEnvelopeScope | None = None,
) -> bool:
    """Write the receipt. Never raises — auditability must not gate the answer.

    A granted command is recorded with its GRANT PROVENANCE (which config key
    allowed it, for which role and lane), because "it ran because the operator
    said so" is the only honest record of a command the envelope would
    otherwise have blocked.

    Returns whether a row landed in :data:`ENVELOPE_DECISION_LOG` — the lane
    that carries the ruling's compensating control. ``False`` for an ungoverned
    or ungated command (nothing to receipt), for an unresolvable audit root, and
    for a failed write. Callers surface it to the agent rather than asserting a
    receipt exists; see :func:`envelope_provenance`.
    """

    if decision.outcome == OUTCOME_ALLOW:
        return False
    resolved = scope if scope is not None else current_terminal_envelope_scope()
    root = _audit_root(resolved)
    if root is None:
        return False
    preview = str(command or "")[:500]
    event: dict[str, Any] = {
        "ts": time.time(),
        "tool": "terminal",
        # Which rung answered, so a receipt is self-describing: an operator
        # reading a row never has to guess whether the root came from the run's
        # own scope or from ambient process state.
        "audit_root_source": audit_root_source(resolved),
        "decision": decision.outcome,
        "lane": decision.lane,
        "role": decision.role,
        "persona_id": decision.persona_id,
        "session_id": decision.session_id,
        "command_class": decision.command_class,
        "reason": decision.reason,
        "failure_class": decision.failure_class,
        # WHY it ran (or was refused under which posture). ``granted_by`` keeps
        # naming the ROOT-config key for a config grant and names the MODE for a
        # permission-mode grant, so no granted command lands in this log without
        # its provenance — the compensating control the 2026-08-09 ruling
        # substitutes for the refusal it removed.
        "granted_by": decision.granted_by,
        "grant_source": decision.grant_source or None,
        "permission_mode": decision.permission_mode or None,
        "command_preview": preview,
    }
    if decision.grant_issues:
        event["grant_issues"] = [issue.row() for issue in decision.grant_issues]
    written = _append_jsonl(root, ENVELOPE_DECISION_LOG, event)
    if decision.refused:
        _append_jsonl(
            root,
            BLOCKED_ATTEMPT_LOG,
            {
                "ts": event["ts"],
                "tool": "terminal",
                "reason": decision.reason or decision.failure_class,
                "command_preview": preview,
                "failure_class": decision.failure_class,
                "command_class": decision.command_class,
                "lane": decision.lane,
                "role": decision.role,
                "config_key": decision.config_key,
            },
        )
    return written


def record_legacy_block(
    command: str,
    reason: str,
    *,
    scope: TerminalEnvelopeScope | None = None,
) -> bool:
    """Write the receipt for a LEGACY (pattern-table) block. Audit Q3.

    ``tools/terminal_tool.py::_log_harness_blocked_attempt`` writes the same row
    but resolves its root as ``os.getenv("HERMES_AGENT_RUNTIME_ROOT")`` and
    **returns early when that is unset** — the command was blocked and nothing
    recorded it, silently. That is reader #4's bug one file over, and reader #4
    is the reason this module already owns a three-rung ladder (:func:`_audit_root`).

    This is the fork-owned replacement for that body. It exists on this side of
    the ``tools/`` boundary so the upstream change is a ONE-LINE delegation
    rather than a re-derivation:

    .. code-block:: diff

        -def _log_harness_blocked_attempt(command: str, reason: str) -> None:
        -    root = os.getenv("HERMES_AGENT_RUNTIME_ROOT", "").strip()
        -    if not root:
        -        return
        -    try:
        -        path = Path(root).expanduser() / "blocked_tool_attempts.jsonl"
        -        ...
        +def _log_harness_blocked_attempt(command: str, reason: str) -> None:
        +    from agent_runtime.terminal_envelope import record_legacy_block
        +
        +    record_legacy_block(command, reason)

    Until that lands, the legacy writer keeps its silent-drop branch on runs
    that bind NO envelope scope. Runs that DO bind one never reach it at all:
    :func:`envelope_decision` answers for every harness lane (Q2), so
    ``_harness_envelope_block`` returns before the legacy table is consulted and
    :func:`record_envelope_decision` writes the receipt through the same ladder.

    Row shape is the legacy one verbatim (``ts``/``tool``/``reason``/
    ``command_preview``) so existing ``blocked_tool_attempts.jsonl`` readers
    need no change, plus ``audit_root_source`` so a receipt says which rung
    resolved its root. Returns whether a row was written; never raises.
    """

    resolved = scope if scope is not None else current_terminal_envelope_scope()
    root = _audit_root(resolved)
    if root is None:
        return False
    _append_jsonl(
        root,
        BLOCKED_ATTEMPT_LOG,
        {
            "ts": time.time(),
            "tool": "terminal",
            "reason": str(reason or ""),
            "command_preview": str(command or "")[:500],
            "audit_root_source": audit_root_source(resolved),
        },
    )
    return True


#: Top-level key the terminal tool's JSON result carries provenance under. Named
#: here, next to the shape, so the producer and the merge site cannot drift.
ENVELOPE_RESULT_KEY = "envelope"


def envelope_provenance(
    decision: TerminalEnvelopeDecision | None,
    *,
    receipted: bool,
) -> dict[str, Any] | None:
    """The provenance fragment merged into a GRANTED command's tool result.

    Why this exists
    ---------------
    The 2026-08-09 unbounded-default ruling removed the preventive refusal for
    every grantable command class and substituted a detective control: the
    receipt in :data:`ENVELOPE_DECISION_LOG`. That trade only holds if the fact
    is *checkable*, and the one party who could never check it was the party the
    receipt is about. Live 2026-08-09 a QA agent ran a formerly-refused
    ``network_egress`` command, was asked to confirm the mechanism, and reported
    the audit proof MISSING — returning an honest BLOCKED verdict on facts that
    were all fine — because the granted path returned the ordinary result and
    said nothing. The runtime knew; its subject did not.

    So this is not new authority and not a new decision. Everything here was
    already resolved by :func:`envelope_decision` and already written by
    :func:`record_envelope_decision`; this makes an existing fact visible to the
    one reader who was structurally blind to it.

    Shape and cost
    --------------
    Returns ``None`` for anything that is not a grant — an ungoverned lane
    (``decision is None``), and, importantly, :data:`OUTCOME_ALLOW`, which is
    almost every command an agent ever runs. The fragment rides ONLY the gated
    classes, so the common path pays exactly zero tokens. A refusal pays nothing
    here either: :func:`blocked_result` already carries the class, the config key
    and the typed failure row.

    ``receipt_log`` is the BARE FILENAME, never the resolved runtime root. The
    agent needs to know which lane the row landed in, not where the operator's
    store lives, and the same constant is already agent-visible in the HUD's
    capability posture line. ``receipted`` is the write's real answer, not an
    assumption — a receipt that silently failed to land is precisely the case an
    agent must not report as proof.
    """

    if decision is None or not decision.granted:
        return None
    row: dict[str, Any] = {
        "command_class": decision.command_class or "",
        "decision": decision.outcome,
        # Names the ROOT-config key for a config grant and the MODE for a
        # permission-mode grant — the same string the receipt records, so the
        # agent's account and the operator's log cannot disagree.
        "granted_by": decision.granted_by or "",
        "grant_source": decision.grant_source or "",
        "receipt_log": ENVELOPE_DECISION_LOG,
        "receipted": bool(receipted),
    }
    if decision.permission_mode:
        row["permission_mode"] = decision.permission_mode
    return {ENVELOPE_RESULT_KEY: row}


def blocked_result(decision: TerminalEnvelopeDecision) -> dict[str, Any]:
    """The terminal-tool JSON payload for a refusal.

    Keeps every key the legacy hard block emitted (``status``, ``blocked_by``,
    ``block_reason``) so nothing downstream has to learn a new shape, and adds
    the typed fields that make the refusal self-explanatory.
    """

    return {
        "output": "",
        "exit_code": -1,
        "error": refusal_text(decision),
        "status": "blocked",
        "blocked_by": "harness_execution_safety",
        "block_reason": decision.reason or decision.failure_class,
        "failure_class": decision.failure_class,
        "command_class": decision.command_class,
        "lane": decision.lane,
        "role": decision.role,
        "config_key": decision.config_key,
        "requirement_failure": decision.row(),
    }
