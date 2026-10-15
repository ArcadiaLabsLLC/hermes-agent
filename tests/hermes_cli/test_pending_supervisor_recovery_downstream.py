"""Fork-owned tests moved out of ``tests/hermes_cli/test_pending_supervisor_recovery.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from hermes_cli import gateway


def test_legacy_launchd_labels_answer_no_units_on_a_host_without_pwd(monkeypatch, tmp_path):
    """The launchd restart pass reaches ``legacy_launchd_labels_for_install`` on every host.
    ``pwd`` is POSIX-only; a Windows host used to die with ModuleNotFoundError before the helper's
    fail-closed guard could answer. An unimportable ``pwd`` now reads as "no legacy units"."""
    import sys

    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_default_hermes_root", lambda: tmp_path / "hermes-root")
    monkeypatch.setitem(sys.modules, "pwd", None)  # ``import pwd`` raises ImportError on any platform
    assert gateway.legacy_launchd_labels_for_install() == []
