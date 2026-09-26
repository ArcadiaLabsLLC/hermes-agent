"""Runtime situational HUD — the single projection the operator's Mission Control
runtime HUD strip and the agent's chat turn both render, so operator and agent
reason from the identical picture ("parity so the AI and I are on the same page").

The launcher `MissionRuntimeHudStrip` shows the operator: the daemon pulse
(state · loop · beat · next-wake), the scope (realm · workspace), the bound
mission (title · state · threads), the selected lane (identity · liveness ·
steer handle), and the on-level roster.
Historically none of that reached the model: the mission-chat turn composed only
identity + rules + optional surface/skill prompts, so the agent was blind to
everything the operator saw.

This module is the one authority. `resolve_situational_hud` assembles the typed
snapshot from already-loaded runtime facts (pure — no I/O, unit-testable);
`render_situational_hud_block` renders it into the compact ``## Runtime Situation``
prompt block injected into the chat turn. The snapshot exposes the same dict on
each per-instance prompt context so the launcher renders exactly what is fed.

The stage/QA-gate ``mission_hud`` slice is GONE (S19). Mission context is now
limited to the persisted lane ``goal_id`` and the count of addressable lanes
sharing it; retired task-store title/state projections are not reconstructed.

Two delivery lanes, one authority
---------------------------------
The HUD has a HASHED BODY and a VOLATILE TAIL, and which one a fact rides is a
contract, not a style choice:

* **Body** — `render_situational_hud_block`. Stable facts (scope, mission, lane,
  steering, roster). Hashed into `situational_hud_revision`, so an unchanged
  picture is delivered as a compact ``unchanged`` stub instead of a re-snapshot.
* **Tail** — `render_runtime_context_envelope(volatile_content=…)`, emitted on
  EVERY delivery (snapshot, unchanged, and unavailable alike). Facts that must
  be true THIS turn: the wall budget (`turn_budget.render_turn_budget_line`),
  the MCP admission denials (`mcp_admission.render_mcp_admission_line`), and
  this lane's capability account (`render_capability_block` — what the chat-lane
  cost policy dropped and what the terminal envelope will refuse). Which lane a
  fact rides is declared ONCE, as ``volatile`` on its :class:`HudField` row in
  ``HUD_FIELDS``; the revision hash and the body renderer both derive from that
  one declaration (:func:`stable_hud_fields`), so a cached body cannot show a
  stale countdown or a stale capability claim.

The tail itself is composed by ``agent_runtime.volatile_tail``: contributors
register by name with a byte budget, and an over-budget contribution is
truncated or dropped WITH an in-band note plus a typed accounting row — never
silently.

The package map (rule 16)
-------------------------
Entry points, and the modules an agent opens to follow each:

* the chat turn's HUD (``mission_chat_turn_context``) -> ``ambient`` ->
  ``hud`` -> ``fields``;
* the observability frame (``prompt_observability/snapshot_frame``) ->
  ``hud.resolve_situational_hud`` + ``ambient.installs_block``;
* the capability account (``chat_lane_bundle``) -> ``ambient`` ->
  ``capability``;
* the envelope round-trip (``persona_chat_history/curation``,
  ``persona_chat_continuity``, ``mission_chat_turn_context``) -> ``envelopes``.

Modules, lowest layer first (no module imports one above it — W0-G6):

==========  ======  =======================================================
module      layer   owns
==========  ======  =======================================================
fields      models  VOCABULARY/TABLE: ``HudField`` / ``HUD_FIELDS`` — the ONE
                    declaration of which lane a key rides;
                    ``stable_hud_fields``; the revision hash; the two caps
envelopes   policy  the two envelope grammars (runtime_context,
                    skill_preload): extract / render / delivery / revision /
                    split / ``EnvelopeCodec``
hud         policy  ``resolve_situational_hud`` and its block builders;
                    ``render_situational_hud_block`` (the hashed body)
capability  policy  ``resolve_capability_block`` + ``render_capability_block``
ambient     lanes   the I/O wrappers: ``situational_hud_for_instance``,
                    ``capability_block_for_persona``, the board digest, the
                    paired-install rows
==========  ======  =======================================================

Stores written: none (``ambient`` READS the persona, workspace, realm, board
and peer stores). The ``persona_runtime`` <-> ``runtime_hud`` cycle stays lazy
on both sides and lives in ``ambient`` only — no policy module names
``persona_runtime``.
"""

from __future__ import annotations

from agent_runtime.runtime_hud import (  # noqa: F401 — every family, lowest layer first
    fields,
    envelopes,
    hud,
    capability,
    ambient,
)
from agent_runtime.runtime_hud.fields import (
    CAPABILITY_HUD_KEY,
    HUD_FIELDS,
    SITUATIONAL_HUD_CAPABILITY_CAP,
    SITUATIONAL_HUD_ROSTER_CAP,
    HudField,
    is_volatile_hud_key,
    situational_hud_revision,
    stable_hud_fields,
)
from agent_runtime.runtime_hud.envelopes import (
    RUNTIME_CONTEXT_CODEC,
    RUNTIME_CONTEXT_DELIVERY_SNAPSHOT,
    RUNTIME_CONTEXT_DELIVERY_UNAVAILABLE,
    RUNTIME_CONTEXT_DELIVERY_UNCHANGED,
    SKILL_PRELOAD_CODEC,
    SKILL_PRELOAD_DELIVERY_SNAPSHOT,
    SKILL_PRELOAD_DELIVERY_UNCHANGED,
    ComposedUserRow,
    EnvelopeCodec,
    extract_runtime_context_envelope,
    extract_skill_preload_envelope,
    render_runtime_context_envelope,
    render_skill_preload_envelope,
    runtime_context_delivery,
    skill_preload_delivery,
    skill_preload_revision,
    split_composed_user_row,
)
from agent_runtime.runtime_hud.hud import render_situational_hud_block, resolve_situational_hud
from agent_runtime.runtime_hud.capability import render_capability_block, resolve_capability_block
from agent_runtime.runtime_hud.ambient import (
    capability_block_for_persona,
    installs_block,
    situational_hud_for_instance,
)

__layer__ = "lanes"

__all__ = [
    "CAPABILITY_HUD_KEY",
    "ComposedUserRow",
    "EnvelopeCodec",
    "HUD_FIELDS",
    "HudField",
    "RUNTIME_CONTEXT_CODEC",
    "RUNTIME_CONTEXT_DELIVERY_SNAPSHOT",
    "RUNTIME_CONTEXT_DELIVERY_UNAVAILABLE",
    "RUNTIME_CONTEXT_DELIVERY_UNCHANGED",
    "SITUATIONAL_HUD_CAPABILITY_CAP",
    "SITUATIONAL_HUD_ROSTER_CAP",
    "SKILL_PRELOAD_CODEC",
    "SKILL_PRELOAD_DELIVERY_SNAPSHOT",
    "SKILL_PRELOAD_DELIVERY_UNCHANGED",
    "capability_block_for_persona",
    "extract_runtime_context_envelope",
    "extract_skill_preload_envelope",
    "installs_block",
    "is_volatile_hud_key",
    "render_capability_block",
    "render_runtime_context_envelope",
    "render_situational_hud_block",
    "render_skill_preload_envelope",
    "resolve_capability_block",
    "resolve_situational_hud",
    "runtime_context_delivery",
    "situational_hud_for_instance",
    "situational_hud_revision",
    "skill_preload_delivery",
    "skill_preload_revision",
    "split_composed_user_row",
    "stable_hud_fields",
]
