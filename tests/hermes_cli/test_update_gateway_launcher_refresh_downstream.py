"""Fork-owned tests moved out of ``tests/hermes_cli/test_update_gateway_launcher_refresh.py`` (seam Stage 5).

The fork's legacy-console warning (``task_action_is_console_less``) was deleted by lane
h13-del: upstream's Scheduled Task drift reconcile (#113670) is the one authority that
names — and on ``hermes update`` / ``gateway start`` repairs — a task still bound to the
pre-#45610 ``.cmd`` action. This pins that it does, for exactly that registration.
"""

from __future__ import annotations

from pathlib import Path

import hermes_cli.gateway_windows as gateway_windows

_VBS = Path(r"C:\hermes\gateway-service\Hermes_Gateway_alice.vbs")
_EXEC_VBS = f'<Command>wscript.exe</Command>\n      <Arguments>//B //Nologo "{_VBS}"</Arguments>'


def _template() -> str:
    xml = gateway_windows._build_scheduled_task_xml("Hermes_Gateway_alice", _VBS, r"PC\alice")
    assert _EXEC_VBS in xml, "the template's Exec block changed shape — re-derive the legacy fixture"
    return xml


def test_drift_names_a_task_still_bound_to_the_legacy_cmd_action():
    """A pre-#45610 registration runs the ``.cmd`` directly (cmd.exe owns a VISIBLE
    console, so closing it kills the gateway). Everything else current, the drift
    reconcile must still see it."""
    template = _template()
    legacy = template.replace(_EXEC_VBS, f"<Command>{_VBS.with_suffix('.cmd')}</Command>")

    assert gateway_windows.compare_scheduled_task_drift(legacy, template) == ["missing: launcher arguments"]


def test_positive_control_the_current_action_is_not_drift():
    template = _template()

    assert gateway_windows.compare_scheduled_task_drift(template, template) == []
