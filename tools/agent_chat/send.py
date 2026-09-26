"""``agent_chat_send`` — the relay: validate, target, envelope, then detached or inline."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from types import SimpleNamespace

from agent_runtime import relay_policy
from agent_runtime.dispatch_session_policy import coerce_optional_flag
from agent_runtime.mission_chat_door import MissionChatDoorUnbound, run_mission_chat_turn

from .detached import _async_delivery_available, _dispatch_detached, _persona_of_chat_root
from .lane import _looks_like_instance_handle, refusal_json, scope_off
from .schemas import _MESSAGE_LIMIT, _REPLY_LIMIT

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def agent_chat_send(
    *,
    persona_id,
    message,
    session_id=None,
    clarify_token=None,
    new_session=None,
    title=None,
    max_seconds=None,
    wait=None,
    notify_operator=None,
    requested_by_session=None,
):
    """Send *message* into another persona's chat lane — the six-tool contract
    in ``tools/agent_chat_tool.py``'s docstring; the phases are :class:`Send`."""
    return Send(
        persona_id=persona_id,
        message=message,
        session_id=session_id,
        clarify_token=clarify_token,
        new_session=new_session,
        title=title,
        max_seconds=max_seconds,
        wait=wait,
        notify_operator=notify_operator,
        requested_by_session=requested_by_session,
    ).run()


