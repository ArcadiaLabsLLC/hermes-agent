"""The real bundle recorder identifies a child lost during fixture setup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled


@pytest.mark.parametrize("preceding_pass", [False, True], ids=["first-test", "after-pass"])
def test_setup_death_records_the_running_member_before_any_phase_report(tmp_path, preceding_pass):
    plugin_dir = Path(__file__).resolve().parents[2] / "scripts" / "_bundle_plugin"
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_before.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    (tmp_path / "test_dying.py").write_text(
        "import os\nimport pytest\n"
        "@pytest.fixture\ndef stopped():\n    os._exit(73)\n"
        "def test_never_reaches_body(stopped):\n    raise AssertionError('body ran')\n",
        encoding="utf-8",
    )
    (tmp_path / "test_after.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    rels = (["test_before.py"] if preceding_pass else []) + ["test_dying.py", "test_after.py"]
    events_path = tmp_path / "events.jsonl"
    env = dict(os.environ, PYTHONPATH=str(plugin_dir), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-c", "pytest.ini", "-p", "hermes_bundle_report",
         f"--hermes-bundle-events={events_path}", *rels],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20, check=False,
    )
    assert child.returncode == 73, child.stdout + child.stderr
    events = bundled.tally_events(events_path.read_text(encoding="utf-8").splitlines())
    assert events.session_end is None
    assert events.files["test_dying.py"].counts == {}
    assert events.files["test_after.py"].counts == {}
    if preceding_pass:
        assert events.files["test_before.py"].counts["passed"] == 1
    members = [Path(rel) for rel in rels]
    assert bundled._where_it_died(members, rels, events, child.returncode) == (
        "test_dying.py", [Path("test_after.py")],
    )
    assert bundled.members_to_rerun(rels, events, child.returncode) == ["test_dying.py", "test_after.py"]
    assert events.last_begun == "test_dying.py"
