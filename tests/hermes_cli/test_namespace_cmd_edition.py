"""``hermes namespace seed | import-sessions`` are Developer Edition only (owner 2026-10-19). Temp roots only.

``probe``, ``list``, ``reset`` and ``delete`` ship on the bundled edition (the launcher's spawn path
calls ``probe``, its account removal ``delete``); the two verbs that carry data between namespaces
refuse ``namespace_dev_only`` there, before their implementation is imported, and touch nothing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from hermes_cli import steward
from hermes_cli import _namespace_bootstrap as ns
from hermes_cli import namespace_cmd

QA = "stagec-smoke"


@pytest.fixture
def base(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / ".hermes"
    (root / "agent-runtime").mkdir(parents=True)
    (root / "config.yaml").write_text("model: x\n", encoding="utf-8")
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)
    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(root))
    monkeypatch.setenv("HERMES_NAMESPACES_DIR", str(tmp_path / "hermes-namespaces"))
    for name in ("HERMES_NAMESPACE", "HERMES_LAUNCHER_SPAWNED"):
        monkeypatch.delenv(name, raising=False)
    return root


def _run(capsys, *argv: str) -> tuple[int, dict]:
    code = namespace_cmd.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def bundled(monkeypatch):
    monkeypatch.setattr(steward, "is_bundled_payload", lambda root: True)


def test_seed_and_import_sessions_refuse_on_the_bundled_edition_and_touch_nothing(base: Path, bundled, capsys,
                                                                                    tmp_path: Path):
    """Red when the edition check is gone: the bundled seed would create and fill the namespace."""
    export = tmp_path / "export.jsonl"
    export.write_text("", encoding="utf-8")
    for argv in (("seed", QA, "--from", "base"), ("seed", QA, "--from", "base", "--dry-run"),
                 ("import-sessions", QA, str(export))):
        code, out = _run(capsys, *argv)
        assert (code, out["reason"]) == (2, "namespace_dev_only"), argv
    assert not (tmp_path / "hermes-namespaces").exists()


def test_probe_list_reset_and_delete_still_run_on_the_bundled_edition(base: Path, bundled, capsys, tmp_path: Path):
    """Red when the edition gate spreads to the verbs the launcher's spawn and account-removal paths call."""
    ns.ensure_manifest(ns.layout(QA, dict(os.environ)))
    assert _run(capsys, "probe", QA)[0] == 0
    code, listed = _run(capsys, "list")
    assert code == 0 and [row["id"] for row in listed["namespaces"]] == [QA]
    assert _run(capsys, "reset", QA)[0] == 0
    assert _run(capsys, "delete", QA)[0] == 0
    assert not (tmp_path / "hermes-namespaces" / QA).exists()


def test_a_build_without_the_seed_modules_refuses_typed(base: Path, capsys, monkeypatch):
    """Red when the dispatcher's import is unguarded: a bundle that omits the module would crash, not refuse."""
    monkeypatch.setitem(sys.modules, "agent_runtime.namespace_seed", None)
    monkeypatch.setitem(sys.modules, "agent_runtime.own_session_import", None)
    import agent_runtime

    monkeypatch.delattr(agent_runtime, "namespace_seed", raising=False)
    monkeypatch.delattr(agent_runtime, "own_session_import", raising=False)
    for argv in (("seed", QA, "--from", "base"), ("import-sessions", QA, "x.jsonl")):
        code, out = _run(capsys, *argv)
        assert (code, out["reason"]) == (2, "namespace_dev_only"), argv
