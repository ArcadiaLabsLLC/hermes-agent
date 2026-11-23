"""The post-build restat: the inputs a build perturbs itself, and re-keying the
fingerprint on post-build reality before it is written back.
"""

from __future__ import annotations

from pathlib import Path

from agent_runtime.core_cache.vocabulary import _DB_SIBLINGS, logger
from agent_runtime.core_cache.models import (
    CoreFingerprint,
    _RestatOutcome,
    _SelfPerturbedInputs,
)
from agent_runtime.core_cache.home import _pinned_to_fingerprint_home
from agent_runtime.core_cache.fingerprint import (
    _fingerprint_over,
    build_input_fingerprint,
)

__layer__ = "stores"

__all__ = [
    "SELF_PERTURBED_LIVE_EVENTS",
    "SELF_PERTURBED_SESSION_DB",
    "_RESTAT_CLEAN",
    "_RESTAT_REFRESHED",
    "_RESTAT_SKIPPED",
    "_RESTAT_UNAVAILABLE",
    "_restat_on_post_build_reality",
    "_self_perturbed_inputs",
    "count_foreign_moves",
    "restat_self_perturbed",
]


# --------------------------------------------------------------------------- #
# IC-2 — keying the write-back on POST-BUILD reality
# --------------------------------------------------------------------------- #
#: THE DESIGN NOTE IC-2 OWES THE MODULE HEADER, written where the code is.
#:
#: The header's standing rule is that a persisted key must be stat'd BEFORE the
#: build, because a key stat'd after would absorb a write that landed WHILE the
#: build ran — the core would not contain that write, the key would say the
#: inputs are unchanged, and the next process would serve a core missing a write
#: as authoritative. That rule is not repealed here. What IC-2 says is narrower
#: and, on the evidence, unavoidable:
#:
#: **The build is not a pure reader, so "the inputs as they were before the
#: build" is not a state any later process can ever observe.** Five writes were
#: proven (2026-08-22 reader audit); the three persona-instance ones
#: (``ensure_for_personas`` minting the hidden copies, its drift rewrites and
#: stale-binding resets) left the build with the mint
#: (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT), leaving the build's OWN SessionDB close draining
#: token deltas and running a TRUNCATE WAL checkpoint
#: (``snapshot.py::_projection_chat_session_db`` -> ``hermes_state.SessionDB.close``),
#: and the stream scope fingerprint appending ``state.reconciled`` to the live
#: events slice when a DB is opened during a build (``stream.py``). Each moves an
#: input the pre-build key already recorded. So the persisted key disagrees with
#: the next consult's stat BY CONSTRUCTION, on every build, forever — which is
#: exactly the ``never_converged`` receipt the operator's log has been emitting:
#: the lane pays a write per build and no later process can ever be served.
#:
#: **THE ANSWER, and why it does not widen what a consult accepts.** At
#: write-back time — after the build, after the SessionDB close — the inputs are
#: re-stat'd and the persisted key is keyed on THAT, for the entries the build
#: itself moved and for no others. Three properties make it sound:
#:
#: 1. **It is on the WRITE path only.** The consult path is untouched: validity is
#:    still "stat the closure now, compare to the persisted key", the fingerprint
#:    is still the only validity authority, and no consult accepts anything it
#:    would have refused yesterday. This changes which key a build PUBLISHES, not
#:    what a reader will believe.
#: 2. **Only the build's own perturbations may adopt a fresh triple.** Everything
#:    else keeps its PRE-build triple even when the re-stat shows it moved — see
#:    :func:`_restat_on_post_build_reality`. An input a CONCURRENT writer moved
#:    while the build ran therefore still carries the old triple into the sidecar,
#:    the next consult still sees a mismatch, and it still demotes. That is the
#:    conservative direction the header demands, kept intact for every input
#:    outside the audited set.
#: 3. **The equivalence golden stays the authority.**
#:    ``test_the_cache_served_core_equals_the_rebuilt_core_field_for_field`` reds
#:    if a cache-served core ever differs from a rebuilt one, and the
#:    shadow-validation window reds it in the field. Neither is weakened here;
#:    both are what this change is checked against rather than argued past.
#:
#: **THE RESIDUAL, stated rather than discovered later.** Inside the audited set
#: the re-stat cannot tell the build's own write from a concurrent one — an
#: operator event appended to the live slice while the build ran adopts a fresh
#: triple exactly as the build's own ``state.reconciled`` append would. So this
#: accepts a bounded staleness window over TWO named input classes, in exchange
#: for a lane that can converge at all. The bound is what makes it acceptable:
#: the set is closed and enumerated below rather than open-ended, every member is
#: an input the build provably moves on every pass, the shadow-validation window
#: still compares a served core against a rebuilt one, and the alternative is not
#: a safer cache — it is no cache, plus a megabyte write per build.
SELF_PERTURBED_SESSION_DB = "session_db"


