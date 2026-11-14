"""The messaging serve lane — the bridge runs inside the serve, with the Work engine (p10-messaging §3 M5).

Plan ``docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md`` §2.5–2.6. Owner RULED 2026-10-19:
v1 runs on the serve the OS scheduler starts (``harness serve --ndjson --service``, no ``--parent-pid``,
templates under ``docs/agent-runtime-harness/reference/service/``); no installer, no third bundle profile.

``queued_turns.start_serve_work_engine`` calls :func:`start_messaging_bridge` after the scheduler, on the
same executor. The lane is one daemon thread that RECONCILES each tick (and at once on :func:`poke`):

* a platform runs when ``messaging_enabled`` is true AND its bot token is present AND no drain has begun;
  otherwise it is ``off`` with a typed :class:`LaneReason` — a missing token is a state the status verb
  reports (``credential: absent``), never a raise;
* the drain (``session.drain_state`` set) stops POLLING at once — an update the poller still holds is
  dropped unhandled and unacknowledged, so the next serve receives it — while the settle listener stays
  registered, so a turn already queued still sends its reply; ``liveness_stop`` stops the bridge;
* ``runtime.messaging.platform.enable|disable`` write the setting and :func:`poke` the lane, which
  converges within one tick;
* a running platform's approval cards are refreshed every tick (``ApprovalCards.refresh``), so a root the
  launcher moved (``/new``) is watched without waiting for a platform message.

The transport is built from :data:`TRANSPORTS` (tests swap the row for a fake; never the network) — or,
when the harness setting ``messaging_telegram_transport`` is ``upstream``, from :data:`UPSTREAM_TRANSPORTS`:
upstream's own platform adapter behind ``upstream_adapter_transport`` (opt-in, off by default,
RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN). A bot has ONE poller, so a platform runs one or the
other, never both; a changed setting restarts the platform on the next tick. One
serve runs one lane: :func:`current` is how the verbs and ``status`` reach it. Receipts
(``work_store.receipts.emit``): ``messaging.lane`` on every state change — platform, state, reason.
Pinned by ``tests/agent_runtime/messaging/test_serve_lane.py``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..harness_settings import harness_setting
from ..work_store.receipts import emit
from . import credentials
from .models import Platform
from .transport import Transport, Update

__layer__ = "lanes"
__all__ = ["TICK_SECONDS", "TRANSPORTS", "TRANSPORT_SETTINGS", "UPSTREAM_TRANSPORTS", "LaneReason", "LaneState",
           "MessagingLane", "TransportKind", "current", "lane_state", "poke", "start_messaging_bridge",
           "transport_kind"]

logger = logging.getLogger(__name__)

TICK_SECONDS = 5.0
#: How often the thread looks at the drain and the stop between ticks (cheap attribute reads).
WATCH_SECONDS = 0.25


class LaneState(StrEnum):
    RUNNING = "running"
    OFF = "off"
    DRAINING = "draining"


class LaneReason(StrEnum):
    """Why a platform is not running — the ``reason`` of its lane state."""

    DISABLED = "disabled"
    CREDENTIAL_ABSENT = "credential_absent"
    DRAINING = "draining"
    START_FAILED = "start_failed"
    NOT_SERVING = "not_serving"


def _telegram(token: str) -> Transport:
    from .telegram_api import TelegramTransport

    return TelegramTransport(token)


#: platform -> transport factory over its bot token. The one construction path; tests replace a row.
TRANSPORTS: dict[Platform, Callable[[str], Transport]] = {Platform.TELEGRAM: _telegram}


class TransportKind(StrEnum):
    """Whose code talks to the platform: the fork's own transport, or upstream's adapter behind the shim."""

    FORK = "fork"
    UPSTREAM = "upstream"


#: platform -> the harness setting that picks its :class:`TransportKind` (absent or unknown = ``fork``).
TRANSPORT_SETTINGS: dict[Platform, str] = {Platform.TELEGRAM: "messaging_telegram_transport"}


def transport_kind(platform: Platform) -> TransportKind:
    """What the setting asks for. Anything but the exact word ``upstream`` is the fork's own transport."""
    name = TRANSPORT_SETTINGS.get(platform)
    value = harness_setting(name, TransportKind.FORK.value) if name else None
    wanted = str(value or "").strip().lower()
    if wanted == TransportKind.UPSTREAM.value and platform in UPSTREAM_TRANSPORTS:
        return TransportKind.UPSTREAM
    return TransportKind.FORK


