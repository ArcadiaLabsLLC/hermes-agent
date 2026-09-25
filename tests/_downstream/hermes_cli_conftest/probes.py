"""Every host probe the registry and the prerequisite guards consult.

Each answers once per process: the two prerequisite probes behind
``functools.cache`` (and probed LAZILY, only when a file that needs them is
collected), the registry probes behind their own caches. They spawn ``node``,
open a socket, chmod a temp file or exec a shebang script -- I/O, so ``stores``.
The map is ``tests/_downstream/hermes_cli_conftest/__init__.py``.
"""

from __future__ import annotations

import functools
import importlib
import os
import sys

__layer__ = "stores"

_VITE8_NODE_FLOOR = "^20.19.0 || >=22.12.0"

def _node_version() -> str | None:
    """Return the host `node --version` string, or None when unavailable."""
    import subprocess as _sp

    try:
        out = _sp.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return (out.stdout or "").strip() or None


def _web_build_prereq_failure() -> str | None:
    """Return a skip reason when the host cannot build the web UI, else None."""
    raw = _node_version()
    if raw is None:
        return (
            "web-UI build prerequisite: node is not runnable on this host, so "
            f"`npm run build -w web` (vite ^8, requires Node {_VITE8_NODE_FLOOR}) "
            "cannot complete; this file executes that build for real."
        )
    try:
        major, minor, patch = (int(part) for part in raw.lstrip("v").split(".")[:3])
    except ValueError:
        return None  # unparseable: assume capable rather than guess
    ok = (
        (major == 20 and (minor, patch) >= (19, 0))
        or (major == 21)
        or (major == 22 and (minor, patch) >= (12, 0))
        or major > 22
    )
    if ok:
        return None
    return (
        f"web-UI build prerequisite: Node {_VITE8_NODE_FLOOR} required for "
        f"`npm run build -w web` (web/package.json pins vite ^8); found {raw}. "
        "This file drives the real build through an unstubbed subprocess.Popen, "
        "so it would block past the per-test timeout and kill the whole run."
    )


# Probed LAZILY, the first time an item of a file that needs it is collected,
# never at conftest import: this module is imported by every one of the ~1,260
# per-file processes under tests/hermes_cli, and only two files consult it.
# Measured 2026-09-24 (lane SPEED, `docs/agent-runtime-harness/planned/
# suite-cost-centres-2026-09-24.md`): the two import-time probes cost every
# hermes_cli process a `node --version` spawn and, on a host that drops SYN on
# 127.0.0.1:11434, a 2 s connect timeout — ~2.5 s x 1,260 files.
@functools.cache
def _web_build_prereq_reason() -> str | None:
    return _web_build_prereq_failure()

def _local_model_probe_failure() -> str | None:
    """Return a skip reason when 127.0.0.1:11434 neither answers nor refuses."""
    import socket as _socket

    try:
        conn = _socket.create_connection(("127.0.0.1", 11434), timeout=2.0)
    except (ConnectionRefusedError, OSError) as exc:
        if isinstance(exc, ConnectionRefusedError):
            return None  # fast refusal — the probes will fail fast too
        if not isinstance(exc, (TimeoutError, _socket.timeout)):
            return None  # some other immediate error — still fast
        return (
            "local-endpoint prerequisite: 127.0.0.1:11434 accepted neither a "
            "connection nor a refusal within 2s (the SYN is being dropped, not "
            "reset). AIAgent construction probes that endpoint over httpx, so "
            "this test would block past the per-test timeout and kill the "
            "whole run. Free the port or let it refuse to re-enable."
        )
    conn.close()
    return None


@functools.cache
def _local_model_probe_reason() -> str | None:
    """Lazy, once per process — see :func:`_web_build_prereq_reason`."""
    return _local_model_probe_failure()

_POSIX_MODE_BITS_PROBE = None


def _no_module(name: str):
    """Return a probe that is True while ``name`` cannot be imported.

    It really imports rather than asking ``find_spec``. ``find_spec("curses")``
    answers yes on Windows — the pure-Python package ships with CPython, and it
    is the ``_curses`` extension underneath that is missing, which only
    executing the module body discovers. The registry ledger caught exactly
    that mistake in this file on its first run, which is the point of having a
    ledger rather than a printed warning.
    """
    cached: list[bool] = []

    def _probe() -> bool:
        if not cached:
            try:
                importlib.import_module(name)
            except Exception:
                cached.append(True)
            else:
                cached.append(False)
        return cached[0]

    return _probe


