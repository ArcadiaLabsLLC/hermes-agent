"""``hermes harness gateway id`` / ``rename``: the install-identity verbs.

Separate from ``gateway_commands`` (pairing, peers, devices) because the install
identity is a different store (``agent_runtime.gateway_identity``) with its own
error families.
"""

from __future__ import annotations

from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import _object_envelope, _print_stage42, emit_harness_error

__layer__ = "lanes"
__all__ = [
    "_GATEWAY_IDENTITY_ERROR_CODES",
    "_cmd_gateway_id",
    "_cmd_gateway_rename",
    "_gateway_identity_error",
    "_gateway_install_row",
]


# ── remote-gateway install identity (Stage 0b) ───────────────────────────────
#
# The operator's door onto `agent_runtime/gateway_identity.py`, which is the
# service half Stage 0a shipped and tested. These two handlers hold no rule of
# their own: WHAT a name may be, WHERE the record lives, and WHEN a record is
# minted are all decided there, because the greeting frame
# (`harness_parts/serve/boot_phases.py`, the `install` block) reads the same module and two
# answers to "what is this install called" is the whole failure this lane exists
# to prevent.
#
# **No authorization gate, and that is a decision rather than an omission.**
# The A4 mirror (`lifecycle_commands._console_denial`) exists so the CLI and
# `serve_rpc.handle_request` cannot answer differently about ONE service
# function — `perform_agent_create` / `perform_agent_retire` each have two
# doors. Stage 0b adds no RPC method, so there is one door and nothing to
# disagree with; a `CLI_CONSOLE` check here would gate a door against a
# predicate that allows every caller that exists, with no wire twin to stay
# honest against. The record is also not a level and not a secret. The day a
# paired DEVICE may rename an install, the door it comes through is a
# `gateway.*` method with a tier declaration (gateway plan Stage 1 / A5), and
# the gate goes there — where the caller is something the transport proved
# rather than the machine owner's own shell.


def _gateway_install_row(identity) -> dict:
    """One `gateway id` / `gateway rename` row.

    ``state`` is carried even on the success path, for the reason the frame
    block carries it: ``loaded`` and ``minted`` are different facts about the
    same root, and "minted" is how an operator learns this call is what created
    the identity rather than reading one that was already there.
    """

    row = {
        "install_id": identity.install_id,
        "display_name": identity.display_name,
        "state": identity.state,
        "created_at": identity.created_at,
        "path": identity.path,
    }
    # S2 (R-S2-1 / R-S2-2). Four facts a caller currently has to open a socket
    # to learn, answered by a cold CLI process:
    #
    # * ``capabilities`` — what this BUILD can do, so S3's request loop can
    #   feature-detect over the loopback argv lane without a listener anywhere.
    #   The same tuple the ``gateway`` block stamps on every greeting, read from
    #   the one module both sides import.
    # * ``endpoints`` / ``endpoints_source`` — where another machine should dial
    #   this one, and how confident that answer is. The SAME list a join payload
    #   advertises (``_candidate_endpoints``), so what this prints and what a
    #   hello offers cannot drift.
    # * ``listener`` — the live block minus nothing secret: an outcome, a host,
    #   a port and the fingerprint a client pins. The private key is not in it
    #   and there is no field for one.
    #
    # Best-effort as a whole: this verb is read-only by contract and Stage 4's
    # install picker runs it against roots it does not own, so a store it cannot
    # read degrades to the identity row rather than to an error.
    # * ``dial_host`` — the ONE address every payload writer hands out (R-D1),
    #   which is ``endpoints[0]`` and ``null`` when there is none. Printed as its
    #   own key rather than left for a reader to slice off the list, because the
    #   launcher renders it as a sentence and as a row label (R-D4: `Windows PC
    #   (192.168.1.203)`, `Listening on 192.168.1.203:8765 · all interfaces`) and
    #   two surfaces computing "the first one" independently is how a sheet ends
    #   up naming an address no payload contains. It is deliberately NOT the
    #   ``listener`` block: that one still reports the BIND, because "what is
    #   this listener on" and "what should another machine dial" are different
    #   questions and a wildcard is the honest answer to the first.
    try:
        from agent_runtime import paths
        from agent_runtime.gateway_capabilities import GATEWAY_CAPABILITIES
        from hermes_cli.harness_parts.gateway_commands import (
            _candidate_endpoints,
            _dial_host,
            _endpoint,
        )

        root = paths.store_root()
        endpoint = _endpoint(root)
        row["endpoints"] = _candidate_endpoints(root)
        row["endpoints_source"] = endpoint["source"]
        row["listener"] = {
            "host": endpoint.get("host"),
            "port": endpoint.get("port"),
            "source": endpoint["source"],
        }
        # The list this row already holds, not a second enumeration of it: since
        # D1b that walk reads the routing table, which is a process spawn.
        dial = _dial_host(row["endpoints"])
        row["dial_host"] = {"host": dial[0], "port": dial[1]} if dial else None
        row["capabilities"] = list(GATEWAY_CAPABILITIES)
    except Exception:
        row.setdefault("endpoints", [])
        row.setdefault("endpoints_source", "unknown")
        row.setdefault("listener", {"host": None, "port": None, "source": "unknown"})
        row.setdefault("dial_host", None)
        from agent_runtime.gateway_capabilities import GATEWAY_CAPABILITIES

        row.setdefault("capabilities", list(GATEWAY_CAPABILITIES))
    return row


