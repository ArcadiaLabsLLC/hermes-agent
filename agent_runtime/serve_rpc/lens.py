"""``runtime.lens.*`` — Eternia Lens on the method lane (plan ``eternia-lens-in-hermes.md`` §3).

The one-import seam the plan names: Lens's verbs register here, in fork-owned
``serve_rpc/``, so no upstream file is edited. Tier ``console`` for every verb: a
monitor names the operator's own systems, and a credential is theirs.

=====================  ================================================================
verb                   params -> result
=====================  ================================================================
list                   {} -> {monitors, feed_kinds}
create                 {manifest} -> monitor (the manifest becomes its DRAFT)
seal                   {monitor_id} -> monitor (draft frozen as the next revision)
enable / pause         {monitor_id} -> monitor (polling of the sealed revision on / off)
retire                 {monitor_id} -> monitor (stopped for good; its data stays)
get                    {monitor_id} -> monitor + credentials: [{feed_id, ref, set, rotated_at}]
preview                {manifest} -> {feeds: [{feed_id, status, number, reason, http_status}]}
                       (one read per feed, typed as the poller would store it;
                       NOTHING is written)
latest                 {monitor_id} -> {latest: [row per feed]}
range                  {monitor_id, feed_id, start_ms, end_ms} -> {series, observations, rollups}
episodes               {monitor_id?, state?} -> {episodes}
fold                   {} -> the Mission Control fold (``lens.snapshot_fold``)
credential.set         {ref, scheme, secret, username?} -> {ref, set, rotated_at}
                       (write-only: no verb returns a credential value)
receipt                {episode_id} -> the exit door's receipt for that Episode (stage L2)
receipts               {monitor_id?, limit?} -> {receipts} (newest first; limit <= 256)
artifact               {episode_id, name} -> {name, media_type, size_bytes, sha256, encoding, content}
                       (one file from the Episode's folder only; 1 MiB, text and images)
=====================  ================================================================

Every refusal carries ``data.reason`` (a ``WireRefusal`` or ``StoreRefusal`` value)
and, for a schema refusal, ``data.detail`` naming the field — never a value.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_lens_list"]

#: The longest range one call may read (the raw window is 24 h; rollups cover 7 d).
MAXIMUM_RANGE = timedelta(days=7)
MAXIMUM_RANGE_ROWS = 10_000
SERIES_SCHEMA = "lens-range-v1"


def _lens_call(rid: Any, body: Callable[[], dict]) -> dict:
    """Run ``body``; turn a Lens refusal into its typed frame."""

    from agent_runtime.lens.artifacts import ArtifactRefusal, LensArtifactError
    from agent_runtime.lens.store import NOT_FOUND_REFUSALS, LensStoreError
    from agent_runtime.lens.wire_value import WireError

    try:
        return ok(rid, body())
    except WireError as exc:
        return err(rid, ERR_INVALID_PARAMS, "The Lens request was refused.",
                   {"reason": exc.code.value, "detail": exc.detail})
    except LensStoreError as exc:
        code = ERR_NOT_FOUND if exc.code in NOT_FOUND_REFUSALS else ERR_CONFLICT
        return err(rid, code, "The Lens store refused the request.", {"reason": exc.code.value})
    except LensArtifactError as exc:
        code = ERR_NOT_FOUND if exc.code is ArtifactRefusal.NOT_FOUND else ERR_INVALID_PARAMS
        return err(rid, code, "The Lens artifact was refused.", {"reason": exc.code.value})


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
        monitors = [{key: row[key] for key in ("monitor_id", "state", "updated_at_ms")}
                    | {"revision": None if row["sealed"] is None else row["sealed"]["revision"]}
                    for row in _store().monitors()]
        return {"monitors": monitors, "feed_kinds": _feed_kinds()}

    return _lens_call(rid, body)


@method("runtime.lens.create", tier=TIER_CONSOLE)
def _runtime_lens_create(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    return _lens_call(rid, lambda: _store().create((params or {}).get("manifest")))


@method("runtime.lens.seal", tier=TIER_CONSOLE)
def _runtime_lens_seal(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    return _lens_call(rid, lambda: _store().seal(_monitor_id(params)))


def _state_verb(state_name: str) -> Callable[..., dict]:
    def handler(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
        from agent_runtime.lens.store import MonitorState

        return _lens_call(rid, lambda: _store().set_state(_monitor_id(params), MonitorState(state_name)))

    return handler


_runtime_lens_enable = method("runtime.lens.enable", tier=TIER_CONSOLE)(_state_verb("enabled"))
_runtime_lens_pause = method("runtime.lens.pause", tier=TIER_CONSOLE)(_state_verb("paused"))
_runtime_lens_retire = method("runtime.lens.retire", tier=TIER_CONSOLE)(_state_verb("retired"))


def _credentials_of(monitor: dict) -> list[dict]:
    from agent_runtime.lens.credentials import credential_status

    manifest = (monitor["sealed"] or {}).get("manifest") or monitor["draft"] or {"feeds": []}
    return [{"feed_id": feed["id"], **credential_status(feed["credential_ref"])}
            for feed in manifest["feeds"] if feed.get("credential_ref")]


@method("runtime.lens.get", tier=TIER_CONSOLE)
def _runtime_lens_get(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        monitor = _store().get(_monitor_id(params))
        return {**monitor, "credentials": _credentials_of(monitor)}

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
    def body() -> dict:
        store = _store()
        monitor = store.get(_monitor_id(params))
        manifest = (monitor["sealed"] or {}).get("manifest") or {"feeds": []}
        return {"monitor_id": monitor["monitor_id"],
                "latest": [store.latest(monitor["monitor_id"], feed["id"]) for feed in manifest["feeds"]]}

    return _lens_call(rid, body)


@method("runtime.lens.range", tier=TIER_CONSOLE)
def _runtime_lens_range(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """A bounded series with EXPLICIT gaps (the Generative UI chart's one read, plan §6a)."""

    def body() -> dict:
        from agent_runtime.lens.store import from_ms
        from agent_runtime.lens.wire_value import WireError, WireRefusal, bounded_int, opaque_id

        params_ = params or {}
        monitor_id, feed_id = _monitor_id(params_), opaque_id(params_.get("feed_id"))
        start, end = bounded_int(params_.get("start_ms")), bounded_int(params_.get("end_ms"))
        if not start < end or end - start > MAXIMUM_RANGE / timedelta(milliseconds=1):
            raise WireError(WireRefusal.INVALID_VALUE, "range_bound")
        store = _store()
        store.get(monitor_id)
        rows = store.observations(monitor_id, feed_id, start=from_ms(start), end=from_ms(end),
                                  limit=MAXIMUM_RANGE_ROWS + 1)
        rollups = [r for r in store.rollups(monitor_id, feed_id) if start <= r["minute_ms"] < end]
        return {"series": SERIES_SCHEMA, "monitor_id": monitor_id, "feed_id": feed_id, "start_ms": start,
                "end_ms": end, "observations": rows[:MAXIMUM_RANGE_ROWS],
                "truncated": len(rows) > MAXIMUM_RANGE_ROWS, "rollups": rollups}

    return _lens_call(rid, body)


@method("runtime.lens.episodes", tier=TIER_CONSOLE)
def _runtime_lens_episodes(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.episode import EpisodeState
        from agent_runtime.lens.wire_value import enum_value

        params_ = params or {}
        monitor_id = None if params_.get("monitor_id") is None else _monitor_id(params_)
        states = None if params_.get("state") is None else (enum_value(params_["state"], EpisodeState).value,)
        return {"episodes": _store().episodes(monitor_id=monitor_id, states=states)}

    return _lens_call(rid, body)


@method("runtime.lens.fold", tier=TIER_CONSOLE)
def _runtime_lens_fold(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.lens.snapshot_fold import lens_fold

    return _lens_call(rid, lens_fold)


@method("runtime.lens.credential.set", tier=TIER_CONSOLE)
def _runtime_lens_credential_set(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.credentials import CredentialScheme, set_credential
        from agent_runtime.lens.wire_value import checked_object, enum_value

        m = checked_object(params or {}, {"ref", "scheme", "secret"}, {"username"})
        return set_credential(m["ref"], scheme=enum_value(m["scheme"], CredentialScheme).value,
                              secret=m["secret"], username=m.get("username"))

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
        return {"receipts": _store().receipts(monitor_id=monitor_id, limit=limit)}

    return _lens_call(rid, body)


@method("runtime.lens.artifact", tier=TIER_CONSOLE)
def _runtime_lens_artifact(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.artifacts import read_artifact
        from agent_runtime.lens.wire_value import checked_object, digest_value

        m = checked_object(params or {}, {"episode_id", "name"})
        return read_artifact(digest_value(m["episode_id"]), m["name"])

    return _lens_call(rid, body)
