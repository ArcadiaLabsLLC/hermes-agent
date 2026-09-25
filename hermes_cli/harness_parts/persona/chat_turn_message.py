"""``mission chat message``: the turn's front door (target, caller, clarify binding, admission).

Separate because it resolves and admits a turn and hands the run to
``chat_turn_commit._mission_chat_commit_turn``.
"""

from __future__ import annotations

import time
import uuid
from agent_runtime.chat_session_scope import is_canonical_session_persistence
from agent_runtime.chat_turn_presence import ChatTurnPresence
from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
from agent_runtime.dispatch_session_policy import (
    derive_dispatch_title,
    resolve_dispatch_session_decision,
    session_established_payload,
)
from agent_runtime.persona_assignments import (
    PERSONA_INSTANCE_ID_PREFIX,
    PersonaInstanceStore,
    RetiredPersonaInstanceError,
    canonical_chat_instance_id,
    canonical_persona_instance_id,
    personas_equal,
    resolve_default_chat_session_id_for_instance,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_continuity import (
    PersonaChatBusyError,
    PersonaChatMintReceiptStore,
    persona_chat_root_lease,
)
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    default_persona_session_db as _default_persona_session_db,
)
from .chat_admission import (
    _bind_mission_chat_delivery_capability,
    _mission_chat_busy_outcome,
    _mission_chat_lease_provenance,
    _normalize_deferred_thread_policy,
    _registry_probe_rounds,
    _visibility_bundle_builds,
    _visibility_bundle_diff_cursor,
    _within_admitted_turn,
)
from .chat_events import _mission_chat_emit, _publish_persona_chat_send_refused_event
from .chat_request import (
    _mission_chat_caller_refusal,
    _mission_chat_retired_target_refusal,
    _resolve_mission_chat_clarify_binding,
    _retired_persona_instance_payload,
)
from .chat_session import _persona_chat_session_owner
from .chat_target import (
    _display_name_for_profile,
    _mission_chat_bare_persona_target,
    _mission_chat_target_decision,
    _persona_by_id,
    _resolve_mission_chat_persona_id,
)
from .chat_turn_commit import _mission_chat_commit_turn

__layer__ = "lanes"
__all__ = [
    "_cmd_mission_chat_message",
]


