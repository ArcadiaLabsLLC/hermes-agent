"""The live-system guard's backend-spawn arm reads ``python SCRIPT ARGS`` by contract.

``python [opts] SCRIPT ARGS...`` runs SCRIPT; ARGS are its ``sys.argv``. Upstream's
desktop-lifecycle E2Es spawn a sleeper SCRIPT whose argv tail is
``-m hermes_cli.main serve`` for psutil to classify - inert data, not a backend
start (2026-09-25 merge). The same argv with the entry point as the program still
refuses. Every spawn here names a script that does not exist, so nothing that
starts can be a backend (python exits on "can't open file").
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_SERVE_TAIL = ["-m", "hermes_cli.main", "serve"]


def test_a_sleeper_script_with_a_serve_tail_is_not_a_backend_start(tmp_path):
    missing_script = tmp_path / "sleeper.py"  # never created
    proc = subprocess.Popen([sys.executable, str(missing_script), *_SERVE_TAIL],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert proc.wait(timeout=30) != 0  # the interpreter refused the missing script


@pytest.mark.parametrize("argv", [
    lambda tmp: [sys.executable, *_SERVE_TAIL],
    lambda tmp: [sys.executable, str(tmp / "hermes_cli" / "main.py"), "serve"],
    lambda tmp: [str(tmp / "bin" / "hermes"), "serve"],
], ids=["python-m", "main-py-script", "hermes-launcher"])
def test_a_real_entry_point_with_serve_is_still_refused(tmp_path, argv):
    with pytest.raises(RuntimeError, match="would START a hermes backend"):
        subprocess.Popen(argv(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
