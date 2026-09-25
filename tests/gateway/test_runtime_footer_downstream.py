"""Fork twins of three upstream ``tests/gateway/test_runtime_footer.py`` cases.

Upstream patches only ``HOME`` and spells paths as POSIX literals; on Windows
``ntpath.expanduser`` prefers ``USERPROFILE`` and ``_home_relative_cwd``
rebuilds natively, so those cases are strict xfails by id
(``tests/_downstream/id_markers.py``). These twins hold the same guarantees
with the home redirected on every platform and the separator taken from ``os``.
"""

from __future__ import annotations

import os

from gateway.runtime_footer import _home_relative_cwd, format_runtime_footer
from tests._home_env import point_home_at


def test_home_relative_cwd_collapses_home(tmp_path, monkeypatch):
    point_home_at(monkeypatch, tmp_path)
    sub = tmp_path / "projects" / "hermes"
    sub.mkdir(parents=True)
    assert _home_relative_cwd(str(sub)) == os.path.join("~", "projects", "hermes")


def test_format_footer_all_fields(monkeypatch, tmp_path):
    point_home_at(monkeypatch, tmp_path)
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path / "projects" / "hermes"))
    (tmp_path / "projects" / "hermes").mkdir(parents=True)
    out = format_runtime_footer(
        model="openai/gpt-5.4",
        context_tokens=68_000,
        context_length=100_000,
        cwd=None,  # falls back to TERMINAL_CWD env var
        fields=("model", "context_pct", "cwd"),
    )
    assert out == "gpt-5.4 · 68% · " + os.path.join("~", "projects", "hermes")


def test_format_footer_skips_missing_context_length():
    cwd = os.path.abspath(os.path.join(os.sep, "wd"))
    out = format_runtime_footer(
        model="openai/gpt-5.4",
        context_tokens=500,
        context_length=None,
        cwd=cwd,
        fields=("model", "context_pct", "cwd"),
    )
    assert "%" not in out
    assert "gpt-5.4" in out
    assert cwd in out


def test_format_footer_latency_in_field_order(monkeypatch, tmp_path):
    point_home_at(monkeypatch, tmp_path)
    out = format_runtime_footer(
        model="openai/gpt-5.4",
        context_tokens=68_000,
        context_length=100_000,
        cwd=str(tmp_path),
        turn_seconds=65.0,
        fields=("model", "context_pct", "latency", "cwd"),
    )
    assert out == "gpt-5.4 · 68% · 1m05s · ~"
