"""scripts/check prints its results on a console whose encoding cannot spell them.

2026-10-12 reasoning-capability gate: every job ran, then ``main`` raised
``UnicodeEncodeError`` printing a tool's U+2717 on a Windows cp1252 console and the
receipt was lost. The results must survive the host's ordinary encoding.
"""

from __future__ import annotations

import io
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_CHECK = Path(__file__).resolve().parents[2] / "scripts" / "check"


def _load_check(monkeypatch):
    loader = SourceFileLoader("scripts_check_under_test", str(_CHECK))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    monkeypatch.setitem(sys.modules, loader.name, module)  # its @dataclass resolves the module
    loader.exec_module(module)
    return module


def _cp1252_console() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", write_through=True)


def test_a_failed_check_prints_its_receipt_on_a_cp1252_console(monkeypatch):
    check = _load_check(monkeypatch)
    out, err = _cp1252_console(), _cp1252_console()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(check, "_run_all", lambda args: {"ruff": (1, "\u2717 F401 unused import")})

    assert check.main(["--only", "ruff"]) == 1

    printed = out.buffer.getvalue().decode("cp1252")
    assert "=== ruff (failed) ===" in printed
    assert "\\u2717 F401 unused import" in printed
    assert "scripts/check: 1 checks, FAILED: ruff" in printed


def test_the_control_console_really_refuses_the_character():
    """Positive control: without the repair, this console raises on exactly that print."""
    console = _cp1252_console()
    try:
        print("\u2717", file=console)
    except UnicodeEncodeError:
        return
    raise AssertionError("a strict cp1252 console accepted U+2717; the test above proves nothing")
