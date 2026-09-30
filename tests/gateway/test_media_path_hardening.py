"""Media delivery hardening: $HOME denylist root, backslash terminator, NUL paths."""

from pathlib import Path

from gateway.platforms import base
from gateway.platforms.base import MEDIA_TAG_CLEANUP_RE, BasePlatformAdapter

BS = chr(92)


def _isolate_hermes_root(tmp_path, monkeypatch):
    """The credential roots are module constants resolved at import; point them at a temp home
    so the denylist build never scans the machine's real Hermes profiles."""
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setattr(base, "_HERMES_HOME", hermes_home)
    monkeypatch.setattr(base, "_HERMES_ROOT", hermes_home)


def test_denylist_home_follows_home_env(tmp_path, monkeypatch):
    home = tmp_path / "operator-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile-home"))
    _isolate_hermes_root(tmp_path, monkeypatch)
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


def test_denylist_keeps_the_native_home_when_home_differs(tmp_path, monkeypatch):
    """Adding the operator ``$HOME`` must not drop the platform-native home's credential dirs."""
    native, configured = tmp_path / "native-home", tmp_path / "operator-home"
    real_expand = base.os.path.expanduser
    monkeypatch.setattr(base.os.path, "expanduser",
                        lambda p: str(native) + p[1:] if p.startswith("~") else real_expand(p))
    monkeypatch.setenv("HOME", str(configured))
    _isolate_hermes_root(tmp_path, monkeypatch)
    denied = base._media_delivery_denied_paths()
    assert native / ".ssh" in denied
    assert configured / ".ssh" in denied


def test_backslash_inside_a_windows_path_is_a_separator_not_a_terminator():
    """A directory named like a file (``album.png``, ``old.zip``) is still a directory."""
    for path in ("C:" + BS + "out" + BS + "album.png" + BS + "photo.jpg",
                 "C:" + BS + "old.zip" + BS + "v1.png" + BS + "report.pdf"):
        media, cleaned = BasePlatformAdapter.extract_media("MEDIA:" + path)
        assert media == [(path, False)]
        assert cleaned == ""


def test_dropped_nul_tag_is_still_removed_from_the_caption():
    media, cleaned = BasePlatformAdapter.extract_media("MEDIA:/tmp/x" + chr(0) + "y.png ok")
    assert media == []
    assert "MEDIA:" not in cleaned
    assert chr(0) not in cleaned
    assert cleaned == "ok"


def test_escaped_newline_before_the_next_tag_still_splits_the_two_paths():
    text = "MEDIA:C:" + BS + "out" + BS + "a.png" + BS + "nMEDIA:C:" + BS + "out" + BS + "b.png"
    media, _ = BasePlatformAdapter.extract_media(text)
    assert [p for p, _ in media] == ["C:" + BS + "out" + BS + "a.png", "C:" + BS + "out" + BS + "b.png"]
