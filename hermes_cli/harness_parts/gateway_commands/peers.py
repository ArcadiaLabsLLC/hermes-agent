"""``peers list`` and ``peers revoke``.
"""

from __future__ import annotations

from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import (
    _list_envelope,
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

from .refusals import _refusal, _store_write_refusal

__layer__ = "lanes"


def cmd_gateway_peers_list(args) -> int:
    """``harness gateway peers list`` — every paired install, revoked included.

    Revoked rows are SHOWN, for ``devices list``'s reason: a list that hid them
    would make "never paired" and "thrown out" the same answer, and the second is
    the one an operator auditing a decommissioned machine needs. The credential
    has no field here and none on ``PeerRecord`` either.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_peers import list_peers, read_peer_cache, usable_peers

    root = paths.store_root()
    cache = read_peer_cache(root)
    usable = {peer.record.peer_install_id: peer for peer in usable_peers(root)}

    rows = []
    for record in list_peers(root):
        row = record.payload()
        cached = cache.get(record.peer_install_id)
        # **The trust/cache split, visible in the ack** (S2c). Nesting the
        # second half rather than flattening it is the point: an operator
        # reading this list can see which facts this install DECIDED and which
        # ones a peer TOLD it — the same question the two files answer, and one
        # that would be lost if both halves sat side by side as flat keys.
        row["cache"] = cached.payload() if cached is not None else None
        # The live stamp comes from the cache when there is one. The top-level
        # key is KEPT rather than removed — a launcher and an operator both read
        # it today — and now answers with the fact instead of with the legacy
        # residue left in the trust row.
        if cached is not None and cached.last_seen:
            row["last_seen"] = cached.last_seen
        peer = usable.get(record.peer_install_id)
        # ONE predicate, rendered. So the sheet's "removed" group is a filter
        # over this list rather than a fourth place deciding for itself which
        # edges are alive.
        row["usable"] = peer is not None
        row["ref"] = peer.ref if peer is not None else None
        row["unusable_reason"] = (
            None if peer is not None else _unusable_reason(record, cached)
        )
        rows.append(row)

    envelope = attach_root_observability(_list_envelope("gateway_peer", rows))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _unusable_reason(record, cached) -> str:
    """Why one row is not in ``usable_peers``, in the resolver's own vocabulary.

    The SAME words ``gateway_targets`` refuses with, so an operator comparing a
    list against a failed send reads one vocabulary rather than two. Ordered as
    the predicate orders them: a decision this operator made outranks a clock,
    and both outrank the far side's decision.
    """

    from agent_runtime.gateway_targets import (
        REASON_PEER_EXPIRED,
        REASON_PEER_REVOKED,
        REASON_PEER_REVOKED_YOU,
    )

    if record.revoked:
        return REASON_PEER_REVOKED
    if record.expired:
        return REASON_PEER_EXPIRED
    if cached is not None and cached.revoked_you:
        return REASON_PEER_REVOKED_YOU
    return ""


def cmd_gateway_peers_revoke(args) -> int:
    """``harness gateway peers revoke <peer_install_id>`` — refuse it from here on.

    Takes effect on the NEXT handshake, not on connections already open, and —
    the fact that distinguishes this from ``devices revoke`` — it is ONE-SIDED.
    A peer edge holds a credential at both ends, so revoking here stops that
    install from reaching this one and does nothing to the row it keeps about us.
    The ack says so rather than leaving an operator to assume symmetry: a
    revocation that reached across the wire would be one install writing into
    another's credential store, which is the authority R5 says an install never
    has over another.

    **S2c adds a courtesy and not an authority, and the distinction is the whole
    of it.** Before the local write, this verb tells the peer ``revoked_you``
    through ``peer.announce`` — a write into the far install's own CACHE, which
    that install applies to its own row under its own rules and which gates
    nothing there. It is still not a revocation reaching across the wire: the
    far side's credential for us is untouched and its operator's decision is
    untouched; all it learns is that ours changed. What it buys is that the news
    arrives in seconds rather than at that install's next call — which, for an
    agent mid-conversation, is the difference between a refusal and a message
    written to nobody.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_peers import lookup_peer, peer_store_path, revoke_peer
    from agent_runtime.serve_gateway_auth import StoreRefusal

    peer_install_id = str(getattr(args, "peer_install_id", "") or "").strip()
    if bool(getattr(args, "dry_run", False)):
        record = lookup_peer(paths.store_root(), peer_install_id)
        if record is None:
            return emit_harness_error(
                RuntimeError("unknown_peer"),
                reason="unknown_peer",
                args=args,
                code="not_found",
                message=f"no install {peer_install_id!r} is paired with this root",
            )
        row = record.payload()
        # What the WRITE would land, not what is there now.
        row["revoked"] = True
        # A preview sends nothing over the wire: a dry run that announced would
        # have told the far install about a revocation that never happened.
        row["announced"] = False
        envelope = attach_root_observability(_object_envelope("gateway_peer", row))
        envelope["dry_run"] = True
        _print_stage42(envelope, args=args, default_output="json")
        return 0

    # **Announce BEFORE the local write** (R-S2-15), and the order is
    # load-bearing rather than tidy. The announce is a CALL to the peer, and a
    # peer we have already revoked would be refused at our own door on the way
    # back — so announcing first means the far install learns it was cut while
    # the edge still works, and announcing after would mean the news went out
    # over a connection this install had just closed to it.
    #
    # A failed announce never blocks the revoke. That is the whole posture: the
    # push makes the news arrive in seconds, and nothing depends on it arriving
    # — the far side still learns at its next dial's refusal, exactly as it did
    # before this edge existed. The ack says which of the two happened.
    announced = False
    if not bool(getattr(args, "no_announce", False)):
        from agent_runtime.gateway_announce import announce_to_peers

        receipts = announce_to_peers(
            paths.store_root(),
            {"revoked_you": True},
            only=[peer_install_id],
        )
        announced = any(receipt.ok for receipt in receipts)

    peers = peer_store_path(paths.store_root())
    try:
        outcome = revoke_peer(
            paths.store_root(), peer_install_id, announced=announced
        )
    except OSError as exc:
        # ``revoke_peer`` catches OSError around its own locked write and
        # returns a refusal; the event append it runs AFTER releasing the lock
        # is outside that span. Both doors, one answer (R-D14).
        return _store_write_refusal(exc, args=args, store_path=peers)
    if isinstance(outcome, StoreRefusal):
        return _refusal(outcome, args=args, store_path=peers)
    row = outcome.payload()
    row["takes_effect"] = "next_handshake"
    row["scope"] = "this_install_only"
    # Whether the other machine was TOLD, not whether we tried. An operator who
    # believes a revocation was heard when it was not is the gap this closes.
    row["announced"] = announced
    row["note"] = (
        f"{peer_install_id} can no longer reach this install. Its own store "
        "still holds a row for this one — run `harness gateway peers revoke` "
        "over there to cut the edge in both directions."
        + (
            ""
            if announced
            else " It was NOT reachable to be told, so it will discover this at "
            "its next call."
        )
    )
    envelope = attach_root_observability(_object_envelope("gateway_peer", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0
