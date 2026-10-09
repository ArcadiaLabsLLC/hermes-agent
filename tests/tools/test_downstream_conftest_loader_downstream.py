"""The fork half of ``tests/tools/conftest.py`` rides it by registration, not import.

When pytest registers this directory's conftest, the root ``conftest.py`` grafts
``tests._downstream.tools_conftest``'s fixtures onto it (so they are scoped here, and the
upstream half's fixtures still run beside them) and registers its hooks as
``tests._downstream.tools_conftest:hooks``.
"""


def test_directory_half_is_registered_with_directory_scope(request):
    assert "_downstream_behavioral_vars_scrubbed" in request.fixturenames  # root half
    # The UPSTREAM half shares this directory; registering the fork half beside it
    # must not evict it (pytest 9.1 holds one pending conftest per directory).
    assert "_materialize_mcp_sdk_symbols" in request.fixturenames
    assert "_no_live_process_table" not in request.fixturenames  # hermes_cli's half stays there
    assert request.config.pluginmanager.get_plugin("tests._downstream.tools_conftest:hooks") is not None
