"""``hermes harness observe turn-timing --check`` (h-live-check): live turns against the committed budgets.

Fixture logs are written in the receipts' own formats (local log stamps, UTC launcher stamps), so the
check runs in any time zone. *Killing mutations:* judge ``send_prep_total`` against its baseline
instead of ``max_ms`` (or drop it from ``turn_latency_budgets.json``) -> the regressed row stops
naming it; drop the ``after-idle`` branch from ``classify`` -> the idle turn lands in ``warm`` and
the after-idle row reds on its group counts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from agent_runtime import paths
from agent_runtime.turn_latency_check import load_budgets
from hermes_cli.harness_parts.observe_commands import _cmd_observe_turn_check

BOOT = datetime(2026, 10, 7, 4, 38, 40, tzinfo=timezone.utc)
CHAT = "persona_chat_personainst_dev_agent_x"


def _stamp(at: datetime) -> str:
    local = at.astimezone().replace(tzinfo=None)
    return f"{local:%Y-%m-%d %H:%M:%S},{local.microsecond // 1000:03d}"


def _turn(at: datetime, n: int, *, accept=27, prep=260, conn="reused", wait=800, gap=150) -> list[str]:
    turn, request = f"agent-chat-send-{n:04d}", f"{CHAT}:req-{n}:abc:api:1"
    anchored = at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        f"{_stamp(at)} INFO [{CHAT}] agent_runtime.turn_activity: chat_turn_accept_to_anchor request=chat-{n} "
        f"queue_ms=0 link_ms=0 dispatch_ms={accept} total_ms={accept} turn={turn}",
        f"{_stamp(at + timedelta(milliseconds=prep))} INFO agent_runtime.send_prep_receipt: send_prep_receipt "
        f"turn={turn} anchored_at={anchored} total_ms={prep} cpu_ms=400",
        f"{_stamp(at + timedelta(seconds=1.5))} INFO agent_runtime.send_window_receipt: send_window_receipt "
        f"request={request} model=m end=event conn={conn} server_wait_ms={wait}.0",
        f"{_stamp(at + timedelta(seconds=2))} INFO agent_runtime.stream_gap_receipt: stream_gap_receipt "
        f"request={request} model=m end=text gap_ms={gap}.0",
    ]


def _launcher(at: datetime, n: int, *, send="warm", admit=110, build_max=120.5, build_sum=1000.0, paint=25) -> str:
    end = (at + timedelta(seconds=2.5)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return (f"[{end}] INFO eternia.mission.chat.timing — [MissionChatTiming] turn_id=agent-chat-send-{n:04d} "
            f"send={send} enqueue_to_dispatch_ms=1 send_to_admit_ms={admit} ui_apply_to_paint_ms={paint} "
            f"ui_build_max_ms={build_max} ui_build_sum_ms={build_sum}")


def _run(tmp_path: Path, monkeypatch, capsys, hermes: list[str], launcher: list[str] | None, **extra):
    store = tmp_path / "store"
    (store / "serve_instances").mkdir(parents=True)
    (store / "serve_instances" / "4242.stderr.log").write_text(
        f"# harness serve --service pid=4242 boot_id=b started={BOOT.isoformat().replace('+00:00', 'Z')}\n",
        encoding="utf-8")
    monkeypatch.setattr(paths, "store_root", lambda: store)
    log = tmp_path / "agent.log"
    log.write_text("\n".join(hermes) + "\n", encoding="utf-8")
    launcher_log = tmp_path / "eternia_launcher_diag.log"
    if launcher is not None:
        launcher_log.write_text("\n".join(launcher) + "\n", encoding="utf-8")
    args = SimpleNamespace(check=True, log=str(log), launcher_log=str(launcher_log), budgets=None,
                           last=10, from_time=None, to_time=None, json=True, **extra)
    code = _cmd_observe_turn_check(args)
    return code, json.loads(capsys.readouterr().out)


def _session(regress: dict | None = None, launcher_regress: dict | None = None):
    """Turn 1 three minutes after boot (cold), then four warm turns four seconds apart."""

    hermes, launcher = [], []
    at = BOOT + timedelta(minutes=3)
    for n in range(1, 6):
        hermes += _turn(at, n, **{"prep": 780 if n == 1 else 260, **(regress if n == 4 and regress else {})})
        launcher.append(_launcher(at, n, send="first_in_process" if n == 1 else "warm",
                                  **(launcher_regress if n == 4 and launcher_regress else {})))
        at += timedelta(seconds=4)
    return hermes, launcher


def _row(report, group, span):
    return next(r for r in report["rows"] if r["group"] == group and r["span"] == span)


def test_a_baseline_like_session_passes_and_turn_one_is_cold(tmp_path, monkeypatch, capsys):
    hermes, launcher = _session()
    code, report = _run(tmp_path, monkeypatch, capsys, hermes, launcher)

    assert code == 0 and report["result"] == "PASS", report["failed"]
    assert report["groups"] == {"warm": 4, "after-idle": 0, "cold": 1}
    assert _row(report, "warm", "send_prep_total")["status"] == "PASS"
    assert _row(report, "warm", "conn")["observed"] == "reusedx4"
    assert _row(report, "warm", "server_wait")["status"] == "REPORT"


def test_a_regressed_session_fails_naming_send_prep_and_ui_build_max(tmp_path, monkeypatch, capsys):
    hermes, launcher = _session(regress={"prep": 890}, launcher_regress={"build_max": 260.0})
    code, report = _run(tmp_path, monkeypatch, capsys, hermes, launcher)

    assert code == 1 and report["result"] == "FAIL"
    assert report["failed"] == ["send_prep_total", "ui_build_max"]
    assert _row(report, "warm", "send_prep_total")["failing_turns"] == ["agent-chat-send-0004"]
    assert _row(report, "warm", "send_prep_total")["observed"] == "260-890 ms"


def test_a_slow_provider_is_reported_never_failed(tmp_path, monkeypatch, capsys):
    hermes, launcher = _session(regress={"wait": 9000, "gap": 4000})
    code, report = _run(tmp_path, monkeypatch, capsys, hermes, launcher)

    assert code == 0, report["failed"]
    assert _row(report, "warm", "server_wait")["observed"] == "800-9000 ms"


def test_without_the_launcher_log_the_hermes_spans_are_still_checked(tmp_path, monkeypatch, capsys):
    hermes, _ = _session(regress={"prep": 1300})
    code, report = _run(tmp_path, monkeypatch, capsys, hermes, None)

    assert report["launcher_log"] is False
    assert _row(report, "warm", "ui_build_max")["status"] == "SKIP"
    assert _row(report, "warm", "accept_to_anchor")["status"] == "PASS"
    assert code == 1 and report["failed"] == ["send_prep_total"]


def test_a_turn_after_thirty_seconds_idle_is_its_own_group_and_judged(tmp_path, monkeypatch, capsys):
    hermes, launcher = _session()
    idle_at = BOOT + timedelta(minutes=3, seconds=16 + 2.5 + 45)
    hermes += _turn(idle_at, 6, prep=1139, conn="new")
    launcher.append(_launcher(idle_at, 6))
    code, report = _run(tmp_path, monkeypatch, capsys, hermes, launcher)

    assert report["groups"] == {"warm": 4, "after-idle": 1, "cold": 1}
    assert code == 1 and report["failed"] == ["conn", "send_prep_total"]
    assert _row(report, "after-idle", "conn")["failing_turns"] == ["agent-chat-send-0006"]
    assert _row(report, "warm", "send_prep_total")["status"] == "PASS"


def test_a_slow_cold_turn_is_reported_not_failed(tmp_path, monkeypatch, capsys):
    hermes, launcher = [], []
    at = BOOT + timedelta(seconds=30)
    hermes += _turn(at, 1, prep=1500, conn="new")
    launcher.append(_launcher(at, 1, send="first_in_process"))
    hermes += _turn(at + timedelta(seconds=5), 2, prep=1200)
    launcher.append(_launcher(at + timedelta(seconds=5), 2))
    code, report = _run(tmp_path, monkeypatch, capsys, hermes, launcher)

    assert report["groups"] == {"warm": 0, "after-idle": 0, "cold": 2}
    assert _row(report, "cold", "send_prep_total")["status"] == "INFO"
    assert code == 0


def test_every_budget_names_its_baseline():
    budgets = load_budgets()
    assert {b["span"] for b in budgets["budgets"]} == {
        "accept_to_anchor", "send_prep_total", "conn", "send_to_admit", "ui_build_max", "ui_build_sum",
        "ui_apply_to_paint"}
    assert all(b.get("baseline") for b in budgets["budgets"] + budgets["reported"])
