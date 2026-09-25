"""The ONE agent-create sequence, and the policy layer above its stores.

Two callers reach the same durable chokepoints — ``PersonaInstanceStore.
add_instance`` and ``OfficeStore.upsert_actor`` — and would silently disagree
about everything that sits ABOVE them:

* the argv lane, ``harness persona instance open-chat --add-instance``
  (``hermes_cli/harness_parts/persona_commands.py``), and
* the method lane, ``runtime.agent.create`` (``serve_rpc.py``).

The store methods are callable and unwelded (verified 2026-08-16), so nothing
had to be extracted out of ``persona_assignments.py``. What DID have to move is
the layer above them, because a handler calling the store directly drops it
without a word — the placement-id validation, the token/text normalisation, and
above all the **honest default display name** rule.

Why the naming rule is the load-bearing one
-------------------------------------------
An omitted name must fall back to the persona's OWN configured
``display_name`` ("QA Agent"), never to the title-cased persona id ("Qa") the
store template mints when it is handed nothing. The launcher's conversational
fold keys on persona+display_name, so a lane that minted "Qa" would fold a new
placement onto a channel it does not belong to. This module is the ONE copy of
that rule; :func:`honest_default_display_name` is what both lanes call.

Where this deviates from the plan, out loud
-------------------------------------------
``archive/2026-08-22-pre-consolidation/AGENT_CREATE_ONE_CALL_PLAN_2026-08-16.md`` AC-0 says the extraction goes
"UPWARD, not downward" — into the CLI's ``persona_commands.py``. That direction
was not available when this landed: the file was ``exec``'d into
``hermes_cli/harness.py``'s globals and its functions closed over names that
lived nowhere else. It is an importable package now
(``hermes_cli/harness_parts/persona/``, lanes H1/H3), but the direction stays
right on its own terms: the shared layer lives where BOTH lanes can import it
without a CLI dependency, which is here, and the CLI calls down into it. The plan's requirement
("the CLI and the RPC handler share one copy", "do not invent a second rule")
is met; only its stated direction is not.

UC-H1: the ORCHESTRATION moved here too
---------------------------------------
AC-1 shared the *policy* (naming, normalisation, payload shape) but left the
sequence — reserve → mint → place → compensate/resume — welded inline into
``serve_rpc._runtime_agent_create``, and therefore welded to JSON-RPC
``rid``/``ok``/``err`` envelopes. That made the atomic create reachable from
exactly one door: a live ``harness serve``. :func:`perform_agent_create` is
that sequence with the envelope peeled off; ``serve_rpc`` is now a translation
shim over it, ``harness agent create`` (UC-H3) calls it directly, and any
future MCP tool wraps whichever of the two it prefers. One sequence, zero
copies — a lane switch cannot become a behaviour change.

The refusal codes are still the JSON-RPC vocabulary (:data:`ERR_CONFLICT` and
friends) because the RPC lane is the fielded consumer and its ``data.reason``
strings are decoded by the launcher (``mission_agent_create_rpc.dart``). Other
lanes map that vocabulary to their own; they do not get to re-spell it.

The package map (program rule 16; layout sheet ``agent_create.md`` §1)
----------------------------------------------------------------------

One request's validation, one sequence, the phases the sequence writes, and
the vocabulary both lanes answer in. Modules, lowest layer first (no module
imports one above it — W0-G6):

========  ======  ============================================================
module    layer   owns
========  ======  ============================================================
outcome   models  ERR_* / PHASE_* / persona reasons, the reservation-fault
                  stamps, the exceptions, ``AgentCreateOutcome`` and ``_refused``
request   stores  ``AgentCreateRequest``, ``normalize_agent_create``, the roster
                  (read through ``config``, a stores package) and its
                  spellings, ``honest_default_display_name``
phases    stores  placement payload / slot / policy, ``run_skills_phase``,
                  ``_reply``, ``compensate_failed_placement``
perform   lanes   ``perform_agent_create``
========  ======  ============================================================

Entry points and the modules an agent opens: ``perform_agent_create`` (both
lanes) — perform, request, phases; ``normalize_agent_create`` /
``require_known_persona`` / the roster spellings — request;
``run_skills_phase`` (the resume lane) — phases, request;
``placement_slot_for`` (``serve_rpc/agent.py``) — phases;
``roster_unavailable_outcome`` — outcome.

Stores written (through their own doors, never here): the persona-instance
roster, the office actor, the agent-create reservation receipt, and the
instance's skill overrides. Siblings ``agent_create_phases`` and
``agent_create_reservations`` stay modules of their own.

Every name an importer or a test takes from ``agent_runtime.agent_create`` is
re-exported below, so no importer changes with the package.
"""

from __future__ import annotations

# The names the single file bound by import, kept as package attributes: a
# test reads a refusal's reason constant off ``agent_create`` by name.
from ..models import (  # noqa: F401
    PLACEMENT_ID_NOT_DISCRIMINABLE_REASON,
    looks_like_deliberate_placement,
    placement_id_not_discriminable_message,
)
from .outcome import (  # noqa: F401
    AgentCreateInvalid,
    AgentCreateOutcome,
    AgentCreateRefusal,
    AgentCreateSkillsRefused,
    DEFAULT_AGENT_FOLDER,
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    PERSONA_NOT_FOUND_REASON,
    PERSONA_ROSTER_UNAVAILABLE_REASON,
    PHASE_INSTANCE,
    PHASE_PLACEMENT,
    PHASE_SKILLS,
    PersonaRosterUnavailable,
    _RESERVATION_ROLLED_BACK,
    _SKILLS_RETRY_SENTENCE,
    _refused,
    _skills_refusal,
    persona_roster_unavailable_message,
    roster_unavailable_outcome,
)
from .request import (  # noqa: F401
    AgentCreateRequest,
    MAX_SKILLS,
    PERSONA_CHOICE_LIST_LIMIT,
    _persona_is_unknown,
    _placeable_persona_choice_text,
    _position,
    _skills,
    accepted_persona_spellings,
    honest_default_display_name,
    mint_placement_id,
    normalize_agent_create,
    persona_not_found_message,
    persona_roster,
    require_known_persona,
    resolve_persona,
)
from .phases import (  # noqa: F401
    _inherited_skills_ack,
    _live_actor,
    _observed_skills,
    _reply,
    _stamp_fresh_skills,
    compensate_failed_placement,
    placement_actor_payload,
    placement_position_policy,
    placement_slot_for,
    run_skills_phase,
)
from .perform import (  # noqa: F401
    perform_agent_create,
)

__layer__ = "lanes"
