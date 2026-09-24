"""Fork-owned tests moved out of ``tests/gateway/test_feishu.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class TestDedupTTL(unittest.TestCase):
    def test_dedup_state_path_follows_a_home_that_moves_after_construction(self):
        """The dedup-state path is resolved live, and __init__ reads nothing.

        Both halves used to be wrong in one line: ``__init__`` did
        ``self._dedup_state_path = get_hermes_home() / ...`` and then called
        ``_load_seen_message_ids()``. That froze the path against whatever
        ``HERMES_HOME`` was set at construction and made construction itself
        depend on the home being resolvable and readable — so an adapter built
        before a profile switch kept writing dedup state into the previous
        profile's home, and an adapter built under a scrubbed environment blew
        up in the constructor rather than on the persistence path that
        actually wants a home.
        """
        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter

        with tempfile.TemporaryDirectory() as home_a, \
                tempfile.TemporaryDirectory() as home_b:
            seeded = Path(home_b) / "feishu_seen_message_ids.json"
            seeded.write_text(
                json.dumps({"message_ids": {"om_seeded": time.time()}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HERMES_HOME": home_a}, clear=True):
                adapter = FeishuAdapter(PlatformConfig())
                # Constructor did no I/O: nothing hydrated yet.
                self.assertEqual(adapter._seen_message_ids, {})

            # The home moves AFTER construction.
            with patch.dict(os.environ, {"HERMES_HOME": home_b}, clear=True):
                self.assertEqual(adapter._dedup_state_path, seeded)
                # First dedup decision hydrates from the home in force NOW,
                # not the one that happened to be set at construction.
                with patch.object(adapter, "_persist_seen_message_ids"):
                    self.assertTrue(asyncio.run(adapter._is_duplicate("om_seeded")))
