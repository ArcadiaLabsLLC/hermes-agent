"""``perform_agent_create`` — the ONE create sequence both lanes call
(``runtime.agent.create`` and ``harness agent create``, UC-H1).
"""

from __future__ import annotations

from typing import Any

from .outcome import (
    AgentCreateInvalid,
    AgentCreateOutcome,
    AgentCreateSkillsRefused,
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    PHASE_INSTANCE,
    PHASE_PLACEMENT,
    _RESERVATION_ROLLED_BACK,
    _refused,
    _skills_refusal,
)
from .phases import (
    _inherited_skills_ack,
    _reply,
    _stamp_fresh_skills,
    compensate_failed_placement,
    placement_actor_payload,
    placement_position_policy,
    run_skills_phase,
)
from .request import normalize_agent_create

__layer__ = "lanes"




def perform_agent_create(
    params: dict[str, Any],
    *,
    updated_by: str = "operator",
    persona: Any | None = None,
    caller: Any | None = None,
) -> AgentCreateOutcome:
    """ONE call places an agent: roster row, chat root and placement together.

    Params: ``persona_id``, ``workspace_id`` and ``idempotency_key`` (required);
    ``position: [x, y]``, ``skills: [id, ...]``, ``display_name``,
    ``placement_id``, ``realm_id``, ``folder``, ``correlation_id`` (all
    optional).

    ``position`` ABSENT means the client did not aim, and the layout policy
    chooses the slot (D2 — :func:`placement_position_policy`, which documents
    where that read sits relative to ``office_lock``). Present, it is taken
    verbatim, exactly as it always was.

    ``skills`` ABSENT leaves the new instance's ``skill_overrides`` at ``None``
    (inherit the persona's, live). A list assigns it at the INSTANCE tier after
    the placement, behind two gates: every canonical id is installed and proven
    hash-equal to the repo package, and every id must resolve. See
    :func:`run_skills_phase` — including why a refusal there keeps the agent.

    Result::

        {persona_instance_id, persona_id, placement_id, display_name,
         default_chat_session_id, actor_key, revision, workspace_id,
         position: [x, y], actor: {...},
         skills: {assigned: [...], inherited: bool,
                  installed: [{skill, changed, installed_hash}]},
         actor_fresh: bool, skills_fresh: bool,
         phases: {instance_ms, placement_ms, skills_ms, total_ms},
         idempotent_replay}

    ``position`` is what was WRITTEN and ``actor`` is the row as STORED, in the
    same shape ``runtime.office.get`` renders. ``skills`` is what was assigned
    and what the install actually did. All of them are additive: an old client
    ignores them, and none of them moves ``RPC_CONTRACT_VERSION`` or the
    manifest's method list.

    On an ``idempotent_replay`` the actor is RE-READ rather than echoed from the
    receipt, so a client adopting it adopts the row as it is now
    (:func:`_reply`). ``actor_fresh`` is ``false`` when that re-read
    could not be made — the actor was archived, the surface is gone — and the
    recorded row is returned unchanged rather than fabricated.

    The ``skills`` block gets the SAME treatment (2026-09-02) and for the same
    reason: ``assigned`` mirrors ``PersonaInstance.skill_overrides``, which
    ``update_profile`` mutates, and ``installed[].installed_hash`` names bytes a
    later install displaces. Those two are re-read on a replay;
    ``inherited`` — a statement about the REQUEST — is not. ``skills_fresh``
    is the valve, present on every reply that carries a block and ``false``
    when the instance row could not be read.

    ``persona`` is the CLI's richer pre-resolved persona object, threaded to
    :func:`normalize_agent_create` so the argv lane's naming behaviour is
    preserved byte-for-byte; the RPC lane has no such object and passes ``None``.

    ``caller`` is the authorization BACKSTOP (Stage A6, plan H-H13) — the
    ``RpcCaller`` the transport minted, which ``params`` can never become. The
    scope-aware gate is and stays the RPC front door (Ruling A picked (b), and
    this does not move it); this is the assertion that a decision was made, so
    the verb cannot be reached by a caller the policy refuses even from a lane
    that forgot to ask. Omitted, the call is the local console — every existing
    caller is an operator at this install's own shell — and that grandfather is
    a VALUE, not an absent check (:func:`call_authorization.service_backstop`).

    Why one call and not two
    ------------------------
    The two-call flow awaits ``persona.instance.create`` on the argv lane and
    then, ≥600 ms later, flushes ``runtime.office.upsert`` on another. Two
    transports, two independent failures, no join — and BOTH half-states are
    reachable: an instance whose placement never lands (R#37), and a placement
    naming an instance the runtime never minted, which the office store accepts
    because it validates payload shape and class keys, not instance existence.
    Here the two writes happen inside one function milliseconds apart, so the
    stream producer's 200 ms settle joins them into one batch by construction
    rather than by luck.

    The durable ORDER is instance-first, and that is not arbitrary. A placement
    written first would BE the second half-state for as long as the mint took,
    and the launcher's codec refuses on principle to derive a binding for an
    actor that has none — so a crash there leaves an actor nothing can ever
    thread. Instance-first's failure mode is a roster row with no desk, which is
    both visible and retireable, and which the compensation below removes.

    What it deliberately does NOT do
    --------------------------------
    It does not make the create foldable and it is not a speed change; the batch
    carries exactly the events the two-call flow carries, which is what lets it
    inherit D3's foldable ``persona_instance`` create for free instead of
    colliding with it. It also does not move naming authority: an explicit
    ``display_name`` from the client still wins (decision D-A1), and an omitted
    one falls back through the ONE shared rule the argv lane uses
    (:func:`honest_default_display_name`) rather than through the store
    template, which would mint "Qa" where the operator expects "QA Agent".

    Every lock in the path is a cross-process FILE lock, so this is correct with
    or without a live ``harness serve`` beside it.

    Three phases, and only two of them are atomic
    ---------------------------------------------
    ``instance`` and ``placement`` are the pair the reservation joins: a failure
    in the second compensates the first away. ``skills`` is deliberately NOT in
    that join (D4). It runs after both writes are durable and after the receipt
    reads ``placed``, and its refusals stamp ``rolled_back: false`` because the
    agent they refuse for is standing, correct and messageable — only its skill
    assignment is owed. The cure is the SAME idempotency key, which re-enters at
    the skills phase alone.
    """

    import time

    from ..call_authorization import service_backstop

    # FIRST, and before ``normalize_agent_create``: a refusal here must be the
    # emptiest one on the method, and it is — nothing is read, nothing is
    # constructed, no reservation lock is taken. ``rolled_back: True`` is its
    # literal reading, spelled for the same reason the eight validation arms
    # below carry it (the launcher renders a missing stamp as "the placement
    # could not be undone").
    denied = service_backstop(caller, method="runtime.agent.create")
    if denied is not None:
        return _refused(
            ERR_HANDLER_FAILED,
            f"runtime.agent.create requires the {denied.tier} tier",
            {**denied.refusal_data(), "rolled_back": True},
        )

    from ..agent_create_phases import (
        CreateSubphases,
        log_create_subphases,
        timed_create_subphase,
        using_create_subphases,
    )
    from ..agent_create_reservations import (
        STATE_DONE,
        STATE_INSTANCE_MINTED,
        STATE_PLACED,
        STATE_ROLLED_BACK,
        AgentCreateReservationError,
        reserve_agent_create,
    )
    from ..errors import StaleRevision, SyncConflict
    from ..office_class_key_guard import ClassKeyedPlacementRefused
    from ..office_store import OfficeStore
    from ..persona_assignments import (
        PersonaInstanceStore,
        RetiredPersonaInstanceError,
    )
    from ..persona_chat_durability import PersonaChatPersistenceError

    started = time.monotonic()

    try:
        request = normalize_agent_create(params, persona=persona)
    except AgentCreateInvalid as exc:
        # ``rolled_back: True`` on EVERY arm of this except, and the claim is
        # structural rather than per-reason: :func:`normalize_agent_create` runs
        # before ``OfficeStore`` is even constructed, so there is no roster row,
        # no chat root, no placement and no reservation receipt for any of its
        # eight refusals to have left behind. Its own docstring is the guarantee
        # ("a refusal here provably wrote nothing").
        #
        # It was absent, and an absent stamp is not neutral: the launcher's
        # decoder reads a missing ``rolled_back`` as ``false`` and renders "the
        # placement could not be undone" — so every mistyped persona id told the
        # operator to go check the runtime for wreckage that could not exist.
        # ``workspace_not_found`` one arm below has carried the stamp since
        # 1da669d908 for exactly this reason; these arms refuse EARLIER than it
        # does.
        return _refused(
            ERR_INVALID_PARAMS, exc, {"reason": exc.reason, "rolled_back": True}
        )

    store = OfficeStore()
    # Before the reservation, and before any store write: an unknown workspace
    # is the ONE refusal that must leave no receipt behind, or a client fixing a
    # typo would be answered with its own stale error under the same key. Mirrors
    # ``runtime.office.upsert``'s refusal to lazily author a surface for a typo.
    if not store.surface_exists(request.workspace_id):
        # Inventoried on a throwaway store root, every path under
        # ``store_root()`` diffed across the call: this arm changes NOTHING —
        # not even the ``locks/agent_creates/<digest>.lock`` its siblings take,
        # because it refuses before ``reserve_agent_create`` is entered and the
        # lock lives inside that context manager. It is the emptiest refusal on
        # the method, and ``rolled_back: True`` is its literal reading.
        #
        # No ``phase``: the surface check runs before the mint is attempted, so
        # neither half of the sequence has a verdict to report. The launcher
        # documents ``null`` for exactly that, and its own taxonomy comment for
        # this reason already says "a CREATE refused for it wrote nothing".
        return _refused(
            ERR_NOT_FOUND,
            f"unknown workspace: {request.workspace_id}",
            {
                "reason": "workspace_not_found",
                "workspace_id": request.workspace_id,
                "rolled_back": True,
            },
        )

    try:
        with reserve_agent_create(
            idempotency_key=request.idempotency_key,
            persona_id=request.persona_id,
            workspace_id=request.workspace_id,
        ) as reservation:
            record = reservation.record

            if record.state == STATE_DONE:
                # The recorded reply, through THE builder with nothing observed
                # — so the actor is re-read and a client that adopts it adopts
                # the row as it is NOW, not as it was when this key first
                # completed (:func:`_reply`). Still no second write: the witness
                # for that is the receipt file and the actor's own revision in
                # the store, never this reply.
                return AgentCreateOutcome(
                    result={**_reply(record.result), "idempotent_replay": True}
                )
            if record.state == STATE_PLACED:
                # Both writes landed under this key; only the skills phase is
                # owed. Re-enter THERE and nowhere else — re-minting or
                # re-placing would be the duplicate-agent bug the ledger exists
                # to prevent.
                #
                # The recorded ack is NOT the reply, though. It is the ack the
                # FIRST attempt rendered, and the office actor has been mutable
                # ever since — an operator drags the agent while they go and
                # look up the skill id they mistyped, and the retry that fixes
                # the typo would otherwise answer with the coordinates and the
                # revision the row had before the drag. Same argument and the
                # same builder as the ``done`` arm above (:func:`_reply`),
                # because it is the same defect: S7's launcher ADOPTS this
                # actor.
                instance_id = record.persona_instance_id or ""
                if not instance_id or not record.result:
                    # A shape this code never writes: ``mark_placed`` always
                    # runs on a record that already carries both. Answered with
                    # the reason the module already spends on an unusable
                    # receipt rather than a new one, and NOT rolled back —
                    # whatever this receipt names may well be standing.
                    return _refused(
                        ERR_HANDLER_FAILED,
                        "agent-create reservation is at 'placed' but names no "
                        "instance or no recorded result",
                        {"reason": "reservation_corrupt", "rolled_back": False},
                    )
                skills_started = time.monotonic()
                result = _reply(record.result)
                # The CURRENT request's list, not the receipt's. The whole
                # point of the resume is that an operator who mistyped a skill
                # id fixes it and retries under the same key; answering with the
                # recorded list would refuse the corrected call for the old
                # typo, forever.
                requested = request.skills
                if requested is None:
                    skills_ack: dict[str, Any] = _inherited_skills_ack()
                else:
                    if list(requested) != list(record.skills or []):
                        reservation.mark_placed(result, skills=list(requested))
                    try:
                        skills_ack = run_skills_phase(
                            requested, instance_id=instance_id
                        )
                    except AgentCreateSkillsRefused as exc:
                        return _skills_refusal(exc, instance_id=instance_id)
                _stamp_fresh_skills(result, skills_ack)
                phases = dict(result.get("phases") or {})
                phases["skills_ms"] = int((time.monotonic() - skills_started) * 1000)
                phases["total_ms"] = int((time.monotonic() - started) * 1000)
                result["phases"] = phases
                reservation.mark_done(
                    result,
                    skills=list(requested) if requested is not None else None,
                )
                # ``False``: this attempt DID work — it ran the phase the first
                # one could not finish. ``idempotent_replay`` means "nothing
                # happened, here is the recorded answer", and that is the
                # ``done`` arm above, not this one.
                return AgentCreateOutcome(result={**result, "idempotent_replay": False})
            if record.state == STATE_ROLLED_BACK:
                # D-A3: the placement id is burned by the retirement tombstone,
                # so this key can never complete. Say so again rather than
                # inventing a different placement the client did not predict.
                return _refused(
                    ERR_CONFLICT,
                    "this create was already attempted and rolled back; "
                    "retry as a new gesture with a new idempotency_key",
                    {**record.failure, "rolled_back": True, "idempotent_replay": True},
                )

            instance_ms = 0
            if record.state == STATE_INSTANCE_MINTED:
                # Resume: the mint already happened (or its compensation could
                # not). Re-minting here is the duplicate-agent bug the whole
                # ledger exists to prevent.
                from dataclasses import replace as _replace

                request = _replace(
                    request, placement_id=record.placement_id or request.placement_id
                )
                try:
                    instance = PersonaInstanceStore().get(
                        record.persona_instance_id or request.persona_instance_id
                    )
                except Exception as exc:  # noqa: BLE001
                    # THE arm whose honest answer is the opposite of its
                    # siblings', and the reason this lane is a sweep rather
                    # than a one-line copy.
                    #
                    # Reaching here means ``record.state`` was
                    # ``instance_minted``, and that state is only ever written
                    # by ``mark_instance_minted`` (or ``mark_rollback_failed``,
                    # which deliberately keeps it) — the module's own "first
                    # durable write". So a receipt naming a roster row is on
                    # disk BEFORE this attempt begins, and this attempt does not
                    # remove it: inventoried on a throwaway root, the call
                    # changes nothing at all, and the ``instance_minted``
                    # receipt plus whatever the earlier attempt left are still
                    # there afterwards.
                    #
                    # ``rolled_back: True`` here would therefore be the same lie
                    # the absent field was telling, only pointed the other way:
                    # the operator would be told "nothing was written" while a
                    # receipt this key cannot get past sits on disk naming a row
                    # nothing can read. ``False`` is the truth, and it is also
                    # the value that makes the launcher publish
                    # ``persona_instance_id`` as ``orphanInstanceId`` (it reads
                    # that key only when ``rolled_back`` is not ``true``), which
                    # is exactly the id an operator needs.
                    #
                    # This lane is NOT a compensation site, and that is a
                    # decision rather than an omission. Retiring the row is
                    # impossible — it is the row we could not read — and marking
                    # the receipt ``rolled_back`` would BURN the placement id
                    # (D-A3: a rolled-back key is answered with its recorded
                    # refusal forever) over an instance that may simply be
                    # unreadable for a minute. Left at ``instance_minted`` the
                    # key stays resumable, which is why ``next_expected`` offers
                    # the same-key cure FIRST.
                    return _refused(
                        ERR_NOT_FOUND,
                        f"reserved instance is gone: {exc}",
                        {
                            "reason": "reserved_instance_missing",
                            "persona_instance_id": record.persona_instance_id,
                            "phase": PHASE_INSTANCE,
                            "rolled_back": False,
                            "next_expected": (
                                "this idempotency_key's receipt still names a minted "
                                "persona instance that cannot be read; restore that "
                                "instance and retry with the SAME idempotency_key to "
                                "resume the placement, or retire it and retry the "
                                "gesture with a NEW idempotency_key"
                            ),
                        },
                    )
            else:
                mint_started = time.monotonic()
                # W3-H1: ``instance_ms`` below is ONE number for everything in
                # this arm, and W3 arrived unable to say which of its half-dozen
                # cost blocks owned the ~2 s a first-of-session drop pays. This
                # recorder collects named spans from the sites inside
                # ``add_instance`` (and from the ``spawned_by`` write below) and
                # bills them to a LOG receipt — never to the ``phases`` block on
                # the result, which is a client-visible shape whose last
                # observability addition landed as a cross-stack fixture change.
                # See ``agent_create_phases``.
                subphases = CreateSubphases()
                try:
                    with using_create_subphases(subphases):
                        instance = PersonaInstanceStore().add_instance(
                            persona_id=request.persona_id,
                            placement_id=request.placement_id,
                            display_name=request.display_name,
                            default_display_name=request.default_display_name,
                            workspace_id=request.workspace_id,
                            realm_id=request.realm_id,
                        )
                except RetiredPersonaInstanceError as exc:
                    # ``add_instance`` decides this in ``assert_bindable``,
                    # which runs before ``_durable_chat_root`` and before
                    # ``open_chat`` — "every refusal this bind can raise is
                    # decidable without writing, so it is decided before the
                    # root is made durable" (``persona_assignments.py``). The
                    # reservation record is still unwritten here: the three
                    # states that mean "on disk" are all handled above, so this
                    # branch is only reached with a brand-new key.
                    #
                    # Inventoried against a REAL retirement tombstone (create,
                    # retire, re-create under a new key): the single path this
                    # refusal adds under ``store_root()`` is the empty
                    # ``locks/agent_creates/<digest>.lock`` every attempt takes.
                    # The tombstone that caused the refusal is older than the
                    # gesture, so it is not this refusal's residue.
                    return _refused(
                        ERR_CONFLICT,
                        exc,
                        {
                            "reason": "instance_retired",
                            "placement_id": request.placement_id,
                            "phase": PHASE_INSTANCE,
                            "rolled_back": True,
                        },
                    )
                except ValueError as exc:
                    # Same inventory, same reason: every ``ValueError``
                    # ``add_instance`` raises is raised from its validation
                    # prologue — a blank placement token, or a placement id that
                    # already belongs to another persona — all of it above
                    # ``assert_bindable`` and therefore above the first write.
                    # Inventoried with a REAL collision (``dev`` re-using
                    # ``qa``'s placement id), not just an injected raise: one
                    # empty lock file, nothing else.
                    return _refused(
                        ERR_INVALID_PARAMS,
                        exc,
                        {
                            "reason": "instance_invalid",
                            "placement_id": request.placement_id,
                            "phase": PHASE_INSTANCE,
                            "rolled_back": True,
                        },
                    )
                except PersonaChatPersistenceError as exc:
                    # The mint could not make this agent's chat root durable, so
                    # it bound NOTHING — ``_durable_chat_root`` raises on the way
                    # into ``open_chat``'s ``session_id`` argument, before the
                    # instance row is written. Nothing to compensate, therefore,
                    # and deliberately no half-created agent: the alternative
                    # this replaces was binding a phantom root and answering
                    # ``ok`` — the agent appeared in the office and every message
                    # to it was refused ``unknown_chat_session`` forever (live
                    # 2026-08-20).
                    #
                    # Same typed vocabulary as the argv open-chat lane's
                    # ``chat_session_persist_failed`` frame, so a launcher that
                    # already decodes that kind from ``mission-chat`` reads this
                    # refusal too.
                    #
                    # ``rolled_back: True`` — and it is the LITERAL truth, not a
                    # courtesy. Nothing was written under this key at all: this
                    # arm is reached before ``mark_instance_minted``, which
                    # ``reserve_agent_create`` names as "the first durable
                    # write", so not even the reservation receipt exists (there
                    # is no ``reserved`` state in that module; ``_VALID_STATES``
                    # is instance_minted/done/rolled_back). Inventoried on a
                    # throwaway store root: the only path this refusal leaves
                    # behind is the empty ``locks/agent_creates/<digest>.lock``
                    # every attempt takes, and there is no
                    # ``persona_instances/`` directory, no office actor and no
                    # reservation directory.
                    #
                    # Stamping it matters because the launcher's parser reads
                    # ``data.rolled_back`` off EVERY error frame and defaults it
                    # to ``false`` as a fail-safe
                    # (``mission_agent_create_rpc.dart``). Without the key this
                    # -32000 fell through to ``handlerRaised`` with
                    # ``rolledBack: false``, and the operator was told "the
                    # roster row could not be undone. Check the runtime." —
                    # sent to look for wreckage that does not exist. Same
                    # spelling as the sibling refusals
                    # (:func:`compensate_failed_placement` and the
                    # ``STATE_ROLLED_BACK`` replay arm above) because it is the
                    # field a client branches on and a second vocabulary for
                    # "nothing survives" is a field no client reads.
                    #
                    # ``next_expected`` does NOT ask for the same idempotency
                    # key. It used to, and that was unreachable advice: the only
                    # client on this lane mints a fresh micros-stamped key per
                    # gesture, deliberately, so a re-click is a new agent. Since
                    # no receipt was recorded under this key, same-key and
                    # fresh-key retries are the SAME operation and the key
                    # discipline the old sentence implied bought nothing.
                    from ..mission_chat_outcome import ChatErrorKind

                    return _refused(
                        ERR_HANDLER_FAILED,
                        exc,
                        {
                            "reason": str(ChatErrorKind.CHAT_SESSION_PERSIST_FAILED),
                            "persistence_operation": exc.operation,
                            "placement_id": request.placement_id,
                            "phase": PHASE_INSTANCE,
                            "rolled_back": True,
                            "next_expected": (
                                "restore canonical persona chat transcript storage "
                                "and retry the gesture; nothing was recorded under "
                                "this idempotency_key"
                            ),
                        },
                    )
                # The argv lane's own provenance stamp, matched so the two lanes
                # cannot be told apart by the row they leave. Deliberately NOT
                # ``updated_by``: that names the author of the office WRITE,
                # while this names who the agent was spawned by, and no
                # coordinator reaches either lane that calls this function.
                instance.spawned_by = "operator"
                with using_create_subphases(subphases), timed_create_subphase(
                    "spawned_by_write_ms"
                ):
                    instance = PersonaInstanceStore().update(instance)
                instance_ms = int((time.monotonic() - mint_started) * 1000)
                # Emitted here rather than beside the result: this is where the
                # mint's span CLOSES, and every arm between here and the return
                # is a placement failure whose cost belongs to ``placement_ms``.
                log_create_subphases(
                    subphases,
                    persona_id=request.persona_id,
                    instance_ms=instance_ms,
                )
                reservation.mark_instance_minted(
                    persona_instance_id=instance.id,
                    placement_id=request.placement_id,
                )

            placement_started = time.monotonic()
            # D2/M10: the aim if there was one, otherwise the policy — resolved
            # by the STORE, inside the office lock, against the exact actor set
            # this write lands beside. The two travel together on purpose: a
            # payload with no point and no policy is refused by the store, so
            # the pairing cannot come apart. See ``placement_position_policy``.
            payload = placement_actor_payload(
                request, display_name=instance.display_name, position=request.position
            )
            position_policy = (
                None if request.position is not None else placement_position_policy(request)
            )
            try:
                # CI-4's FREE half (EG-2.3): this method already reserved
                # ``correlation_id`` from birth and already echoes it on the
                # result, so the only hop it was missing is the one the office
                # store now takes — the placement's domain event and its paired
                # patch row. With this kwarg a create's OFFICE half joins the
                # same token as an ordinary drag, and the named partial-coverage
                # window (Plan D §V3) shrinks to the roster half alone. The 38
                # argv capability lanes stay deferred.
                #
                # The token is re-normalized inside the store: this method's own
                # parser admits up to 200 characters, which is looser than the
                # payload cap, so a long id degrades to "no id" rather than
                # riding the wire.
                actor = store.upsert_actor(
                    request.workspace_id,
                    payload,
                    updated_by=updated_by,
                    correlation_id=request.correlation_id,
                    position_policy=position_policy,
                )
            except ClassKeyedPlacementRefused as exc:
                # ``placement_actor_payload`` is instance-keyed by construction,
                # so the store's class-key fence can never fire from this
                # sequence AS IT STANDS — and a defence that is only correct "by
                # construction" is one refactor away from being absent, so this
                # arm exists and is tested by injecting the payload shape that
                # refactor would produce (EG-6.6). It is a compensated refusal
                # like every other placement failure: the roster row this method
                # just minted must not outlive the placement it was minted for.
                #
                # ``placement_reason`` keeps the string it has always spent, and
                # the fence's own evidence rides beside it: a refusal that does
                # not name the actor it collided with is one nobody can act on,
                # and this lane had been dropping exactly that.
                data = compensate_failed_placement(
                    reservation,
                    instance_id=instance.id,
                    failure={
                        "reason": "placement_failed",
                        "phase": PHASE_PLACEMENT,
                        "placement_reason": "class_key_collision",
                        "workspace_id": request.workspace_id,
                        "reasons": exc.safe_details["reasons"],
                        "class_actor_key": exc.safe_details["class_actor_key"],
                        "conflicting_actor_keys": exc.safe_details["conflicting_actor_keys"],
                    },
                )
                return _refused(ERR_CONFLICT, "class-keyed placement refused", data)
            except (StaleRevision, SyncConflict, ValueError) as exc:
                data = compensate_failed_placement(
                    reservation,
                    instance_id=instance.id,
                    failure={
                        "reason": "placement_failed",
                        "phase": PHASE_PLACEMENT,
                        "placement_reason": type(exc).__name__,
                        "workspace_id": request.workspace_id,
                    },
                )
                return _refused(ERR_CONFLICT, exc, data)
            except Exception as exc:  # noqa: BLE001
                # An unexpected store fault is still a placement that did not
                # land, and the roster row must not survive it. The RPC
                # boundary would have turned this into a -32000 with the
                # instance stranded — which is R#37 with a nicer error code.
                data = compensate_failed_placement(
                    reservation,
                    instance_id=instance.id,
                    failure={
                        "reason": "placement_failed",
                        "phase": PHASE_PLACEMENT,
                        "placement_reason": type(exc).__name__,
                        "workspace_id": request.workspace_id,
                    },
                )
                return _refused(ERR_HANDLER_FAILED, exc, data)

            placement_ms = int((time.monotonic() - placement_started) * 1000)
            # Identity and timings — everything this call DECIDED. What it
            # OBSERVED (``actor``/``position``/``revision``/``actor_fresh``) is
            # stamped by :func:`_reply` below, from the actor the store just
            # returned, because that is the row the client adopts and this arm
            # is not allowed a private opinion about it.
            result: dict[str, Any] = {
                "persona_instance_id": instance.id,
                "persona_id": instance.persona_id,
                "placement_id": request.placement_id,
                "display_name": instance.display_name,
                "default_chat_session_id": instance.default_chat_session_id,
                "actor_key": actor.actor_key,
                "workspace_id": request.workspace_id,
                "phases": {
                    "instance_ms": instance_ms,
                    "placement_ms": placement_ms,
                    "total_ms": int((time.monotonic() - started) * 1000),
                },
            }
            result = _reply(result, observed=actor)
            if request.correlation_id:
                result["correlation_id"] = request.correlation_id

            # ── phase 3: skills (plan S4 / D5) ───────────────────────────────
            # Durable BEFORE the phase runs, and the receipt carries the request
            # — that is what makes a crash mid-install resumable at the skills
            # phase instead of re-entering the two writes above.
            skills_started = time.monotonic()
            if request.skills is None:
                # No opinion sent: ``skill_overrides`` stays ``None`` (inherit
                # the persona's, live) and NOTHING is written — not even an
                # empty list, which would be a different agent (D5, F13's
                # ``is not None`` contract). The ack block is still present and
                # empty, so a client reads one shape whatever was asked.
                skills_ack = _inherited_skills_ack()
            else:
                reservation.mark_placed(result, skills=list(request.skills))
                try:
                    skills_ack = run_skills_phase(
                        request.skills, instance_id=instance.id
                    )
                except AgentCreateSkillsRefused as exc:
                    return _skills_refusal(exc, instance_id=instance.id)
            _stamp_fresh_skills(result, skills_ack)
            result["phases"]["skills_ms"] = int(
                (time.monotonic() - skills_started) * 1000
            )
            # Re-stamped: ``total_ms`` was measured before the phase existed and
            # would under-report every create that installs a cold skill by
            # exactly the cost this plan set out to make visible.
            result["phases"]["total_ms"] = int((time.monotonic() - started) * 1000)
            reservation.mark_done(
                result,
                skills=list(request.skills) if request.skills is not None else None,
            )
            # S2c: tell every paired install our roster moved. Off-thread and
            # swallowed inside ``announce_roster_changed`` — a slow install on
            # the far side of a LAN must never be the reason a create takes five
            # seconds.
            from ..gateway_announce import announce_roster_changed

            announce_roster_changed()
            return AgentCreateOutcome(result={**result, "idempotent_replay": False})
    except AgentCreateReservationError as exc:
        # One ``except`` for three faults that do NOT agree about what survives
        # them — see :data:`_RESERVATION_ROLLED_BACK` for the per-code argument.
        # Answering them with one value would have been the same shortcut this
        # lane exists to undo, one level up.
        #
        # No ``phase`` on any of them: ``reserve_agent_create`` raises before the
        # mint is attempted, so neither half has a verdict.
        refusal_data: dict[str, Any] = {"reason": exc.code}
        if exc.code in _RESERVATION_ROLLED_BACK:
            refusal_data["rolled_back"] = _RESERVATION_ROLLED_BACK[exc.code]
        return _refused(
            ERR_CONFLICT
            if exc.code in {"idempotency_conflict", "create_lock_unavailable"}
            else ERR_HANDLER_FAILED,
            exc,
            refusal_data,
        )
