"""Start-up cuts for ``hermes`` read-only verbs (HQ3, 2026-10-01).

Two cuts, each pinned where its guarantee lives:

* ``gettext.find`` is answered once per question per process
  (``hermes_cli.gettext_find_memo``), and ``main()`` installs it BEFORE the parser
  tree is built — the ~620 parsers are where the probes were spent.
* ``hermes_cli.harness`` (imported for every ``hermes harness`` verb) no longer
  imports the charsheet draft pipeline or PIL; the pet verbs import them when
  they run.
"""

from __future__ import annotations

import gettext
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def counting_find(monkeypatch):
    """A stand-in ``gettext.find`` that counts its calls, with the memo installed over it."""

    from hermes_cli.gettext_find_memo import install_gettext_find_memo

    calls = []

    def fake_find(domain, localedir=None, languages=None, all=False):  # noqa: A002
        calls.append((domain, localedir, languages, all, os.environ.get("LANG")))
        return [f"/{domain}/{os.environ.get('LANG')}.mo"] if all else None

    monkeypatch.setattr(gettext, "find", fake_find)
    assert install_gettext_find_memo() is True
    return calls


def test_one_question_is_answered_once(counting_find, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    for _ in range(5):
        assert gettext.find("argparse") is None
        assert gettext.find("argparse", all=True) == ["/argparse/en_US.UTF-8.mo"]

    assert len(counting_find) == 2


def test_every_caller_gets_its_own_list(counting_find):
    first = gettext.find("argparse", all=True)
    first.append("mutated by a caller")

    assert gettext.find("argparse", all=True) == [first[0]]


def test_a_changed_locale_variable_is_a_new_question(counting_find, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    gettext.find("argparse", all=True)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")

    assert gettext.find("argparse", all=True) == ["/argparse/de_DE.UTF-8.mo"]
    assert len(counting_find) == 2


def test_installing_twice_wraps_once(counting_find):
    from hermes_cli.gettext_find_memo import install_gettext_find_memo

    assert install_gettext_find_memo() is False
    gettext.find("argparse")
    gettext.find("argparse")

    assert len(counting_find) == 1


def test_main_installs_the_memo_before_it_builds_the_parser(monkeypatch):
    import hermes_cli.main as main_mod

    def plain_find(domain, localedir=None, languages=None, all=False):  # noqa: A002
        return [] if all else None

    monkeypatch.setattr(gettext, "find", plain_find)
    seen = {}

    class _Stop(Exception):
        pass

    def fake_build_cli_parser():
        seen["memo"] = getattr(gettext.find, "__hermes_find_memo__", False)
        raise _Stop

    monkeypatch.setattr(main_mod, "_build_cli_parser", fake_build_cli_parser)
    monkeypatch.setattr(sys, "argv", ["hermes", "harness", "status", "--json"])

    with pytest.raises(_Stop):
        main_mod.main()

    assert seen == {"memo": True}


def _probe(code: str) -> list:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH")) if p)}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT), env=env, timeout=240
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


_DEFERRED = "m == 'PIL' or m.startswith(('PIL.', 'agent.charsheet.draft'))"


def test_the_harness_parser_does_not_import_the_charsheet_pipeline_or_pil():
    before, after = _probe(
        "import json, sys\n"
        "import hermes_cli.harness\n"
        f"before = sorted(m for m in sys.modules if {_DEFERRED})\n"
        "from pathlib import Path\n"
        "from hermes_cli.harness_parts import pets_commands\n"
        "pets_commands._pet_sheet_revision(Path('missing.png'))\n"
        f"after = sorted(m for m in sys.modules if {_DEFERRED})\n"
        "print(json.dumps([before, after]))\n"
    )

    assert before == []
    # Positive control: the probe sees the pipeline the moment a pet verb needs it.
    assert "agent.charsheet.draft.installed" in after


def test_the_memo_module_is_stdlib_only():
    # main() imports it before anything heavy is needed; it must not BE the heavy thing.
    loaded = _probe(
        "import json, sys\n"
        "heavy = ('argparse', 'yaml', 'hermes_cli.config', 'agent_runtime')\n"
        "import hermes_cli  # the package itself is not this module's cost\n"
        "before = {m for m in sys.modules if m.startswith(heavy)}\n"
        "import hermes_cli.gettext_find_memo\n"
        "print(json.dumps(sorted({m for m in sys.modules if m.startswith(heavy)} - before)))\n"
    )

    assert loaded == []
