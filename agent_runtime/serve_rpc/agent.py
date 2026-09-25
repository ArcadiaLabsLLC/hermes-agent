"""``runtime.agent.create`` / ``retire`` — the two agent lifecycle verbs.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_agent_create",
    "_runtime_agent_retire",
]


# ── runtime.agent.create ─────────────────────────────────────────────────────


@method("runtime.agent.create", tier=TIER_CONSOLE)
def _runtime_agent_create(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE call places an agent: roster row, chat root and placement together.

    Params: ``persona_id``, ``workspace_id`` and ``idempotency_key`` (required);
    ``position: [x, y]``, ``skills: [id, ...]``, ``display_name``,
    ``placement_id``, ``realm_id``, ``folder``, ``correlation_id`` (all
    optional).

    ``position`` ABSENT (omitted or ``null``) means the client did not aim, and
    the service resolves the slot through ``agent_runtime.office_layout_policy``
    — the same lattice the launcher predicts with, pinned across the two repos
    by ``tests/fixtures/office_layout/cases.json`` (plan D2). Present, it is
    taken verbatim, exactly as before.

    ``skills`` ABSENT leaves the new instance inheriting its persona's skills; a
    list assigns ``skill_overrides`` at the instance tier after the placement,
    installing and hash-verifying every canonical id first (plan D5). It rides
    the RPC params rather than a CLI-only flag precisely so a remote connector,
    which can never run the install's CLI, gets the whole verb over ``call``.
    Two refusals are its own — ``skill_unresolved`` (-32602, with ``data.skill``
    and ``data.status``) and ``skill_install_diverged`` (-32000, with both
    hashes) — and both carry ``phase: "skills"`` with ``rolled_back: false``:
    the agent is PLACED and kept, and the same ``idempotency_key`` resumes the
    phase.

    Result::

        {persona_instance_id, persona_id, placement_id, display_name,
         default_chat_session_id, actor_key, revision, workspace_id,
         position: [x, y], actor: {...},
         skills: {assigned: [...], installed: [{skill, changed, installed_hash}]},
         actor_fresh: bool,
         phases: {instance_ms, placement_ms, skills_ms, total_ms},
         idempotent_replay}

    On an ``idempotent_replay`` the ``actor``/``revision``/``position`` are
    RE-READ off the live row rather than echoed from the receipt — the recorded
    ones can be arbitrarily old, and a client that adopts them would adopt a
    stale ``revision`` into its ``expect_revision`` bookkeeping. ``actor_fresh``
    is ``false`` exactly when that re-read could not be made (the actor was
    archived, the surface is gone), and the recorded row is then returned
    unchanged rather than invented.

    ``actor_key``/``revision`` mirror ``runtime.office.upsert``'s light ack on
    purpose, so the launcher's existing prediction and ``expect_revision``
    bookkeeping keeps working with no new decoder.

    ``position`` is what was WRITTEN — policy or verbatim — and ``actor`` is the
    row as STORED, in the SAME item shape ``runtime.office.get`` renders
    (``office_models.office_actor_wire_row``, which that method's projection now
    also flattens through). Both keys are ADDITIVE: an old client ignores them,
    ``RPC_CONTRACT_VERSION`` does not move, and no name joins the manifest's
    ``methods`` list.

    UC-H1 — this is a TRANSLATION SHIM and nothing else
    ---------------------------------------------------
    The sequence (reserve → mint → place → compensate/resume) lives in
    ``agent_create.perform_agent_create``, which is the same function
    ``harness agent create`` calls with no serve in the picture. Everything
    below is JSON-RPC envelope work: the reply dict and every ``data.reason``
    string come out of the service unchanged, because the launcher's
    ``missionAgentCreateReasonFrom`` decoder is the fielded consumer that pins
    them. If a refusal string ever needs to change, it changes in the service —
    a second spelling here would be the copy the hoist exists to abolish.

    Note the deliberate absence of a ``try``: ``KeyboardInterrupt`` and every
    other ``BaseException`` must keep propagating exactly as they did inline,
    since the crash-between-the-two-writes property is asserted by letting one
    escape.
    """

    from agent_runtime.agent_create import perform_agent_create

    # ``context.caller`` travels INTO the service (Stage A6): the front-door
    # gate above has already refused a caller without the console tier, and the
    # service checks the same predicate again with the same caller. That is the
    # point of a backstop — the guarantee stops being a property of this
    # dispatcher and becomes a property of the verb. Passing the caller rather
    # than a "the gate already ran" flag is what keeps it non-bypassable: a flag
    # is something a caller could eventually set.
    outcome = perform_agent_create(
        params, caller=context.caller if context is not None else None
    )
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)


