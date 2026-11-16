"""``runtime.lens.*`` — Eternia Lens on the method lane (plan ``eternia-lens-in-hermes.md`` §3).

The one-import seam the plan names: Lens's verbs register here, in fork-owned
``serve_rpc/``, so no upstream file is edited. Tier ``console`` for every verb: a
monitor names the operator's own systems, and a credential is theirs.

=====================  ================================================================
verb                   params -> result
=====================  ================================================================
list                   {workspace_id?} -> {monitors, feed_kinds}; a monitor row is {monitor_id,
                       state, updated_at_ms, revision, has_draft, workspace_id} — ``has_draft``
                       is true while a draft waits for seal: a new proposal, or a SEALED
                       monitor's next revision
create                 {manifest, workspace_id?} -> monitor (the manifest becomes its DRAFT; a
                       NEW monitor belongs to ``workspace_id``, else the active workspace)
seal                   {monitor_id, client_scope?} -> monitor (draft frozen as the next revision; the
                       verified client_scope records the account its Episode chats open for)
draft.drop             {monitor_id} -> monitor (a SEALED monitor's pending next-revision draft
                       is forgotten; the sealed revision and its state stand. ``no_draft``
                       without one, ``not_sealed`` for a never-sealed proposal: retire it)
enable / pause         {monitor_id} -> monitor (polling of the sealed revision on / off)
retire                 {monitor_id} -> monitor (stopped for good; its data stays)
get                    {monitor_id} -> monitor + credentials: [{feed_id, ref, set, rotated_at, host}]
                       (``set``: the value would be sent to THIS feed's address; ``host``: the
                       address it is saved for, null when none or saved before addresses were kept;
                       the rows are the sealed revision's feeds, else the draft's)
                       + draft_credentials: null | [the same rows for a SEALED monitor's waiting
                       next-revision draft] — what Seal would run with, so a draft that moves a
                       source to another site reads ``set: false`` there until it is signed in
                       + equivalence_evidence: null | {draft_digest, stale, members:
                       {<feed_id>: {why, cited}}} (a proposal's W5 justification; source-derived)
                       + guidance: {text, source: monitor|workspace|shipped, draft: null | {text,
                       source}} (the rules the sealed revision runs under, else the draft's;
                       ``draft`` is a waiting next revision's). A monitor's own rules are its
                       manifest's ``guidance`` key, written by ``create`` and frozen by ``seal``
                       + act_tools: null (not an act monitor) | {persona_id, missing: [tool] |
                       null (unreadable), restore_hint, persona_missing?} — the listed actions
                       the persona's bounded chat cannot reach (``lens/act_tools.py``)
guidance.default.get   {workspace_id?} -> {workspace_id, text, source: workspace|shipped,
                       updated_at_ms, shipped_text} (absent ``workspace_id``: the active workspace)
guidance.default.set   {workspace_id?, text: str | null} -> the same (``null`` forgets the workspace's
                       text and the shipped text applies; ``lens.guidance``, kept in the Lens store)
preview                {manifest} -> {feeds: [{feed_id, status, number, reason, http_status}]}
                       (one read per feed, typed as the poller would store it;
                       NOTHING is written)
latest                 {monitor_id} -> {latest: [row per feed]}
range                  {monitor_id, feed_id, start_ms, end_ms} -> {series, observations, rollups}
episodes               {monitor_id?, state?, workspace_id?} -> {episodes}; each row also carries
                       ``workspace_id`` (its monitor's) and ``orphan``: null, or why nothing will
                       ever observe it again (monitor_gone | monitor_retired | monitor_paused)
episode.decide         {episode_id, decision: dismiss|investigate|snooze15m} -> the Episode
                       (the operator's settle, ``lens.store_decisions``; a dismissed ORPHAN is
                       resolved; ``episode_not_found``, ``episode_settled`` for one already
                       closed or resolved)
episodes.close_orphans {workspace_id?} -> {closed: [Episode]} (every orphaned open Episode
                       resolved in one call, ``lens.store_scope``)
episode.close          {episode_id, workspace_id?} -> {closed: [Episode]} (ONE orphaned open
                       Episode resolved, the per-pill Close; ``episode_not_found`` for an id
                       no Episode carries or one outside ``workspace_id``, ``episode_settled``
                       for one already closed or resolved, ``episode_not_orphaned`` for one
                       its monitor still observes, ``episode_contended``)
fold                   {workspace_id?} -> the Mission Control fold (``lens.snapshot_fold``)
credential.set         {ref, scheme, secret, username?, monitor_id?, revision?: sealed|draft} ->
                       {ref, set, rotated_at, host}
                       (write-only: no verb returns a credential value. Saved for the ONE address
                       the live monitors naming ``ref`` read — scheme://name:port, never a request
                       param — and sent nowhere else: ``credential_host_unknown`` when no monitor
                       names it, ``credential_host_ambiguous`` when they read several addresses; a
                       feed at another address reads ``credential_host_mismatch``. ``monitor_id``
                       and ``revision``, given together, say WHICH manifest the sign-in is for:
                       that monitor's sealed revision or its waiting draft, so a draft that moved
                       a source is signed in before Seal and the sealed revision's own sign-in
                       stands — a name holds one sign-in per address, ``lens/credentials.py``;
                       ``monitor_not_found``, ``monitor_retired``, ``not_sealed``, ``no_draft``)
receipt                {episode_id} -> the exit door's receipt for that Episode (stage L2); a receipt that
                       ran a turn carries ``budget``: {tokens_used, token_limit, calls_used,
                       call_limit, stopped_by: null|tokens|calls}, else null
budget.get             {monitor_id?, workspace_id?} -> {lens: {limits, today: {tokens, turns}, bounds},
                       workspace: {workspace_id, limits, bounds}, monitor?: {monitor_id, limits,
                       today: {tokens}, bounds}} — each limit is {value, source: monitor |
                       workspace | lens | config}; ``workspace`` is the given one, else the
                       monitor's, else the active one (``lens/budget.py``)
budget.set             {scope: monitor|workspace|lens, monitor_id? | workspace_id?, limits: {key: int
                       | null}} -> budget.get's answer for that scope (monitor/workspace keys:
                       episode_tokens, episode_calls, daily_tokens; lens keys: daily_tokens,
                       daily_turns; null clears back to the next layer; stored in the Lens store,
                       so it survives a restart; takes effect from the next Episode)
receipts               {monitor_id?, limit?, workspace_id?} -> {receipts} (newest first; limit
                       <= 256; each row carries its monitor's ``workspace_id``)
actions                {episode_id? | monitor_id?, limit?, workspace_id?} -> {actions} (an ``act`` turn's
                       action receipts, newest first, limit <= 256, only ``workspace_id``'s monitors'
                       when it is given — RT-LENS-ACTIONS-TAKE-A-WORKSPACE; a row is {action_id, episode_id,
                       monitor_id, turn_id, tool, arguments_digest, arguments (a proposal's only,
                       else null), verdict: approve|deny|escalate|null, decided_by: rules|owner,
                       result: running|ran|failed|refused|proposed|approved|denied|expired, why: null|untrusted_text|
                       not_listed|cannot_be_undone|rules_unsure|rules_denied|owner_approved, undoable,
                       undo_handle, undone_by, created_ms, finished_ms, answered_ms, expires_ms (an open
                       proposal's, else null), follow_up_turn_id} — ``lens/store_actions.py``;
                       a proposal's result moves proposed -> approved | denied | expired
proposal.answer        {action_id, decision: approve|deny} -> the action row (result approved |
                       denied, answered_ms). An approval owes ONE follow-up turn in the Episode's
                       chat with that call pre-admitted once; the door claims it on its next tick
                       (``follow_up_turn_id``), and the call itself lands as a new action row
                       (decided_by owner, why owner_approved). ``proposal_not_found`` (not found),
                       ``proposal_settled`` (already answered or past its 24 h), ``episode_has_no_chat``
undo                   {action_id} -> {action (now with undone_by), receipt} — restores the file
                       an act action wrote from the before image Lens took (``undo_handle``:
                       {kind: file, path, existed}; a created file is removed) and writes an undo
                       receipt (tool undo, decided_by owner, result ran|failed, why undo);
                       ``action_not_found``, ``action_cannot_be_undone`` (no image, or it never
                       ran), ``action_already_undone`` (``lens/undo.py``)
artifact               {episode_id, name} -> {name, media_type, size_bytes, sha256, encoding, content}
                       (one file from the Episode's folder only; 1 MiB, text and images)
ingress.register       {monitor_id, kind, mapping?, auth?} -> {route_id, url, secret, kind, mapping,
                       auth, weaker, ...} (stage L3; the secret is in this answer ONCE, then
                       only in the home's credential file as ``ingress:<route_id>``;
                       ``auth: bearer``, alertmanager and a local bind only, is ``weaker``)
ingress.list           {monitor_id?} -> {routes, listener} (never a secret; listener =
                       {host, port, listening, bound_since_ms, url_base, maximum_body_bytes,
                       bind_error}; bind_error is null or, while a route wants the door and
                       the last bind failed, {reason: address_in_use | permission_denied |
                       other, host, port, errno, at_ms})
ingress.revoke         {route_id} -> the route + revoked (its secret is forgotten)
ingress.bind           {host, port} -> listener (loopback or a private address only; the
                       running listener moves, a door whose bind failed is retried there;
                       written to the head home's ``lens/ingress.json``, so each serve's
                       home holds its own port — the default is 127.0.0.1:47652)
=====================  ================================================================

``workspace_id`` (RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS): given, a read answers only that
workspace's monitors and their Episodes and receipts; absent, every workspace — the
all-workspaces read, and the answer these verbs always gave.

The four ``runtime.lens.recipe.*`` verbs (share a monitor with its workspace, list, withdraw, add
one as a DRAFT) are ``serve_rpc/lens_recipes.py``'s; their table is in that module.

Every refusal is ONE frame, whichever part of Lens refused (``_lens_call``; row
``RT-LENS-RPC-REFUSALS-FIVE-EXCEPTION-SHAPES``): ``data: {reason, detail}``. ``reason`` is the
value of the refusing module's Enum (``WireRefusal``, ``StoreRefusal``, ``OwnerRefusal``,
``RecipeRefusal``, ``ArtifactRefusal``); ``detail`` names the field or feed — never a value — and
is ``""`` when the refusal names none. The error code is the refusal's kind: invalid params,
not found, or conflict. Pinned by ``tests/agent_runtime/lens/test_lens_refusal_frames.py``.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_lens_list"]

#: The error code of each ``lens.wire_value.RefusalKind`` value — the one rule for every Lens verb.
_REFUSAL_CODES = {"invalid": ERR_INVALID_PARAMS, "not_found": ERR_NOT_FOUND, "conflict": ERR_CONFLICT}

def _lens_call(rid: Any, body: Callable[[], dict]) -> dict:
    """Run ``body``; turn a Lens refusal — every one is a ``lens.wire_value.LensRefusal`` — into
    its frame: the error code of its kind (:data:`_REFUSAL_CODES`), its ``summary``, and
    ``data: {reason, detail}``.

    Every answer carries ``store_revision``, the Lens store revision read BEFORE ``body`` runs
    (``RT-LENS-STORE-HAS-ONE-REVISION``): what the answer shows is at least that fresh, so a reader
    comparing it with an event's revision may re-read once too often, never too seldom."""

    from agent_runtime.lens.revision import read_store_revision
    from agent_runtime.lens.wire_value import LensRefusal

    revision = read_store_revision(_store().path)
    try:
        result = body()
        if isinstance(result, dict):
            result = result | {"store_revision": revision}
        return ok(rid, result)
    except LensRefusal as exc:
        return err(rid, _REFUSAL_CODES[exc.kind.value], exc.summary,
                   {"reason": exc.reason.value, "detail": exc.detail})


