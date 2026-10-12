"""The serve's cron lane: upstream's in-process ticker, hosted by ``hermes harness serve``.

ADR 0015 step 1 (owner, 2026-10-12; audit ``upstream-capability-audit-2026-10-12.md`` §3, §8).
Upstream's cron ticker lives in the gateway process, which the Launcher never runs, so until
this lane a job a persona created was stored and never fired. The lane starts upstream's own
``InProcessCronScheduler`` on upstream's own ``SupervisedTickerThread``, multiplexed over every
profile home on this install (a persona's bound profile is a profile), with no delivery
adapters: upstream saves each run's output (``deliver=local``), and the persona chat that
created the job is woken through the serve's completion drain by :mod:`agent_runtime.cron_wake`.

Switch: ``cron.serve_ticker`` (default on). The phone bundle sets it off — no background ticker
on a phone, and the ``cron`` package is not packaged there, which is why every ``cron`` import
below is inside the function and ``ImportError``-guarded. Two tickers on one home never
double-fire: upstream's per-home tick lock (``cron.scheduler._acquire_tick_lock``) serialises a
serve beside a gateway.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: ``config.yaml`` key the lane reads through ``hermes_cli.config_switches.config_switch``.
SWITCH: tuple[str, str] = ("cron", "serve_ticker")

#: Seconds between ticks — upstream's gateway default.
DEFAULT_TICK_SECONDS = 60

OUTCOME_TICKING = "ticking"
OUTCOME_DISABLED = "disabled"
OUTCOME_UNAVAILABLE = "unavailable"


def serve_ticker_enabled() -> bool:
    """``cron.serve_ticker`` — on unless a bundle or an operator turned it off."""

    from hermes_cli.config_switches import config_switch

    return config_switch(*SWITCH, default=True)


def profile_homes() -> list[tuple[str, str]]:
    """``(name, home)`` for every live profile on this install, the multiplex ticker's input.

    Re-enumerated every cycle by the ticker (it is handed this callable, not its result), so
    a persona profile minted after boot is ticked without a restart. Never raises: a listing
    that fails ticks nothing this cycle and logs why."""

    try:
        from hermes_cli.profiles import get_profile_dir, list_profile_names

        return [(name, str(get_profile_dir(name))) for name in list_profile_names()]
    except Exception:  # noqa: BLE001 — a listing fault must not kill the ticker thread
        logger.debug("cron lane: profile enumeration failed; ticking nothing this cycle", exc_info=True)
        return []


def start_serve_cron_ticker(
    stop_event: threading.Event,
    *,
    interval: int = DEFAULT_TICK_SECONDS,
    can_dispatch: Callable[[], bool] | None = None,
) -> Any | None:
    """Start the ticker thread; ``None`` when the switch is off or ``cron`` is not packaged.

    ``can_dispatch`` is upstream's drain gate: while it answers False a tick leaves due jobs
    intact for the next allowed tick, which is how a draining serve stops starting runs
    without losing any. The returned handle is upstream's ``SupervisedTickerThread``
    (``is_alive`` / ``restart_if_dead``)."""

    if not serve_ticker_enabled():
        logger.info("cron lane: cron.serve_ticker is off; no ticker started")
        return None
    try:
        from cron.scheduler_provider import InProcessCronScheduler
        from cron.scheduler_thread import SupervisedTickerThread
    except ImportError:
        logger.info("cron lane: the cron package is not packaged in this bundle; no ticker started")
        return None
    scheduler = InProcessCronScheduler()
    handle = SupervisedTickerThread(
        scheduler.start,
        args=(stop_event,),
        kwargs={
            "adapters": None,
            "loop": None,
            "interval": int(interval),
            "can_dispatch": can_dispatch,
            "profile_homes": profile_homes,
        },
        stop_event=stop_event,
        name="serve-cron",
    )
    handle.start()
    logger.info("cron lane: in-process ticker started (interval=%ds, multiplexed over profile homes)", interval)
    return handle


def boot_serve_cron_lane(session: Any) -> None:
    """The serve's boot step (``BootPhases._boot_cron_lane``), on a session that carries
    ``liveness_stop`` (the stop event), ``drain_state`` (``None`` until a drain begins — the
    tick gate), ``cron_ticker`` (written here) and ``_service_log`` (the receipt sink).

    ``can_dispatch`` is the drain gate: once a drain has begun a tick starts no new run and
    leaves the due job for the next runtime. Never raises — a lane that cannot start logs
    ``error`` and the runtime still serves."""

    enabled = serve_ticker_enabled()
    session.cron_ticker = None
    if enabled:
        try:
            session.cron_ticker = start_serve_cron_ticker(
                session.liveness_stop, can_dispatch=lambda: session.drain_state is None
            )
        except Exception:  # noqa: BLE001 — never the reason a runtime fails to come up
            logger.warning("cron lane: ticker failed to start; the runtime serves without it", exc_info=True)
            session.cron_ticker = None
    session._service_log({"event": "cron_lane", **cron_lane_block(session.cron_ticker, enabled=enabled)})


def cron_lane_block(handle: Any | None, *, enabled: bool, interval: int = DEFAULT_TICK_SECONDS) -> dict[str, Any]:
    """The one-line receipt the serve logs for this lane (never a frame key)."""

    if handle is not None:
        return {"outcome": OUTCOME_TICKING, "interval_seconds": int(interval)}
    return {"outcome": OUTCOME_DISABLED if not enabled else OUTCOME_UNAVAILABLE}


__all__ = [
    "DEFAULT_TICK_SECONDS",
    "OUTCOME_DISABLED",
    "OUTCOME_TICKING",
    "OUTCOME_UNAVAILABLE",
    "SWITCH",
    "boot_serve_cron_lane",
    "cron_lane_block",
    "profile_homes",
    "serve_ticker_enabled",
    "start_serve_cron_ticker",
]
