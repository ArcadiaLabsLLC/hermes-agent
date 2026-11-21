"""Serve start reconciles the default model of an install signed in before the sign-in seed existed.

Row ``RT-FU-A-PHONE-SIGNED-IN-BEFORE-AN-UPGRADE-GETS-A-DEFAULT-MODEL-TOO``: the hook is injected and
OFF in ``serve_loop`` (it writes ``config.yaml``), ON in both entry points, and runs once after
``ready`` on its own thread under the serve's own home. The reconcile's decisions are tested in
``test_runtime_default_model.py``.
"""

from __future__ import annotations

import io
import json
import threading

from hermes_cli.harness_parts.serve import serve_loop
from hermes_cli.harness_parts.serve import in_memory

SHUTDOWN = json.dumps({"op": "shutdown"}) + "\n"


def test_serve_start_runs_the_reconcile_once_after_ready_off_the_boot_thread(monkeypatch, tmp_path):
    """Killing mutations: drop ``self._start_default_model_reconcile()`` from
    ``_start_background_workers`` -> the hook never runs, red; drop the thread's
    ``process_home_scope`` -> it reads the ambient home flipped after boot captured its own, red."""
    from hermes_constants import get_hermes_home

    serve_home = get_hermes_home()
    calls: list[tuple[str, object]] = []
    boot_thread = threading.current_thread().name

    def reconcile():
        calls.append((threading.current_thread().name, get_hermes_home()))

    def flip_ambient_home() -> str:
        # Runs after the serve captured its home; a persona prewarm's env mirror looks like this.
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "someone-elses-profile"))
        return "flipped"

    out = io.StringIO()
    code = serve_loop(iter([SHUTDOWN]), out, pool_size=1, default_model_reconcile=reconcile,
                      skill_install=flip_ambient_home)

    assert code == 0
    assert any(json.loads(line).get("event") == "ready" for line in out.getvalue().splitlines() if line)
    assert len(calls) == 1
    thread_name, home = calls[0]
    assert thread_name == "harness-serve-default-model" != boot_thread
    assert home == serve_home


def test_the_embedded_serve_turns_the_reconcile_on_and_a_caller_can_replace_it():
    """The phone's entry. Killing mutation: drop ``default_model_reconcile`` from
    ``EmbeddedServe``'s default options -> the phone never reconciles, red."""
    assert in_memory.EmbeddedServe(lambda _line: None)._options["default_model_reconcile"] is (
        in_memory._reconcile_default_model)

    def own():
        return None

    assert in_memory.EmbeddedServe(lambda _line: None, default_model_reconcile=own)._options[
        "default_model_reconcile"] is own
