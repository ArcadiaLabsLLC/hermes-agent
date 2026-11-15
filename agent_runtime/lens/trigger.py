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
``when: urgent`` and   receipt ``skipped_severity`` — except a feed's reserved
a non-urgent rule      ``source_broken:<feed_id>`` Episode (W1), settled ``notified``:
                       an urgent-only monitor never hides a broken source
daily cap reached      receipt ``capped`` (``store.receipts_today``, per UTC day)
global budget reached  receipt ``notified_over_budget`` (W6: an ``investigate`` turn past
                       the root config's ``agent_runtime.lens.daily_turn_budget`` turns,
                       all monitors, this UTC day — downgraded to a notify, never dropped);
                       also when the monitor's or all Lens's TOKENS today fill their daily
                       limit (``lens/budget.py``)
``level: notify``      receipt ``notified``; no turn
``level: investigate`` the RULES CHECK (``rules_check.py``, RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE):
                       the monitor's effective rules judge what fired; ``deny``, ``escalate``
                       or a failed check -> receipt ``notified_by_rules``, no turn (fail closed);
                       ``approve`` -> receipt ``forging`` -> the turn -> ``forged`` |
                       ``budget_spent`` | ``forge_failed:<reason>``. The verdict,
                       ``decided_by: rules`` and the check's tokens ride the receipt either way
``level: act``         as ``investigate`` (RT-LENS-ACT-LEVEL), but the chat is held at ``bounded``
                       and the act gate (``act.py``) judges every mutating call: listed, undoable
                       and approved by the rules runs; denied is refused; anything else is a
                       proposal for the owner. Receipt ``tool_admission: bounded``; each call an
                       action receipt (``store_actions.py``)
