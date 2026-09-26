"""Boot-time helpers the loop and ``_cmd_serve`` call once: logging repoint, the boot
fault seam, the runtime-state fingerprint, the three prewarms, the skill install and the
import-tax annotation.
"""

from __future__ import annotations

import os
from typing import Any

from hermes_cli.harness_parts.serve.constants import (
    _FINGERPRINT_BOARD_CARD_CAP,
    _FINGERPRINT_ROOT_FILES,
    _FINGERPRINT_STORE_DIRS,
)

__layer__ = "lanes"

__all__ = [
    "BOOT_FAULT_ENV_VAR",
    "_FINGERPRINT_TURN_FILE_CAP",
    "_annotate_import_tax",
    "_maybe_inject_boot_fault",
    "_prewarm_persona_chat_actors",
    "_prewarm_provider_runtime",
    "_prewarm_read_model_snapshot",
    "_repoint_logging_root_stderr",
    "_runtime_state_fingerprint",
    "_stat_board_tree",
    "_stat_turn_store_tree",
    "install_harness_skills_at_boot",
]


# ── RL-19: the service runtime keeps its own stderr ─────────────────────────
#
# RL-17 gave the launcher's intermediary three ``DEVNULL`` handles, which was
# right — a pipe nobody reads is a runtime that blocks on its first full buffer
# — and it cost this: everything the runtime writes to stderr goes nowhere. On
# 2026-09-06 at 09:09:18Z a local hub stream went silent for thirty seconds and
# the watchdog tore it down, and the runtime's side of that half hour did not
# exist to be read.
#
# So under ``--service`` the runtime keeps its stderr in a file beside its own
# registry row: ``serve_instances/<pid>.stderr.log``, opened by the registry
# (one writer for that directory), floored by the same boot prune as the RL-16
# sidecars. Three sinks are wired to it and they are NOT the same sink:
#
# 1. the loop's stderr proxy MIRRORS every completed line into it, so the
#    ``_service_log`` transport events and every handler's stderr survive
#    having no audience on the frame lane;
# 2. ``logging``'s root handler is repointed if it was writing to stderr —
#    a library's ``logging.warning`` is exactly the material this file is for;
# 3. it becomes the loop's ``original_stderr``, so it is what is RESTORED when
#    ``serve_loop`` unwinds — anything written to stderr after that point, a
#    late ``atexit`` hook or a warning during teardown, still lands in the file.
#
# And one thing the redirect could NOT buy, discovered while proving it: an
# uncaught exception out of a serve child prints no traceback anywhere at all.
# The harness dispatch turns it into an error envelope the ``--ndjson`` serve
# never emits, so the interpreter never displays it and a restored
# ``sys.stderr`` is a channel nobody writes to. ``serve_loop``'s uncaught arm
# therefore writes the traceback into this file itself — see the
# ``except Exception`` at the bottom of that function.
#
# What is NOT here: an fd-level ``dup2``. A subprocess's raw fd 2 is a
# different question with a different blast radius (every child a handler
# spawns would inherit it), and the ruling is about what this process writes.


def _repoint_logging_root_stderr(stream: Any, *, previous: tuple[Any, ...]) -> int:
    """Move root ``StreamHandler``s that were writing to stderr onto *stream*.

    Only the handlers whose stream IS one of *previous* — the objects that were
    stderr at some point in this boot. A handler someone deliberately pointed at
    a file, a socket or stdout is left exactly where it is: this redirects the
    stderr lane, it does not collect logging.

    Returns how many it moved, and never raises: a boot must not fail because
    ``logging`` was configured in a shape this did not expect.
    """

    moved = 0
    try:
        import logging as _logging

        for handler in list(_logging.getLogger().handlers):
            handler_stream = getattr(handler, "stream", None)
            if handler_stream is None or not any(
                handler_stream is candidate for candidate in previous
            ):
                continue
            setter = getattr(handler, "setStream", None)
            if callable(setter):
                setter(stream)
            else:  # pragma: no cover - every StreamHandler has setStream
                handler.stream = stream
            moved += 1
    except Exception:  # pragma: no cover - defensive
        return moved
    return moved


