"""Public name for a doctor section banner.

A plugin that adds its own ``hermes doctor`` output wants its section to look
like every other one. The private spelling stays as an alias bound to the same
object; doctor reads the public name, so overriding it is what takes effect.
"""

from hermes_cli import doctor_report


def test_public_name_is_the_private_helper():
    assert doctor_report.section is doctor_report._section


def test_section_prints_a_titled_banner(capsys):
    doctor_report.section("Plugin checks")
    assert "Plugin checks" in capsys.readouterr().out


def test_overriding_section_reaches_the_live_doctor_checks(monkeypatch):
    from hermes_cli import doctor_live

    titles = []
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", dict)
    monkeypatch.setattr(doctor_live, "_KEYED_PROBES", {})
    monkeypatch.setattr(doctor_live, "_probe_browser",
                        lambda timeout: doctor_live.ProbeResult("Browser", "skip", ""))
    monkeypatch.setattr(doctor_live, "section", titles.append)
    doctor_live.run_live_checks([])
    assert titles == ["Live Backend Probes (opt-in, real calls)"]
