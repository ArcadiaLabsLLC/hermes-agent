"""One deterministic, operator-governed decision point for envelope-gated commands.

Why this module exists
----------------------
The harness terminal safety envelope (``tools/terminal_tool.py`` —
``_HARNESS_BLOCK_PATTERNS`` / ``_harness_safety_block``, both fork-added) hard
blocks ``git push``, destructive git, recursive delete, credential reads,
production operations and non-localhost network egress. It activates on the mere
PRESENCE of ``HERMES_AGENT_RUNTIME_ROOT`` and reads no permission state at
all — see ``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/mission-chat-lane-gap-audit.md`` G4/G5b.

That produced a lane that behaves two opposite ways for the same command, and
BOTH were observed live on 2026-07-26 on the mission-chat Dev lane:

* **fail-CLOSED** — a turn whose persona is bound to a Hermes profile runs
  inside :func:`agent_runtime.profile_context.persona_profile_context`, which
  exports ``HERMES_AGENT_RUNTIME_ROOT``. The envelope fires and the agent gets
  ``git_push_requires_operator_approval`` with no channel to obtain that
  approval.
* **fail-OPEN** — a turn whose persona binds NO Hermes profile takes the
  ``binding.profile_home is None`` early-``yield`` at
  ``profile_context.py:82-84``: ``HERMES_AGENT_RUNTIME_ROOT`` is never
  exported, so the envelope is INERT. The command then falls through to
  ``tools/approval.py``, where ``is_cli`` / ``is_gateway`` / ``is_ask`` are all
  false and no cron marker is set — the historical non-interactive fail-open
  default — and ``git push origin main`` executes ungated and unrecorded.

Same lane, same role, opposite outcomes — decided by ambient process
environment state that nothing in the policy layer controls. Profile binding is
the clearest path to "unset" (above), and process history is a second: some
harness command handlers ``os.environ.setdefault`` the variable and
``_cmd_mission_chat_message`` does not, so in a long-lived ``harness serve``
process the answer also depends on what ran before this turn. Either way it is
not a policy; it is a coin flip.

What this module does
---------------------
It is the ONE place that answers "may this command run on this lane?" for the
envelope-gated classes, and it answers deterministically:

* **Governed lane + gated class + explicit grant** ⇒ runs, and the grant
  provenance is recorded (:func:`record_envelope_decision`).
* **Governed lane + gated class + no grant** ⇒ a TYPED refusal carrying the
  command class, the exact ROOT-config key that would grant it, the lane and
  the role. Never a silent auto-approval; never an unexplained hard block.
* **Governed lane + ungated command** ⇒ allowed, exactly as before.
* **Ungoverned lane** (no governed scope bound: ``hermes chat``, cron,
  gateway, acp, plain CLI) ⇒ :func:`envelope_decision` returns
  ``None`` and the caller keeps the legacy behavior byte-for-byte. This slice
  changes ONE lane.

Because the decision is keyed on a bound :class:`TerminalEnvelopeScope` rather
than on ``HERMES_AGENT_RUNTIME_ROOT``, the fail-open branch is closed: a
mission-chat turn is governed whether or not its persona binds a profile.

TWO DOORS — read this before believing "deny by default"
---------------------------------------------------------
A class can be granted by **either** of two independent paths, and only the
first is described below:

1. the **grants table**, which is deny-by-default (rules 1-4 below), and
2. the **permission mode**, where :func:`resolve` grants any class in
   :data:`GRANTABLE_COMMAND_CLASSES` on ``resolved.unbounded`` alone —
   without consulting the grants table at all.

``unbounded`` is the SHIPPED DEFAULT. Ruling R-2 also removed the last hard
floors, so today, with no stanza written anywhere, **every class in
:data:`COMMAND_CLASSES` runs on a governed lane.** That is deliberate: R-2
traded a preventive control for a detective one, and the compensating control
is that a mode grant is receipted through ``record_envelope_decision`` exactly
like a config grant. Nothing runs unaudited.

This note exists because the section below is true of the grants table and
says nothing about the mode door, and a reader who stops here concludes the
opposite of the live posture. A doc did exactly that for weeks
(``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/mission-chat-terminal-envelope-grants.md``,
corrected 2026-08-14) while quoting rule 2 accurately.

Grants are ROOT-config only
---------------------------
Mirrors the ``agent_runtime/mcp_admission.py`` precedent (landed 2026-07-26)
in every load-bearing respect. Everything in this section describes the GRANTS
TABLE door only — see "TWO DOORS" above:

1. **Root config only.** Read through
   :func:`agent_runtime.config.load_root_runtime_config`, so a sticky-active
   profile's own ``config.yaml`` can never grant itself the right to push. A
   profile cannot self-grant.
2. **Deny by default, no wildcard, no inheritance.** ``grants.<role>.<lane>``
   with no entry admits nothing. There is no ``*`` role, no ``*`` lane, and a
   grant on one lane says nothing about another.
3. **A code-owned command taxonomy.** :data:`COMMAND_CLASSES` is the complete
   envelope surface. Every current class is grantable; adding a future class
   still requires an explicit code review before configuration can name it.
4. **Every step can only NARROW.** A malformed stanza, an unknown class, a
   non-list value — all collapse to "grants nothing" AND produce a typed
   config issue. A config fault never reads as "allow".

Root ``config.yaml`` shape::

    agent_runtime:
      terminal_envelope:
        grants:
          dev:
            mission_chat: [git_push]

Nothing in THIS section weakens the envelope for a class that has no grant.
The mode door above is what does, and it does so by design.

The package map (rule 16)
-------------------------
Entry points, and the modules an agent opens to follow each:

* one terminal command on a governed lane (``tools/terminal_tool.py``,
  upstream, through ``terminal_policy``) -> ``decision`` -> ``grants`` ->
  ``records`` (+ ``classes`` for the classification), then ``receipts`` for
  the receipt;
* ``explain_terminal_envelope`` (``runtime_hud``, ``terminal_envelope_explain``)
  -> ``decision`` -> ``grants``;
* ``scope_for_persona`` / ``terminal_envelope_scope`` (``persona_runtime``,
  ``profile_runner/execute``) -> ``records``.

Modules, lowest layer first (no module imports one above it — W0-G6):

==========  ======  =======================================================
module      layer   owns
==========  ======  =======================================================
classes     models  VOCABULARY/TABLE: the governed lane, the four command
                    classes, the legacy reason + summary tables, the pattern
                    mirror, ``classify_command``
records     models  the scope + its ContextVar ferry, the outcome / failure /
                    grant tokens, the grant issue / grants / decision records,
                    the role aliases + config-key spelling, the two receipt
                    log names
grants      policy  the ROOT-config grants table: ``envelope_config``,
                    ``resolve_terminal_envelope_grants``
decision    policy  ``envelope_decision``, the fix hint, ``refusal_text``,
                    ``explain_terminal_envelope``,
                    ``hard_floor_command_classes``
receipts    stores  the audit-root ladder, the two JSONL receipts,
                    ``envelope_provenance``, ``blocked_result``
==========  ======  =======================================================

Stores written: ``<audit root>/terminal_envelope_decisions.jsonl`` and
``blocked_tool_attempts.jsonl`` (``receipts`` only).
"""

