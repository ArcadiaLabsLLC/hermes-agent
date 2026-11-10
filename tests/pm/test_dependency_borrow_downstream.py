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


# --- RT-QA-CHECKOUT-BORROW-LENDER-KEY / -INPUTS-MATCH: a pinned QA checkout borrows the LENDER
# CHECKOUT's environment (plan docs/agent-runtime-harness/planned/qa-checkout-dependency-identity-2026-11-05.md).

_INPUTS = {"uv.lock": "version = 1\n", "pyproject.toml": "[project]\nname = 'x'\n", "pm/lock.json": "{}\n"}


def _write_inputs(checkout: Path, **overrides: str) -> None:
    for name, text in {**_INPUTS, **overrides}.items():
        (checkout / name).parent.mkdir(parents=True, exist_ok=True)
        (checkout / name).write_text(text, encoding="utf-8")


def _committed_lender(tmp_path: Path, lender_checkout: Path) -> tuple[Path, Path]:
    """A lender root whose ``installs/<install_key(lender checkout)>`` commits an environment."""
    import json
    import sys

    from pm.environments import install_key

    root = tmp_path / "lender-root"
    state = root / "installs" / install_key(lender_checkout)
    venv = state / "environments" / "g1" / "venv"
    major, minor = sys.version_info[:2]
    site = venv / "lib" / f"python{major}.{minor}" / "site-packages"
    site.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"version = {major}.{minor}.0\n", encoding="utf-8")
    # The editable pointer a uv/setuptools install leaves: it names the LENDER checkout.
    (site / "__editable__.lender.pth").write_text(f"{lender_checkout}\n", encoding="utf-8")
    facts = {"packages": {"venv": {"environment": str(venv)}}}
    (state / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return root, venv


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A lender checkout + its committed root, and a borrower worktree at another path."""
    monkeypatch.delenv("HERMES_DEPENDENCY_ROOT", raising=False)
    monkeypatch.delenv("HERMES_DEPENDENCY_CHECKOUT", raising=False)
    lender_checkout, borrower = tmp_path / "hermes-agent", tmp_path / "worktrees" / "qa-pin"
    for checkout, who in ((lender_checkout, "lender"), (borrower, "borrower")):
        (checkout / "borrow_probe").mkdir(parents=True)
        (checkout / "borrow_probe" / "__init__.py").write_text(f"WHO = {who!r}\n", encoding="utf-8")
        _write_inputs(checkout)
    root, venv = _committed_lender(tmp_path, lender_checkout)
    monkeypatch.setenv("HERMES_DEPENDENCY_ROOT", str(root))
    monkeypatch.setenv("HERMES_DEPENDENCY_CHECKOUT", str(lender_checkout))
    return lender_checkout, borrower, root, venv


def test_a_pinned_checkout_selects_the_lender_checkouts_environment(pinned):
    from pm import environments

    lender_checkout, borrower, root, venv = pinned
    assert environments.install_state_dir(borrower) == root / "installs" / environments.install_key(lender_checkout)
    assert environments.selected_venv(borrower) == venv.resolve()
    assert environments.committed_venv(borrower) == venv.resolve()
    # The key itself still hashes the real checkout (the reclaim and owning_home_root rely on it).
    assert environments.install_key(borrower) != environments.install_key(lender_checkout)


def test_positive_control_without_the_checkout_variable_the_borrower_finds_nothing(pinned, monkeypatch):
    """The failure the row is: the root alone hashes the RUNNING checkout, which the lender never installed."""
    from pm import environments

    _, borrower, _, _ = pinned
    monkeypatch.delenv("HERMES_DEPENDENCY_CHECKOUT")
    assert environments.committed_venv(borrower) is None


@pytest.mark.parametrize(("setup", "reason"), [
    ("no_root", "dependency_checkout_without_root"),
    ("relative", "relative_dependency_checkout"),
    ("not_installed", "lender_checkout_not_installed"),
])
def test_a_checkout_borrow_that_cannot_be_honoured_refuses_by_name(pinned, tmp_path, monkeypatch, setup, reason):
    from pm import environments
    from pm._fork_dependency_borrow import BorrowedEnvironmentReadOnly

    _, borrower, _, _ = pinned
    if setup == "no_root":
        monkeypatch.delenv("HERMES_DEPENDENCY_ROOT")
    elif setup == "relative":
        monkeypatch.setenv("HERMES_DEPENDENCY_CHECKOUT", "worktrees/hermes-agent")
    else:
        uninstalled = tmp_path / "never-installed"
        _write_inputs(uninstalled)
        monkeypatch.setenv("HERMES_DEPENDENCY_CHECKOUT", str(uninstalled))
    with pytest.raises(BorrowedEnvironmentReadOnly) as refused:
        environments.selected_venv(borrower)
    assert refused.value.reason == reason
    assert str(refused.value).startswith(f"{reason}: ")


def test_a_one_byte_uv_lock_difference_refuses_dependency_inputs_differ(pinned):
    from pm import environments
    from pm._fork_dependency_borrow import BorrowedEnvironmentReadOnly

    lender_checkout, borrower, _, venv = pinned
    assert environments.selected_venv(borrower) == venv.resolve()  # identical inputs select
    lock = borrower / "uv.lock"
    stat = (lender_checkout / "uv.lock").stat()
    lock.write_text(_INPUTS["uv.lock"].replace("1", "2"), encoding="utf-8")  # same size
    os_utime = __import__("os").utime
    os_utime(lock, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # same mtime: only content tells
    with pytest.raises(BorrowedEnvironmentReadOnly, match=r"dependency_inputs_differ: uv\.lock ") as refused:
        environments.selected_venv(borrower)
    assert refused.value.reason == "dependency_inputs_differ"


def test_a_child_booted_on_the_borrower_runs_the_borrowers_code_on_the_lenders_packages(pinned):
    """D3: the lender environment's editable pointer names the LENDER checkout; the borrower's code must win."""
    import os
    import subprocess
    import sys

    _lender_checkout, borrower, _, venv = pinned
    repo = Path(__file__).resolve().parents[2]
    script = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from pathlib import Path\n"
        "from pm.environments import activate_dependencies, site_packages\n"
        "activate_dependencies(Path(sys.argv[2]))\n"
        "import borrow_probe\n"
        "print(borrow_probe.WHO, borrow_probe.__file__, str(site_packages(Path(sys.argv[3]))) in sys.path)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(repo), str(borrower), str(venv)],
        capture_output=True, text=True, timeout=60, env=dict(os.environ), cwd=str(borrower.parent), check=False)
    assert result.returncode == 0, result.stderr
    who, file, lender_packages_on_path = result.stdout.split()
    assert who == "borrower"
    assert Path(file).resolve().is_relative_to(borrower.resolve())
    assert lender_packages_on_path == "True"
