"""An update whose gateway relaunch failed stays a success but never reports the restart done (FH-WINDOWS-UPDATE-RESTART-RECEIPT-FALSE-SUCCESS).

The live Windows run (2026-11-06) exited 0 with ``restart`` stage ``success`` while its own
completion owed ``gateway_restart`` and no gateway ran. These drive the real post-restart
verification (``_verify_fleet_after_update``) and the real receipt with a FAKE restart retry:
nothing is launched.

Killing mutations (2026-11-08): delete the seam call in ``_verify_fleet_after_update`` ->
``test_a_failed_relaunch_names_it_and_the_recourse`` red (last restart mark ``success``, no
summary); drop ``restart.incomplete = False`` from the proven-retry branch ->
``test_a_proven_retry_settles_the_restart`` red (a ``gateway_restart`` follow-up is still owed).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_cli import update_cmd_fleet as fleet
from hermes_cli import update_cmd_fleet_verify as fleet_verify
from hermes_cli import update_receipt
from hermes_cli import update_restart_recovery
from hermes_cli import update_restart_truth as truth
from hermes_cli.update_inventory import UpdatePlan


@pytest.fixture
def owed_gateway(monkeypatch):
    """A committed update whose fleet restart left the gateway owed (its relaunch failed)."""
    monkeypatch.setattr(fleet_verify, "_print_legacy_units_warning", lambda: None)
    monkeypatch.setattr("hermes_cli.update_cmd._finish_dashboard_update_cleanup", lambda *a, **k: None)
    monkeypatch.setattr("hermes_cli.update_cmd_maint._refresh_dashboard_after_update", lambda **k: set())
    monkeypatch.setattr("hermes_cli.gateway_migrate.maybe_auto_migrate_after_update", lambda: None)
    monkeypatch.setattr(update_receipt, "collect_fleet_versions", lambda **k: [])
    monkeypatch.setattr(update_restart_recovery, "_launch_profile", lambda: "default")
    restart = fleet._GatewayRestartOutcome(True, ["gateway relaunch failed"], [], [], [], [], [], set())
    update_receipt.begin_update_receipt()
    fleet._write_fleet_restart_pending_marker(expected_sha="new")
    # update_completion marks the stage right after the restart phase, before verification.
    update_receipt.record_stage("restart", "success")
    return restart


def _retry(monkeypatch, outcome):
    calls = []

    def retry(profile):
        calls.append(profile)
        return outcome

    monkeypatch.setattr(truth, "retry_gateway_restart", retry)
    return calls


def _verify(restart):
    fleet_verify._verify_fleet_after_update(
        restart, _pre_update_plan=UpdatePlan(runtimes=[]), _windows_gateway_resume=None, update_complete=True)
    return update_receipt.read_latest_receipt()


def _restart_marks(receipt):
    return [mark for mark in receipt.get("stages") or () if mark.get("name") == "restart"]


@pytest.mark.parametrize("outcome", [truth.RetryOutcome.FAILED, truth.RetryOutcome.NOT_PROVEN])
def test_a_failed_relaunch_names_it_and_the_recourse(monkeypatch, capsys, owed_gateway, outcome):
    calls = _retry(monkeypatch, outcome)

    receipt = _verify(owed_gateway)

    assert calls == ["default"]  # retried exactly once
    assert receipt["outcome"] == "success"  # C3: the update itself is never failed
    assert _restart_marks(receipt)[-1]["outcome"] == "failed"
    assert receipt["restart_summary"] == "Updated — the gateway did not restart"
    assert receipt["restart_recourse"] == "hermes gateway restart"
    assert "gateway_restart" in [f["step"] for f in receipt["followups"]]
    assert fleet._fleet_restart_obligation_armed()
    out = capsys.readouterr().out
    assert "Updated — the gateway did not restart. Run: hermes gateway restart" in out


def test_a_proven_retry_settles_the_restart(monkeypatch, owed_gateway):
    calls = _retry(monkeypatch, truth.RetryOutcome.RESTARTED)

    receipt = _verify(owed_gateway)

    assert calls == ["default"]
    assert receipt["outcome"] == "success"
    assert _restart_marks(receipt)[-1] == {**_restart_marks(receipt)[-1], "outcome": "success", "retry": "restarted"}
    assert receipt["restart_summary"] == truth.RESTARTED_ON_RETRY
    assert "restart_recourse" not in receipt
    assert "gateway_restart" not in [f["step"] for f in receipt.get("followups") or ()]


def test_a_clean_restart_is_left_alone(monkeypatch, owed_gateway):
    calls = _retry(monkeypatch, truth.RetryOutcome.FAILED)
    owed_gateway.incomplete = False
    owed_gateway.phase_errors.clear()

    receipt = _verify(owed_gateway)

    assert calls == []
    assert [m["outcome"] for m in _restart_marks(receipt)] == ["success"]
    assert "restart_summary" not in receipt


def _record():
    stages, facts = [], {}
    return stages, facts, (lambda name, outcome, **kw: stages.append((name, outcome, kw))), facts.__setitem__


def test_serve_only_debt_is_not_a_gateway_restart():
    stages, facts, stage, fact = _record()
    restart = SimpleNamespace(incomplete=True, failed_or_stale_units=[], stopped_unmapped_pids=set())

    settled = truth.settle_owed_restart(restart, gateway_owed=False, down_serves={901}, profile="default",
                                        retry=pytest.fail, record_stage=stage, record_fact=fact, say=lambda _: None)

    assert settled == truth.Settlement(None, "", "")
    assert stages == [("restart", "failed", {"owed": "serve"})]
    assert facts == {}


def test_a_proven_retry_keeps_serve_debt_owed():
    _stages, _facts, stage, fact = _record()
    restart = SimpleNamespace(incomplete=True, failed_or_stale_units=[], stopped_unmapped_pids=set())

    truth.settle_owed_restart(restart, gateway_owed=True, stale_serves={902}, profile="work",
                              retry=lambda _: truth.RetryOutcome.RESTARTED, record_stage=stage, record_fact=fact,
                              say=lambda _: None)

    assert restart.incomplete is True


def test_a_raising_retry_is_a_failed_retry_not_a_raise():
    _stages, facts, stage, fact = _record()
    restart = SimpleNamespace(incomplete=True, failed_or_stale_units=[], stopped_unmapped_pids=set())

    def boom(_profile):
        raise OSError("spawn refused")

    settled = truth.settle_owed_restart(restart, gateway_owed=True, profile="work", retry=boom,
                                        record_stage=stage, record_fact=fact, say=lambda _: None)

    assert settled.outcome is truth.RetryOutcome.FAILED
    assert facts["restart_recourse"] == "hermes -p work gateway restart"


def test_retry_proves_a_restart_only_by_a_new_live_process(monkeypatch):
    pids = iter([101, 101])
    monkeypatch.setattr(truth, "_host_gateway_pid", lambda: next(pids))
    monkeypatch.setattr(update_restart_recovery, "_run_profile_restart", lambda profile, run: True)
    monkeypatch.setattr(update_restart_recovery, "_systemd_verified_active", lambda profile, run: False)
    assert truth.retry_gateway_restart("default") is truth.RetryOutcome.NOT_PROVEN

    pids = iter([101, 202])
    assert truth.retry_gateway_restart("default") is truth.RetryOutcome.RESTARTED

    monkeypatch.setattr(update_restart_recovery, "_run_profile_restart", lambda profile, run: False)
    pids = iter([0, 0])
    assert truth.retry_gateway_restart("default") is truth.RetryOutcome.FAILED


def test_a_failed_windows_resume_after_a_marked_restart_names_it(monkeypatch, capsys, owed_gateway):
    """The live 2026-11-06 order: the fleet restart phase came back clean (stage marked ``success``),
    THEN the Windows gateway resume failed; the update stays a success, the restart is not done.

    Killing mutation (2026-11-10): delete the ``settle_owed_restart`` seam call in
    ``_verify_fleet_after_update`` -> red (last ``restart`` mark ``success``, no summary)."""
    import hermes_cli.main as main_mod

    from hermes_cli.update_cmd_windows import _resume_windows_gateways_and_merge_outcome

    calls = _retry(monkeypatch, truth.RetryOutcome.FAILED)
    owed_gateway.incomplete = False
    owed_gateway.phase_errors.clear()

    def resume_fails(_token):
        raise OSError("gateway exited during boot")

    monkeypatch.setattr(main_mod, "_resume_windows_gateways_after_update", resume_fails)
    token = {"resume_needed": True, "platform": "windows", "services": [], "relaunched_profiles": []}
    _resume_windows_gateways_and_merge_outcome(owed_gateway, token, False)
    receipt = _verify(owed_gateway)

    assert calls == ["default"]
    assert receipt["outcome"] == "success"
    assert [m["outcome"] for m in _restart_marks(receipt)] == ["success", "failed"]
    assert receipt["restart_summary"] == truth.NOT_RESTARTED
    assert receipt["restart_recourse"] == "hermes gateway restart"
    assert "Run: hermes gateway restart" in capsys.readouterr().out