def _no_posix_mode_bits() -> bool:
    """True where os.chmod cannot express an owner-only file mode.

    Measured, not assumed: NTFS records only FILE_ATTRIBUTE_READONLY, so
    chmod(0o600) reads back as 0o666. The probe performs the actual round trip
    rather than testing the platform name.
    """
    global _POSIX_MODE_BITS_PROBE
    if _POSIX_MODE_BITS_PROBE is None:
        import stat as _stat
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as _tmp:
            _probe_file = os.path.join(_tmp, "mode_probe")
            with open(_probe_file, "w", encoding="utf-8"):
                pass
            os.chmod(_probe_file, 0o600)
            _POSIX_MODE_BITS_PROBE = (
                _stat.S_IMODE(os.stat(_probe_file).st_mode) != 0o600
            )
    return _POSIX_MODE_BITS_PROBE


def _no_os_chown() -> bool:
    """True where os.chown is absent — the POSIX service-manager seam."""
    return not hasattr(os, "chown")


def _no_posix_wait_status() -> bool:
    """True where a raw wait status cannot be decoded.

    kanban_db._classify_worker_exit uses os.WIFEXITED / WEXITSTATUS /
    WIFSIGNALED, and the exit registry it reads is populated only by
    reap_worker_zombies, itself gated ``os.name != "nt"``.
    """
    return not hasattr(os, "WIFEXITED")


def _no_posix_privilege_api() -> bool:
    """True where os.geteuid is absent, so root/sudo branches are unreachable."""
    return not hasattr(os, "geteuid")


def _posix_only_branch() -> bool:
    """True where the code under test selects its non-POSIX arm.

    Used ONLY where the production code itself branches on ``sys.platform`` and
    the assertion pins the arm this host never takes — i.e. where the platform
    genuinely is the mechanism rather than a stand-in for one.
    """
    return sys.platform == "win32"


_SHEBANG_EXEC_PROBE = None


def _no_shebang_script_execution() -> bool:
    """True where the OS cannot spawn a ``#!``-prefixed script directly.

    The shebang is honoured by the kernel's exec, not by the file: Windows'
    CreateProcess has no equivalent, so ``subprocess.run([r"C:\\...\\hook.sh"])``
    raises ``OSError: [WinError 193] %1 is not a valid Win32 application`` no
    matter how the path is spelled. Interpreter-prefixed hook commands
    (``python C:\\...\\hook.py``) are unaffected and still run here — it is the
    bare-script spawn shape alone that is unavailable.

    Probed by performing the spawn, because there is no attribute to test for:
    the answer is a property of the loader, not of the standard library.
    """
    global _SHEBANG_EXEC_PROBE
    if _SHEBANG_EXEC_PROBE is None:
        import subprocess as _sp
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as _tmp:
            _script = os.path.join(_tmp, "shebang_probe.sh")
            with open(_script, "w", encoding="utf-8", newline="\n") as _fh:
                _fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(_script, 0o755)
            try:
                _sp.run([_script], capture_output=True, timeout=15)
            except OSError:
                _SHEBANG_EXEC_PROBE = True
            else:
                _SHEBANG_EXEC_PROBE = False
    return _SHEBANG_EXEC_PROBE


def _test_python_outside_project_venv() -> bool:
    """True where ``sys.executable`` is not under this checkout.

    ``update_cmd_windows._detect_venv_python_processes`` reports only processes
    whose exe lives under the project venv (or the checkout root), and the live
    venv-holder E2Es spawn their sleepers from ``sys.executable``. A shared test
    venv outside the checkout makes every sleeper invisible to the scan.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    try:
        Path(sys.executable).resolve().relative_to(root)
    except ValueError:
        return True
    return False


def _unelevated_windows_shell() -> bool:
    """True on a Windows shell without administrator rights (schtasks /Create refuses)."""
    import sys

    if sys.platform != "win32":
        return False
    import ctypes

    try:
        return not ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