SELF_PERTURBED_LIVE_EVENTS = "live_events_slice"


def _self_perturbed_inputs() -> _SelfPerturbedInputs | None:
    """The audited self-perturbation set, or ``None`` when it cannot be resolved.

    ``None`` means "refuse to refresh anything" — the pre-build key is persisted
    unchanged, i.e. exactly today's behaviour. A set this function could not
    resolve must never degrade into an EMPTY one silently: an empty set would
    read as "the build perturbs nothing", which is the fail-quiet default the
    whole module is against.

    THE THREE CLASSES AND THEIR CITATIONS:

    * :data:`SELF_PERTURBED_SESSION_DB` — the databases the build OPENS and
      CLOSES. ``snapshot._projection_chat_session_db`` closes the chat SessionDB
      inside the build, and ``hermes_state.SessionDB.close`` drains queued token
      deltas and then attempts a TRUNCATE WAL checkpoint, which moves
      ``state.db``'s own triple with zero logical change (the 2026-08-21 17:18
      and 2026-08-22 13:42 ``every_pass`` firings). Resolved through
      ``chat_session_scope.chat_session_db_path`` and
      ``running_work.running_work_store_paths`` — the same two authorities
      classes 2 and 3 of the closure ask, under the same pin — and narrowed to
      the SQLite databases among them by ``running_work``'s own filename
      constant. ``processes.json`` is deliberately NOT here: a background process
      starting or exiting rewrites it, and that is a FOREIGN write the next
      consult must still demote on.
    * (retired) the persona-instances tree: ``snapshot`` called
      ``PersonaInstanceStore.ensure_for_personas`` on every build, which minted
      each agent's hidden copy and rewrote rows. Nothing in a build writes an
      instance row since RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT, so a
      row that moves during a build is a FOREIGN write and demotes like one.
    * :data:`SELF_PERTURBED_LIVE_EVENTS` — a DB opened during the build flips the
      stream's scope fingerprint and appends a synthetic ``state.reconciled``
      event (``stream.py``), which grows the live slice the build already stat'd.
      The slice is resolved through ``event_rotation.live_path()``, the same
      authority class 7 of the closure uses, so a rotation moves both together.
      (The stream half of that loop is out of IC-2's scope by ruling; this makes
      the write-back stop RE-TRIGGERING on it.)
    """

    files: set[str] = set()
    trees: list[str] = []
    try:
        from .. import event_rotation as _event_rotation
        from ..chat_session_scope import chat_session_db_path
        from ..running_work.ownership import running_work_store_paths
        from ..running_work.vocabulary import _STATE_DB_FILENAME

        # PINNED exactly as closure classes 2 and 3 are — an unpinned resolution
        # here would name ANOTHER profile's database and the set would cover a
        # file the walk never stat'd while missing the one it did.
        with _pinned_to_fingerprint_home():
            db_paths = [chat_session_db_path()]
            db_paths.extend(
                path
                for path in running_work_store_paths()
                if Path(path).name == _STATE_DB_FILENAME
            )
        for db_path in db_paths:
            for suffix in _DB_SIBLINGS:
                files.add(f"{db_path}{suffix}")
        # NOT pinned, like closure class 7: it resolves off the store root rather
        # than following the profile home.
        files.add(str(_event_rotation.live_path()))
    except Exception:
        logger.debug("the self-perturbation set could not be resolved", exc_info=True)
        return None
    return _SelfPerturbedInputs(frozenset(files), tuple(trees))


