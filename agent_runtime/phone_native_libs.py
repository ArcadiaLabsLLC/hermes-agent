"""The phone's native image libraries: loaded by path before Pillow, on Android only.

Android's Pillow is Flet's prebuilt wheel (owner RULED 2026-11-17, row RT-PHONE-PILLOW-ANDROID;
pins in ``agent_runtime/bundle_profiles/phone_wheels.lock.json``). Its extension modules link
``libjpeg.so``, ``libtiff.so``, ``libfreetype.so`` and the libwebp set by bare name and carry no
``RUNPATH``; the four ``flet-lib*`` wheels install those libraries under ``site-packages/opt/lib``,
a folder Android's loader never searches. Seen on the x86_64 emulator 2026-11-17: importing
``PIL.Image`` fails with ``dlopen failed: library "libtiff.so" not found: needed by
.../PIL/_imaging...so``, and succeeds once each library is loaded by its full path first — the
loader then matches the later ``NEEDED`` entries by soname.

:func:`load_phone_native_libs` does that once per process. A library that needs another one still
unloaded fails and is retried after the rest, so no load order is written down. Off Android it
does nothing: desktop and iPhone Pillow wheels carry their own libraries.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

__layer__ = "lanes"

__all__ = ["LIBRARY_DIR", "load_phone_native_libs", "native_library_files"]

logger = logging.getLogger(__name__)

#: Where the ``flet-lib*`` wheels put their shared libraries, relative to a ``sys.path`` entry.
LIBRARY_DIR = Path("opt") / "lib"

_loaded: list[str] | None = None


def native_library_files(paths: list[str] | None = None) -> list[Path]:
    """Every ``*.so`` under ``<entry>/opt/lib`` for each ``sys.path`` entry, in path order."""
    found: list[Path] = []
    for entry in sys.path if paths is None else paths:
        folder = Path(entry or ".") / LIBRARY_DIR
        if folder.is_dir():
            found += sorted(p for p in folder.iterdir() if p.suffix == ".so" and p.is_file())
    return found


def load_phone_native_libs(*, platform: str | None = None, paths: list[str] | None = None,
                           loader=ctypes.CDLL) -> list[str]:
    """Load every library :func:`native_library_files` finds; -> the file names loaded.

    Android only (``platform`` overrides ``sys.platform`` for tests). Runs once per process; a
    library that still fails once no other one loads is logged with its error and left unloaded,
    so the Pillow import that needs it reports the missing name itself.
    """
    global _loaded
    if (platform or sys.platform) != "android":
        return []
    if _loaded is not None:
        return list(_loaded)
    pending = native_library_files(paths)
    loaded: list[str] = []
    errors: dict[str, str] = {}
    while pending:
        progress = False
        for path in list(pending):
            try:
                loader(str(path))
            except OSError as exc:
                errors[path.name] = str(exc)
                continue
            loaded.append(path.name)
            errors.pop(path.name, None)
            pending.remove(path)
            progress = True
        if not progress:
            break
    for path in pending:
        logger.warning("phone native library %s did not load: %s", path, errors.get(path.name, "unknown error"))
    _loaded = loaded
    return list(loaded)
