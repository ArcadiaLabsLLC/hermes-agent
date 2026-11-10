"""``hermes_cli.doctor``'s home names stay live after a test patches them (FH-FOOTPRINT-FORK-TEST-HUNKS-OUT).

Upstream's doctor helpers read ``from hermes_cli.doctor import HERMES_HOME``; the fork serves that
name live through the module ``__getattr__`` (PR #125260). ``monkeypatch``'s undo re-binds the value
it read as a real attribute, so ``tests/_downstream/doctor_live_home.py`` drops it before each test.
The first test leaves the frozen attribute behind; the second (run after it, same process) must see
the live home again.
"""

from __future__ import annotations

import hermes_cli.doctor as doctor
from hermes_constants import get_hermes_home


def test_a_patched_home_reaches_the_helpers_and_its_undo_leaves_a_real_attribute(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "HERMES_HOME", tmp_path)
    from hermes_cli.doctor import HERMES_HOME

    assert HERMES_HOME == tmp_path
    monkeypatch.undo()
    assert "HERMES_HOME" in doctor.__dict__, "monkeypatch's undo froze the live value (the premise)"


def test_the_next_test_reads_the_live_home_again(monkeypatch, tmp_path):
    assert "HERMES_HOME" not in doctor.__dict__
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli.doctor import HERMES_HOME

    assert HERMES_HOME == get_hermes_home() == tmp_path
