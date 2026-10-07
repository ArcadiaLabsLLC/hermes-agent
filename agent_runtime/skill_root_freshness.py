"""h-warm-phases: a warm chat turn reads its skill roots from the process registry and re-walks them after ``request_sent`` (2026-10-06).

**What it cost.** Every chat turn walked every skill root it resolved against
(``skill_resolution._skill_root_signature``: one ``os.scandir`` per directory
under the root) before its request could leave -- once for the preload policy
in ``context_built`` and once for the profile-scoped roots of the observability
row in ``observability_built``. The walk scales with the skill tree, not the
turn: on the operator's trees (the neko profile root, 431 directories / 898
markdown files, plus the head root) it was 50-70 ms of ``context_built`` and up
to 250 ms of ``observability_built`` on every warm turn, and 0 on the offline
guard's empty home -- which is why the guard never saw it.

**What a turn does now.** The handler hands its pre-admit resolves a
:class:`TurnRootRegistries` map (``chat_turn_commit/run.py``). A root that map
has not seen yet is answered from the process registry cache
(``skill_resolution._SKILL_ROOT_REGISTRY_CACHE``) when that holds the root, and
is walked inline only when it does not (a cold process). The root is queued,
and the turn's ``request_sent`` (:func:`agent_runtime.mission_chat_phases.on_request_sent`)
starts ONE background re-walk of the queued roots, which refreshes the cache for
the next turn. Every other caller -- a resolve during the model run, a snapshot
build, the chat-open prewarm -- still walks inline and refreshes the same cache.

**Why what the turn sends does not change.** The registry answers which file
backs a skill name; the file's frontmatter and content are read fresh by the
loader either way. A cached answer can only be wrong about names added,
renamed or deleted since the last walk, and :func:`needs_fresh_walk` re-walks
inline when a requested name is missing or a resolved file is gone -- the two
ways such a change shows. What is left is a NEW duplicate of a resolved name
(a collision), seen one turn late. The same window the skill catalog memo has
held since h-send-window (``prompt_observability.skills_resolver``).
"""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from agent_runtime.mission_chat_phases import on_request_sent

__layer__ = "stores"

logger = logging.getLogger(__name__)

#: Work a turn deferred to its ``request_sent``: ``key -> refresh``. A root served from the cache
#: (``root:<root_key>``) and the shared skill catalog served from its memo are the two kinds.
_PENDING: dict[str, Callable[[], Any]] = {}
_PENDING_LOCK = threading.Lock()
#: The one re-walk in flight, if any; kept for a test to join.
_REVALIDATION: dict[str, threading.Thread | None] = {"thread": None}

REVALIDATE_THREAD_NAME = "skill-root-revalidate"


class TurnRootRegistries(dict):
    """A turn's pre-admit ``root_key -> registry`` map whose misses may be answered from the process cache.

    ``served_from_cache`` names the roots this turn took from the cache without walking, so a resolve
    that finds a name missing can walk exactly those.
    """

    __slots__ = ("served_from_cache",)

    def __init__(self) -> None:
        super().__init__()
        self.served_from_cache: dict[str, Path] = {}


def registry_for_turn(root: Path, root_key: str, turn_map: TurnRootRegistries) -> Any:
    """The cached registry for ``root`` (queued for a re-walk after ``request_sent``), else a walk."""

    from agent_runtime import skill_resolution as resolution

    with resolution._SKILL_ROOT_REGISTRY_LOCK:
        cached = resolution._SKILL_ROOT_REGISTRY_CACHE.get(root_key)
    if cached is None:
        return resolution._skill_root_registry(root)
    turn_map.served_from_cache[root_key] = root
    queue_after_request_sent(f"root:{root_key}", functools.partial(resolution._skill_root_registry, root))
    return cached


def queue_after_request_sent(key: str, refresh: Callable[[], Any]) -> None:
    """Run ``refresh`` on the background re-walk the next ``request_sent`` starts (in the caller's context)."""

    with _PENDING_LOCK:
        _PENDING[key] = functools.partial(contextvars.copy_context().run, refresh)


def needs_fresh_walk(turn_map: Any, resolutions: dict[str, Any]) -> bool:
    """True when a cache-served answer may be stale: a name is missing, or a resolved file is gone."""

    if not isinstance(turn_map, TurnRootRegistries) or not turn_map.served_from_cache:
        return False
    for resolution in resolutions.values():
        if resolution.status == "missing":
            return True
        for candidate in resolution.candidates:
            try:
                if not candidate.skill_md.is_file():
                    return True
            except OSError:
                return True
    return False


def walk_served_roots(turn_map: TurnRootRegistries) -> None:
    """Replace every cache-served registry in ``turn_map`` with a fresh walk (the miss path)."""

    from agent_runtime import skill_resolution as resolution

    served, turn_map.served_from_cache = dict(turn_map.served_from_cache), {}
    for root_key, root in served.items():
        turn_map[root_key] = resolution._skill_root_registry(root)


def _revalidate(refreshes: dict[str, Callable[[], Any]]) -> None:
    try:
        for key, refresh in refreshes.items():
            try:
                refresh()
            except Exception:
                logger.debug("deferred refresh %s failed", key, exc_info=True)
    finally:
        with _PENDING_LOCK:
            _REVALIDATION["thread"] = None
            again = bool(_PENDING)
        if again:
            revalidate_served_roots()


def revalidate_served_roots() -> threading.Thread | None:
    """Start the one background run of every queued refresh. Never raises; the thread, if started."""

    try:
        with _PENDING_LOCK:
            if _REVALIDATION["thread"] is not None or not _PENDING:
                return None
            refreshes = dict(_PENDING)
            _PENDING.clear()
            thread = threading.Thread(target=_revalidate, args=(refreshes,), name=REVALIDATE_THREAD_NAME, daemon=True)
            _REVALIDATION["thread"] = thread
        thread.start()
        return thread
    except Exception:
        logger.debug("skill root re-walk not started", exc_info=True)
        with _PENDING_LOCK:
            _REVALIDATION["thread"] = None
        return None


on_request_sent(revalidate_served_roots)


def pending_refreshes_for_tests() -> list[str]:
    with _PENDING_LOCK:
        return sorted(_PENDING)


def reset_for_tests() -> None:
    with _PENDING_LOCK:
        _PENDING.clear()


__all__ = [
    "REVALIDATE_THREAD_NAME", "TurnRootRegistries", "needs_fresh_walk", "pending_refreshes_for_tests",
    "queue_after_request_sent", "registry_for_turn", "reset_for_tests", "revalidate_served_roots",
    "walk_served_roots",
]
