"""The fork half of ``tests/tools/conftest.py`` rides it by registration, not import.

The root ``conftest.py`` registers ``tests._downstream.tools_conftest`` under a
``tests/tools/_downstream_conftest.py`` name when pytest registers this
directory's conftest, so its fixtures are scoped here and its hooks run.
"""

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]


def test_directory_half_is_registered_with_directory_scope(request):
    assert "_downstream_behavioral_vars_scrubbed" in request.fixturenames  # root half
    assert "_tirith_config_value_under_test" in request.fixturenames
    assert "_no_live_process_table" not in request.fixturenames  # hermes_cli's half stays there
    name = str(_TESTS / "tools" / "_downstream_conftest.py")
    assert request.config.pluginmanager.get_plugin(name) is not None