#: The e2e's only way to make a REAL serve child end uncaught, exit plainly, or
#: vanish without a word. Inert without the variable — read once, right after
#: the ready frame, and absent from every other code path.
BOOT_FAULT_ENV_VAR = "HERMES_SERVE_BOOT_FAULT"


def _maybe_inject_boot_fault() -> None:
    """Three endings a test cannot otherwise ask a real child for.

    ``raise`` → an uncaught ``RuntimeError`` (proves ``uncaught:<Type>``),
    ``exit`` → ``SystemExit`` (proves the ``atexit`` fallback ``unknown_exit``),
    ``hard`` → ``os._exit`` (proves the ABSENCE that stands in for
    ``TerminateProcess``). Anything else, including unset, does nothing at all.
    """

    mode = (os.environ.get(BOOT_FAULT_ENV_VAR) or "").strip().lower()
    if not mode:
        return None
    if mode == "exit":
        raise SystemExit(9)
    if mode == "hard":
        os._exit(9)
    raise RuntimeError(f"{BOOT_FAULT_ENV_VAR}={mode!r}: injected boot fault")


def _stat_board_tree(root: Any, _stat) -> None:
    """Bounded stat of the boards/ subtree: the root, each board's def + card
    files + conflict dir. Card files are stat'd individually so in-place edits
    (move/edit rewrite a file without touching the dir mtime) still flip the
    fingerprint. Capped per board to stay cheap on the hot poll path."""

    boards_root = root / "boards"
    _stat(boards_root)
    try:
        board_dirs = sorted(p for p in boards_root.iterdir() if p.is_dir())
    except OSError:
        return
    for board_dir in board_dirs:
        _stat(board_dir / "board.json")
        cards_dir = board_dir / "cards"
        _stat(cards_dir)
        _stat(board_dir / "conflicts")
        try:
            card_files = sorted(cards_dir.glob("*.json"))
        except OSError:
            continue
        for card_path in card_files[:_FINGERPRINT_BOARD_CARD_CAP]:
            _stat(card_path)


_FINGERPRINT_TURN_FILE_CAP = 200  # session cap is 50; defensive bound only


def _stat_turn_store_tree(root: Any, _stat) -> None:
    """Bounded stat of the per-session turn store (mission_chat_turns/<key>.json).

    The turn-store split (one file per chat session) made the legacy
    `mission_chat_turns.json` root-file stat a dead signal: after migration the
    monolith is renamed aside and every streamed-turn flush rewrites ONE
    session file in place — which does not reliably move the directory mtime.
    Stat each session file individually (the board-tree pattern) so a cached
    snapshot can never serve stale turn elements. The legacy root file stays in
    _FINGERPRINT_ROOT_FILES so the one-time migration rename also flips the
    fingerprint."""

    turns_root = root / "mission_chat_turns"
    _stat(turns_root)
    try:
        session_files = sorted(turns_root.glob("*.json"))
    except OSError:
        return
    for session_path in session_files[:_FINGERPRINT_TURN_FILE_CAP]:
        _stat(session_path)


