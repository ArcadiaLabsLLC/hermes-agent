"""``hermes harness serve --ndjson`` — persistent stdio bridge (schema v1).

One warm process replaces the per-call CLI spawns the Launcher Mission
Control bridge pays ~3s import tax on today. Requests dispatch into the
EXISTING harness argparse tree and ``_cmd_*`` handlers, unchanged — argv
arrives verbatim as the bridge already builds it, so intent→argv mapping,
the capability registry, and the per-call CLI fallback stay byte-identical.

Design doc: ``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/harness-serve-design.md``
(settled 2026-07-08). Explicit non-goals: no network listener, not the
mission daemon, no second chat pipeline. "No auth (a local stdio child IS
the security model)" held while the transport was an inherited pipe; the
durable runtime-root service replaces that pipe with one any local process
can reach, so a per-root token is now minted at boot (unwired — see
``agent_runtime/serve_auth.py``) rather than retrofitted after the socket
exists.

Protocol (NDJSON, one frame per line):

- boot:      ``{"event":"ready","pid":…,"schema_version":1,"runtime_root":…}``
             plus the durable-service foundations, all additive:
             ``"build"`` (which commit this runtime is on —
             ``agent_runtime/build_stamp.py``), ``"auth"``
             (``{"token_file":"present"|"minted"|"error:<reason>"}`` — the
             posture, NEVER the token itself), and ``"instance"`` (this
             serve's registry entry under ``<store_root>/serve_instances/``).
             It also carries the two CAPABILITY advertisements — ``"rpc"``
             (``serve_rpc.manifest()``) and ``"ops"``
             (:func:`ops_manifest`) — so a client learns the method set AND the
             op set from the greeting it already reads, instead of probing.
- request:   ``{"id":"req-7","argv":["harness","status","--json"]}``
- reply:     ``{"id":"req-7","event":"line","line":…}`` × N then
             ``{"id":"req-7","event":"exit","code":0}``
             (a status/snapshot poll replayed from the poll response cache
             adds ``"served_from_cache": true, "cache_age_ms": N`` to its exit
             frame — additive; see _PollResponseCache below)
- stderr:    ``{"id":<request id or null>,"event":"stderr","line":…}``
- progress:  ``{"id":"req-7","event":"request_progress","state":"queued"|
             "running","waited_ms":N,"running_ms":N,"pending":M,
             "pool_size":P}`` — UNSOLICITED, on the lane that asked, for a
             request that has produced nothing for
             ``_REQUEST_SILENCE_SECONDS``. A request's first frame is written
             by its HANDLER, so before the fix "queued behind a full pool",
             "slow handler" and "wedged" were one silence; ``state`` separates
             the first from the other two, and it is the field that says
             whether a retry is free. Additive and never emitted on the normal
             path — a client that does not know the event ignores it and
             still reads its ``line``/``exit`` frames unchanged.
- ping:      ``{"op":"ping"}`` → ``{"event":"busy","chat_turns":N,
             "long_runs":N,"pending":M,"subscriptions":S,"work":M-S}``
             (the Launcher supervisor must NEVER recycle serve while
             ``chat_turns`` > 0 — recording safety). ``pending`` is EVERYTHING
             in flight and keeps that meaning; ``subscriptions`` is the
             standing-`harness stream` subset, which an attached launcher holds
             two of forever, and ``work`` is the remainder — the count that
             actually returns to zero on an idle service. The SAME frame is
             pushed unsolicited by the liveness pump, to stdout AND to every
             attached socket/gateway client, but ONLY while ``work`` > 0: a
             `ping` always answers, an idle runtime with subscribers says
             nothing.
- shutdown:  ``{"op":"shutdown"}`` → drain in-flight requests, exit 0
- version:   ``{"op":"version"}`` → ``{"event":"version","build":{…},
             "runtime_root":…,"boot_id":…,"transport":"stdio","auth":{…}}``
             — the SAME stamp the ready frame carried, re-askable at any
             time. A durable service outlives the install it was started
             from; this is how a client proves it is not talking to last
             week's code. Both advertisements (``"rpc"`` and ``"ops"``) are
             restated here, and ``"ops"`` is answered for the transport the
             ask arrived on.
- drain:     ``{"op":"drain"[,"deadline_seconds":30][,"force":true]}`` → stop
             accepting new requests (each is answered
             ``{"id":…,"event":"draining",…}`` and a terminal ``exit`` frame
             with code 75), let in-flight requests finish, then
             ``{"event":"drain_complete","requests_refused":N,
             "requests_completed":M,"drain_ms":X}`` and exit 0. If the
             deadline elapses first: ``{"event":"drain_timeout",…,
             "stuck_request_ids":[…],"held_by_chat_turns":N,
             "held_by_long_runs":N,"terminal":true}``
             and a NONZERO exit — a drain that can hang forever is not a drain.
             Progress is reported as ``{"event":"drain_progress",…}`` while the
             wait runs, so a draining service never looks dead to a watchdog.

             THE DEADLINE IS THE SERVER'S, and so is the kill. Two rules make
             it so, and both exist because `drain` on the socket is reachable
             by any local process holding the root's secret while `shutdown` is
             refused there on purpose:

             * ON THE SOCKET the effective deadline is ``max(client ask,
               server minimum)`` — a socket client could previously ask for
               0.05s, which turned the restart verb into a kill
               (`hard_exit(3)` is `os._exit`) over a live chat turn, straight
               through the never-recycle-during-turns contract this file opens
               with. Over STDIO the ask still stands as given: that asker is
               the parent that spawned this process and owns its stdin, so it
               can end the runtime with a signal regardless, and flooring it
               would change a contract this lane promised to leave untouched;
             * a deadline that expires WHILE A CHAT TURN OR A LONG RUN IS IN
               FLIGHT does not end the process. It emits a non-terminal
               ``{"event":"drain_timeout","terminal":false,
               "held_by_chat_turns":N,"held_by_long_runs":N,…}``, keeps serving,
               and re-arms. Only an expiry with neither in flight is terminal.
               Recording safety outranks restart latency: a killed turn is lost
               work, a late restart is a slow one.

               The long runs are the ``characters turnaround|rows|auto`` verbs
               (``_LONG_RUN_COMMANDS``), and they are here on the same argument
               a chat turn is: a launcher update or a Reap & Restart landing
               mid-generation used to end a ten-to-twenty-minute run without a
               word, and a ``turnaround`` has no partial result to resume from.
               Both counts are reported separately because the WAIT differs —
               a chat turn ends in seconds, a generation may be fifteen minutes
               from done — and ``held_by_chat_turns`` keeps its name and its
               meaning so a reader that only knows that key is never lied to.

             On the SOCKET lane `drain` additionally requires ``"force":true``.
             Same reasoning as the `shutdown` refusal — an attached client
             asking to replace a service other clients are using should have to
             say so explicitly — and one flag is a trivial cost for the
             operator verb (`harness serve connect --drain` sets it). The
             refusal is typed: ``{"event":"error","error":"drain_requires_force"}``.
- cancel:    ``{"op":"cancel","id":"req-7"}`` → a QUEUED request is dropped
             and answers ``{"id":"req-7","event":"exit","code":130,
             "cancelled":true}``; a request already RUNNING (or unknown)
             answers ``{"id":…,"event":"cancel_denied","state":
             "running"|"unknown"}`` — its side effects may still happen, so
             mutation verbs carry their own replay guard (``--issued-at``).
             A RUNNING read-only ``harness stream`` is cooperatively cancelled
             and releases its pool worker; it is the sole running exception.
- errors:    ``{"id":…,"event":"error","error":"invalid_request"|…,"detail":…}``
             A request's argv can end three ways and each has its OWN word
             (RL-24): ``argv_root_unsupported`` (``"root":<word>``) when
             ``argv[0]`` is not ``harness`` — refused before a parser is built;
             ``argv_parse_failed`` when the parser refused it, which is the
             only one a client may replay, because it is the only one that
             proves nothing ran; and ``handler_exit`` (``"code":<int>``) when
             the HANDLER called ``sys.exit`` — its effect already happened. All
             three are followed by the request's ``exit`` frame carrying the
             same code, so a client that knows only the middle word decodes
             them exactly as it does today.
- method:    ``{"jsonrpc":"2.0","id":…,"method":"runtime.office.get"|…,
             "params":{…}}`` → ``{"jsonrpc":"2.0","id":…,"result":{…}}`` or
             ``{"jsonrpc":"2.0","id":…,"error":{"code":…,"message":…,"data":…}}``.

             The method name above is ONE example, deliberately not a list:
             the ``@method`` registry in ``agent_runtime/serve_rpc/registry.py`` is the
             authority for the advertised set (count it there). This block
             used to name ``get`` | ``upsert`` and stayed at two while the
             registry grew — a docstring that copies a register starts lying
             the first time the register moves, and nothing reports it.

             The CALL half (``agent_runtime/serve_rpc/``), mirroring
             ``tui_gateway``'s JSON-RPC 2.0 shape and its error codes rather
             than minting a third convention. It sits BESIDE the argv lane
             above, which is unchanged and remains the fallback: a frame is
             claimed by this lane only when it names ``jsonrpc`` or ``method``,
             neither of which an argv request has ever carried.

             HOW A CLIENT LEARNS THE SURFACE — the ``hello_contract``
             precedent, not a parallel scheme. ``{"contract":N,"methods":[…]}``
             rides the greeting each transport already reads (``ready`` on
             stdio, ``hello_ok`` on the socket) under ``"rpc"``, and is
             restated on the re-askable ``version`` reply because a durable
             service outlives the install it was started from. The manifest is
             a SET plus an integer: the integer moves when an existing
             method's shape changes incompatibly, the set grows when a method
             is added — so methods can be adopted one at a time, exactly as
             ``fold_entities`` does for patch entities. A runtime that
             predates the lane carries no ``rpc`` key, which reads as "argv
             only" rather than as a failure.

Per-request stdout: handlers ``print()`` directly and streaming turns emit
deltas live, so ``sys.stdout``/``sys.stderr`` are swapped once for
contextvar-dispatching proxies; each pool worker binds its request id and a
single write lock keeps frames atomic. Writes from threads a handler spawns
itself carry no request id and are forwarded with ``"id": null``.

The socket lane (slice 3)
-------------------------

``serve_loop`` is now transport-agnostic: ONE dispatcher answers ops arriving
on stdio and on a localhost socket alike. Everything above this line is
unchanged on stdio — every frame, reply, and exit code is byte-identical,
because the socket lane is injected and OFF unless ``_cmd_serve`` turns it on.

- ownership: one serve per root owns the socket, decided by an OS-held
  exclusive lock (``agent_runtime/serve_socket.py``). The loser runs
  stdio-only and says so on ``ready`` under ``"socket"``:
  ``{"outcome":"lock_held_by","pid":…,"owner_started_at":…}``. The winner's
  ``ready`` carries ``{"outcome":"listening","host":"127.0.0.1","port":…}`` —
  plus ``took_over_from`` when it inherited a proven-dead owner's lane (R-L2) —
  and its registry entry records ``transport:"stdio+socket"`` plus the port.
  A serve that loses this race opens no LAN listener either, and since R-L1
  the ``gateway`` block says so in its own words (``socket_unavailable``)
  rather than in the word for "the operator never asked" (``disabled``).
- hello:     CHALLENGE-RESPONSE, and the SERVER speaks first
             (``hello_contract`` 3). On accept the service writes
             ``{"event":"server_hello","nonce":<64 hex>,"boot_id":…,
             "contract":1,"hello_contract":3,"algorithm":"hmac-sha256"}`` and
             the client answers
             ``{"op":"hello","client":…,"client_build":…,"proof":<hex>}`` where
             the proof is ``HMAC-SHA256(key=<per-root token>,
             msg="v3|<the port the client DIALLED>|<nonce>")`` —
             ``serve_socket.hello_proof`` is the authority, and this line said
             ``2`` and ``msg=<nonce>`` until 2026-08-27, which is wrong twice
             over: a client written against it is refused with ``bad_proof``,
             indistinguishable from holding the wrong credential.
             Success → ``{"event":"hello_ok","build":{…},"boot_id":…,
             "contract":1,"hello_contract":3,"build_mismatch":true|false|null}``;
             failure → ONE ``{"event":"hello_rejected","reason":…}`` and the
             connection is closed, with a rate limit against hammering. Before
             that proof is verified a connection can do NOTHING.

             THE TOKEN NEVER TRAVELS. It is the HMAC key, never a field, so it
             appears in no frame, log, error, or registry entry on either side,
             and a captured transcript is unreplayable (fresh nonce per
             connection). The first cut sent the raw token and paired that with
             a discovery fallback that could hand a client a target already
             classified ``stale_dead_pid`` — an impostor on a dead serve's port
             harvested the real token, live-proven. There is deliberately no
             compatibility shim for the old hello: it has no other clients yet,
             and a shim would keep the cleartext lane open forever.

             Rejection reasons are typed and mean different things:
             ``bad_proof`` / ``hello_required`` / ``hello_malformed`` are
             AUTHENTICATION failures and are the only ones that charge the rate
             limiter; ``too_many_connections`` / ``too_many_pending`` /
             ``draining`` / ``hello_timeout`` / ``rate_limited`` /
             ``handshake_throttled`` describe the SERVER's state and never do —
             charging them made a blocked window extend itself forever, so a
             client with the right credential could not recover.
- subscribe: ``{"op":"subscribe","lane":"stream"}`` pushes the SAME hydrate /
             delta / heartbeat frames ``harness stream`` produces, from ONE
             shared producer fanned out to every subscriber (a per-batch
             snapshot rebuild is why it is not one generator per client). A
             subscriber that outruns its bounded buffer gets
             ``{"event":"subscription_dropped","reason":"backpressure",…}`` and
             is unsubscribed — never silently stalled, and never able to wedge
             the producer or another subscriber. ``{"op":"unsubscribe"}`` ends
             it cleanly, and so does a disconnect.
             An optional ``"fold_entities":["persona_instance",…]`` declares
             which entity classes THIS client can fold in place; the producer
             promotes a coalesced batch to a small ``patch`` frame only for
             declared entities and demotes anything else to the full core it
             would have sent anyway. Omitting it means the historical
             ``{persona_instance, incident}`` — exactly today's wire, so an
             un-updated client is unaffected. The producer is SHARED, so the
             ACCEPTED set is the intersection over every attached subscriber and
             is echoed on the ``subscribed`` ack (and on the hydrate) rather than
             left for the client to assume. A malformed declaration is refused
             with ``{"event":"subscribe_denied","reason":"invalid_fold_entities"}``
             instead of being silently read as absent.
             The frames a subscriber receives are the argv stream's frames,
             not a second contract: byte parity against
             ``harness stream --fold-entities …`` over one seeded root and one
             scripted event sequence is a contract test
             (``tests/agent_runtime/test_serve_stream_lane_parity.py``).
             Whether THIS runtime carries the lane is answerable before
             subscribing — see ``"ops"`` / :func:`ops_manifest`.
- connections: ``{"op":"connections"}`` → ``{"event":"socket_connections",…}``
             (count, and per client: name, build, subscribed, connected_at,
             frames and bytes pushed). The same block rides the ``version``
             reply, so "who is attached to this runtime" is answerable from the
             handshake a client already performs.

Client disconnect unsubscribes and does NOTHING else: the backend state a
client was watching is the runtime's, not the client's, and surviving a client
is the entire point of the durable service.

Service mode (``--service``, L-h)
---------------------------------

Everything above survived a socket CLIENT leaving. Until this flag existed
nothing survived the STDIO OWNER leaving: the reader loop is the main loop, so
stdin EOF ended the process — pool joined, socket lanes closed, registry entry
removed — and "the runtime" was in practice a child of whichever launcher had
started it.

``harness serve --ndjson --service`` separates the two facts EOF used to
conflate:

- **stdin EOF = the starter detached.** The loop logs
  ``{"event":"stdio_owner_detached","boot_id":…,"starter_pid":…}``, broadcasts
  it to attached socket clients, swaps the stdio frame sink for a null sink
  (nothing is reading that pipe, and a late write must not raise), keeps BOTH
  socket lanes serving, and parks the main thread.
- **a stdio ``{"op":"shutdown"}`` received BEFORE EOF is still an order** and
  ends the runtime exactly as it always has. This is what keeps the flag safe
  for a caller that does own the pipe.
- the park ends on ``{"op":"drain","force":true}`` over the socket (the
  operator's stop/restart verb, from outside), on ``SIGTERM`` where the platform
  delivers one, or on that stdio ``shutdown``. Then the SAME finalization runs:
  pool shutdown, terminal frame, lane close, unregister, unchanged exit codes.
- a ``--service`` starter that LOSES the per-root ownership lock exits 0 with
  ``{"event":"serve_owner_exists","pid":<winner>,"port":<winner's>}`` and serves
  nothing — no pool, no registry row, no ready frame. A stdio serve that loses
  the lock still runs stdio (unchanged); a service that lost it would be a
  second, undiscoverable executor against one store, which is the thing F1
  named.
- ``service`` (bool) and ``starter_pid`` ride the registry row and all three
  greeting frames (``ready``/``hello_ok``/``version``), and ``"service"`` is
  additionally a key on the ``ops`` manifest whose PRESENCE tells a client that
  this runtime understands the flag at all. The ops contract integer is
  unchanged: these are added keys, not a new shape.

Without ``--service`` none of the above is reachable and every frame, code and
teardown order is byte-identical to what it was.
"""

