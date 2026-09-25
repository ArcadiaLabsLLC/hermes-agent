"""Selective, declared, per-run MCP admission for harness-lane persona runs.

Why this module exists
----------------------
``mcp_lane`` (R0) made one thing honest: the harness / mission-chat lane never
runs ``discover_mcp_tools()``, so a persona whose profile DECLARES MCP servers
gets none of their tools there, and now says so in a typed
``mcp_not_registered_on_lane`` row instead of reporting ``[]``.

This module is R1 of the follow-on: turning that honest refusal into an honest
ADMISSION for a narrow, declared, config-flagged set of personas — so a QA
persona that already declares ``launcher_qa`` in three places can actually run
``mcp__launcher_qa__*`` tools AS ITSELF on the mission-chat lane, with its
chats, trace and roster presence all native.

Design (canonical): ``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/mission-chat-mcp-admission.md``.
Read that before changing anything here.

The invariants this module exists to hold
-----------------------------------------
1. **The lane blanket never flips.** ``hermes_cli/main.py::_AGENT_COMMANDS`` is
   untouched and ``discover_mcp_tools()`` is never called from here. Admission
   is per-RUN and per-PERSONA, driven by ``register_mcp_servers({name: cfg})``
   for an explicitly resolved subset — the same per-session mechanism
   ``acp_adapter/server.py::_register_session_mcp_servers`` already uses.
2. **The profile declaration is the admission authority.** A persona can admit
   only servers declared by its backing profile. A profile that declares none
   admits none; role names do not narrow or widen that data-owned set. Machine
   resolution and permission-mode filtering may still narrow it.
3. **``unbounded`` must never cross the declared set.** The chat lane's
   ``unbounded`` mode USED to resolve ``all_registered_toolsets()`` — which, in
   a long-lived multi-persona harness process, includes another persona's
   admitted MCP toolsets. Since S0a A1 (2026-09-03) both modes resolve the
   persona's own declaration (``personas.declared_lane_toolsets``), so no
   foreign ``mcp-*`` name reaches the scope in the first place.
   ``scope_toolsets_to_admission`` is still applied AFTER permission-mode
   resolution and still strips every ``mcp-*`` toolset (and alias) this run was
   not admitted: the property must hold by construction, not by the shape of
   today's declarations. Since R2 the registry is ALSO empty between admitted
   runs (see below), so this is the third line of defence rather than the
   only one.
4. **Registration is single-flight and bounded.** ``tools.registry`` and
   ``tools/mcp_tool._servers`` are process-global and a serve process is
   multi-persona (``ThreadPoolExecutor(4)``), so two interleaved admissions
   against one global registry are refused (``mcp_admission_lane_busy``) rather
   than raced. A registration that outruns its budget degrades to
   ``mcp_admission_timeout`` and the turn continues without those tools.

5. **The registry scope belongs to the RUN, the transport belongs to the
   process.** :func:`teardown_mcp_admission` removes the admitted
   ``mcp-<server>`` tools (and, with the last tool, the toolset check and every
   alias pointing at it) at the end of every admitted run, while the connection
   in ``tools/mcp_tool._servers`` stays warm for the next one. Teardown never
   fails a finished turn: every fault is a typed ``mcp_admission_teardown_failed``
   row.
6. **An admitted run is bounded in CALLS, not only in time.** Single-flight
   bounds how many admissions may be in flight; the wall budget and the AS0
   liveness watchdog bound the turn's clock. Neither bounds how many times an
   admitted agent may call ``kill_launcher`` inside one turn. The per-run budget
   (:class:`McpCallBudget`, installed by :func:`admit_mcp_servers` over the
   registered handlers) does: past ``max_tool_calls_per_run`` every further
   admitted MCP call is REFUSED with a typed ``mcp_admission_budget_exhausted``
   row instead of dispatched. The turn is never killed — the agent keeps its
   non-MCP tools and can finish with what it already captured.
7. **The agent is told when it does NOT get what it declared.** A denial or
   degradation is rendered as one compact line
   (:func:`render_mcp_admission_line`) on the same volatile envelope tail the
   wall-budget line rides, so the model reads the truth in-band instead of
   improvising a workaround. Volatile on purpose — never hashed into the HUD
   revision.

R2: why teardown forced the registrar to change
-----------------------------------------------
R1 shipped no teardown, and the consequence was load-bearing: once a server was
admitted in a warm serve process its tools stayed in the process registry until
the process recycled, and a ``read_only`` admission FOLLOWING a
``profile_default`` one re-used the already-registered full surface, because
``register_mcp_servers`` short-circuits on connected servers
(``tools/mcp_tool.py`` — ``if not new_servers: return _existing_tool_names()``).
The registration-time tool filter therefore could not subtract; only
``blocked_tool_names`` kept the mutators out of the model's list.

Open question 2 of the design asked whether ``tools/registry.py`` supports
scoped removal. It does, so R2 takes the design's preferred shape — **tear down
the registry scope, keep the transport warm**. But that same short-circuit means
``register_mcp_servers`` alone can no longer re-register a torn-down warm server:
it would return ``_existing_tool_names()`` forever and the server would stay
tool-less. :func:`_default_registrar` therefore splits the admitted set:

* **warm** (already in ``_servers`` with a live session) ⇒ re-register straight
  off that session through the upstream ``_register_server_tools`` seam — no
  spawn, no handshake, and the per-run ``tools.include`` / ``tools.exclude``
  filter is applied to the already-listed tools;
* **cold** ⇒ ``register_mcp_servers({name: cfg})``, exactly as in R1.

Both paths run the filter, so ``read_only`` after ``profile_default`` now
subtracts AT REGISTRATION TIME rather than relying on ``blocked_tool_names``
(which stays, as defence in depth for a resident actor's cached tool list).

The warm path is the one place this module reaches for an upstream private. It
fails CLOSED — an unavailable seam registers nothing, which surfaces as a typed
``mcp_not_registered_on_lane`` denial rather than a silently full surface — and
``tests/agent_runtime/test_mcp_admission_r2.py`` pins the seam so upstream drift
is loud instead of silent.

The package map (program rule 16; layout sheet ``mcp_admission.md`` §1)
-----------------------------------------------------------------------

The seven invariants above are the map: resolution is pure (2-3), registration
is single-flight and bounded (4, 6), the registry scope belongs to the run and
the transport to the process (5), the agent is told (7). Modules, lowest layer
first; no module imports one above it (W0-G6)::

    agent_runtime/mcp_admission/
      __init__.py       lanes   this docstring + map; re-exports the importers' and the tests' names
      vocabulary.py     models  the MCP_* denial codes, LANE_MISSION_CHAT, the toolset prefix,
                                TRANSPORT_WARM / _COLD, the parked-wake bound, the read-only
                                tool tables, MCP_OPERATING_SKILLS, the two defaults
                                (a vocabulary module: exempt from the floor)
      outcomes.py       models  McpAdmissionDenial, McpAdmission, McpAdmissionOutcome,
                                McpTeardownOutcome, McpCallBudget; render_mcp_admission_line
      resolve.py        stores  resolution, pure (zero spawns): admission_config / _enabled,
                                resolve_mcp_admission, scope_toolsets_to_admission,
                                admitted_operating_skill_ids, admission_requirement_failures
      transport.py      stores  the process's warm transports, behind agent_runtime._upstream_doors:
                                _default_registrar, classify_admission_transport,
                                mcp_sdk_available, the live / parked reads, the parked wake,
                                the warm re-registration
      registration.py   lanes   the registry scope's two ends: admit_mcp_servers (the mutex,
                                the call budget's meter) and teardown_mcp_admission

    entry point                                           opens
    admit_mcp_servers / teardown_mcp_admission (runner)   registration -> transport -> outcomes
    resolve_mcp_admission (persona runtime, tool
      visibility, inspect, prewarm)                       resolve -> outcomes
    render_mcp_admission_line (persona runtime, mcp_lane) outcomes
    scope_toolsets_to_admission / admitted_operating_
      skill_ids / admission_requirement_failures          resolve -> outcomes

A monkeypatch lands where a name is BOUND (``_default_registrar`` is read by
``registration``; ``_PARKED_WAKE_TIMEOUT_SECONDS`` by ``transport``): patch the
binding module (``tests/_downstream/split_package_source.py::patch_where_bound``).
``resolve`` is ``stores`` in this commit only because ``admission_config``'s
lazy import names the ``config`` package map (``stores``); the CHANGE reads
``config.loader`` (``policy``) and ``resolve`` drops to ``policy``.
"""