# ── runtime.agent.retire ─────────────────────────────────────────────────────


@method("runtime.agent.retire", tier=TIER_CONSOLE)
def _runtime_agent_retire(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE call retires an agent: the roster row AND every actor bound to it.

    Params: ``persona_instance_id`` (required); ``reason``, ``requested_by``,
    ``correlation_id`` (optional).

    Result::

        {persona_instance_id, persona_id, display_name, mode, reason,
         requested_by, archive_path, archive_dir, archived_actor_keys: [...],
         office_archive_failures: [{actor_key, workspace_id, error}],
         already_retired, correlation_id?}

    ``correlation_id`` (S8b) rides onto the ``office.actor.removed`` event and
    the ``state.patched`` remove row this call produces, and is echoed on the
    ack when sent. Until it existed this was the ONLY level-mutating verb with
    no gesture token, so a launcher's create half and delete half could not be
    joined by one grep — see ``agent_retire.perform_agent_retire``.

    The INVERSE of ``runtime.agent.create``, and the join its absence left
    unmade: the launcher removed a deliberate placement through two unjoined
    lanes (a ``persona.instance.retire`` argv capability AND
    ``runtime.office.remove``), so a half-state — actor archived with the row
    still live, or the reverse — was representable and nothing detected it. One
    call now archives both halves, and ``archived_actor_keys`` /
    ``office_archive_failures`` make the office half — best-effort inside the
    store, and until plan D7 also SILENT — visible on the ack.

    Idempotent under retry: a second retire of an archived id answers the same
    ack with ``already_retired: true`` rather than ``not_found``, because a
    remote client that lost the first ack must be able to ask again.

    Refusals are ``PersonaInstanceRetireError``'s codes one-to-one:
    ``not_found`` → ``ERR_NOT_FOUND``; ``canonical_persona_channel`` /
    ``instance_active`` → ``ERR_CONFLICT`` with ``data.reason`` carrying the
    code verbatim. (The two assignment refusals this list carried until AX2 left
    with the store guards that raised them, 2026-08-31.)

    **Authorization scope (placement plan §A.11, owner decision D10-iv):
    ``console``.** It mutates the level exactly as ``runtime.office.*`` does, and
    it is deliberately NOT on any peer-tier allowlist — an agent on install A
    never retires an agent on install B; a remote OPERATOR (device tier) does.

    A TRANSLATION SHIM and nothing else, exactly like ``_runtime_agent_create``:
    the sequence lives in ``agent_retire.perform_agent_retire``, which is the
    same function ``harness agent retire`` and ``harness persona instance
    retire`` call with no serve in the picture. Adding this name to the manifest
    GROWS the set without moving ``RPC_CONTRACT_VERSION`` — a manifest is a set
    plus an integer, and the integer moves only when an existing method's shape
    changes incompatibly.
    """

    from agent_runtime.agent_retire import perform_agent_retire

    # Stage A6's backstop, exactly as ``_runtime_agent_create`` threads it.
    outcome = perform_agent_retire(
        params, caller=context.caller if context is not None else None
    )
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    return ok(rid, outcome.result)