#: What :func:`_restat_on_post_build_reality` did, as a countable field on the
#: write-back's own ``ok=true`` line (``restat=``). Not a fourth ``reason=``
#: vocabulary — see the channel table's own warning about those — just the four
#: states the re-stat can end in, so a census can tell "the build's writes were
#: absorbed" from "we could not look" without reading prose.
_RESTAT_REFRESHED = "refreshed"


_RESTAT_CLEAN = "clean"


_RESTAT_SKIPPED = "skipped"


_RESTAT_UNAVAILABLE = "unavailable"


def _restat_on_post_build_reality(key: CoreFingerprint) -> _RestatOutcome:
    """Re-key the pre-build stat set on what the store looks like NOW.

    Read the design note at :data:`SELF_PERTURBED_SESSION_DB` first — this
    function is that argument in code.

    THE RULE, in one sentence: an entry that moved AND is in the audited
    self-perturbation set adopts its fresh triple; every other entry keeps the
    triple the pre-build walk recorded, whatever the re-stat says about it.

    That asymmetry is the whole safety property. Between the build finishing and
    this re-stat, a CONCURRENT writer may have moved an input too — and a key
    that adopted its fresh triple would describe a store the persisted CORE does
    not reflect, which is the "missed input serves unlabeled stale" hazard the
    module header calls the worst one. Keeping the pre-build triple for those
    entries means the next consult stats the store, sees a disagreement, and
    demotes. Same outcome as before IC-2, for exactly the inputs IC-2 has no
    audit for.

    An entry that APPEARED is adopted only when it lands under a self-perturbed
    TREE — a persona-instance row the build just minted, which is the ordinary
    cold-store shape and has no pre-build triple to compare. An entry that
    VANISHED is never adopted, in or out of the set: no build DELETES an input
    (retirement is an operator verb), so a disappearance is somebody else's write
    however self-perturbed the path looks, and it keeps its pre-build triple so
    the next consult demotes on it. That asymmetry is deliberate and is the
    narrower reading of the audit — the audit proved five WRITES, not one
    removal.

    ``refuse`` arms, each keeping the pre-build key unchanged:

    * the re-stat itself refused (``build_input_fingerprint`` returned ``None`` —
      a bound blown, an unresolvable authority). "I could not look" is never
      "nothing moved";
    * the self-perturbation set could not be resolved;
    * either stat set records the SAME path twice under different triples. The
      closure stats a few paths through two classes (the live slice is in the
      store walk AND in class 7), and a duplicate means a path-keyed diff would
      have to pick one — so it declines rather than picking. Rare by
      construction and safe by refusal.
    """

    return _re_key(key, build_input_fingerprint())