class Send:
    """``agent_chat_send`` as phases (W0-G7): ``validate -> target -> envelope ->
    remote -> admit_detached -> budget`` each answer a refusal or ``None``;
    then ``relay_args`` and either ``dispatch`` (``wait=false``) or ``relay``
    (inline, through the Q10 door) and ``reply``. The fields are the locals the
    422-line function carried, so each phase keeps the names its comments use.
    """

    def __init__(
        self,
        *,
        persona_id,
        message,
        session_id,
        clarify_token,
        new_session,
        title,
        max_seconds,
        wait,
        notify_operator,
        requested_by_session,
    ) -> None:
        persona_id = (persona_id or "").strip()
        message = (message or "").strip()
        resolved_session_id = (str(session_id).strip() or None) if session_id else None
        resolved_clarify_token = (str(clarify_token).strip() or None) if clarify_token else None
        # TRI-STATE, not a bool: True = fresh thread, False = continue the target's
        # current default thread, UNSET = let agent_runtime.mission_chat.dispatch_session_policy
        # decide (default: one fresh thread per dispatched task). `bool()` here would
        # collapse "unset" into an explicit "sticky" and silently pin every caller to
        # the old mega-thread behavior.
        new_session = coerce_optional_flag(new_session)
        resolved_title = (str(title).strip() or None) if title else None
        self.persona_id, self.message = persona_id, message
        self.resolved_session_id, self.resolved_clarify_token = resolved_session_id, resolved_clarify_token
        self.new_session, self.resolved_title = new_session, resolved_title
        self.max_seconds, self.wait, self.notify_operator = max_seconds, wait, notify_operator
        self.requested_by_session = requested_by_session

    def run(self) -> str:
        refusal = (
            self.validate()
            or self.target()
            or self.envelope()
            or self.remote()
            or self.admit_detached()
            or self.budget()
        )
        if refusal is not None:
            return refusal
        args = self.relay_args()
        if self.detached:
            return self.dispatch()
        return self.relay(args)

    def validate(self) -> str | None:
        """The request's own bounds and contradictions — :data:`_REQUEST_REFUSALS`, in order."""
        for refused, refusal in _REQUEST_REFUSALS:
            if refused(self):
                return refusal(self)
        return None

    def target(self):
        """SYNTAX first: an ``@install/target`` that will not parse refuses here."""
        persona_id = self.persona_id
        # Gateway Stage 7 (R4). SYNTAX first, and before anything else looks at the
        # target: an `@install/target` that will not parse must refuse rather than
        # fall through to the local lane, because falling through would silently
        # address somebody on THIS machine with a briefing written for another one.
        # `None` here is the ordinary case and means "unqualified, i.e. local" —
        # which is a property of the parser rather than a default (see
        # `agent_runtime.gateway_targets`).
        from agent_runtime.gateway_targets import TargetRefusal, parse_install_target

        install_qualifier = parse_install_target(persona_id)
        if isinstance(install_qualifier, TargetRefusal):
            return refusal_json(
                install_qualifier.message,
                error_kind=install_qualifier.reason,
                target_persona=persona_id,
            )
        self.install_qualifier = install_qualifier
        return None

    def envelope(self):
        """The relay envelope for THIS turn, and which lane the caller asked for."""
        # Envelope provenance: the chain/deadline for the CURRENT turn, seeded by
        # the mission-chat handler. Depth/cycle policy is decided downstream at
        # the canonical chokepoint; here we only clamp this hop's wall budget to
        # the shared chain deadline and fast-fail when nothing usable is left.
        chain = relay_policy.RELAY_CHAIN.get()
        deadline_epoch = relay_policy.RELAY_DEADLINE.get()

        # Detached or inline? TRI-STATE for the same reason ``new_session`` is —
        # ``bool(None)`` would read "the caller said nothing" as "the caller said
        # inline", which happens to be the right default but would make the two
        # indistinguishable to anything downstream that needs to know which it was.
        detached = coerce_optional_flag(self.wait) is False
        notify = coerce_optional_flag(self.notify_operator) is True
        sender_session = str(self.requested_by_session or "").strip()
        self.chain, self.deadline_epoch = chain, deadline_epoch
        self.detached, self.notify, self.sender_session = detached, notify, sender_session
        return None

    def remote(self):
        """A cross-install target: detached only, no clarify token, and it must resolve."""
        from agent_runtime.gateway_targets import TargetRefusal, peer_store_root, resolve_install_target

        remote_target = None
        if self.install_qualifier is not None:
            if not self.detached:
                # **A cross-install send is the DETACHED lane only, and this is a
                # scope statement rather than a limitation discovered late.** The
                # synchronous relay runs the target's turn inside the sender's own
                # turn, under the sender's process lock and the shared chain
                # deadline — a safety story made entirely of facts about THIS
                # process. None of it holds across a machine boundary: the far
                # install's turn obeys its own concurrency cap, its own budget and
                # its own drain, so a sender blocked on it would be blocked on a
                # clock nobody here owns. The durable row is what replaces that,
                # and the durable row is what `wait: false` means.
                return refusal_json(
                    f"{self.persona_id} is on another install, and a cross-install send "
                    "returns a handle rather than a reply: send it with wait=false "
                    "and their answer will arrive as its own message in this "
                    "conversation.",
                    error_kind="remote_requires_detached",
                    target_persona=self.persona_id,
                )
            if self.resolved_clarify_token:
                # **R-IP10's one exception, said out loud.** Every local messaging
                # feature crosses an install boundary except this: a clarify token
                # is minted by THIS install's clarify gateway and resolves against
                # THIS install's pending questions, so carrying it to another
                # machine would hand the far side a token it cannot look up. The
                # continuity that DOES cross is the session id — which the dispatch
                # delivery already reported as "Their thread" — so the refusal names
                # the route rather than only the wall.
                return refusal_json(
                    f"a clarify_token belongs to this install and cannot answer a "
                    f"question asked on {self.install_qualifier.install_ref}. Answer them "
                    "by naming their thread instead: send with session_id set to the "
                    "session_id your dispatch delivery reported as 'Their thread', "
                    "and your answer lands in the conversation the question came "
                    "from.",
                    error_kind="clarify_token_not_portable",
                    target_persona=self.persona_id,
                )
            remote_target = resolve_install_target(peer_store_root(), self.install_qualifier)
            if isinstance(remote_target, TargetRefusal):
                # DETERMINISTIC, so it fails fast here and burns no attempt — the
                # `dispatch_delivery.py:123-132` class, reached before any row
                # exists rather than after eight identical retries.
                extra = (
                    {"candidates": list(remote_target.candidates)}
                    if remote_target.candidates
                    else {}
                )
                return refusal_json(
                    remote_target.message,
                    error_kind=remote_target.reason,
                    target_persona=self.persona_id,
                    **extra,
                )
        self.remote_target = remote_target
        return None

    def admit_detached(self):
        """The three preconditions a ``wait=false`` promise needs before any work starts."""
        persona_id, detached, sender_session = self.persona_id, self.detached, self.sender_session
        if detached and not sender_session:
            # A detached dispatch is a PROMISE to deliver the answer back into the
            # caller's conversation. With no caller session there is nowhere to
            # deliver it, so refuse the promise rather than run the work and drop
            # the result on the floor — the failure mode a wait:false lane must
            # never have is "it ran and nobody was told".
            return refusal_json(
                "agent_chat_send(wait=false) needs a chat session to deliver the reply back into, "
                "and this lane has none. Send it with wait=true (the default) and use the reply "
                "inline.",
                error_kind="async_delivery_unavailable",
                target_persona=persona_id,
            )

        if detached and not _async_delivery_available():
            # The SAME question the capability contract already answers, asked by the
            # lane that most needs it. `async_delivery_supported()` is False here for
            # a concrete reason — this turn's process ends when the turn does, and
            # nothing in it will be alive to notice a background result — and a
            # dispatch accepted on such a lane would leave an orphaned child process
            # writing into a chat thread with no recorder left to settle its row.
            #
            # This is exactly the reasoning `delegate_task` follows when the same
            # flag is False: fall back to the synchronous path and return the result
            # INSIDE the turn that asked for it, rather than promise a delivery the
            # channel cannot make. Refusing here is the same ruling, applied to the
            # tool that made the promise.
            return refusal_json(
                "agent_chat_send(wait=false) is not available on this lane: it ends when this turn "
                "ends, so nothing would be left to receive their answer or to record what happened "
                "to the work. Send it with wait=true (the default) and use the reply inline — same "
                "fallback delegate_task takes when a channel cannot take a late completion.",
                error_kind="async_delivery_unavailable",
                target_persona=persona_id,
            )

        sender_persona = _persona_of_chat_root(sender_session) if detached else ""
        if detached and not sender_persona:
            # Admission check, run BEFORE any work starts. The delivery drain
            # addresses its forged turn by resolving this root to a persona; a root
            # it cannot resolve gets a typed ``sender_session_unresolvable`` drop —
            # AFTER the target has already done the work. Running real work whose
            # answer is guaranteed to be discarded is the exact run-and-drop this
            # lane must never have, so the same resolver decides admission here.
            return refusal_json(
                "agent_chat_send(wait=false) can only deliver back into a persona chat thread, and "
                "this session does not resolve to one. Send it with wait=true (the default) and use "
                "the reply inline.",
                error_kind="async_delivery_unavailable",
                target_persona=persona_id,
            )
        self.sender_persona = sender_persona
        return None

    def budget(self):
        """This hop's wall budget and the deadline the envelope carries."""
        if self.detached:
            # RELAY RULING (operator-approved 2026-08-03): a detached dispatch is a
            # NEW CHAIN ROOT with its own deadline, and the chain is still forwarded.
            #
            # Both halves matter. Minting a fresh deadline is the whole point: the
            # shared 4-minute chain budget exists so a synchronous hop cannot
            # out-live the caller who is BLOCKED on it, and nobody is blocked here —
            # clamping a 30-minute background job to whatever was left of a
            # conversational window would kill exactly the work this lane exists to
            # host, and the remaining-budget fast-fail would refuse most dispatches
            # outright. Forwarding the chain unchanged is what keeps that from being
            # a loophole: depth and cycle detection are decided downstream by
            # ``evaluate_relay`` at the handler's canonical persona chokepoint, and
            # they read the CHAIN, not the clock. So A→B→A is still refused across a
            # detach, and the depth ceiling still holds — a detached hop buys time,
            # never reach.
            #
            # The policy itself stays where it lives. Nothing here decides anything:
            # this branch chooses which BUDGET rides the envelope, and the guard
            # that could refuse the send runs, unchanged, in the handler.
            from agent_runtime.config import resolve_mission_chat_dispatch_max_seconds

            try:
                stated = float(self.max_seconds) if self.max_seconds is not None else None
            except (TypeError, ValueError):
                stated = None
            wall_budget = float(resolve_mission_chat_dispatch_max_seconds(stated))
            # NO deadline is minted here. The child mints it when the turn actually
            # starts (``agent_chat_dispatch.build_dispatch_argv``), because a
            # dispatch queued behind the concurrency cap would otherwise burn its
            # wall budget sitting in a queue — the budget the sender was told about
            # and the budget the turn got would drift apart with nothing reporting it.
            effective_deadline = None
        else:
            try:
                wall_budget = max(10.0, min(float(self.max_seconds or 240), 600.0))
            except (TypeError, ValueError):
                wall_budget = 240.0
            remaining = relay_policy.remaining_budget_seconds(self.deadline_epoch)
            if remaining is not None:
                if remaining < relay_policy.MIN_RELAY_BUDGET_SECONDS:
                    return refusal_json(
                        f"relay budget exhausted: {max(remaining, 0.0):.1f}s left on the shared "
                        f"chain deadline (minimum {relay_policy.MIN_RELAY_BUDGET_SECONDS:.0f}s "
                        "per hop). Answer your caller with what you have.",
                        error_kind="relay_budget_exhausted",
                        relay_chain=list(self.chain),
                    )
                wall_budget = min(wall_budget, remaining)
            effective_deadline = (
                self.deadline_epoch if self.deadline_epoch is not None else time.time() + wall_budget
            )
        self.wall_budget, self.effective_deadline = wall_budget, effective_deadline
        return None

    def relay_args(self):
        """The handler's argument namespace — the one request both lanes forward."""
        requested_by = "agent-chat-relay"
        source_token = str(self.requested_by_session or "").strip()
        if source_token:
            requested_by = f"agent:{source_token[:120]}"

        # Instance targeting: a personainst_* handle in the persona slot addresses
        # THAT specific instance (a persona may have more than one live instance).
        # Forward it as the instance id so the handler threads the specific
        # instance's default session; the handler's canonical_persona_instance_id
        # preserves placement-backed sibling ids (personainst_<persona>_agent_2). A
        # bare persona id forwards no handle → the persona's canonical primary.
        #
        # A cross-install target forwards NO local handle: the string after the
        # `/` is spelled in the far install's vocabulary and is split by the far
        # install's own rule (`chat_turn.normalize_peer_chat_execute`), so running
        # this machine's handle test over it would be this machine answering a
        # question only the other one can.
        target_instance_id = (
            None
            if self.remote_target is not None
            else (self.persona_id if _looks_like_instance_handle(self.persona_id) else None)
        )

        args = SimpleNamespace(
            persona_id=self.persona_id,
            persona_instance_id=target_instance_id,
            session_id=self.resolved_session_id,
            # Clarify continuity: the handler resolves this token to the thread the
            # question was asked in and outranks everything else with it. Forwarded
            # verbatim — the tool never resolves it (one ticket-store authority, and
            # it lives with the handler that owns the session lane).
            clarify_token=self.resolved_clarify_token,
            # Fresh-thread lane: the handler mints a new canonical session through the
            # SAME default-session chokepoint (mint= mode), never a tool-side mint —
            # keeping ONE minting authority (the orphaned-relay fix's whole point).
            # Forwarded UNCOERCED (None stays None) so the handler's policy resolver
            # can tell "the caller said nothing" from "the caller said continue".
            new_session=self.new_session,
            task_id=None,
            goal_id=None,
            # Names the thread only when this send mints one; the handler derives a
            # title from the message when the caller offered none.
            title=self.resolved_title,
            message=self.message,
            provider=None,
            model=None,
            use_agent_default=False,
            surface_prompt="",
            intent_hint="chat",
            requested_by=requested_by,
            client_message_id=f"agent-relay-{uuid.uuid4().hex[:12]}",
            stream=False,
            max_seconds=self.wall_budget,
            json=True,
            # Sender provenance (envelope field, not guard logic): the sender's
            # chat-root session id lets the handler's target chokepoint scope
            # bare-persona resolution to the SENDER's workspace.
            requested_by_session=source_token or None,
            # Explicit relay envelope — the handler's chokepoint guard reads
            # these; ambient ContextVars never cross a transport boundary.
            relay_chain=list(self.chain),
            relay_deadline_epoch=self.effective_deadline,
        )
        self.requested_by, self.source_token = requested_by, source_token
        self.target_instance_id = target_instance_id
        return args

    def dispatch(self):
        """``wait=false``: hand the turn to a detached child and return its handle."""
        # The child is a separate PROCESS, so it takes argv and an environment,
        # not an args object. The spec below is that invocation's whole input;
        # nothing about the turn is smuggled through ambient state.
        return _dispatch_detached(
            spec={
                "persona_id": self.persona_id,
                "persona_instance_id": self.target_instance_id,
                "session_id": self.resolved_session_id,
                "clarify_token": self.resolved_clarify_token,
                "new_session": self.new_session,
                "title": self.resolved_title,
                "message": self.message,
                "intent_hint": "chat",
                "requested_by": self.requested_by,
                "requested_by_session": self.source_token or None,
                "relay_chain": list(self.chain),
                "max_seconds": self.wall_budget,
            },
            persona_id=self.persona_id,
            target_instance_id=self.target_instance_id,
            sender_session=self.sender_session,
            sender_persona=self.sender_persona,
            message=self.message,
            title=self.resolved_title,
            notify_operator=self.notify,
            chain=self.chain,
            wall_budget=self.wall_budget,
            remote_target=self.remote_target,
        )

    def relay(self, args):
        """Inline: run the turn in-process through the Q10 door, then the compact reply."""
        persona_id, requested_by = self.persona_id, self.requested_by
        # The handler hands its payload dict straight over through the
        # ``payload_sink`` seam. This used to be a ``contextlib.redirect_stdout``
        # capture plus a JSON re-parse of the captured text, which was wrong in two
        # ways worth naming: ``redirect_stdout`` rebinds ``sys.stdout``
        # PROCESS-GLOBALLY (so any other thread in this process — every other serve
        # request — briefly wrote into this buffer), and a payload that already
        # existed as a dict was serialised only to be parsed back. The seam removes
        # both, and it is what makes the detached lane above safe to run concurrently.
        # The seam lives in the door now (``run_mission_chat_turn`` sets
        # ``payload_sink`` and returns the last payload), and the door is how
        # this tool reaches the CLI's turn handler at all: bound at plugin
        # registration and serve boot (ruling Q10), never imported from here.
        try:
            exit_code, payload = run_mission_chat_turn(args)
        except MissionChatDoorUnbound as exc:
            return refusal_json(
                str(exc), error_kind="mission_chat_door_unbound", target_persona=persona_id
            )
        except Exception as exc:  # pragma: no cover - defensive; surfaced to the model
            logger.exception("agent_chat_send relay failed")
            return refusal_json(f"{type(exc).__name__}: {exc}", target_persona=persona_id)

        if payload is None:
            return refusal_json(
                "relay produced no reply payload",
                target_persona=persona_id,
                exit_code=exit_code,
            )

        # Compact result: the caller needs the reply and the thread pointers, not
        # the ~75KB prompt-observability block.
        reply = str(payload.get("reply") or "")[:_REPLY_LIMIT]
        result = {
            "ok": bool(payload.get("ok")) and exit_code == 0,
            "target_persona": persona_id,
            "reply": reply,
            "session_id": payload.get("session_id"),
            "chat_session_id": payload.get("chat_session_id"),
            "persona_instance_id": payload.get("persona_instance_id"),
            "total_tokens": payload.get("total_tokens"),
            "requested_by": requested_by,
        }
        # Thread lineage: whether this send opened a fresh task-scoped thread, the
        # typed reason, and the thread it superseded. The caller needs it to know
        # that continuing THIS exchange means passing `session_id` back — under the
        # new_per_dispatch default, omitting it opens another fresh thread.
        if payload.get("session_established") is not None:
            result["session_established"] = payload.get("session_established")
        # Where a clarify answer actually landed, and why. Present only when this
        # send carried a token or settled an open question; `overrode_session_id`
        # names a session_id the token outranked, so the override is never silent.
        if payload.get("clarify_binding") is not None:
            result["clarify_binding"] = payload.get("clarify_binding")
        # Clarify-back: the briefed agent asked a question instead of answering
        # (it holds context you don't — e.g. "which dev, launcher or backend?").
        # Forwarded WHOLESALE, which is why the `clarify_token` inside it needs no
        # code here: answer by sending the choice back with that token (or this
        # session_id) and the exchange continues as one conversation.
        if payload.get("clarify_request") is not None:
            result["clarify_request"] = payload.get("clarify_request")
        if payload.get("relay_chain") is not None:
            result["relay_chain"] = payload.get("relay_chain")
        # Ambiguous-target refusal: forward the candidate instance handles so the
        # calling agent can immediately retry against an exact @personainst_ handle
        # (the whole point of the typed refusal — the CLI error text alone is not
        # enough for the model to pick a sibling).
        if payload.get("candidates") is not None:
            result["candidates"] = payload.get("candidates")
        if not result["ok"]:
            result["error"] = str(payload.get("error") or payload.get("blocker") or "relay turn failed")[:400]
            if payload.get("error_kind"):
                result["error_kind"] = str(payload.get("error_kind"))[:60]
            result["exit_code"] = exit_code
        return json.dumps(result, indent=2, default=str)