from __future__ import annotations

from typing import Final

__layer__ = "models"

__all__ = [
    "HELLO_OP",
    "OPS",
    "READER_STOP",
    "DEFAULT_DRAIN_DEADLINE_SECONDS",
    "DEFAULT_POOL_SIZE",
    "DRAINING_EXIT_CODE",
    "DRAIN_TIMEOUT_EXIT_CODE",
    "FINGERPRINT_HOME_BOOT_SITE",
    "GATEWAY_TRANSPORT",
    "OPS_CONTRACT_VERSION",
    "OPS_EVERY_TRANSPORT",
    "OPS_GATEWAY_DENIED",
    "OPS_STDIO_ONLY",
    "SERVE_SCHEMA_VERSION",
    "SUBSCRIBE_LANES",
    "_CACHEABLE_ARGV",
    "_CHAT_TURN_COMMANDS",
    "_DRAIN_ABANDON_GRACE_SECONDS",
    "_DRAIN_DEADLINE_FLOOR_SECONDS",
    "_DRAIN_DEADLINE_MAX_SECONDS",
    "_DRAIN_EXIT_DEADLINE_SECONDS",
    "_DRAIN_POLL_INTERVAL_SECONDS",
    "_DRAIN_PROGRESS_INTERVAL_SECONDS",
    "_DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS",
    "_FINGERPRINT_BOARD_CARD_CAP",
    "_FINGERPRINT_ROOT_FILES",
    "_FINGERPRINT_STORE_DIRS",
    "_LONG_RUN_COMMANDS",
    "_READ_CACHE_MAX_AGE_SECONDS",
    "_REQUEST_SILENCE_SECONDS",
    "_SERVICE_PARK_POLL_SECONDS",
]