def _refused_at_intake(platform: Platform) -> Callable[[str, str, str], None]:
    """What the bridge's ``_refuse`` does for a stranger, for a transport that refuses before the bridge."""
    from .models import Reason
    from .refused import RefusedSenders

    def record(user_id: str, chat_id: str, display: str) -> None:
        emit("messaging.refused", platform=platform.value, update_id=None, chat_id=chat_id, user_id=user_id,
             reason=Reason.UNKNOWN_OPERATOR.value)
        RefusedSenders().record(platform, user_id=user_id, display=display, chat_id=chat_id)
    return record


def _telegram_upstream(token: str, scope: Callable[[], Any], *, extra: dict[str, Any] | None = None) -> Transport:
    """Upstream's Telegram adapter as a plain pipe: no ``GatewayRunner``, the fork's operator list at its
    intake gate, its typing refresh off (the bridge sends its own)."""
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter

    from .approvals import CALLBACK_PREFIX
    from .operators import OperatorStore
    from .upstream_adapter_transport import TelegramUpstreamAdapterTransport

    adapter = TelegramAdapter(PlatformConfig(enabled=True, token=token, typing_indicator=False,
                                             extra=dict(extra or {})))  # ``extra``: a test's local Bot API
    return TelegramUpstreamAdapterTransport(
        adapter, press_prefix=CALLBACK_PREFIX, scope=scope,
        is_allowed=lambda user_id: OperatorStore().is_allowed(Platform.TELEGRAM, user_id),
        on_refused=_refused_at_intake(Platform.TELEGRAM))


#: platform -> factory of upstream's adapter behind the shim, over the bot token and the lane's home scope
#: (the sender gate runs on the adapter's thread). Tests replace a row.
UPSTREAM_TRANSPORTS: dict[Platform, Callable[[str, Callable[[], Any]], Transport]] = {
    Platform.TELEGRAM: _telegram_upstream}


@dataclass
class _Running:
    bridge: Any
    polling: bool = True
    kind: TransportKind = TransportKind.FORK


