"""Fork-owned half of ``tests/plugins/platforms/photon/test_sidecar_paths.py``.

Upstream's ``test_adapter_import_does_not_resolve_sidecar_dir`` calls ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a skip row in
``tests/_downstream/id_markers.py``. This is the same test with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import plugins.platforms.photon.sidecar_paths as sidecar_paths


def test_adapter_import_does_not_resolve_sidecar_dir(monkeypatch) -> None:
    """Importing the adapter must not probe the filesystem or mirror files.

    resolve_sidecar_dir() touch/unlink-probes the source tree and may copy
    files to HERMES_HOME; the adapter and CLI resolve lazily on first use so
    a bare import (plugin discovery, `hermes --help`, test collection) has
    no filesystem side effects.
    """
    import importlib

    from plugins.platforms.photon import adapter as photon_adapter
    from plugins.platforms.photon import cli as photon_cli

    def _boom(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("resolve_sidecar_dir called at import time")

    monkeypatch.setattr(sidecar_paths, "_SIDECAR_DIR", None)
    try:
        # SCOPED (EG-0.1 / ML-4). The resolver stub has to be gone before the
        # restoring reloads in the ``finally`` — otherwise they re-import
        # against ``_boom`` — and those reloads must still run when an
        # assertion above fails. So the context sits INSIDE the try and the
        # reloads stay in the finally, where a mid-test ``monkeypatch.undo()``
        # used to sit unwinding the whole shared instance.
        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(sidecar_paths, "resolve_sidecar_dir", _boom)
            importlib.reload(photon_adapter)
            importlib.reload(photon_cli)
            # Nothing resolved yet.
            assert sidecar_paths._SIDECAR_DIR is None
            # First real use resolves (and would call resolve_sidecar_dir).
            with pytest.raises(AssertionError, match="import time"):
                photon_adapter._sidecar_dir()
            # A monkeypatched _SIDECAR_DIR (the pattern existing tests use) is
            # honored without touching the resolver.
            patched.setattr(sidecar_paths, "_SIDECAR_DIR", Path("/tmp/x"))
            assert photon_adapter._sidecar_dir() == Path("/tmp/x")
            assert photon_adapter._npm_error_log() == Path("/tmp/x/.photon-npm-error.log")
    finally:
        # Restore real bindings for any later test importing these modules.
        importlib.reload(photon_adapter)
        importlib.reload(photon_cli)
