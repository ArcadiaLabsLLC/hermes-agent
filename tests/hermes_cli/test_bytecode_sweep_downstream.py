"""Fork-owned tests moved out of ``tests/hermes_cli/test_bytecode_sweep.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import logging
import pytest
from hermes_cli import _boot_clock
from hermes_cli import main as hermes_main
from hermes_cli import _bytecode_sweep as sweep

from tests.hermes_cli.test_bytecode_sweep import (  # noqa: F401 — upstream names the moved tests use
    _make_pycache,
    _make_repo,
)


@pytest.fixture
def _clean_sweep_anchor():
    _boot_clock.reset_for_tests()
    yield
    _boot_clock.reset_for_tests()


def test_a_sweep_records_its_duration_for_the_boot_frame(
    monkeypatch, tmp_path, caplog, _clean_sweep_anchor
):
    """Anti-vacuity. *Mutation:* drop the ``record_bytecode_sweep_ms`` call.
    *Probed field:* ``_boot_clock.BYTECODE_SWEEP_MS`` is not None afterwards —
    a module global this test cleared itself, which nothing else in the sweep
    writes, so the mutant cannot set it by taking any other branch. Second,
    independent witness: the log line's ``swept_ms=`` token, which lives in a
    different mechanism (the ``logger.info`` format string) and would survive a
    mutation of the recorder, and vice versa.
    """

    repo = _make_repo(tmp_path, sha="c" * 40)
    _make_pycache(repo)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    (repo / sweep._BYTECODE_FINGERPRINT_FILE).write_text(
        "git:refs/heads/main:" + "a" * 40, encoding="utf-8"
    )

    assert _boot_clock.BYTECODE_SWEEP_MS is None
    with caplog.at_level(logging.INFO, logger=sweep.logger.name):
        sweep._sweep_stale_bytecode_if_checkout_changed()

    assert _boot_clock.BYTECODE_SWEEP_MS is not None
    assert _boot_clock.BYTECODE_SWEEP_MS >= 0
    purge_lines = [r.getMessage() for r in caplog.records if "__pycache__" in r.getMessage()]
    assert len(purge_lines) == 1
    assert "swept_ms=" in purge_lines[0]


def test_a_no_op_sweep_still_records_a_duration(
    monkeypatch, tmp_path, _clean_sweep_anchor
):
    """The cheap path is measured too — otherwise every warm boot looks unmeasured.

    Anti-vacuity. *Mutation:* record only inside the ``if removed:`` branch (the
    natural place a first draft puts it). *Probed field:*
    ``BYTECODE_SWEEP_MS`` after a run that takes the ``recorded == fingerprint``
    early return, where ``removed`` is never even computed. "The sweep decided in
    2 ms that it had nothing to do" is an answer; a missing key would be read as
    "nobody measured", and a warm boot is the baseline every cold-boot claim is
    compared against.
    """

    repo = _make_repo(tmp_path, sha="d" * 40)
    cache = _make_pycache(repo)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    # Stamp already matches — the early return.
    (repo / sweep._BYTECODE_FINGERPRINT_FILE).write_text(
        "git:refs/heads/main:" + "d" * 40, encoding="utf-8"
    )

    sweep._sweep_stale_bytecode_if_checkout_changed()

    assert cache.exists(), "nothing should have been swept"
    assert _boot_clock.BYTECODE_SWEEP_MS is not None


def test_a_non_git_install_still_records_a_duration(
    monkeypatch, tmp_path, _clean_sweep_anchor
):
    """The other early return: no ``.git``, so no fingerprint, so no sweep."""

    repo = tmp_path / "zip-install"
    (repo / "hermes_cli").mkdir(parents=True)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)

    sweep._sweep_stale_bytecode_if_checkout_changed()

    assert _boot_clock.BYTECODE_SWEEP_MS is not None