SERVE_SCHEMA_VERSION = 1
DEFAULT_POOL_SIZE = 4

#: The NAMED boot instant at which this serve captures the core cache's
#: fingerprint home (HC-1). A constant rather than a literal at the call site
#: because it is a two-ended contract: it is what
#: ``core_cache.RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE`` prints as ``site=`` when
#: the capture did NOT happen here, and it is what the regression pin asserts the
#: capture instant to be. The spelling names the frame it follows, so a boot log
#: and the receipt can be read against each other without consulting this file.
FINGERPRINT_HOME_BOOT_SITE = "serve_loop:booting_frame_emitted"

# ── The OP lane's advertisement (TC-1/C-1) ───────────────────────────────────
#
# The METHOD lane has been discoverable since ``serve_rpc.manifest()`` started
# riding ``ready``/``hello_ok``/``version`` under ``"rpc"``: a client reads the
# greeting it already reads and learns which methods exist. The OP lane — the
# ``{"op":…}`` verbs this file dispatches, ``subscribe`` among them — was NOT
# discoverable at all, so a client could only learn whether this runtime carries
# the push lane by sending a subscribe and interpreting whatever came back. That
# is a probe, and a probe cannot distinguish "this runtime is too old" from "this
# runtime refused THIS subscribe" (`unsupported_lane`, `draining`,
# `already_subscribed` are all real answers a live lane gives).
#
# So the ops advertise themselves, under ``"ops"``, beside ``"rpc"``, following
# the method lane's discipline verbatim rather than minting a second scheme:
#
#   * a SET plus an integer. The set grows when an op is added — a client only
#     ever sends an op it FOUND — and the integer moves only when an existing
#     op's shape changes incompatibly. Adding ``subscribe`` to the advertisement
#     does not move ``SERVE_SCHEMA_VERSION``, ``RPC_CONTRACT_VERSION``, or this
#     module's own integer, exactly as the eighth RPC method did not move the
#     method lane's;
#   * a runtime that predates the advertisement carries no ``"ops"`` key, which
#     reads as "ops undiscoverable, probe if you must" rather than as a failure;
#   * PER TRANSPORT, because the answer genuinely differs. ``shutdown`` is the
#     stdio owner's verb and is refused on the socket
#     (``op_not_available_on_socket``), so advertising it to a socket client
#     would be a false all-clear of the exact kind the build stamp beside it
#     exists to retire. The block names the transport it describes so a client
#     that cached it cannot mis-apply it to the other lane.
#
# A THIRD block rides the same three frames, and it is not a manifest: ``install``
# (``{install_id, display_name, state}``, from
# ``agent_runtime.gateway_identity``) names WHICH runtime a client reached, where
# ``rpc``/``ops`` say what it can do. It is on the greeting for the same reason
# they are — a remote client (gateway plan Stage 2+) has no ``runtime_root`` path
# it can interpret and no second question it can afford to ask — but it is a pair
# of strings rather than a set plus an integer, so nothing negotiates on it and
# no contract integer moves when it appears. Absent from a runtime that predates
# it; ``state`` says ``error:<reason>`` rather than vanishing when this one could
# not mint. It NAMES; it never authorises (see the module's own docstring).
#
# ``hello`` is deliberately absent from both sets. It is the socket's FIRST line
# and is consumed by ``serve_socket`` before this dispatcher ever sees a frame;
# reaching the dispatcher means it is a SECOND hello, which is answered
# ``unexpected_hello``. Its contract is already advertised — ``hello_contract``
# on ``server_hello`` and restated on ``hello_ok``.
OPS_CONTRACT_VERSION = 1

