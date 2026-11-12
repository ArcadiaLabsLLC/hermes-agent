"""A steer the turn finished before absorbing becomes this chat root's next turn.

Upstream's ``agent/turn_finalizer.py`` drains the steer buffer once more at the end
of a turn and hands what is left back as ``result["pending_steer"]`` — input that
arrived after the final tool batch, so no tool result carried it. Every upstream
consumer delivers it as the next user turn (``gateway/run_turn.py``,
``cli_chat_turn_mixin``, ``tui_gateway/prompt_turn.py``). The Mission Control lane
acknowledged that input as ACCEPTED (``agent_runtime.mission_chat_steer``) and,
before this module, dropped it.

Owner ruling 2026-10-15: pass it to the next turn, as upstream does; never drop
what the operator typed. That hand-back only exists when the run RETURNS: a turn that
raises, or that the hard wall ends (the runner discards the interrupted result), took the
agent's steer buffer with it. ``requeue_undelivered_steers`` closes that from the steer
watcher's own on-disk ledger of what it accepted (RT-STEER-LOST-WHEN-TURN-FAILS). The next turn rides the busy-root send queue
(``agent_runtime.chat_root_send_queue``), the one door that already runs a send
after the turn holding the root, in arrival order, with the sender's origin.

Owner ruling 2026-11-12 (RT-LATE-STEER-TURN-RUNS-AS-THE-WORK-REQUEST-IT-WAS-TYPED-AT): "it should be an
ordinary chat message". A steer typed at a one-shot or wave-lane Work turn that arrives too late runs next
as the OPERATOR'S OWN send on that chat (:func:`_operators_own_send`), not as another turn of the run: the
run ended, and was reported, on its own turn's reply. An until-done run's late steer stays a turn of the
run. Every site that mints a ``steer-next-…`` send goes through :func:`_next_turn_send`.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.chat_root_send_queue import ORIGIN_ARG
from agent_runtime.chat_turn import INTENT_HINT_DEFAULT, OPERATOR_REQUESTED_BY, SURFACE_PROMPT_DEFAULT
from agent_runtime.mission_chat_turns.records import STEER_OF_FIELD
from agent_runtime.persona_chat_history.vocabulary import PERSONA_RUNTIME_NOTICE_KIND
from agent_runtime.turn_attendance import is_work_requester

__layer__ = "lanes"
__all__ = ["leftover_steer_client_message_id", "queue_leftover_steer", "requeue_dead_turn_steers",
           "requeue_undelivered_steers", "steer_ids"]

#: Prefix of the queued turn's ``client_message_id``. Derived from the steer's own
#: id, so a replay of the same turn converges on the one queue entry.
NEXT_TURN_PREFIX = "steer-next-"

def steer_ids(pending: Any) -> list[str]:
    """The client message ids of the OPERATOR steers in a hand-back, oldest first.

    A background notice rides the same buffer under an id of its own; it is not something the
    operator typed, so it is not named.
    """

    # MUTATION: drop the ``kind`` term and test_steer_next_turn_names_its_steer's notice test reddens.
    return [platform_id for item in getattr(pending, "inputs", ()) or ()
            if getattr(item, "kind", "") == "steer"
            and (platform_id := str(getattr(item, "platform_id", None) or "").strip())]


def _next_turn_text(pending: Any) -> str:
    """What the next turn is sent of a hand-back: everything but the ENDED turn's own harness notices.

    A runtime notice (``persona_chat_history.vocabulary.runtime_notice``: the wall checkpoint's "give
    your final reply now", a tool-availability note) speaks to the turn it was steered into. Handed
    back because that turn ended first, it was queued with the operator's steer — drawn in their own
    bubble — and, alone, as a turn nobody sent (RT-LATE-STEER-CARRIES-THE-ENDED-TURNS-TIME-NOTICE, seen
    live 2026-11-12). A background-process notice still rides: it is news for whoever runs next. A
    hand-back that kept no provenance (upstream's plain join) is sent as it is.
    """

    inputs = getattr(pending, "inputs", None)
    if not inputs:
        return str(pending or "").strip()
    # MUTATION: return ``str(pending).strip()`` here and both tests of
    # test_late_steer_without_the_ended_turns_notice redden.
    return "\n".join(item.text for item in inputs
                     if getattr(item, "kind", "") != PERSONA_RUNTIME_NOTICE_KIND).strip()


def _name_steers(persisted: dict, ids: list[str]) -> None:
    """State ``ids`` on a queued send — and nothing inherited from the send it was copied from.

    The turn writes them ahead on its journal record and the stored operator row carries them, so a
    reader links the steer it echoed to the turn that delivers it by this field, never by taking
    :data:`NEXT_TURN_PREFIX` off the turn's id — that id is the TURN's own when the hand-back kept no
    ids (RT-STEER-NEXT-TURN-NAMES-THE-STEER-IT-DELIVERS).
    """

    # MUTATION: return here and test_steer_next_turn_names_its_steer reddens at every minting site.
    persisted.pop(STEER_OF_FIELD, None)
    if ids:
        persisted[STEER_OF_FIELD] = list(ids)


#: What a late steer's own turn keeps of a Work run's send: whose chat it is. Nothing the run set for itself.
_CHAT_IDENTITY = ("persona_id", "persona_instance_id")


def _is_one_shot_work_send(send_args: dict) -> bool:
    """The send of a Work run that ends on this turn's reply: a single pass or a wave lane, not until-done.

    An until-done run's origin says ``goal`` (``work_store/persona_turn.py::start_from``); on its root every
    turn's settle feeds the run's after-turn hook, so a late steer there is part of the run by design.
    """

    origin = send_args.get(ORIGIN_ARG)
    until_done = isinstance(origin, dict) and bool(origin.get("goal"))
    return is_work_requester(send_args.get("requested_by")) and not until_done


def _operators_own_send(send_args: dict) -> dict:
    """The send ``runtime.chat.message`` would have queued for the operator on this chat, message aside.

    Not a copy of the run's send with fields struck out: a field the run gains later (as it gained its
    working folder) must not reach the operator's turn by default. So the requester is the operator's
    (no ``work:`` → no Work clock, no run to report to), there is no time budget (a turn a person sent
    runs until it ends), no ``run_workdir`` (the agent's own folder, not the lane's worktree), and the
    origin names no run, rows, lane or lent skills — its settle is the chat's, like any message's.
    ``tests/agent_runtime/test_late_steer_at_a_work_turn.py`` holds each field to what the real parser
    gives the app's own send.
    """

    return {
        **{name: send_args.get(name) for name in _CHAT_IDENTITY},
        "requested_by": OPERATOR_REQUESTED_BY, "requested_by_session": None, "max_seconds": None,
        "intent_hint": INTENT_HINT_DEFAULT, "surface_prompt": SURFACE_PROMPT_DEFAULT, "provider": None,
        "model": None, "use_agent_default": False, "relay_chain": None, "relay_deadline_epoch": None,
        # Who typed the steer is not on its ledger record; ``owner: None`` binds the link a send whose
        # sender has gone binds (``queued_turn_origin.queued_turn_link``: the Launcher that answers).
        ORIGIN_ARG: {"owner": None, "gateway": False},
    }


def _next_turn_send(send_args: dict, *, session_id: str, text: str, next_id: str, ids: list[str]) -> dict:
    """The ONE writer of a ``steer-next-…`` send: ``text`` as the root's next turn, naming ``ids``.

    ``send_args`` is the persisted send of the turn the steer was typed at. A one-shot Work turn's is
    replaced by the operator's own (owner ruling 2026-11-12, the module docstring); any other turn's is
    kept — an operator's own send, or an until-done pass.
    """

    # MUTATION: keep ``dict(send_args)`` for every turn and test_late_steer_at_a_work_turn reddens at
    # all three minting sites (the requester, the budget, the origin, the working folder).
    persisted = _operators_own_send(send_args) if _is_one_shot_work_send(send_args) else dict(send_args)
    # The same root, as a plain follow-up: never a new thread, a clarify answer, a
    # retry, a title or a second use of the first send's idempotency key.
    persisted.update(
        message=text, client_message_id=next_id, session_id=session_id, new_session=False,
        clarify_token=None, retry_of=None, title=None, idempotency_key=None,
    )
    _name_steers(persisted, ids)
    return persisted


def leftover_steer_client_message_id(pending: Any, turn_client_message_id: str) -> str:
    """The next turn's id: the first addressed input's id, else the turn's own."""

    for item in getattr(pending, "inputs", ()) or ():
        platform_id = str(getattr(item, "platform_id", None) or "").strip()
        if platform_id:
            return NEXT_TURN_PREFIX + platform_id
    return NEXT_TURN_PREFIX + str(turn_client_message_id or "").strip()


def queue_leftover_steer(args: Any, *, session_id: str, client_message_id: str, raw: Any) -> str | None:
    """Queue ``raw["pending_steer"]`` as the root's next operator send. Returns its id.

    ``None`` when the turn left nothing over. Called under the chat-root lease, so the
    entry is on disk before the root frees; the lease release wakes the runner.
    """

    from agent_runtime import chat_root_send_queue
    from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

    pending = raw.get("pending_steer") if isinstance(raw, dict) else None
    text = _next_turn_text(pending)
    if not text or not session_id:
        return None
    next_id = leftover_steer_client_message_id(pending, client_message_id)
    persisted = _next_turn_send(
        chat_root_send_queue.persistable_args(args, origin=send_origin()), session_id=session_id, text=text,
        next_id=next_id, ids=steer_ids(pending))
    chat_root_send_queue.enqueue(session_id, next_id, persisted)
    return next_id


def requeue_undelivered_steers(
    args: Any, *, session_id: str, client_message_id: str, session_db: Any, turn_returned: bool,
    raw: Any = None,
) -> list[str]:
    """Queue every accepted steer that reached neither the transcript nor a next turn. Returns their ids.

    Reads (and so clears) the root's accepted-steer ledger. A record is re-delivered unless
    its own row is in the transcript (the model was given it) or, for a steer of THIS turn
    when the run returned, ``raw["pending_steer"]`` handed it back (``queue_leftover_steer``
    queued that already). A returned turn's own steer can be in neither: the watcher keeps
    accepting until the runner's cleanup stops it, after upstream's finalizer drained the
    buffer for the last time (RT-STEER-ACCEPTED-AS-REPLY-ENDS) — so "the run returned" alone
    accounts for nothing. Process-completion notices are not operator input and are not
    re-sent. Called under the chat-root lease, like ``queue_leftover_steer``.
    """

    from agent_runtime import chat_root_send_queue
    from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

    if not session_id:
        return []
    return _requeue_from_ledger(
        chat_root_send_queue.persistable_args(args, origin=send_origin()), session_id=session_id,
        client_message_id=client_message_id, session_db=session_db, turn_returned=turn_returned,
        handed_back=raw.get("pending_steer") if isinstance(raw, dict) else None,
    )


def _handed_back(pending: Any, steer_id: str, text: str) -> bool:
    """Whether the turn's ``pending_steer`` carries this steer: by its id, or — when the
    hand-back is plain text that kept no ids — by its text."""

    inputs = getattr(pending, "inputs", None)
    if inputs:
        return any(str(getattr(item, "platform_id", None) or "").strip() == steer_id for item in inputs)
    return bool(text) and text in str(pending or "")


def _requeue_from_ledger(
    send_args: dict, *, session_id: str, client_message_id: str, session_db: Any, turn_returned: bool,
    handed_back: Any = None,
) -> list[str]:
    """Take the root's ledger and queue what is owed, each as ``send_args`` with the steer's text."""

    from agent_runtime import chat_root_send_queue, paths
    from agent_runtime.mission_chat_steer import take_accepted_steers

    from ..chat_history_writes import _persona_chat_existing_turn

    queued: list[str] = []
    for steer in take_accepted_steers(runtime_root=paths.store_root(), session_id=session_id):
        steer_id = str(steer.get("client_message_id") or "").strip()
        text = str(steer.get("message") or "").strip()
        if not steer_id or not text or steer.get("notification") is True:
            continue
        # MUTATION: skip every record of a returned turn here (drop the ``_handed_back`` term) and
        # test_steer_accepted_as_reply_ends' "accepted as the reply ends" row reddens.
        if turn_returned and steer.get("turn") == client_message_id and _handed_back(handed_back, steer_id, text):
            continue
        if _persona_chat_existing_turn(
            session_db=session_db, session_id=session_id, client_message_id=steer_id,
        ).get("operator"):
            continue
        next_id = NEXT_TURN_PREFIX + steer_id
        chat_root_send_queue.enqueue(session_id, next_id, _next_turn_send(
            send_args, session_id=session_id, text=text, next_id=next_id, ids=[steer_id]))
        queued.append(next_id)
    return queued


def requeue_dead_turn_steers() -> list[str]:
    """Serve boot: queue the steers a dead executor accepted, as each root's next turn. Returns their ids.

    A turn that died never settles, so its ledger waited for the root's NEXT settle — the
    steer typed just before a crash was delivered only after the operator sent something
    else (RT-DEAD-TURN-STEER-WAITS-FOR-NEXT-TURN). The watcher now keeps the turn's send
    beside the ledger (``active.json`` ``send_args``), so the boot can queue each record at
    once; the serve's queued-send runner then runs it. A root whose lease is HELD has a live
    turn, which settles its own ledger, and is skipped; a root whose transcript cannot be
    opened keeps its ledger for the next settle. Fail-open per root, like the orphan sweep.
    """

    from agent_runtime import paths
    from agent_runtime.chat_heads import resolve_conversation_chat_scope
    from agent_runtime.mission_chat_steer import roots_owing_steers
    from agent_runtime.persona_chat_continuity import persona_chat_root_lease
    from agent_runtime.persona_chat_durability import persona_session_db_for

    queued: list[str] = []
    for owed in roots_owing_steers(runtime_root=paths.store_root()):
        root = owed["session_id"]
        try:
            with persona_chat_root_lease(root, observer_kind="orphan_sweep"):
                from .. import chat_turn_message

                session_db = persona_session_db_for(
                    resolve_conversation_chat_scope(
                        session_id=root, persona_instance_id=owed.get("persona_instance_id") or None),
                    process=chat_turn_message._default_persona_session_db,
                )
                queued += _requeue_from_ledger(
                    owed["send_args"], session_id=root, client_message_id="", session_db=session_db,
                    turn_returned=False,
                )
        except Exception:  # busy (a live turn) or unreadable: the root's next settle still has the ledger
            continue
    return queued
