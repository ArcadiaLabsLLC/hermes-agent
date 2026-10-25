"""The Lens EXIT DOOR: an Episode owed its turn gets ONE forged chat turn, or a notification.

Plan ``p10-agent-2026-10-19.md`` §5.3 L2.4 (decisions §5.2: 1 target, 2 thread,
6 notify / investigate, 7 worker). The poller opens Episodes and never waits on
an agent; :class:`LensForge` runs on its own daemon thread beside it (started by
``hermes_cli/harness_parts/serve/session.py`` through :func:`start_lens_forge`)
and, every tick, admits each ACTIVE Episode that
:func:`~agent_runtime.lens.episode.needs_admission`.

:meth:`LensForge.admit` decides, in this order:

=====================  =============================================================
monitor not enabled    nothing written; the Episode stays owed (a paused monitor's
                       Episode forges when it is enabled again)
``when: urgent`` and   receipt ``skipped_severity``
a non-urgent rule
daily cap reached      receipt ``capped`` (``store.receipts_today``, per UTC day)
``level: notify``      receipt ``notified``; no turn
``level: investigate`` receipt ``forging`` -> the turn -> ``forged`` |
                       ``forge_failed:<reason>``
=====================  =============================================================

Every receipt is written in the SAME transaction that sets the Episode's
``turn_id`` (the client message id for a turn; the outcome's own name for the
rest), and BEFORE any turn runs, so a second admission — another tick, a restart,
a reentrant pass — finds the receipt and forges nothing.

The turn goes through the one mission-chat door
(:func:`agent_runtime.mission_chat_door.run_mission_chat_turn`), as a dispatch
delivery's does (``dispatch_delivery/forge.py::forge_delivery_turn``): a NEW chat
titled ``<monitor> · <rule> · #<n>``, under the manifest's ``persona_id``, with
Lens provenance (``lens/provenance.py``) and the Episode's idempotency key.

**Tool admission is read-only** (owner RULED 2026-10-22, ``RT-LENS-FORGED-TURN-TOOL-ADMISSION``):
nobody attends a forged turn, so the chat is minted FIRST — through the open-chat door, keyed by the
Episode — and held at ``read_only`` in the session-scoped permission store
(``tool_permissions.ChatToolPermissionStore``) before the turn runs on it; the turn's tool surface
then blocks every mutating tool (``READ_ONLY_BLOCKS``) and keeps the read-only ones, the lens tools
among them. The receipt says so (``tool_admission: read_only``); a receipt that ran no turn says
``none``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from typing import Any, Callable

from .artifacts import collect, episode_folder
from .episode import Episode, needs_admission
from .evidence import MAXIMUM_SPAN, EvidenceRefused, build_evidence
from .feed import Observation
from .manifest import AutomationLevel, AutomationWhen
from .provenance import lens_client_message_id, lens_requested_by
from .rules import Severity, rule_feed_ids
from .store import FORGE_FAILED_PREFIX, LensStore, MonitorState, ReceiptOutcome, from_ms, to_ms
from .tool import episode_title, opening_block

__layer__ = "lanes"

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0
TOOL_ADMISSION_READ_ONLY = "read_only"
#: A receipt that forged no turn (notified, capped, skipped, refused before the turn).
TOOL_ADMISSION_NONE = "none"
_PERMISSION_SOURCE = "lens"
#: The evidence window is halved this many times before the turn goes without it.
_EVIDENCE_SHRINKS = 12

Clock = Callable[[], datetime]
#: ``(manifest, episode, message) -> (ok, payload)`` — the turn, injectable for tests.
Forge = Callable[..., "tuple[bool, dict | None]"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _open_episode_chat(persona_id: str, episode: Episode) -> tuple[str | None, dict[str, Any]]:
    """Mint the Episode's own chat (never selected over the operator's), titled, held ``read_only``.

    ``(session_id, {})`` or ``(None, refusal payload)``. Keyed by the Episode, so a restart that finds the
    ``forging`` receipt and re-enters here answers the same root rather than a second one.
    """

    from ..persona_chat_durability import default_persona_session_db
    from ..persona_open_chat import perform_persona_instance_open_chat
    from ..tool_permissions import ChatToolPermissionStore
    from ..permission_modes import PERMISSION_MODE_READ_ONLY

    outcome = perform_persona_instance_open_chat({
        "persona_id": persona_id, "new_session": True,
        "idempotency_key": f"{lens_client_message_id(episode.id)}:chat",
        "requested_by": lens_requested_by(episode.id, episode.monitor_id),
    }, select_session=False)
    if outcome.refusal is not None:
        return None, {"ok": False, "error_kind": str((outcome.refusal.data or {}).get("reason") or "open_chat_refused")}
    session_id = str((outcome.result or {}).get("session_id") or "")
    if not session_id:
        return None, {"ok": False, "error_kind": "open_chat_refused"}
    ChatToolPermissionStore().set(persona_id=persona_id, session_id=session_id, mode=PERMISSION_MODE_READ_ONLY,
                                  reason=f"unattended Lens investigate turn ({episode.id})", source=_PERMISSION_SOURCE)
    session_db = default_persona_session_db()
    try:
        session_db.set_session_title(session_id, episode_title(episode))
    except Exception:  # a title is navigation, never a reason to skip the turn
        logger.debug("lens episode chat %s kept its default title", session_id, exc_info=True)
    finally:
        getattr(session_db, "close", lambda: None)()
    return session_id, {}


def forge_episode_turn(*, manifest: dict[str, Any], episode: Episode, message: str,
                       max_seconds: float | None = None) -> tuple[bool, dict[str, Any] | None]:
    """Run the Episode's turn as a real mission-chat turn in its own read-only chat. ``(ok, payload)``."""

    from ..config import mission_chat_default_max_seconds
    from ..mission_chat_door import run_mission_chat_turn

    # One new chat per Episode: a storm never splices into an operator's conversation.
    session_id, refused = _open_episode_chat(manifest["persona_id"], episode)
    if session_id is None:
        return False, refused
    args = SimpleNamespace(
        persona_id=manifest["persona_id"],
        persona_instance_id=None,
        session_id=session_id,
        clarify_token=None,
        new_session=False,
        task_id=None,
        goal_id=None,
        title=None,
        message=message,
        provider=None,
        model=None,
        use_agent_default=False,
        surface_prompt="",
        intent_hint="chat",
        requested_by=lens_requested_by(episode.id, episode.monitor_id),
        client_message_id=lens_client_message_id(episode.id),
        stream=False,
        max_seconds=float(max_seconds or mission_chat_default_max_seconds()),
        json=True,
        requested_by_session=None,
        relay_chain=[],
        relay_deadline_epoch=None,
    )
    exit_code, payload = run_mission_chat_turn(args)
    return exit_code == 0 and bool((payload or {}).get("ok")), payload