#: The request's own bounds and contradictions, refused in THIS order before
#: anything looks at the target — each is a (refused, refusal) pair over a
#: :class:`Send`, and each has a named test in ``test_agent_chat_tool.py``.
_REQUEST_REFUSALS: tuple[tuple[Callable[[Send], bool], Callable[[Send], str]], ...] = (
    (
        lambda send: scope_off(),
        lambda send: refusal_json(
            "agent_chat_send is disabled on this runtime (HERMES_AGENT_CHAT_SCOPE=off). "
            "Tell the operator instead of retrying."
        ),
    ),
    (
        lambda send: not send.persona_id,
        lambda send: refusal_json("agent_chat_send requires a persona_id."),
    ),
    (
        lambda send: not send.message,
        lambda send: refusal_json("agent_chat_send requires a non-empty message."),
    ),
    (
        lambda send: len(send.message) > _MESSAGE_LIMIT,
        lambda send: refusal_json(
            f"message exceeds the {_MESSAGE_LIMIT}-character relay limit; send a briefing, not a dump."
        ),
    ),
    # Contradictory: new_session asks for a fresh thread; session_id names an
    # existing one. Refuse rather than silently picking one — the caller must
    # decide which thread they mean.
    (
        lambda send: send.new_session is True and bool(send.resolved_session_id),
        lambda send: refusal_json(
            "agent_chat_send: new_session=true and session_id are contradictory — omit session_id "
            "to start a fresh thread, or drop new_session to continue that specific thread.",
            error_kind="contradictory_thread_target",
        ),
    ),
    # The symmetric contradiction, and the ONE clarify case with no correct
    # reading: a clarify token means "put this answer where the question
    # was", new_session=true means "put it somewhere new". A stale
    # session_id alongside a token is NOT this — the token deliberately wins
    # that one downstream, because getting session_id wrong is exactly the
    # failure the token exists to absorb.
    (
        lambda send: send.new_session is True and bool(send.resolved_clarify_token),
        lambda send: refusal_json(
            "agent_chat_send: new_session=true and clarify_token are contradictory — a clarify "
            "answer belongs in the thread its question was asked in. Drop new_session to answer "
            "them, or drop clarify_token to dispatch something new.",
            error_kind="contradictory_thread_target",
        ),
    ),
)
