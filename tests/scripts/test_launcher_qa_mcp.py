"""``scripts/launcher_qa_mcp.py``: the launcher QA MCP server, resolved from the environment only.

Killing mutation: drop the STAGEC_LAUNCH_HELPER default in ``resolve`` -> the child
env carries no helper and ``open_app_tab`` refuses ``launch_helper_missing``; the
default-helper assertion reds.
"""

from __future__ import annotations

import json
import os

import pytest

from scripts.launcher_qa_mcp import HELPER, SERVER_DIR, LaunchRefused, main, resolve


def _checkout(tmp_path, *, exe: bool = False):
    root = tmp_path / "launcher checkout"
    (root / SERVER_DIR / "bin").mkdir(parents=True)
    (root / SERVER_DIR / "bin" / "main.dart").write_text("void main() {}\n", encoding="utf-8")
    (root / HELPER).parent.mkdir(parents=True)
    (root / HELPER).write_text("# helper\n", encoding="utf-8")
    if exe:
        build = root / SERVER_DIR / "build"
        build.mkdir()
        (build / ("stagec_qa_mcp_server.exe" if os.name == "nt" else "stagec_qa_mcp_server")).write_bytes(b"")
    return root


def test_no_checkout_in_the_environment_is_refused_by_name():
    with pytest.raises(LaunchRefused, match="STAGEC_QA_REPO_ROOT"):
        resolve({})


def test_the_checkout_alone_yields_both_variables_and_the_dart_server(tmp_path):
    root = _checkout(tmp_path)
    argv, cwd, env = resolve({"ETERNIA_LAUNCHER_ROOT": str(root)})
    assert argv == ["dart", "run", "tool/stagec_qa_mcp_server/bin/main.dart"]
    assert cwd == root
    assert env["STAGEC_QA_REPO_ROOT"] == str(root)
    assert env["STAGEC_LAUNCH_HELPER"] == str(root / HELPER)
    assert env["STAGEC_QA_TRANSPORT"] == "direct_control"


def test_a_prebuilt_server_and_explicit_values_win(tmp_path):
    root = _checkout(tmp_path, exe=True)
    helper = tmp_path / "my-helper.ps1"
    helper.write_text("# mine\n", encoding="utf-8")
    argv, _, env = resolve({"STAGEC_QA_REPO_ROOT": str(root), "STAGEC_LAUNCH_HELPER": str(helper),
                            "STAGEC_QA_TRANSPORT": "other"})
    assert argv[0].endswith(("stagec_qa_mcp_server.exe", "stagec_qa_mcp_server"))
    assert env["STAGEC_LAUNCH_HELPER"] == str(helper)
    assert env["STAGEC_QA_TRANSPORT"] == "other"


def test_a_directory_that_is_not_a_launcher_checkout_is_refused(tmp_path):
    with pytest.raises(LaunchRefused, match="not an EterniaLauncher checkout"):
        resolve({"STAGEC_QA_REPO_ROOT": str(tmp_path)})


def test_print_names_the_resolved_server_without_starting_it(tmp_path, monkeypatch, capsys):
    root = _checkout(tmp_path)
    monkeypatch.delenv("STAGEC_LAUNCH_HELPER", raising=False)
    monkeypatch.setenv("STAGEC_QA_REPO_ROOT", str(root))
    assert main(["--print"]) == 0
    assert json.loads(capsys.readouterr().out)["env"]["STAGEC_LAUNCH_HELPER"] == str(root / HELPER)
    monkeypatch.delenv("STAGEC_QA_REPO_ROOT")
    monkeypatch.delenv("ETERNIA_LAUNCHER_ROOT", raising=False)
    assert main(["--print"]) == 2
