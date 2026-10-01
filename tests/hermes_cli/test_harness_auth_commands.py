"""The plugin command reaches native credential operations without a second writer."""

import argparse
import io
import json

import pytest

from hermes_cli.harness import build_cli_parser


def harness_parser():
    root = argparse.ArgumentParser()
    command = root.add_subparsers(dest="command").add_parser("harness")
    build_cli_parser(command)
    return root


def test_harness_key_command_writes_to_the_selected_home_only(tmp_path, monkeypatch, capsys):
    home = tmp_path / "selected"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("sys.stdin", io.StringIO("synthetic-provider-key\n"))
    args = harness_parser().parse_args(["harness", "auth", "set-key", "openrouter", "--stdin"])
    with pytest.raises(SystemExit) as exit:
        args.func(args)
    assert exit.value.code == 0
    out = capsys.readouterr()
    receipt = json.loads(out.out)
    assert receipt["ok"] is True
    assert receipt["home"] == str(home)
    assert "synthetic-provider-key" not in out.out + out.err
    assert "OPENROUTER_API_KEY" in (home / ".env").read_text()


def test_rpc_signin_child_uses_the_same_plugin_parser(monkeypatch):
    from agent_runtime import provider_signin_child
    from hermes_cli.harness_parts.parser import auth

    calls = []
    monkeypatch.setattr(provider_signin_child, "_PopenChild", lambda argv, env: argv)
    monkeypatch.setattr(auth, "auth_login_command", lambda args: calls.append((args.provider, args.flow, args.json)) or 7)
    argv = provider_signin_child.spawn_login_child("codex", "browser", None)
    args = harness_parser().parse_args(argv[3:])
    with pytest.raises(SystemExit) as exit:
        args.func(args)
    assert exit.value.code == 7
    assert calls == [("codex", "browser", True)]