def _evidence(store: LensStore, manifest: dict[str, Any], rule: dict[str, Any], episode: Episode, now: datetime):
    """The rule's evidence window ending now, halved until it fits its byte budget (None if it never does)."""

    feeds = {feed["id"]: feed for feed in manifest["feeds"]}
    feed_ids = rule_feed_ids(rule)
    interval = max(timedelta(milliseconds=feeds[f]["interval_ms"]) for f in feed_ids)
    end = now + timedelta(milliseconds=1)
    span = min(MAXIMUM_SPAN, (now - episode.first_seen) + timedelta(milliseconds=rule["window_ms"])
               + interval * (rule["samples"] + 3))
    observations = [
        Observation(monitor_id=episode.monitor_id, feed_id=feed_id, sequence=row["sequence"],
                    observed_at=from_ms(row["observed_ms"]), received_at=from_ms(row["received_ms"]),
                    value=row["value"], gap=row["gap"])
        for feed_id in feed_ids
        for row in store.observations(episode.monitor_id, feed_id, start=end - span, end=end)
    ]
    for _ in range(_EVIDENCE_SHRINKS):
        try:
            return build_evidence(observations, monitor_id=episode.monitor_id, feed_ids=feed_ids,
                                  start=end - span, end=end)
        except EvidenceRefused as refused:
            if refused.code != "byte_budget":
                return None
            span /= 2
    return None


