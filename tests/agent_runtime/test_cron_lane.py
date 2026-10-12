"""The serve's cron lane (``agent_runtime/cron_lane.py``; ADR 0015 step 1, 2026-10-12).

Upstream's in-process ticker, hosted by ``hermes harness serve`` instead of only by the
gateway. Proven through the lane's own door with upstream's scheduler class stubbed at its
import site, so what is asserted is the WIRING: the switch, the multiplex input, the stop
event and the drain gate the ticker is handed.

Killing mutations (each applied, red recorded in the commit body, reverted):
* ``serve_ticker_enabled`` returns ``True`` unconditionally        -> the off test red.
* ``start_serve_cron_ticker`` drops ``"profile_homes": profile_homes`` -> the multiplex test red.
* ``_boot_cron_lane`` drops ``can_dispatch=``                     -> the drain-gate test red.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import cron_lane


@pytest.fixture
def switch_off(monkeypatch, tmp_path):
    """A hermetic home whose config turns the lane off."""
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"cron": {"serve_ticker": False}}), encoding="utf-8")
    from hermes_cli import config as _config

    for name in ("_READONLY_CONFIG_CACHE", "_config_cache", "_CONFIG_CACHE"):
        if hasattr(_config, name):
            monkeypatch.setattr(_config, name, None, raising=False)
    return home


class _FakeScheduler:
    started: list[dict] = []

    def start(self, stop_event, **kwargs):
        _FakeScheduler.started.append({"stop_event": stop_event, **kwargs})


class _FakeThread:
    """``SupervisedTickerThread``-shaped: runs the target synchronously on ``start``."""

    instances: list["_FakeThread"] = []

    def __init__(self, target, *, args=(), kwargs=None, stop_event, name=""):
        self.target, self.args, self.kwargs = target, args, dict(kwargs or {})
        self.stop_event, self.name, self.started = stop_event, name, False
        _FakeThread.instances.append(self)

    def start(self):
        self.started = True
        self.target(*self.args, **self.kwargs)

    def is_alive(self):
        return False


@pytest.fixture
def fake_upstream(monkeypatch):
    import cron.scheduler_provider as provider
    import cron.scheduler_thread as thread_mod

    _FakeScheduler.started = []
    _FakeThread.instances = []
    monkeypatch.setattr(provider, "InProcessCronScheduler", _FakeScheduler)
    monkeypatch.setattr(thread_mod, "SupervisedTickerThread", _FakeThread)
    return _FakeScheduler, _FakeThread


def test_the_switch_is_on_by_default_and_off_when_the_config_says_so(switch_off):
    # Positive control first: with no config.yaml the default is today's behaviour, ON.
    (switch_off / "config.yaml").unlink()
    assert cron_lane.serve_ticker_enabled() is True
    (switch_off / "config.yaml").write_text(json.dumps({"cron": {"serve_ticker": False}}), encoding="utf-8")
    assert cron_lane.serve_ticker_enabled() is False


def test_off_starts_nothing(switch_off, fake_upstream):
    scheduler, thread = fake_upstream
    assert cron_lane.start_serve_cron_ticker(threading.Event()) is None
    assert thread.instances == [] and scheduler.started == []


def test_the_ticker_is_multiplexed_over_profile_homes_and_handed_the_stop_event(fake_upstream, monkeypatch):
    scheduler, thread = fake_upstream
    monkeypatch.setattr(cron_lane, "profile_homes", lambda: [("default", "/h/default"), ("neko", "/h/neko")])
    stop = threading.Event()
    gate = lambda: True  # noqa: E731

    handle = cron_lane.start_serve_cron_ticker(stop, interval=7, can_dispatch=gate)

    assert handle is thread.instances[0] and handle.started and handle.name == "serve-cron"
    (call,) = scheduler.started
    assert call["stop_event"] is stop
    assert call["interval"] == 7 and call["can_dispatch"] is gate
    assert call["adapters"] is None and call["loop"] is None
    # The CALLABLE, not its result: the ticker re-enumerates every cycle, so a persona
    # profile minted after boot is ticked without a restart.
    assert call["profile_homes"] is cron_lane.profile_homes
    assert call["profile_homes"]() == [("default", "/h/default"), ("neko", "/h/neko")]


def test_a_bundle_without_the_cron_package_is_unavailable_not_an_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_cron(name, *args, **kwargs):
        if name.startswith("cron."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_cron)
    assert cron_lane.start_serve_cron_ticker(threading.Event()) is None


def test_profile_homes_lists_every_live_profile_and_never_raises(monkeypatch):
    import hermes_cli.profiles as profiles

    monkeypatch.setattr(profiles, "list_profile_names", lambda: ["default", "neko"])
    monkeypatch.setattr(profiles, "get_profile_dir", lambda name: Path("/homes") / name)
    assert cron_lane.profile_homes() == [("default", str(Path("/homes/default"))), ("neko", str(Path("/homes/neko")))]

    def _boom():
        raise RuntimeError("listing broke")

    monkeypatch.setattr(profiles, "list_profile_names", _boom)
    assert cron_lane.profile_homes() == []


def test_the_receipt_names_the_three_outcomes():
    assert cron_lane.cron_lane_block(object(), enabled=True, interval=60) == {"outcome": "ticking", "interval_seconds": 60}
    assert cron_lane.cron_lane_block(None, enabled=False) == {"outcome": "disabled"}
    assert cron_lane.cron_lane_block(None, enabled=True) == {"outcome": "unavailable"}


# ── the boot phase ───────────────────────────────────────────────────────────


def _phase_host(monkeypatch, *, enabled: bool, handle):
    """A ``BootPhases`` host carrying only what ``_boot_cron_lane`` reads."""
    from hermes_cli.harness_parts.serve.boot_phases import BootPhases

    calls: dict = {"log": [], "start": []}
    monkeypatch.setattr(cron_lane, "serve_ticker_enabled", lambda: enabled)

    def _start(stop_event, *, can_dispatch=None, **kw):
        calls["start"].append({"stop_event": stop_event, "can_dispatch": can_dispatch})
        return handle

    monkeypatch.setattr(cron_lane, "start_serve_cron_ticker", _start)
    host = SimpleNamespace(
        liveness_stop=threading.Event(), drain_state=None, cron_ticker="stale",
        _service_log=lambda payload: calls["log"].append(payload),
    )
    return BootPhases._boot_cron_lane, host, calls


def test_the_boot_phase_starts_the_ticker_on_liveness_stop_with_the_drain_gate(monkeypatch):
    phase, host, calls = _phase_host(monkeypatch, enabled=True, handle="handle")
    phase(host)
    assert host.cron_ticker == "handle"
    (start,) = calls["start"]
    assert start["stop_event"] is host.liveness_stop
    # The drain gate: a tick may start runs only while no drain has begun.
    assert start["can_dispatch"]() is True
    host.drain_state = object()
    assert start["can_dispatch"]() is False
    assert calls["log"] == [{"event": "cron_lane", "outcome": "ticking", "interval_seconds": 60}]


def test_the_boot_phase_logs_disabled_and_starts_nothing_when_off(monkeypatch):
    phase, host, calls = _phase_host(monkeypatch, enabled=False, handle="never")
    phase(host)
    assert host.cron_ticker is None and calls["start"] == []
    assert calls["log"] == [{"event": "cron_lane", "outcome": "disabled"}]


def test_the_phone_bundle_turns_the_lane_off_and_the_manifest_knows_the_key():
    from agent_runtime.bundle_profiles.manifest import KEYS_READ_OUTSIDE_DEFAULTS, apply_to_config, load_profile

    assert KEYS_READ_OUTSIDE_DEFAULTS["cron.serve_ticker"] == "agent_runtime/cron_lane.py::serve_ticker_enabled"
    config = apply_to_config(load_profile("bundled-phone"), {})
    assert config["cron"]["serve_ticker"] is False