def _runtime_state_fingerprint() -> tuple | None:
    """Cheap stat-based sequence check over the harness poll-payload inputs.

    Returns None when the runtime root cannot be resolved — callers must
    treat None as "never cache"."""
    try:
        from agent_runtime import paths as _paths

        root = _paths.store_root()
    except Exception:
        return None
    parts: list[tuple[str, int, int]] = []

    def _stat(path: Any) -> None:
        try:
            st = os.stat(path)
        except OSError:
            parts.append((str(path), -1, -1))
            return
        parts.append((str(path), st.st_mtime_ns, st.st_size))

    for name in _FINGERPRINT_ROOT_FILES:
        _stat(root / name)
    for name in _FINGERPRINT_STORE_DIRS:
        _stat(root / name)
    # Background-work stores hang off the HERMES home, not the store root, and
    # resolve through the same head authority their WRITERS use
    # (``get_hermes_background_work_home``): ``persona_profile_context`` flips
    # ambient HERMES_HOME process-globally while a persona turn runs in THIS
    # process, so an ambient read here would fingerprint whichever profile
    # happened to be mid-turn.
    #
    # An EMPTY tuple means the authority could not resolve a home — "I cannot
    # fingerprint these", not "there is nothing to watch". Both that case and a
    # raised exception get the same sentinel, because caching against a silently
    # missing signal is exactly how a stale HUD gets served.
    try:
        from agent_runtime.running_work import running_work_store_paths

        store_paths = running_work_store_paths()
        if not store_paths:
            parts.append(("running_work_stores", -1, -1))
        for path in store_paths:
            _stat(path)
    except Exception:
        parts.append(("running_work_stores", -1, -1))
    # Event-log rotation (C6a) moves appends off the static "events.jsonl" onto a
    # rotating live slice, so the _FINGERPRINT_ROOT_FILES entry above freezes once
    # the log rotates. Stat the manifest (flips on each rotation) AND the resolved
    # live slice (flips on every append) so a cached snapshot never serves stale
    # frames after rotation. Pre-rotation the live slice IS events.jsonl (a
    # harmless duplicate stat); the manifest is absent (a stable -1/-1 signal).
    try:
        from agent_runtime import event_rotation as _event_rotation

        _stat(_event_rotation.manifest_path())
        _stat(_event_rotation.live_path())
    except Exception:
        parts.append(("event_log_rotation", -1, -1))
    # Mission Board tree is nested two levels deep (boards/<id>/cards/<card>.json),
    # so a top-level dir stat alone misses card adds/moves/in-place edits and
    # pull-materialized cards. Every board mutation also advances events.jsonl
    # (already fingerprinted), but a bounded subtree walk here keeps cached
    # snapshots honest even for event-less file materialization (realm pull).
    _stat_board_tree(root, _stat)
    # Per-session turn store: streamed-turn flushes rewrite one session file in
    # place and emit NO EventLog event, so without these stats a cached snapshot
    # would serve stale turn elements.
    _stat_turn_store_tree(root, _stat)
    try:
        # Fingerprint the database the CHAT LANE actually writes, not the one
        # ambient HERMES_HOME resolution happens to hand this process. A bare
        # ``SessionDB()`` keyed the cache on ``HERMES_HOME/state.db`` while every
        # chat write goes to the resolved chat scope; whenever the two diverge a
        # cached snapshot could serve a frozen Chat History for the life of the
        # serve process (defect D1 in
        # ``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/chat-session-presence-authority.md``,
        # the serve twin of the stream-lane fix 639242901). Resolving the PATH
        # also stops the poll loop from opening — and potentially creating — a
        # database just to read its own filename.
        from agent_runtime.chat_session_scope import chat_session_db_path
        from agent_runtime.core_cache.walk import sqlite_fingerprint_triples

        # Keyed through the SHARED SQLite authority, not a raw stat of the three
        # siblings, since 2026-08-21. SQLite deletes the WAL on a clean
        # last-close and re-creates it EMPTY on the next open, so under the raw
        # stat this entry flipped between ``-1/-1`` and a fresh ``mtime_ns``
        # every time any process merely OPENED the chat database — keeping this
        # cache permanently cold for reasons that were never content. That is
        # the defect the 2026-08-09 analysis named; the mask that answers it has
        # existed in ``core_cache`` since MC-3b and had simply never been
        # propagated to the two poll lanes. A real commit still moves this
        # entry: uncheckpointed the WAL is non-empty and keyed in full,
        # checkpointed the frames are in ``state.db`` whose own triple is here.
        db_path = str(chat_session_db_path())
        for suffix, mtime_ns, size in sqlite_fingerprint_triples(db_path):
            parts.append((db_path + suffix, mtime_ns, size))
    except Exception:
        # Chat persistence unavailable → its absence is itself stable.
        parts.append(("session_db", -1, -1))
    return tuple(parts)


