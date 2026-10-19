"""The Lens poll door: a reader with a clock, under ``harness serve``.

Plan ``eternia-lens-in-hermes.md`` §3 (``poller.py``), stage L1. Started by the
serve that owns the home's socket (one writer over the store), stopped with the
serve's liveness event. It reads; it never schedules an agent (the exit door is
stage L2, and reads :func:`~agent_runtime.lens.episode.needs_admission`).

Each :meth:`LensPoller.tick` polls every due feed of every ENABLED monitor once:

* a read that answers records its number; a read that fails records a GAP — one
  gap row per failed poll, with the typed reason — and backs the feed off
  (interval x 2, x 4, capped at x 8) until it answers again;
* after each record, every rule on that feed is evaluated over its window and the
  rule's Episode moves (``episode.observe``);
* a feed the watcher could not see while the serve was down gets ONE
  ``watcher_offline`` gap at start (W8(a)): missed windows are gaps, never silence;
* a ``push`` feed is never read here (its ingress route writes it, L3): it is
  skipped by the tick, the offline catch-up and the deadline's confirming read;
* a read is typed by ``sources.typed_result`` with the feed's recent raw reads (the
  outlier window, kept in memory: a restart refills it, and the guard abstains
  until it is full) and the monitor's newest dated exchange rate (W2(c), W5);
* W7 adaptive cadence: while a monitor's ``ends_within`` deadline is ahead, every
  feed of that monitor is read at most ``remaining / 4`` apart (never under
  :data:`ADAPTIVE_FLOOR_MS`, never slower than its own interval); and a deadline
  rule the CLOCK would fire is first given a confirming read of its feed this
  tick, so an extended deadline never opens an Episode on a stale read.

The serve runs this on a daemon thread; the module keeps the watcher's state
(running / since / last tick) for the fold.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, UTC
from typing import Any, Callable

from .episode import EpisodeState, observe
from .feed import is_push_feed
from .rules import CLOCK_FORMS, RuleForm, evaluate, rule_feed_ids
from .sources import read_feed_source
from .sources.transport import ReadReason, ReadResult
from .store import LensStore, MonitorState, from_ms, to_ms

__layer__ = "lanes"

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0
MAXIMUM_BACKOFF = 8
RETENTION_EVERY = timedelta(minutes=10)
#: A feed whose newest row is older than this many intervals was not watched.
_OFFLINE_INTERVALS = 1.5
#: W7: near a deadline a feed is read at most ``remaining / ADAPTIVE_DIVISOR`` apart,
#: and never faster than the floor (the politeness bound a source is owed, W3).
ADAPTIVE_DIVISOR = 4
ADAPTIVE_FLOOR_MS = 5000

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _FeedClock:
    last_read: datetime | None = None
    failures: int = 0
    #: The feed's recent raw reads, refused ones included (the outlier window).
    recent: deque = field(default_factory=lambda: deque(maxlen=64))

    def period(self, feed: dict[str, Any], deadline: datetime | None) -> timedelta:
        """The wait after the last read: backoff while failing, else the adaptive cadence
        (a quarter of the time the last read had left before ``deadline``)."""

        interval = timedelta(milliseconds=feed["interval_ms"])
        if self.failures:
            return interval * min(2 ** (self.failures - 1), MAXIMUM_BACKOFF)
        deadline_in = None if deadline is None or self.last_read is None else deadline - self.last_read
        if deadline_in is None or deadline_in <= timedelta(0):
            return interval
        floor = timedelta(milliseconds=ADAPTIVE_FLOOR_MS)
        return min(interval, max(floor, deadline_in / ADAPTIVE_DIVISOR))


@dataclass
class WatcherState:
    running: bool = False
    since: datetime | None = None
    last_tick: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        def _at(moment: datetime | None) -> int | None:
            return None if moment is None else to_ms(moment)

        return {"running": self.running, "since_ms": _at(self.since), "last_tick_ms": _at(self.last_tick)}


WATCHER = WatcherState()


@dataclass
class LensPoller:
    store_factory: Callable[[], LensStore] = LensStore
    clock: Clock = _utc_now
    client: Any = None
    resolver: Any = None
    _clocks: dict[tuple[str, str], _FeedClock] = field(default_factory=dict)
    _last_retention: datetime | None = None

    # --- one pass -------------------------------------------------------------

    def catch_up(self) -> int:
        """Record one ``watcher_offline`` gap per enabled feed that went unwatched."""

        store, now, recorded = self.store_factory(), self.clock(), 0
        for monitor_id, manifest in self._enabled(store):
            for feed in manifest["feeds"]:
                if is_push_feed(feed):
                    continue
                latest = store.latest(monitor_id, feed["id"])
                horizon = timedelta(milliseconds=feed["interval_ms"] * _OFFLINE_INTERVALS)
                if latest is not None and now - from_ms(latest["observed_ms"]) > horizon:
                    store.record(monitor_id, feed["id"], observed_at=now, received_at=now, value=None,
                                 reason=ReadReason.WATCHER_OFFLINE.value)
                    recorded += 1
        return recorded

    def tick(self) -> int:
        """Poll every due feed once. Returns how many reads were made (confirming reads included)."""

        store, now, reads = self.store_factory(), self.clock(), 0
        for monitor_id, manifest in self._enabled(store):
            deadline = self._deadline(store, monitor_id, manifest, now)
            # A rate feed is read before the feeds it converts, so one tick's total uses one tick's rate.
            for feed in sorted(manifest["feeds"], key=lambda f: not _is_rate_feed(manifest, f["id"])):
                if is_push_feed(feed):
                    continue
                clock = self._clocks.setdefault((monitor_id, feed["id"]), _FeedClock())
                if clock.last_read is not None and now < clock.last_read + clock.period(feed, deadline):
                    continue
                self._read(store, monitor_id, manifest, feed, now)
                reads += 1
        reads += self._clock_rules(store, now)
        self._retention(store, now)
        WATCHER.last_tick = now
        return reads

    def _read(self, store: LensStore, monitor_id: str, manifest: dict[str, Any], feed: dict[str, Any],
              now: datetime) -> None:
        clock = self._clocks.setdefault((monitor_id, feed["id"]), _FeedClock())
        result = read_feed_source(feed, client=self.client, resolver=self.resolver)
        received = self.clock()
        self._record(store, monitor_id, manifest, feed, result, observed=now, received=received,
                     history=list(clock.recent))
        if result.value is not None:
            clock.recent.append(result.value)
        clock.failures = 0 if result.value is not None else clock.failures + 1
        clock.last_read = now

    def _deadline(self, store: LensStore, monitor_id: str, manifest: dict[str, Any],
                  now: datetime) -> datetime | None:
        """The monitor's nearest deadline still ahead, from its ``ends_within`` feeds (W7)."""

        nearest = None
        for rule in manifest["rules"]:
            if RuleForm(rule["form"]) not in CLOCK_FORMS:
                continue
            latest = store.latest(monitor_id, rule["feed_id"])
            if latest is None or latest["value"] is None:
                continue
            deadline = from_ms(int(latest["value"]))
            if deadline > now and (nearest is None or deadline < nearest):
                nearest = deadline
        return nearest

    def _enabled(self, store: LensStore) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for row in store.monitors(states=(MonitorState.ENABLED,)):
            if row["sealed"] is not None:
                out.append((row["monitor_id"], row["sealed"]["manifest"]))
        return out

    def _record(self, store: LensStore, monitor_id: str, manifest: dict[str, Any], feed: dict[str, Any],
                result: ReadResult, *, observed: datetime, received: datetime,
                history: list[float] = ()) -> None:
        from .sources import typed_result

        received = max(observed, received)
        # W2 / W5: a read the feed's type, range or outlier guard refuses is a gap with its
        # reason; a money read with a total_cost is stored as its total.
        typed = typed_result(feed, result, history=history,
                             fx_rate=self._fx_rate(store, monitor_id, feed, observed))
        store.record(monitor_id, feed["id"], observed_at=observed, received_at=received,
                     value=typed.value, reason=typed.reason.value, http_status=typed.http_status)
        for rule in manifest["rules"]:
            if feed["id"] in rule_feed_ids(rule):
                # Evaluated at the RECEIVE time: an observation is never later than its verdict.
                self._evaluate(store, monitor_id, manifest, rule, received)

    def record_pushed(self, store: LensStore, monitor_id: str, manifest: dict[str, Any], feed: dict[str, Any], *,
                      value: float | None, reason: ReadReason, observed: datetime, received: datetime) -> None:
        """Record one push-door reading through the same typing, store and rule step as a poll (L3)."""

        self._record(store, monitor_id, manifest, feed, ReadResult(value=value, reason=reason),
                     observed=observed, received=received)

    def _fx_rate(self, store: LensStore, monitor_id: str, feed: dict[str, Any], at: datetime) -> float | None:
        """The newest exchange rate read no longer than ``fx.max_age_ms`` before ``at`` (W5)."""

        from .feed import fx_feed_id, value_type_of

        rate_feed = fx_feed_id(feed)
        if rate_feed is None:
            return None
        max_age = timedelta(milliseconds=value_type_of(feed)["total_cost"]["fx"]["max_age_ms"])
        rows = store.observations(monitor_id, rate_feed, start=at - max_age, end=at + timedelta(milliseconds=1))
        values = [row["value"] for row in rows if row["value"] is not None]
        return values[-1] if values else None

    def _clock_rules(self, store: LensStore, now: datetime) -> int:
        """W7: a deadline rule moves with the runtime clock, not only when its feed is read.

        A rule the clock would newly fire is first given a confirming read of its feed,
        unless that feed was read this tick. Returns the confirming reads made."""

        reads = 0
        for monitor_id, manifest in self._enabled(store):
            feeds = {feed["id"]: feed for feed in manifest["feeds"]}
            for rule in manifest["rules"]:
                if RuleForm(rule["form"]) not in CLOCK_FORMS:
                    continue
                clock = self._clocks.get((monitor_id, rule["feed_id"]))
                pulled = not is_push_feed(feeds[rule["feed_id"]])
                if pulled and (clock is None or clock.last_read != now) and self._would_open(
                        store, monitor_id, manifest, rule, now):
                    self._read(store, monitor_id, manifest, feeds[rule["feed_id"]], now)
                    reads += 1
                self._evaluate(store, monitor_id, manifest, rule, now)
        return reads

    def _would_open(self, store: LensStore, monitor_id: str, manifest: dict[str, Any], rule: dict[str, Any],
                    now: datetime) -> bool:
        from .rules import Verdict

        previous = store.latest_episode(monitor_id, rule["id"])
        if previous is not None and previous.state is EpisodeState.ACTIVE:
            return False
        return self._verdict(store, monitor_id, manifest, rule, now, previous) is Verdict.FIRING

    def _evaluate(self, store: LensStore, monitor_id: str, manifest: dict[str, Any], rule: dict[str, Any],
                  now: datetime) -> None:
        previous = store.latest_episode(monitor_id, rule["id"])
        verdict = self._verdict(store, monitor_id, manifest, rule, now, previous)
        nxt = observe(monitor_id=monitor_id, rule_id=rule["id"],
                      next_ordinal=(previous.ordinal if previous else 0) + 1,
                      verdict=verdict, at=now, previous=previous)
        if nxt is not None and nxt != previous:
            store.save_episode(nxt)

    def _verdict(self, store: LensStore, monitor_id: str, manifest: dict[str, Any], rule: dict[str, Any],
                 now: datetime, previous: Any):
        from .feed import Observation

        feeds = {feed["id"]: feed for feed in manifest["feeds"]}
        interval = max(timedelta(milliseconds=feeds[f]["interval_ms"]) for f in rule_feed_ids(rule))
        # A deadline's lead time is not an evidence window: it reads only the newest reads.
        lookback = 0 if RuleForm(rule["form"]) in CLOCK_FORMS else rule["window_ms"]
        span = timedelta(milliseconds=lookback) + interval * (rule["samples"] + 3)
        observations = [
            Observation(monitor_id=monitor_id, feed_id=feed_id, sequence=row["sequence"],
                        observed_at=from_ms(row["observed_ms"]), received_at=from_ms(row["received_ms"]),
                        value=row["value"], gap=row["gap"])
            for feed_id in rule_feed_ids(rule)
            for row in store.observations(monitor_id, feed_id, start=now - span, end=now + timedelta(milliseconds=1))
        ]
        return evaluate(rule, observations, now=now, expected_interval=interval,
                        was_firing=previous is not None and previous.state is EpisodeState.ACTIVE)

    def _retention(self, store: LensStore, now: datetime) -> None:
        from .retention import apply_retention

        if self._last_retention is None or now - self._last_retention >= RETENTION_EVERY:
            self._last_retention = now
            apply_retention(store, now)

    # --- the loop -------------------------------------------------------------

    def run(self, stop_event: threading.Event) -> None:
        WATCHER.running, WATCHER.since = True, self.clock()
        try:
            self.catch_up()
            while not stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    logger.warning("lens poll pass failed", exc_info=True)
                stop_event.wait(TICK_SECONDS)
        finally:
            WATCHER.running = False


def _is_rate_feed(manifest: dict[str, Any], feed_id: str) -> bool:
    from .feed import fx_feed_id

    return any(fx_feed_id(feed) == feed_id for feed in manifest["feeds"])


def lens_shipped() -> bool:
    """True when this installation ships the ``eternia-lens`` plugin directory.

    The phone bundle does not list it (ruling 4: phones run no poller), so the
    phone's serve never starts a watcher — by packaging, not by a flag."""

    from hermes_cli.plugins import get_bundled_plugins_dir

    return (get_bundled_plugins_dir() / "eternia-lens" / "plugin.yaml").is_file()


def start_lens_poller(*, stop_event: threading.Event) -> threading.Thread | None:
    """Start the watcher on a daemon thread; it stops with ``stop_event``. None when not shipped."""

    if not lens_shipped():
        return None
    poller = LensPoller()
    thread = threading.Thread(target=poller.run, args=(stop_event,), name="harness-serve-lens-poller", daemon=True)
    thread.start()
    return thread
