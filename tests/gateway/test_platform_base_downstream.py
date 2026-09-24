"""Fork-owned tests moved out of ``tests/gateway/test_platform_base.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from gateway.platforms.base import (
    BasePlatformAdapter,
    MEDIA_DELIVERY_SAFE_ROOTS,
    _log_safe_path,
)


class TestExtractMedia:
    def test_media_tag_supports_unquoted_windows_drive_paths(self):
        content = r"MEDIA:X:\HermesCache\images\alice.png"
        media, cleaned = BasePlatformAdapter.extract_media(content)
        assert media == [(r"X:\HermesCache\images\alice.png", False)]
        assert cleaned == ""

    def test_media_tag_supports_quoted_windows_drive_paths_with_spaces(self):
        content = r"Here\nMEDIA:'X:\Hermes Cache\images\alice cat.png'\nDone"
        media, cleaned = BasePlatformAdapter.extract_media(content)
        assert media == [(r"X:\Hermes Cache\images\alice cat.png", False)]
        assert "Here" in cleaned
        assert "Done" in cleaned
        assert "MEDIA:" not in cleaned


class TestMediaDeliveryDiagnosability:
    def test_extract_media_tolerates_crafted_null_path(self):
        """extract_media must not raise on a crafted ~\\x00 MEDIA tag."""
        content = "here\nMEDIA:`~\x00evil.png`\ntrailing"
        # Must not raise ValueError("embedded null byte").
        media, cleaned = BasePlatformAdapter.extract_media(content)
        assert all("\x00" not in p for p, _ in media)

    def test_log_safe_path_neutralises_line_breaks(self):
        forged = "/tmp/a.png\nWARNING forged second line"
        assert "\n" not in _log_safe_path(forged)
        # Unicode separators that split log lines are also neutralised.
        for sep in ("\u2028", "\u2029", "\x85"):
            assert sep not in _log_safe_path(f"/tmp/a{sep}b.png")

    def test_canonical_cache_roots_present(self):
        roots = {str(r).replace("\\", "/") for r in MEDIA_DELIVERY_SAFE_ROOTS}
        assert any(r.endswith("cache/images") for r in roots)
        assert any(r.endswith("cache/audio") for r in roots)
        assert any(r.endswith("cache/videos") for r in roots)
        assert any(r.endswith("cache/documents") for r in roots)
        assert any(r.endswith("cache/screenshots") for r in roots)
