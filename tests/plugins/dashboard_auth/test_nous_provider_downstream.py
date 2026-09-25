"""Fork-owned half of ``tests/plugins/dashboard_auth/test_nous_provider.py``.

``plugins/dashboard_auth/_shared.py`` reads ``load_config_readonly`` in the fork;
upstream's ``patch_config`` stubs ``load_config``, and the
``config_reads_through_load_config`` row in ``tests/_downstream/id_markers.py``
routes one to the other. This is the anti-vacuity check for that route: the stub
must reach the plugin's own read path. ``patch_config`` is upstream's.
"""

from __future__ import annotations

import plugins.dashboard_auth.nous as nous_plugin
from tests.plugins.dashboard_auth.test_nous_provider import (
    TestConfigYamlSource as _UpstreamConfigYamlSource,
)


class TestConfigYamlSource:
    patch_config = _UpstreamConfigYamlSource.patch_config

    def test_the_stub_is_the_accessor_the_plugin_reads(self, patch_config):
        """ANTI-VACUITY for this whole class: the stub has to reach the
        plugin's own read path, or every "config.yaml" assertion below is
        describing an empty config instead of the one the test wrote."""

        patch_config({"client_id": "agent:probe", "portal_url": "https://probe"})
        assert nous_plugin._load_config_oauth_section() == {
            "client_id": "agent:probe",
            "portal_url": "https://probe",
        }