def _prewarm_read_model_snapshot() -> None:
    """Build ONE read-model core in the background right after ``ready``.

    A fresh serve child's first snapshot build costs ~7.5s against ~2.2s warm
    (measured 2026-08-09, B4/B11): ~5s of that is per-process cache fill —
    YAML parse cache, tool-visibility memos, skill resolution, the event tail.
    Serve is long-lived, so paying it on a daemon thread the moment the child
    is ready takes it off whichever request would otherwise have been first.

    Since EG-3.1 this build is also the process's cache CONSULTATION and, when it
    demotes, its write-back: ``build_snapshot`` stats every build input and either
    loads the persisted core (~2 s, ``core_source=cache``) or rebuilds and
    persists what it built under ``<store_root>/serve_read_model/``. So the
    prewarm is no longer read-only — it is the fastest place in the boot to
    discover which of the two this child is paying for. It still writes no STORE
    state (it never called ``write_snapshot``, the ``snapshot.json`` boot-cache
    writer — and Stage 6 deleted that writer outright, so the bypass this line
    used to describe is now the only behaviour there is), and the cache write is
    best-effort by contract. Concurrency is
    handled by the builder's own coalescing — a real request arriving mid-build
    joins it (hydrate) or waits and shares the next one; it never double-builds.
    Best effort by contract: a failure here surfaces on the first real request
    exactly as it would have without the prewarm.

    ``build_info={"caller": "prewarm"}`` is what makes this build appear in the
    log at all. It is the most expensive build of a cold boot and, until the
    builder learned to emit its own receipt, it was the only one with no line
    anywhere: every ``snapshot_build`` line in the boot window belonged to a
    caller that RODE it, which is how one build came to look like three
    (plan EG-2.1). Naming the caller here costs a dict.
    """

    try:
        from agent_runtime.snapshot.build import build_snapshot

        build_snapshot(build_info={"caller": "prewarm"})
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "serve snapshot prewarm did not complete", exc_info=True
        )


def _prewarm_provider_runtime() -> None:
    """Best-effort warmup of the per-process one-time costs a chat turn pays.

    Runs on a daemon thread right after the ready frame. Each step is
    independent and failure-isolated: a missing provider dependency surfaces on
    the first real turn with its normal typed error, exactly as it would without
    prewarm. TLS trust is upstream's one authority,
    ``agent.ssl_verify.install_truststore()`` (idempotent, never raises; logs a
    warning and returns ``False`` when truststore is unavailable) — there is no
    CA-bundle preflight left to run.
    """
    try:
        from hermes_cli.harness_parts._upstream_doors import load_openai_cls

        load_openai_cls()
    except Exception:
        pass
    try:
        from agent.ssl_verify import install_truststore

        install_truststore()
    except Exception:
        pass
    try:
        from model_tools import get_tool_definitions

        # The exact cache key varies per persona toolset; this call warms the
        # shared parts (tool module imports, registry build, config parse).
        get_tool_definitions(quiet_mode=True)
    except Exception:
        pass


def _prewarm_persona_chat_actors() -> None:
    """Best-effort background construction of the resident chat actors.

    THIRD on the one prewarm thread, behind the read-model build and the
    provider warmup, and the ordering is load-bearing in both directions: the
    launcher's canvas is waiting on the build, and an agent construction that
    runs after ``_load_openai_cls``/``install_truststore`` does not pay the SDK
    import itself (which is the single largest item in a cold construct).

    Inert unless the root config turns hot sessions on — with no resident
    registry there is nowhere to put a pre-built actor, and that is the ONLY
    gate (a ``prewarm_on_boot`` knob was written and withdrawn: every
    ``PersonaChatConfig`` field rides the read-model wire, so a new key is a
    cross-stack golden change — see the note on that class). The pass QUEUES;
    the constructions run on
    ``persona_chat_actor_prewarm``'s own single daemon worker, which stands down
    for any real turn in flight, so a chat sent during the boot window is never
    behind a warm.
    """

    try:
        from agent_runtime.persona_chat_actor_prewarm import prewarm_chat_actors_on_boot

        prewarm_chat_actors_on_boot()
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "serve chat-actor prewarm did not complete", exc_info=True
        )


