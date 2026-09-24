"""Fork-owned tests moved out of ``tests/hermes_cli/test_config.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from hermes_cli.config import (
    DEFAULT_CONFIG,
)



class TestBackgroundNotificationsConciseMigration:

    def test_default_config_preserves_fork_result_delivery(self):
        assert DEFAULT_CONFIG["display"]["background_process_notifications"] == "result"
