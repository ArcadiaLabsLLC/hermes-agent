"""Fork-owned tests moved out of ``tests/hermes_cli/test_gateway_windows.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import hermes_cli.gateway as gateway
import hermes_cli.gateway_windows as gateway_windows


def test_launcher_settings_keeps_managed_python_for_explicit_profile(monkeypatch, tmp_path):
    """A sibling cold-start selects its home without reverting to checkout Python."""
    caller = tmp_path / "caller"
    target = tmp_path / "profiles" / "alice"
    caller.mkdir()
    target.mkdir(parents=True)
    managed = str(tmp_path / "managed" / "python.exe")
    monkeypatch.setattr(gateway, "resolve_managed_python", lambda: managed)
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: caller)
    monkeypatch.setattr(gateway, "_profile_arg", lambda home: "--profile alice" if home == str(target) else "")

    python, cwd, home, profile = gateway_windows._launcher_settings(target)

    assert python == managed
    assert home == str(target)
    assert profile == "--profile alice"
    assert cwd == str(caller)
