"""pm/downloader builds its HTTPS opener on the first request, not at import.

``ssl.create_default_context()`` opens ``SSLKEYLOGFILE``. With the opener built
at import, a key-log path in a missing directory made ``import pm.downloader``
raise, and a device or an unread pipe aborted or stalled every CLI start that
imports the module, including commands that never download.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _import_downloader(env_extra: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_extra}
    return subprocess.run(
        [sys.executable, "-c", "import pm.downloader as d; print(type(d._OPENER).__name__)"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.timeout(90)
def test_a_bad_key_log_target_does_not_break_the_import(tmp_path):
    missing = tmp_path / "no-such-dir" / "keys.log"
    proc = _import_downloader({"SSLKEYLOGFILE": str(missing)})
    assert proc.returncode == 0, proc.stderr
    assert not missing.parent.exists()


def test_the_opener_is_built_once_on_first_use(monkeypatch):
    import urllib.request

    from pm import downloader

    built = []
    real = urllib.request.build_opener

    def counting(*handlers):
        built.append(handlers)
        return real(*handlers)

    lazy = downloader._LazyOpener()
    monkeypatch.setattr(urllib.request, "build_opener", counting)
    assert built == []
    for _ in range(2):
        with pytest.raises(Exception):
            lazy.open("https://127.0.0.1:1/", timeout=0.5)
    assert len(built) == 1
