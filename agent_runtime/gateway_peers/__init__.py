"""Per-PEER credentials for the gateway listener: pair, join, verify, revoke.

The sibling of ``serve_gateway_auth``. Where that module answers "which paired
DEVICE is this" — a phone, a tablet, something with a screen and an operator
holding it — this one answers "which paired INSTALL is this": another hermes
runtime, on another machine, that an operator approved on BOTH sides.

``<store_root>/gateway/peers.json``, beside ``install.json``, ``devices.json``
and ``pairing.json``. One row per peer::

    {peer_install_id, display_name, endpoints, cert_fingerprint,
     secret_verifier, approved_at, last_seen, revoked, revoked_at, expires_at}

Two kinds of field in one row: TRUST, and CACHE (R-IP14)
---------------------------------------------------------

Every key above is one of exactly two things, and the split is worth stating
because the file's own name covers only half of it:

* **Trust** — ``peer_install_id``, ``secret_verifier``, ``approved_at``,
  ``revoked``, ``revoked_at``, ``expires_at``. Written by a ceremony
  (:func:`redeem_peer_code`, :func:`record_peer`) or by :func:`revoke_peer`, and
  by nothing else. The network never moves one of these, and that is what makes
  this a credential store rather than a directory. ``expires_at`` (S2, R-IP15 as
  amended) is trust for the sharpest version of that reason: a peer that could
  push its own expiry out would hold a credential with no end, which is exactly
  the authority ``revoked`` denies it. ``None`` means never and is what the
  manual ceremony keeps minting; a thirty-day stamp is what an ``introduce``
  mints, and BOTH ends of the edge hold the same one because it rides
  ``hello_ok.peered.expires_at`` rather than being recomputed on the far side.
* **Cache** — ``display_name``, ``endpoints``, ``cert_fingerprint``,
  ``last_seen``. What the far install TOLD us, at pairing or on a hello. The
  install itself is the authority for its own name, addresses and certificate;
  these are copies, and a copy that has gone stale is a stale copy rather than
  a wrong answer — provided every reader knows which kind it is holding.

The two sets are declared as :data:`PEER_ROW_TRUST_FIELDS` and
:data:`PEER_ROW_CACHE_FIELDS` beside :func:`peer_row`, and a test asserts they
partition its keys exactly — so a new field cannot be added without being
classified. That is the whole mechanism: a label nothing checks is a comment.

The honest residue, stated rather than fixed here: ``last_seen`` is a cache
fact the NETWORK writes into a trust file on every verified hello
(:func:`note_peer_seen`). S2c moves it and the other cache fields to a sidecar
(``peers_cache.json``, R-IP12a), at which point this file is trust only. Until
then the write stays exactly where it is — the frozensets are what will let
that move be mechanical rather than archaeological.

R5, and why the ceremony has two operators in it
-------------------------------------------------

R5 is **ADOPTED at its recommendation** (primary plan §5, under the operator's
"implement it all" directive): *each install⇄install edge is explicitly
approved (both sides), and agents can never initiate pairing.* Everything about
the shape below follows from that sentence.

"Both sides" is not decoration and it is not achieved by asking twice. It is
achieved by making the ceremony physically require a human at each end: install
A's operator runs ``harness gateway peers pair`` and reads eight characters off
their own terminal; install B's operator types those characters into ``harness
gateway peers join`` on a different machine. Neither half can be performed by
the other install, because A never learns B's address until B dials, and B
cannot mint a code in A's store. **There is no verb that pairs an install
without an operator at both ends**, which is a stronger property than an
approval flag on a row: a flag can be set by whatever wrote the row.

"Agents can never initiate pairing" — and the residual, named honestly
---------------------------------------------------------------------

The peer verbs are CLI verbs and have NO wire twin: there is no ``gateway.*``
RPC method that mints, redeems, lists or revokes a peer. **S2's ``harness
gateway introduce`` is the fifth and changes nothing about that**: it is a
COMPOSITION of :func:`mint_peer_code` and
:func:`~agent_runtime.serve_gateway_auth.mint_pairing_code` in one envelope for
a launcher to post as a backend grant — two existing mints, no third ceremony,
no new store, and no method. It inherits this paragraph's residual exactly (a
local agent with a shell can run it) and adds one real narrowing the manual verb
does not have: a code minted with ``for_install_id`` is spendable only by the
install it names (:func:`redeem_peer_code`), so an intercepted introduction buys
an attacker an edge with nobody. A remote
caller therefore cannot reach them through the method lane (nothing to call)
and cannot reach them through the argv lane either, because **the argv lane is
refused outright to every gateway connection** (Stage 1, ``serve.py``'s
``argv_lane_unavailable``) — so "send the CLI verb as argv" is not a door
standing beside the missing method, it is a door that answers one typed error.
That is what closes the REMOTE half, and it closes it structurally.

What it does not close, and what would be dishonest to claim it closes: **a
local agent with shell access on this machine can run these verbs**, exactly as
it can run ``harness gateway pair``, read ``serve_auth_token``, or edit
``peers.json`` with a text editor. Every tool-using agent on an install already
holds the machine owner's authority — that is what ``CALLER_STDIO_OWNER``'s
docstring says and it is true here too. So the accurate statement of what R5
buys is: *no agent on install A can cause install B to trust it, and no remote
caller of any tier can mint a peer anywhere.* An agent that has already taken
over the machine A's operator is sitting at is not a case this ceremony was
ever going to fix, and pretending otherwise would put a false claim in the one
file an auditor would read.

What is stored, and the honest limit of hashing it
--------------------------------------------------

The peer secret is SYMMETRIC and both installs keep only ``sha256(secret)``,
under the key ``secret_verifier``. The limit is exactly ``serve_gateway_auth``'s
and is restated rather than referenced, because a security note one indirection
away is a security note nobody reads: **the verifier is HMAC-key-equivalent.**
Anyone who can read ``peers.json`` can answer a challenge as that peer, exactly
as anyone who can read ``devices.json`` can answer as any device in it.
Digesting buys one real thing and not two — the bytes that travelled through
the pairing channel are not the bytes on either disk, so a store read cannot
recover the ISSUED secret, only the ability to use it. Store-read resistance
needs an asymmetric scheme (the R1 survey's bullet 2) and would change only
:func:`peer_proof` and this file; the wire says "proof" and nothing about how
it was computed.

Say the mechanism plainly too, because it differs from the device lane in a way
a reader would otherwise get wrong: the digest is not merely what is compared,
it is the working KEY at both ends. A phone holds its device token and digests
it per connection; neither install ever holds a peer secret again after the one
frame that carried it, so both sides key the HMAC with the stored verifier
directly. That is what makes the edge symmetric — either install can dial the
other with the row it already has — and it is why :func:`peer_proof` has one
spelling where the device lane needs two.

One thing is genuinely different from the device store and is worth stating.
The device secret is minted BY the install and held by a phone; the peer secret
is minted by A and held by B, and A keeps a digest of it too. So a peer edge
has two verifier copies rather than one, and revoking on one side does not
revoke on the other — :func:`revoke_peer` refuses the peer at THIS install's
door and says so, and the operator at the other install revokes their own row
if they want the edge gone in both directions. A revocation that reached across
the wire would be a peer-tier write into another install's credential store,
which is precisely the authority R5 says an install never has over another.

Why the field is ``secret_verifier`` and not ``verifier``
----------------------------------------------------------

Deliberately a different key from the device row's. The two stores sit in one
directory and hold rows of a similar shape; a row copied from one file to the
other by a script, a merge, or a hand edit must not accidentally be a valid
credential in its new home. Different key name, different id field, different
proof prefix — three independent reasons a device row read as a peer row (or
the reverse) decodes to nothing rather than to something that works.

Root as INPUT, and never raises for a READ
-------------------------------------------

Both rules are ``serve_gateway_auth``'s, for its reasons. Every function takes
``store_root`` and none resolves one: several roots coexist on this machine and
Stage 6's whole subject is two of them at once, so a credential store free to
re-derive its own root could pair a peer against one install and answer for
another. And the read paths (:func:`lookup_peer`, :func:`list_peers`,
:func:`verify_peer_proof`) answer with a typed outcome and never propagate an
``OSError``: they run on the handshake path, where an exception is a peer that
learns nothing and a runtime that logged a traceback.

The package map (program rule 16; layout sheet ``gateway_peers.md`` §1)
------------------------------------------------------------------------

Two stores, one ceremony, one dial. Modules, lowest layer first (no module
imports one above it — W0-G6):

===========  ======  ==========================================================
module       layer   owns
===========  ======  ==========================================================
models       models  the vocabulary, the six frozen rows, the field partition,
                     the two paths, ``clean_endpoints``
cache        stores  ``peers_cache.json``: every cache writer beside
                     ``_touch_cache`` (its one write door); ``usable_peers``
trust_store  stores  ``peers.json``: the HMAC, the reads, ``record_peer`` /
                     ``revoke_peer`` / ``note_peer_seen`` beside ``_write_peers``
                     (its one write door); the revision memo; ``_emit_peer_event``
ceremony     lanes   ``mint_peer_code`` / ``redeem_peer_code`` over ``pairing.json``
dial         lanes   ``dial_peer`` — one outbound handshake
===========  ======  ==========================================================

Entry points and the modules an agent opens to follow each: ``dial_peer`` —
dial, trust_store, cache; ``mint_peer_code`` / ``redeem_peer_code`` — ceremony,
trust_store, cache; ``record_peer`` / ``revoke_peer`` / ``note_peer_seen`` —
trust_store, cache, models; ``verify_peer_proof`` / ``lookup_peer`` /
``list_peers`` — trust_store, models; ``apply_peer_announce`` /
``cache_peer_roster`` / ``usable_peers`` — cache, trust_store, models.

Stores written: ``<store_root>/gateway/peers.json`` (trust_store),
``peers_cache.json`` (cache), ``pairing.json`` (ceremony, through
``serve_gateway_auth``), and the event log (``_emit_peer_event``).

The one cycle (``trust_store`` -> ``cache`` for ``_clear_revoked_you``;
``cache`` -> ``trust_store`` for ``lookup_peer`` / ``_emit_peer_event``) is
broken in ``cache``, which binds its two ``trust_store`` names last; this
``__init__`` therefore imports ``cache`` before ``trust_store``.

Every name an importer or a test takes from ``agent_runtime.gateway_peers`` is
re-exported below, so no importer changes with the package.
"""

