# History — `agent_runtime/serve_rpc/` (the METHOD lane's handler rationale)

Rule 7 of the god-file program (`docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` §1)
and ruling Q3 (`docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md` §9): prose that narrates
WHY a handler is shaped the way it is, and what it used to be, lives here once the handler's code is
rewritten. Each section below is the handler's former docstring subsections, verbatim; the docstring
keeps its contract summary (params, result) and a pointer back here. Lane R3's CHANGE commit moved
them when the office verbs became phases and translation tables.

## `runtime.office.subscribe`

From the docstring of `agent_runtime/serve_rpc/office_read.py::_runtime_office_subscribe`.

Why one call and not two
------------------------
A ``get`` followed by a separate join is two reads of one truth with a
window between them, and nothing tells the client whether anything moved
inside that window. Taking the projection and the offset together — and
registering with the same value — is what makes "I have the office as of N,
push me everything after N" a statement the runtime can honour rather than
a hope. The office lock is held across the pair so a write cannot land
between them.

The ordering seam, stated rather than papered over
--------------------------------------------------
The dispatcher emits this reply AFTER the handler returns, so a patch
published in between reaches the client BEFORE the baseline it rebases on.
That is not fixed by a server-side buffer; it is fixed by the sink dropping
any frame at or below ``event_offset``, which is the same rule that absorbs
the hub's mandatory re-hydrate. See ``serve_office_subscriptions``.

A second subscribe RE-BASELINES, and says so
--------------------------------------------
Registering and answering together has a consequence the first cut did not
follow through on: the subscription exists before the client has finished
reading the reply. A client that finds the baseline unusable is right to
refuse it — folding a knowingly-partial office would render it as
authoritative — but the old ``already_subscribed`` refusal then left a live
subscription the client would never fold against, reclaimable only by
dropping the connection. There is no method that could have released it.

So a repeat subscribe for this ``(connection, workspace)`` replaces the
registration with a fresh baseline and watermark, and the stuck state stops
existing by construction. The refusal it retires was only ever there to stop
a subscriber leaking per retry; one key still means one subscription, so
nothing leaks either way, and replacement is the answer that gets a confused
client out of the hole rather than deeper into it.

``replaced`` on the result is the bill. ``StreamHub.subscribe`` restarts the
producer, so a re-baseline costs every OTHER subscriber on that hub a fresh
full core — a cost the old refusal did not incur, because a duplicate key
was declined before a generation was ever bumped. A client that sees
``replaced: true`` on a call it thought was its first has learned something
true about its own state, and the same event is written to the service log
for the operator (``serve_office_subscription_rebaselined``). Silent
re-baselining would let a retry loop tax the whole room invisibly.

Refusals are typed because their cures differ:

``push_channel_unavailable``
    This caller has no push channel — a stdio probe, a test double. The
    method refuses rather than registering into a void, which is the whole
    reason ``RpcContext.emit`` is allowed to be ``None``.
``push_lane_unavailable``
    The runtime has no stream hub bound — no socket lane, or a serve loop
    that has not reached its bind yet. Nothing the client can do about the
    first; the second is a startup window ``serve.py`` announces ``ready``
    several hundred lines before closing, and it is a separate bug.
``push_lane_draining``
    A hub IS bound and it refused: it is stopping, so this call raced
    ``_close_socket_lane``. Transient, and the cure is to reconnect — which
    is precisely why it must not share a name with the case above. When the
    caller held a subscription, ``data.prior_subscription_released`` says
    so: the re-baseline's teardown already ran, so the old lane is gone too.
``baseline_unavailable``
    The event log's tail could not be read, so there is no offset to
    baseline at. Transient like the case above, and the reason this method
    no longer answers an unreadable log with ``0`` — see the refusal at the
    watermark read for what a fabricated baseline costs the whole room.

``already_subscribed`` is GONE. It was the only ``ERR_CONFLICT`` this method
raised, and its disappearance also retires a mislabel that shipped with it:
the old branch chose its reason by asking ``bound()``, which answers True
for a bound-but-draining hub as readily as for a live one. A client racing
the drain was therefore told "already subscribed to this workspace" while
holding no subscription at all — sent to the one cure (stop retrying) that
could not work. Splitting the two reasons is what keeps replacement from
quietly inheriting that lie under a new name.

