"""``build_input_fingerprint`` — the stat fingerprint over every input class the
core is built from — and the stamp tokens it is judged against.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable

from agent_runtime.core_cache.vocabulary import (
    MAX_FINGERPRINT_ENTRIES,
    MAX_SKILL_ENTRIES_PER_ROOT,
    REFUSAL_SCOPE_SKILL_ROOT,
    REFUSAL_SCOPE_STORE_ROOT,
    _EXCLUDED_NESTED_STORE_NAMES,
    _EXCLUDED_STORE_ENTRIES,
)
from agent_runtime.core_cache.models import CoreFingerprint, FingerprintEntry
from agent_runtime.core_cache.walk import (
    _config_input_entry,
    _db_entries,
    _receipt_fingerprint_refused,
    _stat_entry,
    _walk_tree,
)
from agent_runtime.core_cache.home import _pinned_to_fingerprint_home

__layer__ = "stores"

__all__ = [
    "_fingerprint_over",
    "build_input_fingerprint",
    "build_stamp_token",
    "contract_versions",
]


def build_input_fingerprint() -> CoreFingerprint | None:
    """The stat set over EVERY input the read-model build reads.

    ``None`` means "I could not fingerprint the inputs" and every caller must
    read it as **never cache** — not as "nothing changed". A missing answer is a
    loud refusal here, because the alternative is serving unlabeled stale as
    authoritative.

    The seven input classes, each resolved through the authority the BUILD
    reads through (§6.1's first mitigation — one authority, no second list).
    Four of them resolve HOME-RELATIVE and are therefore taken under
    :func:`_pinned_to_fingerprint_home`, so the answer is a function of the
    store and of the home this process resolved once, never of the
    ``HERMES_HOME`` the build itself exports mid-walk. Which classes are pinned
    and which are not is part of the specification, so it is stated per class
    rather than left to be re-derived:

    1. the agent-runtime store root subtree — ``paths.store_root()``, walked
       recursively so an ADDED file flips the key (offices, boards, personas,
       assignments, the event log and its rotation manifest, prompt
       observability, realm-sync baselines: everything the projection reads
       from the store, without a name list to fall behind). That "without a name
       list" is the class's design and it now has TWO stated exceptions, which is
       why the sentence no longer stands alone: ``deleted_archive/`` is excluded
       because the PROJECTION has no reader for it (the full argument — including
       the ``harness_doctor`` reader that does exist and why it does not re-admit
       the tree — is written at ``_EXCLUDED_STORE_ENTRIES``), and the orphaned-
       surface graveyard ``office_archive/`` is excluded because the runtime
       writes it, without bound, and the projection is deliberately built not to
       see it. Both arguments live at that constant. A THIRD exception is nested
       rather than top-level and carries its own argument at its own constant:
       ``realm_sync/**/.git`` — a synced worktree's git bookkeeping, which
       ``build_snapshot`` is forbidden to read (Decision 7) and reads through
       ``realm_sync_state/<realm>.json`` instead, while the four
       ``realm_sync/<realm>/*_baseline.json`` sidecars beside it STAY in the
       closure (see :data:`_EXCLUDED_NESTED_STORE_NAMES`). An exception with a
       reason at the constant is not the failure mode the sentence warns about;
       an unargued name list is. NOT pinned:
       ``resolve_runtime`` reads ``HERMES_AGENT_RUNTIME_ROOT`` and then the ROOT
       config, neither of which follows the profile home — measured unchanged
       across a persona flip on both the same thread and another one;
    2. the ``running_work`` durable stores — ``running_work_store_paths()``, the
       ONE authority for them (they hang off the HERMES home, not the store
       root, and both mutate with NO event). PINNED;
    3. the chat SessionDB — ``chat_session_db_path()``, the database the CHAT
       LANE writes, plus its WAL siblings. PINNED;
    4. the profile inputs ``agents_readiness`` reads — the profiles root and,
       per profile, ``profile.yaml`` + ``config.yaml``, plus the sticky
       ``active_profile`` pointer that decides which one a bare invocation
       resolves. NOT pinned: ``_get_profiles_root`` anchors to
       ``get_default_hermes_root()``, which maps ``<root>/profiles/<name>`` back
       to ``<root>``, so a profile flip resolves the SAME directory — measured.
       The two YAML files are CONTENT-KEYED
       (:func:`_config_input_is_content_keyed`); the profiles root and the
       ``active_profile`` pointer are not;
    5. the config inputs — ``get_config_path()``, taken PINNED (it is literally
       ``get_hermes_home() / "config.yaml"``, so a persona scope swaps the file
       being stat'd), and the ROOT ``harness_root_config_path()`` left ambient
       because it anchors to the hermes root like class 4. Two authorities in
       production because the CLI profile redirect makes them genuinely
       different files. Both CONTENT-KEYED, with class 4's two: these four are
       the whole of that mask's class;
    6. the skill registries — ``get_all_skills_dirs()`` (local profile skills,
       the shared canonical root, configured external roots) walked per root,
       plus the in-repo harness-skill source root the hash comparison reads.
       PINNED, and this is the class the measured 1,237-entry divergence came
       from: index 0 is the AMBIENT home's ``skills/``;
    7. the event-rotation lane — the manifest and the resolved LIVE slice.
       Under the store root today, so class 1 covers them; stat'd explicitly
       anyway because the resolution is free to move the live slice elsewhere
       and a frozen ``events.jsonl`` entry after a rotation is exactly the
       silent-staleness shape this whole module is against. NOT pinned: both
       resolve off the store root.
    """

    entries: list[FingerprintEntry] = []

    # 1 — the agent-runtime store root subtree.
    try:
        from .. import paths as _paths

        root = _paths.store_root()
    except Exception:
        return None
    if not _walk_tree(
        root,
        entries,
        limit=MAX_FINGERPRINT_ENTRIES,
        exclude_top=_EXCLUDED_STORE_ENTRIES,
        exclude_nested=_EXCLUDED_NESTED_STORE_NAMES,
    ):
        _receipt_fingerprint_refused(
            scope=REFUSAL_SCOPE_STORE_ROOT,
            root=root,
            bound=MAX_FINGERPRINT_ENTRIES,
        )
        return None

    # 2 — the running_work durable stores.
    try:
        from ..running_work import running_work_store_paths

        # PINNED. ``running_work._head_home`` already asks the head authority,
        # and its docstring names this very incident class ("ambient
        # get_hermes_home() is not an option either: it is flipped
        # process-globally for the duration of a persona turn"). That is true and
        # still not enough HERE: the authority it consults is a ContextVar, so on
        # a thread that is not the one running the persona scope the recording is
        # invisible and the head degenerates to the flipped ambient home.
        # Measured with a scope held on another thread: the stores resolved to
        # the OTHER profile's ``processes.json`` and ``state.db``.
        with _pinned_to_fingerprint_home():
            store_paths = running_work_store_paths()
    except Exception:
        return None
    if not store_paths:
        # The authority could not resolve a home. "I cannot fingerprint these"
        # is not "there is nothing to watch" — refuse.
        return None
    for path in store_paths:
        _db_entries(path, entries)

    # 3 — the chat SessionDB.
    try:
        from ..chat_session_scope import chat_session_db_path

        # PINNED, for the same cross-thread reason as class 2: the scope ladder
        # asks ``hermes_head_home_is_authoritative()`` first — a ContextVar read
        # — and when no rung answers it bottoms out in the ambient home. Measured
        # with a scope held on another thread: the SessionDB resolved to the
        # OTHER profile's ``state.db``, which is a whole different chat history
        # inside the key.
        with _pinned_to_fingerprint_home():
            chat_db = chat_session_db_path()
        _db_entries(chat_db, entries)
    except Exception:
        return None

    # 4 — profile inputs + the sticky active-profile pointer.
    try:
        from .._upstream_doors import default_hermes_home, profiles_root as _profiles_root

        profiles_root = _profiles_root()
        entries.append(_stat_entry(profiles_root))
        entries.append(_stat_entry(default_hermes_home() / "active_profile"))
        try:
            profile_dirs = sorted(os.scandir(profiles_root), key=lambda item: item.name)
        except OSError:
            profile_dirs = []
        for entry in profile_dirs:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            entries.append(_stat_entry(entry.path))
            # CONTENT-KEYED, not mtime-keyed — see _config_input_is_content_keyed.
            # These two are re-serialised in place by writers outside this build,
            # landing identical bytes under a fresh mtime; keying them on the
            # timestamp made the persisted core unreachable on every boot.
            entries.append(_config_input_entry(Path(entry.path) / "profile.yaml"))
            entries.append(_config_input_entry(Path(entry.path) / "config.yaml"))
    except Exception:
        return None

    # 5 — the two config authorities.
    try:
        from hermes_constants import get_config_path

        from ..config import harness_root_config_path

        # PINNED: ``get_config_path()`` is ``get_hermes_home() / "config.yaml"``,
        # so a persona scope swaps the file being stat'd.
        #
        # NAMED RESIDUAL, measured rather than assumed. In the standard profile
        # layout this stat is REDUNDANT with class 4, which already enumerates
        # every ``<profiles>/<name>/config.yaml``, so unpinning it alone does not
        # move the digest there and no witness in this repo can kill it on its
        # own. It is pinned anyway, because a closure's specification must not
        # rest on one class accidentally covering another. The digest-visible
        # half of this class's exposure is SECOND-ORDER and lands in class 6:
        # ``agent.skill_utils.get_external_skills_dirs()`` reads this very file
        # to decide which external skill roots exist.
        # CONTENT-KEYED, like class 4's two — same writers, same file class.
        with _pinned_to_fingerprint_home():
            entries.append(_config_input_entry(get_config_path()))
        # NOT pinned: anchored to the hermes ROOT, like class 4.
        entries.append(_config_input_entry(harness_root_config_path()))
    except Exception:
        return None

    # 6 — the skill registries.
    try:
        from agent.skill_utils import get_all_skills_dirs

        from ..skill_install import harness_skill_source_root

        # PINNED, and this is the class the measured 1,237-entry divergence came
        # from. ``get_all_skills_dirs()`` puts ``get_skills_dir()`` — the AMBIENT
        # home's ``skills/`` — at index 0, so a walk taken while a persona scope
        # is exported enumerates ANOTHER PROFILE'S ENTIRE SKILLS TREE. The
        # external roots behind it are read out of the ambient ``config.yaml``
        # (class 5's file), so they flip with it.
        #
        # The pin is what keeps ``agent/skill_utils.py`` — upstream-owned — out
        # of this change: the resolver stays byte-identical and answers for the
        # home this process resolved, instead of core_cache growing a second copy
        # of its "local, then shared, then external, deduped" rule.
        with _pinned_to_fingerprint_home():
            roots = [*get_all_skills_dirs(), harness_skill_source_root()]
    except Exception:
        return None
    seen_roots: set[str] = set()
    for skill_root in roots:
        key = str(skill_root)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        if not _walk_tree(Path(skill_root), entries, limit=len(entries) + MAX_SKILL_ENTRIES_PER_ROOT):
            _receipt_fingerprint_refused(
                scope=REFUSAL_SCOPE_SKILL_ROOT,
                root=key,
                bound=MAX_SKILL_ENTRIES_PER_ROOT,
            )
            return None

    # 7 — the event-rotation lane.
    try:
        from .. import event_rotation as _event_rotation

        entries.append(_stat_entry(_event_rotation.manifest_path()))
        entries.append(_stat_entry(_event_rotation.live_path()))
    except Exception:
        return None

    return _fingerprint_over(entries)


def _fingerprint_over(entries: Iterable[FingerprintEntry]) -> CoreFingerprint:
    """Order a stat set and digest it — the ONE definition of the key's shape.

    Its own function since IC-2, which needs to re-key a stat set that was
    ASSEMBLED rather than walked (:func:`_restat_on_post_build_reality`). Two
    sites computing "sorted, deduped, sha256 of path|mtime|size" would be two
    rules for one question, and the second one to drift would produce a digest
    that compares unequal to itself.
    """

    ordered = tuple(sorted(set(entries)))
    digest = hashlib.sha256(
        "\n".join(f"{item.path}|{item.mtime_ns}|{item.size}" for item in ordered).encode(
            "utf-8", "surrogatepass"
        )
    ).hexdigest()
    return CoreFingerprint(ordered, digest)


def contract_versions() -> dict[str, int]:
    """The wire versions a persisted core was produced under.

    A core written by a build whose contract has since moved is a core a
    consumer would decode against the wrong shape. Compared as a whole dict, so
    ADDING a version to this set is itself a demote signal for every core
    written before it — which is the safe direction.
    """

    from ..parity import PARITY_ENVELOPE_VERSION
    from ..snapshot import SNAPSHOT_CONTRACT_VERSION
    from ..stream import STREAM_SCHEMA_VERSION

    return {
        "snapshot_contract": int(SNAPSHOT_CONTRACT_VERSION),
        "parity_envelope": int(PARITY_ENVELOPE_VERSION),
        "stream_schema": int(STREAM_SCHEMA_VERSION),
    }


def build_stamp_token() -> str | None:
    """WHICH CODE built the persisted core, or ``None`` when unmeasurable.

    ``None`` refuses the cache. An install whose build cannot be measured — no
    repo, no baked sha, a hung ``git`` — cannot prove the persisted core was
    produced by the code now running, and property 5 says an upgrade must never
    be able to serve the old install's core. Refusing is loud (the demote
    receipt names ``build_stamp_unknown``) and it is the safe direction.

    ``dirty`` rides the token, so a clean → dirty transition demotes. The
    residual is stated rather than hidden: two different EDITS that both leave
    the checkout dirty produce the same token, so on a dirty tree the stamp
    cannot distinguish them. That window is exactly what the shadow-validation
    comparison covers in the field, and it does not exist on any install the
    operator ships from.
    """

    try:
        from ..build_stamp import build_stamp

        stamp = build_stamp()
    except Exception:
        return None
    if stamp.commit is None:
        return None
    return f"{stamp.source}:{stamp.commit}:{'dirty' if stamp.dirty else 'clean' if stamp.dirty is not None else 'unknown'}"