from __future__ import annotations

from ..serve_gateway_auth import store_lock  # noqa: F401
from .cache import (  # noqa: F401
    _CACHE_WRITE_LOCK,
    _touch_cache,
    apply_peer_announce,
    cache_peer_hello,
    cache_peer_roster,
    note_dial_result,
    read_peer_cache,
    unusable_reason,
    usable_peers,
)
from .ceremony import (  # noqa: F401
    mint_peer_code,
    redeem_peer_code,
)
from .dial import (  # noqa: F401
    LOCAL_POLICY,
    dial_peer,
)
from .models import (  # noqa: F401
    MAX_ENDPOINTS,
    PEER_AUTH_BAD_PROOF,
    PEER_AUTH_EXPIRED,
    PEER_AUTH_MALFORMED,
    PEER_AUTH_OK,
    PEER_AUTH_REASONS,
    PEER_AUTH_REVOKED,
    PEER_AUTH_UNKNOWN,
    PEER_CACHE_CONTRACT,
    PEER_CACHE_FILENAME,
    PEER_CACHE_ROSTER_CAP,
    PEER_CACHE_ROW_FIELDS,
    PEER_EVENT_REACHABILITY,
    PEER_EVENT_RECORDED,
    PEER_EVENT_REVOKED,
    PEER_EVENT_ROSTER,
    PEER_EVENT_TYPES,
    PEER_EVENT_UPDATED,
    PEER_PROOF_ALGORITHM,
    PEER_PROOF_CONTRACT,
    PEER_ROW_CACHE_FIELDS,
    PEER_ROW_TRUST_FIELDS,
    PEER_SECRET_BYTES,
    PEER_STORE_CONTRACT,
    PEER_STORE_FILENAME,
    REACHABILITY_REACHABLE,
    REACHABILITY_STATES,
    REACHABILITY_UNKNOWN,
    REACHABILITY_UNREACHABLE,
    PeerAuth,
    PeerCacheRow,
    PeerCredential,
    PeerPairingCode,
    PeerRecord,
    UsablePeer,
    _clean_fingerprint,
    clean_endpoints,
    peer_cache_path,
    peer_store_path,
)
from .trust_store import (  # noqa: F401
    _LAST_SEEN_REVISION,
    _decode_peer,
    _emit_peer_event,
    _read_peers,
    _write_peers,
    list_peers,
    lookup_peer,
    note_peer_seen,
    note_peer_store_read,
    peer_proof,
    peer_row,
    peer_secret_verifier,
    peer_store_revision,
    record_peer,
    revoke_peer,
    verify_peer_proof,
)

