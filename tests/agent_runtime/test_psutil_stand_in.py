"""The phone's ``psutil`` stand-in (``agent_runtime.psutil_stand_in``, FH-FOOTPRINT-PHONE-PSUTIL-STUB):
installed only where it must be, and upstream's unguarded process reads answer through it exactly as
the per-site ``except ImportError`` guards it retired did.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``ensure_psutil_stand_in`` drops the ``provider_sdks_enabled()`` check -> desktop test red.
* the stand-in sets ``LINUX = True`` -> the birth/boot-start row red (it reads ``_proc``).
* ``process_iter`` yields a process -> the scratch-reap row red.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from agent_runtime import psutil_stand_in as stand_in


def _phone_profile() -> None:
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": False}}), encoding="utf-8")


@pytest.fixture
def no_psutil(monkeypatch):
    """No real psutil importable (the phone); every ``psutil`` entry restored afterwards."""
    monkeypatch.setitem(sys.modules, "psutil", None)  # recorded, so teardown puts the real one back
    monkeypatch.delitem(sys.modules, "psutil")
    monkeypatch.setattr(stand_in, "_real_psutil_importable", lambda: False)
    return monkeypatch


def test_the_desktop_profile_installs_nothing(no_psutil):
    assert stand_in.ensure_psutil_stand_in() is False  # agent.provider_sdks defaults on
    assert "psutil" not in sys.modules

    _phone_profile()  # positive control: the same call on the phone profile installs it
    assert stand_in.ensure_psutil_stand_in() is True
    assert stand_in.is_stand_in(sys.modules["psutil"])


def test_a_real_psutil_is_never_shadowed(no_psutil):
    _phone_profile()
    no_psutil.setattr(stand_in, "_real_psutil_importable", lambda: True)
    assert stand_in.ensure_psutil_stand_in() is False
    assert "psutil" not in sys.modules


def test_upstream_process_identity_reads_answer_as_the_retired_guards_did(no_psutil):
    """process_birth -> the plain create_time; worker_birth -> the same; boot_start -> None;
    spawned_by_this_process -> False (the tag is unreadable)."""
    no_psutil.setitem(sys.modules, "psutil", stand_in.stand_in_modules()["psutil"])
    from hermes_cli import process_identity

    class Proc:  # what a caller holds: no platform ``_proc`` to read
        def create_time(self):
            return 1234.5

    assert process_identity.process_birth(Proc()) == 1234.5
    assert process_identity.worker_birth(Proc()) == 1234.5
    assert process_identity.boot_start(Proc()) is None
    assert process_identity.spawned_by_this_process(os.getpid()) is False


def test_the_upstream_scratch_reap_finds_and_signals_nothing(no_psutil, tmp_path):
    no_psutil.setitem(sys.modules, "psutil", stand_in.stand_in_modules()["psutil"])
    import hermes_constants_scratch as scratch

    doomed = [tmp_path / "scratch" / "entry"]
    doomed[0].mkdir(parents=True)
    assert scratch.reap_processes_rooted_in(tmp_path / "scratch", doomed) == 0
    assert doomed == [tmp_path / "scratch" / "entry"]


def test_the_stand_in_reads_as_not_installed_to_a_package_probe(no_psutil):
    import importlib.util

    no_psutil.setitem(sys.modules, "psutil", stand_in.stand_in_modules()["psutil"])
    with pytest.raises(ValueError):
        importlib.util.find_spec("psutil")