``fold_entities``: what THIS client can fold, not what an office subscriber
can fold in general
---------------------------------------------------------------------------
The declaration used to be a SERVER-side constant
(``OFFICE_FOLD_ENTITIES``), which is a shape that can only ever report a
fact about the runtime — and that is the hole the 2026-08-16 capability
token exposed (plan §V4). Promotion is negotiated over the room, so a
launcher whose fold had been widened could never have its widened rows
promoted on this lane: the intersection cannot contain a token nobody told
the server about.

So the param is optional and FAIL-OPEN. Absent → the legacy constant, i.e.
today's wire for every client in the field, byte-identical. Present → this
subscription declares exactly what it says, unknown members included (the
channel has never interpreted its strings, and a server that filtered to a
known vocabulary would drop the NEXT token the same way). An explicitly
EMPTY list is honoured as empty — "I fold nothing, send me full cores" is a
thing a client is allowed to say and must stay distinguishable from silence.
A non-list is refused rather than guessed: a client sending the wrong shape
should learn it, not be quietly filed as legacy.

The accepted set is ECHOED on the reply, under the same always-present rule
the other keys follow. Without it a client cannot tell a declaration that
was honoured from one the runtime is too old to have read — and this whole
method exists because a push that arrives and is silently dropped is the
failure this lane keeps paying for.

``reason``: the client's own resubscribe cause, so the server log can join
the ladder
---------------------------------------------------------------------------
Every re-subscribe in the launcher flows through ONE door and already
carries an exact cause string (``start``, ``fold:fenced``,
``push:full_core``, ``reconnect``, ``deferred:*``, ``fold_threw``) — and
that string used to die in the launcher's log. The server saw a re-baseline
with no way to tell a fold-fence storm from a demote storm, so separating
the two classes meant joining two logs on timestamps: inference, on the same
shape that has already misattributed this lane once.

So the param is optional, additive and INERT. It decides nothing: it is
stamped verbatim on the ``serve_office_subscription_rebaselined`` receipt
and read nowhere else. A cause the client chose is evidence, never
authority — a server that branched on it would be taking dispatch orders
from an untrusted string.

Boundary-validated rather than echoed raw, because it is written to an
operator's log: ≤64 chars over ``[a-z0-9_:.-]``, refused ``-32602`` with
``{"reason": "reason_invalid"}`` otherwise, and refused BEFORE any store or
hub call so a bad param cannot cost a projection, a lock, or a producer
restart. See ``normalize_office_subscribe_reason`` for why a blank is a
refusal rather than an absence.

Absent — every client in the field today — prints
``SUBSCRIBE_REASON_ABSENT`` (``-``) on the receipt, so silence is visible as
a value rather than as a missing key.

## `runtime.office.upsert`

From the docstring of `agent_runtime/serve_rpc/office_actor_writes.py::_runtime_office_upsert`.

Why this method REFUSES an unknown workspace instead of authoring one
---------------------------------------------------------------------
``OfficeStore.upsert_actor`` calls ``ensure_surface``, which used to lazily
create the office for ANY id. This lane's caller is the same program that
just called ``runtime.office.get``, which REFUSES an unknown workspace so a
typo cannot render as a blank canvas. A pair where the read refuses a typo
and the write silently authors a whole new office for it is incoherent, and
the write side is the worse half — a mis-rendered canvas is repainted on the
next poll, a mis-authored one is on disk forever. So the existence check
happens HERE, before the store's own create.

**Amended MC-8 / P10.** This paragraph used to continue "…which is right for
the CLI: a human typed ``--workspace`` and can see what they made", leaving
the surface-authoring path on the argv lane. That reasoning is retired: the
lazy create is how a leaked test context minted a LIVE office for a workspace
that never existed, so ``ensure_surface`` now refuses typed
(``WorkspaceUnresolved``) on every lane when no workspace RECORD resolves the
id. The two guards ask different questions and both still earn their place —
this one asks whether a SURFACE exists, so an unknown workspace reads as
``workspace_not_found`` rather than as an empty office; the store's asks
whether a workspace RECORD does. Because this check runs first and refuses
whenever the surface is absent, ``WorkspaceUnresolved`` is NOT REACHABLE
through this arm. A handler for it here would be a catch that can never fire,
so there deliberately is none.

The desk fence is GONE (2026-09-18, owner ruling)
-------------------------------------------------
This handler used to carry a third translation arm: ``DuplicateDeskRefused``
into a 4090 with ``data.reason = "duplicate_desk"``. The store fence behind
it (D6, one live desk per persona per level) was deleted with the invariant
it enforced — a desk is furniture addressed by its own synthetic id, so a
second desk in a workspace is the normal shape rather than the refused one.
Nothing replaced the arm: a desk write now succeeds, and this lane is one
reason string shorter. ``RPC_CONTRACT_VERSION`` did not move — a reason a
server can no longer emit is not a contract a client has to be told about,
and every other reason on this method is unchanged.