def _re_key(key: CoreFingerprint, fresh: CoreFingerprint | None, *, scope: frozenset[str] | None = None) -> _RestatOutcome:
    """The re-key rule of :func:`_restat_on_post_build_reality` over a ``fresh`` stat set.

    ``scope`` (``None``: every path either set names) limits the paths compared:
    :func:`restat_self_perturbed` hands the audited set's own classes only, and
    every path outside them keeps its pre-build triple, as it would anyway.
    """

    if fresh is None:
        return _RestatOutcome(key, 0, 0, _RESTAT_UNAVAILABLE)
    perturbed = _self_perturbed_inputs()
    if perturbed is None:
        return _RestatOutcome(key, 0, 0, _RESTAT_UNAVAILABLE)
    before = {entry.path: entry for entry in key.entries}
    after = {entry.path: entry for entry in fresh.entries}
    if len(before) != len(key.entries) or len(after) != len(fresh.entries):
        return _RestatOutcome(key, 0, 0, _RESTAT_SKIPPED)

    adopted = dict(before)
    refreshed = 0
    foreign = 0
    for path in (before.keys() | after.keys()) if scope is None else scope:
        was = before.get(path)
        now_entry = after.get(path)
        if was == now_entry:
            continue
        if now_entry is None:
            # VANISHED. Never adopted — see the docstring: a build writes, it
            # does not delete, so this is a foreign change whatever the path is.
            foreign += 1
            continue
        if was is None and not perturbed.under_tree(path):
            # APPEARED outside a self-perturbed tree. The exact-path members of
            # the set (the databases, the live slice) are always ALREADY in a
            # real pre-build key — ``_stat_entry`` records an absent input as its
            # own triple rather than omitting it — so an appearance there is not
            # a state a build produces, and adopting it would let this function
            # invent entries the caller's closure never had.
            foreign += 1
            continue
        if not perturbed.covers(path):
            foreign += 1
            continue
        refreshed += 1
        adopted[path] = now_entry
    if not refreshed:
        return _RestatOutcome(key, 0, foreign, _RESTAT_CLEAN)
    # A kept entry keeps the bytes digest its pre-build walk took; an adopted one takes the fresh walk's
    # (RT-CORE-CACHE-SAME-TICK-REWRITE), so a re-key digests what each triple was measured with.
    kept, measured = dict(key.racy), dict(fresh.racy)
    racy = {path: sha for path, entry in adopted.items()
            if (sha := (measured.get(path) if entry != before.get(path) else kept.get(path)))}
    return _RestatOutcome(
        _fingerprint_over(adopted.values(), racy), refreshed, foreign, _RESTAT_REFRESHED
    )


def _self_perturbed_classes_fingerprint() -> CoreFingerprint | None:
    """A stat set over ONLY the input classes the audited set lives in (2, 3, 7).

    Every audited path is a running_work database, the chat SessionDB or the live
    event slice (:func:`_self_perturbed_inputs`), so these three collectors —
    the same ones :func:`build_input_fingerprint` runs, in its order — name every
    path the re-key could adopt, at a few stats instead of the whole closure.
    """

    import time

    from agent_runtime.core_cache.fingerprint import (
        _collect_event_rotation,
        _collect_running_work,
        _collect_session_db,
        racy_contents,
    )

    started_ns = time.time_ns()
    entries: list = []
    for collect in (_collect_running_work, _collect_session_db, _collect_event_rotation):
        if not collect(entries):
            return None
    return _fingerprint_over(entries, racy_contents(entries, started_ns))


def restat_self_perturbed(key: CoreFingerprint) -> _RestatOutcome:
    """:func:`_restat_on_post_build_reality`'s key, from the audited classes alone.

    Row RT-FU-EVERY-AGENT-LIST-BUILD-WAITS-FOR-ITS-CACHE-COPY-TO-REACH-THE-DISK: the
    re-key ran a WHOLE second closure walk on the build thread after every led build,
    ahead of the waiters, to adopt the fresh triples of a handful of audited files.
    The key it produces is the same (only an audited path is ever adopted); its
    ``foreign`` is left 0 here and counted by :func:`count_foreign_moves` on the
    writer thread, off the response path.
    """

    fresh = _self_perturbed_classes_fingerprint()
    if fresh is None:
        return _RestatOutcome(key, 0, 0, _RESTAT_UNAVAILABLE)
    perturbed = _self_perturbed_inputs()
    if perturbed is None:
        return _RestatOutcome(key, 0, 0, _RESTAT_UNAVAILABLE)
    scope = frozenset(entry.path for entry in fresh.entries) | frozenset(
        entry.path for entry in key.entries if perturbed.covers(entry.path)
    )
    outcome = _re_key(key, fresh, scope=scope)
    return outcome._replace(foreign=0)


def count_foreign_moves(key: CoreFingerprint) -> int:
    """How many inputs outside the audited set moved since ``key`` (the pre-build
    key) was taken: the write receipt's ``foreign_moved=``, counted by a whole walk
    on the writer thread rather than ahead of the build's waiters."""

    return _re_key(key, build_input_fingerprint()).foreign
