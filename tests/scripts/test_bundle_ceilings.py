"""The D4 ceilings probe: the size it reports and the ready frame it times."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.bundle_ceilings import lzma_size, stt_latency, time_to_ready


def test_the_size_is_the_installed_bytes_and_a_deterministic_smaller_xz_count(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.py").write_bytes(b"print('hi')\n" * 1000)
    (tmp_path / "a" / "y.bin").write_bytes(bytes(range(256)) * 4)
    size = lzma_size([("app", tmp_path / "a")])
    assert size["installed_bytes"] == 12000 + 1024
    assert 0 < size["lzma_bytes"] < size["installed_bytes"]
    assert size == lzma_size([("app", tmp_path / "a")])  # deterministic


def _fake_core(tmp_path: Path, main_body: str) -> Path:
    core = tmp_path / "core"
    (core / "site-packages").mkdir(parents=True)
    pkg = core / "app" / "hermes_cli"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text(main_body, encoding="utf-8")
    return core


# The serve driver names `hermes harness serve`, so the guard refuses it (L8.34); here it runs
# under -I -S against _fake_core's stand-in hermes_cli, which boots nothing.
@pytest.mark.live_system_guard_bypass
def test_ready_is_timed_to_the_ready_frame_of_the_bundles_own_serve(tmp_path: Path):
    body = ("import json, sys\nassert sys.argv[1:] == ['harness', 'serve', '--ndjson'], sys.argv\n"
            "print('noise', flush=True)\nprint(json.dumps({'event': 'ready'}), flush=True)\nsys.stdin.read()\n")
    home = tmp_path / "home"
    home.mkdir()
    assert time_to_ready(Path(sys.executable), _fake_core(tmp_path, body), home, [], timeout=60) is not None


# The serve driver names `hermes harness serve`, so the guard refuses it (L8.34); here it runs
# under -I -S against _fake_core's stand-in hermes_cli, which boots nothing.
@pytest.mark.live_system_guard_bypass
def test_a_serve_that_never_reports_ready_reads_none(tmp_path: Path):
    body = "import json, sys\nprint(json.dumps({'event': 'starting'}), flush=True)\nsys.stdin.read()\n"
    home = tmp_path / "home"
    home.mkdir()
    assert time_to_ready(Path(sys.executable), _fake_core(tmp_path, body), home, [], timeout=3) is None


def test_no_model_is_reported_not_measured(tmp_path: Path):
    result = stt_latency(Path(sys.executable), tmp_path, [tmp_path], None, tmp_path / "a.wav", 2.0, tmp_path)
    assert result["measured"] is False and result["reason"] == "model_not_present"