Concurrency is the store's, not a second scheme
-----------------------------------------------
``expect_revision`` and the realm-sync conflict guard are passed straight
through to ``upsert_actor``; both refusals arrive as typed exceptions and
are translated, never re-implemented. Note what ``expect_revision`` can and
cannot express: ``_check_revision`` compares against ``None`` for an actor
that does not exist yet, so EVERY value — including ``0`` — refuses a
create. A create is therefore necessarily unguarded, and a client must send
``expect_revision`` only for a placement it has already seen.

The class-key fence, and why it has NO override here
----------------------------------------------------
The fence is the STORE's (``OfficeStore._guard_class_keyed_write``, hoisted
there by EG-6.6) for the reason ``office_class_key_guard`` gives:
``upsert_actor`` reads an explicit upsert of an ARCHIVED key as operator
intent to re-add and clears the resurrection ledger, so one surviving
class-keyed write undoes the class→instance re-key and places the same agent
twice. What this handler keeps is the TRANSLATION — a 4090 whose
``data.reason`` is ``class_key_collision`` and whose message names the exit
this lane actually has. It holds no copy of the predicate; deleting the
store's fence does not leave this lane guarded.

The CLI verb beside it passes ``allow_class_key=True`` to the store on
``--allow-class-key``. This one never passes it, and that asymmetry is the
point rather than an omission. The
flag is consent: an operator read the refusal, typed the override, and owns
the double placement. A wire PARAMETER is not consent — it is a constant in
a client build, set once by whoever was debugging the day drags started
failing, and thereafter sent by every install on every write with no human
in any loop. And the wire client needs it least: the read projection hands
it ``persona_instance_id`` on every item, so its remedy is to send back the
binding it was already given. The genuine operator-intent paths are
untouched — ``harness office actor-restore``, and the CLI's own override.

## `runtime.office.remove`

From the docstring of `agent_runtime/serve_rpc/office_actor_writes.py::_runtime_office_remove`.

Why this REFUSES an unknown workspace before the store
------------------------------------------------------
Same ruling as ``runtime.office.upsert``'s, reached from the other side.
``remove_actor`` on an unauthored workspace raises ``NotFound`` about the
ACTOR — which is true but useless, because it names the wrong thing: the
client's cure for "this workspace has no office" is not "resend a different
key". Checking ``surface_exists`` first means the read leg and both write
legs spend one reason string on one condition, and a typo answers the same
way whichever verb hit it.

Why an already-archived key is an OK and not a 4001
---------------------------------------------------
``OfficeStore.remove_actor`` is idempotent on purpose: an already-archived
key returns the archived copy and writes nothing. That is the honest answer
for this lane too. The launcher's flush re-names a key it has already
deleted whenever a later save recomputes the same vacated set, and turning
the second attempt into an error would make an operator's single deletion
report a failure it did not have — with a rollback behind it that puts the
actor back on the canvas. Nothing was written either way; the state the
caller asked for is the state the store is in.

NO class-key fence, and that is not an omission
-----------------------------------------------
``office_class_key_guard`` exists because an upsert of an archived key is
read as intent to RE-ADD and clears the resurrection ledger. An archive
moves in the other direction — it cannot resurrect anything, and a
class-keyed archive is the class→instance migration's own mechanism rather
than a write that undoes it.

## `runtime.office.surface.update`

From the docstring of `agent_runtime/serve_rpc/office_surface_writes.py::_runtime_office_surface_update`.

``folders`` is a LIST on this lane, deliberately
-----------------------------------------------
The capability lane joins the folders with commas onto one argv string
because argv has no other shape. That encoding is an ARGV ARTIFACT and it is
lossy in a way nobody has tripped over yet only because folder names happen
not to contain commas — ``_safe_folder`` collapses whitespace and truncates
at 80 chars but keeps every comma it is given, so ``"Design, Ops"`` splits
into two folders on the way through. A typed lane must not copy an
encoding's accidents, so the list stays a list and
``OfficeStore.update_surface`` receives exactly what the operator arranged.

