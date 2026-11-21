"""Agents that lived nowhere become ordinary agents in the Default workspace.

Row ``RT-AGENTS-THAT-LIVED-NOWHERE-BECOME-ORDINARY-AGENTS-IN-THE-DEFAULT-WORKSPACE``; plan
``docs/agent-runtime-harness/planned/agent-template-vs-canonical-instance-2026-11-21.md`` §5(iii) and §6
(owner RULED 2026-11-21: option (iii), "keeping the existing copies that are in use"; review w1118a.78).

A runtime-global row ``personainst_<persona>`` (the hidden copy every persona gets) that HOLDS anything
is adopted in place: it gets ``workspace_id`` / ``realm_id`` of the local Default workspace, a desk on
that workspace's office through the one seating write (``agent_create/seat.py``), and the stamp
``adopted_from_global``; it keeps its id, so session ids, the move ledger, gateway bindings, Work
assignees and peers addressing it keep resolving. A stamped row is an ordinary placed instance.

What counts as holding something, read off facts this machine already keeps:

- a chat: the row's own chat pointer (``default_chat_session_id``, or the legacy chat ``session_id``), or a
  saved chat the move ledger says it holds;
- a goal (``goal_id`` / ``current_chat_goal``) or a Work pointer (``current_assignment_id`` /
  ``current_task_id``);
- folder slots (``assigned_slots``);
- a gateway binding (a live channel credential's ``bound_instances``);
- a Work assignee: a Work board row assigned to it (``assignee: persona:<id>``), read off the boards as
  hermes's worktrees hold them now (an observation read, never a sync). An archived assignee resolves
  ``assignee_unknown``, so such a row is in live use and is adopted, never archived.

``RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT`` (review w1118a.78/.80): once nothing mints the hidden
copy, a row that holds nothing is ARCHIVED through retire's archive (never a delete), so it stays archived
across boots. That includes a copy whose only content is saved chats known from their transcripts (the
transcript's persisted instance or the minted id, no pointer and no ledger entry): the owner RULED those
cleaned up, and Chat history keeps listing them under the agent (``persona_chat_history`` reads a retired
holder's archive row). The report counts them (``saved_chats``) and flags a copy whose chats live in a
``per_profile`` head (``per_profile_head``), which Chat history does not read once the holder is retired.

A row that is neither adopted nor archived is HELD MACHINE-LOCAL (``held_local``, with its reason): it gets
the ``adopted_from_global`` stamp and no workspace, so realm publish, drift, the peer roster and
``peer.thread.read`` keep skipping it exactly as they skipped the hidden copy, and the next run retries it.
After a run no unstamped ``personainst_<persona>`` row is left (:func:`unstamped_hidden_copies`, the security
gate the canonical predicate's deletion waits on). Held, retried at the next run (documented, not worked):

- ``mid_turn``: the row has a live run binding (``active_run_id``);
- ``running_goal``: a Work run's goal is bound to one of its chats (``chat_goal.bindings``);
- ``default_realm_syncs``: the Default workspace's realm has a sync remote or a server (§6 rule 1 —
  adoption never places into a realm that publishes);
- ``no_default_workspace``: the Default workspace is missing or archived, or names no live realm;
- ``seat_refused``: the office refused the desk (an archived desk under the same key, a store fault);
- ``profile_channel``: an empty ``personainst_profile_<name>`` row is a profile's own channel, which a
  ``profile_<name>`` send still opens (a profile persona is not placeable), so it is never archived;
- ``work_unreadable``: the Work boards could not be read, so no empty row is archived this run;
- ``archive_refused``: retire refused the archive (a live run binding found on a second look).

Security (§6): the run is reachable only from the reconciler (``reconcile_persona_instances``) and the
serve boot, never from a caller tier; every adopted row is stamped and the stamp keeps it out of realm
publish (``realm_sync/publish_scans.py``), drift, the peer roster and ``peer.thread.read``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from hermes_time import now

__layer__ = "stores"
__all__ = [
    "ADOPTED",
    "ARCHIVED",
    "HELD_LOCAL",
    "WOULD_ADOPT",
    "WOULD_ARCHIVE",
    "WOULD_HOLD_LOCAL",
    "adopt_global_rows",
    "adopted_local_instance_ids",
    "canonical_row_holdings",
    "hold_unstamped_hidden_copies",
    "is_hidden_copy_id",
    "unstamped_hidden_copies",
]

ADOPTED = "adopted"
WOULD_ADOPT = "would_adopt"
ARCHIVED = "archived"
WOULD_ARCHIVE = "would_archive"
HELD_LOCAL = "held_local"
WOULD_HOLD_LOCAL = "would_hold_local"

SKIP_MID_TURN = "mid_turn"
SKIP_RUNNING_GOAL = "running_goal"
SKIP_DEFAULT_REALM_SYNCS = "default_realm_syncs"
SKIP_NO_DEFAULT_WORKSPACE = "no_default_workspace"
SKIP_SEAT_REFUSED = "seat_refused"
HOLD_PROFILE_CHANNEL = "profile_channel"
HOLD_WORK_UNREADABLE = "work_unreadable"
HOLD_ARCHIVE_REFUSED = "archive_refused"

#: The words retire records on an archived hidden copy (``persona_instance.retired``).
ARCHIVE_REASON = "hidden copy holds nothing (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT)"

_logger = logging.getLogger(__name__)


def is_hidden_copy_id(instance: Any) -> bool:
    """Whether ``instance`` carries the id its persona's hidden copy was minted under.

    The migration's own reader, and its only one: it finds the rows this module settles. A row that
    carries the id AND the stamp AND a workspace is an adopted, ordinary placed instance."""

    from .persona_assignments import persona_instance_id_for

    persona_id = str(getattr(instance, "persona_id", "") or "").strip()
    return bool(persona_id) and getattr(instance, "id", None) == persona_instance_id_for(persona_id)


def _unsettled(instance: Any) -> bool:
    """A hidden copy this module still has to settle: unstamped, or held with no workspace."""

    return is_hidden_copy_id(instance) and not (
        getattr(instance, "adopted_from_global", None) and getattr(instance, "workspace_id", None)
    )


def unstamped_hidden_copies(instances: Any = None) -> list[str]:
    """Ids of every ``personainst_<persona>`` row carrying no stamp: the security gate's count.

    Zero after a run. A non-zero answer means a row could be read as an ordinary unscoped agent, which
    realm publish and the peer roster would no longer skip once the canonical predicate is gone."""

    from .persona_assignments import PersonaInstanceStore

    rows = PersonaInstanceStore().list_all() if instances is None else instances
    return sorted(i.id for i in rows if is_hidden_copy_id(i) and not getattr(i, "adopted_from_global", None))


def hold_unstamped_hidden_copies(*, store: Any = None, today: str | None = None) -> list[str]:
    """The fallback when a run fails: stamp every unstamped hidden copy machine-local, nothing else.

    The serve boot calls it when :func:`adopt_global_rows` raises, so the security gate holds even then:
    no ``personainst_<persona>`` row is ever left readable as an ordinary unscoped agent."""

    from .persona_assignments import PersonaInstanceStore

    store = store or PersonaInstanceStore()
    stamp = today or now().date().isoformat()
    held = []
    for instance_id in unstamped_hidden_copies(store.list_all()):
        store.patch_fields(instance_id, workspace_id=None, realm_id=None, adopted_from_global=stamp)
        held.append(instance_id)
    return held


def adopted_local_instance_ids() -> frozenset[str]:
    """Ids of every stamped row: the machine-local set realm publish and drift skip.

    Empty when the store will not list (a publish that cannot read the stamps keeps
    publishing what it did before; the realm guard in :func:`adopt_global_rows` is the
    first line, this is the second)."""

    from .persona_assignments import PersonaInstanceStore, is_adopted_local_instance

    try:
        instances = PersonaInstanceStore().list_all()
    except Exception:
        return frozenset()
    return frozenset(instance.id for instance in instances if is_adopted_local_instance(instance))


def _row_chats(instance: Any, moves: dict[str, str]) -> list[str]:
    chats = []
    for value in (getattr(instance, "default_chat_session_id", None), getattr(instance, "session_id", None)):
        if isinstance(value, str) and value.startswith("persona_chat_") and value not in chats:
            chats.append(value)
    chats.extend(sorted(session for session, holder in moves.items() if holder == instance.id and session not in chats))
    return chats


def canonical_row_holdings(
    instance: Any, *, moves: dict[str, str], gateway_bound: frozenset[str],
    work_assignees: frozenset[str] = frozenset(),
) -> list[str]:
    """What ``instance`` holds, as words: ``chat``, ``goal``, ``work``, ``slots``, ``gateway``."""

    held = []
    if _row_chats(instance, moves):
        held.append("chat")
    if getattr(instance, "goal_id", None) or getattr(instance, "current_chat_goal", None):
        held.append("goal")
    # A Work board row assigned to the copy holds it as surely as a Work pointer on it (review w1118a.80,
    # kind 2). MUTATION: drop the assignee test and test_a_work_assignee_with_no_pointer_is_adopted reddens.
    if (getattr(instance, "current_assignment_id", None) or getattr(instance, "current_task_id", None)
            or instance.id in work_assignees):
        held.append("work")
    if getattr(instance, "assigned_slots", None):
        held.append("slots")
    if instance.id in gateway_bound:
        held.append("gateway")
    return held


def _gateway_bound_instance_ids() -> frozenset[str]:
    from . import paths
    from .serve_gateway_auth.store import decode_device, read_devices

    try:
        rows = read_devices(paths.store_root())
    except Exception:
        return frozenset()
    bound: set[str] = set()
    for row in rows.values():
        record = decode_device(row)
        if record is not None and not record.revoked:
            bound.update(record.bound_instances)
    return frozenset(bound)


def _work_assignee_tokens() -> frozenset[str] | None:
    """Every ``assignee: persona:<token>`` on this install's Work boards; ``None`` when a board will not read.

    An OBSERVATION read (``work.store.observed``): the boards as hermes's worktrees hold them now, never a
    sync, fetch or write. ``None`` holds every empty row this run (``work_unreadable``): an archived
    assignee resolves ``assignee_unknown``, so a row is archived only when the boards were read."""

    from .default_scope import DEFAULT_WORKSPACE_ID
    from .office_store.store import OfficeStore
    from .work.store import observed
    from .work_store.board import PERSONAL_BOARD_ID, board_rows

    tokens: set[str] = set()
    try:
        owners = sorted({*OfficeStore().list_workspaces(), DEFAULT_WORKSPACE_ID})  # work.service.workspace_ids
        for owner in (*owners, PERSONAL_BOARD_ID):
            for board in observed(owner).boards:
                tokens.update(row.assignee.token for row in board_rows(board) if row.assignee is not None)
    except Exception:
        _logger.warning("persona_instance_adoption could not read the Work boards", exc_info=True)
        return None
    return frozenset(tokens)


def _transcript_chats(candidates: set[str]) -> dict[str, int]:
    """``{holder id: saved chats}`` for ``candidates``, read off the process chat store's transcripts.

    The holder of a saved chat is its transcript's persisted instance, else the move ledger's or the
    minted id's (``chat_session_held_by``) — the same holder Chat history lists a retired holder's chat
    under (``persona_chat_history.summary``). Read-only; empty when there is no store."""

    from . import chat_session_scope
    from .persona_assignments.chat_moves import chat_session_held_by
    from .persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
    from .persona_chat_history.history_rows import _list_sessions, _persisted_persona_instance_id

    counts: dict[str, int] = {}
    if not candidates:
        return counts
    try:
        db = chat_session_scope.open_chat_session_db(access=chat_session_scope.SessionDbAccess.READ)
    except Exception:
        return counts
    if db is None:
        return counts
    offset, page_size = 0, 500
    while True:
        page = _list_sessions(db, source=PERSONA_CHAT_SESSION_SOURCE, limit=page_size,
                              include_children=False, offset=offset)
        for raw in page:
            if not isinstance(raw, dict):
                continue
            holder = _persisted_persona_instance_id(raw) or chat_session_held_by(raw.get("id"))
            if holder in candidates:
                counts[holder] = counts.get(holder, 0) + 1
        if len(page) < page_size:
            return counts
        offset += len(page)


def _running_goal_roots() -> frozenset[str]:
    from .chat_goal import bindings

    try:
        return frozenset(binding.root_session_id for binding in bindings())
    except Exception:
        return frozenset()


def _default_scope() -> tuple[Any, Any, str | None]:
    """``(workspace, realm, refusal)``: the local Default workspace and its realm, or why not."""

    from .default_scope import DEFAULT_WORKSPACE_ID
    from .store import RealmStore, WorkspaceStore

    try:
        workspace = WorkspaceStore().get(DEFAULT_WORKSPACE_ID)
    except Exception:
        return None, None, SKIP_NO_DEFAULT_WORKSPACE
    if workspace.archived or not workspace.realm_id:
        return None, None, SKIP_NO_DEFAULT_WORKSPACE
    try:
        realm = RealmStore().get(workspace.realm_id)
    except Exception:
        return None, None, SKIP_NO_DEFAULT_WORKSPACE
    if realm.archived:
        return None, None, SKIP_NO_DEFAULT_WORKSPACE
    # §6 rule 1: never place into a realm that publishes. A server-less realm carries a backup
    # remote (``harness realm sync remote set``) or a pinned repo in ``sync_manifest_ref``.
    # MUTATION: drop the sync_manifest_ref test and test_a_default_realm_with_a_backup_remote_adopts_nothing reddens.
    if realm.server_id or str(getattr(realm, "sync_manifest_ref", "") or "").strip():
        return workspace, realm, SKIP_DEFAULT_REALM_SYNCS
    return workspace, realm, None


def adopt_global_rows(
    *, apply: bool = True, store: Any = None, today: str | None = None, leaving: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """Settle every hidden copy: adopt it, archive it or hold it machine-local; one fate per row, by id.

    ``apply=False`` names each row's fate (``would_adopt``, ``would_archive``, ``would_hold_local`` with
    its reason) and writes nothing: the census, run before anything is archived. A second applied run
    finds nothing to do. ``leaving`` names rows an earlier reconcile phase archives in this run: a dry
    run still lists them, so they are discounted here and the preview matches an applied run."""

    from .persona_assignments import PersonaInstanceStore
    from .persona_assignments.chat_moves import load_chat_moves

    store = store or PersonaInstanceStore()
    # MUTATION: drop the ``leaving`` test and test_the_dry_run_does_not_adopt_a_row_an_earlier_phase_archives reddens.
    rows = sorted((i for i in store.list_all() if _unsettled(i) and i.id not in leaving), key=lambda i: i.id)
    if not rows:
        return []
    moves = load_chat_moves()
    gateway_bound = _gateway_bound_instance_ids()
    goal_roots = _running_goal_roots()
    work_assignees = _work_assignee_tokens()
    workspace, realm, scope_refusal = _default_scope()
    stamp = today or now().date().isoformat()
    holdings = {i.id: canonical_row_holdings(i, moves=moves, gateway_bound=gateway_bound,
                                             work_assignees=work_assignees or frozenset()) for i in rows}
    saved = _transcript_chats({i.id for i in rows if not holdings[i.id]})
    report: list[dict[str, Any]] = []
    for instance in rows:
        held = holdings[instance.id]
        entry: dict[str, Any] = {"persona_instance_id": instance.id, "persona_id": instance.persona_id, "holds": held}
        if not held:
            report.append(_archive_or_hold(store, instance, entry, apply=apply, stamp=stamp,
                                           saved_chats=saved.get(instance.id, 0), work_read=work_assignees is not None))
            continue
        reason = None
        if getattr(instance, "active_run_id", None):
            reason = SKIP_MID_TURN
        elif goal_roots.intersection(_row_chats(instance, moves)):
            reason = SKIP_RUNNING_GOAL
        else:
            reason = scope_refusal
        if reason is not None:
            report.append(_hold_local(store, instance, entry, reason, apply=apply, stamp=stamp))
            continue
        report.append(_adopt(store, instance, entry, workspace, realm, apply=apply, stamp=stamp))
    for item in report:
        _logger.info(
            "persona_instance_adoption instance=%s fate=%s reason=%s holds=%s saved_chats=%s",
            item["persona_instance_id"], item["fate"], item.get("reason"), ",".join(item["holds"]) or "-",
            item.get("saved_chats", "-"),
        )
    if apply and (left := unstamped_hidden_copies(store.list_all())):
        # The security gate (review w1118a.78): never reached by a run that completed, so said loudly.
        _logger.error("persona_instance_adoption left unstamped hidden copies: %s", ",".join(left))
    return report


def _adopt(store, instance, entry, workspace, realm, *, apply: bool, stamp: str) -> dict[str, Any]:
    from .agent_create.seat import ALREADY_SEATED, SEATED, WOULD_SEAT, seat_added_instance

    adopted = replace(instance, workspace_id=workspace.id, realm_id=realm.id, adopted_from_global=stamp)
    # The desk first: a desk without the stamp is healed by the next run (``already_seated``);
    # a stamp without a desk would be a placed instance standing nowhere.
    seat = seat_added_instance(adopted, updated_by="harness", dry_run=not apply)
    if seat.reason not in {SEATED, WOULD_SEAT, ALREADY_SEATED}:
        return _hold_local(store, instance, {**entry, "seat": seat.receipt()}, SKIP_SEAT_REFUSED,
                           apply=apply, stamp=stamp)
    item = {**entry, "fate": ADOPTED if apply else WOULD_ADOPT, "workspace_id": workspace.id,
            "realm_id": realm.id, "adopted_from_global": stamp}
    if apply:
        # Re-read and write only the three fields, so a rename or a model pick landing since the
        # listing is never reverted by this run.
        written = store.patch_fields(instance.id, workspace_id=workspace.id, realm_id=realm.id,
                                     adopted_from_global=stamp)
        store._event("persona_instance.reconciled", written, {**item, "action": ADOPTED})  # store maintenance
    return item


def _hold_local(store, instance, entry, reason: str, *, apply: bool, stamp: str) -> dict[str, Any]:
    """Stamp the row and clear its scope pointers: machine-local, unplaced, retried at the next run."""

    item = {**entry, "fate": HELD_LOCAL if apply else WOULD_HOLD_LOCAL, "reason": reason}
    already = getattr(instance, "adopted_from_global", None) and not (
        getattr(instance, "workspace_id", None) or getattr(instance, "realm_id", None))
    if apply and not already:
        # MUTATION: skip this write and test_a_row_the_adoption_cannot_place_is_held_machine_local reddens.
        written = store.patch_fields(instance.id, workspace_id=None, realm_id=None,
                                     adopted_from_global=instance.adopted_from_global or stamp)
        store._event("persona_instance.reconciled", written, {**item, "action": HELD_LOCAL})  # store maintenance
    return item


def _archive_or_hold(store, instance, entry, *, apply: bool, stamp: str, saved_chats: int,
                     work_read: bool) -> dict[str, Any]:
    """An empty copy (chats known only from transcripts included) is archived through retire's archive."""

    from .models import CHAT_HEAD_KIND_PER_PROFILE

    if str(instance.persona_id).startswith("profile_"):
        return _hold_local(store, instance, entry, HOLD_PROFILE_CHANNEL, apply=apply, stamp=stamp)
    if getattr(instance, "active_run_id", None):
        return _hold_local(store, instance, entry, SKIP_MID_TURN, apply=apply, stamp=stamp)
    # MUTATION: drop this test and test_an_unreadable_work_board_archives_nothing reddens.
    if not work_read:
        return _hold_local(store, instance, entry, HOLD_WORK_UNREADABLE, apply=apply, stamp=stamp)
    item = {**entry, "fate": ARCHIVED if apply else WOULD_ARCHIVE, "saved_chats": saved_chats}
    if getattr(instance, "chat_head_kind", None) == CHAT_HEAD_KIND_PER_PROFILE:
        item["per_profile_head"] = True
    if not apply:
        return item
    from .persona_assignments.errors import PersonaInstanceRetireError

    try:
        receipt = store.retire(instance.id, reason=ARCHIVE_REASON, requested_by="harness")
    except PersonaInstanceRetireError as exc:
        return _hold_local(store, instance, {**entry, "refusal": exc.code}, HOLD_ARCHIVE_REFUSED,
                           apply=apply, stamp=stamp)
    return {**item, "archive_path": receipt.get("archive_path")}
