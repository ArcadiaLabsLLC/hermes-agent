import json
from types import SimpleNamespace
from hermes_cli.harness_parts.observe_commands import _cmd_observe_snapshot_builds


def test_build_census_uses_live_serve_home_and_respects_explicit_log(tmp_path, monkeypatch, capsys):
    import agent_runtime.turn_timing_census as timing
    from hermes_cli.logs import LOG_FILES
    base = tmp_path / "base"
    (base / "logs").mkdir(parents=True)
    agent_log = base / "logs" / LOG_FILES["agent"]
    agent_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(timing, "live_serve_home", lambda _: (base, 123))
    args = SimpleNamespace(since="1h", log=None, json=True)
    assert _cmd_observe_snapshot_builds(args) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["window"]["files"] == [str(agent_log)]
    assert row["home"]["source"] == "live serve pid 123"
    assert "resolution" in row
    override = tmp_path / "explicit.log"
    override.write_text("", encoding="utf-8")
    args.log = str(override)
    assert _cmd_observe_snapshot_builds(args) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["window"]["files"] == [str(override)]
    assert row["home"]["source"] == "--log"