from __future__ import annotations

from agent_runtime.terminal_envelope import (  # noqa: F401 — every family, lowest layer first
    classes,
    records,
    grants,
    decision,
    receipts,
)
from agent_runtime.terminal_envelope.classes import (
    CLASS_SUMMARY,
    COMMAND_CLASSES,
    DESTRUCTIVE_GIT,
    GIT_PUSH,
    GOVERNED_LANES,
    GRANTABLE_COMMAND_CLASSES,
    LANE_MISSION_CHAT,
    LEGACY_REASON_BY_CLASS,
    NETWORK_EGRESS,
    RECURSIVE_DELETE,
    classify_command,
    legacy_reason_for_class,
)
from agent_runtime.terminal_envelope.records import (
    BLOCKED_ATTEMPT_LOG,
    ENVELOPE_COMMAND_NOT_GRANTABLE,
    ENVELOPE_COMMAND_REQUIRES_GRANT,
    ENVELOPE_DECISION_LOG,
    GRANT_CLASS_NOT_GRANTABLE,
    GRANT_MALFORMED,
    GRANT_SOURCE_CONFIG,
    GRANT_SOURCE_PERMISSION_MODE,
    GRANT_UNKNOWN_COMMAND_CLASS,
    OUTCOME_ALLOW,
    OUTCOME_GRANTED,
    OUTCOME_REFUSE,
    TerminalEnvelopeDecision,
    TerminalEnvelopeGrantIssue,
    TerminalEnvelopeGrants,
    TerminalEnvelopeScope,
    canonical_role,
    current_terminal_envelope_scope,
    grant_config_key,
    scope_for_persona,
    terminal_envelope_scope,
)
from agent_runtime.terminal_envelope.grants import (
    envelope_config,
    resolve_terminal_envelope_grants,
)
from agent_runtime.terminal_envelope.decision import (
    envelope_decision,
    explain_terminal_envelope,
    hard_floor_command_classes,
    refusal_text,
)
from agent_runtime.terminal_envelope.receipts import (
    AUDIT_ROOT_SOURCE_ENV,
    AUDIT_ROOT_SOURCE_RESOLVER,
    AUDIT_ROOT_SOURCE_SCOPE,
    ENVELOPE_RESULT_KEY,
    audit_root_source,
    blocked_result,
    envelope_provenance,
    record_envelope_decision,
    record_legacy_block,
)