def _monitor_id(params: dict) -> str:
    from agent_runtime.lens.wire_value import opaque_id

    return opaque_id((params or {}).get("monitor_id"))


def _store():
    from agent_runtime.lens.store import LensStore

    return LensStore()


def _feed_kinds() -> dict[str, str]:
    from agent_runtime.lens.feed import AVAILABLE_FEED_KINDS, FeedKind

    return {kind.value: ("available" if kind in AVAILABLE_FEED_KINDS else "unavailable") for kind in FeedKind}


@method("runtime.lens.list", tier=TIER_CONSOLE)
def _runtime_lens_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.store_scope import workspace_param

        workspace_id = workspace_param(params)
        monitors = [{key: row[key] for key in ("monitor_id", "state", "updated_at_ms", "workspace_id")}
                    | {"revision": None if row["sealed"] is None else row["sealed"]["revision"],
                       "has_draft": row["draft"] is not None}
                    for row in _store().monitors()
                    if workspace_id is None or row["workspace_id"] == workspace_id]
        return {"monitors": monitors, "feed_kinds": _feed_kinds()}

    return _lens_call(rid, body)


@method("runtime.lens.create", tier=TIER_CONSOLE)
def _runtime_lens_create(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.store_scope import active_workspace_id, workspace_param

        workspace_id = workspace_param(params) or active_workspace_id()
        return _store().create((params or {}).get("manifest"), workspace_id=workspace_id)

    return _lens_call(rid, body)


def _seal_scope(params: dict, context: RpcContext | None) -> str | None:
    """The account scope this seal may record (``store_owner.verified_seal_scope``): a paired
    device is held to the scope its pairing bound, read off the device store, never the request."""

    from agent_runtime.call_authorization import CALLER_DEVICE
    from agent_runtime.lens.store_owner import verified_seal_scope

    caller = getattr(context, "caller", None)
    if getattr(caller, "kind", None) != CALLER_DEVICE:
        return verified_seal_scope(params or {}, None, device=False)
    from agent_runtime.serve_rpc.channel import _device_identity

    return verified_seal_scope(params or {}, _device_identity(caller.device_id)[1], device=True)


@method("runtime.lens.seal", tier=TIER_CONSOLE)
def _runtime_lens_seal(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``{monitor_id, client_scope?}``: seal the draft; the verified ``client_scope`` names the
    account the monitor's Episode chats open for (RT-LENS-EPISODE-CHAT-OWNED-BY-THE-MONITORS-ACCOUNT)."""

    return _lens_call(rid, lambda: _store().seal(_monitor_id(params), client_scope=_seal_scope(params, context)))


@method("runtime.lens.draft.drop", tier=TIER_CONSOLE)
def _runtime_lens_draft_drop(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    return _lens_call(rid, lambda: _store().drop_draft(_monitor_id(params)))


def _state_verb(state_name: str) -> Callable[..., dict]:
    def handler(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
        from agent_runtime.lens.store import MonitorState

        return _lens_call(rid, lambda: _store().set_state(_monitor_id(params), MonitorState(state_name)))

    return handler


_runtime_lens_enable = method("runtime.lens.enable", tier=TIER_CONSOLE)(_state_verb("enabled"))
_runtime_lens_pause = method("runtime.lens.pause", tier=TIER_CONSOLE)(_state_verb("paused"))
_runtime_lens_retire = method("runtime.lens.retire", tier=TIER_CONSOLE)(_state_verb("retired"))


def _credentials_of(manifest: dict) -> list[dict]:
    """One row per feed of ``manifest`` that names a credential: would it be sent to that feed's address."""

    from agent_runtime.lens.credentials import credential_status, feed_host

    return [{"feed_id": feed["id"], **credential_status(feed["credential_ref"], host=feed_host(feed))}
            for feed in manifest["feeds"] if feed.get("credential_ref")]


def _monitor_answer(monitor_id: str) -> dict:
    """``runtime.lens.get``'s answer for one monitor (also what ``runtime.lens.recipe.add`` returns)."""

    from agent_runtime.lens.act_tools import act_tools
    from agent_runtime.lens.guidance import monitor_guidance
    from agent_runtime.lens.store_proposals import equivalence_evidence

    store = _store()
    monitor = store.get(monitor_id)
    sealed, draft = (monitor["sealed"] or {}).get("manifest"), monitor["draft"]
    manifest = sealed or draft
    return {**monitor, "credentials": _credentials_of(manifest or {"feeds": []}),
            "draft_credentials": None if sealed is None or draft is None else _credentials_of(draft),
            "equivalence_evidence": equivalence_evidence(store, monitor),
            "guidance": monitor_guidance(store, monitor), "act_tools": act_tools(manifest)}


@method("runtime.lens.get", tier=TIER_CONSOLE)
def _runtime_lens_get(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    return _lens_call(rid, lambda: _monitor_answer(_monitor_id(params)))


def _default_workspace(params: dict) -> str | None:
    from agent_runtime.lens.store_scope import active_workspace_id, workspace_param

    return workspace_param(params) or active_workspace_id()


@method("runtime.lens.guidance.default.get", tier=TIER_CONSOLE)
def _runtime_lens_guidance_default_get(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.lens.guidance import workspace_guidance

    return _lens_call(rid, lambda: workspace_guidance(_store(), _default_workspace(params)))


@method("runtime.lens.guidance.default.set", tier=TIER_CONSOLE)
def _runtime_lens_guidance_default_set(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.guidance import set_workspace_guidance
        from agent_runtime.lens.wire_value import checked_object

        m = checked_object(params if params is not None else {}, {"text"}, {"workspace_id"})
        return set_workspace_guidance(_store(), _default_workspace(m), m["text"])

    return _lens_call(rid, body)


@method("runtime.lens.preview", tier=TIER_CONSOLE)
def _runtime_lens_preview(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.manifest import read_manifest
        from agent_runtime.lens.sources import preview_reads

        manifest = read_manifest((params or {}).get("manifest"))
        # The value the poller would store, not the raw read (W2: a refused read is a gap; W5: a total).
        return {"monitor_id": manifest["monitor_id"],
                "feeds": [{"feed_id": feed_id, **result.to_json()}
                          for feed_id, result in preview_reads(manifest).items()]}

    return _lens_call(rid, body)


@method("runtime.lens.latest", tier=TIER_CONSOLE)
def _runtime_lens_latest(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    return _lens_call(rid, lambda: _store().latest_reads(_monitor_id(params)))


@method("runtime.lens.range", tier=TIER_CONSOLE)
def _runtime_lens_range(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A bounded series with EXPLICIT gaps (the Generative UI chart's one read, plan §6a)."""

    def body() -> dict:
        from agent_runtime.lens.wire_value import bounded_int, opaque_id

        params_ = params or {}
        return _store().series(_monitor_id(params_), opaque_id(params_.get("feed_id")),
                               start_ms=bounded_int(params_.get("start_ms")), end_ms=bounded_int(params_.get("end_ms")))

    return _lens_call(rid, body)


@method("runtime.lens.episodes", tier=TIER_CONSOLE)
def _runtime_lens_episodes(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.episode import EpisodeState
        from agent_runtime.lens.wire_value import enum_value

        params_ = params or {}
        monitor_id = None if params_.get("monitor_id") is None else _monitor_id(params_)
        states = None if params_.get("state") is None else (enum_value(params_["state"], EpisodeState).value,)
        from agent_runtime.lens.store_scope import with_scope, workspace_param

        workspace_id = workspace_param(params_)
        store = _store()
        rows = store.episodes(monitor_id=monitor_id, states=states, workspace_id=workspace_id)
        return {"episodes": with_scope(store, rows)}

    return _lens_call(rid, body)


@method("runtime.lens.episodes.close_orphans", tier=TIER_CONSOLE)
def _runtime_lens_episodes_close_orphans(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from datetime import UTC, datetime

        from agent_runtime.lens.store_scope import close_orphans, workspace_param

        return {"closed": close_orphans(_store(), datetime.now(UTC), workspace_id=workspace_param(params))}

    return _lens_call(rid, body)


@method("runtime.lens.episode.close", tier=TIER_CONSOLE)
def _runtime_lens_episode_close(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from datetime import UTC, datetime

        from agent_runtime.lens.store_scope import close_orphan, workspace_param
        from agent_runtime.lens.wire_value import checked_object, digest_value

        m = checked_object(params or {}, {"episode_id"}, {"workspace_id"})
        return {"closed": close_orphan(_store(), digest_value(m["episode_id"]), datetime.now(UTC),
                                       workspace_id=workspace_param(m))}

    return _lens_call(rid, body)


@method("runtime.lens.episode.decide", tier=TIER_CONSOLE)
def _runtime_lens_episode_decide(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from datetime import UTC, datetime

        from agent_runtime.lens.episode import Decision
        from agent_runtime.lens.store_decisions import decide_episode
        from agent_runtime.lens.wire_value import checked_object, digest_value, enum_value

        m = checked_object(params or {}, {"episode_id", "decision"})
        return decide_episode(_store(), digest_value(m["episode_id"]), enum_value(m["decision"], Decision),
                              datetime.now(UTC))

    return _lens_call(rid, body)


@method("runtime.lens.fold", tier=TIER_CONSOLE)
def _runtime_lens_fold(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.lens.snapshot_fold import lens_fold
    from agent_runtime.lens.store_scope import workspace_param

    return _lens_call(rid, lambda: lens_fold(workspace_id=workspace_param(params)))


@method("runtime.lens.credential.set", tier=TIER_CONSOLE)
def _runtime_lens_credential_set(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.credentials import (
            CredentialScheme, SignInRevision, named_hosts, revision_manifest, set_credential, sign_in_host,
        )
        from agent_runtime.lens.store import MonitorState
        from agent_runtime.lens.wire_value import checked_object, enum_value, opaque_id

        m = checked_object(params or {}, {"ref", "scheme", "secret"}, {"username", "monitor_id", "revision"})
        ref = opaque_id(m["ref"])
        store = _store()
        # The address is the store's word, never the request's: every live monitor's sealed
        # revision and waiting draft that names the ref — or the ONE manifest the request points at.
        live = [manifest for row in store.monitors() if row["state"] != MonitorState.RETIRED.value
                for manifest in ((row["sealed"] or {}).get("manifest"), row["draft"]) if manifest is not None]
        chosen = live
        if "monitor_id" in m or "revision" in m:
            chosen = [revision_manifest(store.get(_monitor_id(m)), enum_value(m.get("revision"), SignInRevision))]
        return set_credential(ref, scheme=enum_value(m["scheme"], CredentialScheme).value, secret=m["secret"],
                              username=m.get("username"), host=sign_in_host(ref, chosen),
                              live_hosts=named_hosts(ref, live))

    return _lens_call(rid, body)


MAXIMUM_RECEIPTS_PAGE = 256


@method("runtime.lens.receipt", tier=TIER_CONSOLE)
def _runtime_lens_receipt(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.wire_value import digest_value

        return _store().receipt(digest_value((params or {}).get("episode_id")))

    return _lens_call(rid, body)


@method("runtime.lens.receipts", tier=TIER_CONSOLE)
def _runtime_lens_receipts(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.wire_value import bounded_int

        params_ = params or {}
        monitor_id = None if params_.get("monitor_id") is None else _monitor_id(params_)
        limit = bounded_int(params_.get("limit", 32), minimum=1, maximum=MAXIMUM_RECEIPTS_PAGE)
        store = _store()
        from agent_runtime.lens.store_scope import with_scope, workspace_param

        rows = store.receipts(monitor_id=monitor_id, limit=limit, workspace_id=workspace_param(params_))
        reply: dict = {"receipts": with_scope(store, rows, episodes=False)}
        if monitor_id is not None:  # the days retention folded (RT-LENS-RECEIPT-RETENTION L3)
            reply["rollups"] = store.receipt_rollups(monitor_id)
        return reply

    return _lens_call(rid, body)


@method("runtime.lens.actions", tier=TIER_CONSOLE)
def _runtime_lens_actions(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.store_actions import MAXIMUM_ACTIONS_PAGE, actions
        from agent_runtime.lens.wire_value import bounded_int, checked_object, digest_value

        from agent_runtime.lens.store_scope import workspace_param

        m = checked_object(params or {}, (), {"episode_id", "monitor_id", "limit", "workspace_id"})
        episode_id = None if m.get("episode_id") is None else digest_value(m["episode_id"])
        monitor_id = None if m.get("monitor_id") is None else _monitor_id(m)
        limit = bounded_int(m.get("limit", 32), minimum=1, maximum=MAXIMUM_ACTIONS_PAGE)
        return {"actions": actions(_store(), episode_id=episode_id, monitor_id=monitor_id, limit=limit,
                                   workspace_id=workspace_param(m))}

    return _lens_call(rid, body)


@method("runtime.lens.proposal.answer", tier=TIER_CONSOLE)
def _runtime_lens_proposal_answer(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens import store_actions
        from agent_runtime.lens.store import LensStoreError, StoreRefusal
        from agent_runtime.lens.store_actions import action, answer_proposal
        from agent_runtime.lens.wire_value import checked_object, opaque_id, require

        m = checked_object(params or {}, {"action_id", "decision"})
        action_id = opaque_id(m["action_id"])
        require(m["decision"] in ("approve", "deny"), "decision")
        store = _store()
        if m["decision"] == "approve":
            found = action(store, action_id)
            try:
                has_chat = found is not None and bool(store.receipt(found["episode_id"]).get("session_id"))
            except LensStoreError:
                has_chat = False
            if found is not None and found["result"] == "proposed" and not has_chat:
                raise LensStoreError(StoreRefusal.EPISODE_HAS_NO_CHAT)
        return answer_proposal(store, action_id, approve=m["decision"] == "approve",
                               now_ms=store_actions.wall_ms())

    return _lens_call(rid, body)


@method("runtime.lens.undo", tier=TIER_CONSOLE)
def _runtime_lens_undo(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens import store_actions
        from agent_runtime.lens.undo import undo
        from agent_runtime.lens.wire_value import checked_object, opaque_id

        m = checked_object(params or {}, {"action_id"})
        return undo(_store(), opaque_id(m["action_id"]), now_ms=store_actions.wall_ms())

    return _lens_call(rid, body)


@method("runtime.lens.artifact", tier=TIER_CONSOLE)
def _runtime_lens_artifact(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.artifacts import read_artifact
        from agent_runtime.lens.wire_value import checked_object, digest_value

        m = checked_object(params or {}, {"episode_id", "name"})
        return read_artifact(digest_value(m["episode_id"]), m["name"])

    return _lens_call(rid, body)


@method("runtime.lens.ingress.register", tier=TIER_CONSOLE)
def _runtime_lens_ingress_register(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.ingress_routes import register_route
        from agent_runtime.lens.wire_value import checked_object

        m = checked_object(params or {}, {"monitor_id", "kind"}, {"mapping", "auth"})
        return register_route(m["monitor_id"], m["kind"], m.get("mapping"), auth=m.get("auth"))

    return _lens_call(rid, body)


@method("runtime.lens.ingress.list", tier=TIER_CONSOLE)
def _runtime_lens_ingress_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.ingress_routes import list_routes

        from agent_runtime.lens.ingress import ingress_state

        return {"routes": list_routes((params or {}).get("monitor_id")), "listener": ingress_state()}

    return _lens_call(rid, body)


@method("runtime.lens.ingress.revoke", tier=TIER_CONSOLE)
def _runtime_lens_ingress_revoke(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.ingress_routes import revoke_route
        from agent_runtime.lens.wire_value import checked_object

        return revoke_route(checked_object(params or {}, {"route_id"})["route_id"])

    return _lens_call(rid, body)


@method("runtime.lens.ingress.bind", tier=TIER_CONSOLE)
def _runtime_lens_ingress_bind(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.ingress import bind_ingress
        from agent_runtime.lens.wire_value import checked_object

        m = checked_object(params or {}, {"host", "port"})
        return bind_ingress(m["host"], m["port"])

    return _lens_call(rid, body)


@method("runtime.lens.budget.get", tier=TIER_CONSOLE)
def _runtime_lens_budget_get(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from datetime import UTC, datetime

        from agent_runtime.lens.budget import budget_view

        return budget_view(_store(), params or {}, datetime.now(UTC))

    return _lens_call(rid, body)


@method("runtime.lens.budget.set", tier=TIER_CONSOLE)
def _runtime_lens_budget_set(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.budget import set_limits

        return set_limits(_store(), params or {})

    return _lens_call(rid, body)