#: Ops this dispatcher answers on EVERY transport.
OPS_EVERY_TRANSPORT: Final[tuple[str, ...]] = (
    "cancel",
    "connections",
    "drain",
    "ping",
    "stacks",
    "subscribe",
    "unsubscribe",
    "version",
)

#: Ops only the process that owns this runtime's stdin may use. See the
#: ``shutdown`` refusal in ``_handle_message``.
OPS_STDIO_ONLY: Final[tuple[str, ...]] = ("shutdown",)

#: THE op vocabulary: every op the dispatcher answers and ``ops_manifest``
#: advertises, before the per-transport denials below. One vocabulary, two
#: readers that cannot disagree — the manifest subtracts from it, and the
#: dispatcher's op table (``handle_message.OP_HANDLERS``) is checked against it
#: at import.
OPS: Final[tuple[str, ...]] = (*OPS_EVERY_TRANSPORT, *OPS_STDIO_ONLY)

#: The socket handshake's first line. Consumed by ``serve_socket`` before the
#: dispatcher exists, so a ``hello`` that REACHES the dispatcher is a second one:
#: answered (``unexpected_hello``), never advertised — which is why it is not
#: in :data:`OPS`.
HELLO_OP = "hello"

#: What an op returns to stop the stdio reader (the stdio ``shutdown`` op).
#: A named signal rather than a string compared at the reader.
READER_STOP = "shutdown"

