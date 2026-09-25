"""``consult`` — the one entry the snapshot builder asks: read, judge, log the
demote, and decide.
"""

from __future__ import annotations

from agent_runtime.core_cache.vocabulary import (
    CORE_SOURCE_CACHE,
    CORE_SOURCE_REBUILT,
    DEMOTE_ABSENT,
    DEMOTE_FINGERPRINT_MISMATCH,
    DIFF_SCOPE_LAST_PAIR,
    DIFF_UNAVAILABLE_NO_ENTRIES,
    DIFF_UNAVAILABLE_NO_ENTRY_DELTA,
    logger,
)
from agent_runtime.core_cache.models import CoreDecision, CoreFingerprint
from agent_runtime.core_cache.convergence import (
    _changed_paths,
    _diff_detail,
    _diff_unavailable_detail,
)
from agent_runtime.core_cache.read import (
    _persisted_entries,
    label_core,
    read_persisted_core,
)
from agent_runtime.core_cache.lane import _armed_window_read, lane_armed

__layer__ = "lanes"

__all__ = [
    "_demote_diff_detail",
    "_log_demote",
    "consult",
]


def _demote_diff_detail(key: CoreFingerprint | None, sidecar: dict | None) -> str:
    """WHICH inputs moved between the persisted write-back and this walk.

    **The scope is ``last_pair`` by construction, and that is a census caveat, not
    a detail.** This is the delta since the LAST WRITE-BACK, so on a store that is
    simply busy it legitimately names files that are simply moving. It is
    self-perturbation evidence — the A1-b/A2 defect worth acting on — only when
    the named paths are ones the RUNTIME ITSELF writes. The channel table row
    carries the reading rule; the token on the line is the honest scope rather
    than a new one invented to flatter the diagnostic.

    Every arm that cannot answer says so in its OWN words through
    :func:`_diff_unavailable_detail`, never by returning an empty diff — an empty
    ``diff=`` reads to a census exactly like "we looked and nothing moved", which
    is C16's lesson and is the one way this receipt could mislead.
    """

    if key is None or not key.entries:
        return _diff_unavailable_detail(DIFF_UNAVAILABLE_NO_ENTRIES)
    persisted, unavailable = _persisted_entries(
        expect_digest=(sidecar or {}).get("fingerprint")
    )
    if persisted is None:
        return _diff_unavailable_detail(unavailable)
    changed = _changed_paths(persisted.entries, key.entries)
    if not changed:
        # The digests disagreed and no triple did. Nothing here can be named, and
        # borrowing the ``last_pair`` sentence for it would report a measurement
        # that was never taken.
        return _diff_unavailable_detail(DIFF_UNAVAILABLE_NO_ENTRY_DELTA)
    return _diff_detail(DIFF_SCOPE_LAST_PAIR, list(changed))


def _log_demote(
    *, caller: str, reason: str, key: CoreFingerprint | None, sidecar: dict | None = None
) -> None:
    """The demote receipt — and, on a fingerprint miss ONLY, what moved (A1-b).

    Before this, a read-miss said ``reason=fingerprint_mismatch inputs=23107``
    and nothing else, so the operator saw the same line on every same-commit boot
    with nothing to act on, and no process — not the serve, not a read-only
    investigation — could name the file that moved. The absence was the finding.

    TWO things keep the tail honest, and both are load-bearing:

    * **It is computed LAZILY and only for ``fingerprint_mismatch``.** The hit
      path pays nothing — it never reaches here — and the other demote reasons
      are not "an input moved": a diff on a ``build_stamp_mismatch`` would name
      every file the operator's upgrade touched and read to a census as store
      churn, which is a measurement that would be true of the wrong thing.
    * **``diff=`` goes LAST on the line**, after ``changed=``, for the reason
      already written at :func:`_receipt_never_converged`: it is a
      variable-length list and a path may contain spaces, so nothing can be
      field-parsed after it. The tail is purely ADDITIVE — an existing
      ``reason=`` grep is unaffected, which is what made this approvable as a
      change to production log text.

    The diff is worded by :func:`_changed_paths` and :func:`_diff_detail`, the
    never-converged receipt's own helpers, so the two receipts spell ONE
    vocabulary and are told apart by their family/event token exactly as the C22
    table teaches — never by two spellings of one fact.
    """

    detail = (
        " " + _demote_diff_detail(key, sidecar)
        if reason == DEMOTE_FINGERPRINT_MISMATCH
        else ""
    )
    logger.info(
        "snapshot_core_cache core_source=%s caller=%s reason=%s inputs=%s%s",
        CORE_SOURCE_REBUILT,
        caller,
        reason,
        "unknown" if key is None else key.count,
        detail,
    )


def consult(*, caller: str, fingerprint: CoreFingerprint | None = None) -> CoreDecision:
    """The read half of the stage: serve the persisted core, or say why not.

    Runs on the default-store path only, while the lane is armed. On a match it
    emits its OWN receipt (``snapshot_core_cache core_source=cache``) and
    deliberately does NOT emit ``snapshot_build_core role=led``: there was no
    build, and a receipt claiming one would put the log back in the state EG-2.1
    just took it out of, where a wait and a build are indistinguishable.

    Every demote is logged with its reason — except ``absent``, which is the
    ordinary cold-start shape and would otherwise print a line on every build in
    every process that has no cache to consult.

    The riders of one boot share ONE judgement (:data:`_consult_memo`) and each
    still emits its OWN receipt: the log stays a per-caller account of what each
    asker was told, while the store is walked once. A caller that hands in its
    own ``fingerprint`` is answered from that key alone and never touches the
    shared window.
    """

    if not lane_armed():
        return CoreDecision(None, False, "")
    read = (
        _armed_window_read()
        if fingerprint is None
        else read_persisted_core(fingerprint=fingerprint)
    )
    if not read.matched or read.core is None:
        if read.reason != DEMOTE_ABSENT:
            # The sidecar rides along so a fingerprint miss can be diffed against
            # the entries THAT pair persisted — the binding rule at
            # ``entries_path``. Handing the judgement's own sidecar rather than
            # re-reading one is what keeps the diff about the generation that was
            # actually judged.
            _log_demote(
                caller=caller,
                reason=read.reason,
                key=read.fingerprint,
                sidecar=read.sidecar,
            )
        return CoreDecision(None, read.reason != DEMOTE_ABSENT, read.reason)
    core = label_core(read.core, source=CORE_SOURCE_CACHE, stale=False)
    logger.info(
        "snapshot_core_cache core_source=%s caller=%s inputs=%d fingerprint=%s offset=%s",
        CORE_SOURCE_CACHE,
        caller,
        read.fingerprint.count if read.fingerprint else -1,
        read.fingerprint.digest[:12] if read.fingerprint else "unknown",
        read.sidecar.get("event_offset", "unknown"),
    )
    return CoreDecision(core, False, "")
