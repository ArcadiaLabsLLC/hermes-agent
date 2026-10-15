"""``pm._fork_dependency_borrow``: HERMES_DEPENDENCY_ROOT lends a root's environment, read-only.

Owner ruling 2026-10-15 (wave w1015c-dev): QA's Developer Edition side runs under a QA-owned
HERMES_HOME on the owner's installed environment, never one of its own; the borrower never
writes the lender's environment. Unset, upstream's per-home rule (#123238) is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_DEPENDENCY_ROOT", raising=False)
    root = tmp_path / "Eternia" / "hermes-agent"
    root.mkdir(parents=True)
    return root


def _lender(tmp_path: Path, root: Path) -> Path:
    from pm.environments import install_key

    lender = tmp_path / "Eternia" / ".hermes"
    state = lender / "installs" / install_key(root)
    state.mkdir(parents=True)
    (state / "facts.json").write_text("{}", encoding="utf-8")
    return lender


def test_unset_the_dependency_root_is_upstreams_per_home_rule(checkout):
    from pm import environments

    assert environments.dependency_home_root() == environments.dependency_home_root.__wrapped__()
    assert environments.owning_home_root(checkout) == environments.owning_home_root.__wrapped__(checkout)


def test_set_the_lenders_installs_are_read_and_the_launch_stays_a_borrowers(checkout, tmp_path, monkeypatch):
    from pm import environments

    lender = _lender(tmp_path, checkout)
    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(lender))
    key = environments.install_key(checkout)
    assert environments.install_state_dir(checkout) == lender / "installs" / key
    assert environments.runtime_facts_path(checkout) == lender / "installs" / key / "facts.json"
    # The state dirs now coincide, so upstream's rule alone would call this launch the OWNER
    # (and republish the checkout's launchers); the borrow keeps it a borrower.
    assert environments.owning_home_root.__wrapped__(checkout) is None
    assert environments.owning_home_root(checkout) == lender


def test_a_borrower_never_syncs_the_lenders_environment(checkout, tmp_path, monkeypatch):
    import pm.install
    from pm.package import InstallError

    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(_lender(tmp_path, checkout)))
    with pytest.raises(InstallError, match="read-only"):
        pm.install.sync_venv(["anthropic"], explicit=True)


def test_positive_control_unset_the_sync_reaches_upstream(checkout):
    """Same call shape, borrow unset: upstream's own argument check answers, not the refusal."""
    import pm.install

    with pytest.raises(ValueError, match="repair restores"):
        pm.install.sync_venv(["anthropic"], repair=True)


def test_a_relative_dependency_root_is_refused(checkout, monkeypatch):
    from pm import environments
    from pm._fork_dependency_borrow import BorrowedEnvironmentReadOnly

    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", "relative/.hermes")
    with pytest.raises(BorrowedEnvironmentReadOnly):
        environments.dependency_home_root()