def install_harness_skills_at_boot() -> str:
    """Re-join the runtime's copy of every canonical skill to this repo's copy.

    THE GAP THIS CLOSES (operator ruling 2026-08-30, plan
    ``archive/skill-install-trigger-relocation.md``). A canonical shared skill
    has two copies and only one is ever executed: a chat turn loads
    ``<hermes root>/shared/skills/<id>/SKILL.md``, never the repo's
    ``docs/agent-runtime-harness/harness-skills/<id>/SKILL.md``, because
    ``agent.skill_utils`` refuses any candidate for a canonical id whose
    ``source_kind`` is not ``shared_core``. Until this ran, the join was made by
    exactly three triggers — an explicit CLI verb, a realm-sync pull, and a
    pre-push hook — and every one of them fires when the machine PUBLISHES.
    A machine that merely ``git pull``s and boots was repaired by nothing.

    So it runs at the moment a CONSUMER acquires the drift instead: boot. It is
    the strongest spot in the census because it is the only one with an
    unambiguous home — the pre-push hook's whole refuse-to-guess-``HERMES_HOME``
    contortion (``scripts/verify_harness_skill_install.py``, exit 2) exists
    because a hook inherits an arbitrary pushing shell, while this process was
    spawned with its home explicitly pinned and has already resolved it.

    EXACTLY what a realm-sync pull runs (``agent_runtime/realm_sync.py:509-511``),
    deliberately, rather than a second spelling of the same repair.

    FAILURE POSTURE: loud, never fatal. The push gate blocked, because a push is
    a one-shot event and an install that did not take had to stop it. A boot is
    not: the next boot retries for free, and a chat runtime that refuses to start
    because a skill package would not copy is a far worse outcome than one that
    starts carrying a stale package and says so. Every failed result is named on
    the caller's log lane.

    Returns the one-line summary; raising is not part of the contract.
    """

    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.skill_install import (
        HARNESS_SKILLS,
        install_harness_skills,
        install_harness_skills_for_personas,
    )

    results = [
        *install_harness_skills(skills=sorted(HARNESS_SKILLS)),
        *install_harness_skills_for_personas(
            ensure_persisted_personas(load_agent_runtime_config())
        ),
    ]
    changed = [item.skill for item in results if item.changed]
    failed = [item for item in results if not item.ok]
    summary = (
        f"harness serve: skill install — {len(results)} package(s), "
        f"{len(changed)} refreshed, {len(failed)} failed"
    )
    if changed:
        summary += f" | refreshed: {', '.join(sorted(set(changed)))}"
    return summary + "".join(
        f"\n  FAILED {item.skill}: {item.source} -> {item.destination}"
        f" (repo {item.source_hash}, installed {item.installed_hash})"
        for item in failed
    )


def _annotate_import_tax(timeline: Any) -> None:
    """Decompose ``interpreter_ms`` into named segments on the boot block (BW-0).

    ``interpreter_ms`` is one number covering process creation → this command's
    first instruction, and on the 2026-08-17 cold boot it was 20,421 ms against a
    warm baseline of ~2,000 ms — 18.4 s of unattributed cold-boot cost, next to
    1,437 ms of post-``booting`` work attributed phase by phase. The anchors that
    split it can only be read where they were taken (``hermes_cli._boot_clock``,
    written by ``main.py``), so the derivation happens here and rides the frame
    the launcher already parses.

    Never raises and never fabricates: a segment whose endpoints were not both
    observed is simply absent, exactly as ``interpreter_ms`` itself is absent on
    a platform that will not report a process creation time. A boot that reached
    this loop without going through ``main()`` (every ``serve_loop`` unit test)
    annotates whatever subset its anchors support, which is additive and inert.
    """

    try:
        from hermes_cli import _boot_clock

        timeline.annotate(
            _boot_clock.import_tax_segments(
                process_start=timeline.process_start_monotonic,
                dispatch_reached=timeline.started_monotonic,
            )
        )
    except Exception:  # pragma: no cover - observability must never fail a boot
        pass