__layer__ = "stores"

__all__ = [
    "AUDIT_ROOT_SOURCE_ENV",
    "AUDIT_ROOT_SOURCE_RESOLVER",
    "AUDIT_ROOT_SOURCE_SCOPE",
    "BLOCKED_ATTEMPT_LOG",
    "CLASS_SUMMARY",
    "COMMAND_CLASSES",
    "DESTRUCTIVE_GIT",
    "ENVELOPE_COMMAND_NOT_GRANTABLE",
    "ENVELOPE_COMMAND_REQUIRES_GRANT",
    "ENVELOPE_DECISION_LOG",
    "ENVELOPE_RESULT_KEY",
    "GIT_PUSH",
    "GOVERNED_LANES",
    "GRANTABLE_COMMAND_CLASSES",
    "GRANT_CLASS_NOT_GRANTABLE",
    "GRANT_MALFORMED",
    "GRANT_SOURCE_CONFIG",
    "GRANT_SOURCE_PERMISSION_MODE",
    "GRANT_UNKNOWN_COMMAND_CLASS",
    "LANE_MISSION_CHAT",
    "LEGACY_REASON_BY_CLASS",
    "NETWORK_EGRESS",
    "OUTCOME_ALLOW",
    "OUTCOME_GRANTED",
    "OUTCOME_REFUSE",
    "RECURSIVE_DELETE",
    "TerminalEnvelopeDecision",
    "TerminalEnvelopeGrantIssue",
    "TerminalEnvelopeGrants",
    "TerminalEnvelopeScope",
    "audit_root_source",
    "blocked_result",
    "canonical_role",
    "classify_command",
    "current_terminal_envelope_scope",
    "envelope_config",
    "envelope_decision",
    "envelope_provenance",
    "explain_terminal_envelope",
    "grant_config_key",
    "hard_floor_command_classes",
    "legacy_reason_for_class",
    "record_envelope_decision",
    "record_legacy_block",
    "refusal_text",
    "resolve_terminal_envelope_grants",
    "scope_for_persona",
    "terminal_envelope_scope",
]
