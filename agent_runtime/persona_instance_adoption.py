"""Agents that lived nowhere become ordinary agents in the Default workspace.

Row ``RT-AGENTS-THAT-LIVED-NOWHERE-BECOME-ORDINARY-AGENTS-IN-THE-DEFAULT-WORKSPACE``; plan
``docs/agent-runtime-harness/planned/agent-template-vs-canonical-instance-2026-11-21.md`` §5(iii) and §6
(owner RULED 2026-11-21: option (iii), "keeping the existing copies that are in use"; review w1118a.78).

A runtime-global row ``personainst_<persona>`` (the hidden copy every persona gets) that HOLDS anything
is adopted in place: it gets ``workspace_id`` / ``realm_id`` of the local Default workspace, a desk on
that workspace's office through the one seating write (``agent_create/seat.py``), and the stamp
``adopted_from_global``; it keeps its id, so session ids, the move ledger, gateway bindings, Work
assignees and peers addressing it keep resolving. A stamped row answers False to
``is_canonical_persona_channel`` and keeps its workspace on decode.

What counts as holding something, read off facts this machine already keeps:

- a chat: the row's own chat pointer (``default_chat_session_id``, or the legacy chat ``session_id``), or a
  saved chat the move ledger says it holds;
- a goal (``goal_id`` / ``current_chat_goal``) or a Work pointer (``current_assignment_id`` /
  ``current_task_id``);
- folder slots (``assigned_slots``);
- a gateway binding (a live channel credential's ``bound_instances``).

A row that holds nothing is LEFT AS IT IS (``left_empty``): this row retires and archives nothing.
``RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT`` archives empty rows in the change that stops the
mint, because an archive made while the mint runs is minted again at the next snapshot build.

Skipped and reported, retried at the next run (the plan's documented edge cases, not worked):

- ``mid_turn``: the row has a live run binding (``active_run_id``);
- ``running_goal``: a Work run's goal is bound to one of its chats (``chat_goal.bindings``);
- ``default_realm_syncs``: the Default workspace's realm has a sync remote or a server (§6 rule 1 —
  adoption never places into a realm that publishes);
- ``no_default_workspace``: the Default workspace is missing or archived, or names no live realm;
- ``seat_refused``: the office refused the desk (an archived desk under the same key, a store fault).

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
    "LEFT_EMPTY",
    "SKIPPED",
    "WOULD_ADOPT",
    "adopt_global_rows",
    "adopted_local_instance_ids",
    "canonical_row_holdings",
]

ADOPTED = "adopted"
WOULD_ADOPT = "would_adopt"
LEFT_EMPTY = "left_empty"
SKIPPED = "skipped"

SKIP_MID_TURN = "mid_turn"
SKIP_RUNNING_GOAL = "running_goal"
SKIP_DEFAULT_REALM_SYNCS = "default_realm_syncs"
SKIP_NO_DEFAULT_WORKSPACE = "no_default_workspace"
SKIP_SEAT_REFUSED = "seat_refused"

_logger = logging.getLogger(__name__)


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
    instance: Any, *, moves: dict[str, str], gateway_bound: frozenset[str]
) -> list[str]:
    """What ``instance`` holds, as words: ``chat``, ``goal``, ``work``, ``slots``, ``gateway``."""

    held = []
    if _row_chats(instance, moves):
        held.append("chat")
    if getattr(instance, "goal_id", None) or getattr(instance, "current_chat_goal", None):
        held.append("goal")
    if getattr(instance, "current_assignment_id", None) or getattr(instance, "current_task_id", None):
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
    """Adopt every runtime-global row that holds anything; one fate per row, sorted by id.

    ``apply=False`` names each row's fate (``would_adopt``, ``skipped`` with its reason,
    ``left_empty``) and writes nothing. A second applied run finds nothing to do: an adopted
    row is no longer canonical. ``leaving`` names rows an earlier reconcile phase archives in
    this run: a dry run still lists them, so they are discounted here and the preview matches
    what an applied run does."""

    from .agent_create.seat import ALREADY_SEATED, SEATED, WOULD_SEAT, seat_added_instance
    from .persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
    from .persona_assignments.chat_moves import load_chat_moves

    store = store or PersonaInstanceStore()
    # MUTATION: drop the ``leaving`` test and test_the_dry_run_does_not_adopt_a_row_an_earlier_phase_archives reddens.
    rows = sorted(
        (i for i in store.list_all() if is_canonical_persona_channel(i) and i.id not in leaving), key=lambda i: i.id
    )
    if not rows:
        return []
    moves = load_chat_moves()
    gateway_bound = _gateway_bound_instance_ids()
    goal_roots = _running_goal_roots()
    workspace, realm, scope_refusal = _default_scope()
    stamp = today or now().date().isoformat()
    report: list[dict[str, Any]] = []
    for instance in rows:
        held = canonical_row_holdings(instance, moves=moves, gateway_bound=gateway_bound)
        entry: dict[str, Any] = {"persona_instance_id": instance.id, "persona_id": instance.persona_id, "holds": held}
        if not held:
            report.append({**entry, "fate": LEFT_EMPTY})
            continue
        reason = None
        if getattr(instance, "active_run_id", None):
            reason = SKIP_MID_TURN
        elif goal_roots.intersection(_row_chats(instance, moves)):
            reason = SKIP_RUNNING_GOAL
        else:
            reason = scope_refusal
        if reason is not None:
            report.append({**entry, "fate": SKIPPED, "reason": reason})
            continue
        adopted = replace(instance, workspace_id=workspace.id, realm_id=realm.id, adopted_from_global=stamp)
        # The desk first: a desk without the stamp is healed by the next run (``already_seated``);
        # a stamp without a desk would be a placed instance standing nowhere.
        seat = seat_added_instance(adopted, updated_by="harness", dry_run=not apply)
        if seat.reason not in {SEATED, WOULD_SEAT, ALREADY_SEATED}:
            report.append({**entry, "fate": SKIPPED, "reason": SKIP_SEAT_REFUSED, "seat": seat.receipt()})
            continue
        item = {**entry, "fate": ADOPTED if apply else WOULD_ADOPT, "workspace_id": workspace.id,
                "realm_id": realm.id, "adopted_from_global": stamp}
        report.append(item)
        if not apply:
            continue
        # Re-read and write only the three fields, so a rename or a model pick landing since the
        # listing is never reverted by this run.
        written = store.patch_fields(
            instance.id, workspace_id=workspace.id, realm_id=realm.id, adopted_from_global=stamp
        )
        store._event("persona_instance.reconciled", written, {**item, "action": ADOPTED})  # the reconciler IS store maintenance
    for item in report:
        _logger.info(
            "persona_instance_adoption instance=%s fate=%s reason=%s holds=%s",
            item["persona_instance_id"], item["fate"], item.get("reason"), ",".join(item["holds"]) or "-",
        )
    return report
