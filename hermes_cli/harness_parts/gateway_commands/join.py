"""``peers join``: the attested pin before any dial, the dial over the
candidate LIST, the hello validation, the record, the ack.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.gateway_endpoints import (
    DIAL_LOCAL_POLICY,
    LOCAL_POLICY_SENTENCE,
    candidate_endpoints,
    classify_dial_error,
)
from agent_runtime.root_observability import attach_root_observability
from agent_runtime.serde import is_hex
from hermes_cli.harness_support import (
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

from .devices import _install_and_certificate
from .join_payload import _parse_join_payload
from .refusals import (
    PhaseStop,
    _store_write_refusal,
    parse_correlation,
    store_refusal_error,
)

__layer__ = "lanes"


def cmd_gateway_peers_join(args) -> int:
    """``harness gateway peers join <payload|code>`` — redeem, and record BOTH halves.

    Run on install B, the second of R5's two operators. It dials install A's
    gateway listener with a PEER hello carrying the code and B's own identity, A
    redeems it and writes B's row, and the ``hello_ok`` carries the symmetric
    secret back so B can write A's row. One command, two stores, one edge.

    Three things it refuses rather than papers over:

    * a payload that names an ``install_id`` the far side does not turn out to
      have — that is a different install answering on that address, and
      recording the row anyway would pin a credential to the wrong machine;
    * a ``hello_ok`` with no ``peered`` block — the code did not redeem, and a
      row written on hope is a row whose every dial fails;
    * a dial that fails against EVERY advertised address, as
      ``runtime_unavailable`` (family 7, retryable), because a listener that is
      not up yet is exactly the condition where the identical command succeeds
      five seconds later. Since R-D3 the payload carries the far install's whole
      candidate list and this verb walks it in order, stopping at the first
      handshake; ``--host``/``--port`` still collapse that to one candidate, and
      the refusal names every address it tried with the exception class beside
      it, because "runtime_unavailable" alone is the same sentence for a
      listener that is down, a firewall that dropped the SYN, and an address
      that was never dialable.

    S2 adds a fourth, and it fires BEFORE any socket is opened: with
    ``--expect-fingerprint`` (R-S2-6), a payload whose ``cert_fingerprint``
    disagrees with the value the ACCOUNT attests is refused as
    ``tls_fingerprint_mismatch`` with nothing dialled and nothing written.
    Without the flag the verb keeps its trust-on-first-use pin and the ack says
    ``fingerprint_attested: false`` — a weaker posture that announces itself.

    D5h adds no refusal and one recording: the completed handshake is noted as a
    reachability fact (R-D16), and a run where no address answered is noted as
    the failure it was. See the two ``note_dial_result`` calls below.

    D6h splits the third refusal in two (R-D20). When every candidate failed and
    at least one ON-LINK address was refused by this machine's own operating
    system — ``EHOSTUNREACH`` against a host on one of our own subnets, which is
    macOS 15's Local Network privacy and not a route — the code is
    ``local_policy`` (family 2, not retryable: the next move is a permission
    granted HERE, and a client that retries burns a pairing code per attempt).
    Everything else keeps ``runtime_unavailable``. See
    :func:`classify_dial_error`.
    """

    # The verb's own flags are read HERE and handed to the phases as values, so
    # ``test_every_stage42_global_flag_is_honored`` sees each one read by the
    # handler (``--host`` / ``--port`` inside ``_parse_join_payload``).
    parsed = _parse_join_payload(getattr(args, "payload", None), args)
    if parsed is None:
        return 2
    join = Join(
        args,
        parsed,
        expected=str(getattr(args, "expect_fingerprint", "") or "").strip().lower(),
        timeout_seconds=float(getattr(args, "timeout", None) or 20.0),
    )
    try:
        join.attest()
        join.correlation = parse_correlation(args)
        row = join.build()
    except PhaseStop as stop:
        return stop.code
    envelope = attach_root_observability(_object_envelope("gateway_peer", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


class Join:
    """One ``peers join`` run, as the phases its comment map named.

    ``parse -> attest -> correlation -> identity -> dial -> validate_hello ->
    record -> ack``. A phase that refuses raises :class:`PhaseStop` carrying the
    already-rendered exit code; the verb's handler turns it back into the return
    value, and is the one place that prints.
    The dial loop's rule — a certificate mismatch is terminal, a dial failure
    moves on — lives in :meth:`attempt` alone.
    """

    def __init__(self, args, parsed: dict, *, expected: str, timeout_seconds: float) -> None:
        from agent_runtime import paths

        self.args = args
        self.parsed = parsed
        self.expected = expected
        self.timeout_seconds = timeout_seconds
        self.correlation: str | None = None
        self.root = paths.store_root()
        self.attempts: list[str] = []
        # R-D20: the addresses this run could not reach because THIS machine's
        # OS refused to put a packet on its own network. Collected rather than
        # counted, because the refusal has to name them — an operator granting a
        # Local Network permission wants to see the address the permission is for.
        self.policy_refused: list[str] = []
        self.reply: Any = None
        self.dialled: dict | None = None

    def build(self) -> dict[str, Any]:
        """``identity -> dial -> validate_hello -> record -> ack``."""

        self.identity()
        self.dial()
        self.validate_hello()
        return self.ack(self.record())

    def attest(self) -> None:
        """The attested pin (R-S2-6), decided BEFORE anything is dialled.

        Without ``--expect-fingerprint`` this verb is trust-on-first-use: it pins
        whatever fingerprint the payload carried, which is exactly as strong as
        the channel the operator carried the payload through. That is the manual
        ceremony's posture and it stays unchanged — but the ack now SAYS so
        (``fingerprint_attested: false``), because a weaker posture nobody
        announces is a weaker posture nobody notices.

        With the flag, the fingerprint came from the account (S3 passes
        ``DeviceOut.gateway_cert_fingerprint``, which the backend holds because
        the far install told the account, signed in). A payload that disagrees is
        refused HERE, before a socket exists: dialling first and comparing after
        would hand an impostor a completed TLS handshake and a timing signal, and
        would burn an attempt on an answer that cannot change.
        """

        expected = self.expected
        self.attested = bool(expected)
        if not self.attested:
            return
        if not is_hex(expected, 64):
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError("tls_fingerprint_invalid"),
                    reason="tls_fingerprint_invalid",
                    args=self.args,
                    code="invalid_payload",
                    message=(
                        # The reason word LEADS the sentence rather than riding a
                        # field, because ``emit_harness_error`` carries only the
                        # exception CLASS in ``safe_details`` — so the message is
                        # the one channel this lane has for a machine-readable
                        # reason, and R-IP17 asks for one enumerated set of them.
                        "tls_fingerprint_invalid: --expect-fingerprint is the "
                        "account's attested certificate fingerprint and must be 64 "
                        f"lowercase hex characters (sha256); got {len(expected)}."
                    ),
                )
            )
        offered = str(self.parsed["cert_fingerprint"] or "").strip().lower()
        if offered != expected:
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError("tls_fingerprint_mismatch"),
                    reason="tls_fingerprint_mismatch",
                    args=self.args,
                    code="invalid_payload",
                    message=(
                        # R-IP17's word first, for the reason above.
                        "tls_fingerprint_mismatch: the join payload offers "
                        f"certificate {offered or '(none)'} and the account attests "
                        f"{expected}. Nothing was dialled and no row was written: a "
                        "payload whose fingerprint disagrees with the account is "
                        "either stale or is not the install it names."
                    ),
                )
            )
        # From here the PIN is the attested value, not the payload's — they are
        # equal, and taking the attested one is what makes that an invariant
        # rather than a coincidence a later edit could break.
        self.parsed["cert_fingerprint"] = expected

    def identity(self) -> None:
        resolved, code_or_error = _install_and_certificate(self.args)
        if resolved is None:
            raise PhaseStop(code_or_error)
        self.install, self.certificate = resolved
        self.endpoints = candidate_endpoints(self.root)

    def dial(self) -> None:
        """The dial, over the candidate LIST (R-D3).

        One address used to be the whole of it, and that address was whatever
        the payload's ``host`` said — which, before R-D1, could be a bind. Now
        the payload carries every address the far install can offer, in the
        order IT ranked them, and this loop takes the first handshake that
        completes. The two failure kinds are :meth:`attempt`'s.

        ``--timeout`` is PER CANDIDATE, not a budget for the whole loop: an
        operator who allows twenty seconds for a handshake means twenty seconds
        for a handshake, and dividing it by a list length they did not write
        would make the flag mean something different on every payload.
        """

        for candidate in self.parsed["endpoints"]:
            if self.attempt(candidate):
                return
        self.refuse_unanswered()

    def attempt(self, candidate: dict) -> bool:
        """One candidate. Two failure kinds, and telling them apart is the point:

        * a DIAL failure (refused, timed out, no route) is about THIS ADDRESS,
          and the next candidate may be on a segment that works. Recorded and
          moved past (``False``).
        * a certificate that does not match the pin is about the far INSTALL'S
          IDENTITY, and no address can change the answer. Terminal,
          immediately, because retrying it means offering the same wrong
          certificate three more chances and burning three timeouts to reach the
          same refusal.
        """

        from agent_runtime.serve_socket.client import ServeSocketClient
        from agent_runtime.serve_socket.hello import ServeCertificatePinMismatch

        connection = ServeSocketClient(
            candidate["host"],
            candidate["port"],
            timeout_seconds=self.timeout_seconds,
            tls=True,
            cert_fingerprint=self.parsed["cert_fingerprint"],
        )
        try:
            connection.connect()
            self.reply = connection.peer_join_hello(
                peer_code=self.parsed["peer_code"],
                peer_install_id=self.install.install_id,
                display_name=self.install.display_name,
                endpoints=self.endpoints,
                cert_fingerprint=self.certificate.fingerprint,
            )
            self.dialled = candidate
        except ServeCertificatePinMismatch as exc:
            raise PhaseStop(
                emit_harness_error(
                    exc,
                    args=self.args,
                    code="invalid_payload",
                    reason="tls_fingerprint_mismatch",
                    message=(
                        # R-IP17's reason word first, as the pre-dial check
                        # spells it, so one enumerated vocabulary covers both the
                        # payload that disagreed with the account and the
                        # certificate that disagreed with the payload.
                        "tls_fingerprint_mismatch: "
                        f"{candidate['host']}:{candidate['port']} presented a "
                        "certificate that is not the one this payload pins. No "
                        "other address was tried and no row was written: a "
                        "mismatched certificate is a statement about the install, "
                        "not about the address it answered on."
                    ),
                )
            ) from exc
        except Exception as exc:
            where = f"{candidate['host']}:{candidate['port']}"
            word = classify_dial_error(exc, str(candidate["host"]))
            if word == DIAL_LOCAL_POLICY:
                self.policy_refused.append(where)
            # The word replaces the exception CLASS rather than riding beside
            # it: ``OSError`` is what the Mac's receipt said at 20:19:25, and it
            # is the single least useful thing that could be printed about a
            # kernel that knows exactly where that host is and declines to send.
            said = word if word == DIAL_LOCAL_POLICY else type(exc).__name__
            self.attempts.append(f"{where} ({said})")
        finally:
            connection.close()
        return self.reply is not None

    def refuse_unanswered(self) -> None:
        """Every address tried, named, with the exception class beside it.

        The receipt S4's hardware attempt did not have. "runtime_unavailable" on
        its own is unattributable from the far machine: it reads identically
        whether the listener is down, the firewall dropped the SYN, or (the
        actual answer that day) the address was never dialable in the first
        place.
        """

        from agent_runtime.gateway_peers import note_dial_result

        tried = ", ".join(self.attempts) or "(none — the payload offered no address)"
        install_id = self.parsed["install_id"] or ""
        # R-D20, and it fires only when NOTHING answered and at least one
        # on-link address was refused by this machine's own OS. Both halves
        # matter: a run where a second candidate completed the handshake has
        # nothing to say to the operator, and a run where every candidate merely
        # timed out is still the network's answer.
        #
        # The note leads with the word rather than with the list — the one place
        # in this stage where the cache string and the printed ``Tried:`` list
        # deliberately differ (D5h made them identical). The cache row is what
        # the launcher's sheet reads to choose a sentence, and a word buried
        # behind an address list is a word a prefix match cannot find.
        if self.policy_refused:
            named = ", ".join(self.policy_refused)
            note_dial_result(self.root, install_id, ok=False, error=f"{DIAL_LOCAL_POLICY}: {named}")
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError(DIAL_LOCAL_POLICY),
                    reason=DIAL_LOCAL_POLICY,
                    args=self.args,
                    code=DIAL_LOCAL_POLICY,
                    message=(
                        f"{named}: {LOCAL_POLICY_SENTENCE}. Nothing was sent: the "
                        "kernel answered EHOSTUNREACH for an address on one of this "
                        "machine's own subnets, which is a permission and not a "
                        f"route. Tried: {tried}."
                    ),
                )
            )
        # R-D16's failing half, through the door ``dial_peer`` and the announce
        # fan-out record through, with the SAME string the refusal prints — so
        # the cache row and the operator's sentence cannot end up disagreeing
        # about which addresses were tried. A no-op when the payload named no
        # install id: there is no row for the word to land on.
        note_dial_result(self.root, install_id, ok=False, error=tried)
        raise PhaseStop(
            emit_harness_error(
                RuntimeError("no_candidate_answered"),
                reason="no_candidate_answered",
                args=self.args,
                code="runtime_unavailable",
                message=(
                    "could not complete the peer handshake with any advertised "
                    f"address. Tried: {tried}. The other install's gateway listener "
                    "must be running, reachable, and presenting the certificate "
                    "whose fingerprint is in the payload."
                ),
            )
        )

    def validate_hello(self) -> None:
        """The three hello validations, in order; each refuses with its own word."""

        reply = self.reply
        if not isinstance(reply, dict) or reply.get("event") != "hello_ok":
            reason = (reply or {}).get("reason") or "no hello_ok"
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError(str(reason)),
                    args=self.args,
                    code="invalid_payload",
                    message=(
                        f"the other install refused the join ({reason}). Every credential "
                        "failure on that lane reports the same reason on purpose, so the "
                        "cause is one of: the code expired, it was already redeemed, it "
                        "was a DEVICE code, or the install is locked out after repeated "
                        "failed attempts. Mint a fresh code with `harness gateway peers "
                        "pair` over there."
                    ),
                )
            )
        self.peered = reply.get("peered")
        self.remote = reply.get("install") if isinstance(reply.get("install"), dict) else {}
        self.remote_id = str(self.remote.get("install_id") or "").strip()
        if not isinstance(self.peered, dict) or not self.peered.get("peer_secret"):
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError("no_peer_secret"),
                    reason="no_peer_secret",
                    args=self.args,
                    code="invalid_payload",
                    message=(
                        "the other install completed a handshake but returned no peer "
                        "secret, so this side has no credential to store. That frame is "
                        "the only time the secret is ever sent; re-run the ceremony with "
                        "a fresh code."
                    ),
                )
            )
        named = self.parsed["install_id"]
        if named and self.remote_id and named != self.remote_id:
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError("install_id_mismatch"),
                    reason="install_id_mismatch",
                    args=self.args,
                    code="invalid_payload",
                    message=(
                        f"the payload names install {named!r} but "
                        f"{self.dialled['host']}:{self.dialled['port']} answered as "
                        f"{self.remote_id!r}. Something else is on that address; the "
                        "row was NOT written."
                    ),
                )
            )

    def record(self):
        """Recording it: the half that failed on hardware (R-D14).

        Everything before this phase worked on the operator's PC on 2026-09-04.
        The code was granted, the dial reached 192.168.1.39:8765, the far
        install redeemed and returned the secret — and then this write raised
        ``[WinError 5]``, four times in five minutes. It reached the sheet as
        ``runtime_unavailable`` → ``no_route`` → "Unreachable": a claim about the
        network, for a DACL on a local directory.

        So a write refusal here is its OWN reason with its own family, and the
        message names the file. Both doors give the same answer —
        ``record_peer`` catches OSError around its locked write and returns a
        refusal, but the cache touch and the event append it runs after
        releasing the lock are outside that span, and an operator must not get
        two different stories depending on which line inside the store surfaced
        the same permission.
        """

        from agent_runtime.gateway_peers import note_dial_result, peer_store_path, record_peer
        from agent_runtime.serve_gateway_auth import StoreRefusal

        peers = peer_store_path(self.root)
        try:
            outcome = record_peer(
                self.root,
                peer_install_id=self.remote_id or self.parsed["install_id"] or "",
                secret=str(self.peered["peer_secret"]),
                display_name=self.remote.get("display_name"),
                # The candidate that ANSWERED, not the payload's first row. The
                # row is this install's memory of where the far one is, so
                # recording an address the loop walked past would make every
                # later dial start with a failure this run already proved.
                endpoints=[dict(self.dialled)],
                cert_fingerprint=self.parsed["cert_fingerprint"],
                # Read off the frame, never derived. The far side computed it at
                # redemption; a second derivation here would make the two ends of
                # one edge lapse at two different moments. ``None`` on every edge
                # the manual ceremony mints, and on every far install predating S2.
                expires_at=self.peered.get("expires_at"),
            )
        except OSError as exc:
            raise PhaseStop(_store_write_refusal(exc, args=self.args, store_path=peers)) from exc
        if isinstance(outcome, StoreRefusal):
            raise PhaseStop(store_refusal_error(outcome, args=self.args, store_path=peers))

        # ── and the handshake IS a reachability fact (R-D16) ─────────────────
        #
        # Until D5h ``note_dial_result(ok=True)`` had exactly one caller — the
        # chat lane's ``dial_peer`` — so a row this verb wrote kept whatever
        # word the last chat dial had left on it. On the operator's PC that read
        # ``unreachable_since 18:03:17`` at 20:19:19, after a join that dialled
        # 192.168.1.39:8765, redeemed, and stored the secret. The launcher reads
        # the cache, called the edge unusable, and re-requested a pairing code
        # every minute for an edge that was already up — minting codes on the
        # far side for nothing.
        #
        # Recorded AFTER the trust row rather than before it: a cache row for an
        # install this store holds no credential for would describe an edge no
        # dial could use. And through the same door the chat lane and the
        # announce fan-out use, so "reachable" means one thing across the
        # runtime rather than one thing per lane — the event on the flip, the
        # endpoint list untouched, and the cache written under the directory
        # lock ``_touch_cache`` already takes.
        note_dial_result(self.root, outcome.peer_install_id, ok=True)
        return outcome

    def ack(self, outcome) -> dict[str, Any]:
        row = outcome.payload()
        # Which posture wrote this row, said out loud on the ack. An operator (and
        # S3's request loop) reading a stored edge should not have to remember
        # which flags the join was run with to know whether the pin was attested
        # by the account or merely copied off a payload.
        row["fingerprint_attested"] = self.attested
        if self.correlation is not None:
            row["correlation"] = self.correlation
        reached_at = self._reached_at()
        if reached_at is not None:
            row["reached_at"] = reached_at
        # What the OTHER side now holds about us, so one ack answers "is this
        # edge symmetric" without an operator walking to the other machine to
        # check.
        row["this_install"] = {
            "install_id": self.install.install_id,
            "display_name": self.install.display_name,
            "endpoints": self.endpoints,
            "cert_fingerprint": self.certificate.fingerprint,
        }
        if not self.endpoints:
            row["note"] = (
                "this root advertised no dialable gateway endpoint, so the other "
                "install recorded the edge with no address for it. Calls from here "
                "to there work; calls from there to here will not until this root's "
                "remote_gateway.listen names a reachable interface and a `peers "
                "join` is re-run."
            )
        return row

    def _reached_at(self) -> dict[str, Any] | None:
        """D12 — the far install's own MEASUREMENT of where this dial landed.

        Read off the ``hello_ok`` and never re-derived here. ``endpoints`` on
        the row is what THIS side dialled: a candidate off a list, correct only
        as far as the list was. ``reached_at`` is what the accepting kernel bound
        the connection to, which is the address that demonstrably carries
        packets from here to there. They differ exactly where it matters — a
        wildcard-bound install with several interfaces, an alias, a
        port-forward — and where they differ the measurement is the one worth
        publishing (R-D7).

        ``None`` when the far side predates this field or could not answer:
        never backfilled from ``dialled``, because a fabricated measurement is
        worse than no measurement — it would look like proof and be an echo of
        the guess.
        """

        reached_at = self.reply.get("reached_at")
        if (
            isinstance(reached_at, dict)
            and isinstance(reached_at.get("host"), str)
            and reached_at.get("host")
            and isinstance(reached_at.get("port"), int)
        ):
            return {"host": reached_at["host"], "port": int(reached_at["port"])}
        return None