#: The transport name the gateway listener tags its connections and frames with.
#: The same string ``call_authorization.TRANSPORT_GATEWAY`` keys its structural
#: guard on; spelled in both places rather than imported across the boundary,
#: for the reason that module gives (it must not import a transport to answer a
#: question about an object it was handed) and pinned equal by a test.
GATEWAY_TRANSPORT = "gateway"

#: Ops a paired DEVICE is refused, on top of the stdio-only set. One entry, and
#: it is the one that ends the process.
#:
#: ``drain`` is not a read and it is not a level mutation — it is the multi-client
#: lifecycle verb, and its whole effect is that this runtime stops and every
#: OTHER attached client is disconnected. A phone deciding that for the desktop
#: it is a guest on is the wrong default even at ``console`` tier, and "the
#: operator wanted to restart the runtime from their phone" is a verb somebody
#: can add deliberately later. The refusal mirrors ``shutdown``'s
#: (``op_not_available_on_socket``) rather than inventing a shape.
OPS_GATEWAY_DENIED: tuple[str, ...] = ("drain",)

#: The push lanes ``{"op":"subscribe","lane":…}`` accepts. ONE today, and the
#: value EG-4.2's launcher gate reads: the argv stream stays the backstop until
#: a runtime says this word, because the launcher must never unilaterally switch
#: onto a lane the runtime it is attached to does not carry.
SUBSCRIBE_LANES: tuple[str, ...] = ("stream",)