@dataclass
class LensForge:
    store_factory: Callable[[], LensStore] = LensStore
    clock: Clock = _utc_now
    forge: Forge = forge_episode_turn

    def tick(self) -> list[str]:
        """Admit every owed Episode once. Returns the outcomes written this pass."""

        store, now = self.store_factory(), self.clock()
        if not store.exists():
            return []
        outcomes = []
        for row in store.episodes(states=("active",)):
            episode = Episode.from_json(row)
            if needs_admission(episode, now):
                outcome = self.admit(store, episode, now)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def admit(self, store: LensStore, episode: Episode, now: datetime) -> str | None:
        """Settle one owed Episode (see the module table). None when nothing was written."""

        if store.has_receipt(episode.id):
            return None
        monitor = store.get(episode.monitor_id)
        if monitor["state"] != MonitorState.ENABLED.value or monitor["sealed"] is None:
            return None
        manifest = monitor["sealed"]["manifest"]
        automation = manifest["automation"]
        rule = next((r for r in manifest["rules"] if r["id"] == episode.rule_id), None)
        if rule is None:
            return self._settle(store, episode, now, f"{FORGE_FAILED_PREFIX}rule_not_in_revision")
        if automation["when"] == AutomationWhen.URGENT.value and rule["severity"] != Severity.URGENT.value:
            return self._settle(store, episode, now, ReceiptOutcome.SKIPPED_SEVERITY.value)
        if store.receipts_today(episode.monitor_id, now) >= automation["daily_turn_cap"]:
            return self._settle(store, episode, now, ReceiptOutcome.CAPPED.value)
        if automation["level"] == AutomationLevel.NOTIFY.value:
            return self._settle(store, episode, now, ReceiptOutcome.NOTIFIED.value)
        if manifest["persona_id"] is None:
            # A revision sealed before L2.6's guard: nobody to forge the turn for.
            return self._settle(store, episode, now, f"{FORGE_FAILED_PREFIX}persona_required")
        return self._forge(store, manifest, rule, episode, now)

    def _settle(self, store: LensStore, episode: Episode, now: datetime, outcome: str) -> str | None:
        """A receipt with no turn; the Episode's ``turn_id`` names the outcome so it is no longer owed."""

        receipt = {"episode_id": episode.id, "monitor_id": episode.monitor_id, "turn_id": outcome.split(":")[0],
                   "started_ms": to_ms(now), "finished_ms": to_ms(now), "outcome": outcome,
                   "tool_admission": TOOL_ADMISSION_NONE}
        saved = store.save_receipt(receipt, episode=replace(episode, turn_id=receipt["turn_id"]))
        return outcome if saved else None

    def _forge(self, store: LensStore, manifest: dict[str, Any], rule: dict[str, Any], episode: Episode,
               now: datetime) -> str | None:
        folder = episode_folder(episode.id)
        folder.mkdir(parents=True, exist_ok=True)
        evidence = _evidence(store, manifest, rule, episode, now)
        if evidence is None:
            return self._settle(store, episode, now, f"{FORGE_FAILED_PREFIX}evidence_refused")
        message = opening_block(manifest, episode, evidence, folder)
        turn_id = lens_client_message_id(episode.id)
        receipt = {"episode_id": episode.id, "monitor_id": episode.monitor_id, "turn_id": turn_id,
                   "started_ms": to_ms(now), "outcome": ReceiptOutcome.FORGING.value,
                   "tool_admission": TOOL_ADMISSION_READ_ONLY}
        # BEFORE the turn, with the Episode's turn_id, in one transaction: the once-only guarantee.
        if not store.save_receipt(receipt, episode=replace(episode, turn_id=turn_id)):
            return None
        payload: dict[str, Any] = {}
        try:
            ok, payload = self.forge(manifest=manifest, episode=episode, message=message)
            payload = payload or {}
            outcome = (ReceiptOutcome.FORGED.value if ok
                       else FORGE_FAILED_PREFIX + (str(payload.get("error_kind") or "") or "refused"))
        except Exception as exc:
            logger.warning("lens forge failed for episode %s", episode.id, exc_info=True)
            outcome = f"{FORGE_FAILED_PREFIX}{type(exc).__name__}"
        handles, files = collect(episode.id, payload.get("reply"))
        session_id = payload.get("session_id") or payload.get("chat_session_id")
        store.finish_receipt(episode.id, outcome=outcome, finished_ms=to_ms(self.clock()),
                             session_id=None if session_id is None else str(session_id),
                             artifact_handles=handles, files=files)
        return outcome

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.warning("lens forge pass failed", exc_info=True)
            stop_event.wait(TICK_SECONDS)


def start_lens_forge(*, stop_event: threading.Event) -> threading.Thread | None:
    """Start the exit door on a daemon thread beside the poller. None when Lens is not shipped."""

    from .poller import lens_shipped

    if not lens_shipped():
        return None
    thread = threading.Thread(target=LensForge().run, args=(stop_event,), name="harness-serve-lens-forge",
                              daemon=True)
    thread.start()
    return thread