#: ``error:<reason>`` → the harness error taxonomy. Split on the operator's next
#: MOVE, which is what the exit families mean:
#:
#: * ``absent`` — nothing to show (3). Not an infrastructure fault: a root that
#:   has never run a serve genuinely has no identity, and `gateway id` is
#:   read-only by contract, so it reports that instead of minting one behind an
#:   operator who only asked.
#: * ``malformed_record`` / ``record_without_id`` — the file exists and will not
#:   decode (1). Deliberately NOT a re-mint, per the asymmetry
#:   `gateway_identity._decode` documents: a paired device may still name the id
#:   in those bytes, and overwriting them to make a verb look tidy destroys the
#:   only copy of the join key.
#: * everything else is an I/O condition on the root — retryable in exactly the
#:   sense family 7 already means (an AV hold releases, an operator fixes a
#:   permission, the identical call then succeeds).
_GATEWAY_IDENTITY_ERROR_CODES = {
    "absent": "not_found",
    "malformed_record": "store_corrupt",
    "record_without_id": "store_corrupt",
    "empty_display_name": "invalid_payload",
}


def _gateway_identity_error(identity, *, args) -> int:
    reason = identity.state.split(":", 1)[1] if ":" in identity.state else identity.state
    code = _GATEWAY_IDENTITY_ERROR_CODES.get(reason, "runtime_unavailable")
    if reason == "absent":
        message = (
            f"{identity.path} does not exist: this runtime root has no gateway "
            "install identity yet. One is minted by the first `harness serve` "
            "against this root, or by `harness gateway rename <name>`."
        )
    else:
        # The typed reason travels verbatim. It is the same vocabulary the
        # `install` block puts on `ready`/`hello_ok`/`version`, so an operator
        # comparing a frame against a verb reads one word, not two spellings.
        message = f"{identity.path}: install identity is {identity.state}"
    return emit_harness_error(
        RuntimeError(identity.state), args=args, code=code, message=message
    )


def _cmd_gateway_id(args) -> int:
    """`harness gateway id` — which install is this, read WITHOUT minting one.

    The read-only half on purpose: a probe that mints leaves a side effect on a
    root it was only asked about, and Stage 4's install picker will run this
    against roots it does not own.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_identity import read_install_identity

    identity = read_install_identity(paths.store_root())
    if not identity.ok:
        return _gateway_identity_error(identity, args=args)
    # The identity is PER STORE ROOT, so "which root answered" is not decoration
    # here — it is the other half of the answer. A `gateway id` run against the
    # wrong root returns a perfectly well-formed identity for a runtime the
    # operator did not mean (the 2026-08-12 incident's shape, with an id in it).
    envelope = attach_root_observability(
        _object_envelope("gateway_install", _gateway_install_row(identity))
    )
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _cmd_gateway_rename(args) -> int:
    """`harness gateway rename <name>` — name this install; keep its id.

    Mints when the root has no record yet (``set_display_name``'s contract), so
    an operator can name an install before anything has ever booted against it.
    ``--dry-run`` therefore does NOT refuse an absent record — a real run would
    have succeeded there — but it does refuse an undecodable one, because a real
    run would refuse that too.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_identity import (
        clean_display_name,
        read_install_identity,
        set_display_name,
    )

    dry_run = bool(getattr(args, "dry_run", False))
    # Asked here rather than only inside the service because `--dry-run` must
    # answer the same way as a real run, and a preview cannot ask a writer it is
    # not allowed to call. Same authority function either way — not a second
    # copy of the rule.
    cleaned = clean_display_name(args.name)
    if not cleaned:
        return emit_harness_error(
            ValueError(str(args.name)),
            args=args,
            code="invalid_payload",
            message=(
                "A display name must contain at least one printable character. "
                "It is chrome for a picker row, not an identifier — clearing it "
                "would leave the install with nothing to show, so the rename is "
                "refused rather than applied as blank."
            ),
        )

    root = paths.store_root()
    if dry_run:
        identity = read_install_identity(root)
        if not identity.ok and not identity.state.endswith(":absent"):
            return _gateway_identity_error(identity, args=args)
        row = _gateway_install_row(identity)
        # The name the WRITE would land — normalised by the module's own rule,
        # never the raw argument.
        row["display_name"] = cleaned
    else:
        identity = set_display_name(root, args.name)
        if not identity.ok:
            return _gateway_identity_error(identity, args=args)
        row = _gateway_install_row(identity)
        # S2c: tell every paired install what we are called now. A display name
        # is CACHE at the far end (`gateway_peers`' split) — the install itself
        # is the authority for its own name — so a rename that nobody announced
        # left every peer showing the old one until its next hello, which for an
        # install that is rarely dialled could be days. Best-effort and
        # off-thread; a rename does not wait on a LAN.
        try:
            from agent_runtime.gateway_announce import announce_in_background

            announce_in_background(
                root, {"display_name": identity.display_name}
            )
        except Exception:  # noqa: BLE001 — courtesy channel, never the write
            pass

    envelope = attach_root_observability(_object_envelope("gateway_install", row))
    if dry_run:
        envelope["dry_run"] = True
    _print_stage42(envelope, args=args, default_output="json")
    return 0
