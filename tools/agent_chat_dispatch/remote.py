"""The cross-install leg (Gateway Stage 7): the peer params, the frame reader, the dial / ack / read / settle loop.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .child import KILL_GRACE_SECONDS, SERVE_STDOUT_EVENT, _detached_error_text, parse_child_payload

logger = logging.getLogger(__name__)

__layer__ = "lanes"


#: Gateway Stage 7 (R8), the "bounded per-attempt dial timeout" half. How long
#: ONE attempt waits for a paired install to complete TCP, TLS and the peer
#: hello. Short on purpose: an install that is off, asleep or moved answers
#: nothing, and eight attempts at a generous timeout would take an hour to
#: converge on a fact that is knowable in seconds. It is not the budget for the
#: TURN — see :data:`~agent_runtime.serve_socket.ServeSocketClient.set_timeout`.
PEER_DIAL_TIMEOUT_SECONDS = 15.0


#: The gap between dial attempts. Deliberately flat rather than exponential:
#: the case this cap exists for is a machine that is off, and backing off
#: geometrically would turn a converge-in-a-minute answer into a converge-in-an-
#: hour one for no information gained. With the cap at
#: ``MAX_DELIVERY_ATTEMPTS`` an offline install settles in roughly two minutes,
#: which is the same order as the local lane's own attempt-cap convergence.
PEER_RETRY_BACKOFF_SECONDS = 5.0


def build_peer_execute_params(dispatch_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """The ``peer.agent_chat.execute`` params for one cross-install dispatch.

    The mirror of :func:`build_dispatch_argv`, and the differences between the
    two are the whole of what "the far side runs it" costs:

    * ``turn_request_id`` is derived from the DISPATCH ID rather than minted per
      attempt, and that is what makes R8's retry posture safe. A dial that dies
      after install B accepted the turn is a transport failure the sender must
      retry; if each retry carried a fresh id, B would run the turn again. With
      the dispatch's own id, B's reservation and its turn journal answer the
      second attempt ``idempotent_replay`` with the first attempt's ack — the
      exactly-once property Stage 3 built, used here for the first time by
      something that actually retries. It is the same derivation
      ``dispatch_delivery.delivery_client_message_id`` uses on the sender's own
      side, for the same reason.
    * The relay CHAIN does not travel. Locally the chain is seeded in-process by
      the handler and forwarded so depth and cycle detection run at B's
      chokepoint; across an install boundary it would be an assertion B cannot
      check, and a chain a sender can understate is a cycle guard that can be
      talked past. So a cross-install dispatch is a fresh chain root on B —
      which is what a DETACHED dispatch already is locally (the 2026-08-03 relay
      ruling), applied one boundary further out. The honest consequence is
      named in the plan's notes rather than hidden: A→B→A across two installs is
      not detected as a cycle by either side's guard.
    * There is no ``clarify_token`` and no ``requested_by``. The first is a
      ticket in THIS install's store and means nothing on the other one; the
      second is the field install B decides for itself, from the connection.
    """

    params: dict[str, Any] = {
        "turn_request_id": str(spec.get("client_message_id") or f"agent-dispatch-{dispatch_id}"),
        "target": str(spec["remote_target"]),
        "message": str(spec["message"]),
        "max_seconds": float(spec["max_seconds"]),
    }
    if spec.get("title"):
        params["title"] = str(spec["title"])
    if spec.get("session_id"):
        params["session_id"] = str(spec["session_id"])
    if spec.get("new_session") is True:
        params["new_session"] = True
    return params


def _remote_reply_payload(connection: Any, request_id: str) -> dict[str, Any] | None:
    """Read one accepted remote turn's frames to its exit, and parse the payload.

    Install A does here exactly what the local launcher does with a local turn,
    and that is the point: the ack is an ACCEPT (Stage 3's constraint — B's
    dispatcher answers the method lane inline, so it cannot run a turn there),
    and the turn's real output rides the per-request frame lane under the
    returned ``request_id``. The lines are re-joined and handed to
    :func:`parse_child_payload` — the same function the local child's stdout
    goes through — so a remote turn's payload and a local turn's payload are
    read by one implementation rather than two that agree today.

    ``None`` means the connection ended before the exit frame. The caller treats
    that as TRANSPORT, not as a result, which is the whole R8 distinction.

    **The stdout event is called ``line``, not ``stdout``**, and this comment is
    here because the obvious guess is wrong and cost the Stage 7 acceptance a
    round: ``serve.py`` builds its two proxies as
    ``_LineFrameProxy(frames, "line")`` and ``_LineFrameProxy(frames, "stderr")``
    — the OUT stream is the unqualified one and only the error stream is named
    after itself. Spelled as a constant so the next reader is told rather than
    having to find it.
    """

    lines: list[str] = []
    while True:
        frame = connection.read_frame()
        if frame is None:
            return None
        if frame.get("id") != request_id:
            # Another request's frames, or a push on the same socket. Not ours.
            continue
        event = frame.get("event")
        if event == SERVE_STDOUT_EVENT:
            lines.append(str(frame.get("line") or ""))
        elif event == "exit":
            return {
                "payload": parse_child_payload("\n".join(lines)),
                "code": frame.get("code"),
            }


def _run_remote_dispatch(dispatch_id: str, spec: dict[str, Any]) -> None:
    """Perform a dispatch whose target lives on a PAIRED INSTALL (Stage 7).

    The substitution is for the child PROCESS and for nothing else. The row was
    written before this ran, is written again when this finishes, and the
    delivery drain forges the answer into the sender's chat afterwards — all
    unchanged. What changes is that the turn happens on install B, under B's
    admission rules, recorded in B's own chat store.

    **R8's posture, and the one line that decides which class a failure is in.**
    A failure to REACH the install is transport: nothing was refused, nothing
    ran, and the same attempt tomorrow might work — so it costs an attempt out
    of :data:`~agent_runtime.dispatch_store.MAX_DELIVERY_ATTEMPTS` and retries.
    A failure the far install ANSWERED with is deterministic: an unknown
    persona, an admission refusal, a revoked edge are pure functions of B's
    state that another attempt cannot change, so the row settles immediately —
    the same fail-fast rule ``_terminal_forge_rejections`` applies on the
    delivery side, and for the same reason (burning eight attempts ends with the
    operator reading "attempts ran out" instead of the verdict that happened).

    The attempts are spent HERE, inside one supervised run, rather than by
    re-queueing the row on the drain's cadence. That holds a slot on the
    dispatch pool for as long as the retries take — which is the honest cost and
    a small one: a LOCAL dispatch holds its slot for the whole of a
    thirty-minute turn, so a remote one holding it for two minutes of dialling
    is well inside what the cap already admits. The alternative wanted a durable
    copy of the spec, a second claim protocol and a second attempt counter on a
    row that already has one, to buy a property (surviving a serve restart
    mid-dial) that the local lane does not have either.
    """

    from agent_runtime import dispatch_store
    from agent_runtime.gateway_peers import dial_peer
    from agent_runtime.gateway_targets import peer_store_root

    install_id = str(spec["remote_install_id"])
    display = str(spec.get("remote_display_name") or install_id)
    budget = float(spec["max_seconds"])
    params = build_peer_execute_params(dispatch_id, spec)
    root = peer_store_root()

    failures: list[str] = []
    attempts = 0
    while attempts < dispatch_store.MAX_DELIVERY_ATTEMPTS:
        attempts += 1
        connection = None
        try:
            connection, _hello = dial_peer(
                root, install_id, timeout_seconds=PEER_DIAL_TIMEOUT_SECONDS
            )
        except Exception as exc:
            # ``dial_peer`` raises ``ConnectionError`` for every unreachable
            # endpoint and for a revoked or credential-less row. The revoked
            # case is already refused deterministically at send time, so what
            # reaches here is transport — and anything else that raises out of a
            # dial is transport too, because a dial that raised did not run a
            # turn.
            failures.append(f"attempt {attempts}: {type(exc).__name__}: {exc}")
            if attempts < dispatch_store.MAX_DELIVERY_ATTEMPTS:
                time.sleep(PEER_RETRY_BACKOFF_SECONDS)
            continue

        try:
            rid = f"peer-exec-{dispatch_id}"
            connection.send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "method": "peer.agent_chat.execute",
                    "params": params,
                }
            )
            ack = None
            while True:
                frame = connection.read_frame()
                if frame is None:
                    break
                if frame.get("id") == rid and (
                    "result" in frame or "error" in frame
                ):
                    ack = frame
                    break
            if ack is None:
                failures.append(f"attempt {attempts}: the edge closed before an ack")
                if attempts < dispatch_store.MAX_DELIVERY_ATTEMPTS:
                    time.sleep(PEER_RETRY_BACKOFF_SECONDS)
                continue
            if "error" in ack:
                # THE far install answered. Deterministic — settle now.
                error = ack["error"] or {}
                reason = str((error.get("data") or {}).get("reason") or "")
                dispatch_store.record_completion(
                    dispatch_id,
                    state=dispatch_store.STATE_ERROR,
                    error=(
                        f"{display} refused the request: "
                        f"{str(error.get('message') or 'no reason given')[:300]}"
                    ),
                    remote={
                        "install_id": install_id,
                        "attempts": attempts,
                        "reason": reason or "peer_refused",
                    },
                )
                return

            result = ack.get("result") or {}

            # **A REPLAY carries no frames, and waiting for them is a hang.**
            # Found by the acceptance rather than reasoned to: B's per-request
            # frames go to the sink of the connection that ASKED, so a turn
            # started on a socket that then died emits nothing on the socket
            # that retries — the reader would sit until its own timeout for an
            # exit frame that already happened somewhere else. This arm is
            # reached exactly when the retry posture worked (the same
            # ``turn_request_id`` stopped B running the agent twice), so it is
            # the success path of the property, not an error path.
            if result.get("idempotent_replay"):
                if not result.get("settled"):
                    # Accepted by an earlier attempt and STILL RUNNING over
                    # there. Nothing to read and nothing to fix; another attempt
                    # after the backoff may find it settled.
                    failures.append(
                        f"attempt {attempts}: the turn is still running on {display}"
                    )
                    if attempts < dispatch_store.MAX_DELIVERY_ATTEMPTS:
                        time.sleep(PEER_RETRY_BACKOFF_SECONDS)
                    continue
                code = result.get("exit_code")
                dispatch_store.record_completion(
                    dispatch_id,
                    state=(
                        dispatch_store.STATE_COMPLETED
                        if code == 0
                        else dispatch_store.STATE_ERROR
                    ),
                    error=(
                        ""
                        if code == 0
                        else (
                            f"{display} ran the turn and it ended with code {code}."
                        )
                    ),
                    # Honest about what is NOT here: the reply text went to the
                    # connection that started the turn, and that connection is
                    # gone. The thread on the other install has it.
                    reply=(
                        f"[{display} ran this turn on an earlier attempt; its "
                        "answer is in the thread on that install — the "
                        "connection that carried it did not survive.]"
                    ),
                    remote={
                        "install_id": install_id,
                        "attempts": attempts,
                        "reason": "peer_turn_replayed",
                    },
                )
                return

            # Accepted, fresh. The turn's own budget governs the read from here
            # — the dial timeout was about reaching the machine, not about how
            # long its agent may think.
            connection.set_timeout(budget + KILL_GRACE_SECONDS)
            request_id = str(result.get("request_id") or "")
            if not request_id:  # pragma: no cover - the ack always carries one
                failures.append(f"attempt {attempts}: the ack named no request id")
                continue
            answered = _remote_reply_payload(connection, request_id)
        except Exception as exc:
            failures.append(f"attempt {attempts}: {type(exc).__name__}: {exc}")
            if attempts < dispatch_store.MAX_DELIVERY_ATTEMPTS:
                time.sleep(PEER_RETRY_BACKOFF_SECONDS)
            continue
        finally:
            try:
                connection.close()
            except Exception:  # pragma: no cover - defensive
                pass

        if answered is None:
            # The edge died mid-turn. Retrying is SAFE and this is the reason
            # ``turn_request_id`` is derived from the dispatch id: the next
            # attempt presents the same key, and B replays its first ack rather
            # than running the agent twice.
            failures.append(f"attempt {attempts}: the edge closed mid-turn")
            if attempts < dispatch_store.MAX_DELIVERY_ATTEMPTS:
                time.sleep(PEER_RETRY_BACKOFF_SECONDS)
            continue

        payload = answered["payload"]
        remote = {"install_id": install_id, "attempts": attempts}
        if payload is None:
            dispatch_store.record_completion(
                dispatch_id,
                state=dispatch_store.STATE_UNKNOWN,
                error=(
                    f"{display} ran the turn and its process exited with code "
                    f"{answered['code']} without a reply payload; the outcome is "
                    "unknown. Anything it wrote is in its own chat thread."
                ),
                remote=remote,
            )
            return

        ok = bool(payload.get("ok")) and answered["code"] == 0
        from agent_runtime.turn_visibility import TurnVisibility

        dispatch_store.record_completion(
            dispatch_id,
            state=(
                dispatch_store.STATE_COMPLETED if ok else dispatch_store.STATE_ERROR
            ),
            reply=str(payload.get("reply") or ""),
            error="" if ok else _detached_error_text(payload),
            target_session_id=str(
                payload.get("session_id") or payload.get("chat_session_id") or ""
            ),
            total_tokens=payload.get("total_tokens"),
            visibility=TurnVisibility.from_payload(payload).as_dict(),
            remote=remote,
            # Stage P4 (R-P3). The far install minted these — it is the only one
            # that could, because a handle is a digest of bytes it alone holds —
            # and this is the ONLY moment they are in reach of the row that has
            # to outlive them. The reply text lands in the sender's transcript
            # with `MEDIA:` lines naming paths on B's disk; without the map, A's
            # media scope can never name those pictures and every fetch answers
            # `unknown_handle`. Read here, validated by `dispatch_store` (shape)
            # and by `media_handles` (grammar, allowlist, cap) — never trusted.
            media=payload.get("media"),
        )
        return

    # Every attempt was transport. R8's cap, converging on a terminal answer the
    # sender is actually TOLD — see ``dispatch_store.REMOTE_UNREACHABLE_REASON``
    # for why this is not a ``dropped`` delivery.
    logger.info(
        "dispatch %s: %s unreachable after %d attempts",
        dispatch_id,
        install_id,
        attempts,
    )
    dispatch_store.record_completion(
        dispatch_id,
        state=dispatch_store.STATE_ERROR,
        error=(
            f"{display} did not answer: {attempts} attempts over "
            f"~{attempts * PEER_RETRY_BACKOFF_SECONDS:.0f}s reached no endpoint on "
            f"its paired row ({dispatch_store.REMOTE_UNREACHABLE_REASON}). The "
            "install may be off, asleep, or moved to a new address — its "
            f"operator re-runs `harness gateway peers pair` to update it. Last: "
            f"{failures[-1][:200] if failures else 'no detail'}"
        ),
        remote={
            "install_id": install_id,
            "attempts": attempts,
            "reason": dispatch_store.REMOTE_UNREACHABLE_REASON,
        },
    )
