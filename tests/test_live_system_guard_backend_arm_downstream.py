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


def test_python_c_code_that_only_compares_backend_words_is_not_a_backend_start():
    # v0.21.6's approval-scan tests feed "stop/restart hermes gateway" prose to a
    # detector inside ``python -c``: a literal the code compares, not a command.
    code = 'cases = {"hermes gateway restart": "stop/restart hermes gateway (kills agents)"}\nassert cases'
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# The word scan matches bare words (prose, comments); these carry the same bare words
# as the inert case above, beside an identifier that could spawn, so they must still
# refuse. The last three quote the entry point the way code spells a command
# (``run("hermes``, ``['hermes',``): the scan splits quotes and call punctuation off a word.
@pytest.mark.parametrize("code", [
    'import subprocess\nx = 1  # then hermes gateway run',
    'import os\nnote = "stop/restart hermes gateway now"',
    'from hermes_cli.main import main\nnote = "stop/restart hermes gateway now"',
    '__import__("json")\nnote = "stop/restart hermes gateway now"',
    'note = "stop/restart hermes gateway now" +',  # unparseable
    'import subprocess; subprocess.run("hermes gateway run")',
    "import subprocess; subprocess.run(['hermes', 'serve'])",
    'import os; os.system("hermes dashboard")',
], ids=["subprocess", "os", "hermes-cli-in-process", "dunder-import", "unparseable",
        "quoted-string", "quoted-argv", "quoted-os-system"])
def test_python_c_code_that_could_spawn_keeps_the_conservative_scan(code):
    with pytest.raises(RuntimeError, match="live-system guard: blocked"):
        subprocess.run([sys.executable, "-c", code], timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