__layer__ = "lanes"

__all__ = [
    "MAX_ENDPOINTS",
    "PEER_CACHE_CONTRACT",
    "PEER_CACHE_FILENAME",
    "PEER_CACHE_ROW_FIELDS",
    "PEER_EVENT_REACHABILITY",
    "PEER_EVENT_TYPES",
    "PEER_EVENT_RECORDED",
    "PEER_EVENT_REVOKED",
    "PEER_EVENT_ROSTER",
    "PEER_EVENT_UPDATED",
    "REACHABILITY_REACHABLE",
    "REACHABILITY_UNKNOWN",
    "REACHABILITY_STATES",
    "REACHABILITY_UNREACHABLE",
    "PeerCacheRow",
    "UsablePeer",
    "apply_peer_announce",
    "cache_peer_hello",
    "cache_peer_roster",
    "note_dial_result",
    "note_peer_store_read",
    "peer_cache_path",
    "peer_store_revision",
    "read_peer_cache",
    "unusable_reason",
    "usable_peers",
    "PEER_AUTH_BAD_PROOF",
    "PEER_AUTH_EXPIRED",
    "PEER_AUTH_REASONS",
    "PEER_AUTH_MALFORMED",
    "PEER_AUTH_OK",
    "PEER_AUTH_REVOKED",
    "PEER_AUTH_UNKNOWN",
    "PEER_PROOF_ALGORITHM",
    "PEER_PROOF_CONTRACT",
    "PEER_ROW_CACHE_FIELDS",
    "PEER_ROW_TRUST_FIELDS",
    "PEER_SECRET_BYTES",
    "PEER_STORE_CONTRACT",
    "PEER_STORE_FILENAME",
    "PeerAuth",
    "PeerCredential",
    "PeerPairingCode",
    "PeerRecord",
    "LOCAL_POLICY",
    "clean_endpoints",
    "dial_peer",
    "list_peers",
    "lookup_peer",
    "mint_peer_code",
    "note_peer_seen",
    "peer_proof",
    "peer_secret_verifier",
    "peer_store_path",
    "record_peer",
    "redeem_peer_code",
    "revoke_peer",
]