from __future__ import annotations

# Reused from mcp_lane, not re-spelled (the file's own comment); re-exported.
from ..mcp_lane import MCP_NOT_REGISTERED_ON_LANE

from . import outcomes, registration, resolve, transport, vocabulary
from .outcomes import (
    McpAdmission,
    McpAdmissionDenial,
    McpAdmissionOutcome,
    McpCallBudget,
    McpTeardownOutcome,
    render_mcp_admission_line,
)
from .registration import (
    _ADMISSION_LOCK,
    admit_mcp_servers,
    teardown_mcp_admission,
)
from .resolve import (
    admission_config,
    admission_enabled,
    admission_requirement_failures,
    admitted_operating_skill_ids,
    resolve_mcp_admission,
    scope_toolsets_to_admission,
)
from .transport import (
    _current_mcp_servers,
    _default_registrar,
    _is_parked,
    _live_mcp_sessions,
    _wake_parked_servers,
    classify_admission_transport,
    mcp_sdk_available,
)
from .vocabulary import (
    LANE_MISSION_CHAT,
    MCP_ADMISSION_BUDGET_EXHAUSTED,
    MCP_ADMISSION_DISABLED,
    MCP_ADMISSION_LANE_BUSY,
    MCP_ADMISSION_TEARDOWN_FAILED,
    MCP_ADMISSION_TIMEOUT,
    MCP_OPERATING_SKILLS,
    MCP_READ_ONLY_SUBSET_UNKNOWN,
    MCP_SDK_UNAVAILABLE,
    MCP_SERVER_NOT_CONFIGURED,
    READ_ONLY_ALLOWLIST_PROFILE,
    READ_ONLY_EXCLUDED_TOOLS,
    READ_ONLY_INCLUDED_TOOLS,
    TRANSPORT_COLD,
    TRANSPORT_WARM,
    _PARKED_WAKE_TIMEOUT_SECONDS,
)

__layer__ = "lanes"

