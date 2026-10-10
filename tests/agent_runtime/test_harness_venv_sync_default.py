"""Owner 2026-09-29: harness processes keep upstream's startup venv sync off.

``agent_runtime.process_env_defaults`` setdefault()s ``HERMES_DISABLE_LAZY_INSTALLS=1`` in
the processes the fork composes (the serve, conversation workers; v0216 plan §2 moved it
out of the plugin's ``register()``); upstream's ``hermes_cli.venv_sync`` reads it and skips
its sync-and-relaunch. The operator's own value is the opt-out.
"""

from __future__ import annotations

from agent_runtime.process_env_defaults import apply_harness_process_env_defaults


def test_harness_processes_keep_startup_venv_sync_off():
    env: dict[str, str] = {}
    apply_harness_process_env_defaults(env)
    assert env["HERMES_DISABLE_LAZY_INSTALLS"] == "1"


def test_the_operator_value_wins():
    """Positive control: same defaults, operator set ``0`` first -> kept."""
    env = {"HERMES_DISABLE_LAZY_INSTALLS": "0"}
    apply_harness_process_env_defaults(env)
    assert env["HERMES_DISABLE_LAZY_INSTALLS"] == "0"
