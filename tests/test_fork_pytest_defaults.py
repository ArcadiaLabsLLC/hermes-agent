"""The fork's pytest defaults live in ``tests/_downstream/conftest_plugin.py``,
not in pyproject's ``[tool.pytest.ini_options]`` (which stays upstream's).

Asked of the running config, not the source: pytest-timeout folds its settings
into ``config._env_timeout`` / ``_env_timeout_method`` in its own
``pytest_configure``, so these are the values every test in the run is held to.
Killing mutation: drop ``config.option.timeout = FORK_TEST_TIMEOUT_SECONDS`` ->
``(None, 'thread') == (30.0, 'thread')`` fails.
"""

import pytest

pytest.importorskip("pytest_timeout", reason="requirements-fork-dev.txt is not installed")


def test_the_per_test_timeout_defaults_to_the_fork_cap(request):
    config = request.config
    if "--timeout" in " ".join(config.invocation_params.args):
        pytest.skip("an explicit --timeout on the command line wins, by design")
    assert (config._env_timeout, config._env_timeout_method) == (30.0, "thread")


def test_the_fork_markers_are_registered(request):
    registered = " ".join(request.config.getini("markers"))
    assert "real_venv_pip:" in registered
    assert "real_agent_browser_probe:" in registered
