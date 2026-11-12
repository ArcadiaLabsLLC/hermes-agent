"""Fork-owned test moved out of ``tests/hermes_cli/test_source_launcher_publication.py`` (an upstream file).

Same name, same body; the upstream file keeps only upstream's tests (``7939482ee8`` put it there, and the
upstream-footprint ledger row it grew was never reviewed).
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from hermes_cli import _launchers
from tests.hermes_cli.test_source_launcher_publication import fixture_tree  # upstream's fixture the moved test uses


@pytest.mark.platforms("posix")
def test_published_launcher_reports_the_python_it_runs_not_the_current_homes(tmp_path, monkeypatch):
    """RT-PRINT-RUNTIME-COMMAND-NAMES-OTHER-STORE: an unstamped checkout published under one root.

    Live 2026-11-10: the launcher ran ``<root>/tools/.../python3`` while, with ``HERMES_HOME`` unset,
    ``--print-runtime-command`` printed ``~/.hermes/tools/...`` -- another store whose root holds no
    committed environment -- and a consumer that ran the report got Hermes with no dependencies.
    MUTATION: drop ``python=sys.executable`` from the launcher's ``--print-runtime-command`` branch
    and this test reddens (the other home's store is printed).
    """
    repo, _home, interpreter = fixture_tree(tmp_path, monkeypatch)
    out = tmp_path / "bin"
    out.mkdir()
    _launchers.ensure_install_launchers(repo, out)
    baked = (repo / ".hermes" / "bin" / "hermes").read_text(encoding="utf-8").splitlines()[1].split()[1]
    # Another home whose store records a different interpreter path (the same bytes, so it runs).
    other = tmp_path / "other-home"
    other_python = other / "tools" / "python-other" / "bin" / "python3"
    other_python.parent.mkdir(parents=True)
    other_python.symlink_to(interpreter)
    (other / "tools" / "facts.json").write_text(json.dumps({"schema": 1, "packages": {"python": {
        "version": "other", "entry": "python-other"}}}), encoding="utf-8")
    env = {**os.environ, "HERMES_HOME": str(other)}
    result = subprocess.run([str(repo / ".hermes" / "bin" / "hermes"), "--print-runtime-command"],
                            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False, env=env)
    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)[0]
    assert "other-home" not in printed
    assert printed == baked
