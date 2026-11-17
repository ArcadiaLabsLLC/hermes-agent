"""Android Pillow's image libraries load by path before Pillow (row RT-PHONE-PILLOW-ANDROID).

Seen on the x86_64 emulator 2026-11-17: without this, ``PIL.Image`` fails with ``library "libtiff.so"
not found``; with every ``opt/lib`` library loaded first by path, Pillow imports and round-trips
JPEG, PNG, TIFF and WebP. These pin the loader's decisions with a fake ``dlopen``.
"""

from __future__ import annotations

import logging

import pytest

from agent_runtime import phone_native_libs


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(phone_native_libs, "_loaded", None)


def _site(tmp_path, *names):
    lib = tmp_path / "site" / "opt" / "lib"
    lib.mkdir(parents=True)
    for name in names:
        (lib / name).write_bytes(b"\x7fELF")
    (lib / "libjpeg.a").write_bytes(b"!<arch>")
    return [str(tmp_path / "site"), str(tmp_path / "elsewhere")]


def _loader(needs):
    """A fake dlopen: a library loads only once every library it needs has loaded."""
    loaded = []

    def load(path):
        name = path.replace("\\", "/").rsplit("/", 1)[1]
        missing = [n for n in needs.get(name, ()) if n not in loaded]
        if missing:
            raise OSError(f'dlopen failed: library "{missing[0]}" not found')
        loaded.append(name)

    return load, loaded


def test_every_library_loads_whatever_order_the_folder_lists_them(tmp_path):
    # Flet's set happens to list each library after the ones it needs; ``libarchive.so`` sorts before
    # ``libzstd.so`` and needs it, so a single pass in folder order would leave it unloaded.
    paths = _site(tmp_path, "libjpeg.so", "libtiff.so", "libarchive.so", "libzstd.so")
    load, loaded = _loader({"libtiff.so": ["libjpeg.so"], "libarchive.so": ["libzstd.so"]})
    names = phone_native_libs.load_phone_native_libs(platform="android", paths=paths, loader=load)
    assert sorted(names) == ["libarchive.so", "libjpeg.so", "libtiff.so", "libzstd.so"]
    assert loaded.index("libjpeg.so") < loaded.index("libtiff.so")
    assert loaded.index("libzstd.so") < loaded.index("libarchive.so")


def test_off_android_nothing_loads(tmp_path):
    paths = _site(tmp_path, "libjpeg.so")
    load, loaded = _loader({})
    for platform in ("win32", "linux", "darwin", "ios"):
        assert phone_native_libs.load_phone_native_libs(platform=platform, paths=paths, loader=load) == []
    assert loaded == []


def test_a_library_that_never_loads_is_named_and_the_rest_still_load(tmp_path, caplog):
    paths = _site(tmp_path, "libjpeg.so", "libtiff.so")
    load, loaded = _loader({"libtiff.so": ["libz-missing.so"]})
    with caplog.at_level(logging.WARNING, logger=phone_native_libs.__name__):
        names = phone_native_libs.load_phone_native_libs(platform="android", paths=paths, loader=load)
    assert names == ["libjpeg.so"]
    assert "libtiff.so did not load" in caplog.text and "libz-missing.so" in caplog.text


def test_it_loads_once_per_process(tmp_path):
    paths = _site(tmp_path, "libjpeg.so")
    load, loaded = _loader({})
    phone_native_libs.load_phone_native_libs(platform="android", paths=paths, loader=load)
    phone_native_libs.load_phone_native_libs(platform="android", paths=paths, loader=load)
    assert loaded == ["libjpeg.so"]