# ── Drain ────────────────────────────────────────────────────────────────────
#
# A durable service must be replaceable WITHOUT killing work: `drain` refuses
# new requests, lets the in-flight ones land, and exits. Every path emits its
# typed terminal frame BEFORE exiting — the frame is the observability, and a
# drain that exited without one would be indistinguishable from the crash it
# exists to avoid.
DEFAULT_DRAIN_DEADLINE_SECONDS = 30.0
#: The absolute sanity floor, both transports: a deadline of zero is not a
#: deadline. This is the long-standing stdio contract and is unchanged.
_DRAIN_DEADLINE_FLOOR_SECONDS = 0.05
#: The SOCKET lane's floor under a client-supplied deadline, and the
#: correction for a real defect: with only the sanity floor above, any local
#: process holding the root's secret could ask for a deadline that expires
#: instantly, and `drain` became `kill` — the timeout path calls `hard_exit`,
#: which is `os._exit`, over whatever was running.
#:
#: Why the SOCKET lane only. A deadline is a promise about how long in-flight
#: work is allowed to finish, and the question is who is entitled to shorten
#: it. Over stdio the asker is the PARENT that spawned this process and owns
#: its stdin; it can end this runtime with a signal whether or not the drain
#: cooperates, so a floor there buys no safety and would silently rewrite a
#: contract the socket slice promised to leave byte-identical. Over the socket
#: the asker is any local process that could read the token file, refereeing
#: work it cannot see. `max(ask, this)` on that lane, always.
_DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS = 30.0
#: An unbounded value would restore "can hang forever" through the front door.
_DRAIN_DEADLINE_MAX_SECONDS = 3600.0
_DRAIN_POLL_INTERVAL_SECONDS = 0.05
#: While draining, this replaces the `busy` liveness pump (which stops with the
#: delivery drain the moment draining starts). A watchdog keyed on "no frames
#: for N seconds" must not declare a healthily-draining runtime dead.
_DRAIN_PROGRESS_INTERVAL_SECONDS = 5.0
#: Refused-because-draining. 75 is EX_TEMPFAIL: "try again", which is exactly
#: what a client should do — against the replacement runtime. The refusal also
#: carries this terminal `exit` frame so a client that predates the typed
#: `draining` event still terminates its request instead of waiting forever.
DRAINING_EXIT_CODE = 75
#: In-flight work outlived the deadline. Nonzero on purpose: a supervisor must
#: be able to tell "drained" from "gave up with work still running".
DRAIN_TIMEOUT_EXIT_CODE = 3
#: ONE deadline for everything between "the drain has decided how it ended"
#: and "this process is gone": publishing the terminal frame, broadcasting it
#: to attached clients, tearing the socket lane down, unregistering, and the
#: reader unwinding. It is armed as the FIRST act of ``_finish_drain`` rather
#: than after the teardown, because the teardown is exactly what can hang —
#: hub joins were 2.0s EACH and a wedged reader can park a broadcast write for
#: IO_TIMEOUT, so with 32 subscribers the old arrangement could sum past a
#: minute with the watchdog not yet armed. Summed per-step budgets are not a
#: bound; this is.
_DRAIN_EXIT_DEADLINE_SECONDS = 15.0
#: The mirror image: how long the READER waits for the drain monitor to publish
#: its terminal frame when the transport closed first (a `shutdown` op or EOF
#: arriving mid-drain). The pool has already been joined by then, so the monitor
#: is normally one poll interval away; past this bound the drain is declared
#: abandoned IN A FRAME rather than exiting silently.
_DRAIN_ABANDON_GRACE_SECONDS = 5.0
#: How often the ``--service`` park re-checks the drain latch while waiting on
#: its stop event. The event itself is what normally wakes it — this is a cheap
#: safety net, not the mechanism: a missed wakeup would otherwise be a service
#: that drained, published its terminal frame, and then sat there forever. Half
#: a second of a sleeping thread costs nothing and bounds that class of bug.
_SERVICE_PARK_POLL_SECONDS = 0.5


