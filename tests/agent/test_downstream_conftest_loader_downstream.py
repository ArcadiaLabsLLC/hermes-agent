"""The fork half of ``tests/agent/conftest.py`` rides it by registration, not import.

When pytest registers this directory's conftest, the root ``conftest.py`` grafts
``tests._downstream.agent_conftest``'s fixtures onto it (so they are scoped here, and the
upstream half's fixtures still run beside them) and registers its hooks as
``tests._downstream.agent_conftest:hooks``.
"""


def test_directory_half_is_registered_with_directory_scope(request):
    assert "_downstream_behavioral_vars_scrubbed" in request.fixturenames  # root half
    assert "_fresh_structured_output_memo" in request.fixturenames  # upstream half, same directory
    assert request.config.pluginmanager.get_plugin("tests._downstream.agent_conftest:hooks") is not None
