"""``scripts/ensure_fork_dev_deps.py``: the fork's test-only pins, checked from
the requirements file itself. Killing mutation: ``if have != pin`` -> ``if have
is None`` leaves a WRONG version unreported (the version-mismatch control reds).
"""

from __future__ import annotations

from importlib.metadata import version

from scripts.ensure_fork_dev_deps import REQUIREMENTS, main, pins, unmet


def test_the_committed_file_names_the_fork_tools():
    assert set(pins(REQUIREMENTS.read_text(encoding="utf-8"))) == {"coverage", "pytest-timeout"}


def test_unmet_reports_missing_and_mismatched_pins_and_nothing_else():
    have = version("pytest")
    required = pins(f"# comment\npytest=={have}\n\nno-such-dist-xyz==1.0  # trailing\n")
    assert required == {"pytest": have, "no-such-dist-xyz": "1.0"}
    assert unmet(required) == {"no-such-dist-xyz": None}
    # Positive control: the installed dist at a different pin IS unmet.
    assert unmet({"pytest": "0.0.1"}) == {"pytest": have}


def test_a_satisfied_file_installs_nothing(tmp_path):
    req = tmp_path / "req.txt"
    req.write_text(f"pytest=={version('pytest')}\n", encoding="utf-8")
    assert main(req) == 0
    assert main(tmp_path / "absent.txt") == 0


def test_a_held_install_lock_makes_a_second_installer_wait_then_admits_it(tmp_path):
    """Owner ruling 2026-10-15 (install lock first). Killing mutation: ``install_lock``
    yields without ``try_lock_exclusive`` -> the held-lock arm admits the second
    installer and the TimeoutError control reds."""
    import pytest

    from agent_runtime.file_locks import try_lock_exclusive, unlock
    from scripts.ensure_fork_dev_deps import install_lock

    lock = tmp_path / ".fork-dev-deps.lock"
    with open(lock, "a+b") as holder:
        try_lock_exclusive(holder)
        with pytest.raises(TimeoutError, match="another install held"):
            with install_lock(lock, wait=0.6):
                pass
        unlock(holder)
    # Positive control: the same lock, released, admits the installer.
    with install_lock(lock, wait=0.6):
        entered = True
    assert entered
