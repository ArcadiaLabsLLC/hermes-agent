"""Run-serialization S2: a child spawned inside a turn carries THAT turn's root and auth home.

Plan: ``docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md`` S2.

Every case binds with ``export_env=False`` — the mode that writes nothing into
``os.environ`` — and runs two bindings at once on two threads, so a child env that is
right can only have come from the context, never from a process-wide write that the
other thread could see.

Kill-mutation: delete the ``apply_run_context_child_env(env)`` call in
``tools/environments/local.py::_apply_profile_home``. Every factory then hands both
children the process env's (absent) root and auth home, and the overlap test reds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from agent_runtime.profile_context import PersonaProfileBinding, persona_profile_context
from agent_runtime.profile_home import reset_hermes_auth_home_override, set_hermes_auth_home_override

_KEYS = ("HERMES_AGENT_RUNTIME_ROOT", "HERMES_AUTH_HOME", "HERMES_HOME")


def _binding(tmp_path: Path, name: str) -> PersonaProfileBinding:
    home = tmp_path / "profiles" / name
    (home / "home").mkdir(parents=True)
    return PersonaProfileBinding(
        persona_id=f"persona_{name}", hermes_profile=name, profile_home=home,
        readiness="ready", summary="profile exists",
    )


def _child_view(env: dict[str, str]) -> dict[str, str]:
    """What a real child process sees: spawn it with *env* and let it print."""

    script = "import json, os; print(json.dumps({k: os.environ.get(k, '') for k in %r}))" % (_KEYS,)
    out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                         text=True, timeout=60, check=True)
    return json.loads(out.stdout)


@pytest.fixture
def no_process_root(monkeypatch):
    monkeypatch.delenv("HERMES_AGENT_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)


def test_two_overlapping_runs_each_hand_their_child_their_own_root_and_auth_home(tmp_path, no_process_root):
    from tools.environments.local import (
        _sanitize_subprocess_env,
        build_subprocess_env,
        hermes_subprocess_env,
    )

    both_inside = threading.Barrier(2, timeout=30)
    seen: dict[str, dict[str, dict[str, str]]] = {}
    errors: list[BaseException] = []

    def run(name: str) -> None:
        try:
            binding = _binding(tmp_path, name)
            auth_token = set_hermes_auth_home_override(str(tmp_path / f"auth-{name}"))
            try:
                with persona_profile_context(binding, runtime_root=tmp_path / f"root-{name}",
                                             export_env=False):
                    both_inside.wait()  # the other run is bound too, right now
                    envs = {
                        "terminal": _sanitize_subprocess_env(dict(os.environ)),
                        "non_terminal": hermes_subprocess_env(),
                        "unscrubbed": build_subprocess_env(scrub_secrets=False),
                    }
                    views = {lane: _child_view(env) for lane, env in envs.items()}
                    both_inside.wait()  # neither leaves before both children ran
            finally:
                reset_hermes_auth_home_override(auth_token)
            seen[name] = views
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in ("alpha", "beta")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(90)
    assert not errors, errors
    for name in ("alpha", "beta"):
        for lane, view in seen[name].items():
            assert view["HERMES_AGENT_RUNTIME_ROOT"] == str(tmp_path / f"root-{name}"), (name, lane, view)
            assert view["HERMES_AUTH_HOME"] == str(tmp_path / f"auth-{name}"), (name, lane, view)
            assert view["HERMES_HOME"] == str(tmp_path / "profiles" / name), (name, lane, view)
    # Nothing reached the process env: the children's answers came from the context.
    assert "HERMES_AGENT_RUNTIME_ROOT" not in os.environ
    assert "HERMES_AUTH_HOME" not in os.environ


def test_an_unbound_context_leaves_the_child_env_alone(no_process_root):
    """Positive control for the seam's no-op arm: with nothing bound, nothing is added."""

    from tools.environments.local import hermes_subprocess_env

    env = hermes_subprocess_env()
    assert "HERMES_AGENT_RUNTIME_ROOT" not in env
    assert "HERMES_AUTH_HOME" not in env
