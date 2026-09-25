"""Fork-owned tests moved out of ``tests/hermes_cli/test_gateway.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

import sys
from types import ModuleType
import hermes_cli.gateway as gateway

from tests.hermes_cli.test_gateway import (  # noqa: F401 — upstream names the moved tests use
    inert_task_scheduler_probe,
)


def _install_fake_gateway_run(monkeypatch, start_gateway):
    module = ModuleType("gateway.run")
    module.start_gateway = start_gateway

    def _exit_after_graceful_shutdown(code):
        if code:
            raise SystemExit(code)

    setattr(module, "_exit_after_graceful_shutdown", _exit_after_graceful_shutdown)
    monkeypatch.setitem(sys.modules, "gateway.run", module)
    # ``run_gateway()`` calls ``refresh_systemd_unit_if_needed()`` on every
    # invocation so that restart settings stay current after exit-code-75
    # respawns. That helper writes to ``Path.home() / ".config/systemd/user
    # /hermes-gateway.service"`` and runs ``systemctl --user daemon-reload``
    # — both target the *real* user environment because the conftest only
    # sandboxes ``HERMES_HOME``, not ``HOME``. Tests that drive
    # ``run_gateway()`` end-to-end with a fake ``start_gateway`` MUST stub
    # the refresh call too, or every run rewrites the developer's installed
    # unit (baking in the test's pytest-tmp ``HERMES_HOME`` value, which
    # systemd then uses on the next boot — silently breaking the gateway
    # for the developer).
    monkeypatch.setattr(gateway, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(
        gateway, "refresh_systemd_unit_if_needed", lambda system=False: False
    )
    # Neutralize the supervised-gateway conflict guard by default so these
    # end-to-end tests don't trip over a launchd/systemd gateway that happens
    # to be installed+running on the developer's machine. Conflict-guard tests
    # override this snapshot after calling the helper.
    monkeypatch.setattr(
        gateway,
        "get_gateway_runtime_snapshot",
        lambda *a, **k: gateway.GatewayRuntimeSnapshot(manager="manual process"),
    )


def test_command_matches_profile_does_not_match_prefix_collision():
    alice_home = r"x:\\eternia\\.hermes\\profiles\\alice"

    assert gateway._command_matches_profile(
        r'"pythonw.exe" -m hermes_cli.main --profile alice gateway run',
        profile_name="alice",
        hermes_home=alice_home,
    )
    assert gateway._command_matches_profile(
        r'"pythonw.exe" -m hermes_cli.main -p alice gateway run',
        profile_name="alice",
        hermes_home=alice_home,
    )
    assert not gateway._command_matches_profile(
        r'"pythonw.exe" -m hermes_cli.main --profile aliceimagecron gateway run',
        profile_name="alice",
        hermes_home=alice_home,
    )
    assert not gateway._command_matches_profile(
        r'"pythonw.exe" -m hermes_cli.main -p aliceimagecron gateway run',
        profile_name="alice",
        hermes_home=alice_home,
    )


def test_command_matches_profile_home_uses_path_boundary():
    alice_home = r"x:\\eternia\\.hermes\\profiles\\alice"

    assert gateway._command_matches_profile(
        r'set HERMES_HOME=X:\\Eternia\\.hermes\\profiles\\alice && hermes gateway run',
        profile_name="alice",
        hermes_home=alice_home,
    )
    assert not gateway._command_matches_profile(
        r'set HERMES_HOME=X:\\Eternia\\.hermes\\profiles\\aliceimagecron && hermes gateway run',
        profile_name="alice",
        hermes_home=alice_home,
    )


def test_run_gateway_windows_foreground_keeps_ctrl_c_enabled(monkeypatch):
    calls = []

    def fake_start_gateway(*, replace, verbosity, force=False):
        calls.append((replace, verbosity))
        return object()

    class _TTY:
        def isatty(self):
            return True

    signal_calls = []

    def fake_signal(sig, handler):
        signal_calls.append((sig, handler))

    _install_fake_gateway_run(monkeypatch, fake_start_gateway)
    monkeypatch.setattr(gateway, "is_windows", lambda: True)
    monkeypatch.setattr(gateway, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway.sys, "stdin", _TTY())
    monkeypatch.delenv("HERMES_GATEWAY_DETACHED", raising=False)
    monkeypatch.setattr(gateway.signal, "signal", fake_signal)
    monkeypatch.setattr(gateway.asyncio, "run", lambda coro: True)

    gateway.run_gateway()

    assert calls == [(False, 0)]
    assert (gateway.signal.SIGINT, gateway.signal.SIG_IGN) not in signal_calls


def test_run_gateway_windows_detached_absorbs_console_controls(monkeypatch):
    calls = []

    def fake_start_gateway(*, replace, verbosity, force=False):
        calls.append((replace, verbosity))
        return object()

    class _TTY:
        def isatty(self):
            return True

    signal_calls = []

    def fake_signal(sig, handler):
        signal_calls.append((sig, handler))

    _install_fake_gateway_run(monkeypatch, fake_start_gateway)
    monkeypatch.setattr(gateway, "is_windows", lambda: True)
    monkeypatch.setattr(gateway, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway.sys, "stdin", _TTY())
    monkeypatch.setenv("HERMES_GATEWAY_DETACHED", "1")
    monkeypatch.setattr(gateway.signal, "signal", fake_signal)
    monkeypatch.setattr(gateway.asyncio, "run", lambda coro: True)

    gateway.run_gateway()

    assert calls == [(False, 0)]
    assert (gateway.signal.SIGINT, gateway.signal.SIG_IGN) in signal_calls
