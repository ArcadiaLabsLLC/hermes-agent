"""The retired-instance archive layout: the ``*_retire`` batch directories, the
per-id archive path, the retire receipt path, and the retired-id set every mint
consults.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from hermes_time import now
from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments.errors import PersonaInstanceRetireError
from agent_runtime.persona_assignments.identity import (
    canonical_chat_instance_id,
    is_canonical_persona_channel,
)
from agent_runtime.serde import (
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
)
from agent_runtime.state_patches.persona_instance import emit_persona_instance_remove

if TYPE_CHECKING:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"

__all__ = [
    "read_retire_receipt",
    "retire",
    "retire_receipt_path",
    "RETIRE_RECEIPTS_DIRNAME",
    "retired_instance_archive_path",
    "retired_instance_ids",
    "retired_persona_instance_ids",
    "_archive_instance_row",
    "_archive_office_placements",
    "_retire_archive_batches",
    "_retired_persona_instance_archive_path",
    "_write_retire_receipt",
]


def _retire_archive_batches() -> list[Path]:
    """Newest-first ``*_retire`` batch directories under the instance archive.

    THE selection rule for retirement tombstones, in one place: only ``*_retire``
    batches are tombstones. Reconcile/prune archives answer different lifecycle
    questions and must not make a future legitimate mint impossible. Both the
    per-id probe (:func:`_retired_persona_instance_archive_path`) and the
    whole-archive listing (:func:`retired_persona_instance_ids`) read the archive
    through this, so a second, subtly different notion of "retired" cannot be
    born by one of them widening its glob.
    """
    archive_root = paths.persona_instances_archive_dir()
    if not archive_root.exists():
        return []
    return sorted(
        (
            candidate
            for candidate in archive_root.iterdir()
            if candidate.is_dir() and candidate.name.endswith("_retire")
        ),
        key=lambda candidate: candidate.name,
        reverse=True,
    )


def _retired_persona_instance_archive_path(
    persona_instance_id: str,
) -> Path | None:
    """Newest explicit-retire archive row for ``persona_instance_id``.

    Exact child paths avoid treating the instance id as a glob.
    """
    for archive_dir in _retire_archive_batches():
        candidate = archive_dir / f"{persona_instance_id}.json"
        if candidate.is_file():
            return candidate
    return None


#: The retire receipt subdirectory inside a ``*_retire`` batch. A SUBDIRECTORY
#: and never a sibling file, because every ``*.json`` FILE directly inside a
#: batch is read as a tombstone by :func:`retired_persona_instance_ids` — it
#: takes ``row.stem`` as the instance id — so a receipt written beside the row
#: would mint a phantom retired id and the retirement predicate would start
#: refusing legitimate mints for an agent that never existed. ``iterdir`` skips
#: directories and the per-id probe asks for an exact child, so this name is
#: invisible to both by construction rather than by their remembering to skip it.
RETIRE_RECEIPTS_DIRNAME = "receipts"


def retire_receipt_path(archive_dir: Path, persona_instance_id: str) -> Path:
    """Where THIS retire's receipt lives — the one layout authority, both ways.

    Spent by the writer (:meth:`PersonaInstanceStore.retire`) and by the reader
    (:meth:`PersonaInstanceStore.read_retire_receipt`), so the batch layout is
    stated once. See :data:`RETIRE_RECEIPTS_DIRNAME` for why it is a
    subdirectory.
    """

    return archive_dir / RETIRE_RECEIPTS_DIRNAME / f"{persona_instance_id}.json"


def retired_persona_instance_ids() -> frozenset[str]:
    """Every instance id carrying a retirement tombstone, in ONE archive listing.

    The ARCHIVE half of the retirement predicate, for readers that must answer
    "was this id deliberately retired?" for MANY ids at once — a snapshot
    projection walking its sessions, say. The per-id probe
    (:meth:`PersonaInstanceStore.retired_instance_archive_path`) stays the
    predicate of record for a single target because it also composes the LIVE
    half (a live row always wins); a caller of this listing must supply that half
    itself, which the projection callers do by construction — they only ask after
    an id has already failed to resolve against the live roster they hold.

    Read once and memoized by the caller for the length of its build, never
    re-walked per row: the archive is ~one directory per retire, forever.

    NEVER RAISES. The listing is filesystem I/O over a store root that is
    routinely a flaky UNC share on this runtime; a reader that cannot see the
    archive cannot PROVE a retirement, so it reports the empty set (every id
    stays unresolved/anomalous — the loud, pre-fix posture) and logs.
    """
    try:
        return frozenset(_iter_archived_instance_ids())
    except OSError:
        logging.getLogger(__name__).warning(
            "persona-instance retirement archive listing failed; "
            "treating every instance as NOT retired",
            exc_info=True,
        )
        return frozenset()


def _iter_archived_instance_ids() -> Iterator[str]:
    """Each tombstone row's instance id: every ``*.json`` FILE directly inside a
    ``*_retire`` batch (receipts live in a subdirectory, so they never count)."""
    for archive_dir in _retire_archive_batches():
        for row in archive_dir.iterdir():
            if not (row.is_file() and row.suffix == ".json"):
                continue
            instance_id = safe_assignment_token(row.stem)
            if instance_id:
                yield instance_id


def _archive_office_placements(
    store: PersonaInstanceStore, instance: PersonaInstance, *, correlation_id: str | None = None
) -> dict[str, Any]:
    """Archive office actors when a live placement is retired, and SAY what happened.

    The office half stays best-effort — placement retirement is
    authoritative with or without the office projection, and a retire that
    raised because a desk file was locked would leave the operator unable to
    retire at all — but "best-effort" used to also mean "unsaid": this method
    returned ``None`` and swallowed every fault, so the two-lane removal the
    launcher performs (retire the row, remove the actor) had no receipt
    joining its halves and a half-state (row archived, desk still on the
    canvas) was invisible to everyone including the caller that caused it.
    Placement plan D7: the outcome LEAVES, and :meth:`retire` puts it on the
    ack.

    Shape is the store's own (``archived``, ``failed``, ``archived_actor_keys``,
    ``failures``). A fault in the projection ITSELF — the import, the store
    construction, the workspace listing — is not one actor's, so it is
    reported with ``actor_key: None``: naming an actor there would be a
    guess, and the whole point of this return value is that it stops
    guessing.

    ``correlation_id`` is the retiring GESTURE's token and it travels no
    further than the office writes: the row archive above already carries
    its own ``persona_instance.retired`` event, and the office half is the
    part that was landing in a second, unjoinable correlation space.
    """

    try:
        from ..office_store import OfficeStore

        return OfficeStore(event_log=store.event_log).archive_actors_for_instance(
            instance.id,
            reason="instance_reaped",
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001 - the retire is authoritative regardless
        logging.getLogger(__name__).warning(
            "office placement archive failed for %s", instance.id, exc_info=True
        )
        return {
            "archived": 0,
            "failed": 1,
            "archived_actor_keys": [],
            "failures": [
                {
                    "actor_key": None,
                    "workspace_id": instance.workspace_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ],
        }


def retire(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    *,
    reason: str = "placement removed",
    requested_by: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Instance end-of-life: archive a placement-backed (or otherwise
    deliberate) persona-instance ROW and emit an EventLog event.

    The operator ruling is that a deliberate placement IS the instance:
    deleting the placement ends the instance's life. This is the sanctioned
    verb for that transition — the row file MOVES to
    ``persona_instances_archive/<ts>_retire/`` (archive-never-delete), an
    evented mutation (no silent row move). Chat sessions and turn stores
    stay untouched on disk (history is never destroyed); the projection
    simply stops listing the row because ``list_all`` only globs the live
    dir, so every instance-fed surface (snapshot, roster, chat history,
    flow node dropdown) drops it on the next frame.

    The returned dict carries the OFFICE half beside the row's own fields:
    ``archived_actor_keys`` (every actor this retire took off the level) and
    ``office_archive_failures`` (every one it could not, with its error).
    Both are ADDITIVE and neither is authoritative over the row archive —
    the office projection may be unavailable and the retirement still
    stands — but they are no longer DISCARDED, which is what let a
    half-state (row archived, desk still on the canvas) exist with nothing
    able to detect it. ``agent_retire.perform_agent_retire`` is the service
    that puts them on an operator ack (placement plan D7).

    They are also PERSISTED, beside the tombstone, so a client that lost the
    ack can still be told what the office half did
    (:meth:`_write_retire_receipt`, H-H5). ``retire_receipt_path`` says
    where — ``None``, with ``retire_receipt_error`` beside it, when nothing
    could be written.

    Refuses with a typed :class:`PersonaInstanceRetireError` (never a silent
    no-op) when the row is the canonical persona/profile channel
    (``canonical_persona_channel`` — the global-singleton retirement is the
    queued workspace-scoping redesign), or when a live run/worker still
    resolves (``instance_active`` — never archive a working agent). The two
    ASSIGNMENT guards this method used to carry left with AX2; the class
    docstring above carries the argument."""
    try:
        instance = store.get(persona_instance_id)
    except Exception as exc:
        raise PersonaInstanceRetireError(
            "not_found",
            f"persona instance not found: {persona_instance_id}",
            persona_instance_id=safe_assignment_token(persona_instance_id) or str(persona_instance_id),
        ) from exc

    if is_canonical_persona_channel(instance):
        raise PersonaInstanceRetireError(
            "canonical_persona_channel",
            (
                f"{instance.id} is the canonical persona channel for "
                f"{instance.persona_id!r}; the global-singleton channel cannot be "
                "retired here (that is the queued workspace-scoping redesign) — "
                "retire a placement-backed instance instead"
            ),
            persona_instance_id=instance.id,
            detail={"persona_id": instance.persona_id},
        )

    if store._has_live_binding(instance):
        raise PersonaInstanceRetireError(
            "instance_active",
            f"{instance.id} has a live run binding; never retire a working agent",
            persona_instance_id=instance.id,
            detail={
                "active_run_id": safe_optional_token(instance.active_run_id),
            },
        )

    archive_dir = paths.persona_instances_archive_dir() / f"{now().strftime('%Y%m%dT%H%M%SZ')}_retire"
    archived_path = store._archive_instance_row(instance, archive_dir)
    if archived_path is None:
        raise PersonaInstanceRetireError(
            "not_found",
            f"persona instance row is not on disk: {instance.id}",
            persona_instance_id=instance.id,
        )
    safe_reason = safe_assignment_text(reason, limit=240) or "placement removed"
    normalized_requested_by = str(requested_by)[:80] if requested_by else None
    payload: dict[str, Any] = {
        "reason": safe_reason,
        "persona_id": instance.persona_id,
        "mode": instance.mode,
        "archive_dir": str(archive_dir),
    }
    if normalized_requested_by:
        payload["requested_by"] = normalized_requested_by
    store._event("persona_instance.retired", instance, payload)
    # S7-A producer: the retired row leaves the active frame, so the launcher
    # deletes the keyed row (never renders it as a live idle agent). Live
    # unless read_model.delta_patches is explicitly off (it ships on).
    emit_persona_instance_remove(store.event_log, instance)
    # Prune-lane hook (mirrors close_for_task / the janitor): a retired
    # instance must not leave a phantom office desk. Best-effort; office
    # archival never fails the retire.
    #
    # The gesture's token rides INTO the office half (S8b). Before it, a
    # removal gesture's two verbs lived in two correlation spaces: the
    # create/office writes stamped `correlation_id` on their patches and
    # the retire's office removes stamped nothing, so one grep over the two
    # logs could not join the halves of a single operator action — the
    # exact defect EG-2.3 built the token to retire.
    office = store._archive_office_placements(
        instance, correlation_id=correlation_id
    )
    result = {
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "display_name": instance.display_name,
        "mode": instance.mode,
        "reason": safe_reason,
        "requested_by": normalized_requested_by,
        "archive_path": str(archived_path),
        "archive_dir": str(archive_dir),
        # The office half, ADDITIVE and never authoritative over the row
        # archive above it: which actors this retire took off the canvas, and
        # which it could not. Empty failures is the claim "every bound actor
        # archived" — a claim this method could not make while the prune's
        # outcome was discarded (plan D7).
        "archived_actor_keys": list(office.get("archived_actor_keys") or []),
        "office_archive_failures": list(office.get("failures") or []),
    }
    return {**result, **store._write_retire_receipt(archive_dir, result)}


