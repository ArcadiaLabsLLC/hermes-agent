"""Fork-owned tests moved out of ``tests/hermes_cli/test_restart_plan_reconciliation.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import pytest
from hermes_cli.update_inventory import (
    match_runtime_outcomes,
    report_unaccounted_runtimes,
)

from tests.hermes_cli.test_restart_plan_reconciliation import (  # noqa: F401 — upstream names the moved tests use
    _plan,
    _serve,
)


@pytest.mark.platforms("linux")
def test_unaccounted_serve_report_names_the_systemd_unit_on_linux(capsys):
    """The Linux half of the remedy above: a unit-managed serve is named by its unit.

    Positive control for the platform gate — without it, "no systemd line" is equally true
    on a host where the whole report failed to render.
    """
    outcomes = match_runtime_outcomes(
        _plan(_serve("default", 900)),
        restarted_services=["hermes-gateway"], relaunched_profiles=[],
        externally_supervised_profiles=[], killed_pids=set(), failed_units=[],
    )
    assert report_unaccounted_runtimes(outcomes) is True
    out = capsys.readouterr().out
    assert "serve [default] pid 900" in out
    assert "hermes-serve.service" in out