class MessagingLane:
    """Every platform's bridge on one serve, reconciled against the setting, the token and the drain."""

    def __init__(self, session: Any, *, tick_seconds: float = TICK_SECONDS) -> None:
        self.session = session
        self.tick_seconds = tick_seconds
        self.home = getattr(session, "serve_request_home", None)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._running: dict[Platform, _Running] = {}
        self._states: dict[Platform, tuple[LaneState, LaneReason | None]] = {}
        self.thread: threading.Thread | None = None

    # ── what the serve says ──

    def _draining(self) -> bool:
        return getattr(self.session, "drain_state", None) is not None

    def _stopped(self) -> bool:
        stop = getattr(self.session, "liveness_stop", None)
        return stop is not None and stop.is_set()

    def _wanted(self, platform: Platform) -> LaneReason | None:
        """None when the platform should run; else why not."""
        if self._draining():
            return LaneReason.DRAINING
        if harness_setting("messaging_enabled", False) is not True:
            return LaneReason.DISABLED
        if credentials.bot_token(platform) is None:
            return LaneReason.CREDENTIAL_ABSENT
        return None

    def _set(self, platform: Platform, state: LaneState, reason: LaneReason | None = None) -> None:
        if self._states.get(platform) != (state, reason):
            self._states[platform] = (state, reason)
            emit("messaging.lane", platform=platform.value, state=state.value,
                 reason=None if reason is None else reason.value)

    # ── one reconcile ──

    def tick(self) -> None:
        with self._lock:
            for platform in TRANSPORTS:
                try:
                    self._reconcile(platform)
                except Exception:
                    logger.warning("messaging lane tick failed for %s", platform.value, exc_info=True)

    def _reconcile(self, platform: Platform) -> None:
        running = self._running.get(platform)
        why_not = self._wanted(platform)
        if why_not is LaneReason.DRAINING:
            if running is not None and running.polling:
                running.polling = False
                running.bridge.transport.stop()
            self._set(platform, LaneState.DRAINING, LaneReason.DRAINING)
        elif why_not is not None:
            if running is not None:
                self._stop(platform)
            self._set(platform, LaneState.OFF, why_not)
        elif running is None:
            self._start(platform)
        elif running.kind is not transport_kind(platform):
            # The setting changed: one poller per bot, so the old transport stops before the new one starts.
            self._stop(platform)
            self._start(platform)
        elif running.bridge.approvals is not None:
            # A launcher ``/new`` moves an instance's chat root without a platform message; the next tick
            # re-points the approval notifiers at the CURRENT roots.
            running.bridge.approvals.refresh()

    def _start(self, platform: Platform) -> None:
        from .approvals import ApprovalCards
        from .bridge import MessagingBridge

        from ..work_store.engine import home_scope

        token = credentials.bot_token(platform)
        executor = self.session.work_executor
        kind = transport_kind(platform)
        try:
            if kind is TransportKind.UPSTREAM:
                transport = UPSTREAM_TRANSPORTS[platform](token or "", lambda: home_scope(self.home))
            else:
                transport = TRANSPORTS[platform](token or "")
            approvals = ApprovalCards(transport, executor, platform=platform)
            bridge = MessagingBridge(transport, executor, platform=platform, approvals=approvals)
            running = _Running(bridge, kind=kind)
            bridge.start(lambda update: self._inbound(running, update))
        except Exception as exc:
            logger.warning("messaging bridge for %s (%s transport) did not start: %s", platform.value, kind.value,
                           type(exc).__name__)
            self._set(platform, LaneState.OFF, LaneReason.START_FAILED)
            return
        self._running[platform] = running
        self._set(platform, LaneState.RUNNING)
        emit("messaging.transport", platform=platform.value, kind=kind.value)

    def _stop(self, platform: Platform) -> None:
        running = self._running.pop(platform, None)
        if running is not None:
            running.polling = False
            running.bridge.stop()

    def _inbound(self, running: _Running, update: Update) -> None:
        """The transport's callback: nothing is handled once the drain began or the platform stopped."""
        if not running.polling or self._draining():
            return
        from ..work_store.engine import home_scope

        with home_scope(self.home):
            running.bridge.inbound(update)

    # ── the thread ──

    def run(self) -> None:
        """Tick every ``tick_seconds``, at once on :meth:`poke` or when the drain begins; close on the stop."""
        from ..work_store.engine import home_scope

        # The first tick waits one interval (or a poke): the boot's own threads start first, and a config read
        # here would only compete with them for the GIL (measured: it moved the lens watcher's first tick).
        seen_drain, due = False, time.monotonic() + self.tick_seconds
        while not self._stopped():
            draining = self._draining()
            if self._wake.is_set() or draining != seen_drain or time.monotonic() >= due:
                self._wake.clear()
                seen_drain, due = draining, time.monotonic() + self.tick_seconds
                with home_scope(self.home):
                    self.tick()
            self._wake.wait(WATCH_SECONDS)
        self.close()

    def poke(self) -> None:
        self._wake.set()

    def close(self) -> None:
        with self._lock:
            for platform in list(self._running):
                self._stop(platform)
                self._set(platform, LaneState.OFF, LaneReason.NOT_SERVING)

    def state(self) -> dict[str, dict[str, str | None]]:
        # A copy, not the lock: a drain's transport stop may hold the lock for a whole long poll.
        return {p.value: {"state": s.value, "reason": None if r is None else r.value}
                for p, (s, r) in dict(self._states).items()}


_current: MessagingLane | None = None


def current() -> MessagingLane | None:
    """The lane this process's serve started, or None (a CLI, a test, a bundle without messaging)."""
    return _current


def start_messaging_bridge(session: Any, *, tick_seconds: float = TICK_SECONDS) -> MessagingLane:
    """Start the lane's thread on the serve (with the Work engine); its first tick runs one interval later, never at boot."""
    global _current
    lane = MessagingLane(session, tick_seconds=tick_seconds)
    lane.thread = threading.Thread(target=lane.run, name="messaging-serve-lane", daemon=True)
    _current = session.messaging_lane = lane
    lane.thread.start()
    return lane


def poke() -> None:
    lane = _current
    if lane is not None:
        lane.poke()


def lane_state(platform: Platform) -> dict[str, str | None]:
    """``{state, reason}`` of one platform on this process's serve; ``off`` / ``not_serving`` without one."""
    lane = _current
    default = {"state": LaneState.OFF.value, "reason": LaneReason.NOT_SERVING.value}
    return default if lane is None else lane.state().get(platform.value, default)