#: How long ONE request may produce nothing before the loop describes it, on
#: the lane that asked, as ``{"id":…,"event":"request_progress","state":…}``.
#:
#: An argv request's first frame is written by its HANDLER, so until then a
#: request queued behind a full pool, one whose handler is merely slow, and one
#: whose handler has wedged are the same silence on the wire. Measured
#: 2026-08-27: a ``characters list --json`` on an authenticated socket read ZERO
#: frames for >120s while the same serve answered a later connection's identical
#: argv in ~6s — and the client could not tell which of the three it had.
#:
#: The budget is deliberately longer than any healthy read (``status`` and
#: ``snapshot`` are the launcher's cadence polls and a warm ``snapshot`` is
#: ~7s), so the normal path pays no extra frames at all and only a request that
#: has genuinely gone quiet is described.
#:
#: Read from the module at call time on purpose — a test lowers it, the same
#: seam ``_DRAIN_EXIT_DEADLINE_SECONDS`` uses.
_REQUEST_SILENCE_SECONDS = 15.0

# Chat turns must survive supervisor recycles (recording safety): these argv
# shapes mark a request as an in-flight chat turn for the busy/ping frame.
_CHAT_TURN_COMMANDS = (("mission-chat", "message"), ("mission-chat", "steer"))

# The verbs that legitimately run for MINUTES, and hold the drain deadline the
# way a chat turn does. Same reason, different work: a character generation is
# one provider call per direction or per row, hermes's own rate estimate is
# 1-2 min per generation (`harness.py::_characters_auto_write`), and a
# `turnaround` produces NOTHING until the whole strip lands — so a launcher
# update or a Reap & Restart landing mid-generation used to end the run with no
# word to anybody, and `turnaround` had no partial result to resume from.
#
# `rows` and `auto` do land per row, so what a kill costs them is the row in
# flight; `turnaround` loses everything. That is the asymmetry, and it does not
# change the answer: all three hold, because the frame the supervisor reads has
# to say a long run is in flight before the supervisor can be expected to wait.
#
# NOT a licence to hang. The hold is only bounded because the generation itself
# now is: `agent/charsheet/pipeline.py::PROVIDER_TIMEOUT_SECONDS` puts a
# deadline on every provider call, which is what stops one wedged backend from
# holding a drain open forever. The two changes are one change.
_LONG_RUN_COMMANDS = (
    ("characters", "turnaround"),
    ("characters", "rows"),
    ("characters", "auto"),
)