@_within_admitted_turn
def _cmd_mission_chat_message(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import (
        ChatErrorKind,
        ExecutionState,
        MissionChatDeferredFinalization,
        MissionChatTurnPlan,
    )
    from agent_runtime.mission_chat_phases import TurnPhaseMarks

    # ── the turn's monotonic anchor ────────────────────────────────────────
    # FIRST statement of the handler, ahead of the capability bind, the config
    # load and every resolution below, because everything below is admission
    # cost the operator is waiting through. The emitter's own ``ttft_ms`` clock
    # does not start until ~1,100 lines from here (after replay checks, the
    # native-history load, the turn-context build and the observability row),
    # so on a cold turn it cannot see the profile bootstrap at all — that gap
    # is what this anchor closes. ``ttft_ms`` is unchanged and still means what
    # it always meant; these phases are a superset of it.
    #
    # One ``time.monotonic()`` read. See ``agent_runtime.mission_chat_phases``
    # for the honesty contract every mark below obeys.
    turn_phases = TurnPhaseMarks()
    # Baseline for Stage 4's ``registry_probe_rounds``. The registry's counter
    # is cumulative and thread-local (serve reuses pooled threads across turns),
    # so the turn's number is a DELTA and the near end of it has to be sampled
    # here, on the turn's own thread, before any of the turn's work runs.
    turn_phases.set_baseline("registry_probe_rounds", _registry_probe_rounds())
    # Same reasoning, one layer up: the chat-lane visibility bundle's build
    # counter is thread-cumulative too, and its turn number is the delta across
    # the same window. Sampled here so the baseline predates the turn-context
    # build, which is where the first bundle lookup happens.
    turn_phases.set_baseline("visibility_bundle_builds", _visibility_bundle_builds())
    # CP-7's near end, sampled in the same breath and for the same reason: the
    # bundle module's moved-component list is thread-cumulative, so this turn's
    # names are the tail since here. The counter says a rebuild HAPPENED; this
    # is what says which keyed input moved — the question fifteen live turns
    # since 2026-08-29 have carried a ``1`` for and never answered.
    _bundle_diff_cursor = _visibility_bundle_diff_cursor()
    # Per-request capability binding, at the very top so every path below —
    # including the refusals — runs with the truthful answer bound.
    _bind_mission_chat_delivery_capability()
    _normalize_deferred_thread_policy(args)
    cfg = load_agent_runtime_config()
    try:
        normalized_persona = _resolve_mission_chat_persona_id(
            args.persona_id, getattr(args, "persona_instance_id", None)
        )
    except ValueError as exc:
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.REJECTED,
            "error_kind": ChatErrorKind.UNSUPPORTED_PERSONA,
            "error": safe_assignment_text(str(exc), limit=240),
            "persona_id": safe_assignment_token(args.persona_id),
            "next_expected": "pass a configured persona id, profile:<name>, or a known personainst_* instance id",
        }
        _mission_chat_emit(args, data)
        return 2

    # Relay-chain guard at the canonical persona chokepoint. The chain is
    # explicit envelope provenance (relay_chain / relay_deadline_epoch), so
    # every transport into this handler gets the same depth/cycle/budget
    # answer; agent_chat_send carries the envelope but does not re-decide.
    from agent_runtime import relay_policy

    relay_chain_in = relay_policy.normalize_chain(getattr(args, "relay_chain", None))
    relay_deadline = relay_policy.parse_deadline_epoch(getattr(args, "relay_deadline_epoch", None))
    relay_decision = relay_policy.evaluate_relay(
        chain=relay_chain_in,
        target_persona_id=normalized_persona,
        deadline_epoch=relay_deadline,
    )
    if not relay_decision.allowed:
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.REJECTED,
            "error_kind": relay_decision.error_kind,
            "error": safe_assignment_text(relay_decision.reason, limit=400),
            "persona_id": normalized_persona,
            "relay_chain": list(relay_decision.chain),
            "next_expected": "answer your caller directly; do not relay onward on this chain",
        }
        _mission_chat_emit(args, data)
        return 2
    # Chain for THIS turn: envelope chain + the persona now speaking. Seeded
    # into the ContextVars around the model turn so the turn's own
    # agent_chat_send calls (tool workers run under copy_context) inherit it.
    turn_relay_chain = relay_decision.chain
    persona = _persona_by_id(cfg, normalized_persona)
    if persona is None:
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.REJECTED,
            "error_kind": ChatErrorKind.UNSUPPORTED_PERSONA,
            "error": f"unknown persona {safe_assignment_token(args.persona_id)}",
            "persona_id": safe_assignment_token(args.persona_id),
            "next_expected": "persist the persona, use profile:<name>, or address a known personainst_* instance",
        }
        _mission_chat_emit(args, data)
        return 2

    # chat-turn-prep Stage 4: MEASURE the SessionDB open before deciding to pool
    # it. H3 (§3) confirmed in CODE that every turn constructs a fresh
    # ``SessionDB`` whose writer-path constructor runs ``_init_schema`` (DDL +
    # FTS probe + column reconcile) plus the WAL checks, and confirmed just as
    # plainly that its millisecond share of the ``request_received →
    # context_built`` span was never measured. The pooling remedy is gated on
    # this number, not on the code shape — the plan's own §6 rule about remedies
    # measured against numbers nobody can re-take applies to its own stages.
    #
    # ``time.monotonic`` for the same reason ``mission_chat_phases`` uses it: an
    # NTP step must not be able to poison a duration. The value is folded into
    # the durable record's ``profile_timing`` block below; a turn that fails
    # here never reaches that fold, so the key stays ABSENT rather than
    # reporting the cost of an open that did not succeed.
    _session_db_open_started = time.monotonic()
    _session_db_open_ms: int | None = None
    try:
        session_db = _default_persona_session_db()
    except PersonaChatPersistenceError as exc:
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.FAILED,
            "error_kind": ChatErrorKind.CHAT_SESSION_DB_UNAVAILABLE,
            "persistence_operation": exc.operation,
            "error": str(exc),
            "persona_id": normalized_persona,
            "next_expected": "restore canonical persona chat transcript storage and retry the message",
        }
        _mission_chat_emit(args, data)
        return 2
    _session_db_open_ms = max(
        0, int((time.monotonic() - _session_db_open_started) * 1000)
    )
    instance_store = PersonaInstanceStore()
    from agent_runtime.auxiliary_chat import is_auxiliary_chat
    if not is_auxiliary_chat(getattr(args, "persona_instance_id", None), getattr(args, "session_id", None)):
        instance_store.ensure_for_personas(ensure_persisted_personas(cfg))
    # Auxiliary sessions were admitted against an existing exact instance.
    # They must not run the catalog's repairing projection writer (including
    # display/profile fields) while another operator may be editing that row.
    # Canonicalize a caller-supplied instance id at THIS boundary (the same
    # chokepoint open_chat uses), so an instance-shaped target can never mint a
    # variant row.
    #
    # An instance-shaped `--persona` (`personainst_qa_agent_f24601ba`) IS a
    # caller pin, and it arrives in the persona slot constantly (Mission Control
    # payloads, agent @handle targeting, legacy SessionDB rows).
    # `_resolve_mission_chat_persona_id` above canonicalizes it DOWN to the
    # persona id so every persona-keyed lookup works — and the instance half
    # used to be dropped right here, leaving the caller's explicit pin to be
    # re-decided by the bare-persona placement resolver below. Recover the pin
    # at this same chokepoint (no second resolver: `canonical_persona_instance_id`
    # remains the one derivation authority) so an explicit @handle is
    # authoritative BEFORE "placements shadow canonical" runs — which is what
    # that ruling already documents: it never fires when the caller already
    # disambiguated with a `personainst_*` target.
    requested_instance_id = getattr(args, "persona_instance_id", None)
    if not safe_assignment_token(requested_instance_id):
        raw_persona_target = safe_assignment_token(getattr(args, "persona_id", None))
        if raw_persona_target.startswith(PERSONA_INSTANCE_ID_PREFIX):
            requested_instance_id = raw_persona_target
    persona_instance_id = canonical_persona_instance_id(
        requested_instance_id, persona_id=normalized_persona
    )
    session_id = safe_assignment_text(getattr(args, "session_id", None), limit=200)
    # What the CALLER named, before anything on this turn overwrites it. Kept so
    # the settlement can tell "they answered in the right thread because they
    # named it" from "they inherited it" — the adoption signal this whole
    # binding is measured by.
    #
    # It used to be stashed on `args._stated_session_id`, because the lease
    # re-entry re-ran this line AFTER both the clarify bind and the
    # omitted-session mint had written a session back onto `args.session_id` —
    # so the second pass read every sticky continuation as a thread the caller
    # had named. The plan/commit split runs this line exactly once, so a plain
    # local is now the honest carrier.
    stated_session_id = session_id
    # CLARIFY CONTINUITY. Resolved HERE — after the caller's session id is read,
    # BEFORE the target decision below — and both consequences are free:
    #
    #   1. a ticket-supplied session flows through the EXISTING
    #      `unknown_chat_session` / `foreign_chat_session` guards below, so a
    #      token can never smuggle in a session the caller could not have named
    #      legitimately (a token for another instance's thread is refused as
    #      `foreign_chat_session`, reached without a line of new guard code);
    #   2. a bound turn never reaches the omitted-session branch, so it never
    #      mints, never repoints the instance's default-thread pointer, and
    #      never runs the pre-mint gate.
    #
    # Resolved ONCE. It used to be stashed on `args._clarify_binding` because
    # the handler re-entered itself to take the chat-root lease, and by then
    # `args.session_id` had been rewritten — a second pass would rediscover "the
    # caller named a session", report the turn as a plain `explicit_session_id`
    # continuation, and settle the ticket TWICE. The plan/commit split retires
    # the re-entry, so the local is the whole story.
    clarify_binding = _resolve_mission_chat_clarify_binding(
        args, session_id=session_id
    )
    clarify_session_id = (
        safe_assignment_text((clarify_binding or {}).get("bound_session_id"), limit=240)
        if (clarify_binding or {}).get("bound_via") == "clarify_token"
        else ""
    )
    if clarify_session_id:
        session_id = clarify_session_id
        args.session_id = clarify_session_id
    # How this turn's thread was established — typed, and carried in the reply
    # envelope so a dispatching agent can tell "this is a fresh task thread,
    # here is the one it superseded" from "this continued what we had". Decided
    # here for the explicit-session lane; re-decided by policy below when the
    # caller named no session.
    #
    # It used to be carried on `args._dispatch_session_established` because this
    # handler RE-ENTERED itself once to take the chat-root lease, and by then
    # the resolved session had been written back onto `args.session_id` — so a
    # second pass would rediscover "the caller named a session" and report every
    # freshly minted dispatch thread as a plain continuation. One pass now.
    session_established = None
    if session_id:
        # No `policy=`: an explicit session id outranks deployment policy, and
        # the resolver short-circuits before loading it — this lane runs on
        # every mission-chat turn and `mission_chat_dispatch_session_policy()`
        # parses the root config.yaml UNCACHED, to fill a field the
        # `explicit_session_id` reason never reads.
        session_established = session_established_payload(
            resolve_dispatch_session_decision(
                clarify_session_id=clarify_session_id or None, session_id=session_id
            ),
            fresh=False,
            predecessor_session_id=None,
        )
    # Sender identity for workspace-scoped target resolution: the chat-root
    # session of the agent that requested this send (agent-to-agent relay
    # threads it through the envelope; a bare operator CLI send omits it).
    requested_by_session = safe_assignment_text(
        getattr(args, "requested_by_session", None), limit=200
    )
    client_message_id = safe_assignment_text(
        getattr(args, "client_message_id", None), limit=200
    ) or f"agent-chat-send-{uuid.uuid4().hex[:12]}"
    # Written back so the serve lane and the turn store agree on the id a
    # generated fallback produced. (It also used to have to survive the lease
    # recursion; that recursion is gone.)
    args.client_message_id = client_message_id

    # Ambiguous-target guard at the canonical persona chokepoint (sibling of the
    # relay-chain guard above; same envelope, evaluated for every transport so an
    # instance-id target cannot dodge it). A BARE persona id names a persona, not
    # an instance; when the persona runs more than one live instance and the
    # caller pinned none, the omitted-session default below silently threads onto
    # the canonical primary and DROPS the message for every sibling (live
    # 2026-07-19: bare `qa` with two live `qa` instances landed only in
    # `personainst_qa`). Refuse with the candidate @handles so the caller can
    # retry against an exact instance. Never fires when the caller already
    # disambiguated (an explicit `persona_instance_id`, a `personainst_*` target,
    # or ANY caller-chosen session id — the operator console always carries an
    # instance-bearing session id, so its chats to every sibling keep working),
    # for a `profile:<name>` target, or for a single-instance persona.
    target_decision = _mission_chat_target_decision(
        instance_store=instance_store,
        normalized_persona=normalized_persona,
        raw_persona_id=getattr(args, "persona_id", None),
        persona_instance_id=persona_instance_id,
        session_id=session_id,
        relay_chain=turn_relay_chain,
        requested_by_session=requested_by_session,
    )
    if not target_decision.allowed:
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.REJECTED,
            "error_kind": target_decision.error_kind,
            "error": safe_assignment_text(target_decision.reason, limit=400),
            "persona_id": normalized_persona,
            "relay_chain": list(target_decision.chain),
            "candidates": [candidate.as_dict() for candidate in target_decision.candidates],
            "next_expected": (
                "re-send to a specific instance by the @personainst_ handle listed in candidates"
            ),
        }
        _mission_chat_emit(args, data)
        return 2

    if (
        session_id
        and is_canonical_session_persistence(session_db)
        and session_db.get_session(session_id) is None
    ):
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.REJECTED,
            "error_kind": ChatErrorKind.UNKNOWN_CHAT_SESSION,
            "error": f"unknown explicit persona chat root: {session_id}",
            "session_id": session_id,
            "next_expected": "open a server-minted chat root before sending",
        }
        # Pre-lease refusal: durably recorded the same way `chat_busy` is (see
        # `_publish_persona_chat_send_refused_event`'s docstring) — the send
        # never reaches the lease, so this is the only trace it leaves.
        _publish_persona_chat_send_refused_event(
            session_id=session_id,
            client_message_id=client_message_id,
            persona_id=normalized_persona,
            persona_instance_id=persona_instance_id,
            error_kind=ChatErrorKind.UNKNOWN_CHAT_SESSION,
        )
        _mission_chat_emit(args, data)
        return 2
    if session_id and is_canonical_session_persistence(session_db):
        owner = _persona_chat_session_owner(session_db, session_id)
        owner_instance = None
        try:
            owner_instance = instance_store.get(owner) if owner else None
        except Exception:
            owner_instance = None
        # ONE spelling authority on BOTH sides (``personas_equal``). This fence
        # used to compare ``safe_assignment_token(owner.persona_id)`` against
        # ``normalize_persona_or_template_id(caller_persona)`` — token form vs
        # colon form, two normalizers, one persona — so ``profile:alice`` could
        # never equal ``profile_alice`` and EVERY agent-to-agent reply delivery
        # for a profile persona was refused as foreign
        # (2026-08-24, dispatch-2540634d5cf3).
        owner_persona = getattr(owner_instance, "persona_id", None)
        # The PIN leg is an identity check on the very field ownership is
        # defined by: the chat root's owner IS an instance id. When the caller
        # supplies one it is authoritative about OWNERSHIP — but not about
        # WHOSE BRAIN RUNS. ``normalized_persona`` (not the owner's persona) is
        # what selected the persona, model and profile for this turn, so a pin
        # that proved ownership while the caller named a genuinely DIFFERENT
        # persona would run that persona's turn inside this instance's thread.
        # The pin therefore overrides the persona leg only where the persona
        # leg has nothing to say: an owner row whose persona is missing or
        # unreadable. See the F1 note in the guard tests.
        pin_proves_ownership = bool(persona_instance_id) and owner == persona_instance_id
        owner_persona_known = bool(safe_assignment_token(owner_persona))
        persona_ok = personas_equal(owner_persona, normalized_persona) or (
            pin_proves_ownership and not owner_persona_known
        )
        if (
            not owner
            or owner_instance is None
            or not persona_ok
            or (persona_instance_id and owner != persona_instance_id)
        ):
            data = {
                "ok": False,
                "capability_id": "mission.chat.message",
                "execution_state": ExecutionState.REJECTED,
                "error_kind": ChatErrorKind.FOREIGN_CHAT_SESSION,
                "error": f"explicit chat root is not owned by the target instance: {session_id}",
                "session_id": session_id,
                "persona_instance_id": persona_instance_id or None,
                "next_expected": "use the server-minted root returned for this exact persona instance",
            }
            # Pre-lease refusal — same durable record as `chat_busy`. See
            # `_publish_persona_chat_send_refused_event`'s docstring.
            _publish_persona_chat_send_refused_event(
                session_id=session_id,
                client_message_id=client_message_id,
                persona_id=normalized_persona,
                persona_instance_id=persona_instance_id,
                error_kind=ChatErrorKind.FOREIGN_CHAT_SESSION,
            )
            _mission_chat_emit(args, data)
            return 2
        persona_instance_id = owner
    if not session_id:
        # Omitted session (agent_chat_send dispatch lane, and any first-turn
        # open): the thread target is decided by policy below, not by this
        # branch. Under the default `new_per_dispatch` a dispatch MINTS its own
        # task-scoped thread; under `sticky` (or an explicit new_session=False)
        # it continues the target's current default thread. Either way the
        # session comes from the canonical resolve-or-mint chokepoint — never a
        # new random session per send, which orphaned the relay lane in
        # 2026-07-18 (unpointed session, invisible to the snapshot projection).
        # `open_chat` below repoints the instance's default pointer onto
        # whatever thread this turn established.
        #
        # BARE persona (no pin, no session): route through the "placements shadow
        # canonical" ruling — a single in-scope placement is the default target,
        # so the send lands on the deliberate placement instead of the plumbing
        # canonical row. The guard above already refused two-or-more in-scope
        # placements, so this resolves to at most one; with none it returns None
        # and the canonical channel is the reachability fallback.
        #
        # ONE instance identity for the turn: whatever resolves the root/mint
        # here is the instance `open_chat` BINDS below, so it is assigned back
        # onto `persona_instance_id` rather than kept as a second local. Keeping
        # them apart meant the bind received the RAW pin (`None` for a bare or
        # instance-shaped send), fell back to the canonical channel, and the
        # sibling-steal guard correctly refused the root this very turn had just
        # minted for the placement ("chat session
        # 'persona_chat_personainst_qa_agent_f24601ba_...' belongs to instance
        # 'personainst_qa_agent_f24601ba'; it cannot be bound onto
        # 'personainst_qa'") — refusing every placement-routed send, new-session
        # and continue alike. The explicit-session branch above already adopts
        # its resolved owner the same way; this is the omitted-session mirror.
        persona_instance_id = (
            persona_instance_id
            or _mission_chat_bare_persona_target(
                instance_store,
                normalized_persona=normalized_persona,
                requested_by_session=requested_by_session,
            )
            or canonical_chat_instance_id(normalized_persona, None)
        )
        # Fresh-vs-continue is decided by ONE authority
        # (agent_runtime.dispatch_session_policy), not by an inline
        # `not args.new_session` boolean: the flag is tri-state now (True /
        # False / unset) and "unset" must be answerable by deployment policy.
        # Default policy is new_per_dispatch — a dispatched task gets its own
        # task-scoped thread instead of accumulating in one mega-thread per
        # pair (which re-fed the whole transcript every turn). The CLI/serve
        # lane's argparse `--new-session` is store_true, so an operator console
        # send arrives as an explicit False and keeps continuing the target's
        # current default thread, exactly as before this policy existed.
        dispatch_decision = resolve_dispatch_session_decision(
            session_id=None,
            new_session=getattr(args, "new_session", None),
        )
        # Resolved UNCONDITIONALLY, even when we are about to mint: the thread
        # this dispatch supersedes is the lineage a later reader follows back
        # (recorded as `_dispatched_from`, reported as `predecessor_session_id`).
        # Read-only — `resolve_…` never mints.
        existing_root = resolve_default_chat_session_id_for_instance(
            instance_store,
            persona_id=normalized_persona,
            persona_instance_id=persona_instance_id,
        )
        if existing_root and not dispatch_decision.mint:
            session_id = existing_root
            session_established = session_established_payload(
                dispatch_decision, fresh=False, predecessor_session_id=None
            )
        else:
            # PRE-MINT GATE. The mint below is this turn's first DURABLE side
            # effect: a titled session row, and — once `open_chat` binds it —
            # a REPOINT of the instance's default-thread pointer. Under the
            # new_per_dispatch default, running it before the caller's own
            # arguments have been checked meant every refused or retried
            # dispatch littered an empty task thread AND stole the pointer that
            # `new_session:false` follows. So the refusals decidable from
            # `args` alone are evaluated FIRST. They need no session id, so
            # ordering them here costs nothing; their original, session-bearing
            # sites below stay put as defense in depth for the explicit-session
            # lane (which never mints).
            #
            # A RETIRED target is the same defect one layer out: `open_chat`
            # refuses it by raising, but the mint reaches `open_chat` only after
            # creating and titling the row, so the refusal landed one durable
            # thread too late — and outside the typed handler below, so it also
            # escaped as a traceback. It needs the store rather than `args`, so
            # it is its own read-only pre-flight, evaluated through the same gate.
            premint_refusal = _mission_chat_caller_refusal(
                args,
                persona_id=normalized_persona,
                persona_instance_id=persona_instance_id,
            ) or _mission_chat_retired_target_refusal(
                instance_store,
                persona_id=normalized_persona,
                persona_instance_id=persona_instance_id,
            )
            if premint_refusal is not None:
                # Only the retired-target arm of this gate is one of the three
                # pre-lease guard kinds this event exists for; the sibling
                # `_mission_chat_caller_refusal` arms (missing message,
                # invalid model override) are argument validation, not chat-
                # root ownership, and are not routed here.
                if premint_refusal.get("error_kind") == ChatErrorKind.RETIRED_PERSONA_INSTANCE:
                    _publish_persona_chat_send_refused_event(
                        session_id=session_id,
                        client_message_id=client_message_id,
                        persona_id=normalized_persona,
                        persona_instance_id=persona_instance_id,
                        error_kind=ChatErrorKind.RETIRED_PERSONA_INSTANCE,
                    )
                _mission_chat_emit(args, premint_refusal)
                return 2
            # A fresh thread is only navigable if it is NAMED: nine identical
            # "QA Agent chat" rows are worse than the mega-thread they replaced.
            # An explicit --title/`title` wins; otherwise a deliberate fresh
            # dispatch is titled after the task it carries. A first-ever STICKY
            # mint (the operator console's first message) keeps the durable
            # per-persona title, so that lane is unchanged.
            persona_thread_title = (
                f"{safe_assignment_text(getattr(persona, 'display_name', None), limit=120) or normalized_persona} chat"
            )
            requested_title = safe_assignment_text(getattr(args, "title", None), limit=120)
            mint_title = persona_thread_title
            if dispatch_decision.mint:
                mint_title = (
                    requested_title
                    or derive_dispatch_title(getattr(args, "message", None))
                    or persona_thread_title
                )
            try:
                receipt = PersonaChatMintReceiptStore().mint(
                    instance_store=instance_store,
                    session_db=session_db,
                    persona_id=normalized_persona,
                    persona_instance_id=persona_instance_id,
                    idempotency_key=(
                        safe_assignment_text(getattr(args, "idempotency_key", None), limit=240)
                        or f"send:{client_message_id}"
                    ),
                    title=mint_title,
                    dispatched_from={
                        "predecessor_chat_session_id": existing_root,
                        "requested_by_session": requested_by_session,
                    },
                )
            except RetiredPersonaInstanceError as exc:
                # What this handler guarantees is the TYPE. An unhandled raise
                # here was the untyped traceback the operator saw instead of a
                # refusal.
                #
                # What reaches it: a target already retired when the mint began
                # (a caller that skipped the pre-flight above by another road,
                # or a `retire` that landed in the gap between the pre-flight
                # and the mint), AND a `retire` that lands inside the mint lane
                # itself. Both now arrive with nothing left behind: the mint
                # asserts bindability before its first durable write and BINDS
                # before its first session-visible one, so a refusal from either
                # point precedes the titled row that used to survive it.
                data = _retired_persona_instance_payload(exc)
                # Pre-lease refusal, same as the pre-flight arm above — durably
                # recorded via `_publish_persona_chat_send_refused_event`. No
                # `session_id` yet: the mint that would have established one
                # never completed.
                _publish_persona_chat_send_refused_event(
                    session_id=session_id,
                    client_message_id=client_message_id,
                    persona_id=normalized_persona,
                    persona_instance_id=persona_instance_id,
                    error_kind=ChatErrorKind.RETIRED_PERSONA_INSTANCE,
                )
                _mission_chat_emit(args, data)
                return 2
            except PersonaChatPersistenceError as exc:
                # The mint's OTHER typed refusal, and the newer one: the bind
                # landed and the transcript row did not, so the mint retracted
                # the bind and reports the failure rather than returning a root
                # that dereferences nowhere. Same frame the commit phase below
                # emits for the sticky lane — one ``chat_session_persist_failed``
                # vocabulary for "the transcript store would not take it",
                # whichever end of the lane hit it. Without this arm the typed
                # error is merely a better-named traceback.
                #
                # No ``session_id``: the whole point is that this turn never
                # established one. The receipt stays RESERVED, so a retry with
                # the same idempotency key resolves the same root and completes.
                data = {
                    "ok": False,
                    "capability_id": "mission.chat.message",
                    "execution_state": ExecutionState.FAILED,
                    "error_kind": ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
                    "persistence_operation": exc.operation,
                    "error": str(exc),
                    "persona_id": normalized_persona,
                    "persona_instance_id": persona_instance_id,
                    "next_expected": (
                        "restore canonical persona chat transcript storage and retry the message"
                    ),
                }
                _mission_chat_emit(args, data)
                return 2
            session_id = str(receipt["root_chat_session_id"])
            session_established = session_established_payload(
                dispatch_decision,
                fresh=True,
                # The mint reports the lineage it actually RECORDED, so the
                # envelope and `_dispatched_from` cannot disagree. It matters on
                # a RETRY of the same client_message_id: that resolves the same
                # idempotency-keyed receipt, by which time `existing_root` has
                # become this very thread — reporting it here would claim "A
                # superseded A", and reporting nothing would lose the real
                # predecessor the first pass established.
                predecessor_session_id=(receipt.get("dispatched_from") or {}).get(
                    "predecessor_chat_session_id"
                ),
            )
        args.session_id = session_id
    # ── plan → commit ──────────────────────────────────────────────────────
    # Everything above RESOLVED this turn; everything below WRITES it, once,
    # under the chat-root lease.
    #
    # This boundary used to be a self-call: the body re-entered
    # ``_cmd_mission_chat_message(args)`` from inside ``with lease:`` after
    # setting an ``args._persona_chat_root_lease_acquired`` flag. Every
    # resolution above therefore ran TWICE per turn, three durable writes with
    # it (``open_chat``, the session ensure, the model-override persist), and
    # the turn's phase state had to be smuggled across the re-entry on
    # ``args._*`` attributes so the second pass would not re-decide it. The
    # split retires the recursion, the double writes, and the smuggling
    # together.
    display_name = (
        safe_assignment_text(getattr(persona, "display_name", None), limit=120)
        or _display_name_for_profile(normalized_persona)
    )
    plan = MissionChatTurnPlan(
        args=args,
        cfg=cfg,
        session_db=session_db,
        instance_store=instance_store,
        persona=persona,
        normalized_persona=normalized_persona,
        persona_instance_id=persona_instance_id,
        display_name=display_name,
        session_id=session_id,
        client_message_id=client_message_id,
        session_established=session_established,
        clarify_binding=clarify_binding,
        stated_session_id=stated_session_id,
        requested_by_session=requested_by_session,
        turn_relay_chain=turn_relay_chain,
        relay_chain_in=relay_chain_in,
        relay_deadline=relay_deadline,
        phases=turn_phases,
        session_db_open_ms=_session_db_open_ms,
        bundle_key_material_cursor=_bundle_diff_cursor,
    )
    # The lease covers the WRITES and nothing else. Post-emit decoration — the
    # auxiliary-LLM auto-title and the metadata event that reports it — is
    # packaged into ``deferred`` under the lease and run below, after the
    # ``with`` has exited. See MissionChatDeferredFinalization for the 2026-08-09
    # incident that made the distinction load-bearing: a 46-second title tail
    # inside the lease refused the operator's next message ``chat_busy`` long
    # after the reply it answered was on screen.
    deferred = MissionChatDeferredFinalization()
    # C1h-bis: the turn's own two stream publishes. START is issued inside the
    # commit, immediately after the write-ahead record that puts this turn in
    # the ``running_work`` projection; END rides the ``finally`` below, which is
    # the one place EVERY exit of the commit passes through — fourteen terminal
    # journal transitions, a bare ``return`` on each refusal, and an exception
    # that propagates all land there. Unpaired by construction: ``publish_ended``
    # is a no-op unless START actually appended, so the busy/refused paths (which
    # never reach a write-ahead) announce nothing. See
    # ``agent_runtime.chat_turn_presence``.
    presence = ChatTurnPresence()
    try:
        # Provenance decided in ONE place (owner id + observer kind from the
        # same serve-request fact) — see _mission_chat_lease_provenance for the
        # two diagnostic lies this line used to tell.
        lease_owner_id, lease_observer_kind = _mission_chat_lease_provenance()
        with persona_chat_root_lease(
            session_id,
            owner_id=safe_assignment_token(lease_owner_id),
            observer_kind=lease_observer_kind,
        ):
            exit_code = _mission_chat_commit_turn(plan, deferred, presence)
    except PersonaChatBusyError as exc:
        # "The root is busy" is not one answer, it is four — and which one it is
        # depends on whether the turn holding the lease IS this message. The
        # journal is readable without the lease, so that question is answerable
        # here; see ``_mission_chat_busy_outcome`` for the incident that made
        # collapsing all four into ``chat_busy`` a delivered-turn-painted-as-
        # rejected bug.
        return _mission_chat_busy_outcome(
            args=args,
            session_db=session_db,
            session_id=session_id,
            client_message_id=client_message_id,
            normalized_persona=normalized_persona,
            persona_instance_id=persona_instance_id,
            session_established=session_established,
            exc=exc,
        )
    finally:
        # The turn has left the in-flight set (or never entered it). Publishing
        # here rather than at each terminal transition is deliberate: the END
        # frame must be built from a projection that no longer carries the row,
        # and only this point is past every write the commit performs. Fail-safe
        # and idempotent — see ``ChatTurnPresence.publish_ended``.
        presence.publish_ended()
    # ── lease RELEASED ─────────────────────────────────────────────────────
    # Everything the turn owed the root is committed and reported. The root is
    # free from here, so a slow or failing deferred step delays nobody's next
    # send. ``run_once`` never raises: this is past the point where the exit
    # code is decided, and a decoration failure may not change it.
    deferred.run_once()
    return exit_code
