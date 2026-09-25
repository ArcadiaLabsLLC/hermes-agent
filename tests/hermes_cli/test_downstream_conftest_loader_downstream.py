"""The fork half of ``tests/hermes_cli/conftest.py`` rides it by registration, not import.

The root ``conftest.py`` registers ``tests._downstream.hermes_cli_conftest`` under a
``tests/hermes_cli/_downstream_conftest.py`` name when pytest registers this
directory's conftest, so its fixtures are scoped here and its hooks run.
"""

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]


def test_directory_half_is_registered_with_directory_scope(request):
    assert "_downstream_behavioral_vars_scrubbed" in request.fixturenames  # root half
    assert "_no_live_process_table" in request.fixturenames
    assert "_tirith_config_value_under_test" not in request.fixturenames  # tools' half stays in tools
    name = str(_TESTS / "hermes_cli" / "_downstream_conftest.py")
    assert request.config.pluginmanager.get_plugin(name) is not None
