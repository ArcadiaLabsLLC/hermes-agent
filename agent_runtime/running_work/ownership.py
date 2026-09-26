"""Who owns what, honestly: the head home the durable stores live under, the
store paths (the ONE authority), PID identity (honesty rule 2), the session
owner (rule 5) and the ambient block that names the home."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._upstream_doors import pid_exists

from .rows import bounded_operator_text
from .vocabulary import PID_DEAD, PID_NO_BASELINE, PID_RECYCLED, PID_START_TIME_UNREADABLE, PID_VERIFIED, _CHECKPOINT_FILENAME, _STATE_DB_FILENAME

__layer__ = "stores"


def _head_home() -> tuple[Path | None, str]:
    """The durable home the background stores live under, plus its provenance.

    This MUST resolve to the directory the WRITERS use, and now it does: this
    function, ``process_registry.checkpoint_path`` and
    ``async_delegation._db_path`` all call the same
    ``get_hermes_background_work_home`` authority.

    The first version resolved the CHAT head-home scope instead. That scope
    consults a durable ``chat_head_home.json`` pointer the writers know nothing
    about, so wherever the pointer disagreed with the writers' ambient home the
    projection watched one directory while the work was recorded in another —
    and reported "nothing running", with every source ``ok``, for the entire
    life of a build. A confident empty answer is the worst failure this
    projection can produce, and it was reachable on the launcher's own layout
    (``HERMES_HOME=profiles/<profile>`` beside ``HERMES_HEAD_HOME=profiles/base``).

    Ambient ``get_hermes_home()`` is not an option either: it is flipped
    process-globally for the duration of a persona turn, and persona turns share
    a process with snapshot builds. The head authority is correct in both
    situations precisely because ``persona_profile_context`` records the
    operator home BEFORE it diverts the ambient one.
    """

    try:
        from agent_runtime.profile_home import (
            get_hermes_background_work_home,
            hermes_head_home_is_authoritative,
        )

        home = Path(get_hermes_background_work_home())
    except Exception:
        return None, "unresolved"
    try:
        explicit = bool(hermes_head_home_is_authoritative())
    except Exception:  # pragma: no cover - defensive
        explicit = False
    return home, "head_home" if explicit else "ambient_home"


def running_work_store_paths() -> tuple[Path, ...]:
    """The durable stores this projection reads — the ONE authority for them.

    Exported because the serve read-model cache must fingerprint exactly these
    files: both mutate with NO EventLog event (a background process starting or
    exiting rewrites the checkpoint; a delegation dispatch/finalize writes
    ``async_delegations``), so without a stat the 20s cache would keep serving a
    HUD claiming three processes are running for twenty seconds after they all
    exited — and, worse, claiming nothing is running for twenty seconds after an
    agent kicked off a long build.

    Returns an empty tuple when the home cannot be resolved; the caller must
    treat that as "cannot fingerprint" rather than "nothing to watch".
    """

    head, _ = _head_home()
    if head is None:
        return ()
    return (head / _CHECKPOINT_FILENAME, head / _STATE_DB_FILENAME)


def _pid_identity(pid: Any, expected_start: Any) -> tuple[bool, bool, str]:
    """``(alive, verified, verdict)`` for a host PID against its spawn ticks.

    ``alive`` is a bare existence probe; ``verified`` additionally proves the
    number was not recycled onto an unrelated process. ``verdict`` is one of the
    ``PID_*`` constants and is what the caller must branch on — only
    :data:`PID_DEAD` and :data:`PID_RECYCLED` are DISPROOF that the work is
    running. :data:`PID_NO_BASELINE` and :data:`PID_START_TIME_UNREADABLE` are
    both merely unproven, and must surface as an ``unknown`` row.
    """

    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False, False, PID_DEAD
    if pid_int <= 0:
        return False, False, PID_DEAD
    try:
        from gateway.status import get_process_start_time
    except Exception:
        # Without the probe we cannot even test liveness. Refusing to claim
        # anything is the honest answer, and the row keeps its unknown status
        # rather than being reported dead.
        return True, False, PID_START_TIME_UNREADABLE
    try:
        # The existence probe is upstream's private ``_pid_exists``, read through
        # the package's door (which imports it at call time, so a stub on
        # ``gateway.status`` still reaches it); an ImportError lands here too.
        alive = bool(pid_exists(pid_int))
    except Exception:
        return True, False, PID_START_TIME_UNREADABLE
    if not alive:
        return False, False, PID_DEAD
    if expected_start is None:
        return True, False, PID_NO_BASELINE
    try:
        observed = get_process_start_time(pid_int)
    except Exception:
        return True, False, PID_START_TIME_UNREADABLE
    if observed is None:
        # The platform/permissions could not answer. NOT a mismatch: comparing
        # None against a real baseline yields False, which is how an unreadable
        # probe used to masquerade as a recycled PID.
        return True, False, PID_START_TIME_UNREADABLE
    try:
        matches = int(observed) == int(expected_start)
    except (TypeError, ValueError):
        return True, False, PID_START_TIME_UNREADABLE
    return True, matches, PID_VERIFIED if matches else PID_RECYCLED


def _owner_of(
    session_id: Any, *, memo: dict[str, tuple[str, str]] | None = None
) -> tuple[str, str]:
    """``(persona_id, persona_instance_id)`` owning a session, or ``("", "")``.

    Every lane that knows only a session id gets its owner from HERE, and here
    defers to :func:`agent_runtime.persona_assignments.chat_session_owner_persona`
    — the runtime's single answer to "whose work is this", already relied on by
    the dispatch-delivery lane. No lane derives ownership for itself: this
    projection's whole reason to exist is that five subsystems must not answer
    the same operator question five different ways.

    Why this function exists at all: the delegation and terminal lanes used to
    pass only ``session_id``, so every row on them shipped
    ``owner: {persona_id: null, persona_instance_id: null}`` — and Mission
    Control's Activity surface groups BY owner, so a background
    ``delegate_task`` could never appear there. Not late: never.

    An unresolvable session answers ``("", "")`` and the row ships an honestly
    EMPTY owner. Fabricating one — the parent's persona, the active instance,
    anything plausible — would put a confident falsehood on an operator console,
    which is strictly worse than a blank: a consumer can render "no owning
    agent", but it cannot un-believe a name.

    ``memo`` is a caller-owned, BUILD-SCOPED dict. Sibling delegations spawned
    from one conversation all name the same chat root, so without it a lane pays
    one instance-store read per row for an answer it already has. It is passed in
    rather than cached module-side on purpose: a process-lifetime cache would
    keep serving a renamed or retired instance long after the store moved on, and
    a projection that exists to stop stale claims must not manufacture one.
    """

    token = bounded_operator_text(session_id, limit=240)
    if not token:
        return "", ""
    if memo is not None and token in memo:
        return memo[token]
    try:
        from ..persona_assignments import chat_session_owner_persona

        resolved = chat_session_owner_persona(token)
    except Exception:
        # The projection answers with what it has rather than failing a lane:
        # an unresolved owner is already a modelled, visible state.
        resolved = None
    owner = resolved if resolved else ("", "")
    if memo is not None:
        memo[token] = owner
    return owner


def _ambient_context() -> dict[str, str]:
    """Machine-local context for this build. **NOT contract — do not branch on it.**

    Names the background-work home the projection resolved, so an operator can
    tell "nothing is running" apart from "nothing is running *in the directory I
    happened to resolve*" — the exact silent-empty failure
    ``get_hermes_background_work_home`` was introduced to retire.

    Deliberately a BASENAME plus a provenance token, not a path: the error
    contract forbids absolute paths in operator-visible messages, and the
    question this answers ("which home did you mean?") is answered by the name.

    Deliberately ONE block rather than a per-lane field, because it is ONE
    fact: both durable lanes resolve the same home through the same authority,
    and duplicating it into two lanes' prose is how it got concatenated onto a
    contract field in the first place.

    Nothing in this module reads this back. It is published, never consulted.
    """

    head, provenance = _head_home()
    return {
        "home_provenance": provenance,
        "home_name": head.name if head is not None else "",
    }
