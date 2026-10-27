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
rule not in revision   receipt ``forge_failed:rule_not_in_revision``
inside ``cooldown_ms`` receipt ``cooled`` (W6: the rule's previous receipt started
                       less than ``cooldown_ms`` ago; first, so it spends no cap)
``when: urgent`` and   receipt ``skipped_severity``
a non-urgent rule
daily cap reached      receipt ``capped`` (``store.receipts_today``, per UTC day)
global budget reached  receipt ``notified_over_budget`` (W6: an ``investigate`` turn past
                       the root config's ``agent_runtime.lens.daily_turn_budget`` turns,
                       all monitors, this UTC day — downgraded to a notify, never dropped)
``level: notify``      receipt ``notified``; no turn
``level: investigate`` receipt ``forging`` -> the turn -> ``forged`` |
                       ``forge_failed:<reason>``
=====================  =============================================================

W6 digest (``automation.digest_window_ms > 0``; plan ``LENS_EXTENSIONS_2026-10-27.md`` §3
decision 3): after the per-Episode screen (rule, cooldown, urgency) the monitor's first owed
Episode opens a window (``store_digests``); every Episode owed before it ends waits. At the
end the members are admitted TOGETHER past the cap, the budget and the level: ONE turn (or
one notify) under ``turn_id = lens_client_message_id(digest_id)``, the earliest member's
receipt carrying the outcome and every other's ``digested``, all written — and the window
closed — in one transaction before the turn. Each member's evidence gets an N-th of the
one byte budget.

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
from .episode import ADMITTED_STATES, Episode, needs_admission
from .evidence import DEFAULT_MAXIMUM_BYTES, MAXIMUM_SPAN, EvidenceRefused, build_evidence
from .feed import Observation
from .manifest import AutomationLevel, AutomationWhen
from .provenance import lens_client_message_id, lens_requested_by
from .rules import Severity, rule_feed_ids
from .store import FORGE_FAILED_PREFIX, LensStore, MonitorState, ReceiptOutcome, from_ms, to_ms
from .tool import digest_opening_block, episode_title, opening_block

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


def _open_episode_chat(persona_id: str, episode: Episode, turn_key: str) -> tuple[str | None, dict[str, Any]]:
    """Mint the Episode's own chat (never selected over the operator's), titled, held ``read_only``.

    ``(session_id, {})`` or ``(None, refusal payload)``. Keyed by the Episode, so a restart that finds the
    ``forging`` receipt and re-enters here answers the same root rather than a second one.
    """

    from ..persona_open_chat import perform_persona_instance_open_chat
    from ..tool_permissions import ChatToolPermissionStore
    from ..permission_modes import PERMISSION_MODE_READ_ONLY

    # Titled BY the mint (one door), never re-titled after it.
    outcome = perform_persona_instance_open_chat({
        "persona_id": persona_id, "new_session": True,
        "idempotency_key": f"{lens_client_message_id(turn_key)}:chat",
        "requested_by": lens_requested_by(episode.id, episode.monitor_id),
        "title": episode_title(episode),
    }, select_session=False)
    if outcome.refusal is not None:
        return None, {"ok": False, "error_kind": str((outcome.refusal.data or {}).get("reason") or "open_chat_refused")}
    session_id = str((outcome.result or {}).get("session_id") or "")
    if not session_id:
        return None, {"ok": False, "error_kind": "open_chat_refused"}
    ChatToolPermissionStore().set(persona_id=persona_id, session_id=session_id, mode=PERMISSION_MODE_READ_ONLY,
                                  reason=f"unattended Lens investigate turn ({episode.id})", source=_PERMISSION_SOURCE)
    return session_id, {}


def forge_episode_turn(*, manifest: dict[str, Any], episode: Episode, message: str,
                       max_seconds: float | None = None, turn_key: str | None = None
                       ) -> tuple[bool, dict[str, Any] | None]:
    """Run the Episode's turn as a real mission-chat turn in its own read-only chat. ``(ok, payload)``.

    ``turn_key`` names the turn when it is not the Episode's own: a digest's ``digest_id`` (W6)."""

    from ..config import mission_chat_default_max_seconds
    from ..mission_chat_door import run_mission_chat_turn

    # One new chat per Episode: a storm never splices into an operator's conversation.
    key = turn_key or episode.id
    session_id, refused = _open_episode_chat(manifest["persona_id"], episode, key)
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
        client_message_id=lens_client_message_id(key),
        stream=False,
        max_seconds=float(max_seconds or mission_chat_default_max_seconds()),
        json=True,
        requested_by_session=None,
        relay_chain=[],
        relay_deadline_epoch=None,
    )
    exit_code, payload = run_mission_chat_turn(args)
    return exit_code == 0 and bool((payload or {}).get("ok")), payload


