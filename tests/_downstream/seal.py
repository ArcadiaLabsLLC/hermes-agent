"""The ONE seal over what a hermes test may see of the machine it runs on, and what it may leave
running after it ends (row FH-ONE-TEST-SEAL, Eternia task TASK-TESTS-SEALED-FROM-THE-MACHINE; the
Eternia half is ``EterniaLauncher/test/support/test_seal.dart``, the same four parts).

(a) Environment: ``tests/conftest.py::_hermetic_environment`` already blanks credential and
    behavioural variables per test, and ``scripts/fork_test_env.txt`` is the ``env -i`` allowlist
    ``scripts/run_tests.sh`` forwards. The seal adds nothing here.
(b) Home: ``HERMES_HOME`` is a per-test folder (``_hermetic_environment``) and the upstream
    platform default is pinned there too. The fork's one resolver for the platform root,
    ``agent_runtime.host_tools.platform_default_root``, read ``Path.home()`` straight through, so
    ``agent_runtime.resolution`` handed every test the real ``~/.hermes`` (seen 2026-11-16). The
    seal points it at the test's own folder by the same rule as the upstream pin: a root under
    the native parent moves to ``tmp_path``; a test that moves ``HOME`` or ``LOCALAPPDATA`` itself
    still gets its own layout. Fork modules read it through the module, never a bound name, so
    the pin reaches them (``tests/_downstream/test_seal.py`` refuses a bound import).
(c) Launch arguments: ``sys.argv`` is ``[argv[0]]`` for the length of each test and restored
    after. pytest's own arguments are not the program's: ``cmd_update``'s retarget re-ran them as
    ``hermes_cli.main`` once (``conftest_plugin._no_owning_install_retarget``).
(d) Leftovers: a thread or a ``subprocess.Popen`` child that repository code starts during a
    test (its fixtures included, never a module- or session-scoped fixture's) and that is still
    running after every tear-down is named with the line that started it. In the folders
    ``tests/_downstream/test_seal_sealed_roots.txt`` lists (folders whose run was read clean) it
    fails the test after a short grace, and a leftover child is killed; elsewhere it is one
    ``[test-seal] leftover`` line in the run's summary and is left alone (a shared server a later
    test reuses may be one) until its folder is read and added. The list only grows: it is the
    shrink-only baseline of known leakers, stated as the folders that are NOT on it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import hermes_constants

#: the folders (or single test files) whose tests fail on a leftover thread or child (see (d)); one
#: repo-relative folder or file per line, ``#`` starts a comment
SEALED_ROOTS_PATH = Path(os.environ.get("HERMES_TEST_SEAL_ROOTS") or Path(__file__).with_name("test_seal_sealed_roots.txt"))
# (``HERMES_TEST_SEAL_ROOTS`` names another list: the seal's own test seals a planted folder with it.)
#: the line prefix of a leftover report outside a sealed folder
LEFTOVER_REPORT = "[test-seal] leftover"
#: how long a leftover in a sealed folder may take to finish on its own before it fails the test
GRACE_SECONDS = 2.0

_REPO = Path(__file__).resolve().parents[2]
_NOT_REPO = tuple(
    {str(Path(p).resolve()) for p in (sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["purelib"],
                                      sysconfig.get_paths()["platlib"], sys.prefix, sys.base_prefix)}
)
#: the platform-default root's parent at import, before any test moves HOME (the upstream pin's rule)
_NATIVE_PARENT = hermes_constants._get_platform_default_hermes_home().parent


def _read_sealed_roots() -> tuple[str, ...]:
    roots = []
    for line in SEALED_ROOTS_PATH.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            # a ``.py`` entry seals that one file of a folder not yet read whole
            roots.append(entry if entry.endswith(".py") else entry.rstrip("/") + "/")
    return tuple(roots)


SEALED_ROOTS = _read_sealed_roots()


@dataclass
class _Running:
    """The test now running: what repository code started during it, and where."""

    sealed: bool
    threads: list = field(default_factory=list)
    children: list = field(default_factory=list)


_current: list[_Running] = []
_broad_fixture_depth = [0]
_reports: list[str] = []


#: test infrastructure that wraps a spawn (``tests/_fixtures/live_system_guard.py`` wraps ``Popen``):
#: the site named is the frame that called it
_INFRA_DIRS = (str(_REPO / "tests" / "_fixtures"), str(_REPO / "tests" / "_downstream"))


def _is_test_infra(name: str) -> bool:
    return name.startswith(_INFRA_DIRS[0]) or str(Path(name).parent) == _INFRA_DIRS[1]


def _start_site() -> str | None:
    """The first repository frame on the stack (``file:line``), or None when no repository code
    asked: a thread pytest or a plugin starts for itself is not the test's."""
    frame = sys._getframe(2)
    while frame is not None:
        name = frame.f_code.co_filename
        if name.startswith(str(_REPO)) and not name.startswith(_NOT_REPO) and not _is_test_infra(name):
            try:
                return f"{Path(name).relative_to(_REPO).as_posix()}:{frame.f_lineno}"
            except ValueError:
                return f"{name}:{frame.f_lineno}"
        frame = frame.f_back
    return None