Why the ECHO is the load-bearing half of the reply
--------------------------------------------------
``_normalize_folders`` is not identity: it always prepends
``DEFAULT_FOLDERS``, drops duplicates and blanks, and stops at
``MAX_FOLDERS``. The launcher's flush has, until this method existed, copied
its OWN desired list into ``serverFolders`` on accept — so any normalization
difference left the two permanently disagreeing and the folder branch
re-firing on every subsequent flush, one write per flush forever. Echoing
the store's canonical list is what closes that loop, which is why the reply
carries the whole list rather than the light ``{revision}`` ack the actor
verbs answer with. It is small by construction (≤64 names ≤80 chars).

Why this REFUSES an unknown workspace instead of authoring one
--------------------------------------------------------------
Same ruling as ``runtime.office.upsert``'s, and it bites harder here.
``update_surface`` calls ``ensure_surface`` unconditionally on its non-dry
path, so on this lane a typo'd ``workspace_id`` would not merely write to
the wrong place — it would AUTHOR a whole office, emit
``office.surface.created``, and leave it on disk forever, while the read leg
(``runtime.office.get``) answers the same typo with ``workspace_not_found``.
A pair where the read refuses what the write invents is incoherent, and the
write is the worse half. The lazy-create path stays where a human can see
what they made: the argv lane.

No class-key fence and no reservation, for the same reasons the archive
records: this moves no actor rows, and it is one store call under one
``office_lock`` guarded by ``expect_revision``, so a transport retry
converges.

## `runtime.office.resolve_conflict`

From the docstring of `agent_runtime/serve_rpc/office_surface_writes.py::_runtime_office_resolve_conflict`.

Why ``take`` is validated HERE and not left to the store
-------------------------------------------------------
``OfficeStore.resolve_conflict`` answers an unrecognized ``take`` with
``ValueError("invalid_request")`` — a bare string that carries no field
name, and which this handler would then have to spend its ``actor_invalid``
reason on, telling the client to inspect a payload whose only fault is one
enum value. The typed reason is cheaper client-side and the check runs
BEFORE the store is touched at all, so a nonsense ``take`` cannot even open
the workspace it named.

Why an already-resolved conflict is a 4001 and NOT the remove's idempotent
ok
-------------------------------------------------------------------------
The two verbs look like they should agree here and must not. A repeat
ARCHIVE describes the state the store is already in, so answering ok costs
nothing and writes nothing. A repeat RESOLVE has no conflict to adopt: the
sidecar is gone, the store has no remote copy to read, and the only way to
answer ok would be to invent one. ``resolve_conflict`` refuses that with
``SyncConflict("no_conflict:…")``, and this lane translates it to
``4001 {reason: "conflict_not_found"}`` — a 4001 rather than 4090 because
nothing raced: the named conflict does not exist, which is the same shape of
answer the read leg gives an unknown workspace. Note that ``SyncConflict``
means the OPPOSITE thing on ``runtime.office.upsert`` (there a sidecar
EXISTS and blocks the write, so it is a 4090 ``sync_conflict``); copying
that arm here would tell a client to fetch an operator for a conflict that
has already been resolved.

``NotFound`` lands on the same reason on purpose. It is reachable only as a
race — the live actor file disappearing between ``actor_exists`` and
``get_actor`` inside the store — and the client's cure is identical: refetch
the projection, there is nothing here to resolve.

NO ``allow_class_key``, and that asymmetry is the contract
---------------------------------------------------------
``take="remote"`` writes a PEER's actor with ``_write_actor``, past
``upsert_actor`` and every guard its callers hold, so its class-key fence
lives inside the store (``OfficeStore._guard_class_keyed_adoption``) where a
second caller inherits it instead of having to remember it. This method is
that second caller, and it arrives fenced by construction because it calls
the same store method the CLI does.

The override stays where consent lives. ``harness office resolve-conflict
--allow-class-key`` is an operator who read the refusal and typed it; a wire
PARAMETER is not consent — it is a constant in a client build, set once by
whoever was debugging the day resolves started failing, and thereafter sent
by every install on every resolution with no human in any loop. So this
handler takes no such param, forwards no such param, and an unknown
``allow_class_key`` key in ``params`` is inert. The sanctioned override arms
are untouched: the CLI flag, and ``harness office actor-restore``.

Which is also why the refusal message is BUILT here rather than passed
through. The store's sentence ends by offering ``--allow-class-key`` and
``--take local``; the first is advice this caller cannot follow, and the
upsert's arm already ruled that advice a caller cannot follow is worse than
none. The wire message names the one exit this lane really has —
``take: "local"`` — and the machine-readable evidence rides ``data`` with
the same keys the upsert's collision spends, so one client branch covers
``class_key_collision`` whichever verb hit it.
