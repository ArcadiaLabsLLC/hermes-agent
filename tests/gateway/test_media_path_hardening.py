"""Media delivery hardening: $HOME denylist root, backslash terminator, NUL paths."""

from pathlib import Path

from gateway.platforms import base
from gateway.platforms.base import MEDIA_TAG_CLEANUP_RE, BasePlatformAdapter

BS = chr(92)


def test_denylist_home_follows_home_env(tmp_path, monkeypatch):
    home = tmp_path / "operator-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile-home"))
    denied = base._media_delivery_denied_paths()
    assert home / ".ssh" in denied


def test_backslash_terminates_a_media_tag_path():
    text = "see MEDIA:C:" + BS + "out" + BS + "a.png" + BS + "n done"
    assert [m.group("path") for m in MEDIA_TAG_CLEANUP_RE.finditer(text)] == [
        "C:" + BS + "out" + BS + "a.png"
    ]
    media, cleaned = BasePlatformAdapter.extract_media(text)
    assert [p for p, _ in media] == ["C:" + BS + "out" + BS + "a.png"]
    assert "MEDIA:" not in cleaned


def test_nul_path_is_dropped():
    media, cleaned = BasePlatformAdapter.extract_media("MEDIA:/tmp/x" + chr(0) + "y.png ok")
    assert media == []


def test_plain_path_still_delivered():
    """Positive control for the NUL case: the same tag without NUL delivers."""
    media, _ = BasePlatformAdapter.extract_media("MEDIA:/tmp/xy.png ok")
    assert [p for p, _ in media] == ["/tmp/xy.png"]
