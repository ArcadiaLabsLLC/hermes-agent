"""The ROOT-config grants table: ``grants.<role>.<lane>``, deny-by-default.

``envelope_config`` (ROOT config only — a profile cannot grant itself) and
``resolve_terminal_envelope_grants``, which turns every rejected entry into a
typed issue instead of dropping it.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from agent_runtime.terminal_envelope.classes import COMMAND_CLASSES, GRANTABLE_COMMAND_CLASSES
from agent_runtime.terminal_envelope.records import (
    GRANT_CLASS_NOT_GRANTABLE,
    GRANT_MALFORMED,
    GRANT_UNKNOWN_COMMAND_CLASS,
    TerminalEnvelopeGrantIssue,
    TerminalEnvelopeGrants,
    canonical_role,
    grant_config_key,
)

__layer__ = "policy"

logger = logging.getLogger(__name__)




def envelope_config(cfg: Any | None = None):
    """The ``agent_runtime.terminal_envelope`` block from the ROOT config.

    Harness-wide operator policy, so it loads through
    ``config.load_root_runtime_config`` — a sticky-active profile's own
    ``config.yaml`` must not be able to grant itself the right to push. Any
    load fault yields the empty (grants-nothing) config: a config fault can
    only ever narrow.
    """

    from ..runtime_config import TerminalEnvelopeConfig

    if cfg is not None:
        resolved = getattr(cfg, "terminal_envelope", None)
        return resolved if resolved is not None else TerminalEnvelopeConfig()
    try:
        from ..config.loader import load_root_runtime_config

        return load_root_runtime_config().terminal_envelope
    except Exception:  # pragma: no cover - defensive; a config fault must not open the gate
        logger.debug("terminal envelope config load failed; granting nothing", exc_info=True)
        return TerminalEnvelopeConfig()


def _lanes_for_role(grants: Mapping[str, Any], canon_role: str) -> Any:
    """The lane map for a role, honoring the persona aliases (:func:`canonical_role`) on config keys.

    The canonical spelling wins outright when present; an alias is only
    consulted when the canonical key is absent. Never unions the two — a
    resolution rule that merged both spellings would widen a grant table
    depending on how many ways the operator happened to spell one role.
    """

    direct = grants.get(canon_role)
    if direct is not None:
        return direct
    for key, value in grants.items():
        if canonical_role(str(key)) == canon_role:
            return value
    return None


def resolve_terminal_envelope_grants(
    *, role: str, lane: str, cfg: Any | None = None
) -> TerminalEnvelopeGrants:
    """``grants.<role>.<lane>`` — deny-by-default, no wildcard, no inheritance.

    Every rejected entry produces a typed issue instead of being dropped
    silently: an operator who mistypes ``git-push`` must learn that from the
    refusal, not from a command that keeps failing for a reason the config
    appears to have fixed.
    """

    canon_role = canonical_role(role)
    lane_text = str(lane or "").strip()
    config = envelope_config(cfg)
    grants = getattr(config, "grants", None) or {}
    if not isinstance(grants, Mapping):
        return TerminalEnvelopeGrants(role=canon_role, lane=lane_text)

    lanes = _lanes_for_role(grants, canon_role)
    if not isinstance(lanes, Mapping):
        return TerminalEnvelopeGrants(role=canon_role, lane=lane_text)

    raw_classes = lanes.get(lane_text)
    if raw_classes is None:
        return TerminalEnvelopeGrants(role=canon_role, lane=lane_text)
    if not isinstance(raw_classes, (list, tuple, set, frozenset)):
        issue = TerminalEnvelopeGrantIssue(
            code=GRANT_MALFORMED,
            subject=grant_config_key(role=canon_role, lane=lane_text),
            summary=(
                f"{grant_config_key(role=canon_role, lane=lane_text)} is "
                f"{type(raw_classes).__name__}, not a list of command classes; nothing is granted."
            ),
            fix_hint="Write it as a YAML list, e.g. mission_chat: [git_push].",
        )
        return TerminalEnvelopeGrants(role=canon_role, lane=lane_text, issues=(issue,))

    granted: set[str] = set()
    issues: list[TerminalEnvelopeGrantIssue] = []
    for raw in raw_classes:
        name = str(raw or "").strip()
        if not name:
            continue
        if name not in COMMAND_CLASSES:
            issues.append(
                TerminalEnvelopeGrantIssue(
                    code=GRANT_UNKNOWN_COMMAND_CLASS,
                    subject=name,
                    summary=(
                        f"'{name}' is not a terminal-envelope command class, so it grants nothing."
                    ),
                    fix_hint=(
                        "Valid classes: " + ", ".join(sorted(COMMAND_CLASSES)) + "."
                    ),
                )
            )
            continue
        if name not in GRANTABLE_COMMAND_CLASSES:
            issues.append(
                TerminalEnvelopeGrantIssue(
                    code=GRANT_CLASS_NOT_GRANTABLE,
                    subject=name,
                    summary=(
                        f"'{name}' is a hard envelope floor and cannot be granted by config; "
                        "it grants nothing."
                    ),
                    fix_hint=(
                        "Grantable classes: " + ", ".join(sorted(GRANTABLE_COMMAND_CLASSES)) + "."
                    ),
                )
            )
            continue
        granted.add(name)

    return TerminalEnvelopeGrants(
        role=canon_role,
        lane=lane_text,
        classes=frozenset(granted),
        issues=tuple(issues),
    )
