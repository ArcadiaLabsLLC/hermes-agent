"""The one answer per command: ``envelope_decision``, and how a refusal reads.

The decision (ungoverned -> ungated -> config grant -> mode grant -> hard
floor -> requires grant, in that order), the operator-actionable fix hint,
``refusal_text``, the side-effect-free ``explain_terminal_envelope`` view and
``hard_floor_command_classes``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.permission_modes import permission_mode_is_unbounded

from agent_runtime.terminal_envelope.classes import (
    CLASS_SUMMARY,
    GOVERNED_LANES,
    COMMAND_CLASSES,
    GRANTABLE_COMMAND_CLASSES,
    LANE_MISSION_CHAT,
    classify_command,
    legacy_reason_for_class,
)
from agent_runtime.terminal_envelope.grants import resolve_terminal_envelope_grants
from agent_runtime.terminal_envelope.records import (
    ENVELOPE_COMMAND_NOT_GRANTABLE,
    ENVELOPE_COMMAND_REQUIRES_GRANT,
    ENVELOPE_DECISION_LOG,
    GRANT_SOURCE_CONFIG,
    GRANT_SOURCE_PERMISSION_MODE,
    OUTCOME_ALLOW,
    OUTCOME_GRANTED,
    OUTCOME_REFUSE,
    TerminalEnvelopeDecision,
    TerminalEnvelopeGrants,
    TerminalEnvelopeScope,
    current_terminal_envelope_scope,
    grant_config_key,
)

__layer__ = "policy"




# ── the decision ────────────────────────────────────────────────────────────


def envelope_decision(
    command: str,
    *,
    scope: TerminalEnvelopeScope | None = None,
    cfg: Any | None = None,
) -> TerminalEnvelopeDecision | None:
    """Decide one command, or return ``None`` when this lane is not governed.

    ``None`` is load-bearing: it means "this module has no opinion, keep the
    legacy behavior" and is what every run that binds NO scope gets — i.e.
    everything that is not a harness-constructed run (``hermes chat``, cron,
    gateway, acp, plain CLI). Callers must treat ``None`` as "fall through",
    never as "allow".

    Mission-chat is the only producer of a governed scope. A stale or external
    scope carrying any other lane gets ``None`` and therefore cannot invent a
    second grant surface.
    """

    resolved = scope if scope is not None else current_terminal_envelope_scope()
    if resolved is None or not resolved.governed:
        return None

    permission_mode = str(resolved.permission_mode or "")
    command_class = classify_command(command)
    if command_class is None:
        return TerminalEnvelopeDecision(
            outcome=OUTCOME_ALLOW,
            lane=resolved.lane,
            role=resolved.role,
            persona_id=resolved.persona_id,
            session_id=resolved.session_id,
            permission_mode=permission_mode,
        )

    reason = legacy_reason_for_class(command_class)
    grants = resolve_terminal_envelope_grants(role=resolved.role, lane=resolved.lane, cfg=cfg)
    config_key = grants.config_key

    if command_class in grants.classes:
        return TerminalEnvelopeDecision(
            outcome=OUTCOME_GRANTED,
            lane=resolved.lane,
            role=resolved.role,
            command_class=command_class,
            reason=reason,
            config_key=config_key,
            summary=(
                f"'{command_class}' is granted for role '{grants.role}' on the "
                f"'{resolved.lane}' lane by {config_key}."
            ),
            persona_id=resolved.persona_id,
            session_id=resolved.session_id,
            grant_issues=grants.issues,
            permission_mode=permission_mode,
            grant_source=GRANT_SOURCE_CONFIG,
        )

    # Permission-mode grant (operator ruling 2026-08-09). An ``unbounded`` run
    # gets every GRANTABLE class without a per-role config stanza — schema-plane
    # "full tool access" was hollow while the execution plane still refused
    # ``git push``. Three properties are load-bearing and must not be softened:
    #
    # * it never touches the hard floor (``GRANTABLE_COMMAND_CLASSES`` is the
    #   bound, and the not-grantable branch below is unchanged),
    # * it never applies to an ungoverned lane (we returned ``None`` above), and
    # * it is RECEIPTED exactly like a config grant. This is the compensating
    #   control the ruling trades the refusal for: preventive → detective. If a
    #   future change makes a mode-granted command run without
    #   ``record_envelope_decision`` seeing it, the ruling's safety argument is
    #   gone, not merely weakened.
    if resolved.unbounded and command_class in GRANTABLE_COMMAND_CLASSES:
        return TerminalEnvelopeDecision(
            outcome=OUTCOME_GRANTED,
            lane=resolved.lane,
            role=resolved.role,
            command_class=command_class,
            reason=reason,
            # No config key: this grant did not come from the grants table, and
            # naming one would send an operator to a stanza that is not why the
            # command ran.
            config_key=None,
            summary=(
                f"'{command_class}' is granted by permission_mode="
                f"'{permission_mode}' (runtime default) for role '{grants.role}' on "
                f"the '{resolved.lane}' lane; the command is recorded in "
                f"{ENVELOPE_DECISION_LOG}."
            ),
            persona_id=resolved.persona_id,
            session_id=resolved.session_id,
            grant_issues=grants.issues,
            permission_mode=permission_mode,
            grant_source=GRANT_SOURCE_PERMISSION_MODE,
        )

    if command_class not in GRANTABLE_COMMAND_CLASSES:
        return TerminalEnvelopeDecision(
            outcome=OUTCOME_REFUSE,
            lane=resolved.lane,
            role=resolved.role,
            command_class=command_class,
            reason=reason,
            failure_class=ENVELOPE_COMMAND_NOT_GRANTABLE,
            config_key=None,
            summary=(
                f"This command {CLASS_SUMMARY.get(command_class, 'is envelope-gated')} "
                f"('{command_class}'), which is a hard floor of the Harness execution "
                "safety envelope. No configuration grants it."
            ),
            fix_hint=(
                "There is no config key for this class and no permission mode lifts it. "
                "Do not retry or reword the command — achieve the goal without it, or ask "
                "the operator to perform this step themselves."
            ),
            persona_id=resolved.persona_id,
            session_id=resolved.session_id,
            grant_issues=grants.issues,
            permission_mode=permission_mode,
        )

    return TerminalEnvelopeDecision(
        outcome=OUTCOME_REFUSE,
        lane=resolved.lane,
        role=resolved.role,
        command_class=command_class,
        reason=reason,
        failure_class=ENVELOPE_COMMAND_REQUIRES_GRANT,
        config_key=config_key,
        summary=(
            f"This command {CLASS_SUMMARY.get(command_class, 'is envelope-gated')} "
            f"('{command_class}'), and role '{grants.role}' holds no grant for it on the "
            f"'{resolved.lane}' lane."
        ),
        fix_hint=_grant_fix_hint(
            role=grants.role, lane=resolved.lane, command_class=command_class, grants=grants
        ),
        persona_id=resolved.persona_id,
        session_id=resolved.session_id,
        grant_issues=grants.issues,
        permission_mode=permission_mode,
    )


def _grant_fix_hint(
    *, role: str, lane: str, command_class: str, grants: TerminalEnvelopeGrants
) -> str:
    """The operator-actionable half of the refusal the AGENT reads.

    Names the exact ROOT-config key, shows the stanza, and states plainly that
    the agent cannot grant it — the audit's finding was that the lane's own
    operative-rules text tells the model "the operator's current permission
    grant is the only gate", which is false. A refusal that does not say where
    the real gate lives reproduces that lie one layer down.
    """

    lines = [
        "This session is running under a RESTRICTED permission mode — the runtime "
        "default grants every operator-grantable envelope class, so a refusal here "
        "means an operator narrowed this session (`hermes harness persona permission "
        "set --mode bounded|read_only`) or the runtime default was configured "
        "narrower. Ask the operator to lift the restriction, or:",
        "",
        "An OPERATOR can allow just this class by adding this to the ROOT config.yaml "
        "(not a profile config — a profile cannot grant itself this):",
        "",
        "  agent_runtime:",
        "    terminal_envelope:",
        "      grants:",
        f"        {role}:",
        f"          {lane}: [{command_class}]",
        "",
        f"Config key: {grant_config_key(role=role, lane=lane)}",
        "The grant is read at turn time from the root config; a running "
        "`hermes harness serve` picks it up on its next turn.",
        "Do NOT retry, reword, or split this command — every form of it resolves to the "
        f"same '{command_class}' class and will be refused identically. Report the refusal "
        "to the operator and continue with the work you can do.",
    ]
    if grants.issues:
        lines.append("")
        lines.append("The existing grant stanza has problems that grant nothing:")
        for issue in grants.issues:
            lines.append(f"  - [{issue.code}] {issue.summary}")
    return "\n".join(lines)


def refusal_text(decision: TerminalEnvelopeDecision) -> str:
    """The full refusal an agent sees, self-explanatory by construction."""

    head = f"BLOCKED by Harness execution safety envelope: {decision.reason or decision.failure_class}"
    parts = [head, decision.summary]
    if decision.fix_hint:
        parts.append(decision.fix_hint)
    return "\n".join(part for part in parts if part)




def explain_terminal_envelope(
    *,
    role: str,
    lane: str = LANE_MISSION_CHAT,
    cfg: Any | None = None,
    permission_mode: str | None = None,
) -> dict[str, Any]:
    """Operator view: what this role may do on this lane, and why. No side effects.

    ``permission_mode`` makes the view match :func:`envelope_decision`: an
    ``unbounded`` run is granted every grantable class by MODE, so a view that
    only read the grants table would show classes as refused that the very next
    command would run. Left unset the answer is the config-grants-only view,
    byte-identical to the pre-2026-08-09 shape.
    """

    grants = resolve_terminal_envelope_grants(role=role, lane=lane, cfg=cfg)
    mode = str(permission_mode or "")
    granted_by_mode: frozenset[str] = frozenset()
    if lane in GOVERNED_LANES and permission_mode_is_unbounded(mode):
        granted_by_mode = GRANTABLE_COMMAND_CLASSES - grants.classes
    granted = grants.classes | granted_by_mode
    return {
        "lane": lane,
        "role": grants.role,
        "governed": lane in GOVERNED_LANES,
        "config_key": grants.config_key,
        "command_classes": sorted(COMMAND_CLASSES),
        "grantable_command_classes": sorted(GRANTABLE_COMMAND_CLASSES),
        "granted": sorted(granted),
        "granted_by_config": sorted(grants.classes),
        "granted_by_permission_mode": sorted(granted_by_mode),
        "permission_mode": mode,
        "refused": sorted(COMMAND_CLASSES - granted),
        "grant_issues": grants.issue_rows(),
    }


def hard_floor_command_classes() -> frozenset[str]:
    """The classes no configuration can grant (empty after ruling R-2).

    Read-only accessor over the two canonical sets above, added so operator
    surfaces (``harness persona tool-diff --explain-envelope``) can name the hard
    floor without re-deriving it from a hand-listed set of their own. The
    grantable/hard-floor split is exactly the distinction
    :data:`ENVELOPE_COMMAND_NOT_GRANTABLE` exists for: telling an agent — or an
    operator — to ask for a grant that cannot exist would be a new lie.
    """

    return frozenset(COMMAND_CLASSES - GRANTABLE_COMMAND_CLASSES)
