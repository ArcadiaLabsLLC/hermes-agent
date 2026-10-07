"""``hermes harness observe turn-timing`` (h-perf-guard): each turn's spans against the baseline.

The command joins the turn record's ``phases``, the serve's ``chat_turn_accept_to_anchor``
receipt and the Launcher's ``[MissionChatTiming]`` line per turn, and names the spans over 1.5x
the committed baseline. It reads the LIVE serve's home (``serve_instances/<pid>.json``), never
the CLI's own profile.

*Killing mutations:* drop ``turn=`` from ``ACCEPT_TO_ANCHOR_RECEIPT`` -> the admitted-turn row
reds; resolve the home from ``get_hermes_home()`` instead of ``live_serve_home`` -> the live-home
row reads the CLI's sticky profile and reds.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from agent_runtime import turn_activity
from agent_runtime.turn_timing_census import (
    PROVIDER_SPANS,
    compare,
    default_baseline_path,
    join_turns,
    read_turn_records,
)

BASELINE = json.loads(default_baseline_path().read_text(encoding="utf-8"))
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _record(store: Path, turn_id: str, anchored: datetime, **marks) -> None:
    phases = {"anchored_at": anchored.isoformat().replace("+00:00", "Z"), "request_received": 0,
              "write_ahead": 300, "agent_ready": 340, "request_sent": 700, "response_headers": 1500,
              "provider_first_byte": 3000, "stream_done": 3600, "projected": 3680,
              "visibility_bundle_builds": 0, "builds_overlapped": 0, **marks}
    path = store / "mission_chat_turns" / "persona_chat_x.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    session = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    session[turn_id] = {"phases": phases, "profile_timing": {"resident_actor_reused": 1}}
    path.write_text(json.dumps(session), encoding="utf-8")


def _log_line(at: datetime, message: str) -> str:
    local = at.astimezone().replace(tzinfo=None)
    return f"{local:%Y-%m-%d %H:%M:%S},{local.microsecond // 1000:03d} INFO agent_runtime.turn_activity: {message}\n"


def _accept_receipt(turn, total_ms: int) -> str:
    """The serve's own receipt format, as ``admitted_turn`` fills it."""

    return turn_activity.ACCEPT_TO_ANCHOR_RECEIPT % ("chat-1", 0, 0, total_ms, total_ms,
                                                     turn_activity._turn_name(turn))


def test_a_slow_write_ahead_is_named_and_a_slow_provider_is_named_apart(tmp_path):
    anchored = NOW - timedelta(minutes=5)
    _record(tmp_path, "m-slow", anchored, write_ahead=1300, agent_ready=1340, request_sent=1700,
            response_headers=5000, provider_first_byte=6000, stream_done=6600, projected=6680)
    log = [_log_line(anchored, _accept_receipt(lambda: "m-slow", 30))]
    launcher = ["[2026-10-06T16:05:25.123Z] INFO agent_console — [MissionChatTiming] turn_id=m-slow "
                "enqueue_to_dispatch_ms=4 send_to_admit_ms=41 admit_to_first_delta_ms=6100 rt_turn_context_ms=9\n"]
    turns = read_turn_records(tmp_path, since=NOW - timedelta(hours=1))
    [row] = compare(join_turns(turns, log, launcher), BASELINE)

    assert row["regressed"] == ["anchor_to_write_ahead", "anchor_to_request_sent"], row["regressed"]
    assert set(row["provider_regressed"]) <= PROVIDER_SPANS and row["provider_regressed"]
    assert row["spans"]["accept_to_anchor"]["value"] == 30  # joined on turn=
    assert row["spans"]["send_to_admit"]["value"] == 41  # the Launcher's span, no baseline yet
    assert row["spans"]["send_to_admit"]["baseline"] is None


def test_an_old_receipt_without_turn_joins_on_the_anchor_instant(tmp_path):
    anchored = NOW - timedelta(minutes=2)
    _record(tmp_path, "m-old", anchored)
    old = "chat_turn_accept_to_anchor request=chat-2 queue_ms=0 link_ms=0 dispatch_ms=110 total_ms=110"
    elsewhere = "chat_turn_accept_to_anchor request=chat-3 queue_ms=0 link_ms=0 dispatch_ms=9 total_ms=9"
    log = [_log_line(anchored + timedelta(milliseconds=200), old),
           _log_line(anchored + timedelta(seconds=30), elsewhere)]
    [row] = compare(join_turns(read_turn_records(tmp_path, since=NOW - timedelta(hours=1)), log, []), BASELINE)
    assert row["spans"]["accept_to_anchor"]["value"] == 110
    assert "accept_to_anchor" in row["regressed"]


def test_a_count_over_its_baseline_is_a_regression(tmp_path):
    _record(tmp_path, "m-build", NOW - timedelta(minutes=1), visibility_bundle_builds=2)
    [row] = compare(join_turns(read_turn_records(tmp_path, since=NOW - timedelta(hours=1)), [], []), BASELINE)
    assert row["regressed"] == ["visibility_bundle_builds"]


def test_the_admitted_turn_receipt_carries_the_client_message_id(caplog):
    caplog.set_level(logging.INFO, logger=turn_activity.__name__)
    accepted = turn_activity.AcceptedTurn("chat-9")
    with turn_activity.accepted_turn_scope(accepted):
        with turn_activity.admitted_turn(turn_id=lambda: "m-9"):
            pass
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("chat_turn_accept_to_anchor ")]
    assert line.endswith(" turn=m-9"), line


def test_the_command_reads_the_live_serves_home_not_the_cli_profile(tmp_path, monkeypatch, capsys):
    from agent_runtime import paths, serve_registry
    from hermes_cli.harness_parts.observe_commands import _cmd_observe_turn_timing

    store = tmp_path / "store"
    serve_home = tmp_path / "profiles" / "base"
    (serve_home / "logs").mkdir(parents=True)
    anchored = NOW - timedelta(minutes=3)
    _record(store, "m-live", anchored)
    (serve_home / "logs" / "agent.log").write_text(_log_line(anchored, _accept_receipt("m-live", 12)),
                                                    encoding="utf-8")
    monkeypatch.setattr(paths, "store_root", lambda: store)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "cli-sticky"))
    serve_registry.register_serve_instance(store, pid=os.getpid(), hermes_home=str(serve_home))
    try:
        code = _cmd_observe_turn_timing(SimpleNamespace(since="1h", log=None, launcher_log=str(tmp_path / "none.log"),
                                                        baseline=None, json=True))
    finally:
        serve_registry.unregister_serve_instance(store)
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["home"] == {"path": str(serve_home), "source": f"live serve pid {os.getpid()}"}
    [row] = report["turns"]
    assert row["turn_id"] == "m-live" and row["spans"]["accept_to_anchor"]["value"] == 12
