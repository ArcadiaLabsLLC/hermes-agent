"""The process version identity is per test: whatever a test leaves in it is undone at teardown.

``tests/conftest.py`` seeds ``hermes_cli.version_info._cached_version_info`` once per process (the
shape a shallow CI checkout resolves to), and every bundled provider plugin bakes
``HermesAgent/<base_version>`` into its headers at import. ``tests/hermes_cli/test_version_info.py``
resets and re-resolves that cache and left its last answer behind, so a later file in the same
process compared a header baked from the seed with an identity the earlier test resolved
(``test_fireworks_profile::test_user_agent_identifies_hermes``, ``test_provider_attribution_headers``:
``'HermesAgent/unknown' == 'HermesAgent/0.22.2'``; fork-hygiene-queue row, q-version report).

The autouse ``_version_info_scope`` (re-exported by ``conftest_plugin``, so it tears down after
every conftest fixture and after the test's own monkeypatch undo) records the cache at setup and puts
that value back at teardown. Nothing is resolved here: a module that is not imported costs a dict
lookup.
"""

from __future__ import annotations

import sys

import pytest

_ABSENT = object()


@pytest.fixture(autouse=True)
def _version_info_scope():
    module = sys.modules.get("hermes_cli.version_info")
    before = getattr(module, "_cached_version_info", _ABSENT) if module is not None else _ABSENT
    yield
    if before is not _ABSENT:
        module._cached_version_info = before
