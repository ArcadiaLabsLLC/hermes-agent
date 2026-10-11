"""Opt-in receipt of every git a test runs against the checkout itself (design sweep D3.16).

A gate run left a zero-byte ``index.lock`` in its worktree. ``GIT_OPTIONAL_LOCKS=0``
(the root ``conftest.py``) removes the opportunistic-refresh mechanism; this
receipt NAMES the tests that still run git with the checkout as its directory,
so each can be pointed at a temp repo. With ``HERMES_TEST_GIT_AUDIT=1`` (the
bundled runner's ``--git-audit`` sets it for its children), a Python audit hook
on ``subprocess.Popen`` appends one JSON line per such call —
``{"file", "nodeid", "argv", "cwd"}`` — to ``.pytest_cache/hermes_git_in_checkout.jsonl``
under the session's rootdir. A git whose directory (``cwd``, then ``-C``)
resolves outside the checkout (a ``tmp_path`` repo) is not recorded. It is a
negative inventory and over-approximates: every verb is recorded, lock-taking
or not; ``os.system`` and ``os.spawn*`` are not seen.

Off (the default), nothing is installed: an audit hook cannot be removed, so it
is added only when asked for.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

GIT_AUDIT_ENV = "HERMES_TEST_GIT_AUDIT"
RECEIPT = Path(".pytest_cache") / "hermes_git_in_checkout.jsonl"
CHECKOUT = Path(__file__).resolve().parents[2]

_state: dict = {"nodeid": None, "receipt": None}


def _argv(args) -> list[str]:
    """The audit event's argv as a list. On Windows ``Popen`` audits the command
    LINE (``list2cmdline`` ran first), so a string is split back, quotes dropped."""

    if isinstance(args, (str, bytes, os.PathLike)):
        return [token.strip('"') for token in shlex.split(os.fsdecode(args), posix=False)]
    return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in args]


def git_directory(argv: list[str], cwd) -> Path | None:
    """The directory a ``git`` argv runs in (``cwd``, then every ``-C``), or None when not git."""

    if not argv or Path(argv[0]).name.lower() not in ("git", "git.exe"):
        return None
    where = Path(os.fsdecode(cwd)) if cwd is not None else Path.cwd()
    for flag, value in zip(argv[1:], argv[2:]):
        if flag == "-C":
            where = where / value
    return where


def in_checkout(path: Path, checkout: Path = CHECKOUT) -> bool:
    try:
        path.resolve().relative_to(checkout.resolve())
    except (OSError, ValueError):
        return False
    return True


def _hook(event: str, args) -> None:
    if event != "subprocess.Popen" or _state["receipt"] is None:
        return
    try:
        _executable, popen_args, cwd, _env = args
        argv = _argv(popen_args)
        where = git_directory(argv, cwd)
        if where is None or not in_checkout(where):
            return
        nodeid = _state["nodeid"] or "<outside a test>"
        line = {"file": nodeid.split("::", 1)[0], "nodeid": nodeid, "argv": argv, "cwd": str(where)}
        with open(_state["receipt"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
    except Exception:  # noqa: BLE001 — an audit hook must never break the call it watches
        return


@pytest.hookimpl(specname="pytest_configure")
def pytest_configure_git_audit(config):  # noqa: D401 — pytest hook
    if os.environ.get(GIT_AUDIT_ENV) != "1" or _state["receipt"] is not None:
        return
    receipt = Path(str(config.rootpath)) / RECEIPT
    receipt.parent.mkdir(parents=True, exist_ok=True)
    _state["receipt"] = receipt
    sys.addaudithook(_hook)


@pytest.hookimpl(specname="pytest_runtest_protocol", hookwrapper=True)
def pytest_runtest_protocol_git_audit(item, nextitem):  # noqa: D401 — pytest hook
    _state["nodeid"] = item.nodeid
    try:
        yield
    finally:
        _state["nodeid"] = None
