"""Native approval and speed policy for the Mission Chat conversation owner.

Approvals off-desktop (p10-messaging §2.5, M4): :data:`approval_notifiers` maps a chat root to the
callable a surface renders a pending approval with (the messaging bridge's approval cards). The
launcher reads the queue off the agent list's ``running_work`` section (``running_work.approval_presence``);
a notifier only adds a second place the same approval shows, and
both answer through ``operator_session_controls.respond_operator_approval``. Pinned by
``tests/agent_runtime/messaging/test_approval_cards.py``.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

from .session_control_store import SessionControlStore

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: The choices an operator may answer an approval with — the ONE list ``pending_session_approvals``
#: offers and ``respond_operator_approval`` accepts.
APPROVAL_CHOICES = ("once", "deny")

#: chat root -> ``cb(approval_data)``; read when an approval is raised, so a notifier registered
#: mid-turn is heard. Written only through :func:`register_approval_notifier` / ``unregister``.
approval_notifiers: dict[str, Callable[[dict], None]] = {}
_notifiers_lock = threading.Lock()


def register_approval_notifier(session_id: str, cb: Callable[[dict], None]) -> None:
    with _notifiers_lock:
        approval_notifiers[session_id] = cb


def unregister_approval_notifier(session_id: str, cb: Callable[[dict], None] | None = None) -> None:
    """Remove the root's notifier (only ``cb``'s, when given — a newer registration is kept)."""
    with _notifiers_lock:
        if cb is None or approval_notifiers.get(session_id) is cb:
            approval_notifiers.pop(session_id, None)


def _notify_root(session_id: str, data: dict) -> None:
    """The gateway notify callback of a root's turn: the root's notifier, if any. Never raises: a
    raising notify would make upstream deny the approval for every surface (``notify_failed``).

    Every turn of a chat root runs in the serve — a dispatched helper's too, since 2026-11-21 (row
    ``RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES``) — so the serve's own queue holds
    every request; the file relay that carried a dispatch child's requests (``approval_relay``)
    retired with the child.

    First, the stream is told (``running_work.approval_presence``): the approval rides the agent
    list's ``running_work`` section, so Eternia shows it without polling
    (RT-FU-A-PENDING-APPROVAL-ARRIVES-AS-AN-UPDATE)."""
    from .running_work.approval_presence import approval_raised

    # MUTATION: drop this call and test_a_turns_approval_reaches_the_running_work_section reddens.
    approval_raised(session_id, data)
    with _notifiers_lock:
        cb = approval_notifiers.get(session_id)
    if cb is None:
        return
    try:
        cb(dict(data))
    except Exception:
        logger.warning("the approval notifier of %s failed", session_id, exc_info=True)

APPROVAL_OPTIONS = (
    {"id": "manual", "label": "Ask", "description": "Ask before actions Hermes flags for approval."},
    {"id": "smart", "label": "Smart", "description": "Hermes reviews flagged actions and asks when uncertain."},
    {"id": "off", "label": "Off", "description": "Skip approval prompts. Tool restrictions and deny rules still apply."},
)
SPEED_OPTIONS = (
    {"id": "", "label": "Normal", "description": "Use standard processing."},
    {"id": "priority", "label": "Fast", "description": "Request faster processing. Additional usage or charges may apply."},
    {"id": "auto", "label": "Auto", "description": "Request fast processing during Hermes' window at each turn's start."},
    {"id": "cold", "label": "First turn", "description": "Request fast processing during a new conversation's first turn."},
)


def speed_options(provider, model, base_url=None, api_mode=None) -> list[dict]:
    from hermes_cli.models import normalize_provider, resolve_fast_mode_overrides

    if not provider or not model or not resolve_fast_mode_overrides(model, provider=provider, base_url=base_url):
        return []
    options = [dict(row) for row in SPEED_OPTIONS]
    from agent.fast_mode import CODEX_TIER_WORDS
    app_server = api_mode == "codex_app_server"
    unknown_codex_transport = normalize_provider(provider) == "openai-codex" and not api_mode
    ultrafast_transport = not unknown_codex_transport and (not app_server or "ultrafast" in CODEX_TIER_WORDS)
    if ultrafast_transport and resolve_fast_mode_overrides(model, provider=provider, base_url=base_url, tier="ultrafast"):
        options.insert(2, {"id": "ultrafast", "label": "Ultrafast",
                           "description": "Request this model's ultrafast tier. Higher usage or charges may apply."})
    return options


def resolved_session_controls(session_id: str, *, provider, model, base_url=None, api_mode=None) -> dict:
    from agent.fast_mode import parse_service_tier
    from hermes_cli.config import is_managed, load_config_readonly
    from .approval_surface_policy import approval_policy_mode, approval_policy_modes
    from tools.approval import is_approval_bypass_active_for_session

    config = load_config_readonly()
    saved = SessionControlStore().read(session_id)
    configured = approval_policy_mode()
    managed = is_managed()
    mode = configured if managed else saved.get("approval_mode", configured)
    known_options = {row["id"]: row for row in APPROVAL_OPTIONS}
    native_options = [known_options.get(value, {"id": value, "label": value.replace("_", " ").title(),
                      "description": "Use this native approval policy."}) for value in approval_policy_modes()]
    if mode not in {row["id"] for row in native_options}:
        raise ValueError("invalid stored approval policy")
    from .approval_surface_policy import scoped_approval_policy
    with scoped_approval_policy(mode):
        effective_mode = approval_policy_mode()
    approval_options = []
    for option in native_options:
        with scoped_approval_policy(option["id"]):
            if approval_policy_mode() == option["id"]:
                approval_options.append(option)
    # Upstream's reader also counts ``approvals.mode: off``; read it under a manual binding so a
    # policy of "off" stays a writable policy and only process/session YOLO reads as a bypass.
    with scoped_approval_policy("manual"):
        bypass = is_approval_bypass_active_for_session(session_id)
    profile_tier = parse_service_tier((config.get("agent") or {}).get("service_tier")) or ""
    requested = profile_tier if managed else saved.get("service_tier", profile_tier)
    options = speed_options(provider, model, base_url, api_mode)
    available = {row["id"] for row in options}
    tier = requested if requested in available else ""
    reported_mode = "off" if bypass else effective_mode
    approval_source = "conversation" if "approval_mode" in saved else "profile"
    if len(approval_options) < 2:
        approval_source = "runtime_policy"
    if managed:
        approval_source = "managed"
    if bypass:
        approval_source = "bypass"
    return {
        "scope": "conversation", "provider": provider, "model": model, "api_mode": api_mode,
        "approval": {"mode": reported_mode, "requested": mode,
                     "label": next((row["label"] for row in native_options if row["id"] == reported_mode), "Not reported"),
                     "source": approval_source,
                     "options": approval_options,
                     "writable": len(approval_options) > 1 and not bypass and not is_managed()},
        "speed": {"state": "supported" if options else "unsupported", "requested": requested,
                  "effective": tier, "source": "managed" if managed else "conversation" if "service_tier" in saved else "profile",
                  "options": options, "writable": not is_managed(), "delivered": None},
    }


def apply_session_speed(agent, controls: dict) -> None:
    from agent.fast_mode import STATIC_TIERS
    from hermes_cli.models import resolve_fast_mode_overrides

    tier = controls["speed"]["effective"]
    overrides = dict(getattr(agent, "request_overrides", None) or {})
    overrides.pop("service_tier", None)
    overrides.pop("speed", None)
    if tier in STATIC_TIERS:
        overrides.update(resolve_fast_mode_overrides(
            controls["model"], provider=controls["provider"], base_url=getattr(agent, "base_url", None), tier=tier) or {})
    agent.service_tier = tier or None
    agent.request_overrides = overrides


_CHOICE_LABELS = {"once": "Allow once", "deny": "Deny"}


def pending_session_approvals(session_id: str) -> list[dict]:
    from agent.redact import redact_sensitive_text
    from tools.approval import list_gateway_approvals

    # The serve's own queue holds every request of this chat, a dispatched helper turn's included.
    rows = list_gateway_approvals(session_id)
    return [{"id": row["request_id"],
             "command": redact_sensitive_text(str(row.get("command") or ""), force=True),
             "description": redact_sensitive_text(str(row.get("description") or "Approval required"), force=True),
             "choices": [{"id": choice, "label": _CHOICE_LABELS[choice]} for choice in APPROVAL_CHOICES]}
            for row in rows]


#: A dispatched helper's chat root -> the ROOT lead chat it acts for, as its latest turn found it.
#: Written by :func:`session_approval_scope` only: a dispatched turn records its root lead, any other
#: turn of that chat drops the entry, so a helper that dispatches in turn passes its own lead up the
#: chain (``A -> B -> C``: C answers to A) and a chat a person drives again is its own root. Bounded;
#: an evicted entry makes the requester its own lead (its chat's mode), never a looser one by design.
_dispatch_leads: dict[str, str] = {}
#: A dispatched turn in flight (its ``turn_key``) -> ``(helper root, human-wait seconds at its start)``:
#: what :func:`dispatched_person_wait_seconds` reads for the turn's budget clocks.
_dispatched_turns: dict[str, tuple[str, float]] = {}
_dispatch_lock = threading.Lock()
_DISPATCH_LEADS_MAX = 1024


@dataclass(frozen=True)
class TurnApprovalPolicy:
    """What governs one turn's flagged steps: its mode, whether a person-wait expires, the lead's
    deny globs and the chat whose policy it is (the lead's root for a dispatched turn)."""

    mode: str
    dispatched: bool = False
    lead_root: str = ""
    lead_deny: tuple[str, ...] = ()


def _lead_policy(lead_root: str) -> TurnApprovalPolicy | None:
    """The lead chat's policy, read from THIS install's own records, or None when this install does
    not hold that chat (a turn sent from another install keeps the helper's own policy).

    The mode is the lead chat's saved ``approval_mode``, else the lead profile's ``approvals.mode`` read in
    the lead's profile home; the lead profile's ``approvals.deny`` globs come with it. Nothing is read
    from the dispatch request but the chat id it names."""
    from .persona_assignments.lookups import chat_session_owner_persona

    owner = chat_session_owner_persona(lead_root)
    if owner is None:
        return None
    from .approval_surface_policy import approval_policy_mode
    from .profile_context import process_home_scope, resolve_persona_profile
    from .profile_home import get_hermes_head_home
    from .store import AgentStore
    from hermes_cli.config import load_config_readonly

    try:
        persona = AgentStore().get(owner[0])
    except Exception:
        logger.warning("the lead of %s is not in this install's roster; the helper keeps its own policy",
                       lead_root, exc_info=True)
        return None
    binding = resolve_persona_profile(persona)
    # A lead bound to no profile runs on the head home, not on the helper's profile home this turn holds.
    with process_home_scope(binding.profile_home or get_hermes_head_home()):
        profile_mode = approval_policy_mode()
        deny = (load_config_readonly().get("approvals") or {}).get("deny") or []
    mode = SessionControlStore().read(lead_root).get("approval_mode", profile_mode)
    return TurnApprovalPolicy(mode=mode, dispatched=True, lead_root=lead_root,
                              lead_deny=tuple(glob for glob in deny if isinstance(glob, str) and glob.strip()))


def turn_approval_policy(session_id: str, *, requested_by_session: str | None = None) -> TurnApprovalPolicy:
    """THE answer to "whose approval policy governs this turn" (row
    ``RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS``, owner 2026-11-22 "1 a / 2 keep").

    A managed install's policy wins for every turn. A turn another chat of this install dispatched
    (``requested_by_session``) follows the ROOT lead of its chain: that chat's mode, its profile's deny
    globs added to the helper's own, and a person-wait with no expiry. Any other turn: its own chat's
    saved mode, else its profile's. Never raises for a missing lead: the helper keeps its own policy."""
    from hermes_cli.config import is_managed

    from .approval_surface_policy import approval_policy_mode

    if is_managed():
        return TurnApprovalPolicy(mode=approval_policy_mode())
    requester = str(requested_by_session or "").strip()
    if requester and requester != session_id:
        with _dispatch_lock:
            lead_root = _dispatch_leads.get(requester, requester)
        try:
            lead = _lead_policy(lead_root)
        except Exception:
            logger.warning("the lead policy of %s was not read; the helper keeps its own", lead_root, exc_info=True)
            lead = None
        if lead is not None:
            return lead
    return TurnApprovalPolicy(mode=SessionControlStore().read(session_id).get("approval_mode", approval_policy_mode()))


def _record_turn_origin(session_id: str, policy: TurnApprovalPolicy) -> None:
    with _dispatch_lock:
        _dispatch_leads.pop(session_id, None)
        if policy.dispatched and policy.lead_root and policy.lead_root != session_id:
            while len(_dispatch_leads) >= _DISPATCH_LEADS_MAX:
                _dispatch_leads.pop(next(iter(_dispatch_leads)))
            _dispatch_leads[session_id] = policy.lead_root


def dispatched_person_wait_seconds(turn_key: str | None) -> float:
    """Seconds the dispatched turn ``turn_key`` has spent waiting on a person so far (0 for any other
    turn). Its budget clocks add them back, so a person-wait never ends a helper as over budget.

    Read under the no-expiry window the turn's own wait runs under, so upstream's per-window ceiling
    (``approvals.timeout`` + margin) cannot cut a long wait short from a supervisor's thread."""
    with _dispatch_lock:
        entry = _dispatched_turns.get(str(turn_key or ""))
    if entry is None:
        return 0.0
    from tools.approval_human_wait import human_wait_seconds

    from .approval_surface_policy import approval_policy_mode, scoped_approval_policy

    with scoped_approval_policy(approval_policy_mode(), wait_without_expiry=True):
        return max(0.0, human_wait_seconds(entry[0]) - entry[1])


@contextmanager
def session_approval_scope(session_id: str | None, *, requested_by_session: str | None = None,
                           turn_key: str | None = None):
    """Use Hermes' authoritative queue/wait/timeout lifecycle on this operator root.

    The queue is always this chat's own (a dispatched helper's card shows in its lead's chat through the
    dispatch thread binding); the POLICY is :func:`turn_approval_policy`'s. ``turn_key`` (the turn's
    ``client_message_id``) names a dispatched turn for :func:`dispatched_person_wait_seconds`."""
    if not session_id:
        yield
        return
    from tools.approval import register_gateway_notify, unregister_gateway_notify
    from tools.approval_context import reset_current_session_key, set_current_session_key
    from tools.approval_human_wait import human_wait_seconds

    from .approval_surface_policy import scoped_approval_policy

    policy = turn_approval_policy(session_id, requested_by_session=requested_by_session)
    _record_turn_origin(session_id, policy)
    token = set_current_session_key(session_id)
    # The existing queue is the replay authority, read by the attached console; a registered
    # notifier (approval cards, M4) is told as well.
    register_gateway_notify(session_id, lambda data: _notify_root(session_id, data))
    key = str(turn_key or "") if policy.dispatched else ""
    try:
        with scoped_approval_policy(policy.mode, gateway_session=True, wait_without_expiry=policy.dispatched,
                                    also_deny=policy.lead_deny):
            if key:
                baseline = human_wait_seconds(session_id)
                with _dispatch_lock:
                    _dispatched_turns[key] = (session_id, baseline)
            yield
    finally:
        if key:
            with _dispatch_lock:
                _dispatched_turns.pop(key, None)
        unregister_gateway_notify(session_id)
        reset_current_session_key(token)