def _evidence(store: LensStore, manifest: dict[str, Any], rule: dict[str, Any], episode: Episode, now: datetime,
              *, maximum_bytes: int = DEFAULT_MAXIMUM_BYTES):
    """The rule's evidence window ending now, halved until it fits ``maximum_bytes`` (None if it never does).
    A digest of N Episodes gives each one N-th of the budget, so the whole block keeps the one budget."""

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
                                  start=end - span, end=end, maximum_bytes=maximum_bytes)
        except EvidenceRefused as refused:
            if refused.code != "byte_budget":
                return None
            span /= 2
    return None


def _offline(store: LensStore, rule: dict[str, Any], episode: Episode) -> tuple[int, int] | None:
    """A ``missed`` Episode's outage, from the recorded rows (W8); None for every other Episode."""

    from .missed_deadlines import offline_interval

    if episode.missed_deadline_ms is None:
        return None
    return offline_interval(store, episode.monitor_id, rule["feed_id"], episode.missed_deadline_ms)


def _cooling(store: LensStore, episode: Episode, now: datetime, cooldown_ms: int) -> bool:
    """True when the rule's previous counted receipt started less than ``cooldown_ms`` ago (W6)."""

    from .store_admission import last_rule_receipt_ms

    if cooldown_ms <= 0:
        return False
    previous = last_rule_receipt_ms(store, episode.monitor_id, episode.rule_id)
    return previous is not None and to_ms(now) - previous < cooldown_ms


