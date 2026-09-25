"""Reading the persisted pair back and judging it against the live
fingerprint: ``read_persisted_core``, the demote checks, ``label_core``.
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.core_cache.vocabulary import (
    CORE_FILENAME,
    CORE_SOURCE_CACHE,
    DEMOTE_ABSENT,
    DEMOTE_BUILD_STAMP_MISMATCH,
    DEMOTE_BUILD_STAMP_UNKNOWN,
    DEMOTE_CONTRACT_MISMATCH,
    DEMOTE_CORE_DIGEST_MISMATCH,
    DEMOTE_FINGERPRINT_MISMATCH,
    DEMOTE_FINGERPRINT_UNAVAILABLE,
    DEMOTE_HOME_MISMATCH,
    DEMOTE_RUNTIME_ROOT_MISMATCH,
    DEMOTE_UNREADABLE,
    DIFF_UNAVAILABLE_ENTRIES_UNBOUND,
    DIFF_UNAVAILABLE_NO_ENTRIES,
    SIDECAR_FILENAME,
)
from agent_runtime.core_cache.models import (
    CacheRead,
    CoreFingerprint,
    FingerprintEntry,
    PersistedEntries,
)
from agent_runtime.core_cache.home import resolved_fingerprint_home
from agent_runtime.core_cache.fingerprint import (
    build_input_fingerprint,
    build_stamp_token,
    contract_versions,
)
from agent_runtime.core_cache.generations import (
    _core_digest,
    _live_generation_dir,
    entries_path,
)

__layer__ = "stores"

__all__ = [
    "_judge_persisted_pair",
    "_persisted_entries",
    "_read_pair",
    "_runtime_root_for_sidecar",
    "_sidecar_answers_a_different_question",
    "label_core",
    "read_persisted_core",
]


def _persisted_entries(*, expect_digest: Any) -> tuple[PersistedEntries | None, str]:
    """The stat set behind a persisted digest, or a TYPED reason it is unusable.

    Returns ``(record, "")`` on success and ``(None, <diff_reason>)`` otherwise.
    Never raises: a diagnostic that could take down the lane it explains is worse
    than no diagnostic.

    ``expect_digest`` is the SIDECAR's fingerprint, and the comparison is the
    binding rule :func:`entries_path` documents — which MCF-21 re-aimed rather
    than retired: the swap makes cross-generation mixing unrepresentable, and this
    check now convicts an entries file inside the LIVE generation whose contents
    are not the ones the write-back put there. It is a required keyword rather
    than an optional check, because "read the entries" and "read the entries that
    belong to this pair" are different operations and only one of them is sound —
    an optional check is one call site away from being the unsound one.
    """

    try:
        raw = entries_path().read_text(encoding="utf-8")
    except OSError:
        return None, DIFF_UNAVAILABLE_NO_ENTRIES
    try:
        payload = json.loads(raw)
    except Exception:
        return None, DIFF_UNAVAILABLE_NO_ENTRIES
    if not isinstance(payload, dict):
        return None, DIFF_UNAVAILABLE_NO_ENTRIES
    rows = payload.get("entries")
    if not isinstance(rows, list):
        return None, DIFF_UNAVAILABLE_NO_ENTRIES
    if not expect_digest or payload.get("fingerprint") != expect_digest:
        return None, DIFF_UNAVAILABLE_ENTRIES_UNBOUND
    entries: list[FingerprintEntry] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            return None, DIFF_UNAVAILABLE_NO_ENTRIES
        path, mtime_ns, size = row
        try:
            entries.append(FingerprintEntry(str(path), int(mtime_ns), int(size)))
        except (TypeError, ValueError):
            return None, DIFF_UNAVAILABLE_NO_ENTRIES
    try:
        # Absent on every entries file written before the streak was persisted,
        # which is a legitimate shape and not a refusal: it means "this
        # write-back recorded no streak", i.e. zero.
        streak = int(payload.get("streak") or 0)
    except (TypeError, ValueError):
        streak = 0
    return PersistedEntries(tuple(entries), streak), ""


def _runtime_root_for_sidecar(parity: dict) -> Any:
    identity = parity.get("runtime_root") if isinstance(parity.get("runtime_root"), dict) else {}
    resolved = identity.get("resolved") or identity.get("path")
    if resolved:
        return resolved
    try:
        from .. import paths as _paths

        return _paths.store_root()
    except Exception:
        return ""


def read_persisted_core(*, fingerprint: CoreFingerprint | None = None) -> CacheRead:
    """Load the persisted pair and judge it. Never raises.

    The judgement is a conjunction and each clause has its own demote reason on
    the receipt, because "the cache did not answer" is useless to an operator
    without WHY: bytes that do not match the sidecar, a fingerprint that moved,
    an install that changed, a contract that moved, a root that is not this one.

    The clauses are ordered CHEAPEST-FIRST, deliberately. The stat set is a walk
    of every build input; a process with no persisted core to judge — every cold
    CLI invocation, every test with a fresh root — must not pay for one to be
    told there is nothing to compare it against.

    **This primitive is never memoised.** Every call reads the pair and, unless
    handed a key, walks the store. The boot lane's shared answer lives behind
    :func:`_armed_window_read`, reached only through :func:`consult` and
    :func:`take_stale_first_core`; a caller that asks this function directly is
    asking for a fresh judgement and gets one.
    """

    pair = _read_pair()
    if pair is None:
        return CacheRead(None, False, DEMOTE_ABSENT, None, {})
    return _judge_persisted_pair(pair[0], pair[1], fingerprint=fingerprint)


def _read_pair() -> tuple[str, str] | None:
    """The persisted BYTES, or ``None`` when there is no pair to judge.

    Its own function so the boot lane can count and memoise the READ separately
    from the judgement — and so a witness can prove one read happened rather than
    inferring it from a duration.

    The generation is resolved ONCE and both files are read out of it, rather than
    asking :func:`sidecar_path` and :func:`core_path` in turn. Two resolutions
    could straddle a publish and read one file from each of two generations, which
    is precisely the torn read MCF-21 exists to end — reintroduced by the reader
    instead of the writer.
    """

    generation = _live_generation_dir()
    try:
        return (
            (generation / SIDECAR_FILENAME).read_text(encoding="utf-8"),
            (generation / CORE_FILENAME).read_text(encoding="utf-8"),
        )
    except OSError:
        return None


def _judge_persisted_pair(
    raw_sidecar: str, raw_core: str, *, fingerprint: CoreFingerprint | None
) -> CacheRead:
    """The conjunction above, over bytes that have already been read."""

    try:
        sidecar = json.loads(raw_sidecar)
        core = json.loads(raw_core)
    except Exception:
        return CacheRead(None, False, DEMOTE_UNREADABLE, None, {})
    if not isinstance(sidecar, dict) or not isinstance(core, dict):
        return CacheRead(None, False, DEMOTE_UNREADABLE, None, {})
    if _core_digest(core) != sidecar.get("core_sha256"):
        # The sidecar does not describe these bytes. Refuse the core outright
        # rather than serving it stale: an unbound core is not a projection this
        # module produced, so nothing here can say what it contains.
        return CacheRead(None, False, DEMOTE_CORE_DIGEST_MISMATCH, None, sidecar)
    key = fingerprint if fingerprint is not None else build_input_fingerprint()
    if key is None:
        return CacheRead(core, False, DEMOTE_FINGERPRINT_UNAVAILABLE, key, sidecar)
    different_question = _sidecar_answers_a_different_question(sidecar)
    if different_question:
        return CacheRead(core, False, different_question, key, sidecar)
    if sidecar.get("fingerprint") != key.digest:
        return CacheRead(core, False, DEMOTE_FINGERPRINT_MISMATCH, key, sidecar)
    return CacheRead(core, True, "", key, sidecar)


def _sidecar_answers_a_different_question(sidecar: dict) -> str:
    """The demote reason for "this pair is not comparable", or ``""``.

    Every clause here asks the same thing in a different dimension: is the
    persisted pair about the same CODE, the same CONTRACT, the same ROOT and the
    same HOME as the process judging it? None of them is about whether the store
    moved — that is the digest compare, and it is the only clause left outside.

    **Its own function because it has two callers and must never grow a second
    rule.** :func:`_judge_persisted_pair` asks it to demote; the cross-process
    convergence seed (:func:`_capture_boot_streak_seed`) asks it to decide whether
    a disagreement is EVIDENCE of non-convergence or an ordinary upgrade. A
    hand-copied second cascade there would drift from this one and the drift
    would surface as a WARNING receipt fired at an operator with a healthy
    install — the expensive direction.

    Clause ORDER is preserved from the conjunction it was lifted out of, and the
    ordering is load-bearing rather than incidental: each is a string compare
    against something already in hand, and the home clause sits BEFORE the digest
    compare (at the call site) because behind it the case it exists for is
    unreachable — a pair written under another home has a different digest by
    construction, so it would be swallowed as a generic ``fingerprint_mismatch``
    and the operator would read "the store moved" for something that is not about
    the store at all.
    """

    stamp = build_stamp_token()
    if stamp is None:
        return DEMOTE_BUILD_STAMP_UNKNOWN
    if sidecar.get("build_stamp") != stamp:
        return DEMOTE_BUILD_STAMP_MISMATCH
    if sidecar.get("contract_versions") != contract_versions():
        return DEMOTE_CONTRACT_MISMATCH
    try:
        from .. import paths as _paths

        current_root = str(_paths.store_root())
    except Exception:
        current_root = None
    recorded_root = sidecar.get("runtime_root")
    if current_root is not None and recorded_root and str(recorded_root) != current_root:
        return DEMOTE_RUNTIME_ROOT_MISMATCH
    # ABSENT MUST NOT DEMOTE. Every sidecar written before MC-2 carries no
    # ``fingerprint_home``, and treating absent as mismatch would demote every
    # install a SECOND time for no information — once for the closure change that
    # stage already forced, then again for a field it could not have written.
    recorded_home = sidecar.get("fingerprint_home")
    if recorded_home and str(recorded_home) != str(resolved_fingerprint_home()[0]):
        return DEMOTE_HOME_MISMATCH
    return ""


# --------------------------------------------------------------------------- #
# Labelling
# --------------------------------------------------------------------------- #
def label_core(core: dict, *, source: str, stale: bool) -> dict:
    """Stamp provenance onto the core's parity envelope, in place.

    ``parity`` is the frame's self-describing provenance block, and
    ``frame_source`` is already stamped there for exactly this reason — one
    location, additive, no contract bump. (The stamp used to live in
    ``read_model._resolved``; Stage 6 retired that module and moved the one-line
    stamp into ``runtime_commands._cmd_snapshot``, where the CLI frame is built.)

    ``core_source`` is emitted ONLY when a persisted core was available to
    decide between, which is why the committed fixtures do not move: a build in
    a root that has never held a persisted core answers no such question, and
    stamping ``rebuilt`` there would be answering a question nobody asked, on
    every golden. Same rule as the ``delta_patches`` hydrate marker, which is
    absent when the lane is off precisely so the flag-off golden stays
    byte-identical.

    A stale core additionally sets ``parity.freshness.state = "stale"``. That is
    the field the launcher's ``MissionSnapshotEnvelope`` already parses and maps
    to ``MissionSnapshotHealth.stale``, so a stale-labeled frame can never read
    ``live`` — it is non-authoritative by the consumer's existing predicate, not
    by a new one.
    """

    parity = core.get("parity")
    if not isinstance(parity, dict):
        parity = {}
        core["parity"] = parity
    parity["core_source"] = str(source)
    if stale:
        parity["core_stale"] = True
        freshness = parity.get("freshness")
        if not isinstance(freshness, dict):
            freshness = {}
            parity["freshness"] = freshness
        freshness["state"] = "stale"
    else:
        parity.pop("core_stale", None)
        freshness = parity.get("freshness")
        if isinstance(freshness, dict) and source == CORE_SOURCE_CACHE:
            # The fingerprint matched, so this projection is confirmed CURRENT
            # as of now — that, and not the original build's clock, is when its
            # freshness window starts. The build's own time stays on the core's
            # top-level ``generated_at``; nothing is overwritten, one anchor is
            # refreshed. Without this a cache hit would serve a core whose
            # 30-second freshness window expired before it was loaded.
            from hermes_time import now as _now

            from ..serde import to_jsonable

            freshness["generated_at"] = to_jsonable(_now())
    return core
