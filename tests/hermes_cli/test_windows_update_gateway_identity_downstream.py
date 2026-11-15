"""A Windows update replays the gateway it actually paused, even after profile selection changes."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gateway.control_socket import build_identify_payload
from hermes_cli import _subprocess_compat, main, update_cmd_windows


@pytest.mark.platforms("windows")
@pytest.mark.parametrize(
    ("updater", "target", "mapped"),
    [
        ("default", "default", True),
        ("sticky", "default", True),
        ("default", "default", False),
        ("sticky", "default", False),
        ("default", "standalone", True),
    ],
)
def test_windows_update_watcher_preserves_the_paused_identity(tmp_path, monkeypatch, updater, target, mapped):
    root = tmp_path / "hermes"
    homes = {"default": root, **{name: root / "profiles" / name for name in ("sticky", "standalone")}}
    for home in homes.values():
        home.mkdir(parents=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    (root / "active_profile").write_text("sticky\n", encoding="utf-8")
    # The standalone uses no bot token. An inherited token would compete with the host's poller.
    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=fixture-root-token\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(homes[updater]))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fixture-root-token" if updater == "default" else "fixture-sticky-token")
    monkeypatch.delenv("HERMES_SUPERVISED_CHILD", raising=False)
    monkeypatch.delenv("HERMES_GATEWAY_PROFILE_PIN", raising=False)
    monkeypatch.delenv("HERMES_PROFILE_PINNED", raising=False)
    monkeypatch.setattr(main, "_explicit_cli_profile", None)

    launches = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: launches.append((argv, kwargs)))
    monkeypatch.setattr(_subprocess_compat, "pid_exists_stdlib", lambda _pid: False)
    paused_argv = [sys.executable, "-m", "hermes_cli.main", "gateway", "run"]
    paused = {"pid": 4242, "argv": paused_argv, "home": str(homes[target])}
    profiles = {target: paused["pid"]} if mapped else {}
    unmapped = [] if mapped else [paused]

    assert update_cmd_windows._relaunch_paused_gateways(profiles, unmapped) == (profiles, unmapped)
    (watcher_argv, watcher_kwargs), = launches
    with monkeypatch.context() as watcher:
        watcher.setattr(sys, "argv", ["-c", *watcher_argv[3:]])
        watcher.setattr(sys, "path", list(sys.path))
        with patch.dict(os.environ, watcher_kwargs.get("env") or os.environ.copy(), clear=True):
            # Execute the same watcher program Windows starts, with only its process I/O stubbed.
            exec(watcher_argv[2], {})

    _, (child_argv, child_kwargs) = launches
    if not mapped:
        assert child_argv[1:] == paused_argv[1:]
    child_args = child_argv[4:] if mapped else child_argv[3:]
    with monkeypatch.context() as child:
        child.setattr(sys, "argv", ["hermes", *child_args])
        with patch.dict(os.environ, child_kwargs["env"], clear=True):
            main._apply_profile_override()
            assert Path(os.environ["HERMES_HOME"]) == homes[target]
            assert build_identify_payload()["profile"] == target
            assert os.environ.get("TELEGRAM_BOT_TOKEN") == (
                "fixture-root-token" if target == "default" else None
            )
