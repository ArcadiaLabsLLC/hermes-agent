"""A bundled YAML file is parsed once per test process, not once per test (suite speed, lane w2-speed-b).

Upstream re-parses unchanging files that ship in the checkout: ``agent/i18n._load_bundled`` parses
``locales/<lang>.yaml`` (260-330 KB) once per ``(HERMES_HOME, lang)`` and every test has its own home;
the plugin stack parses each ``plugin.yaml`` per discovery, and ``load_gateway_config`` re-reads every
platform manifest per profile scope. The test venv's ruamel has no C parser, so each locale parse is
~0.65 s (``Harness_Brain/20 — Active Initiatives/r-perf-2026-10-17.md`` § h4-hotpath: 23.8% and
16.6% of 3,668 profiled call-phase seconds).

What is kept: the parsed document of a file STREAM handed to ``hermes_yaml.safe_load`` whose file lives
inside this checkout, keyed on ``(path, mtime_ns, size, encoding)``; a hit returns a deep copy, so a
caller that mutates its result never reaches the next caller. Strings, streams outside the checkout
(every test home and ``tmp_path``), and a stream not at offset 0 go to the real parser: a test that
writes a YAML file writes it under its own temp root, where a same-size rewrite inside one clock tick
could otherwise hit a stale entry. A parse that raises is not kept. No upstream file changes;
production parses as before (the upstream-owned rows ``RT-I18N-BUNDLED-PER-HOME`` and the platform
registry evidence name it).

Installed by the autouse ``_bundled_parse_memo`` (re-exported by ``conftest_plugin``) once
``hermes_yaml`` is imported; the wrapper stays for the process.
"""

from __future__ import annotations

import copy
import os
import sys
import threading
from pathlib import Path

import pytest

_REPO_ROOT = os.path.normcase(str(Path(__file__).resolve().parents[2])) + os.sep
_MARK = "_fork_bundled_parse_memo"
_MEMO: dict[tuple, object] = {}
_LOCK = threading.Lock()


def _bundled_key(stream) -> tuple | None:
    """The memo key for a stream over a checkout file at offset 0, else None (parse for real)."""
    if isinstance(stream, (str, bytes)):
        return None
    name = getattr(stream, "name", None)
    if not isinstance(name, str):
        return None
    path = os.path.normcase(os.path.abspath(name))
    if not path.startswith(_REPO_ROOT):
        return None
    try:
        if stream.tell() != 0:
            return None
        st = os.fstat(stream.fileno())
    except (OSError, ValueError, AttributeError):
        return None
    return (path, st.st_mtime_ns, st.st_size, getattr(stream, "encoding", None))


def _memoized_safe_load(real):
    def safe_load(stream):
        key = _bundled_key(stream)
        if key is None:
            return real(stream)
        with _LOCK:
            hit = _MEMO.get(key, _MEMO)
        if hit is not _MEMO:
            return copy.deepcopy(hit)
        data = real(stream)
        with _LOCK:
            _MEMO[key] = copy.deepcopy(data)
        return data

    safe_load.__wrapped__ = real
    setattr(safe_load, _MARK, True)
    return safe_load


def install_if_imported() -> bool:
    """Wrap ``hermes_yaml.safe_load`` once ``hermes_yaml`` is imported (idempotent)."""

    module = sys.modules.get("hermes_yaml")
    if module is None:
        return False
    if not getattr(module.safe_load, _MARK, False):
        module.safe_load = _memoized_safe_load(module.safe_load)
    return True


@pytest.fixture(autouse=True)
def _bundled_parse_memo():
    """Autouse: bundled YAML files parse once per test process once ``hermes_yaml`` is imported."""

    install_if_imported()
    yield