def _over_budget(store: LensStore, now: datetime) -> bool:
    """True when the turns every monitor began today already fill the global budget (W6)."""

    from .settings import lens_setting
    from .store_admission import turns_today

    return turns_today(store, now) >= lens_setting("daily_turn_budget")


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
        for row in store.episodes(states=tuple(state.value for state in sorted(ADMITTED_STATES))):
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
        screened = self._screen(store, manifest, episode, now)
        if screened is not None:
            return self._settle(store, episode, now, screened)
        if manifest["automation"].get("digest_window_ms", 0) > 0:
            return self._digest(store, manifest, episode, now)
        outcome = self._admission(store, manifest, episode, now)
        if outcome is not None:
            return self._settle(store, episode, now, outcome)
        return self._forge(store, manifest, [episode], now)

    def _screen(self, store: LensStore, manifest: dict[str, Any], episode: Episode, now: datetime) -> str | None:
        """The outcomes that settle ONE Episode on its own facts — before any digest or cap."""

        automation = manifest["automation"]
        rule = next((r for r in manifest["rules"] if r["id"] == episode.rule_id), None)
        if rule is None:
            return f"{FORGE_FAILED_PREFIX}rule_not_in_revision"
        if _cooling(store, episode, now, automation.get("cooldown_ms", 0)):
            return ReceiptOutcome.COOLED.value
        if automation["when"] == AutomationWhen.URGENT.value and rule["severity"] != Severity.URGENT.value:
            return ReceiptOutcome.SKIPPED_SEVERITY.value
        return None

    def _admission(self, store: LensStore, manifest: dict[str, Any], episode: Episode, now: datetime) -> str | None:
        """What a screened Episode (or digest) is owed: an outcome with no turn, or None — forge."""

        automation = manifest["automation"]
        if store.receipts_today(episode.monitor_id, now) >= automation["daily_turn_cap"]:
            return ReceiptOutcome.CAPPED.value
        if automation["level"] == AutomationLevel.INVESTIGATE.value and _over_budget(store, now):
            return ReceiptOutcome.NOTIFIED_OVER_BUDGET.value
        if automation["level"] == AutomationLevel.NOTIFY.value:
            return ReceiptOutcome.NOTIFIED.value
        if manifest["persona_id"] is None:
            # A revision sealed before L2.6's guard: nobody to forge the turn for.
            return f"{FORGE_FAILED_PREFIX}persona_required"
        return None

    def _settle(self, store: LensStore, episode: Episode, now: datetime, outcome: str) -> str | None:
        """A receipt with no turn; the Episode's ``turn_id`` names the outcome so it is no longer owed."""

        receipt = {"episode_id": episode.id, "monitor_id": episode.monitor_id, "turn_id": outcome.split(":")[0],
                   "started_ms": to_ms(now), "finished_ms": to_ms(now), "outcome": outcome,
                   "tool_admission": TOOL_ADMISSION_NONE}
        saved = store.save_receipt(receipt, episode=replace(episode, turn_id=receipt["turn_id"]))
        return outcome if saved else None

    def _digest(self, store: LensStore, manifest: dict[str, Any], episode: Episode, now: datetime) -> str | None:
        """W6 digest window: wait while it is open; at its end settle every member at once."""

        from .store_digests import close_window, digest_id, drop_window, open_window

        start = open_window(store, episode.monitor_id, to_ms(now))
        end = start + manifest["automation"]["digest_window_ms"]
        if to_ms(now) < end:
            return None
        members = []
        for candidate in [episode, *self._owed(store, episode, now)]:
            if to_ms(candidate.first_seen) >= end:
                continue  # owed after this window closed: it waits for the next one
            screened = None if candidate is episode else self._screen(store, manifest, candidate, now)
            if screened is not None:
                self._settle(store, candidate, now, screened)
            else:
                members.append(candidate)
        if not members:
            drop_window(store, episode.monitor_id)
            return None
        members.sort(key=lambda member: (member.first_seen, member.ordinal))
        digest = digest_id(episode.monitor_id, start)
        outcome = self._admission(store, manifest, members[0], now)
        if outcome is not None:
            pairs = [self._digest_receipt(member, now, digest, outcome if i == 0 else ReceiptOutcome.DIGESTED.value,
                                          outcome.split(":")[0], TOOL_ADMISSION_NONE)
                     for i, member in enumerate(members)]
            saved = store.save_receipts(pairs, also=close_window(episode.monitor_id))
            return outcome if saved else None
        return self._forge(store, manifest, members, now, digest=digest,
                           close=close_window(episode.monitor_id))

    def _owed(self, store: LensStore, episode: Episode, now: datetime) -> list[Episode]:
        """The monitor's other Episodes still owed their admission."""

        rows = store.episodes(monitor_id=episode.monitor_id,
                              states=tuple(state.value for state in sorted(ADMITTED_STATES)))
        owed = [Episode.from_json(row) for row in rows]
        return [other for other in owed
                if other.id != episode.id and needs_admission(other, now) and not store.has_receipt(other.id)]

    @staticmethod
    def _digest_receipt(member: Episode, now: datetime, digest: str | None, outcome: str, turn_id: str,
                        admission: str) -> tuple[dict[str, Any], Episode]:
        settled = outcome != ReceiptOutcome.FORGING.value
        receipt = {"episode_id": member.id, "monitor_id": member.monitor_id, "turn_id": turn_id,
                   "started_ms": to_ms(now), "finished_ms": to_ms(now) if settled else None, "outcome": outcome,
                   "tool_admission": admission, "digest_id": digest}
        return receipt, replace(member, turn_id=turn_id)

    def _forge(self, store: LensStore, manifest: dict[str, Any], members: list[Episode], now: datetime, *,
               digest: str | None = None, close: Callable[[Any], None] | None = None) -> str | None:
        """ONE turn for ``members`` (one Episode, or a digest's leader first), its receipts
        written before it runs in one transaction."""

        leader = members[0]
        folder = episode_folder(leader.id)
        folder.mkdir(parents=True, exist_ok=True)
        budget = DEFAULT_MAXIMUM_BYTES // len(members)
        windows = []
        for member in members:
            rule = next(r for r in manifest["rules"] if r["id"] == member.rule_id)
            evidence = _evidence(store, manifest, rule, member, now, maximum_bytes=budget)
            if evidence is None:
                return self._refuse(store, members, now, digest, close)
            windows.append((member, evidence))
        if digest is None:
            leader_rule = next(r for r in manifest["rules"] if r["id"] == leader.rule_id)
            message = opening_block(manifest, leader, windows[0][1], folder,
                                    offline=_offline(store, leader_rule, leader))
        else:
            message = digest_opening_block(manifest, windows, folder)
        turn_key = leader.id if digest is None else digest
        turn_id = lens_client_message_id(turn_key)
        pairs = [self._digest_receipt(member, now, digest,
                                      ReceiptOutcome.FORGING.value if i == 0 else ReceiptOutcome.DIGESTED.value,
                                      turn_id, TOOL_ADMISSION_READ_ONLY) for i, member in enumerate(members)]
        # BEFORE the turn, with every Episode's turn_id, in one transaction: the once-only guarantee.
        if not store.save_receipts(pairs, also=close):
            return None
        payload: dict[str, Any] = {}
        turn = {} if digest is None else {"turn_key": digest}
        try:
            ok, payload = self.forge(manifest=manifest, episode=leader, message=message, **turn)
            payload = payload or {}
            outcome = (ReceiptOutcome.FORGED.value if ok
                       else FORGE_FAILED_PREFIX + (str(payload.get("error_kind") or "") or "refused"))
        except Exception as exc:
            logger.warning("lens forge failed for episode %s", leader.id, exc_info=True)
            outcome = f"{FORGE_FAILED_PREFIX}{type(exc).__name__}"
        handles, files = collect(leader.id, payload.get("reply"))
        session_id = payload.get("session_id") or payload.get("chat_session_id")
        store.finish_receipt(leader.id, outcome=outcome, finished_ms=to_ms(self.clock()),
                             session_id=None if session_id is None else str(session_id),
                             artifact_handles=handles, files=files)
        return outcome

    def _refuse(self, store: LensStore, members: list[Episode], now: datetime, digest: str | None,
                close: Callable[[Any], None] | None) -> str | None:
        outcome = f"{FORGE_FAILED_PREFIX}evidence_refused"
        if digest is None:
            return self._settle(store, members[0], now, outcome)
        pairs = [self._digest_receipt(member, now, digest, outcome if i == 0 else ReceiptOutcome.DIGESTED.value,
                                      outcome.split(":")[0], TOOL_ADMISSION_NONE) for i, member in enumerate(members)]
        return outcome if store.save_receipts(pairs, also=close) else None

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
