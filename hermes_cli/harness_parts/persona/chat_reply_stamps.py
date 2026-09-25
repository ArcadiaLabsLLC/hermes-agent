"""Stamps on a reply payload: turn visibility and reply media.

Separate because both the admission replay and the committed turn stamp the
same fields, and neither may own the other.
"""

from __future__ import annotations



__layer__ = "policy"
__all__ = [
    "_stamp_reply_media",
    "_stamp_turn_visibility",
]


def _stamp_turn_visibility(data: dict, reply_text, *, chat_result=None) -> dict:
    """Stamp the typed "did this turn produce visible content" block, in place.

    Every payload on this lane that carries a `reply` carries this beside it —
    the live turn, both idempotent-replay branches, and the projection-failure
    branch — so a consumer never has to know which internal path produced its
    payload in order to know whether anyone saw an answer. `ok` alone cannot
    tell it: this handler returns `ok: True` with an empty `reply` when the
    model produces no content, and on 2026-08-11 it did exactly that on a
    background-completion delivery, which every surface downstream then
    reported as a clean delivery.

    Total by construction (`classify_turn_visibility` never raises) because one
    of the four call sites is inside an exception handler, where a raise would
    replace a real failure with this one and corrupt the one-JSON-object stdout
    contract on the way.

    Function-local import, like the rest of this file.
    """

    from agent_runtime.turn_visibility import (
        TURN_VISIBILITY_KEY,
        classify_turn_visibility,
    )

    data[TURN_VISIBILITY_KEY] = classify_turn_visibility(
        reply_text=reply_text,
        # Absent on the replay branches, which answer from a stored reply and
        # have no turn result in hand. That is honestly less evidence, not
        # missing evidence: the stored text is exactly what the operator saw.
        messages=getattr(chat_result, "messages", None),
        raw=getattr(chat_result, "raw", None),
    ).as_dict()
    return data


#: The payload key carrying the ``reference → handle`` map minted for a
#: peer-executed turn's reply. Named here, read by
#: ``tools/agent_chat_dispatch._run_remote_dispatch``, and by nothing else.
REPLY_MEDIA_KEY = "media"


def _stamp_reply_media(data: dict, reply_text, args) -> dict:
    """Mint content handles for a PEER-EXECUTED reply's ``MEDIA:`` lines.

    Stage P4 / ruling R-P3. This is install **B**, answering a turn install A
    dispatched to it. The reply is about to travel home carrying
    ``MEDIA:<absolute path>`` lines that name files on THIS disk, and A can
    never mint handles for them: a handle is a digest of BYTES and A has none.
    So the mint happens here, at reply time, and the map rides the completion —
    which is the only channel between the two installs that does not require a
    second verb, because the payload this function stamps IS what
    ``peer.agent_chat.execute``'s frame lane carries back.

    **Gated on the peer origin, and the gate is the one fact that is already
    true.** ``--requested-by peer:<install id>`` is set by
    ``chat_turn.normalize_peer_chat_execute`` from a connection whose HMAC
    verified, and it is the ONLY spelling that reaches this handler for a
    cross-install turn. A local turn mints nothing, which is not an
    optimisation but the honest answer: on this machine the ``MEDIA:`` path IS
    the pointer, every local surface opens it directly, and hashing every image
    of every local turn would spend real I/O to produce a field with no reader.

    Absent, never empty. A reply that declared no image carries no key at all,
    so a local payload is byte-identical to what it has always been and a
    consumer never has to tell "no pictures" from "an older runtime".

    Total by construction, like :func:`_stamp_turn_visibility` beside it and for
    the same reason: one call site is inside an exception handler, and a raise
    here would replace a real failure with this one and corrupt the
    one-JSON-object stdout contract on the way out.
    """

    try:
        requested_by = str(getattr(args, "requested_by", "") or "")
        from agent_runtime.chat_turn import PEER_REQUESTED_BY_PREFIX

        if not requested_by.startswith(PEER_REQUESTED_BY_PREFIX):
            return data
        from agent_runtime.media_handles import mint_reply_media

        minted = mint_reply_media(reply_text)
        if minted:
            data[REPLY_MEDIA_KEY] = minted
    except Exception:  # noqa: BLE001 - a picture is never worth losing a turn
        import logging

        logging.getLogger(__name__).debug(
            "reply media mint failed; the reply travels without handles",
            exc_info=True,
        )
    return data