def _tracking() -> _Running | None:
    return _current[0] if _current and not _broad_fixture_depth[0] else None


_real_thread_start = threading.Thread.start
_real_popen_init = subprocess.Popen.__init__


def _tracked_thread_start(self, *args, **kwargs):
    _real_thread_start(self, *args, **kwargs)
    running = _tracking()
    if running is not None:
        site = _start_site()
        if site is not None:
            running.threads.append((self, site))


def _tracked_popen_init(self, *args, **kwargs):
    _real_popen_init(self, *args, **kwargs)
    running = _tracking()
    if running is not None:
        site = _start_site()
        if site is not None:
            running.children.append((self, site))


def install() -> None:
    """Process-wide, at plugin import: count the threads and children tests start (d)."""
    threading.Thread.start = _tracked_thread_start
    subprocess.Popen.__init__ = _tracked_popen_init


def is_sealed(relpath: str) -> bool:
    return relpath.startswith(SEALED_ROOTS)


def leftovers(running: _Running, *, grace: float) -> list[str]:
    """Each thread or child of *running* still alive once *grace* seconds are spent waiting for it."""
    deadline = time.monotonic() + grace
    found = []
    for thread, site in running.threads:
        if thread.is_alive():
            thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            found.append(f"thread {thread.name!r} started at {site}")
    for child, site in running.children:
        if child.poll() is None:
            try:
                child.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        if child.poll() is None:
            found.append(f"child pid {child.pid} ({_argv0(child)}) started at {site}")
    return found


def _argv0(child) -> str:
    args = child.args
    first = args if isinstance(args, (str, bytes)) else (args[0] if args else "")
    return Path(str(first)).name or str(first)


def _kill_children(running: _Running) -> None:
    for child, _site in running.children:
        if child.poll() is None:
            child.kill()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                pass


@pytest.fixture(autouse=True)
def _test_seal(monkeypatch, tmp_path, _hermetic_environment):
    """(b) and (c), per test."""
    from agent_runtime import host_tools

    unsealed = host_tools.platform_default_root

    def sealed_platform_default_root(env=None):
        root = unsealed(env)
        return tmp_path / root.name if root.parent == _NATIVE_PARENT else root

    monkeypatch.setattr(host_tools, "platform_default_root", sealed_platform_default_root)
    monkeypatch.setattr(sys, "argv", list(sys.argv[:1]))


@pytest.hookimpl(specname="pytest_fixture_setup", wrapper=True)
def pytest_fixture_setup_test_seal(fixturedef, request):
    broad = fixturedef.scope != "function"
    if broad:
        _broad_fixture_depth[0] += 1
    try:
        return (yield)
    finally:
        if broad:
            _broad_fixture_depth[0] -= 1


@pytest.hookimpl(specname="pytest_runtest_setup", wrapper=True, tryfirst=True)
def pytest_runtest_setup_test_seal(item):
    _current[:] = [_Running(sealed=is_sealed(_relpath(item)))]
    return (yield)


@pytest.hookimpl(specname="pytest_runtest_teardown", wrapper=True, tryfirst=True)
def pytest_runtest_teardown_test_seal(item, nextitem):
    try:
        result = yield
    finally:
        running = _current.pop() if _current else None
    if running is None:
        return result
    found = leftovers(running, grace=GRACE_SECONDS if running.sealed else 0.0)
    if not found:
        return result
    if running.sealed:
        _kill_children(running)
        pytest.fail(
            f"{LEFTOVER_REPORT} in a sealed folder ({SEALED_ROOTS_PATH.name}): "
            + "; ".join(found) + f" — still running {GRACE_SECONDS:g}s after {item.nodeid} ended",
            pytrace=False,
        )
    _reports.extend(f"{LEFTOVER_REPORT}: {item.nodeid}: {line}" for line in found)
    return result


@pytest.hookimpl(specname="pytest_terminal_summary")
def pytest_terminal_summary_test_seal(terminalreporter):
    if _reports:
        terminalreporter.section("test-seal")
        for line in _reports:
            terminalreporter.write_line(line)


def _relpath(item) -> str:
    try:
        return Path(str(item.path)).resolve().relative_to(_REPO).as_posix()
    except ValueError:
        return str(item.path)