# ── Poll response cache (follow-up slice 1 of the serve design doc) ──────────
#
# NOT the serve core cache (``<store_root>/serve_read_model/``). This is a
# per-serve-loop replay cache for the stdout payload of the two read-only poll
# commands.
#
# The disambiguation used to name a THIRD thing, ``agent_runtime/read_model.py``,
# because "read model" meant three unrelated things in this repo. Stage 6
# (2026-08-22) deleted that module, so two remain — and the one that still
# collides is the DIRECTORY NAME below, which is the core cache's on-disk home
# and has nothing to do with either cache's contents. That naming trap is the
# reason this comment survives the module it used to warn about.
#
# The Launcher polls `harness status --json` / `harness snapshot --json` on a
# fixed cadence; each build recomputes the full projection (~1.7s status /
# ~7s snapshot warm) even when NOTHING changed. Serve is a warm process, so it
# caches the exact stdout payload of these read-only requests keyed by a
# runtime-state fingerprint (the sequence check) and replays it while the
# fingerprint holds.
#
# The fingerprint stats the cheap change signals: events.jsonl (every store
# mutation appends an event — the architecture's change feed), the turn store,
# scope pointers, the live store directories (record add/rename
# flips a directory's mtime), and the SessionDB files (chat writes; -wal /
# -journal included because a SQLite WAL commit does not touch the main db's
# mtime). Signals that live OUTSIDE the runtime root (git working trees for
# dirty state, provider health) cannot flip the fingerprint, so a TTL bounds
# their staleness: a cached payload older than _READ_CACHE_MAX_AGE_SECONDS is
# rebuilt even on a fingerprint match.
#
# Visibility: a replayed response stamps `served_from_cache` + `cache_age_ms`
# on its exit frame (additive), and the payload's own parity envelope keeps
# the honest original `generated_at`.

_CACHEABLE_ARGV: dict[tuple[str, ...], str] = {
    ("harness", "status", "--json"): "status",
    ("harness", "snapshot", "--json"): "snapshot",
}
_READ_CACHE_MAX_AGE_SECONDS = 20.0

_FINGERPRINT_ROOT_FILES = (
    "events.jsonl",
    "mission_chat_turns.json",
    "active_realm.json",
    "active_workspace.json",
)
_FINGERPRINT_STORE_DIRS = (
    "runs",
    "incidents",
    "agents",
    # S57 dropped "repo_bundles" here with the store: this list exists to
    # invalidate the poll response cache when a store directory changes, and no
    # code path can write that tree any more (S52 took the last writer, S57 the
    # module).
    # Stat'ing it every poll was cost against a directory that cannot move. Same
    # rule S56 applied to "worker_sessions".
    "runtime_instances",
    "persona_instances",
    "persona_assignments",
    "workspaces",
    "realms",
    # DELIBERATELY ABSENT: "serve_instances". Its entries appear and vanish at
    # every serve boot/exit, and the ``serve_auth_token`` file appears at first
    # boot — inside a fingerprint either one would cold the poll response cache
    # exactly when a fresh runtime is warming up, and make the stream emit
    # ``state.reconciled`` on every restart. Same standing precedent as
    # ``dispatch_delivery.DRAIN_STATE_FILENAME``; the rule is restated at both
    # ``agent_runtime/serve_registry.py`` and ``agent_runtime/serve_auth.py``.
)

# The ``running_work`` durable stores (``processes.json``, ``state.db``) are
# fingerprinted too, but they live under the HERMES **home** rather than the
# agent-runtime store root — on a profiled install those are genuinely
# different directories — so they cannot ride the two tuples above. Their one
# path authority is ``agent_runtime.running_work.running_work_store_paths``,
# called from ``_runtime_state_fingerprint`` below; duplicating the names here
# would stand up a second list free to drift from the projection's.


_FINGERPRINT_BOARD_CARD_CAP = 600  # bounded per-board card stat; remainder is rare + also evented
