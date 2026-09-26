"""``scripts/ensure_fork_dev_deps.py``: the fork's test-only pins, checked from
the requirements file itself. Killing mutation: ``if have != pin`` -> ``if have
is None`` leaves a WRONG version unreported (the version-mismatch control reds).
"""

from __future__ import annotations

from importlib.metadata import version

from scripts.ensure_fork_dev_deps import REQUIREMENTS, main, pins, unmet


def test_the_committed_file_names_the_fork_tools_and_the_acp_extra():
    assert set(pins(REQUIREMENTS.read_text(encoding="utf-8"))) == {"coverage", "pytest-timeout", "agent-client-protocol"}


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
