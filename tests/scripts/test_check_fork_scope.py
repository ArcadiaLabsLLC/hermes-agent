"""``scripts/check`` judges ruff and footgun reds on fork lines only; ``--judge-all`` judges all.

The fixture repo (``_fork_repo``) plants ``Dict[str, Any]`` (UP006) on an upstream base line
and on a fork-added line of the same upstream file. The tool output is the real formats
(ruff ``--output-format=json``, the footgun scanner's ``path:line: [name]`` blocks), fed
through ``scripts/check``'s own ``_run`` / ``main``.
Plan: ``docs/agent-runtime-harness/planned/fork-seam-line-lint-2026-10-21.md`` F2.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from scripts.code_health import fork_scope
from tests.scripts._fork_repo import make_fork_repo

_CHECK = Path(__file__).resolve().parents[2] / "scripts" / "check"

UP_BASE = "from typing import Any, Dict\n\nA: Dict[str, Any] = {}\n"
UP_FORK = "from typing import Any, Dict\n\nA: Dict[str, Any] = {}\nB: Dict[str, Any] = {}  # fork\n"


def _load_check(monkeypatch):
    loader = SourceFileLoader("scripts_check_fork_scope_under_test", str(_CHECK))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    monkeypatch.setitem(sys.modules, loader.name, module)
    loader.exec_module(module)
    return module


def _ruff_finding(root: Path, row: int) -> dict:
    return {"code": "UP006", "message": "Use `dict` instead of `Dict` for type annotation",
            "filename": str(root / "up.py"), "location": {"row": row, "column": 4},
            "end_location": {"row": row, "column": 8}}


def _echo_job(check, root: Path, stdout: str, code: int, *tail: str):
    script = f"import sys; sys.stdout.write({stdout!r}); sys.exit({code})"
    return check._Job([sys.executable, "-c", script, *tail], root, None)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    make_fork_repo(root, up_base=UP_BASE, up_fork=UP_FORK)
    return root


def _run_ruff_gate(monkeypatch, capsys, repo: Path, *extra: str) -> tuple[int, str]:
    check = _load_check(monkeypatch)
    payload = json.dumps([_ruff_finding(repo, 3), _ruff_finding(repo, 4)])
    job = _echo_job(check, repo, payload, 1, "check", *fork_scope.RUFF_ARGS)
    monkeypatch.setattr(check, "_jobs", lambda *a, **k: {"ruff": job})
    code = check.main(["--only", "ruff", *extra])
    return code, capsys.readouterr().out


def test_the_gate_fails_naming_only_the_fork_line(monkeypatch, capsys, repo):
    code, out = _run_ruff_gate(monkeypatch, capsys, repo)
    assert code == 1
    assert "up.py:4:4 UP006" in out.split("=== ruff upstream")[0]
    assert "up.py:3:4 UP006" not in out.split("=== ruff upstream")[0]
    assert "=== ruff upstream (not judged): 1 ===" in out
    assert "  up.py:3:4 UP006" in out
    assert "scripts/check: 1 checks, FAILED: ruff" in out


def test_judge_all_fails_naming_both(monkeypatch, capsys, repo):
    code, out = _run_ruff_gate(monkeypatch, capsys, repo, "--judge-all")
    assert code == 1
    assert "up.py:3:4 UP006" in out and "up.py:4:4 UP006" in out
    assert "upstream (not judged)" not in out
    assert "scope: every line (--judge-all)" in out


def test_a_red_only_on_an_upstream_line_passes_and_is_still_printed(monkeypatch, capsys, repo):
    check = _load_check(monkeypatch)
    job = _echo_job(check, repo, json.dumps([_ruff_finding(repo, 3)]), 1, "check",
                    *fork_scope.RUFF_ARGS)
    monkeypatch.setattr(check, "_jobs", lambda *a, **k: {"ruff": job})
    assert check.main(["--only", "ruff"]) == 0
    out = capsys.readouterr().out
    assert "=== ruff upstream (not judged): 1 ===" in out
    assert "scripts/check: 1 checks, ok" in out


def test_footguns_share_the_line_filter(monkeypatch, capsys, repo):
    check = _load_check(monkeypatch)
    blocks = "".join(
        f"up.py:{n}: [open() without encoding]\n    x = open(p)\n    — msg\n    Fix: pass encoding\n\n"
        for n in (3, 4)
    )
    job = _echo_job(check, repo, blocks, 1, "scripts/check-windows-footguns.py", "--all")
    monkeypatch.setattr(check, "_jobs", lambda *a, **k: {"footguns": job})
    assert check.main(["--only", "footguns"]) == 1
    out = capsys.readouterr().out
    judged = out.split("=== footguns upstream")[0]
    assert "up.py:4: [open() without encoding]" in judged
    assert "up.py:3:" not in judged
    assert "=== footguns upstream (not judged): 1 ===" in out


def test_without_a_base_every_line_is_judged(monkeypatch, capsys, repo):
    (repo / "tests" / "fixtures" / "upstream_manifest.txt").unlink()
    code, out = _run_ruff_gate(monkeypatch, capsys, repo)
    assert code == 1
    assert "up.py:3:4 UP006" in out and "up.py:4:4 UP006" in out
    assert "fork lines unavailable" in out


def test_a_job_that_is_neither_tool_is_untouched(repo):
    fork_scope.configure(judge_all=False)
    proc = subprocess.CompletedProcess(["x"], 3, stdout="raw", stderr="err")
    assert fork_scope.filter_job(["python", "scripts/check_bash_shebangs.py"], repo, None, proc) is proc


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None, reason="ruff not installed here")
def test_real_ruff_json_is_read(repo):
    """The real tool's JSON, not a hand-written copy of it."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "UP006",
         "--target-version", "py311", "up.py", *fork_scope.RUFF_ARGS],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    fork_scope.configure(judge_all=False)
    out = fork_scope.filter_job(["ruff", "check", *fork_scope.RUFF_ARGS], repo, None, proc)
    assert out.returncode == 1
    judged = [line for line in out.stdout.splitlines() if "UP006" in line]
    assert len(judged) == 1 and judged[0].startswith("up.py:4:")
