"""``StoreRefusal`` -> harness error (R-D6 / R-D14), the operator sentences,
the grant payload's shape, and ``_dial_target`` — the one refusal the
payload writers share when this root has no address to hand out.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.gateway_endpoints.candidates import _candidate_endpoints, _dial_host
from hermes_cli.harness_support import emit_harness_error

__layer__ = "lanes"


#: ``StoreRefusal.reason`` → the harness error taxonomy, split on the operator's
#: next MOVE, which is what the exit families mean:
#:
#: * ``too_many_pending`` / ``locked_out`` — the store is telling you to wait,
#:   for a code to expire or a lockout to lapse. Family 6 (precondition), not a
#:   fault: nothing is broken and the identical command succeeds later.
#: * ``invalid_tier`` / ``invalid_device_id`` / ``invalid_code`` — the argument
#:   was wrong (2).
#: * ``unknown_device`` — nothing to act on (3).
#: * a WRITE this machine could not perform — ``store_unwritable`` (family 1),
#:   R-D14. See :data:`_STORE_WRITE_REASONS` for why these three left family 7.
#: * every remaining I/O condition on the root — retryable in the sense family 7
#:   already means (an AV hold releases, the identical call then succeeds).
_REFUSAL_CODES = {
    "too_many_pending": "pairing_codes_pending",
    "locked_out": "pairing_locked_out",
    "invalid_tier": "invalid_payload",
    "invalid_device_id": "invalid_payload",
    "invalid_code": "invalid_payload",
    "unknown_device": "not_found",
    "store_corrupt": "store_corrupt",
    # Stage 6's peer refusals, split on the same rule — the operator's next
    # MOVE. A malformed install id or a secret the remote never returned is a
    # bad argument or a bad exchange (2); an install nobody paired is nothing to
    # act on (3). The shared refusals above (`locked_out`, `too_many_pending`,
    # every I/O condition) are shared because the store is shared: one
    # `pairing.json`, one lockout, one cap across both ceremonies.
    "invalid_peer_id": "invalid_payload",
    "invalid_secret": "invalid_payload",
    "unknown_peer": "not_found",
}

#: The ``os_error_reason`` words that mean **this machine could not write its own
#: store** — R-D14, and the one thing on this lane that is not about the network.
#:
#: D3 run #1 (2026-09-04, 18:06:20) is why they have their own code. The
#: handshake completed, the far install answered, and ``record_peer`` came back
#: ``permission_denied`` from a ``[WinError 5]`` on ``peers.json``. That fell
#: through this table to ``runtime_unavailable``, the launcher's fulfiller mapped
#: ``runtime_unavailable`` to ``no_route``, and the sheet told the operator the
#: Mac was unreachable — a claim about the network, for a DACL on a local
#: directory, retried once a minute for four minutes to the identical result.
#:
#: ``root_missing`` is deliberately NOT here and keeps family 7. An absent
#: directory is the one condition the writer creates for itself on its next call
#: (``write_secure_json`` mkdirs its parents), so "retry" really is the cure —
#: which is the whole distinction family 1 and family 7 encode.
_STORE_WRITE_REASONS = frozenset(
    {"permission_denied", "unwritable", "root_not_a_directory"}
)
for _reason in _STORE_WRITE_REASONS:
    _REFUSAL_CODES[_reason] = "store_unwritable"
del _reason


def _refusal(refusal: Any, *, args, store_path: Any = None) -> int:
    """One ``StoreRefusal`` as a harness error, with BOTH words on it.

    R-D6. The mapping above is many-to-one on purpose — the family answers "what
    do I do next", and nine I/O conditions genuinely share one next move — but a
    reader who only has the family cannot say what happened. The launcher's
    fulfiller maps ``runtime_unavailable`` to ``no_route``, so S4's 12:00:40
    receipt recorded "no route" for a refusal whose actual reason existed and
    was thrown away one process earlier.

    So ``reason`` rides beside ``code``: the store's own word, unmapped,
    untranslated, and never a substitute for the family an exit code is derived
    from.

    ``store_path`` is R-D14's other half. A write refusal carries an OS message
    like ``[WinError 5] Access is denied: '.peers.json.ntk1yca6.tmp' ->
    'peers.json'`` — two BASENAMES, which name no directory an operator could go
    and fix. This is the one caller that knows which file the verb was writing,
    so it is the one place that can put the absolute path in front of them.
    """

    code = _REFUSAL_CODES.get(refusal.reason, "runtime_unavailable")
    detail = refusal.detail or refusal.reason
    reason = refusal.reason
    message = detail
    if code == "store_unwritable":
        # ONE word on the wire for this condition (R-D14), because the launcher
        # renders it as a sheet sentence of its own — three spellings would be
        # three sentences for one fault. The store's own word is not lost: it
        # rides in the message, beside the OSError text, which is where an
        # operator reads "which failure was it" anyway.
        reason = "store_unwritable"
        where = f" at {store_path}" if store_path is not None else ""
        message = (
            f"could not write this install's own gateway store{where}: {detail} "
            f"({refusal.reason}). Nothing on the other machine is wrong — the "
            "handshake it answered is lost because this side could not record "
            "it. Give the user this process runs as write and delete permission "
            "on that file and the directory holding it, then run the command "
            "again."
        )
    return emit_harness_error(
        RuntimeError(refusal.reason),
        args=args,
        code=code,
        message=message,
        reason=reason,
    )


def _store_write_refusal(exc: OSError, *, args, store_path: Any) -> int:
    """An ``OSError`` that ESCAPED a store call, as the same R-D14 refusal.

    The store functions on this lane catch ``OSError`` around their locked
    read-modify-write and return a ``StoreRefusal``, which :func:`_refusal`
    already classifies. This covers what that ``try`` does not span — the event
    append and the cache touch that ``record_peer`` runs after its lock is
    released, and any future write that acquires a raise on the way out.

    One helper rather than four, and both doors give the identical code, message
    shape and exit: an operator hitting a permission problem must not get two
    different stories depending on which line inside the store it surfaced on.
    """

    from agent_runtime.store_file_io import os_error_reason

    reason = os_error_reason(exc)
    if reason not in _STORE_WRITE_REASONS:
        reason = "unwritable"
    return _refusal(
        _StoreWriteRefusal(reason, str(exc)), args=args, store_path=store_path
    )


class _StoreWriteRefusal:
    """A ``StoreRefusal``-shaped pair, so :func:`_refusal` has one input type.

    Not the real class: importing ``serve_gateway_auth`` here would pull the
    whole device-store module into every verb that only needs two strings, and
    the only contract ``_refusal`` reads is ``.reason`` / ``.detail``.
    """

    __slots__ = ("reason", "detail")

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail


#: The one sentence every verb on this lane uses for "nothing is listening".
#: ``peers pair`` printed it as a NOTE and :func:`cmd_gateway_introduce` raises
#: it as a REFUSAL; the words are identical on purpose, because an operator
#: reading a launcher's error and an operator reading a terminal note are
#: looking at the same condition and should not have to recognise two spellings
#: of it.
LISTENER_OFF_SENTENCE = (
    "remote_gateway.listen is off for this root: nothing will accept this code "
    "until an interface is configured and the runtime restarts."
)

#: The OTHER "nowhere to dial", and it is a different condition from the one
#: above rather than a rewording of it: the lane is ON, a listener is up or
#: configured, and the bind names every interface — but interface enumeration
#: came back empty, so this machine cannot say which address the far side should
#: use. R-D1's refusal, and the reason it exists is that the alternative is
#: writing the BIND into the payload, which is what S4's first hardware attempt
#: did: Windows dialled ``0.0.0.0:8765`` and reported ``runtime_unavailable``,
#: which reads exactly like the far install being down.
NO_DIAL_HOST_SENTENCE = (
    "the listener is bound to every interface but this machine offers no "
    "address to dial"
)

#: What :func:`cmd_gateway_introduce` prints, compactly, for a launcher to POST
#: as the backend grant's ``payload``. Declared as a tuple rather than left
#: implicit in a dict literal so the backend contract (S1 packet §4.1) has one
#: name on this side and a test can assert the key set without restating it.
GRANT_PAYLOAD_KEYS = (
    "peer_join_payload",
    "device_pair_payload",
    "install_id",
    "endpoints",
    "cert_fingerprint",
    "correlation",
)

#: The backend's own ceiling on a fulfil payload (S1 §4.1: compact, ≤ 4096
#: bytes). Asserted HERE, at the only place that builds the object, so an
#: envelope that would be rejected on POST is refused on this side with a reason
#: an operator can act on instead of failing as an opaque 400 later.
GRANT_PAYLOAD_MAX_BYTES = 4096


def _dial_target(store_root, endpoint: dict, *, args):
    """What a payload writer needs: the dial host, the full list, or a refusal.

    Returns ``(dial, endpoints, 0)`` or ``(None, [], exit_code)`` — the error
    branch is already rendered when it returns, so callers propagate the int.

    The refusal fires on exactly one condition: the listener is ``live`` or
    ``config`` — so this root IS reachable in principle — and enumeration
    produced nothing. ``unknown`` is deliberately NOT refused here, because each
    verb already answers that its own way and they disagree on purpose:
    ``introduce`` refuses it (its consumer is a machine that will dial), while
    ``pair`` and ``peers pair`` print :data:`LISTENER_OFF_SENTENCE` as a note and
    still mint (their consumer is a human who can go turn the listener on, and
    a code minted before the first boot is a legitimate thing to have).
    """

    endpoints = _candidate_endpoints(store_root)
    dial = _dial_host(endpoints)
    if dial is None and endpoint.get("source") in {"live", "config"}:
        return (
            None,
            [],
            emit_harness_error(
                RuntimeError("no_dial_host"),
                reason="no_dial_host",
                args=args,
                code="runtime_unavailable",
                message=(
                    f"{NO_DIAL_HOST_SENTENCE}. Writing the bind "
                    f"({endpoint.get('host')!r}) into the payload would tell the "
                    "other machine to dial an address that is not one. Name a "
                    "reachable interface in remote_gateway.listen, or fix why "
                    "this host enumerates none."
                ),
            ),
        )
    return dial, endpoints, 0