decided after the read receipt ``skipped_decided``, no turn: ``save_receipts`` re-checks
                       ``needs_admission`` on the STORED row (an operator dismiss/snooze
                       written between the door's read and its receipt transaction)
=====================  =============================================================

A SCHEDULED run (``schedule:run``, plan ``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md``
§2 decision 7) passes the cooldown and urgency screens — they govern breaches; the sealed schedule
is the operator's explicit ask and its spacing is its own cooldown — but the daily cap and the
global budget apply; it never joins a digest, and its opening block is
``tool.schedule_opening_block``.

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

**Token budget** (RT-LENS-INVESTIGATE-TOKEN-BUDGET, design ``planned/lens-act-and-safe-investigate.md``
§3): the turn runs with a :class:`~agent_runtime.turn_token_budget.TurnTokenBudget` armed for its
client message id — the Episode's token and call limits (``lens/budget.py``), never more tokens than
the monitor and all Lens have left today. At 80 % the model is told to write what it has; when the
next call would pass a limit the turn lands (receipt ``budget_spent``). What it spent is the
receipt's ``budget`` block and counts toward the day.

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
``none``. An ``act`` turn (RT-LENS-ACT-LEVEL) is held at ``bounded`` instead (``tool_admission: bounded``),
with its mutating calls gated one by one (``act.py``).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from typing import Any, Callable

from .artifacts import collect, episode_folder, write_reply_report
from .episode import ADMITTED_STATES, Episode, needs_admission
from .evidence import DEFAULT_MAXIMUM_BYTES, MAXIMUM_SPAN, EvidenceRefused, build_evidence
from .feed import Observation
from .manifest import TURN_LEVELS, AutomationLevel, AutomationWhen
from .provenance import lens_client_message_id, lens_requested_by
from .rules_check import RulesCheck, RulesVerdict, check_investigate, fired_values
from .rules import SCHEDULE_RULE_ID, Severity, is_scheduled, is_source_broken, manifest_rule, rule_feed_ids
from .store import FORGE_FAILED_PREFIX, LensStore, MonitorState, ReceiptOutcome, from_ms, to_ms
from .tool import digest_opening_block, episode_title, opening_block, schedule_opening_block

__layer__ = "lanes"

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0
TOOL_ADMISSION_READ_ONLY = "read_only"
#: An ``act`` turn's chat: mutating tools reachable, each call judged by the act gate (``act.py``).
TOOL_ADMISSION_BOUNDED = "bounded"
#: A receipt that forged no turn (notified, capped, skipped, refused before the turn).
TOOL_ADMISSION_NONE = "none"
_PERMISSION_SOURCE = "lens"
#: The evidence window is halved this many times before the turn goes without it.
_EVIDENCE_SHRINKS = 12

Clock = Callable[[], datetime]
#: ``(manifest, episode, message) -> (ok, payload)`` — the turn, injectable for tests.
Forge = Callable[..., "tuple[bool, dict | None]"]
#: ``(guidance=, monitor_name=, fired=, turns_left_today=) -> RulesCheck`` — the rules check, injectable for tests.
Check = Callable[..., RulesCheck]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _operator_client_scope(persona_id: str) -> str | None:
    """The client scope the operator's chat with *persona_id* records, or ``None`` (RT-LENS-ALERT-CHAT-NO-CLIENT-SCOPE).

    An Episode's chat is minted by no client, so it carried no ``client_scope`` and a scoped operator
    client's conversation directory never listed it: Eternia's Lens receipt "Open chat" could not open
    it. The operator who reads this persona's Episodes is the client that owns the persona's canonical
    instance's current chat (its ``default_chat_session_id``); the Episode chat is stamped with that
    owner. No current chat, an unscoped one, or any read failure: ``None``, minted unscoped as before.
    """

    from ..persona_assignments import PersonaInstanceStore, persona_instance_id_for
    from ..persona_chat_history.messages import existing_chat_session

    try:
        instance = PersonaInstanceStore().get(persona_instance_id_for(persona_id))
        session_id = str(getattr(instance, "default_chat_session_id", None) or "")
        if not session_id:
            return None
        with existing_chat_session(session_id=session_id) as session:
            return session.owner
    except Exception:  # the scope is a listing courtesy: a failed read never blocks the Episode
        logger.debug("lens: no operator client scope for %s", persona_id, exc_info=True)
        return None


def _monitor_client_scope(monitor_id: str) -> str | None:
    """The account that sealed the monitor (RT-LENS-EPISODE-CHAT-OWNED-BY-THE-MONITORS-ACCOUNT), or
    ``None``: a monitor sealed before it, or by an unscoped operator, falls back to the borrow."""

    from .store_owner import monitor_client_scope

    try:
        return monitor_client_scope(monitor_id)
    except Exception:  # a listing courtesy, as the borrow is: a failed read never blocks the Episode
        logger.debug("lens: no recorded owner for monitor %s", monitor_id, exc_info=True)
        return None


def _open_episode_chat(persona_id: str, episode: Episode, turn_key: str, mode: str | None = None
                       ) -> tuple[str | None, dict[str, Any]]:
    """Mint the Episode's own chat (never selected over the operator's), titled, held ``read_only``
    (``bounded`` for an ``act`` turn, whose mutating calls the act gate judges one by one).

    ``(session_id, {})`` or ``(None, refusal payload)``. Keyed by the Episode, so a restart that finds the
    ``forging`` receipt and re-enters here answers the same root rather than a second one.
    """

    from ..persona_open_chat import perform_persona_instance_open_chat
    from ..tool_permissions import ChatToolPermissionStore
    from ..permission_modes import PERMISSION_MODE_READ_ONLY

    # Titled BY the mint (one door), never re-titled after it; owned by the account that sealed the
    # monitor, else the operator's current-chat client, so its conversation directory lists it
    # (RT-LENS-EPISODE-CHAT-OWNED-BY-THE-MONITORS-ACCOUNT, RT-LENS-ALERT-CHAT-NO-CLIENT-SCOPE).
    owner = _monitor_client_scope(episode.monitor_id) or _operator_client_scope(persona_id)
    outcome = perform_persona_instance_open_chat({
        "persona_id": persona_id, "new_session": True,
        "idempotency_key": f"{lens_client_message_id(turn_key)}:chat",
        "requested_by": lens_requested_by(episode.id, episode.monitor_id),
        "title": episode_title(episode),
        **({"client_scope": owner} if owner is not None else {}),
    }, select_session=False)
    if outcome.refusal is not None:
        return None, {"ok": False, "error_kind": str((outcome.refusal.data or {}).get("reason") or "open_chat_refused")}
    session_id = str((outcome.result or {}).get("session_id") or "")
    if not session_id:
        return None, {"ok": False, "error_kind": "open_chat_refused"}
    ChatToolPermissionStore().set(persona_id=persona_id, session_id=session_id, mode=mode or PERMISSION_MODE_READ_ONLY,
                                  reason=f"unattended Lens turn ({episode.id})", source=_PERMISSION_SOURCE)
    return session_id, {}


def forge_episode_turn(*, manifest: dict[str, Any], episode: Episode, message: str,
                       max_seconds: float | None = None, turn_key: str | None = None,
                       permission_mode: str | None = None, session_id: str | None = None,
                       client_message_id: str | None = None) -> tuple[bool, dict[str, Any] | None]:
    """Run the Episode's turn as a real mission-chat turn in its own read-only chat. ``(ok, payload)``.

    ``turn_key`` names the turn when it is not the Episode's own: a digest's ``digest_id`` (W6);
    ``permission_mode`` holds the chat at ``bounded`` for an ``act`` turn (default ``read_only``);
    ``session_id`` runs it in the Episode's EXISTING chat (an approved proposal's follow-up), under
    ``client_message_id``, instead of minting one."""

    from ..config import mission_chat_default_max_seconds
    from ..mission_chat_door import run_mission_chat_turn

    # One new chat per Episode: a storm never splices into an operator's conversation.
    key = turn_key or episode.id
    if session_id is None:
        session_id, refused = _open_episode_chat(manifest["persona_id"], episode, key, permission_mode)
        if session_id is None:
            return False, refused
    else:
        from ..tool_permissions import ChatToolPermissionStore

        ChatToolPermissionStore().set(persona_id=manifest["persona_id"], session_id=session_id,
                                      mode=permission_mode or TOOL_ADMISSION_READ_ONLY,
                                      reason=f"unattended Lens follow-up turn ({episode.id})", source=_PERMISSION_SOURCE)
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
        client_message_id=client_message_id or lens_client_message_id(key),
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


def _shapes(store: LensStore, rule: dict[str, Any], episode: Episode) -> dict[str, Any] | None:
    """A ``source_broken`` Episode's two skeletons, known-good and newest different (W1); else None."""

    from .store_shapes import feed_shape

    if not is_source_broken(rule):
        return None
    row = feed_shape(store, episode.monitor_id, rule["feed_id"]) or {}
    return {name: None if row.get(column) is None else json.loads(row[column])
            for name, column in (("known_good", "good_skeleton"), ("newest", "other_skeleton"))}


def _notes(store: LensStore, rule: dict[str, Any], episode: Episode) -> dict[str, Any]:
    """What the opening block says beyond the evidence: a missed outage (W8), a broken source's shapes (W1)."""

    return {"offline": _offline(store, rule, episode), "shapes": _shapes(store, rule, episode)}


def _cooling(store: LensStore, episode: Episode, now: datetime, cooldown_ms: int) -> bool:
    """True when the rule's previous counted receipt started less than ``cooldown_ms`` ago (W6)."""

    from .store_admission import last_rule_receipt_ms

    if cooldown_ms <= 0:
        return False
    previous = last_rule_receipt_ms(store, episode.monitor_id, episode.rule_id)
    return previous is not None and to_ms(now) - previous < cooldown_ms


def _over_daily_tokens(store: LensStore, monitor_id: str, now: datetime) -> bool:
    """True when the monitor's or all Lens's tokens today fill their daily limit (``lens/budget.py``)."""

    from .budget import over_daily_tokens

    return over_daily_tokens(store, monitor_id, now)


def _over_budget(store: LensStore, now: datetime) -> bool:
    """True when the turns every monitor began today already fill the global budget (W6)."""

    from .budget import lens_limits
    from .store_admission import turns_today

    # The owner's edited value (``runtime.lens.budget.set``, scope lens), else the root config's.
    return turns_today(store, now) >= lens_limits(store)["daily_turns"]["value"]


@dataclass
class LensForge:
    store_factory: Callable[[], LensStore] = LensStore
    clock: Clock = _utc_now
    forge: Forge = forge_episode_turn
    check: Check = check_investigate

    def tick(self) -> list[str]:
        """Admit every owed Episode once. Returns the outcomes written this pass."""

        store, now = self.store_factory(), self.clock()
        if not store.exists():
            return []
        outcomes = self._proposals(store, now)
        for row in store.episodes(states=tuple(state.value for state in sorted(ADMITTED_STATES))):
            episode = Episode.from_json(row)
            if needs_admission(episode, now):
                outcome = self.admit(store, episode, now)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def _proposals(self, store: LensStore, now: datetime) -> list[str]:
        """Expire proposals unanswered for a day; run each approved one's follow-up turn, once."""

        from .store_actions import claim_follow_ups, expire_proposals

        expired = expire_proposals(store, to_ms(now))
        outcomes = ["proposal_expired"] * expired
        for proposal in claim_follow_ups(store):
            outcomes.append(self._follow_up(store, proposal, now))
        return outcomes

    def _follow_up(self, store: LensStore, proposal: dict[str, Any], now: datetime) -> str:
        """ONE turn in the Episode's chat with the approved call pre-admitted (design §4); the rest of the
        turn is judged like any act turn. Its spend adds to the Episode's."""

        from ..turn_token_budget import TurnTokenBudget, armed_turn_budget
        from .act import ActTurn, armed_act_turn
        from .budget import add_spend, episode_limits
        from .guidance import effective_guidance

        episode_id, monitor_id = proposal["episode_id"], proposal["monitor_id"]
        try:
            monitor = store.get(monitor_id)
            manifest = monitor["sealed"]["manifest"]
            from .store_episode_rows import episode_body

            with store.connection() as conn:
                body = episode_body(conn, episode_id)
            if body is None:
                return "follow_up_failed:episode_not_found"
            episode = Episode.from_json(json.loads(body))
            session_id = store.receipt(episode_id).get("session_id")
            if not session_id:
                return "follow_up_failed:episode_has_no_chat"
            arguments = proposal["arguments"] or {}
            message = (f"[LENS APPROVED ACTION — {episode_title(episode)}]\n"
                       f"The owner approved the action this Episode proposed: run `{proposal['tool']}` once, with "
                       "exactly these arguments, then say in one or two sentences what it did. No operator typed "
                       "this message; Lens wrote it from the owner's approval.\n"
                       + json.dumps(arguments, sort_keys=True, ensure_ascii=False).replace("<", "\\u003c"))
            token_limit, call_limit = episode_limits(store, monitor_id, now)
            budget = TurnTokenBudget(token_limit=token_limit, call_limit=call_limit)
            rules = effective_guidance(store, manifest, monitor.get("workspace_id"))
            turn = ActTurn(episode_id=episode_id, monitor_id=monitor_id, turn_id=proposal["follow_up_turn_id"],
                           actions=frozenset(manifest["automation"].get("actions", [])), guidance=rules["text"],
                           episode={"episode_id": episode_id, "rule_id": episode.rule_id, "count": episode.count,
                                    "approved_by_owner": proposal["action_id"]},
                           budget=budget, store_factory=self.store_factory, clock=self.clock,
                           preadmitted=(proposal["tool"], proposal["arguments_digest"]))
            with armed_turn_budget(turn.turn_id, budget), armed_act_turn(turn):
                ok, _ = self.forge(manifest=manifest, episode=episode, message=message,
                                   permission_mode=TOOL_ADMISSION_BOUNDED, session_id=str(session_id),
                                   client_message_id=turn.turn_id)
            add_spend(store, episode_id=episode_id, monitor_id=monitor_id, started_ms=to_ms(now),
                      summary=budget.summary())
            return "follow_up_forged" if ok else "follow_up_failed:refused"
        except Exception as exc:
            logger.warning("lens follow-up failed for proposal %s", proposal.get("action_id"), exc_info=True)
            return f"follow_up_failed:{type(exc).__name__}"

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
        if manifest["automation"].get("digest_window_ms", 0) > 0 and episode.rule_id != SCHEDULE_RULE_ID:
            return self._digest(store, manifest, episode, now)
        outcome = self._admission(store, manifest, episode, now)
        if outcome is not None:
            return self._settle(store, episode, now, outcome)
        return self._forge(store, manifest, [episode], now)

    def _screen(self, store: LensStore, manifest: dict[str, Any], episode: Episode, now: datetime) -> str | None:
        """The outcomes that settle ONE Episode on its own facts — before any digest or cap."""

        automation = manifest["automation"]
        rule = manifest_rule(manifest, episode.rule_id)
        if rule is None:
            return f"{FORGE_FAILED_PREFIX}rule_not_in_revision"
        if is_scheduled(rule):
            return None  # the operator's sealed ask: no cooldown, no urgency filter (cap and budget still apply)
        if _cooling(store, episode, now, automation.get("cooldown_ms", 0)):
            return ReceiptOutcome.COOLED.value
        if automation["when"] == AutomationWhen.URGENT.value and rule["severity"] != Severity.URGENT.value:
            # W1 decision 6: a broken source is shown, never skipped, under an urgent-only filter.
            return ReceiptOutcome.NOTIFIED.value if is_source_broken(rule) else ReceiptOutcome.SKIPPED_SEVERITY.value
        return None

    def _admission(self, store: LensStore, manifest: dict[str, Any], episode: Episode, now: datetime) -> str | None:
        """What a screened Episode (or digest) is owed: an outcome with no turn, or None — forge."""

        automation = manifest["automation"]
        if store.receipts_today(episode.monitor_id, now) >= automation["daily_turn_cap"]:
            return ReceiptOutcome.CAPPED.value
        if automation["level"] in TURN_LEVELS and (
                _over_budget(store, now) or _over_daily_tokens(store, episode.monitor_id, now)):
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
        # A scheduled run is never a digest member: merging a standing ask into an alert mixes two instructions.
        return [other for other in owed
                if other.id != episode.id and other.rule_id != SCHEDULE_RULE_ID and needs_admission(other, now)
                and not store.has_receipt(other.id)]

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
            rule = manifest_rule(manifest, member.rule_id)
            evidence = _evidence(store, manifest, rule, member, now, maximum_bytes=budget)
            if evidence is None:
                return self._refuse(store, members, now, digest, close)
            windows.append((member, evidence))
        notes = {member.id: _notes(store, manifest_rule(manifest, member.rule_id), member) for member in members}
        if digest is None and leader.rule_id == SCHEDULE_RULE_ID:
            from .schedules import previous_run_ms

            message = schedule_opening_block(manifest, leader, windows[0][1], folder,
                                             previous_ms=previous_run_ms(store, leader))
        elif digest is None:
            message = opening_block(manifest, leader, windows[0][1], folder, **notes[leader.id])
        else:
            message = digest_opening_block(manifest, windows, folder, notes=notes)
        checked = self._rules_check(store, manifest, windows, now)
        if not checked.allows:
            return self._notify_by_rules(store, members, now, digest, close, checked)
        acts = manifest["automation"]["level"] == AutomationLevel.ACT.value
        admission = TOOL_ADMISSION_BOUNDED if acts else TOOL_ADMISSION_READ_ONLY
        if acts:
            from .tool import READ_ONLY_CLOSING, act_closing

            message = message.replace(READ_ONLY_CLOSING, act_closing(manifest["automation"].get("actions", [])))
        turn_key = leader.id if digest is None else digest
        turn_id = lens_client_message_id(turn_key)
        pairs = [self._digest_receipt(member, now, digest,
                                      ReceiptOutcome.FORGING.value if i == 0 else ReceiptOutcome.DIGESTED.value,
                                      turn_id, admission) for i, member in enumerate(members)]
        pairs[0][0].update(checked.receipt_fields())
        # BEFORE the turn, with every Episode's turn_id, in one transaction: the once-only guarantee.
        if not store.save_receipts(pairs, also=close):
            return None
        payload: dict[str, Any] = {}
        turn: dict[str, Any] = {} if digest is None else {"turn_key": digest}
        if acts:
            turn["permission_mode"] = TOOL_ADMISSION_BOUNDED
        from ..turn_token_budget import TurnTokenBudget, armed_turn_budget
        from .budget import episode_limits, record_spend

        token_limit, call_limit = episode_limits(store, leader.monitor_id, now)
        budget = TurnTokenBudget(token_limit=token_limit, call_limit=call_limit)
        budget.charge(checked.tokens or 0)  # the rules check is the Episode's first spend (design §2)
        try:
            # Armed for THIS turn's client message id: every provider call of the turn is counted and the
            # turn lands when the next call would pass a limit (``turn_token_budget``).
            with armed_turn_budget(turn_id, budget), self._armed_act(store, manifest, windows, notes, turn_id,
                                                                     budget, acts):
                ok, payload = self.forge(manifest=manifest, episode=leader, message=message, **turn)
            payload = payload or {}
            if not ok:
                outcome = FORGE_FAILED_PREFIX + (str(payload.get("error_kind") or "") or "refused")
            else:  # a turn that landed on its budget says so; its reply so far is still the report
                outcome = ReceiptOutcome.BUDGET_SPENT.value if budget.stopped_by else ReceiptOutcome.FORGED.value
        except Exception as exc:
            logger.warning("lens forge failed for episode %s", leader.id, exc_info=True)
            outcome = f"{FORGE_FAILED_PREFIX}{type(exc).__name__}"
        record_spend(store, episode_id=leader.id, monitor_id=leader.monitor_id, started_ms=to_ms(now),
                     summary=budget.summary())
        # The turn is read-only: its reply IS the report, written by the door before the folder is listed.
        write_reply_report(leader.id, payload.get("reply"))
        handles, files = collect(leader.id, payload.get("reply"))
        session_id = payload.get("session_id") or payload.get("chat_session_id")
        store.finish_receipt(leader.id, outcome=outcome, finished_ms=to_ms(self.clock()),
                             session_id=None if session_id is None else str(session_id),
                             artifact_handles=handles, files=files)
        return outcome

    def _armed_act(self, store: LensStore, manifest: dict[str, Any], windows: list, notes: dict[str, Any],
                   turn_id: str, budget: Any, acts: bool):
        """An ``act`` turn's gate, armed for its client message id (``act.py``); a null context otherwise."""

        from contextlib import nullcontext

        if not acts:
            return nullcontext()
        from .act import ActTurn, armed_act_turn
        from .guidance import effective_guidance

        leader = windows[0][0]
        rules = effective_guidance(store, manifest, store.get(leader.monitor_id).get("workspace_id"))
        # W9: source-controlled text in the opening block (a broken source's shapes) means no action alone.
        free_text = any((notes.get(member.id) or {}).get("shapes") is not None for member, _ in windows)
        episode = {"episode_id": leader.id, "rule_id": leader.rule_id, "count": leader.count,
                   "members": len(windows)}
        return armed_act_turn(ActTurn(episode_id=leader.id, monitor_id=leader.monitor_id, turn_id=turn_id,
                                      actions=frozenset(manifest["automation"].get("actions", [])),
                                      guidance=rules["text"], episode=episode, free_text=free_text, budget=budget,
                                      store_factory=self.store_factory, clock=self.clock))

    def _rules_check(self, store: LensStore, manifest: dict[str, Any], windows: list, now: datetime) -> RulesCheck:
        """The monitor's effective rules judge what fired (design §2), before any turn is written."""

        from .guidance import effective_guidance
        from .settings import lens_setting
        from .store_admission import turns_today

        leader = windows[0][0]
        monitor_id = leader.monitor_id
        rules = effective_guidance(store, manifest, store.get(monitor_id).get("workspace_id"))
        left = {"monitor": max(0, manifest["automation"]["daily_turn_cap"] - store.receipts_today(monitor_id, now)),
                "all_lens": max(0, lens_setting("daily_turn_budget") - turns_today(store, now))}
        fired = [fired_values(manifest_rule(manifest, member.rule_id), member, evidence) for member, evidence in windows]
        try:
            return self.check(guidance=rules["text"], monitor_name=monitor_id, fired=fired, turns_left_today=left)
        except Exception:  # fail closed (owner decision 3): a check that cannot answer forges no turn
            logger.warning("lens rules check failed for episode %s", leader.id, exc_info=True)
            return RulesCheck(verdict=RulesVerdict.ESCALATE)

    def _notify_by_rules(self, store: LensStore, members: list[Episode], now: datetime, digest: str | None,
                         close: Callable[[Any], None] | None, checked: RulesCheck) -> str | None:
        """The rules said no (or were unsure): ``notified_by_rules`` with the verdict, and no turn."""

        outcome = ReceiptOutcome.NOTIFIED_BY_RULES.value
        pairs = [self._digest_receipt(member, now, digest, outcome if i == 0 else ReceiptOutcome.DIGESTED.value,
                                      outcome, TOOL_ADMISSION_NONE) for i, member in enumerate(members)]
        pairs[0][0].update(checked.receipt_fields())
        if not store.save_receipts(pairs, also=close):
            return None
        from .budget import record_spend

        # No turn, but the check spent tokens: they count toward the monitor's and all Lens's day.
        record_spend(store, episode_id=members[0].id, monitor_id=members[0].monitor_id, started_ms=to_ms(now),
                     summary={"tokens_used": checked.tokens or 0, "calls_used": 1})
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