def _write_retire_receipt(
    store: PersonaInstanceStore, archive_dir: Path, result: dict[str, Any]
) -> dict[str, Any]:
    """Persist THIS retire's outcome beside its tombstone (H-H5).

    The office half is the part of a retire that only ever existed on the
    ack. ``archived_actor_keys`` survived a lost ack because the archive can
    be re-read; ``office_archive_failures`` did not, so a replay answered the
    positive-claim shape — the empty list — for a first attempt that had
    actually failed to take a desk off the canvas, and the operator whose ack
    went missing was told the opposite of what happened. The create has had a
    receipt for this reason since S4; this is the retire's.

    BEST-EFFORT AND SAID, never best-effort and silent. The retirement is
    already durable when this runs — refusing it because a receipt would not
    write would fail a retire that has succeeded — but a failed write is
    reported on the ack (``retire_receipt_path: None`` plus
    ``retire_receipt_error``), because "a best-effort lane discarded its
    outcome" is the exact class this repo has already paid for three times
    and the fourth instance is not going to be one written by the fix for the
    third.

    ``retire_receipt_path`` is present on every fresh ack, ``None`` when
    nothing was written — one shape, so a client never reads an absent key as
    "yes, it was recorded".
    """

    path = retire_receipt_path(archive_dir, result["persona_instance_id"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(
            path,
            {
                # The wall clock this retire ran at. Not derivable from the
                # batch directory name by a reader that should not have to
                # parse a path to learn a time.
                "retired_at": now().isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                ),
                **result,
            },
            indent=2,
            sort_keys=True,
        )
    except Exception as exc:  # noqa: BLE001 - the retirement is already durable
        logging.getLogger(__name__).warning(
            "retire receipt write failed for %s",
            result["persona_instance_id"],
            exc_info=True,
        )
        return {
            "retire_receipt_path": None,
            "retire_receipt_error": f"{type(exc).__name__}: {exc}",
        }
    return {"retire_receipt_path": str(path)}


def read_retire_receipt(
    store: PersonaInstanceStore, persona_instance_id: str | None
) -> dict[str, Any] | None:
    """The recorded outcome of the retire that archived this id, or ``None``.

    ``None`` for every answer that is not a receipt: no tombstone, a retire
    from before receipts existed, an unreadable file. NEVER RAISES — every
    caller is on a lane whose whole point is to answer a client that already
    lost its ack, and a traceback there would cost the answer as well as the
    receipt.

    The absence is INFORMATION, not a gap to paper over: it says the first
    attempt's per-actor failures are unrecoverable, which is exactly what was
    true of every retire before H-H5 and is what the replay reports instead
    of inventing an empty list.
    """

    tombstone = store.retired_instance_archive_path(persona_instance_id)
    if tombstone is None:
        return None
    instance_id = safe_assignment_token(persona_instance_id)
    if not instance_id:
        return None
    try:
        raw = json.loads(
            retire_receipt_path(tombstone.parent, instance_id).read_text(
                encoding="utf-8"
            )
        )
    except Exception:  # noqa: BLE001 - absent, unreadable, or not JSON
        return None
    return raw if isinstance(raw, dict) else None


def _archive_instance_row(store: PersonaInstanceStore, instance: PersonaInstance, archive_dir) -> Any:
    """Move the instance's row file into ``archive_dir`` (archive-never-delete).
    Returns the archived path, or ``None`` when the live row is already gone."""
    source = paths.persona_instance_path(instance.id)
    if not source.exists():
        return None
    store._release_parent_references(instance.id)
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / source.name
    shutil.move(str(source), str(target))
    return target


def retired_instance_ids(store: PersonaInstanceStore) -> frozenset[str]:
    """Every retired instance id, in one archive listing — the bulk reader's
    door to :func:`retired_persona_instance_ids` (see it for the contract and
    for why the LIVE half of the predicate is the caller's to supply)."""
    return retired_persona_instance_ids()


def retired_instance_archive_path(
    store: PersonaInstanceStore,
    persona_instance_id: str | None,
    *,
    persona_id: str | None = None,
) -> Path | None:
    """The retirement tombstone for *persona_instance_id*, or ``None``.

    THE read-only retirement predicate. Retirement is not a flag on a row —
    it is the ABSENCE of a live row PLUS the presence of a ``*_retire``
    archive — so every caller that needs the answer has to compose those two
    facts. Composing them inline at each site is how a second, subtly
    different retirement rule gets born (one that reads a reconcile/prune
    archive as a tombstone, say, and makes a legitimate future mint
    impossible), so the composition lives here and :meth:`open_chat` — the
    write chokepoint that refuses a retired placement — asks this same
    method instead of re-deriving it.

    It exists because ``open_chat`` answers the question only by RAISING,
    and by then a caller like ``PersonaChatMintReceiptStore.mint`` has
    already created a titled session row. A refusal decidable without
    writing anything must be decidable WITHOUT writing anything.

    Never creates, mutates, or resurrects a row. Pass ``persona_id`` to
    resolve a caller-supplied (or omitted) instance id through the same
    :func:`canonical_chat_instance_id` derivation ``open_chat`` uses;
    without it the id is taken as already canonical.

    NEVER RAISES for a storage failure. Both callers ask this before their
    first durable write, and the mint's caller handles exactly one typed
    error (:class:`RetiredPersonaInstanceError`) — so an ``OSError`` from a
    flaky/UNC store root escaping here would reach the operator as the
    untyped traceback this predicate exists to retire. A probe that cannot
    read the archive cannot PROVE retirement, so it reports ``None`` (the
    pre-flight's posture, now shared by construction) and logs; the write
    chokepoint ``open_chat`` still refuses a retired target, so failing open
    costs the litter, never the guarantee.
    """
    instance_id = (
        canonical_chat_instance_id(persona_id, persona_instance_id)
        if persona_id
        else safe_assignment_token(persona_instance_id)
    )
    if not instance_id:
        return None
    try:
        store.get(instance_id)
    except Exception:
        pass
    else:
        # A live row always wins: the archive is history, and an id carried by a
        # live placement is live — never a tombstone.
        return None
    try:
        return _retired_persona_instance_archive_path(instance_id)
    except OSError:
        # The tombstone probe is filesystem I/O (``exists`` / ``iterdir`` /
        # ``is_file``) over the archive root. Loud in the log, quiet in the
        # answer: a caller must not be handed a refusal the store never
        # actually proved, nor a traceback from a lane that has a typed
        # refusal contract.
        logging.getLogger(__name__).warning(
            "retirement tombstone probe failed for %s; "
            "treating the target as NOT retired",
            instance_id,
            exc_info=True,
        )
        return None
